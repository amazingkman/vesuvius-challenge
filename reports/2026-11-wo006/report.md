# WO-006 report: Σ calibration, decorrelation-gain diagnostic, across-fibre estimate

Executor: VSCode. Date: 2026-11-02. Covers WO-006 with Addendum 1. Synthetic data only: no scroll data, Podman or GPU.

Every number comes from saved runs, except two ad-hoc checks marked as such. The tables and figures are in `generated/`, and this file interprets them. Cited protocol parameters are from `angelotti2026`, through DR-013.

| Run | Seeds | Cases | Role |
|---|---|---|---|
| `wo006-calibration-20261102T022756` | 0–4 | 1,400 | Fits κ and f; read by nothing else |
| `wo006-evaluation-20261102T025614` | 5–9 | 1,400 | Verdicts. Ran only after κ and f were committed |
| `wo006-processed-20261102T030915` | 5–6 | 1,792 | Addendum 1 |

Each cell holds fibre-to-tilt angles 0–90° in 15° steps, θ = 1, 2, 5, 10°, SNR 6, both estimators, on A1, two-layer and realistic L = 2, 4.3, 8. The WO asks for 2 seeds per cell on the evaluation split; I ran all 5 of its seeds.

```bash
uv run vch synth run --config configs/synth/wo006-calibration.toml
uv run vch synth calibrate runs/synth/wo006-calibration-<timestamp> --out reports/2026-11-wo006/calibration.json
uv run vch synth run --config configs/synth/wo006-evaluation.toml
uv run vch synth run --config configs/synth/wo006-processed.toml
uv run vch synth wo006-report reports/2026-11-wo006/calibration.json runs/synth/wo006-evaluation-<timestamp> runs/synth/wo006-processed-<timestamp> --out reports/2026-11-wo006/generated
```

Patch-level tables are 8–12 MB each, too large to commit. `sweeps/` holds each run's `cases.parquet` and `run.json`. Seeds are fixed, so a rerun rebuilds the patches, and §9 gives their SHA-256 hashes to check against.

## 1. Bottom line

1. **All three pre-registered criteria FAIL.** None was changed after seeing results.
2. **The directional estimate fixes the sign reversal.** At L = 4.3 its slope ratio is 0.82–1.10 at every angle from 15° to 90°, where the full estimate reads −0.43 to 1.04. It fails its criterion on confident wrong signs, not on slope.
3. **Those wrong signs come from Σ, not from bias.** At L = 4.3 they fall with tilt: 20.9% at 1°, 13.2% at 2°, 4.1% at 5°, 1.5% at 10°.
4. **No single κ and f suits every texture.** κ = 2.95, f = 0 gives no confident wrong signs in A1 and two-layer, and two-layer coverage of 0.936, but A1 over-covers at 0.997 and realistic mode covers only 0.35–0.44. Σ is about 3.5× too small in realistic mode even across fibres, where the slope is unbiased (sd(z) = 3.5 after calibration).
5. **`gain_map` is usable where decorrelation is mild.** Within tolerance for 85% of L = 8 cells, 42% at L = 4.3 and none at L = 2, where 69% of patches are flagged. Along the true tilt the first two rise to 96% and 58%, so part of the error is the tilt direction, not the gain model.
6. **Processed noise behaves as DR-013 predicted.** It shrinks the gain toward 0 and never reverses it. Reversal needs material decorrelation. At SNR 2 it does break the white-noise calibration: A1 coverage falls to 0.81.

## 2. Verdicts

| Criterion | Result |
|---|---|
| Calibration: coverage 0.90–0.98, confident wrong sign ≤ 2.5%, A1 and two-layer | **FAIL.** A1 coverage 0.997 is above the band; two-layer 0.936 is inside. Wrong sign 0 in both |
| Directional, L = 4.3, every angle: slope 0.8–1.2 and wrong sign ≤ 2.5% | **FAIL.** Slope 0.82–1.10 passes where it is defined. Worst wrong sign 0.206 fails. **0° is not estimable** (§5) |
| Gain: \|predicted − measured\| ≤ 0.25 for gains in [0, 1.2] | **FAIL.** 61% of 100 cells within tolerance, worst 1.94 |
| WO-002 defaults unchanged, apart from κ, f, `gain_map`, `directional` | **PASS,** with one consequence: `integrate` now uses calibrated Σ, as DR-011 item 4 requires (§3) |
| Tests and CI green; no images outside the register | **PASS** locally, 261 tests and 17 selftest checks. CI status is on the PR |

