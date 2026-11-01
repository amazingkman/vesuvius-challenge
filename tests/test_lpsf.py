"""LPSF estimator: predictions P1–P6 on small synthetic stacks, degenerate inputs, conventions (WO-002 §3.4)."""

from __future__ import annotations

import numpy as np
import pytest

from vesuvius_challenge import crlb, experiments, lpsf
from vesuvius_challenge import synthetic as syn

SHEET = syn.Sheet(snr=6.0)


def tilt_field(theta: float, azimuth: float = 0.0, estimator: str = "pc", slice_step: float = 1.0, **kw):
    shape = (224, 64) if azimuth == 0 else (160, 160)
    case = syn.make_case(
        None,
        syn.Texture(),
        kw.pop("sheet", SHEET),
        21,
        slice_step,
        seed=11,
        points=syn.tilted_points(shape, theta, azimuth),
    )
    f = lpsf.estimate(case.layers, slice_step, lpsf.Params(estimator=estimator, **kw), metric=case.metric)
    return case, f


@pytest.mark.parametrize("estimator", ["pc", "lk"])
def test_sign_and_scale_known_answer(estimator: str) -> None:
    """s points along +grad h, and g = tan(theta) on an isometric mesh (addendum 1 item 4, addendum 2 item 1)."""
    case, f = tilt_field(5.0, estimator=estimator)
    truth = lpsf.patch_average(case.grad_h, f)[..., 1][f.valid].mean()
    got = f.grad[..., 1][f.valid].mean()
    assert got > 0
    assert got / truth == pytest.approx(1.0, abs=0.06)
    assert abs(f.grad[..., 0][f.valid].mean()) < 0.01


def test_p1_shift_scales_with_slice_step() -> None:
    _, f1 = tilt_field(5.0, slice_step=1.0)
    _, f2 = tilt_field(5.0, slice_step=2.0)
    s1 = f1.shift[..., 1][f1.valid].mean()
    s2 = f2.shift[..., 1][f2.valid].mean()
    assert s2 / s1 == pytest.approx(2.0, rel=0.1)


def test_p2_direction_follows_the_tilt() -> None:
    case, f = tilt_field(5.0, azimuth=30.0)
    g = f.grad[f.valid].mean(axis=0)
    angle = np.degrees(np.arctan2(g[0], g[1]))
    assert angle == pytest.approx(30.0, abs=5.0)


def test_p2_pure_offset_gives_no_shift() -> None:
    row, _ = experiments.run_case({"experiment": "offset", "offset": 4.0, "case_id": 0, "seed": 5, "size": 192})
    assert row["status"] == "ok", row["error"]
    assert row["shift_mag_max"] < 0.05


@pytest.mark.parametrize("offset", [-6.0, 0.0, 6.0])
def test_p3_zstar_tracks_a_constant_offset(offset: float) -> None:
    row, _ = experiments.run_case({"experiment": "offset", "offset": offset, "case_id": 0, "seed": 6, "size": 192})
    assert row["censored_fraction"] == 0
    assert abs(row["zstar_err_mean"]) < 0.5


def test_p4_consistency_residual_finds_a_step_and_curl_stays_small() -> None:
    row, _ = experiments.run_case({"experiment": "step", "amplitude": 4.0, "size": 320, "case_id": 0, "seed": 7})
    assert row["status"] == "ok", row["error"]
    assert row["auroc_residual"] >= 0.9
    # curl is not a step detector: along the straight step it stays far below the residual
    assert row["curl_pos_mean"] < 0.1 * row["residual_pos_mean"]


def test_p5_sigma_reflects_the_aperture_problem() -> None:
    row, _ = experiments.run_case(
        {"experiment": "aperture", "texture": "a1", "spread_deg": 0, "length": 352, "case_id": 0, "seed": 8}
    )
    assert row["status"] == "ok", row["error"]
    assert row["pred_var_along"] > 100 * row["pred_var_across"]
    assert row["emp_var_along"] > 10 * row["emp_var_across"]


def test_p6_correlation_collapses_in_the_gap_and_the_window_stays_on_its_wrap() -> None:
    for thickness, gap in ((20, 27), (47, 0)):
        row, _ = experiments.run_case(
            {"experiment": "layers", "thickness": thickness, "gap": gap, "case_id": 0, "seed": 9, "size": 128}
        )
        assert row["status"] == "ok", row["error"]
        assert row["window_leak_fraction"] == 0
        if gap:
            assert row["rho_in_gap"] < 0.5 * row["rho_in_sheet"]


