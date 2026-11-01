"""Synthetic experiments for WO-002: one function per experiment, each returning a summary row and per-item details.

Every experiment builds its stack with :mod:`vesuvius_challenge.synthetic`, runs :func:`lpsf.estimate`, and compares
against ground truth averaged with the estimator's own window (addendum 2 item 8). All slope statistics are signed
components along the known tilt direction, never ``|s|``.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import replace
from typing import Any

import numpy as np

from vesuvius_challenge import crlb, lpsf
from vesuvius_challenge import synthetic as syn

Result = tuple[dict[str, Any], list[dict[str, Any]]]


# ---------------------------------------------------------------------------------------------------------------
# Shared builders
# ---------------------------------------------------------------------------------------------------------------


def make_texture(p: dict) -> syn.Texture:
    mode = p.get("texture", "a1")
    spread = p.get("spread_deg", 25.0)
    spread = None if spread in (None, "iso", "none") else float(spread)
    common = dict(
        wavelength=float(p.get("wavelength", 8.0)),
        orientation_deg=float(p.get("fibre_deg", 30.0)),
        spread_deg=spread,
    )
    if mode == "realistic":
        return syn.realistic_texture(float(p.get("realistic_snr", 6.0)), **common)
    return syn.Texture(mode=mode, **common)


def make_sheet(p: dict) -> syn.Sheet:
    snr = p.get("snr", 6.0)
    return syn.Sheet(
        thickness=float(p.get("thickness", 20.0)),
        snr=None if snr in (None, "none", "inf") else float(snr),
        gap=None if p.get("gap") in (None, "none") else float(p["gap"]),
    )


def make_params(p: dict) -> lpsf.Params:
    keys = {f.name for f in lpsf.Params.__dataclass_fields__.values()}
    chosen = {k: p[k] for k in keys if k in p}
    return lpsf.Params(**chosen)


def odd(n: float) -> int:
    n = int(np.ceil(n))
    return n if n % 2 else n + 1


def stack_for(reach_voxels: float, slice_step: float, minimum: int = 21) -> int:
    """Odd K whose half-span covers ``reach_voxels``."""
    return max(minimum, odd(2 * reach_voxels / slice_step + 1))


def auroc(scores: np.ndarray, labels: np.ndarray) -> float:
    """Mann–Whitney AUROC; NaN if a class is empty."""
    scores = np.asarray(scores, dtype=np.float64)
    labels = np.asarray(labels, dtype=bool)
    pos, neg = scores[labels], scores[~labels]
    if pos.size == 0 or neg.size == 0:
        return float("nan")
    order = np.argsort(np.concatenate([pos, neg]), kind="mergesort")
    ranks = np.empty(order.size)
    ranks[order] = np.arange(1, order.size + 1)
    # average ties
    allv = np.concatenate([pos, neg])
    for value in np.unique(allv):
        tie = allv == value
        if tie.sum() > 1:
            ranks[tie] = ranks[tie].mean()
    return float((ranks[: pos.size].sum() - pos.size * (pos.size + 1) / 2) / (pos.size * neg.size))


def hann_transfer(patch: int, wavelength: float, power: int = 2) -> float:
    """Attenuation of a sinusoid's slope by the estimator's 1-D weighting ``hann^power`` (window-average factor)."""
    w = np.hanning(patch + 2)[1:-1] ** power
    x = np.arange(patch) - (patch - 1) / 2
    return float(np.sum(w * np.cos(2 * np.pi * x / wavelength)) / w.sum())


# ---------------------------------------------------------------------------------------------------------------
# Experiments
# ---------------------------------------------------------------------------------------------------------------


def exp_tilt(p: dict, seed: int) -> Result:
    """P1/P2, small angles, envelope, estimator benchmark: an isometric plane tilted by theta along +u.

    The field is a strip ``length x patch`` with the tilt across its short axis, so every patch is centred where the
    mesh crosses the sheet mid-plane.
    """
    params = make_params(p)
    tex, sheet = make_texture(p), make_sheet(p)
    theta, dd = float(p["theta_deg"]), float(p.get("slice_step", 1.0))
    length = int(p.get("length", 544))
    K = int(p.get("num_slices", 21))
    pts = syn.tilted_points((length, params.patch), theta, 0.0)
    case = syn.make_case(None, tex, sheet, K, dd, seed=seed, points=pts)
    t0 = time.perf_counter()
    f = lpsf.estimate(case.layers, dd, params, metric=case.metric)
    elapsed = time.perf_counter() - t0
    truth = lpsf.patch_average(case.grad_h, f)
    g = f.grad
    ok = f.valid
    par, perp = g[..., 1], g[..., 0]
    tpar = truth[..., 1]
    n_pairs = f.pair_used.sum(axis=0)
    mean_pairs = float(n_pairs[ok].mean()) if ok.any() else 0.0
    bound_pair = crlb.crlb_pair(tex, sheet, dd, params.patch) / dd**2
    bound_stack = crlb.crlb_stack(tex, sheet, dd, params.patch, max(2, int(round(mean_pairs)) + 1)) / dd**2
    row = {
        "truth_tan": float(np.tan(np.deg2rad(theta))),
        "truth_window": float(tpar[ok].mean()) if ok.any() else np.nan,
        "g_par_mean": float(par[ok].mean()) if ok.any() else np.nan,
        "g_par_sd": float(par[ok].std(ddof=1)) if ok.sum() > 1 else np.nan,
        "g_perp_mean": float(perp[ok].mean()) if ok.any() else np.nan,
        "g_perp_sd": float(perp[ok].std(ddof=1)) if ok.sum() > 1 else np.nan,
        "pred_sd_par": float(np.sqrt(f.grad_cov[..., 1, 1][ok].mean())) if ok.any() else np.nan,
        "rho_mean": float(f.rho[ok].mean()) if ok.any() else np.nan,
        "valid_fraction": float(ok.mean()),
        "pairs_mean": mean_pairs,
        "crlb_pair_var": bound_pair,
        "crlb_stack_var": bound_stack,
        "n_patches": int(ok.sum()),
        "estimate_seconds": elapsed,
    }
    details = [
        {
            "patch": int(i),
            "g_par": float(par.ravel()[i]),
            "g_perp": float(perp.ravel()[i]),
            "truth_par": float(tpar.ravel()[i]),
            "valid": bool(ok.ravel()[i]),
            "rho": float(f.rho.ravel()[i]),
            "pred_var_par": float(f.grad_cov[..., 1, 1].ravel()[i]),
            "pairs": int(n_pairs.ravel()[i]),
        }
        for i in range(ok.size)
    ]
    return row, details


def exp_offset(p: dict, seed: int) -> Result:
    """P3 and the pure-offset half of P2: constant offset c on a flat mesh; z* must track c and s must stay ~0."""
    params = make_params(p)
    tex, sheet = make_texture(p), make_sheet(p)
    c, dd = float(p["offset"]), float(p.get("slice_step", 1.0))
    size = int(p.get("size", 3 * params.patch))
    K = stack_for(abs(c) + sheet.thickness / 2 + 6, dd, int(p.get("num_slices", 41)))
    case = syn.make_case(syn.offset_constant((size, size), c), tex, sheet, K, dd, seed=seed)
    f = lpsf.estimate(case.layers, dd, params, metric=case.metric)
    truth = lpsf.patch_average(case.h, f, power=1)
    ok = f.zstar_ok
    shift_mag = np.linalg.norm(f.shift, axis=-1)[f.valid]
    row = {
        "num_slices": K,
        "truth_mean": float(truth.mean()),
        "zstar_mean": float(np.nanmean(np.where(ok, f.zstar, np.nan))),
        "zstar_err_mean": float(np.nanmean(np.where(ok, f.zstar - truth, np.nan))),
        "zstar_err_rms": float(np.sqrt(np.nanmean(np.where(ok, (f.zstar - truth) ** 2, np.nan)))),
        "censored_fraction": float(f.kstar_censored.mean()),
        "shift_mag_mean": float(shift_mag.mean()) if shift_mag.size else np.nan,
        "shift_mag_max": float(shift_mag.max()) if shift_mag.size else np.nan,
        "shift_u_mean": float(f.shift[..., 1][f.valid].mean()) if f.valid.any() else np.nan,
    }
    return row, []


def _field_case(p: dict, h: np.ndarray, seed: int, extra_reach: float = 0.0):
    params = make_params(p)
    tex, sheet = make_texture(p), make_sheet(p)
    dd = float(p.get("slice_step", 1.0))
    K = stack_for(float(np.max(np.abs(h))) + sheet.thickness / 2 + 6 + extra_reach, dd, int(p.get("num_slices", 21)))
    case = syn.make_case(h, tex, sheet, K, dd, seed=seed, stretch=tuple(p.get("stretch", (1.0, 1.0))))
    f = lpsf.estimate(case.layers, dd, params, metric=case.metric)
    return case, f, K


def exp_bump(p: dict, seed: int) -> Result:
    """Offset recovery: constant + Gaussian bump; RMSE of h_hat (screened LSQ, FC reference) and of z* alone."""
    patch = int(p.get("patch", 64))
    amp = float(p["amplitude"])
    width = float(p["fwhm_px"]) if p.get("fwhm_px") else float(p["fwhm_patches"]) * patch
    size = int(p.get("size") or max(6 * patch, np.ceil(3 * width / patch) * patch))
    h = syn.offset_bump((size, size), amp, width) + float(p.get("constant", 1.5))
    case, f, K = _field_case(p, h, seed)
    truth = lpsf.patch_average(case.h, f, power=1)
    out = {"num_slices": K, "size": size}
    for method in ("lsq", "fc"):
        e = lpsf.integrate(f, method) - truth
        out[f"rmse_{method}"] = float(np.sqrt(np.mean(e**2)))
        out[f"shape_rmse_{method}"] = float(np.std(e))
    ez = np.where(f.zstar_ok, f.zstar - truth, np.nan)
    out["rmse_zstar"] = float(np.sqrt(np.nanmean(ez**2)))
    out["valid_fraction"] = float(f.valid.mean())
    out["zstar_ok_fraction"] = float(f.zstar_ok.mean())
    return out, []


def exp_step(p: dict, seed: int) -> Result:
    """P4: a straight step (sheet-jump surrogate). Scores per patch; labels with a buffer zone.

    Positive: patch centre within P/4 of the step line. Negative: farther than P. In between: excluded.
    """
    patch = int(p.get("patch", 64))
    size = int(p.get("size", 6 * patch))
    amp = float(p["amplitude"])
    angle = float(p.get("step_angle_deg", 20.0))
    h = syn.offset_step((size, size), amp, angle, float(p.get("step_width", 2.0))) - amp / 2
    case, f, K = _field_case(p, h, seed)
    d = syn.step_distance((size, size), angle)
    dist = np.abs(d[np.rint(f.centres_v).astype(int)][:, np.rint(f.centres_u).astype(int)])
    pos, neg = dist < patch / 4, dist > patch
    use = pos | neg
    resid = np.linalg.norm(lpsf.consistency_residual(f), axis=-1)
    curl = np.abs(lpsf.field_curl(f))
    h_hat = lpsf.integrate(f, "lsq")
    grad_hat = np.linalg.norm(np.stack(np.gradient(h_hat, f.spacing), -1), axis=-1)
    z = np.where(f.zstar_ok, f.zstar, np.nanmean(np.where(f.zstar_ok, f.zstar, np.nan)))
    grad_z = np.linalg.norm(np.stack(np.gradient(z, f.spacing), -1), axis=-1)
    scores = {"residual": resid, "curl": curl, "grad_hhat": grad_hat, "grad_zstar": grad_z}
    row = {"num_slices": K, "n_pos": int(pos.sum()), "n_neg": int(neg.sum())}
    for name, sc in scores.items():
        row[f"auroc_{name}"] = auroc(sc[use], pos[use])
        row[f"{name}_pos_mean"] = float(sc[pos].mean()) if pos.any() else np.nan
        row[f"{name}_neg_mean"] = float(sc[neg].mean()) if neg.any() else np.nan
    details = [
        {
            "dist": float(dist.ravel()[i]),
            "label": int(pos.ravel()[i]) if use.ravel()[i] else -1,
            **{k: float(v.ravel()[i]) for k, v in scores.items()},
        }
        for i in range(dist.size)
    ]
    return row, details


def exp_sinusoid(p: dict, seed: int) -> Result:
    """The windowed-validation trap (addendum 2 item 8): regress g on the point slope vs the window-averaged slope."""
    patch = int(p.get("patch", 64))
    lam = float(p["wavelength_px"])
    size = int(p.get("size", max(6 * patch, int(2 * lam) + patch)))
    h = syn.offset_sinusoid((size, size), float(p.get("amplitude", 2.0)), lam, 0.0)
    case, f, K = _field_case(p, h, seed)
    ok = f.valid
    g = f.grad[..., 1][ok]
    window = lpsf.patch_average(case.grad_h, f)[..., 1][ok]
    cv = np.rint(f.centres_v).astype(int)
    cu = np.rint(f.centres_u).astype(int)
    point = case.grad_h[cv][:, cu][..., 1][ok]

    def through_origin(x, y):
        return float(np.sum(x * y) / np.sum(x * x))

    row = {
        "num_slices": K,
        "slope_vs_point": through_origin(point, g),
        "slope_vs_window": through_origin(window, g),
        "hann_transfer": hann_transfer(patch, lam),
        "sinc": float(np.sinc(patch / lam)),
    }
    return row, []


def exp_stretch(p: dict, seed: int) -> Result:
    """Metric correction (addendum 2 item 1): a ramp on a mesh stretched by (1 + eps) along u."""
    eps = float(p["eps"])
    theta = float(p.get("theta_deg", 5.0))
    patch = int(p.get("patch", 64))
    shape = (int(p.get("length", 544)), patch)
    h = syn.offset_ramp(shape, theta, 0.0)
    q = dict(p, stretch=(1.0, 1.0 + eps))
    case, f, K = _field_case(q, h, seed)
    ok = f.valid
    truth = lpsf.patch_average(case.grad_h, f)[..., 1][ok]
    with_metric = f.grad[..., 1][ok]
    without = (f.shift[..., 1] / f.slice_step)[ok]
    row = {
        "ratio_with_metric": float(with_metric.mean() / truth.mean()),
        "ratio_without_metric": float(without.mean() / truth.mean()),
        "predicted_without": float(1 / (1 + eps) ** 2),
    }
    return row, []


def exp_layers(p: dict, seed: int) -> Result:
    """P6 and the neighbouring-wrap rule: two sheets, gap ``gap``; flat mesh on the first.

    Reports the correlation profile and whether any aggregation-window layer reaches the second sheet.
    """
    params = make_params(p)
    tex, sheet = make_texture(p), make_sheet(p)
    dd = float(p.get("slice_step", 1.0))
    K = int(p.get("num_slices", 81))
    size = int(p.get("size", 3 * params.patch))
    case = syn.make_case(syn.offset_constant((size, size), 0.0), tex, sheet, K, dd, seed=seed)
    f = lpsf.estimate(case.layers, dd, params, metric=case.metric)
    k = np.arange(K)
    z = (k - f.k0) * dd + float(np.mean(case.h))  # layer depth relative to sheet-1 mid-plane
    half = sheet.thickness / 2
    gap = sheet.gap or 0.0
    in_second = (z >= half + gap) & (z <= half + gap + sheet.thickness)
    in_gap = (z > half) & (z < half + gap)
    rho = f.rho0.mean(axis=(1, 2))
    zp = 0.5 * (z[:-1] + z[1:])
    pair_first = (z[:-1] >= -half + 1) & (z[1:] <= half - 1)
    pair_gap = (z[:-1] > half + 1) & (z[1:] < half + gap - 1)
    pair_cross = np.abs(zp - (half + gap / 2)) <= 3 if gap == 0 else np.zeros_like(pair_first)
    leak = (f.in_window & in_second[:, None, None]).any(axis=0)
    row = {
        "num_slices": K,
        "rho_in_sheet": float(rho[pair_first].mean()) if pair_first.any() else np.nan,
        "rho_in_gap": float(rho[pair_gap].mean()) if pair_gap.any() else np.nan,
        "rho_interface": float(rho[pair_cross].min()) if np.any(pair_cross) else np.nan,
        "window_leak_fraction": float(leak.mean()),
        "window_layers_mean": float(f.in_window.sum(axis=0).mean()),
        "layers_in_gap": int(in_gap.sum()),
    }
    details = [{"k": int(i), "z_mid": float(zp[i]), "rho0": float(rho[i])} for i in range(K - 1)]
    return row, details


def exp_aperture(p: dict, seed: int) -> Result:
    """P5 and addendum 2 item 4: oriented textures; predicted Sigma vs empirical scatter, per layer and summed."""
    params = make_params(p)
    tex, sheet = make_texture(p), make_sheet(p)
    theta, dd = float(p.get("theta_deg", 3.0)), float(p.get("slice_step", 1.0))
    pts = syn.tilted_points((int(p.get("length", 1056)), params.patch), theta, 0.0)
    case = syn.make_case(None, tex, sheet, int(p.get("num_slices", 21)), dd, seed=seed, points=pts)
    f = lpsf.estimate(case.layers, dd, params, metric=case.metric)
    ok = f.valid
    err = (f.grad - lpsf.patch_average(case.grad_h, f))[ok]  # (N, 2) (v, u)
    fibre = np.deg2rad(tex.orientation_deg - syn.GENERIC_ROTATION_DEG)  # fibre direction in the mesh (v, u) frame
    along = np.array([np.sin(fibre), np.cos(fibre)])  # (v, u)
    across = np.array([np.cos(fibre), -np.sin(fibre)])
    pred = f.grad_cov[ok].mean(axis=0)
    # per-pair conditioning inside the window vs the summed information
    used = f.pair_used
    pc = f.pair_cov[used]
    cond_pair = np.linalg.cond(pc) if pc.size else np.array([np.nan])
    info_sum = np.linalg.inv(f.pair_cov).copy()
    info_sum[~used] = 0
    summed = info_sum.sum(axis=0)[ok]
    cond_sum = np.linalg.cond(summed) if summed.size else np.array([np.nan])
    row = {
        "emp_var_along": float(np.var(err @ along, ddof=1)),
        "emp_var_across": float(np.var(err @ across, ddof=1)),
        "pred_var_along": float(along @ pred @ along),
        "pred_var_across": float(across @ pred @ across),
        "bias_along": float(np.mean(err @ along)),
        "bias_across": float(np.mean(err @ across)),
        "cond_pair_median": float(np.median(cond_pair)),
        "cond_summed_median": float(np.median(cond_sum)),
        "n_patches": int(ok.sum()),
    }
    return row, []


def exp_crosscheck(p: dict, seed: int) -> Result:
    """Fast path vs skimage (upsample 100) vs villa ``_phase_correlate`` on exactly shifted patches."""
    from skimage.registration import phase_cross_correlation
    from vesuvius.tifxyz_label_transfer.estimate_canvas_offset import _phase_correlate as villa

    rng = np.random.default_rng(seed)
    n, patch = int(p.get("n", 50)), int(p.get("patch", 64))
    tex = syn.Texture(spread_deg=None, wavelength=float(p.get("wavelength", 10.0)))
    noise = float(p.get("noise", 0.0))
    details = []
    for i in range(n):
        a = syn.texture_2d((patch, patch), tex, rng)
        s = rng.uniform(-3, 3, 2)
        f = np.fft.fftfreq(patch)
        b = np.real(np.fft.ifft2(np.fft.fft2(a) * np.exp(2j * np.pi * (f[:, None] * s[0] + f[None, :] * s[1]))))
        if noise:
            a = a + rng.normal(0, noise, a.shape)
            b = b + rng.normal(0, noise, b.shape)
        fast = lpsf.phase_correlate(a[None], b[None], lpsf.Params(window=False, beta=1.0)).shift[0]
        fast0 = lpsf.phase_correlate(a[None], b[None], lpsf.Params(window=True, beta=0.0)).shift[0]
        sk = phase_cross_correlation(a, b, upsample_factor=100, normalization="phase")[0]
        vl = np.array(villa(a, b)[0])
        details.append(
            {
                "i": i,
                "true_v": s[0],
                "true_u": s[1],
                "err_fast": float(np.abs(fast - s).max()),
                "err_fast_default": float(np.abs(fast0 - s).max()),
                "err_skimage": float(np.abs(sk - s).max()),
                "err_villa": float(np.abs(vl - s).max()),
                "fast_vs_skimage": float(np.abs(fast - sk).max()),
                "villa_vs_skimage": float(np.abs(vl - sk).max()),
            }
        )
    cols = ["err_fast", "err_fast_default", "err_skimage", "err_villa", "fast_vs_skimage", "villa_vs_skimage"]
    row = {f"{c}_max": float(max(d[c] for d in details)) for c in cols}
    row |= {f"{c}_mean": float(np.mean([d[c] for d in details])) for c in cols}
    return row, details


EXPERIMENTS: dict[str, Callable[[dict, int], Result]] = {
    "tilt": exp_tilt,
    "offset": exp_offset,
    "bump": exp_bump,
    "step": exp_step,
    "sinusoid": exp_sinusoid,
    "stretch": exp_stretch,
    "layers": exp_layers,
    "aperture": exp_aperture,
    "crosscheck": exp_crosscheck,
}


def run_case(case: dict) -> tuple[dict, list[dict]]:
    """Run one expanded case dict (``experiment``, ``seed`` and parameters); never raises."""
    params = {k: v for k, v in case.items() if k not in ("experiment", "seed", "case_id")}
    started = time.perf_counter()
    try:
        row, details = EXPERIMENTS[case["experiment"]](params, int(case["seed"]))
        status = "ok"
        error = ""
    except Exception as exc:  # noqa: BLE001 - a sweep records failures as data
        row, details, status, error = {}, [], "error", f"{type(exc).__name__}: {exc}"
    row = {**case, **row, "status": status, "error": error, "seconds": time.perf_counter() - started}
    details = [{"case_id": case["case_id"], "experiment": case["experiment"], **d} for d in details]
    return row, details


def expand(config: dict) -> list[dict]:
    """Cartesian product of every ``[[sweep]]`` block; lists are axes, scalars are fixed. ``seeds = n`` replicates."""
    import itertools

    base_seed = int(config.get("seed", 2026))
    cases = []
    for block in config.get("sweep", []):
        block = dict(block)
        seeds = int(block.pop("seeds", 1))
        axes = {k: v for k, v in block.items() if isinstance(v, list) and k != "stretch"}
        fixed = {k: v for k, v in block.items() if k not in axes}
        for combo in itertools.product(*axes.values()) if axes else [()]:
            for rep in range(seeds):
                case = {**fixed, **dict(zip(axes, combo, strict=True)), "rep": rep}
                cases.append(case)
    for i, case in enumerate(cases):
        case["case_id"] = i
        case["seed"] = base_seed * 1000 + i
    return cases


__all__ = ["EXPERIMENTS", "expand", "run_case", "auroc", "hann_transfer", "replace"]
