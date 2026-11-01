# WO-003 — Real-data validation: injected perturbations vs. baselines (rev 2)

Executor: **VSCode**  Depends on: WO-001 (merged) and WO-002 (estimator, merged)  Status: **rev 2, issued 2026-11-01. Supersedes rev 1 (2026-10-31)** per DR-008. No LPSF output on real data existed when this revision was written. Thresholds below are pre-registered and are not changed after data is seen. If something cannot be run as written, stop and report; don't adapt.

## 1. Objective

Find out whether LPSF recovers known, injected normal-offset errors on **real** papyrus texture better than existing baselines, and where it fails. This is the decision gate for DR-002.

## 2. Background & citations

- Design: `docs/method-lpsf.md` §2 and §5. The paired difference ĥ(perturbed) − ĥ(original) cancels the unknown pre-existing error. **Perturbed renders must be real re-renders of perturbed meshes, never layer-axis resampling of the original** (method-lpsf §5).
- Data, renderer and conventions: DR-008; `reports/2026-11-wo001/` (layer k₀ = (K−1)/2; rising k along −n of `vesuvius`; `--group-idx 0`; tifxyz format, `scale` 0.05, validity rule z > 0).
- Baselines and prior results to cite and compare against: `offset_sweep`, `segmata`, `vc_objrefine_pr2224`, `tifxyz_doctor`.
- The prize page asks analytic tools to show they "facilitated improvements… e.g. by detecting failure-cases of existing methods on real scroll data" [`scrollprize_prizes`].

## 3. Data and render settings (fixed)

- **Scroll and volume:** PHerc0139, volume `20260102150214` (2.399 µm). Segments w043 `20260112000000`, w057 `20260127000000`, w044 `20260115000000`, w058 `20260210000000`. Native `-on-20260102150214` meshes only.
- **Render:** `--num-slices 81 --slice-step 1 --scale 1 --group-idx 0`, giving k₀ = 40 and a ±40 voxel (±96 µm) stack.
- **Crops:** 2048 × 2048 px (≈ 4.9 × 4.9 mm). Place them by a seeded random draw inside each mesh's valid area, rejecting any crop with less than 95% valid vertices. The seed and placements are recorded before rendering.
- **Patch defaults:** whatever WO-002 chose and documented, frozen at its merged commit.

## 4. Step 0 — cost probe (before any LPSF run on real data)

1. **Choose the I/O path.** Render one crop of w057 by streaming, and the same crop by any faster path you choose (for example a local copy of the needed volume region). The faster path is accepted only if its 81 layers are byte-identical to the streamed render; otherwise use streaming.
2. **Fix the crop count.** Using the measured time per render, set crops per segment, C, so that the whole render plan (original plus every perturbation, every crop, every segment) fits in **≤ 24 h wall-clock**, with C ≥ 2. If C ≥ 2 cannot fit, stop and report to the Planner.
3. **Record before going on.** Log C, the timings and the placements in the provenance log. No LPSF numbers are computed in step 0.

## 5. Perturbations

Perturbations are applied to stored tifxyz vertices along **n**, using the VC3D / layer-increasing convention. With `vesuvius.tifxyz` normals, that means `−n_vesuvius`. Each family uses one fixed seed.

| Family | Parameters | Purpose |
|---|---|---|
| Sinusoidal corrugation, h = A·sin(2π·x′/λ) along a random direction | A ∈ {5, 10, 20} µm × λ ∈ {0.3, 0.6, 1.2} mm (local slopes ≈ 1.5° to 23°) | S1 (tilt physics), S2 |
| Gaussian bump | A ∈ {10, 20, 40} µm × σ ∈ {0.15, 0.3} mm, centered at a seeded position | S2 (offset recovery) |
| Step along a seeded random line | {10, 25, 50} µm | S3 (failure detection) |
| Step, exploratory | ≈ one sheet pitch (110 µm) | Reported, not gated |