def test_flat_patches_give_low_rho_and_capped_covariance() -> None:
    flat = np.ones((4, 64, 64))
    res = lpsf.phase_correlate(flat[:-1], flat[1:])
    assert np.all(res.rho == 0)
    assert np.allclose(res.cov, lpsf.cov_cap(64) * np.eye(2))


def test_pure_noise_gives_low_rho_and_large_covariance() -> None:
    rng = np.random.default_rng(0)
    noise = rng.normal(size=(9, 64, 64))
    texture = syn.texture_2d((64, 64), syn.Texture(spread_deg=None), rng)
    res_noise = lpsf.phase_correlate(noise[:-1], noise[1:])
    res_tex = lpsf.phase_correlate(texture[None], (texture + 0.1 * rng.normal(size=texture.shape))[None])
    assert res_noise.ncc.max() < 0.3
    assert np.trace(res_noise.cov, axis1=-2, axis2=-1).min() > 100 * np.trace(res_tex.cov[0])


def test_metric_correction_removes_the_stretch_bias() -> None:
    row, _ = experiments.run_case({"experiment": "stretch", "eps": 0.1, "length": 224, "case_id": 0, "seed": 10})
    assert row["ratio_with_metric"] == pytest.approx(1.0, abs=0.06)
    # skipping g under-reads by (1 + eps)^-2 ~ 1 - 2 eps relative to the corrected estimate
    assert row["ratio_without_metric"] / row["ratio_with_metric"] == pytest.approx(row["predicted_without"], abs=0.01)


def test_bandpass_removes_the_envelope_bias() -> None:
    """Addendum 2 item 2: a thin sheet under a tilted patch; unfiltered layers are biased, band-passed are not."""
    thin = syn.Sheet(snr=6.0, thickness=16.0)  # a 64-px patch at 10 degrees spans 11 voxels of depth
    case, filtered = tilt_field(10.0, sheet=thin)
    _, raw = tilt_field(10.0, sheet=thin, bp_fine=0.0, bp_coarse=0.0, normalize=False)
    truth = lpsf.patch_average(case.grad_h, filtered)[..., 1][filtered.valid].mean()
    good = filtered.grad[..., 1][filtered.valid].mean() / truth
    bad = raw.grad[..., 1][raw.valid].mean() / truth
    assert abs(good - 1) < 0.1
    assert abs(bad - 1) > 2 * abs(good - 1)


def test_point_slope_regression_under_reads_a_short_sinusoid() -> None:
    """Addendum 2 item 8: against point slopes the estimate reads ~the window transfer, against window truth ~1."""
    row, _ = experiments.run_case(
        {"experiment": "sinusoid", "wavelength_px": 128, "size": 384, "case_id": 0, "seed": 12}
    )
    assert row["slope_vs_point"] == pytest.approx(row["hann_transfer"], abs=0.05)
    assert row["slope_vs_window"] == pytest.approx(1.0, abs=0.05)


def test_screened_integration_recovers_a_bump() -> None:
    row, _ = experiments.run_case(
        {"experiment": "bump", "amplitude": 3.0, "fwhm_px": 160, "size": 320, "case_id": 0, "seed": 13}
    )
    assert row["status"] == "ok", row["error"]
    assert row["rmse_lsq"] < 0.5


def test_window_rule_never_uses_the_shifts() -> None:
    """The aggregation window depends on intensities only: changing the estimator leaves it unchanged."""
    _, pc = tilt_field(5.0, estimator="pc")
    _, lk = tilt_field(5.0, estimator="lk")
    assert np.array_equal(pc.in_window, lk.in_window)


def test_crlb_shrinks_with_snr_and_layers() -> None:
    tex = syn.Texture()
    low = crlb.crlb_pair(tex, syn.Sheet(snr=2.0), 1.0, 64)
    high = crlb.crlb_pair(tex, syn.Sheet(snr=20.0), 1.0, 64)
    assert high < low
    assert crlb.crlb_stack(tex, SHEET, 1.0, 64, 10) < crlb.crlb_pair(tex, SHEET, 1.0, 64)


def test_auroc_reference_values() -> None:
    assert experiments.auroc(np.array([3.0, 4.0, 1.0, 2.0]), np.array([1, 1, 0, 0])) == 1.0
    assert experiments.auroc(np.array([1.0, 1.0]), np.array([1, 0])) == 0.5
