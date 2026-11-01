# WO-003 — Real-data validation: injected perturbations vs. baselines (rev 4)

Executor: **VSCode**  Depends on: WO-001 (merged) and WO-002 (estimator, merged)  Executor note: also depends on **WO-005** (anonymous run records) and **WO-006** (calibrated Σ, gain diagnostic) being merged.  Status: **rev 4, issued 2026-11-01. Supersedes rev 3**, per DR-011: adds the §4a feasibility pilot (go/no-go), the LK secondary estimator and gap-width stratification. Rev 3 superseded rev 2 (DR-008) and rev 1 per DR-009. No LPSF output on real data existed when this revision was written. Thresholds below are pre-registered and are not changed after data is seen. If something cannot be run as written, stop and report; don't adapt.

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
- **Patch defaults, estimator, band-pass, integrator and in-sheet window rule:** whatever WO-002 chose and documented, frozen at its merged commit. The one exception is W_max, fixed in step 0.

## 4. Step 0 — cost probe (before any LPSF run on real data)

1. **Choose the I/O path.** Render one crop of w057 by streaming, and the same crop by any faster path you choose (for example a local copy of the needed volume region). The faster path is accepted only if its 81 layers are byte-identical to the streamed render; otherwise use streaming.
2. **Fix the crop count.** Using the measured time per render, set crops per segment, C, so that the whole render plan (original plus every perturbation, every crop, every segment) fits in **≤ 24 h wall-clock**, with C ≥ 2. If C ≥ 2 cannot fit, stop and report to the Planner.
3. **Physical diagnostics on the original renders only**, no LPSF shifts:
   - (a) depth profiles of mean intensity and band-passed variance, giving the measured **sheet thickness, gap and wrap pitch** per crop; set **W_max** = the median sheet thickness, capped at 0.8 × the median pitch;
   - (b) the through-depth correlation r(d) for d = 1–3, in-sheet versus in-gap (void) layers, to separate the point-spread function from material structure (DR-009);
   - (c) the fraction of gap-layer patches with ρ above the in-sheet 25th percentile, as a fixed-pattern artifact indicator.
4. **Record before going on.** Log C, the timings, the placements, W_max and the diagnostics in the provenance log. No LPSF shift or offset numbers are computed in step 0.

## 4a. Feasibility pilot: go/no-go before the main study (DR-011)

**Data:** one **held-out** PHerc0139 segment, not among the four study segments and not used later. Choose it by a seeded random draw among segments on volume `20260102150214` with valid tifxyz, and record the choice before rendering. Use two 2048-px crops.

1. **Physical measurements** with WO-006's `gain_map` on the original renders:
   - the distributions of L, ℓ_along, ℓ_across and fibre angle;
   - r(d) in-sheet against in-gap (void), as in step 0(b), to settle whether depth decorrelation is material.
2. **Two pilot perturbations** per crop, rendered for real:
   - a sinusoidal corrugation (A = 10 µm, λ = 0.6 mm) with its tilt direction **along** the dominant fibre direction;
   - the same with its tilt direction **across** it.
3. **Paired LPSF**, full and directional, using the calibrated Σ.

**GO, pre-registered, all three required:**
- (i) the across-fibre case, full or directional estimate, has a signed slope ratio against window-averaged truth of 0.7–1.3, with a 95% block-bootstrap CI excluding 0;
- (ii) the confident-wrong-sign rate is ≤ 10% for the estimate that will be used (full if it passes the along-fibre case as well, otherwise directional);
- (iii) |predicted − measured gain| ≤ 0.3 on both cases.

**Outcomes:**
- **GO with full estimate** if the along-fibre case also meets (i) and (ii). Otherwise **GO with directional**, and WO-003 runs with `directional=True` everywhere.
- **NO-GO** otherwise. Stop, write `reports/2026-11-wo003/pilot.md`, and return to the Planner. The main study does not run.

Pilot numbers are reported in full whatever the outcome. The pilot segment's data is never reused in S1–S3.

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