The calibration failure is on the safe side, intervals too wide, and misses by 0.017. It is still a failure as written.

## 3. Σ calibration

**Frozen values: κ = 2.95, f = 0**, in `lpsf.Params`, fitted on seeds 0–4 and committed before any evaluation seed ran. WO-002 forecast κ ≈ 2.5–3.5. Calibration-split coverage (A1 0.996, two-layer 0.932) matches the evaluation split (0.997, 0.936), so the fit did not overfit.

**The fit departs from the WO, and this is my decision to check.** Item 1 says to fit on A1, realistic and two-layer. On the calibration split:

| Fit | κ | f | A1 | two-layer | L = 4.3 | Problem |
|---|---|---:|---:|---:|---:|---|
| All modes, as written | 11.2 | 0.57 | 1.00 | 1.00 | 0.98 | With f above 0.51, |g|/σ can never reach 1.96, so no estimate could ever be significant |
| A1 and two-layer (**used**) | 2.95 | 0 | 0.996 | 0.932 | 0.42 | Realistic stays under-covered, and is reported |

**No (κ, f) on a fine grid puts A1 and two-layer in the band together**: 0 of 16,261 points. A1's bias is 1–3% of g and two-layer's is 7–8%, so an interval wide enough for two-layer is too wide for A1. The criterion could not have been met by any one pair.

**Evaluation split, full estimate along the tilt:**

| Mode | Raw coverage* | Coverage | Confident wrong sign |
|---|---:|---:|---:|
| A1 | 0.848 | 0.997 | 0 |
| two-layer | 0.542 | 0.936 | 0 |
| L = 8 | 0.167 | 0.441 | 0.064 |
| L = 4.3 | 0.147 | 0.426 | 0.167 |
| L = 2 | 0.123 | 0.353 | 0.433 |

\* κ = 1, from the calibration split.

- **Estimators:** one pair works for both, with no case for separate values. Coverage is A1 1.000 / 0.994 and two-layer 0.906 / 0.966 (pc / lk).
- **By tilt:** two-layer drops to 0.809 at θ = 10°, the edge of the envelope; A1 stays at 0.987.
- **Why realistic mode resists:** Σ assumes pair errors are independent, and that adjacent pairs differ only by noise. In realistic mode neither holds, and the error scale is set by the texture, not by a constant.
- **Integration:** `integrate` now uses calibrated Σ. Across 12 A1 bump cases the worst RMSE is 0.048 voxels, against 0.049 with raw Σ and a limit of 0.5, so WO-002's offset recovery does not regress. These cases were run ad hoc and are not in the saved sweeps.

## 4. Decorrelation-gain diagnostic

`lpsf.gain_map` returns per-patch L, ℓ_along, ℓ_across, the fibre angle, the predicted gain along the measured tilt, and a flag. Median recovered values in the realistic mode are L ≈ 4.6–4.8 (set to 4.3), and ℓ_along ≈ 4.0 and ℓ_across ≈ 1.35 px, against an expected 1.27 across the fibres.

**A correction to WO-002 §4.** The 1-D formula generalises to a tensor, G = I − (2/L²) T⁻¹, with T the normalised structure tensor. So ℓ(φ)² = cos²φ·ℓ_along² + sin²φ·ℓ_across², an average in ℓ², not in curvature. This changes tilts between the principal directions. A test checks it against a numerical maximum of the correlation model (`tests/test_wo006.py`). `docs/method-lpsf.md` should adopt this form.

| L | Cells in range | Within 0.25 | Along the true tilt | Worst | Patches flagged |
|---:|---:|---:|---:|---:|---:|
| 8 | 54 | 85% | 96% | 0.53 | 0 |
| 4.3 | 36 | 42% | 58% | 0.94 | 0.5% |
| 2 | 10 | 0% | 0% | 1.94 | 69% |

Figure: `generated/fig2-gain.png`. Three causes, in order of size:

