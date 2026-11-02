"""Sigma calibration, the gain map, the directional estimate and processed noise (WO-006). Synthetic data only."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from scipy import ndimage, optimize

from vesuvius_challenge import experiments, lpsf
from vesuvius_challenge import synthetic as syn

SHEET = syn.Sheet(snr=6.0)


def tilted_stack(texture: syn.Texture, theta: float = 5.0, length: int = 288, sheet: syn.Sheet = SHEET, seed: int = 4):
    points = syn.tilted_points((length, 64), theta, 0.0)
    return syn.make_case(None, texture, sheet, 21, 1.0, seed=seed, points=points)


def fibres(angle: float, **kwargs) -> dict:
    """Texture settings with fibres at ``angle`` to the tilt in the mesh frame."""
    return {"orientation_deg": syn.GENERIC_ROTATION_DEG + angle, **kwargs}


# Sigma calibration


def test_calibrated_variance_is_the_stated_formula() -> None:
    assert lpsf.calibrated_variance(4.0, 3.0, 2.0, 0.5) == pytest.approx(4 * 4 + (0.5 * 3) ** 2)


def test_apply_calibration_adds_the_floor_along_every_direction() -> None:
    cov = np.array([[2.0, 0.5], [0.5, 1.0]])
    grad = np.array([3.0, 4.0])
    out = lpsf.apply_calibration(cov, grad, 2.0, 0.1)
    assert out == pytest.approx(4 * cov + 0.25 * np.eye(2))


def test_defaults_leave_sigma_unchanged() -> None:
    case = tilted_stack(syn.Texture())
    field = lpsf.estimate(case.layers, 1.0, metric=case.metric)
    assert field.calibrated_grad_cov == pytest.approx(field.grad_cov)
    assert field.information is None
    assert field.grad_information is None


def test_calibrate_recovers_a_known_inflation() -> None:
    rng = np.random.default_rng(1)
    variance = rng.uniform(0.5, 2.0, 40_000)
    error = 2.5 * np.sqrt(variance) * rng.standard_normal(variance.size)
    fit = lpsf.calibrate(error, variance, np.zeros(variance.size), np.zeros(variance.size, dtype=int))
    # Coverage of 0.94 instead of 0.95 sets kappa a little below 2.5.
    assert fit.kappa == pytest.approx(2.5, abs=0.15)
    assert fit.floor == 0.0


def test_calibrate_uses_the_floor_for_error_proportional_to_g() -> None:
    rng = np.random.default_rng(2)
    magnitude = rng.uniform(1.0, 2.0, 40_000)
    variance = np.full(magnitude.size, 1e-6)
    error = 0.1 * magnitude * rng.standard_normal(magnitude.size)
    fit = lpsf.calibrate(error, variance, magnitude, np.zeros(magnitude.size, dtype=int))
    assert fit.floor == pytest.approx(0.1, abs=0.02)


def test_every_stratum_counts_the_same_however_many_patches_it_has() -> None:
    rng = np.random.default_rng(3)
    small = 2.0 * rng.standard_normal(2_000)
    large = 4.0 * rng.standard_normal(38_000)
    error = np.concatenate([small, large])
    strata = np.array(["small"] * small.size + ["large"] * large.size)
    fit = lpsf.calibrate(error, np.ones(error.size), np.zeros(error.size), strata)
    assert 2.0 < fit.kappa < 4.0, "a size-weighted fit would land near 4"


# Decorrelation gain


def peak_shift(tensor: np.ndarray, length: float, theta: float, tilt: np.ndarray) -> np.ndarray:
    """Slow reference: maximise the correlation model numerically for one layer pair, Delta = 1."""

    def negative(shift: np.ndarray) -> float:
        tan = np.tan(theta)
        x = shift - tan * tilt  # in-plane offset between the matched points in the sheet
        z = 1.0 + float(shift @ tilt) * tan  # their depth offset
        return 0.5 * float(x @ tensor @ x) + z**2 / length**2

    return optimize.minimize(negative, np.zeros(2), tol=1e-12).x


@settings(max_examples=60, deadline=None)
@given(
    st.floats(1.2, 5.0),
    st.floats(1.0, 2.0),
    st.floats(4.0, 30.0),
    st.floats(0.0, np.pi),
    st.floats(0.0, np.pi),
)
def test_gain_tensor_matches_the_correlation_maximum(along, across, length, fibre, azimuth) -> None:
    """``I - (2 / L^2) T^-1``, as in the `gain_map` docstring, against brute force at small tilt."""
    e = np.array([np.cos(fibre), np.sin(fibre)])
    n = np.array([-e[1], e[0]])
    tensor = np.outer(e, e) / along**2 + np.outer(n, n) / across**2
    tilt = np.array([np.cos(azimuth), np.sin(azimuth)])
    theta = np.deg2rad(0.05)
    expected = (np.eye(2) - 2 / length**2 * np.linalg.inv(tensor)) @ tilt * np.tan(theta)
    assert peak_shift(tensor, length, theta, tilt) == pytest.approx(expected, abs=2e-3 * np.tan(theta) * (1 + along**2))


def test_fit_depth_length_recovers_l_through_a_noise_nugget() -> None:
    lags = np.array([1.0, 2.0, 3.0])
    r = (0.9 * np.exp(-(lags**2) / 4.3**2)).reshape(3, 1, 1)
    assert lpsf.fit_depth_length(r, lags)[0, 0] == pytest.approx(4.3)


def test_fit_depth_length_reports_no_decorrelation_and_missing_data() -> None:
    lags = np.array([1.0, 2.0, 3.0])
    flat = np.array([[0.9], [0.9], [0.9]])
    assert np.isinf(lpsf.fit_depth_length(flat, lags)[0])
    short = np.array([[0.9], [0.01], [np.nan]])
    assert np.isnan(lpsf.fit_depth_length(short, lags)[0])


def test_a1_texture_predicts_a_gain_near_one() -> None:
    case = tilted_stack(syn.Texture(**fibres(0.0)))
    field = lpsf.estimate(case.layers, 1.0, metric=case.metric)
    gains = lpsf.gain_map(case.layers, field)
    assert np.nanmedian(gains.gain[field.valid]) > 0.95
    assert np.nanmedian(gains.length[field.valid]) > 30


def test_realistic_texture_measures_the_set_lengths() -> None:
    texture = syn.realistic_texture(6.0, corr_length=4.3, **fibres(0.0))
    case = tilted_stack(texture)
    field = lpsf.estimate(case.layers, 1.0, metric=case.metric)
    gains = lpsf.gain_map(case.layers, field)
    ok = field.valid
    assert np.median(gains.length[ok]) == pytest.approx(4.3, rel=0.2)
    assert np.median(gains.ell_across[ok]) == pytest.approx(8 / (2 * np.pi), rel=0.15)
    assert np.median(gains.ell_along[ok]) > 2 * np.median(gains.ell_across[ok])
    angle = np.rad2deg(np.median(np.abs(np.mod(gains.fibre_angle[ok] + np.pi / 2, np.pi) - np.pi / 2)))
    assert angle < 12, "the fibres were set along the tilt, +u"


def test_gain_map_predicts_the_sign_reversal_along_fibres_not_across() -> None:
    results = {}
    for angle in (0.0, 90.0):
        texture = syn.realistic_texture(6.0, corr_length=4.3, **fibres(angle))
        case = tilted_stack(texture, length=416)
        field = lpsf.estimate(case.layers, 1.0, metric=case.metric)
        results[angle] = np.nanmedian(lpsf.gain_map(case.layers, field).gain[field.valid])
    assert results[0.0] < 0.1
    assert results[90.0] > results[0.0] + 0.3


def test_tilt_direction_ignores_noise_along_the_fibres() -> None:
    case = tilted_stack(syn.Texture(**fibres(90.0)), length=416)
    field = lpsf.estimate(case.layers, 1.0, metric=case.metric)
    direction = lpsf.tilt_direction(field)
    assert np.median(np.abs(direction[..., 1][field.valid])) > 0.99


def test_extreme_prediction_is_clipped_and_flagged() -> None:
    texture = syn.realistic_texture(6.0, corr_length=2.0, **fibres(0.0))
    case = tilted_stack(texture)
    field = lpsf.estimate(case.layers, 1.0, metric=case.metric)
    gains = lpsf.gain_map(case.layers, field)
    assert gains.gain.min() >= lpsf.GAIN_CLIP[0]
    assert gains.flagged[field.valid].mean() > 0.5


def test_no_void_layers_means_no_noise_estimate() -> None:
    case = tilted_stack(syn.Texture())
    field = lpsf.estimate(case.layers, 1.0, metric=case.metric)
    assert np.isnan(lpsf.gain_map(case.layers, field).noise_share).all()


def test_void_layers_separate_fixed_noise_from_texture() -> None:
    sheet = replace(SHEET, noise="processed", snr=2.0)
    points = syn.tilted_points((288, 64), 5.0, 0.0)
    case = syn.make_case(None, syn.Texture(), sheet, 41, 1.0, seed=8, points=points)
    field = lpsf.estimate(case.layers, 1.0, metric=case.metric)
    gains = lpsf.gain_map(case.layers, field)
    ok = field.valid
    assert np.nanmedian(gains.noise_share[ok]) > 0.05
    assert np.nanmedian(gains.length_void[ok]) < np.nanmedian(gains.length[ok])
    assert 0 < np.nanmedian(gains.shrink[ok]) < 1


# Directional estimate


@settings(max_examples=60, deadline=None)
@given(
    st.lists(
        st.tuples(st.floats(0.2, 5.0), st.floats(-3.0, 3.0), st.floats(-3.0, 3.0)),
        min_size=2,
        max_size=3,
    )
)
def test_solve_observed_matches_the_pseudo_inverse_when_all_directions_are_kept(terms) -> None:
    matrix = np.diag([1e-3, 1e-3]) + sum(a * np.outer([b, c], [b, c]) for a, b, c in terms)
    rhs = matrix @ np.array([0.3, -0.2])
    shift, information, _ = lpsf.solve_observed(matrix, rhs, 0.0, 100.0)
    assert shift == pytest.approx(np.linalg.pinv(matrix) @ rhs, abs=1e-6)
    assert information == pytest.approx(matrix, abs=1e-9)


def test_rank_deficient_system_leaves_the_unobserved_direction_empty() -> None:
    e = np.array([0.6, 0.8])
    matrix = 4.0 * np.outer(e, e) + 1e-9 * np.eye(2)
    shift, information, cov = lpsf.solve_observed(matrix, 4.0 * e * 0.5, 0.1, 100.0)
    null = np.array([-0.8, 0.6])
    assert shift == pytest.approx(0.5 * e, abs=1e-8)
    assert null @ information @ null == pytest.approx(0.0, abs=1e-12)
    assert null @ cov @ null == pytest.approx(100.0)


def pairs(directions: list[np.ndarray], truth: np.ndarray) -> tuple:
    """A one-patch stack of pairs, each seeing only ``truth`` across its own direction."""
    n = len(directions)
    cov = np.empty((n, 1, 1, 2, 2))
    shift = np.empty((n, 1, 1, 2))
    for k, e in enumerate(directions):
        null = np.array([-e[1], e[0]])
        cov[k, 0, 0] = 0.01 * np.outer(e, e) + 100.0 * np.outer(null, null)
        shift[k, 0, 0] = (e @ truth) * e + 7.0 * null  # the along-fibre part is a large bias
    return shift, cov, np.ones((n, 1, 1), dtype=bool)


def test_one_fibre_direction_gives_rank_one_and_ignores_the_along_bias() -> None:
    e = np.array([1.0, 0.0])
    truth = np.array([0.2, 0.5])
    shift, _, _ = lpsf.directional_summary(*pairs([e, e, e], truth), 0.1, 256.0)
    assert shift[0, 0] == pytest.approx([0.2, 0.0])


def test_two_fibre_layers_jointly_recover_both_directions() -> None:
    truth = np.array([0.2, 0.5])
    a, b = np.array([1.0, 0.0]), np.array([0.0, 1.0])
    shift, information, _ = lpsf.directional_summary(*pairs([a, a, b, b], truth), 0.1, 256.0)
    assert shift[0, 0] == pytest.approx(truth)
    assert np.linalg.matrix_rank(information[0, 0]) == 2


@pytest.mark.parametrize("estimator", ["pc", "lk"])
def test_directional_keeps_the_across_fibre_component_where_full_reverses(estimator: str) -> None:
    angle = 45.0
    texture = syn.realistic_texture(6.0, corr_length=4.3, **fibres(angle))
    case = tilted_stack(texture, length=416)
    params = lpsf.Params(estimator=estimator, directional=True)
    field = lpsf.estimate(case.layers, 1.0, params, metric=case.metric)
    truth = lpsf.patch_average(case.grad_h, field)
    seen = np.linalg.eigh(field.information)[1][..., 1]
    ok = field.valid & (field.observed_rank() == 1)
    assert ok.mean() > 0.5
    observed = np.sum(field.grad * seen, axis=-1)[ok]
    expected = np.sum(truth * seen, axis=-1)[ok]
    assert np.sum(observed * expected) / np.sum(expected**2) == pytest.approx(1.0, abs=0.3)


@pytest.mark.parametrize("estimator", ["pc", "lk"])
def test_unobserved_direction_has_no_estimate_and_no_information(estimator: str) -> None:
    texture = syn.Texture(spread_deg=0.0, **fibres(30.0))
    case = tilted_stack(texture)
    params = lpsf.Params(estimator=estimator, directional=True)
    field = lpsf.estimate(case.layers, 1.0, params, metric=case.metric)
    ok = field.valid & (field.observed_rank() == 1)
    assert ok.mean() > 0.9
    evals, evecs = np.linalg.eigh(field.information)
    null = evecs[..., 0]
    assert np.abs(evals[..., 0][ok]).max() < 1e-9 * evals[..., 1][ok].max()
    assert np.abs(np.sum(field.shift * null, axis=-1)[ok]).max() < 1e-6
    assert field.grad_information is not None
    assert np.abs(np.einsum("rci,rcij,rcj->rc", null, field.grad_information, null)[ok]).max() < 1e-6


def test_calibrating_a_directional_field_cannot_create_an_observation() -> None:
    texture = syn.Texture(spread_deg=0.0, **fibres(30.0))
    case = tilted_stack(texture)
    params = lpsf.Params(directional=True, sigma_inflation=2.0, sigma_floor=0.1)
    field = lpsf.estimate(case.layers, 1.0, params, metric=case.metric)
    ok = field.valid & (field.observed_rank() == 1)
    assert (np.linalg.matrix_rank(field.grad_information[ok], tol=1e-9) == 1).all()


def test_integration_fills_the_unobserved_direction_from_neighbours_and_zstar() -> None:
    size = 64 * 6
    h = syn.offset_bump((size, size), 3.0, 256.0) + 1.5
    case = syn.make_case(h, syn.Texture(), SHEET, 31, 1.0, seed=9)
    field = lpsf.estimate(case.layers, 1.0, lpsf.Params(directional=True), metric=case.metric)
    assert (field.observed_rank()[field.valid] < 2).any()
    error = lpsf.integrate(field) - lpsf.patch_average(case.h, field, power=1)
    assert np.sqrt(np.mean(error**2)) < 0.6


def test_directional_integration_gives_a_finite_surface_on_a_rank_zero_mask() -> None:
    gv, gu = np.zeros((5, 5)), np.zeros((5, 5))
    information = np.zeros((5, 5, 2, 2))
    zstar = np.full((5, 5), 2.0)
    everywhere = np.ones((5, 5), dtype=bool)
    cov = np.eye(2) * np.ones((5, 5, 2, 2))
    out = lpsf.screened_lsq(gv, gu, cov, 32.0, everywhere, zstar, everywhere, information=information)
    assert out == pytest.approx(zstar, abs=1e-6)


def test_full_estimate_is_unchanged_by_the_directional_code() -> None:
    case = tilted_stack(syn.Texture())
    base = lpsf.estimate(case.layers, 1.0, lpsf.Params(), metric=case.metric)
    calibrated = lpsf.estimate(case.layers, 1.0, lpsf.Params(sigma_inflation=2.0), metric=case.metric)
    assert base.shift == pytest.approx(calibrated.shift)
    assert base.cov == pytest.approx(calibrated.cov)


# Processed noise


def test_paganin_length_matches_the_decision_record() -> None:
    assert syn.paganin_length_voxels() == pytest.approx(7.0, abs=0.1)


def test_processing_transfer_is_one_at_zero_frequency() -> None:
    assert syn.processing_transfer(np.array(0.0), 7.0, 4.0, 1.2) == pytest.approx(1.0)


def test_transfer_matches_the_unsharp_mask_in_real_space() -> None:
    """Fast path: the frequency response. Slow reference: the mask applied to an image with a real Gaussian."""
    rng = np.random.default_rng(11)
    image = rng.standard_normal((64, 64, 64))
    spectrum = np.fft.fftn(image)
    k = 2 * np.pi * np.fft.fftfreq(64)
    k2 = k[:, None, None] ** 2 + k[None, :, None] ** 2 + k[None, None, :] ** 2
    fast = np.real(np.fft.ifftn(spectrum * syn.processing_transfer(k2, 0.0, 4.0, 1.2)))
    slow = 5.0 * image - 4.0 * ndimage.gaussian_filter(image, 1.2, mode="wrap", truncate=8.0)
    assert np.std(fast - slow) < 0.02 * np.std(slow)


def test_processed_noise_is_unit_variance_and_correlated_over_voxels() -> None:
    noise = syn.processed_noise((48, 96, 96), np.random.default_rng(5))
    assert noise.std() == pytest.approx(1.0, abs=1e-3)
    assert noise.dtype == np.float32
    assert abs(noise.mean()) < 1e-3
    lag_z = np.mean(noise[:-1] * noise[1:])
    lag_x = np.mean(noise[..., :-1] * noise[..., 1:])
    assert lag_z > 0.5, "white noise would give zero"
    assert lag_z == pytest.approx(lag_x, abs=0.1), "the filter is isotropic"


def test_noise_is_fixed_in_volume_coordinates() -> None:
    rng_a, rng_b = np.random.default_rng(6), np.random.default_rng(6)
    sheet = replace(SHEET, noise="processed", snr=1.0)
    a = syn.make_volume((32, 64, 64), 400.0, sheet, syn.Texture(), rng_a)
    b = syn.make_volume((32, 64, 64), 800.0, sheet, syn.Texture(), rng_b)
    assert np.allclose(a, b), "both sheets are out of range: only the noise remains, and it did not move"


def test_white_noise_path_is_unchanged() -> None:
    sheet = syn.Sheet(snr=6.0)
    assert sheet.noise == "white"
    a = syn.make_volume((24, 48, 48), 12.0, sheet, syn.Texture(), np.random.default_rng(7))
    b = syn.make_volume((24, 48, 48), 12.0, replace(sheet, noise="white"), syn.Texture(), np.random.default_rng(7))
    assert np.array_equal(a, b)


# Sweeps


def test_seed_splits_can_never_share_a_seed() -> None:
    config = {"seed": 2029, "sweep": [{"experiment": "orientation", "theta_deg": [1, 2], "seed_id": [0, 1, 2, 3, 4]}]}
    first = {case["seed"] for case in experiments.expand(config)}
    config["sweep"][0]["seed_id"] = [5, 6, 7, 8, 9]
    second = {case["seed"] for case in experiments.expand(config)}
    assert len(first) == 10
    assert not first & second


def test_sweeps_without_a_split_keep_their_seeds() -> None:
    cases = experiments.expand({"seed": 2026, "sweep": [{"experiment": "tilt", "theta_deg": [1, 2]}]})
    assert [case["seed"] for case in cases] == [2026000, 2026001]


@pytest.mark.parametrize("texture", ["a1", "realistic"])
def test_orientation_experiment_runs_and_reports_both_estimates(texture: str) -> None:
    case = {
        "experiment": "orientation",
        "texture": texture,
        "fibre_tilt_deg": 45,
        "theta_deg": 5,
        "length": 224,
        "case_id": 0,
        "seed": 12,
    }
    row, details = experiments.run_case(case)
    assert row["status"] == "ok", row["error"]
    assert details
    assert all(key in details[0] for key in ("g_u", "truth_u", "var_uu", "side_var", "side_rank", "L", "gain_pred"))
