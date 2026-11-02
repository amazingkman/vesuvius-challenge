# Figure register

Every tracked image must be listed here (`docs/security.md` R3, WO-005). The pre-commit hook and CI reject any image file that is not.

Allowed provenance classes:

- `synthetic`: generated entirely from synthetic data, with no scroll data involved.
- `field-map`: a QC field shown on its own, with no render underneath.

**Render-derived images are never allowed**, whatever they show.

| Path | Provenance | Generating command |
|---|---|---|
| `reports/2026-11-wo002/generated/fig1-p1p2-slope.png` | synthetic | `uv run vch synth report reports/2026-11-wo002/sweeps/wo002-20261101T191224 reports/2026-11-wo002/sweeps/wo002-fibre-20261101T195301 --out reports/2026-11-wo002/generated` |
| `reports/2026-11-wo002/generated/fig2-min-detectable-tilt.png` | synthetic | `uv run vch synth report reports/2026-11-wo002/sweeps/wo002-20261101T191224 reports/2026-11-wo002/sweeps/wo002-fibre-20261101T195301 --out reports/2026-11-wo002/generated` |
| `reports/2026-11-wo002/generated/fig3-offset-recovery.png` | synthetic | `uv run vch synth report reports/2026-11-wo002/sweeps/wo002-20261101T191224 reports/2026-11-wo002/sweeps/wo002-fibre-20261101T195301 --out reports/2026-11-wo002/generated` |
| `reports/2026-11-wo002/generated/fig4-step-detection.png` | synthetic | `uv run vch synth report reports/2026-11-wo002/sweeps/wo002-20261101T191224 reports/2026-11-wo002/sweeps/wo002-fibre-20261101T195301 --out reports/2026-11-wo002/generated` |
| `reports/2026-11-wo002/generated/fig5-failure-envelope.png` | synthetic | `uv run vch synth report reports/2026-11-wo002/sweeps/wo002-20261101T191224 reports/2026-11-wo002/sweeps/wo002-fibre-20261101T195301 --out reports/2026-11-wo002/generated` |
| `reports/2026-11-wo002/generated/fig6-patch-size.png` | synthetic | `uv run vch synth report reports/2026-11-wo002/sweeps/wo002-20261101T191224 reports/2026-11-wo002/sweeps/wo002-fibre-20261101T195301 --out reports/2026-11-wo002/generated` |
| `reports/2026-11-wo002/generated/fig7-orientation.png` | synthetic | `uv run vch synth report reports/2026-11-wo002/sweeps/wo002-20261101T191224 reports/2026-11-wo002/sweeps/wo002-fibre-20261101T195301 --out reports/2026-11-wo002/generated` |
