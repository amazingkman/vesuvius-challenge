# WO-003 — Real-data validation: injected perturbations vs. baselines

Executor: **VSCode**  Depends on: WO-001 (segments, render wrapper, tifxyz format) and WO-002 (estimator, merged)  Status: issued 2026-10-31. Thresholds are pre-registered below and are not changed after data is seen.

## 1. Objective

Find out whether LPSF recovers known, injected normal-offset errors on **real** papyrus texture better than existing baselines, and where it fails. This is the decision gate for DR-002.

## 2. Background & citations

- Design: `docs/method-lpsf.md` §5. The paired difference ĥ(perturbed) − ĥ(original) cancels the unknown pre-existing error.
- Baselines and prior results we must cite and compare against: `offset_sweep` (negative result for brightest-layer snap), `vc_objrefine_pr2224`, `tifxyz_doctor`, `segmata`.
- What counts for the prize page: an analytic tool must show it "facilitated improvements… e.g. by detecting failure-cases of existing methods on real scroll data" [`scrollprize_prizes`].

## 3. Method

1. **Segments:** the 2–4 chosen in WO-001. Work on crops, each about 1–4 cm² of surface.
2. **Perturbations** of the tifxyz vertices along the mesh normals, written as new tifxyz. Each perturbation family uses one fixed seed:
   - ramps: θ ∈ {2, 5, 10, 20}°;
   - Gaussian bumps: amplitude {1, 2, 4, 8} voxels × width {2, 4, 8} patches;
   - steps: amplitude {3, 6, sheet spacing} voxels, along a random line.
3. **Render:** original and every perturbed mesh with `vch render`, using identical flags (`--num-slices 21 --slice-step 1`, plus `--slice-step 0.5` and `2` for P1).
4. **Estimate:** run LPSF on all of them. Compute ĥ and the curl map, and their differences against the original.
5. **Baselines on the same renders:**
   - (B1) brightest-layer snap: k* from mean intensity alone;
   - (B2) the `vc_objrefine` offset report, if present at the pin (WO-001 audit); otherwise record "not available at SHA …";
   - (B3) the TIFXYZ Doctor normal-offset cue, if runnable; otherwise record why not.
6. **Stratification:** patch contrast (std) tertiles and structure-tensor coherence tertiles, to control the texture confound.
7. **Secondary, observational:**
   - if WO-001 found tagged Defective segments: the distribution of LPSF statistics, Approved vs. Defective;
   - if `state.tif` exists: AUROC of median ρ and |curl| for 100 vs. 0, and the 80 (infilled) class reported on its own.

## 4. Pre-registered success criteria

- **S1 (physics holds on real texture):** in patches above the ρ 25th percentile, the slope of |**s**|/Δd vs. sin θ_inj is 1 ± 0.2 for θ ≤ 10°.
- **S2 (beats the baseline):** on the bump family, the paired RMSE of ĥ is at least 20% lower than B1. The bootstrap 95% CI of the difference must exclude 0, resampling patches within segments.
- **S3 (detects failures):** step localization AUROC ≥ 0.9 for the curl residual or |∇ĥ|, and not worse than B1, B2 or B3 where they are available.
- **Gate:**
  - S1 and S3 pass → proceed to BACKLOG item "LPSF → vc_objrefine integration" and prepare a progress-prize submission.
  - S1 passes but S2 and S3 fail → publish the comparison as a negative-result report.
  - S1 fails → the model does not transfer to real data; stop and record it in decisions.md.

## 5. Deliverables

- `vch perturb` (tifxyz writer plus perturbation families) and `vch validate` (orchestrates render, estimate, baselines and metrics), both at the python-lab-ux floor. Long runs need a live stats panel and resumable state.
- `reports/2026-11-wo003/report.md`:
  - S1–S3 results with CIs;
  - stratified tables;
  - an **honest failure section**: where LPSF is wrong, with example patches shown as field maps without the underlying text, per data rules;
  - the secondary analyses;
  - compute used;
  - full citations.
- Figures: the field overlays (ĥ, curl, ρ) follow `docs/data-licensing.md`. No legible text.
- README and CHANGELOG. Draft a gate-outcome note for the Planner to turn into a DR.

## 6. Out of scope

Changes to VC3D/villa; refinement loops; anything public (Kevin and the Planner review first); GPU acceleration (unless profiling shows CPU time is the blocker; then stop and report).

## 7. Provenance log (executor appends below)

---
