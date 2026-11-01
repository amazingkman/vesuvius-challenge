"""WO-002 diagnosis of the sign-reversed slope in realistic-decorrelation mode (Kevin's questions 1-3).

Writes reports/2026-11-wo002/diagnosis-realistic.json. Synthetic data only. Run:
    uv run python scripts/wo002_diagnose_realistic.py
"""

from __future__ import annotations

import json
import time
from dataclasses import replace
from pathlib import Path

import numpy as np

from vesuvius_challenge import lpsf
from vesuvius_challenge import synthetic as syn
from vesuvius_challenge.runrecord import RunRecord

OUT = Path("reports/2026-11-wo002/diagnosis-realistic.json")
THETA = 5.0
FILTERS = {
    "bandpass (default)": {},
    "unfiltered": dict(bp_fine=0.0, bp_coarse=0.0, normalize=False),
}


def tilt_case(texture, sheet, theta=THETA, length=1056, seed=21):
    return syn.make_case(None, texture, sheet, 21, 1.0, seed=seed, points=syn.tilted_points((length, 64), theta, 0.0))


def slope_stats(case, **params):
    f = lpsf.estimate(case.layers, 1.0, lpsf.Params(**params), metric=case.metric)
    truth = lpsf.patch_average(case.grad_h, f)[..., 1]
    ok = f.valid
    g = f.grad[..., 1][ok]
    sd = np.sqrt(f.grad_cov[..., 1, 1][ok])
    z = (g - truth[ok]) / sd
    return {
        "ratio": float(g.mean() / truth[ok].mean()),
        "sd_g": float(g.std(ddof=1)),
        "median_pred_sd": float(np.median(sd)),
        "coverage95": float(np.mean(np.abs(z) <= 1.96)),
        "confident_wrong_sign": float(np.mean((np.sign(g) != np.sign(truth[ok])) & (np.abs(g / sd) > 1.96))),
        "n_patches": int(ok.sum()),
    }


def tilt_moment(texture: syn.Texture, bp=(1.0, 8.0), size=256) -> float:
    """1 / l_t^2: second spectral moment of the band-passed texture along the tilt direction (mesh +u)."""
    f = np.fft.fftfreq(size)
    fy, fx = np.meshgrid(f, f, indexing="ij")
    radius = np.hypot(fx, fy)
    f0 = 1 / texture.wavelength
    w = np.exp(-0.5 * ((radius - f0) / (texture.bandwidth * f0)) ** 2)
    if texture.spread_deg is not None:
        across = np.deg2rad(texture.orientation_deg + 90)
        w = w * np.exp(
            -0.5 * (np.sin(np.arctan2(fy, fx) - across) / np.sin(np.deg2rad(max(texture.spread_deg, 0.5)))) ** 2
        )
    dog = np.exp(-2 * np.pi**2 * bp[0] ** 2 * radius**2) - np.exp(-2 * np.pi**2 * bp[1] ** 2 * radius**2)
    power = (w * dog) ** 2
    a = np.deg2rad(syn.GENERIC_ROTATION_DEG)  # mesh +u expressed in volume (x, y)
    ft = fx * np.cos(a) + fy * np.sin(a)
    return float(np.sum(power * (2 * np.pi * ft) ** 2) / np.sum(power))


def predicted_gain(inv_l2: float, length: float, theta: float) -> float:
    c, s = np.cos(np.deg2rad(theta)), np.sin(np.deg2rad(theta))
    return float(c**2 * (inv_l2 - 2 / length**2) / (c**2 * inv_l2 + 2 * s**2 / length**2))


