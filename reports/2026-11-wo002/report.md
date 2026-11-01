# WO-002 report: LPSF estimator and synthetic-sheet harness

Executor: Cloud. Date: 2026-11-01. Covers WO-002 with addenda 1 and 2 and Kevin's mid-work instructions (realistic-mode diagnosis, Σ-calibration criterion, fibre-orientation sweep, patch-size recommendation). Synthetic data only; no scroll data, Podman or GPU.

Every number here comes from saved runs:

- `sweeps/wo002-20261101T191224/`: main sweep, 1,208 cases, `configs/synth/wo002.toml`;
- `sweeps/wo002-fibre-20261101T195301/`: orientation sweep, 252 cases, `configs/synth/wo002-fibre.toml`;
- `diagnosis-realistic.json` and `diagnosis-overshoot.json`, written by the scripts in `scripts/`.

The full generated tables and figures are in `generated/summary.md` and `generated/fig*.png`; this file interprets them. Reproduce:

```bash
uv run vch synth run --config configs/synth/wo002.toml
uv run vch synth run --config configs/synth/wo002-fibre.toml
uv run vch synth report reports/2026-11-wo002/sweeps/wo002-20261101T191224 reports/2026-11-wo002/sweeps/wo002-fibre-20261101T195301 --out reports/2026-11-wo002/generated
uv run python scripts/wo002_diagnose_realistic.py
uv run python scripts/wo002_diagnose_overshoot.py
```

## 1. Bottom line

1. **The physical model holds where its assumptions hold.** In A1 mode, with the patch well inside the sheet, the ratio of estimate to window-averaged tan θ is 0.96–1.01 for θ = 2–5° at every Δd and SNR ≥ 6 (0.88–1.08 at SNR 2), for both estimators, and 0.98–1.01 at every fibre orientation in the orientation sweep. A 40-voxel sheet at 20° gives 0.360 against a truth of 0.364. Nothing synthetic falsifies P1/P2 *as physics*.
2. **The pre-registered P1/P2 acceptance criterion is not met.** The fitted slope over θ ≤ 20° at P = 64 on the 20-voxel default sheet is 0.08–0.59, because the 20° point collapses (§3). This is a geometric limit of the estimator (patch depth span versus effective sheet thickness), not a failure of the s = Δd·tan θ relation. Restricted to θ ≤ 10°, the slope is 0.93–1.00. Whether that is a DR-002 reversal is the Planner's call; my reading is that it is not, but the criterion as written failed.
3. **Realistic decorrelation (addendum 1) breaks the estimator when fibres run near the tilt direction.** The slope is sign-reversed for fibre-to-tilt angles ≤ 30°, about 0.25–0.5 at 45°, and 0.9–1.1 only at 75–90°. Phase correlation and LK behave the same. The cause is physical, not a bug (§4): a texture that decorrelates through the thickness pulls the match toward constant depth, which is the in-band twin of the envelope trap. **This bears directly on WO-003.** If papyrus texture really decorrelates as the WO-001 numbers suggest (and is not mostly noise or blur), LPSF slopes on real data will be biased by an amount that depends on fibre orientation.
4. **Σ is not calibrated.** No mode meets the new criterion (95% intervals covering the truth in 90–98% of patches, ≤ 2.5% confident wrong signs). A1 comes closest. Realistic mode gives confident wrong signs in up to 81% of patches (§6).
5. **Integration, the consistency residual and the depth window work in A1.** Offset-recovery RMSE is 0.04–0.08 voxel (criterion ≤ 0.5). Step AUROC for ‖∇z* − g‖ is 1.00 at ≥ 3 voxels (criterion ≥ 0.9). The window never leaks into a neighbouring wrap at a 47-voxel pitch. In realistic mode the g-based outputs fail and z* alone does better.
6. **Defaults (frozen, §9):** phase correlation (β = 0, one refinement pass), P = 64 with 50% overlap, DoG band-pass 1–8 px, window fraction 0.9 with w_max = 21 voxels. The estimator benchmark is inconclusive: LK has about 1.5× the median efficiency, but my pre-stated mean rule picked phase correlation (§7).

## 2. Acceptance verdicts

Source: `generated/summary.md` §Acceptance verdicts. Moderate SNR = 6 (fixed before any run; `configs/synth/wo002.toml` header).

