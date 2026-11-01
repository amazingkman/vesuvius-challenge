"""WO-002: isolate the A1 gain overshoot when fibres run across the tilt (orientation sweep finding).

Writes reports/2026-11-wo002/diagnosis-overshoot.json. Synthetic only. Run:
    uv run python scripts/wo002_diagnose_overshoot.py
"""

from __future__ import annotations

from pathlib import Path

from vesuvius_challenge import lpsf
from vesuvius_challenge import synthetic as syn
from vesuvius_challenge.runrecord import RunRecord

OUT = Path("reports/2026-11-wo002/diagnosis-overshoot.json")
ROT = syn.GENERIC_ROTATION_DEG


def run(angle, order=1, wavelength=8.0, snr=None, estimator="pc", theta=5.0):
    original = syn.ndimage.map_coordinates

    def sampler(volume, coords, order_=1, **kw):
        return original(volume, coords, order=order, mode="nearest")

    syn.ndimage.map_coordinates = sampler
    try:
        tex = syn.Texture(orientation_deg=ROT + angle, wavelength=wavelength)
        case = syn.make_case(
            None,
            tex,
            syn.Sheet(snr=snr, thickness=40),
            21,
            1.0,
            seed=31,
            points=syn.tilted_points((544, 64), theta, 0.0),
        )
    finally:
        syn.ndimage.map_coordinates = original
    f = lpsf.estimate(case.layers, 1.0, lpsf.Params(estimator=estimator), metric=case.metric)
    truth = lpsf.patch_average(case.grad_h, f)[..., 1][f.valid].mean()
    return float(f.grad[..., 1][f.valid].mean() / truth)


def main() -> None:
    record = RunRecord("wo002-diagnose-overshoot", {"theta_deg": 5.0, "thickness": 40}, seed=31)
    rows = []
    for angle in (0.0, 45.0, 90.0):
        for order in (1, 3):
            for wavelength in (8.0, 16.0):
                for est in ("pc", "lk"):
                    rows.append(
                        {
                            "fibre_to_tilt_deg": angle,
                            "render_order": order,
                            "wavelength_px": wavelength,
                            "estimator": est,
                            "gain": run(angle, order, wavelength, estimator=est),
                        }
                    )
                    print(rows[-1], flush=True)
    record.results = {"rows": rows}
    record.finish(OUT)


if __name__ == "__main__":
    main()