def main() -> None:
    record = RunRecord("wo002-diagnose-realistic", {"theta_deg": THETA}, seed=21)
    t0 = time.monotonic()
    real = syn.realistic_texture(6.0)
    res: dict = {"realistic_texture": {"corr_length": real.corr_length, "corr_power": real.corr_power}}

    # Q1 and Q2: band-passed vs unfiltered, pc vs lk, with and without the envelope inside the window.
    q12 = []
    for sheet_name, sheet in {
        "thickness 20, SNR 6": syn.Sheet(snr=6.0),
        "thickness 60, noiseless": syn.Sheet(snr=None, thickness=60),
    }.items():
        for tex_name, tex in {"realistic": real, "a1": syn.Texture()}.items():
            case = tilt_case(tex, sheet)
            for filt, kw in FILTERS.items():
                for est in ("pc", "lk"):
                    q12.append(
                        {
                            "sheet": sheet_name,
                            "texture": tex_name,
                            "filter": filt,
                            "estimator": est,
                            **slope_stats(case, estimator=est, **kw),
                        }
                    )
    res["q1_q2_filter_and_estimator"] = q12

    # Q3a: does the generator drift in-plane between depth slices? Correlate texture slices directly (no renderer).
    rng = np.random.default_rng(5)
    block = syn.texture_3d((24, 512, 512), 12.0, real, rng)
    drifts = []
    for lag in (1, 2, 3):
        pairs = []
        for z in range(0, 24 - lag):
            a = block[z].reshape(8, 64, 8, 64).transpose(0, 2, 1, 3).reshape(-1, 64, 64)
            b = block[z + lag].reshape(8, 64, 8, 64).transpose(0, 2, 1, 3).reshape(-1, 64, 64)
            pairs.append(lpsf.phase_correlate(a, b, lpsf.Params()).shift)
        s = np.concatenate(pairs)
        drifts.append(
            {
                "lag_voxels": lag,
                "mean_shift_v": float(s[:, 0].mean()),
                "mean_shift_u": float(s[:, 1].mean()),
                "sd_shift": float(s.std()),
                "n": int(len(s)),
            }
        )
    res["q3_generator_slice_drift"] = drifts

    # Q3b: untilted render in realistic mode (any drift would show as a non-zero mean g).
    flat = tilt_case(real, syn.Sheet(snr=6.0), theta=0.0, length=2080)
    f = lpsf.estimate(flat.layers, 1.0, lpsf.Params(), metric=flat.metric)
    g = f.grad[f.valid]
    res["q3_untilted_render"] = {
        "mean_g_v": float(g[:, 0].mean()),
        "mean_g_u": float(g[:, 1].mean()),
        "se_g": float(g.std(ddof=1) / np.sqrt(len(g))),
        "n_patches": int(len(g)),
    }

    # Q3c: mechanism. Vary the through-thickness length L and the texture anisotropy; compare with the first-order
    # prediction gain = c^2 (1/l^2 - 2/L^2) / (c^2/l^2 + 2 s^2/L^2), l from the band-passed spectrum along the tilt.
    mech = []
    thick = syn.Sheet(snr=None, thickness=60)
    for spread in (25.0, None):
        for fibre in (30.0, 30.0 + 90.0):
            if spread is None and fibre != 30.0:
                continue
            for length in (2.0, real.corr_length, 8.0, 16.0, 64.0):
                tex = replace(real, corr_length=length, corr_power=2.0, spread_deg=spread, orientation_deg=fibre)
                case = tilt_case(tex, thick)
                inv_l2 = tilt_moment(tex)
                for est in ("pc", "lk"):
                    s = slope_stats(case, estimator=est)
                    mech.append(
                        {
                            "spread_deg": "iso" if spread is None else spread,
                            "fibre_to_tilt_deg": round(fibre - syn.GENERIC_ROTATION_DEG, 1),
                            "corr_length": length,
                            "estimator": est,
                            "l_t": float(1 / np.sqrt(inv_l2)),
                            "predicted_gain": predicted_gain(inv_l2, length, THETA),
                            "measured_gain": s["ratio"],
                            "coverage95": s["coverage95"],
                            "confident_wrong_sign": s["confident_wrong_sign"],
                        }
                    )
    res["q3_mechanism"] = mech
    record.results = res
    record.results["seconds"] = time.monotonic() - t0
    record.finish(OUT)
    print(json.dumps(res, indent=1)[:6000])


if __name__ == "__main__":
    main()