| Criterion (addendum 2 item 9, plus Kevin's Σ criterion) | Result |
|---|---|
| Signed slope 1 ± 0.05 for θ ≤ 20°, A1, SNR 6, P = 64 | **FAIL**: pc 0.59 / 0.10 / 0.53 and lk 0.29 / 0.08 / 0.36 at Δd = 0.5 / 1 / 2; the 20° point collapses (§3) |
| — same, θ ≤ 10° only (not pre-registered; for context) | pc 0.975 / 0.957 / 0.997, lk 0.952 / 0.931 / 0.994 |
| A1 at 20°: P = 64 vs P = 32 | **FAIL** for both: ratio pc 0.17 / −0.49, lk 0.04 / −0.88 (§3) |
| Pure offset \|s\| < 0.05 px, A1 | **PASS**: max per-patch \|s\| 0.006 px over offsets −10…10 |
| Pure offset, realistic (not pre-registered) | FAIL: max 0.28 px (per-patch scatter, sd ≈ 0.1) |
| Offset recovery RMSE ≤ 0.5 voxel (amp ≥ 2, width ≥ 4 patches), A1 | **PASS**: worst 0.049 (lk), 0.061 (pc) |
| — realistic | FAIL: worst 1.87 (lk), 1.99 (pc); z* alone 0.54–0.71 |
| P4 ‖r‖ AUROC ≥ 0.9 at amp ≥ 3, A1 | **PASS**: 1.000 (both) |
| — realistic | FAIL: 0.53 (lk), 0.62 (pc); ‖∇z*‖ alone 0.97–1.00 |
| Σ calibrated (coverage 0.90–0.98, confident wrong sign ≤ 2.5%), every mode | **FAIL** in every mode (§6) |
| Tests green, ruff clean, selftest | PASS locally (126 tests, 13 selftest checks); CI could not run, because the push was refused (HTTP 403) |

## 3. P1/P2 and the geometric envelope (P = 64 at 20°)

Figure: `generated/fig1-p1p2-slope.png`. The realistic panels are clipped at −0.4; the full values are in the summary tables.

**A1, SNR 6, ratio of estimate to window-averaged truth:**

| θ | 0.5° | 1° | 2° | 3° | 5° | 10° | 20° | 30° |
|---|---|---|---|---|---|---|---|---|
| pc, Δd 1 | 1.03 | 0.97 | 0.97 | 1.00 | 0.99 | 0.96 | 0.03 | −0.43 |
| lk, Δd 1 | 1.02 | 1.01 | 1.01 | 1.00 | 0.99 | 0.94 | 0.02 | −0.64 |

**Why 20° fails (unmet criterion, geometric reason).** At tilt θ, each layer of a P-px patch spans P·tan θ voxels of depth. At P = 64 and 20° that is 23.3 voxels, more than the 20-voxel sheet, so no layer lies wholly inside the sheet. The binding quantity is the **effective** thickness, not the nominal one. The envelope's tanh edges, about 1.5 voxels each, appear in-plane as features only e/tan θ ≈ 4 px wide at 20°. That is inside the band-pass, so layers whose patch footprint reaches within ~2–3 edge widths of the sheet boundary are biased. The thickness sweep shows the effect directly at P = 64:

| sheet thickness (voxels) | 8 | 12 | 20 | 40 |
|---|---|---|---|---|
| ratio at 10° (pc / lk) | 0.47 / 0.22 | 0.85 / 0.76 | 0.96 / 0.94 | 0.99 / 1.00 |
| ratio at 20° (pc / lk) | −2.3 / −2.4 | −0.91 / −1.08 | −0.04 / −0.03 | 0.99 / 0.99 |

**P = 32 alongside.** P·tan 20° = 11.6 voxels fits inside 20 voxels nominally, but P = 32 still fails at 20° (pc −0.49, lk −0.88). The effective thickness, 20 minus about 6–9 voxels of edge, leaves room for only one or two clean layers, and the 0.9-variance window admits more than that. So halving the patch does not rescue 20° on a 20-voxel sheet. A 40-voxel sheet does.

**Recommended default: P = 64, 50% overlap.** The noise trade-off, from the patch-size sweep (A1, SNR 6, pc / lk):

| P | sd of g at θ = 0 | ratio at 10° | bump RMSE, FWHM 256 px | seconds per patch |
|---|---|---|---|---|
| 32 | 0.0036 / 0.0027 | 0.94 / 0.97 | 0.059 / 0.036 | 0.016 / 0.019 |
| 48 | 0.0023 / 0.0020 | 0.96 / 0.96 | 0.040 / 0.037 | 0.033 / 0.061 |
| **64** | **0.0016 / 0.0015** | **0.96 / 0.94** | **0.058 / 0.042** | **0.057 / 0.12** |
| 96 | 0.0010 / 0.0010 | 0.95 / 0.91 | 0.037 / 0.038 | 0.15 / 0.19 |
| 128 | 0.0008 / 0.0007 | 0.91 / 0.87 | — | 0.71 / 0.42 |

Noise falls about as 1/P; tilt capacity falls as P grows. Bump RMSE does not separate the sizes (0.036–0.059 voxels, one seed each). Real tilt errors are a few degrees (addendum 1 item 2), where P = 64 is within 1–3% of truth and has 2.3× (pc) lower noise than P = 32. P = 32 buys tilt range only on sheets thick enough to use it. For a 20-voxel sheet, P = 64 holds to about 10°. WO-003 step 0 measures thickness; if the real effective thickness is under ~15 voxels, it should rerun this table at that thickness before using P = 64.

## 4. Realistic mode: diagnosis of the sign reversal (Kevin's questions 1–3)

Source: `diagnosis-realistic.json`; figure `generated/fig7-orientation.png`.

1. **It is not the sheet-envelope trap.** With band-passed layers (the default), the reversal persists: ratio −0.70 (pc) / −0.73 (lk) at θ = 5°, thickness 20, SNR 6. It also persists on a noiseless 60-voxel sheet, where no envelope edge enters the window: −0.64 / −0.54. Removing the band-pass makes the thin-sheet case worse (−2.95 / −2.51), because the envelope trap then adds to it. In A1 mode the same band-pass gives 0.99 / 0.99.
2. **Lucas–Kanade reverses too** (figures above). Both estimators converge to a maximum of the inter-layer correlation, so they share any bias of that maximum.
3. **The generator does not drift.** Phase-correlating the realistic texture's own depth slices, with no renderer, gives a mean in-plane shift of 0.003 / 0.007 / 0.021 px at lags of 1 / 2 / 3 voxels (per-pair sd 0.07 / 0.16 / 0.36, about 1,400 pairs each). An untilted realistic render gives mean g = −0.016 ± 0.009 (SE, 64 patches). Neither can produce a −0.06 slope error at 5°.

**Mechanism (derived here, first order).** Adjacent layers through a mesh tilted by θ meet the sheet at points offset by Δd·tan θ in-plane (the A1 match) or at the same depth after an in-plane shift of −Δd/tan θ. When the texture decorrelates with depth (r_z = exp(−Δz²/L²)), the correlation maximum trades the two. With in-plane curvature 1/ℓ_t² along the tilt direction:

  gain = cos²θ·(1/ℓ_t² − 2/L²) / (cos²θ/ℓ_t² + 2 sin²θ/L²) ≈ 1 − 2ℓ_t²/L²  (small θ)

So the sign reverses once ℓ_t > L/√2 ≈ 3 voxels (L = 4.3 in the realistic mode). Along fibres, ℓ_t is long; across fibres, it is short. Test with fibres 6° from the tilt, varying L:

| L (voxels) | 2 | 4.3 | 8 | 16 | 64 |
|---|---|---|---|---|---|
| predicted gain (ℓ_t = 3.6 px) | −5.4 | −0.41 | 0.58 | 0.90 | 0.99 |
| measured, pc / lk | −4.1 / −4.3 | −0.64 / −0.54 | 0.34 / 0.37 | 0.76 / 0.78 | 0.97 / 0.97 |

The sign, the trend and the L → ∞ limit agree. Across fibres (ℓ_t = 1.3 px) and with isotropic texture (ℓ_t = 1.7 px), the formula predicts shrinkage (0.82 / 0.68 at L = 4.3). The measured gains are 1.11–1.14 and 0.90–0.92, less shrinkage than predicted; the first-order model does not explain that part.

**Fibre-orientation sweep** (SNR 6, 2 seeds × 32 patches per cell; ratio / coverage / confident wrong sign, pc at θ = 5°):

| fibre-to-tilt angle | 0° | 15° | 30° | 45° | 60° | 75° | 90° |
|---|---|---|---|---|---|---|---|
| A1 | 0.99 / 0.86 / 0 | 0.98 / 0.72 / 0 | 0.99 / 0.91 / 0 | 1.00 / 0.95 / 0 | 1.00 / 0.97 / 0 | 1.00 / 0.98 / 0 | 1.01 / 0.95 / 0 |
| realistic | −0.19 / 0.12 / 0.50 | −0.14 / 0.17 / 0.41 | 0.11 / 0.08 / 0.39 | 0.37 / 0.23 / 0.27 | 0.70 / 0.16 / 0.19 | 0.88 / 0.16 / 0.06 | 1.03 / 0.11 / 0.02 |
| two-layer | 0.90 / 0.50 / 0 | 0.93 / 0.52 / 0 | 0.93 / 0.39 / 0 | 0.92 / 0.45 / 0 | 0.91 / 0.48 / 0 | 0.90 / 0.45 / 0 | 0.91 / 0.48 / 0 |

LK and θ = 2° / 10° follow the same pattern (`generated/summary.md`). The worst confident-wrong-sign rate is 0.81 (lk, realistic, 10°, fibres along the tilt).

**What WO-003 should know.** The bias depends on two quantities measurable on real renders: the through-thickness correlation length L (WO-003 step 0 already measures it) and the in-plane correlation length of the texture along the tilt direction (structure tensor). On real data the predicted gain could be checked or corrected per patch, but that is method development and not in this WO. It also matters whether WO-001's r(d) reflects material decorrelation or noise and blur (method-lpsf §4 PSF item). Only material decorrelation produces this pull.

## 5. Minimum detectable tilt (addendum 1 item 2)

Detection at 5% false alarms (threshold = 95th percentile of the θ = 0 null over 96 patches) and 80% power; θ ∈ {0, 0.5, 1, 2, 3}°, SNR 6, Δd = 1, P = 64; figure `generated/fig2-min-detectable-tilt.png`.

| | single pair | window (all in-sheet pairs) |
|---|---|---|
| A1, pc | 2.9° (unknown direction), 2.8° (known) | ≤ 0.5° (the smallest tilt tested is already detected) |
| A1, lk | 2.2°, 1.9° | ≤ 0.5° |
| realistic, pc / lk | not reached by 3° | not reached by 3° |

In realistic mode a tilt is "detected" at every orientation only in the sense that |g| exceeds the null, and at fibre angles ≤ 30° the direction is wrong (§4). WO-003 should take the A1 numbers as a lower bound on what real data can do, and the realistic numbers as a warning, not as an MDT.

## 6. Σ calibration (Kevin's criterion) and the aperture problem (P5, addendum 2 item 4)

Coverage = share of patches whose ±1.96σ interval along the tilt contains the window-averaged truth; normalised error z = (g − truth)/σ. All tilt cases, both runs:

| mode | estimator | coverage | sd(z) | confident wrong sign |
|---|---|---|---|---|
| A1 | pc / lk | 0.54 / 0.60 | 24 / 32 | 0.107 / 0.155 |
| realistic | pc / lk | 0.14 / 0.17 | 32 / 81 | 0.55 / 0.57 |
| two-layer | pc / lk | 0.42 / 0.56 | 13 / 13 | 0.021 / 0.003 |

The A1 totals include the 20° and 30° geometric failures. Within θ ≤ 10° in A1, coverage is 0.73–0.86, with sd(z) 1.55–1.88 and a negative mean z (−0.4 to −0.9). So Σ is too small by about 1.6–1.9× in σ, and a residual shrinkage bias of 1–5% dominates at high SNR. In the noiseless limit Σ → 0 while that bias stays, so coverage → 0. Two fixes would follow from this, and **neither is applied** because the defaults are frozen at merge: an empirical inflation κ ≈ 2.5–3.5, and a relative floor of about 3% of |g|. The realistic-mode failures are bias, not variance, and no rescaling of Σ fixes them.

**Aperture (P5), 1-D fibres 6° from the tilt.** Phase-correlation Σ along the fibres is conservative (predicted 8.1e-4 vs empirical 2.8e-4) and accurate across them (6.9e-7 vs 5.8e-7); the condition number of Σ is about 1,800. LK's Σ along the fibres is **overconfident** (predicted 3.2e-4 vs empirical 1.0e-2, a 32× variance ratio). That makes LK more prone to confident wrong signs in unobservable directions (A1: 0.155 vs 0.107).

**Two-layer (recto/verso).** Per-pair Σ is ill-conditioned (condition number 300–800). Summing information over the window removes most of that, but only when the window covers both fibre layers. With the frozen window fraction 0.9, the lower fibre layer's band-passed variance (0.8 of the upper one in this generator) is excluded, and the summed condition number stays 380–630 (pc). At fraction 0.7 it drops to 8–27 (pc, lk). However, 0.7 admits envelope-edge layers and costs slope at 10° in A1: 0.78 vs 0.96 (one ad-hoc case, seed 3, on the fixed code; not in the saved sweeps). The frozen default favours slope accuracy; WO-003 should check recto/verso coverage on real renders.

## 7. Estimator benchmark against the Cramér–Rao bound (addendum 2 item 3)

The bound comes from `crlb.fisher_stack`: the multi-layer Fisher information from the generator's exact texture spectrum, trilinear-interpolated noise and depth correlation. It assumes independent noise per layer, so it is optimistic where Δd < 2. Efficiency = bound / variance across patches:

| mode | pc median (mean) | lk median (mean) |
|---|---|---|
| A1 | 0.092 (0.53) | 0.132 (0.39) |
| realistic | 0.029 (17.3) | 0.045 (11.7) |

Before running, I pre-stated the rule "LK only if its mean efficiency over the realistic configurations exceeds phase correlation's by more than 10%; ties to phase correlation". Applied as stated, it picks **phase correlation**. The realistic means are meaningless, though: they are dominated by cases with efficiency > 1, which a biased estimator can reach against an unbiased bound. By median, LK is about 1.5× more efficient in both modes, and it has better A1 coverage. Against it, LK is overconfident along fibres (§6) and costs about 1.3× the time. I kept phase correlation as the default, per the pre-stated rule and DR-003 (reuse of the existing primitive), and flag the call for the Planner.

Single pair (MDT block, θ = 0, A1, SNR 6): phase correlation reaches 0.59 of the pair bound and LK 1.01, i.e. LK is at the bound for a single pair. Realistic: 0.07 (pc), 0.11 (lk). Pure (whitened, β = 1) phase correlation is far worse on these renders (θ = 10°: 0.079 vs truth 0.176, sd 0.020). Whitening weights out-of-band frequencies, where voxel-grid interpolation residue and isotropic noise live and correlate best at zero shift. β = 0 with one refinement pass gives 0.170 (sd 0.002).

## 8. Other checks

- **P3, z\* tracks offsets:** mean error −0.07 to −0.13 voxel, RMS 0.14, over offsets −10…10 (A1); realistic RMS 0.32–0.71.
- **P6, layers and wraps:** ρ in-sheet 0.996–0.998 (A1). In a gap ρ falls to 0.86 / 0.54 / 0.39 at gaps of 4 / 8 / 27 voxels; it does not reach zero, because interpolation and the band-pass carry noise correlation across one-voxel steps. Across a touching interface the minimum ρ is only 0.80–0.85, because the soft envelope edges blend the two textures over ~3 voxels. **Window leak** into the neighbouring wrap is 0 at a 47-voxel pitch (thickness 20 + gap 27, and touching 47-voxel sheets). It is 20% at a 20-voxel pitch, where w_max = 21 exceeds the pitch, as the rule requires w_max to stay below the pitch.
- **Metric correction (item 1):** with g, ratio 0.98–1.00 at ε = 0 to 0.2. Without g, 0.88 / 0.81 / 0.69 at ε = 0.05 / 0.1 / 0.2, against the predicted (1+ε)⁻² = 0.91 / 0.83 / 0.69.
- **Band-pass (item 2):** with unfiltered layers the slope ratio on 8–20-voxel sheets is +0.28 to −6.2 at 5–10° (sign-reversed in 11 of 12 cells); on 40-voxel sheets it is 0.95–0.97. Band-passed: 0.97–1.00 on 12–40-voxel sheets at 5°, and 0.92–1.00 on 8-voxel sheets.
- **Window-averaged truth (item 8):** against point slopes of a sinusoid, the estimate reads 0.82 / 0.89 / 0.95 / 0.97 (λ = 96 / 128 / 192 / 256 px). The Hann² window transfer predicts 0.83 / 0.90 / 0.96 / 0.98. Against window-averaged truth it reads 0.98–0.99. sinc(P/λ) is the box-window value and under-predicts the attenuation of a Hann² window.
- **Curl (item 6):** along a straight step the curl stays small. At step patches its mean is 0.0003–0.002 px⁻¹, against 0.03–0.27 for ‖r‖ (A1, amplitude 3–8), so about two orders below. It is still above its Monte-Carlo null (amplitude-0 cases, 95th percentile) in 83–100% of step patches, and its AUROC is 0.93–1.00. So it is not ≈ 0 in the strict sense the method doc predicts. The step is drawn at 20° to the patch grid, and the discretised field is not exactly curl-free there.
- **Reference implementations (addendum 1 item 3):** fast path vs skimage on exactly shifted noiseless patches, max error 3e-5 px (selftest: < 0.02 px over 60 hypothesis cases). villa `_phase_correlate` (parabolic peak on a whitened surface) has a mean error of 0.43 px on band-limited noiseless patches and 0.25–0.38 px with noise; its sign convention matches ours. It is **not** accurate enough to be the fast path, so it is cross-checked, not reused (DR-003 considered).

## 9. Frozen defaults (WO-002 addendum 1 item 5)

`lpsf.Params()` as merged. The patch size, overlap and in-sheet window rule are the ones WO-003 must use unchanged:

| parameter | value | why |
|---|---|---|
| `estimator` | `pc` | pre-stated rule (§7) |
| `patch`, `overlap` | 64 px, 0.5 | §3 trade-off |
| `bp_fine`, `bp_coarse` | 1, 8 px (DoG) | removes the envelope at 5–10° on ≥ 12-voxel sheets; keeps 8–16 px texture |
| `normalize` | true (local amplitude + common-support mask) | removes moving texture strips at sheet edges |
| `beta`, `refine` | 0, 1 | whitening fails (§7); refinement removes the window pull |
| **window rule** | E(k) = band-passed variance × ρ, Gaussian prior σ = 20 layers on k₀; hull of layers with smoothed variance ≥ 0.9 × max; `w_max` = 21 voxels; depth smoothing 1.5 layers | never uses s; no leak at a 47-voxel pitch |
| z* | centroid of E(k) over its half-maximum run, cap 41 voxels | P3 |
| `rho_min`, `kappa`, `zstar_sigma` | 0.1, 1.0, 1 voxel | κ is **not** calibrated (§6) |

## 10. Defect found in my own code during this WO

The first estimator realigned layer k+1 with Keys cubic convolution before re-correlating. Its phase error produced a gain of +10% for 8-px texture across the tilt in A1. It was the same with a cubic renderer, and gone with refinement off (`diagnosis-overshoot-keys-resampler.json`). It is now replaced by prefiltered cubic B-spline interpolation: gain 0.97–1.005 at 0°, 45° and 90° for both renderers (`diagnosis-overshoot.json`). All runs reported here use the fixed code (`source_sha256` 9bdc19a6204a in every record).

## 11. Compute used

One cloud container: 4 vCPU, 15 GB RAM, no GPU.

| run | wall | CPU in cases |
|---|---|---|
| main sweep (3 workers) | 40.6 min | 2.03 h |
| orientation sweep (3 workers) | 12.5 min | 0.62 h |
| realistic diagnosis | 9.3 min | — |
| overshoot diagnosis | 6.6 min | — |
| superseded runs (first sweep, killed out of memory after 23 min on 4 workers; Keys-resampler sweeps and diagnoses; not reported) | ≈ 1.5 h | ≈ 4.3 h |

## 12. Recommendations to the Planner

1. Decide whether the P1/P2 failure (geometry at 20° on a 20-voxel sheet) is a DR-002 reversal. The physics holds at θ ≤ 10°, and at 20° on a 40-voxel sheet.
2. Before WO-003 relies on LPSF slopes, settle what WO-001's r(d) is (material decorrelation vs noise and PSF), and measure ℓ_t along typical tilt directions. If it is material, §4 predicts orientation-dependent and possibly sign-reversed slopes.
3. Decide the estimator (§7). The rule picked phase correlation; the medians favour LK.
4. Σ needs a calibration step (κ and a relative floor) before integration weights or QC thresholds rely on it.
5. A follow-up WO could correct the decorrelation gain per patch from measured L and ℓ_t (§4). That is new method and not in scope here.