1. **At L = 2 the model is out of range.** The prediction is far below 0 while the measured gain is near 1 across fibres. Most of these patches are flagged, as they should be, but the criterion counts them.
2. **The measured tilt direction is imperfect.** Noise along the fibres swings a single patch's g, so `tilt_direction` uses a Σ-weighted mean over neighbours. That lifted one ad-hoc pilot case from 0.22 to 0.55, but at L = 4.3 and 90° the mean prediction is still 0.43, against 0.83 along the true tilt.
3. **Across fibres the measured gain exceeds the model,** the gap WO-002 could not explain: 1.01 measured against 0.83 predicted at L = 4.3 and 90°. It remains unexplained.

I did not tune any of this to pass. Prediction stays a diagnostic.

## 5. Directional estimate

`Params(directional=True)`, off by default. Each pair keeps only its across-fibre information; information is summed over layers and then solved. A direction below `directional_rcond = 0.1` of the strongest counts as unobserved: zero information, no estimate. The integrator leaves it to neighbours and z\*.

**L = 4.3, slope ratio** (figure `generated/fig3-slope-ratio.png`):

| Fibre-to-tilt angle | 0° | 15° | 30° | 45° | 60° | 75° | 90° |
|---|---:|---:|---:|---:|---:|---:|---:|
| Full, pc / lk | −0.33 / −0.41 | −0.22 / −0.43 | −0.04 / −0.08 | 0.35 / 0.32 | 0.64 / 0.69 | 0.95 / 0.97 | 1.01 / 1.04 |
| Directional, pc / lk | n/a | 0.82 / 0.83 | 0.99 / 1.03 | 1.05 / 1.10 | 1.08 / 1.07 | 1.07 / 1.07 | 1.02 / 1.03 |
| Wrong sign, pc / lk | n/a | 0.206 / 0.159 | 0.134 / 0.112 | 0.105 / 0.055 | 0.083 / 0.058 | 0.077 / 0.061 | 0.094 / 0.041 |

**The WO's criterion cannot be evaluated at 0°.** With fibres along the tilt, the observed direction is perpendicular to it, so the truth along it is about zero and a ratio means nothing: only 1.4–3.1% of patches meet the 10% threshold on the truth's share. I report that angle as not estimable, not as a pass. Nothing is wrong there; the estimate correctly says it saw no tilt.

**Wrong signs by tilt, all angles:**

| θ | 1° | 2° | 5° | 10° |
|---|---:|---:|---:|---:|
| L = 8 | 0.152 | 0.084 | 0.018 | 0.003 |
| L = 4.3 | 0.209 | 0.132 | 0.041 | 0.015 |
| L = 2 | 0.209 | 0.161 | 0.081 | 0.043 |

Directional Σ over-covers in A1 and two-layer (0.999 and 1.000) and under-covers in realistic mode (0.38–0.45), the same split as the full estimate. Mean observed rank is 1.0, except two-layer at 1.4, where recto and verso sometimes give two directions.

## 6. Addendum 1: processed noise