- **Ground truth.** The realized displacement field on the render pixel grid, computed from the perturbed versus the original tifxyz at full resolution, projected on **n**.
- **S0 check, required.** Run `vch verify-io` on every perturbed render. It must show r ≥ 0.98 and best offset 0 at k₀. A perturbed render that fails is excluded and listed.
- **Clipping.** Perturbations that push any vertex invalid (z ≤ 0) are clipped at the mesh edge and reported.

## 6. Estimation and baselines (same renders for every method)

- **LPSF.** **s**, ρ, Σ on adjacent pairs; ĥ by integration; curl map. Compute paired differences against the original.
- **B1, brightest-layer snap.** k* from the mean-intensity depth profile per patch, giving the offset (`offset_sweep` context).
- **B2, `vc_objrefine` as a black box.**
  - Run it on the original and on each perturbed mesh with its **default** parameters from the image of record (record the JSON).
  - Its correction is the refined mesh minus the input mesh, along **n**, on the stored grid. The paired difference is compared with −h_inj.
  - If its output is not on the input grid, or it will not run on a crop, record B2 as "not comparable" with the reason. Do not tune its parameters.
- **B3, TIFXYZ Doctor.** Run its normal-offset cue if it runs on these meshes (check the license first); otherwise record why not.
- **Stratification.** Patch contrast (std) tertiles and structure-tensor coherence tertiles.

## 7. Pre-registered success criteria

Bootstrap confidence intervals resample patches within crops within segments, with 2,000 resamples.

- **S1, tilt physics on real texture.** On the corrugation family, in patches above the 25th percentile of ρ and with local slope ≤ 12°:
  - the regression slope of |**s**|/Δd on sin θ_local is 1 ± 0.2 at Δd = 1;
  - *and* the Δd = 2 slope is within ±0.3 of the Δd = 1 slope (P1, by subsampling layers).
- **S2, beats baselines on offset recovery.** On corrugations and bumps, the paired RMSE of ĥ versus h_inj is at least 20% lower than B1's, with a 95% CI on the difference that excludes 0. Report the same comparison against B2 and B3 where available; it is not gated.
- **S3, detects failures.** For steps of 25 µm or more, step-line localization AUROC is ≥ 0.9 for the curl residual or |∇ĥ|, and not lower than B1, B2 or B3 where they are available.

**Gate:**
- S1 and S3 pass → BACKLOG "LPSF → `vc_objrefine` integration" and a progress-prize draft for Planner review.
- S1 passes, S2 and S3 fail → write a negative-result report.
- S1 fails → the model does not transfer to real texture; stop, and the Planner records it in decisions.md.

## 8. Exploratory (not gated; label as exploratory in the report)

- **w044 on the March scan.** Mesh `…-on-20260319133554-2.403um`, where #1912 reports ink ~96 µm off the mesh. Prediction from method-lpsf §2: little shift field, because a constant offset is invisible to the shift. k* may sit at the stack edge.
- **w034–w036 region.** Measured crossings in #2167 and the ChaseHendrick notes. Describe what LPSF shows; do not claim detection.
- **Sheet-pitch step**, from §5.

## 9. Deliverables

- **Commands** `vch perturb` (tifxyz writer via `vesuvius.tifxyz.write_tifxyz`, plus the families above) and `vch validate`, which orchestrates render, S0, estimate, baselines and metrics. Both are resumable and at the python-lab-ux floor, with a live stats panel; long runs show the render queue ETA.
- **Report** `reports/2026-11-wo003/report.md`, containing:
  - step 0 numbers;
  - S0 exclusions;
  - S1–S3 with CIs;
  - stratified tables;
  - baseline availability;
  - an **honest failure section**;
  - the exploratory section;
  - compute used;
  - full citations.
- **Figures:** field maps only (ĥ, curl, ρ, **s**). **No render-derived images in the repo** (DR-008). Example patches go to `data/derived/figures/` for Kevin and Planner review.
- README and CHANGELOG, plus a gate-outcome note for the Planner.

## 10. Out of scope

- Paris 4 and FASP `state.tif` (DR-008);
- tag-based analysis;
- changes to villa or VC3D;
- building VC3D from source;
- refinement loops;
- anything public;
- GPU acceleration (if CPU time blocks step 0, stop and report).

## 11. Provenance log (executor appends below)

---
