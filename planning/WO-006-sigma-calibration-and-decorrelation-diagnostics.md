# WO-006 — Σ calibration, decorrelation-gain diagnostic, across-fibre directional estimate

Executor: **VSCode** (synthetic only)  Depends on: WO-002 merged; WO-005 merged or in parallel (no file overlap except README/CHANGELOG)  Status: issued 2026-11-01 (DR-011). Must merge before the WO-003 pilot.

## 1. Objective

Make LPSF's uncertainty trustworthy, and make its known real-data failure mode (the depth-decorrelation pull) **visible per patch and avoidable**, validated on the WO-002 synthetic modes before any real data is used.

## 2. Background

`reports/2026-11-wo002/report.md`: §4 (mechanism and the gain ≈ 1 − 2ℓ_t²/L²), §6 (Σ too small by about 1.6–1.9× within the envelope; LK overconfident along fibres; confident wrong signs in realistic mode), §9 (frozen defaults). DR-011. `docs/method-lpsf.md` §4.

## 3. Deliverables

1. **Σ calibration** (`lpsf.calibrate`):
   - Inflation κ and a relative floor f (σ² ← κ²·σ² + (f·|g|)²), fitted on A1, realistic and two-layer synthetic cases inside the validity envelope.
   - The fit uses a **calibration split** (seeds 0–4), and the reported numbers come from a **disjoint evaluation split** (seeds 5–9).
   - κ and f are frozen in `Params` at merge. One pair applies to both estimators unless the evaluation split shows they need separate values; report either way.
2. **Decorrelation-gain diagnostic** (`lpsf.gain_map`). Per patch, estimate from the band-passed layers inside the depth window:
   - L, the through-depth correlation length (fit r(Δz) at Δz = 1–3);
   - the in-plane correlation lengths ℓ_along and ℓ_across along the structure tensor's principal directions;
   - the predicted gain along any direction, g_pred(φ) = 1 − 2ℓ(φ)²/L², clipped and flagged where the first-order model is outside its range.
   Output: per-patch fields L, ℓ_along, ℓ_across, the fibre angle, and the predicted gain along the measured tilt direction.
3. **Directional estimate** (`Params(directional=True)`):
   - Project each layer pair's information onto the across-fibre direction(s) only. The along-fibre component is reported as **unobserved**, with infinite variance, not estimated.
   - Sum information across layers before solving, so recto and verso can jointly cover two directions where both are present.
   - The solver must handle rank-deficient patches by leaving the unobserved direction to neighbours and the z* screening term.
4. **Synthetic validation** (extend `configs/synth/`):
   - fibre-to-tilt angles 0–90° in 15° steps;
   - modes A1, realistic (L = 2, 4.3, 8) and two-layer;
   - θ ∈ {1, 2, 5, 10}° inside the envelope; SNR 6; 2 seeds per cell on the evaluation split.
   Report:
   - (a) calibrated coverage and confident-wrong-sign rate, for the full and directional estimates;
   - (b) predicted against measured gain;
   - (c) slope ratio of the directional estimate against window-averaged truth projected on the observed direction.
5. A report `reports/2026-11-wo006/report.md`, built from saved runs; README and CHANGELOG entries.

## 4. Acceptance criteria (pre-registered)

- **Calibration** (evaluation split, inside the envelope, A1 and two-layer): coverage 0.90–0.98, and confident-wrong-sign ≤ 2.5%.
- **Directional estimate in realistic mode** (L = 4.3), every fibre angle: slope ratio on the observed component 0.8–1.2 *and* confident-wrong-sign ≤ 2.5%.
- **Gain prediction:** |predicted − measured gain| ≤ 0.25 for gains in [0, 1.2] across the realistic grid. Report where it fails rather than tuning to pass.
- **No change to the frozen WO-002 defaults** other than adding κ, f, `gain_map` and the `directional` option (default `False` until WO-003's pilot decides).
- Tests and CI green; no images outside the figure manifest (WO-005 amendment).

## 5. Out of scope

Real data; correcting slopes by predicted gain (diagnostic only, so far); changing P, the band-pass or the window rule.

## Addendum 1 — 2026-11-01 (Planner, DR-013; binding)

Add a **processed-noise mode** to the synthetic generator. Generate independent white noise and pass it through:
- (a) a Paganin filter, 1/(1 + ℓ²k²) with ℓ = √(z·λ·(δ/β)/4π) for δ/β = 1000, z = 0.22 m, E = 78 keV (ℓ ≈ 7 voxels at 2.4 µm), applied in 3-D;
- (b) an unsharp mask, (1 + c)·I − c·G_σ(I) with c = 4 and σ = 1.2 voxels.
The noise is fixed in volume coordinates: it does not move with the sheet.

Run the realistic and A1 grids with this noise at SNR 6 and SNR 2 and report:
- (i) the gain against noise-only expectations, which predict shrinkage toward 0 rather than reversal;
- (ii) Σ calibration with and without it;
- (iii) whether `gain_map` can tell processed noise from material decorrelation, using the anisotropy of the depth correlation and comparisons with void regions.

Cite `angelotti2026` for the protocol parameters.

## 6. Provenance log (executor appends below)

---