White noise through a 3-D Paganin filter, 1/(1 + ℓ²k²) with ℓ = 6.95 voxels (δ/β = 1000, z = 0.22 m, 78 keV, 2.4 µm; DR-013's ≈ 7), then an unsharp mask, c = 4, σ = 1.2 voxels [`angelotti2026`]. It is fixed in the volume, and its standard deviation sets the SNR. Most of its power is at low frequency, so the band-pass removes much of it: its share of band-passed variance is about 2–5% at SNR 6 and 16% at SNR 2. Only the noise is processed here, not the texture.

**(i) Gain against the noise-only expectation.** Figure `generated/fig4-processed-noise.png`, A1 texture:

| Gain range over fibre angles | SNR 6 | SNR 2 |
|---|---:|---:|
| White noise | 0.97–1.00 | 0.93–1.00 |
| Processed noise | 0.93–1.00 | 0.71–0.96 |

The lowest gain in any A1 cell is 0.70, so **noise shrinks and never reverses**. The expectation from void layers follows it but runs high, by up to 0.04 at SNR 6 and 0.15 at SNR 2. In realistic mode the reversal comes from the material: at L = 4.3 the lowest gain is −0.52 with white noise and −0.45 with processed noise at SNR 6, so processed noise pulls it slightly toward 0 and does not cause it.

**(ii) Σ calibration, frozen κ and f, full estimate:**

| Mode | White, SNR 6 | Processed, SNR 6 | White, SNR 2 | Processed, SNR 2 |
|---|---:|---:|---:|---:|
| A1 | 0.996 | 0.955 | 0.999 | **0.813** |
| L = 4.3 | 0.409 | 0.431 | 0.483 | 0.491 |

Confident wrong sign in A1 stays below 0.1%. So the white-noise calibration holds at SNR 6 and under-covers at SNR 2. The real scan's position on that scale is unknown until WO-003 step 0.

**(iii) Can `gain_map` tell the causes apart?** On these synthetic pairs, yes, using void layers (stacks with `num_slices = 41`). Noise raises apparent decorrelation in A1: L drops to 10 at SNR 2. Subtracting the void correlation brings it back, while realistic values barely move:

| SNR 2, processed noise | Raw L | Void-corrected L | Set L |
|---|---:|---:|---:|
| A1 | 10.3 | 41 | ∞ |
| L = 8 | 6.8 | 9.1 | 8 |
| L = 4.3 | 4.4 | 4.8 | 4.3 |

- **Patch-level separation of A1 from realistic (exploratory):** AUROC ≥ 0.999 for L, void-corrected L, their ratio and the isotropy index L²/(2ℓ_along·ℓ_across), including the hardest pair, L = 8. This is an easy synthetic setting, since the noise is exactly as modelled and its level known. It shows the signal exists, not that it will hold on real data.
- **Noise share alone does not separate them:** AUROC 0.19–0.46.
- **The void correction does not improve the gain prediction:** mean error 0.027 against 0.023 for A1, and 0.71 against 0.70 for realistic. Report L_material as a cause indicator, not as a better gain.
- **`L_void`** is 2.6–3.0 voxels for processed noise and 1.4–2.4 for white. The void itself distinguishes them.

## 7. What this means for WO-003

- **Use the directional estimate.** It is the only one with usable slopes across orientations if real data decorrelates.
- **Do not trust small tilts in realistic conditions.** Against the pilot's ≤ 10% wrong-sign bar, L = 4.3 passes for pc at 60–90° and for lk at 45–90°, and fails at smaller angles. At θ ≥ 5° it is at 4.1% and below, pooled over angles. Below 5° it fails.
- **Treat Σ as a lower bound on real data** until step 0 measures L and the void.
- **Stacks need void layers.** `num_slices = 21` gives none; 41 does on a 20-voxel sheet. Without them `gain_map` cannot separate noise from material.

## 8. Recommendations to the Planner

1. **Decide the status of κ = 2.95, f = 0.** It failed as written, and any one pair must fail this criterion. I recommend keeping it as a conservative setting for A1-like data, with Σ recorded as unreliable under decorrelation.
2. **Decide on the fit departure** in §3.
3. **Change the directional criterion's wording.** "Every fibre angle" cannot apply at 0°.
4. **Consider a data-driven Σ next.** Scatter of pair shifts inside the window would respond to texture in a way a global constant cannot. It is new method, so I did not try it.
5. **Update `docs/method-lpsf.md`** with the gain tensor, and record that the void correction identifies a cause without improving the gain.

## 9. Compute and reproducibility

One workstation, 16 threads, no GPU. Commits: calibration `9f46ee8`; evaluation and processed `2c0fa39`, which has `source_sha256` 91214fad2d… in both records. Between the two, κ and f were frozen and the processed-noise FFT was limited to one thread. Neither changes the raw estimates the fit used.

| Run | Workers | Wall | CPU in cases | SHA-256 of `details-orientation.parquet` |
|---|---:|---:|---:|---|
| Calibration | 14 | 11.7 min | 2.71 h | `f6827edf23824049c38cbb5d0682abccf4f6d7967df073b83e23573c139da0fb` |
| Evaluation | 12 | 13.0 min | 2.59 h | `47ef1b4450b0f8769894628cac0abd42c2d052ee6f74cd12a14aa2c94479c339` |
| Processed | 10 | 20.4 min | 3.39 h | `042e3ad933c0b3c68803090f73f527ee4cfda3aa6f343592bed38ffac1809c51` |

One calibration sweep was stopped early and deleted: testing found a bug in the LK directional covariance. The bug did not touch full estimates, but I would not fit from a run with known-bad columns. No result here comes from that run.