- **LPSF**, with the frozen WO-002 configuration: band-passed layers; **s**, ρ, Σ; metric-corrected gradient **g**; ĥ by the screened weighted solve; the consistency residual ‖∇z* − **g**‖; the curl map (diagnostic only). Compute paired differences against the original.
- **B1, brightest-layer snap.** k* from the mean-intensity depth profile per patch, giving the offset (`offset_sweep` context).
- **B2, `vc_objrefine` as a black box.**
  - Run it on the original and on each perturbed mesh with its **default** parameters from the image of record (record the JSON).
  - Its correction is the refined mesh minus the input mesh, along **n**, on the stored grid. The paired difference is compared with −h_inj.
  - If its output is not on the input grid, or it will not run on a crop, record B2 as "not comparable" with the reason. Do not tune its parameters.
- **B4, structure-tensor normal.** Per patch, the tilt of the mesh normal relative to the sheet normal from the 3D structure tensor of the CT. Use `vesuvius.compute_st` if it runs on the crop region; otherwise a documented Gaussian-derivative structure tensor with scales chosen from step 0, frozen before LPSF runs. Integrate it with the same solver to get ĥ_B4.
- **B3, TIFXYZ Doctor.** Run its normal-offset cue if it runs on these meshes (check the license first); otherwise record why not.
- **Secondary estimator (pre-specified, DR-011):** LK with the same frozen settings. All S1–S3 numbers are reported for both; the gate uses phase correlation.
- **Stratification.** Patch contrast (std) tertiles and structure-tensor coherence tertiles.
- **Gap-width stratification (pre-specified secondary, DR-011):** local gap between wraps from step 0 (clear > 10 voxels / narrow 3–10 / touching < 3). Report S2 and the value claim (LPSF, B4, fusion) per stratum. Hypothesis: B4 leads where gaps are clear; LPSF or the fusion helps where wraps touch.

## 7. Pre-registered success criteria

**Resampling.** Spatial block bootstrap: 256 × 256 px blocks drawn with replacement within each segment (segments are fixed strata), 2,000 replicates. **Ground truth is always window-averaged** with the estimator's own spatial weighting, applied to the realized (metric-corrected) ∇h_inj on the pixel grid. Point slopes are never used.

- **S1, tilt physics on real texture.** On the corrugation family, with paired shifts Δ**s** = **s**(perturbed) − **s**(original), metric-corrected, in patches above the 25th percentile of ρ with window-averaged tilt ≤ 12°:
  - the regression slope of the **signed** component of Δ**g** along the window-averaged ∇h_inj direction, against |window-averaged ∇h_inj|, is 1 ± 0.2 at Δd = 1;
  - *and* the Δd = 2 slope is within ±0.3 of the Δd = 1 slope (P1, by layer subsampling).
- **S2, offset recovery against baselines.** On corrugations and bumps, the paired RMSE of ĥ against window-averaged h_inj is at least 20% lower than B1's, and the 95% CI on the difference excludes 0. **Report the same comparison against B4, B2 and B3.** Not gated, but it decides the value claim below.
- **S3, failure detection.** Step-line labels:
  - positive: patch centre within P/4 of the line;
  - buffer, excluded: between P/4 and P;
  - negative: at least P.
  For steps ≥ 25 µm, AUROC ≥ 0.9 for the **consistency residual ‖∇z* − g‖**, and not lower than B1, B2, B3 or B4 (each with its own natural detector: |∇ĥ| for B1 and B4) where available. Also report partial AUROC at FPR ≤ 0.05.

**Gate:**
- S1 and S3 pass → BACKLOG integration plus a progress-prize draft for Planner review.
- S1 passes, S2 and S3 fail → negative-result report.
- S1 fails → stop; Planner records it.

**Value claim, also pre-registered.** LPSF is presented as a better tilt/offset signal only if its S2 RMSE beats B4's with a CI excluding 0. If B4 is as good or better, we test the **fusion** (both gradient fields in one weighted solve). LPSF is then presented as complementary only if the fusion beats B4 alone with a CI excluding 0. Otherwise the report says plainly that the structure-tensor normal already does this job.

## 8. Exploratory (not gated; label as exploratory in the report)

- **w044 on the March scan.** Mesh `…-on-20260319133554-2.403um`, where #1912 reports ink ~96 µm off the mesh. Prediction from method-lpsf §2: little shift field, because a constant offset is invisible to the shift. k* may sit at the stack edge.
- **w034–w036 region.** Measured crossings in #2167 and the ChaseHendrick notes. Describe what LPSF shows; do not claim detection.
- **Sheet-pitch step**, from §5.

## 9. Deliverables

- **Additional command** `vch diagnose` for step 0 (depth profiles, r(d), gap-layer check), at the same UX floor.
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
