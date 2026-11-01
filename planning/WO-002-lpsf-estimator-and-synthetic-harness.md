# WO-002 — LPSF estimator and synthetic-sheet harness (calibration before flight)

Executor: **Cloud** (pure code; no scroll data, Podman or GPU)  Depends on: scaffold commit (can run in parallel with WO-001)  Status: issued 2026-10-31

## 1. Objective

Implement the LPSF estimator from `docs/method-lpsf.md` and test predictions P1–P6 on synthetic 3D papyrus sheets with known ground truth. The deliverable is a calibrated estimator with a **documented failure envelope**, or a documented falsification of the model.

## 2. Background & citations

- Theory, assumptions A1/A2, predictions and failure modes: `docs/method-lpsf.md`.
- Sub-pixel phase correlation: `foroosh2002`, `guizar2008`.
- Gradient-field integration: `frankot1988`.
- The `skimage.registration.phase_cross_correlation` implementation of `guizar2008` is the **slow reference** for the selftest. It is not the fast path.

## 3. Deliverables

1. `src/vesuvius_challenge/synthetic.py`: a generator for 3D volumes containing a papyrus-like sheet.
   - **Texture:** anisotropic band-pass noise with set fiber orientation and wavelength. Modes: (a) through-thickness invariant, satisfying A1; (b) two fiber layers (horizontal then vertical), violating A1.
   - **Geometry:** sheet thickness envelope w; a second parallel sheet at a set gap (for P6); Gaussian and Poisson noise; contrast.
   - **Mesh:** a nominal surface plus an injected normal-offset field h(u,v): constant, ramp (tilt θ), Gaussian bump, or step.
   - **Reference renderer:** trilinear sampling along normals with `num_slices`, `slice_step`. It exists only for synthetic tests; real renders use `vc_render_tifxyz`.
2. `src/vesuvius_challenge/lpsf.py`: the estimator.
   - **Patch tiling:** patch size and overlap are parameters; start at 64 px with 50% overlap. **Choose the default from the results.**
   - **Per patch, per layer pair:** shift **s**, peak correlation ρ, and covariance Σ (structure tensor plus peak curvature).
   - **Batched FFT fast path:** numpy/scipy. Torch is optional and must not be required.
   - **Aggregation across layer pairs:** weighted by ρ, restricted to the in-sheet band.
   - **Depth profile:** k* from ρₖ and the mean intensity.
   - **Integration** to ĥ: Frankot–Chellappa, plus a Σ-weighted sparse least-squares solver. Constant fixed by k*.
   - **Curl residual** map.
3. **CLI**, at the python-lab-ux floor:
   - `vch selftest`: fast path vs. the skimage reference on hypothesis-generated patches (shift error < 0.02 px on noiseless inputs); integration on analytic gradient fields.
   - `vch synth run --config …`: parameter sweeps, with a run record and Parquet output.
   - `vch synth report <run>`: figures and a markdown summary, built from saved runs only.
4. **Tests** in `tests/test_lpsf.py` and `tests/test_synthetic.py`:
   - P1–P6 as executable tests on small volumes, kept fast enough for CI;
   - degenerate cases: a flat patch and pure noise must give low ρ and a large Σ, not confident garbage;
   - known-answer tests for the renderer.
5. **CI:** `.github/workflows/ci.yml` running `uv sync`, `ruff check` and `pytest` on Python 3.14.
6. **Report** `reports/2026-11-wo002/`:
   - estimated vs. true slope for P1/P2 across θ ∈ {0, 1, 2, 5, 10, 20, 30}°, Δd ∈ {0.5, 1, 2}, three SNR levels;
   - offset-recovery RMSE vs. bump amplitude and width;
   - step detection with the curl residual vs. |∇ĥ|;
   - the A1-violation mode, quantified;
   - patch-size trade-off, i.e. the choice of default;
   - **failure envelope**: the θ, SNR and anisotropy where the estimate breaks;
   - compute used.
7. README ("Method" section, pointing to `docs/method-lpsf.md`) and CHANGELOG.

## 4. Acceptance criteria (pre-registered)

- **P1/P2, in A1-satisfying mode at moderate SNR:** fitted |**s**|/Δd vs. sin θ has slope 1 ± 0.05 for θ ≤ 20°. Pure offset gives |**s**| < 0.05 px.
- **Offset recovery:** RMSE(ĥ − h) ≤ 0.5 voxel for bumps with amplitude ≥ 2 voxels and width ≥ 4 patches, at moderate SNR.
- **P4:** step localization AUROC ≥ 0.9 at step amplitude ≥ 3 voxels.
- **If P1 or P2 fails:** the WO still completes. The report states the falsification, and the Planner records it in decisions.md (DR-002 reversal).
- Tests green, ruff clean, CI green, and the selftest passes.

## 5. Out of scope

Real scroll data; Podman; GPU; mesh writing; refinement or integration with VC3D.

## Addendum — 2026-11-01 (Planner, after WO-001; binding)

If WO-002 is already in progress, fold these in. They tighten the WO; they don't change its scope.

1. **Realistic decorrelation.** Add a synthetic texture mode whose through-thickness correlation matches the WO-001 measurement on PHerc0139 at 2.399 µm: r ≈ 0.93, 0.78 and 0.60 at 1, 2 and 3 voxels (`reports/2026-11-wo001/data-survey.md` §9). Run the P1/P2 sweep in this mode as well, and report how it compares with the A1-satisfying mode.
2. **Small angles.** Real tilt errors are mostly a few degrees, so extend the θ sweep with 0.5°, 1° and 3°. Report the **minimum detectable tilt** per patch, and per patch averaged over adjacent pairs, at realistic SNR and decorrelation. WO-003 depends on this number.
3. **Second reference implementation.** Cross-check the fast path against `vesuvius.tifxyz_label_transfer.estimate_canvas_offset._phase_correlate` (villa, MIT, at the pin) as well as skimage, and report agreement. If it is accurate enough to be the fast path, prefer reuse (DR-003). Cite `villa_estimate_canvas_offset`.
4. **Conventions.** The normal **n** follows VC3D, which is the direction of rising layer index (= −n of `vesuvius`). Stacks use odd K with k₀ = (K−1)/2. Document the sign of **s** relative to ∇h with a known-answer test.
5. **Freeze the defaults.** Patch size, overlap and the in-sheet band rule are frozen when this WO merges. WO-003 uses them unchanged.
6. **No render-derived images** in the repo (DR-008). Synthetic-only figures are fine.

## Addendum 2 — 2026-11-01 (Planner, after external derivation review DR-009; binding)

If work is in progress, fold these in, and say in the provenance log which already-built parts changed. Theory is in `docs/method-lpsf.md` (rev. 2026-11-01). Where it conflicts with §3–§4 above, this addendum wins.

1. **Exact geometry.** Use s = Δd·tan θ·t, and s/Δd = ∇h with h measured along **n**. Apply the metric correction ∂ᵢh = (1/Δd)·g_ij·s^j, with g from the mesh grid. The synthetic harness must include a non-isometric (stretched) mesh case, with a test that integration with g is unbiased and integration without g is biased by ≈2ε.
2. **Band-pass each layer in-plane before estimation.** Add a synthetic case where the sheet envelope varies across a tilted patch, and a test that the band-passed estimate is unbiased while the unfiltered one is not. The cut-offs are parameters, frozen at merge.
3. **Two estimators, one benchmark.**
   - (i) Phase correlation: the existing fast path, plus the skimage and villa `_phase_correlate` references.
   - (ii) A multi-layer gradient estimator: symmetric Lucas–Kanade / 3D structure-tensor flow on band-passed layers, summing normal equations across in-sheet layers before solving, with an optional iterative refinement.
   - Compute the **Cramér–Rao bound** for each synthetic configuration from the generator's known power spectrum and decorrelation, and report each estimator's efficiency, CRLB/variance, against θ, SNR and anisotropy. The default is whichever estimator is closer to the bound across the realistic configurations (Addendum 1, item 1). Ties go to phase correlation, which reuses the existing primitive (DR-003). Record the choice and the numbers.
4. **Two-layer (recto/verso) texture mode** with orthogonal fibers at different depths. Report Σ per layer and summed, and check that summing information before inverting removes the 1-D aperture problem.
5. **Integration:** a screened, anisotropically weighted least-squares solver with in-mask Neumann edges and a z* screening term. Frankot–Chellappa is a reference only.
6. **Failure detection.**
   - Implement the consistency residual r = ∇z* − g, where z* comes from the depth profile of band-passed variance × ρ.
   - Replace the P4 acceptance test: step localization AUROC ≥ 0.9 at step amplitude ≥ 3 voxels **for ‖r‖**.
   - Add a test that curl is about 0 along a straight step interior. Curl stays as a diagnostic; its null distribution comes from Monte Carlo on the actual patch layout, not from a formula.
7. **In-sheet window rule (non-circular).**
   - Per patch, find the dominant peak of E(k) = (band-passed variance × ρ)(k) × a Gaussian prior centred on k₀ (σ_prior = 20 layers).
   - Aggregate over a contiguous window around that peak, with width ≤ W_max < wrap pitch.
   - Add a synthetic neighbouring-wrap case at a 47-layer pitch, including touching sheets, and test that no neighbouring-wrap layers enter.
   - W_max is a parameter; WO-003 step 0 fixes it from measured sheet thickness.
8. **Validation hygiene.**
   - All slope tests regress the **signed** component along the known tilt direction (or vector-regress), never |s|.
   - Ground truth is window-averaged with the estimator's own spatial weighting.
   - Add a test showing that regressing against the point slope of a short-wavelength sinusoid under-reads by about sinc(P/λ), so the harness itself demonstrates the trap.
9. **Acceptance (replaces §4 P1/P2 and P4 items):**
   - signed slope of (s·t)/Δd against window-averaged tan θ = 1 ± 0.05 for θ ≤ 20° in A1 mode at moderate SNR;
   - pure offset gives |s| < 0.05 px;
   - offset recovery RMSE ≤ 0.5 voxel as before;
   - ‖r‖ step AUROC ≥ 0.9 at ≥ 3 voxels.
   Report the **minimum detectable tilt** (Addendum 1, item 2) for the chosen estimator; WO-003 relies on it.

## 6. Provenance log (executor appends below)

---

### 2026-11-01 — Cloud (WO-002 with addenda 1 and 2)

**Branch.** Work is on `claude/great-gates-licedm`, the branch this Cloud session was assigned, not `wo-002-…` as `docs/workflow.md` asks. The session instructions forbid pushing elsewhere without permission; Kevin can rename it when opening the PR.

**Pins.** villa `d57c28ebee8776b618f9851c2289cc407ea99dd4` (from `uv.lock`, confirmed by `tests/test_cli.py::test_installed_vesuvius_is_the_pinned_commit`). No Podman image was used (Cloud; out of scope). No scroll data was read: every volume is synthetic, generated in-process from a seed. Python 3.14.6, numpy 2.5.4, scipy 1.18.1, scikit-image 0.26.0.

**Commands.**
```
uv sync
uv run ruff check && uv run ruff format --check
uv run pytest -q                                        # 126 passed
uv run vch selftest
uv run vch synth run --config configs/synth/wo002.toml --out runs/synth --workers 3        # -> wo002-20261101T191224
uv run vch synth run --config configs/synth/wo002-fibre.toml --out runs/synth --workers 3  # -> wo002-fibre-20261101T195301
uv run vch synth report reports/2026-11-wo002/sweeps/wo002-20261101T191224 reports/2026-11-wo002/sweeps/wo002-fibre-20261101T195301 --out reports/2026-11-wo002/generated
uv run python scripts/wo002_diagnose_realistic.py
uv run python scripts/wo002_diagnose_overshoot.py
uv run vch selftest                                     # 13 / 13 pass
```
Compute: one cloud container, 4 vCPU, 15 GB RAM, no GPU. Reported runs: 40.6 min + 12.5 min of sweep wall time (2.65 CPU-hours in cases) and 16 min of diagnostics; superseded runs ≈ 1.5 h wall, ≈ 4.3 CPU-hours (report §11). Run records: `reports/2026-11-wo002/sweeps/*/run.json`, `generated/report.run.json` and `diagnosis-*.json`. All reported records carry `source_sha256` 9bdc19a6204a, the committed package source. **Data identifiers:** synthetic only; every case's seed is in `cases.parquet` (base seed 2026 for the main sweep, 2027 for the orientation sweep, ×1000 + case index).

**Addendum 2 arrived mid-work (merged from `master` at 9eb802a). Already-built parts that changed:**

1. *Geometry and truth (item 1).* The first harness measured h along the **nominal** normal on a graph-displaced mesh, where |s|/Δd = sin θ exactly in grid pixels, and the estimator converted g → g/√(1−|g|²) and k* → h with a cos θ factor. Replaced:
   - truth h is the distance along the **rendered** mesh normal (`synthetic.normal_offset`);
   - ramps use an exactly isometric tilted plane (`synthetic.tilted_points`);
   - the estimator applies ∂ᵢh = gᵢⱼ sʲ/Δd with g from the mesh (`Field.grad`), and z* = (k* − k₀)Δd with no cos factor.
   Both conversions were removed. A stretched-mesh mode and its test were added.
2. *Pre-filtering (item 2).* The first estimator used a local contrast normalisation (Gaussian high-pass σ = 8 px, divided by local amplitude) that I had added after finding the envelope bias myself. It is now an explicit difference-of-Gaussians band-pass (`bp_fine` 1 px, `bp_coarse` 8 px). The amplitude normalisation and a common-support mask are kept as options (on by default; justified in the report). An "unfiltered" switch exists for the item-2 test.
3. *Estimators (item 3).* Phase correlation was kept (batched, matrix-DFT zoom, one resample-and-recorrelate pass, β-generalised whitening). Multi-layer symmetric Lucas–Kanade and `crlb.py` (pair and multi-layer Fisher information) were added. The phase-correlation Σ changed from the curvature of the windowed correlation peak to a cross structure tensor: the peak curvature contains the window's own curvature, which manufactured information along fibres and hid the aperture problem (found while building item 4).
4. *Depth window (item 7).* The first rule was a contiguous run of the patch's **mean intensity** above half-maximum (later 0.8). It was replaced by the addendum rule: the peak of E(k) = band-passed variance × ρ times a Gaussian prior on k₀ (σ = 20 layers), a contiguous hull of layers whose smoothed band-passed variance is ≥ 0.9 of the maximum, and a cap of `w_max` = 21 voxels. Pairs are now correlated only inside the window.
5. *k\* → z\* (item 6).* The centroid of (mean − min) × ρ became the centroid of E(k) over its half-maximum run, capped at 41 voxels.
6. *Integration (item 5).* The first solver was a Σ-weighted least squares with a small Laplacian and a constant pinned to k*. It is now the screened solve with a z* term and in-mask cells (Neumann). Frankot–Chellappa is a reference only.
7. *Failure detection (item 6).* P4 previously scored the curl. The consistency residual ‖∇z* − g‖ is now the detector; curl is kept, with a Monte-Carlo null from amplitude-0 step cases.
8. *Validation (items 8, 9).* Slopes are now signed components regressed against window-averaged truth, never |s|. The window is Hann² for gradients, since both layers of a pair are windowed, and Hann for h. A sinusoid trap test was added. Acceptance follows item 9.

**Surprises (each quantified in the report):**
- Pure (whitened) phase correlation fails on these renders even without noise: it read 0.002 against a true 0.17 px at θ = 10° on a generically placed mesh. Whitening gives out-of-band frequencies, where fixed voxel-grid interpolation residue and isotropic noise live, the same weight as the texture band, and that residue correlates best at zero shift. The default is β = 0 (windowed cross-correlation with sub-pixel DFT zooming).
- An axis-aligned synthetic mesh at integer voxel positions makes trilinear pixel-locking coherent across a patch. Synthetic meshes are now placed generically (in-plane rotation of 23.7° and a sub-voxel offset).
- With slice step ≤ 1, adjacent layers share interpolation voxels. Isotropic CT noise then correlates best at zero in-plane shift, a pull toward zero that grows as SNR falls.
- The realistic (WO-001-fitted) decorrelation mode biases the slope strongly and can reverse its sign when fibres run near the tilt direction. A 3-D texture that decorrelates through the thickness pulls the match toward smaller depth mismatch, and along the fibres nothing in-plane resists. This bears directly on WO-003.
- The first full sweep died at 17:54 UTC when a worker was killed (most likely out of memory: four 768-px bump cases at once, peak ~2.7 GB each, while tests also ran), and it lost all results. The runner now retries in a fresh pool, checkpoints every 50 cases and always writes what finished. The volume generator now works in float32 slabs. The sweep was rerun with 3 workers.
- **Interpolation defect in my own refinement step, found while diagnosing the orientation sweep.** In A1 mode with fibres across the tilt, the gain was +10% (λ = 8 px) and +2.6% (λ = 16 px). It was the same with a cubic renderer, and it disappeared with refinement off (0.994). The cause was the phase error of the Keys cubic-convolution resampler used to align layer k+1 before re-correlating. Both estimators inherit it, because LK converges to the same fixed point. I replaced it with prefiltered cubic B-spline interpolation; the selftest now matches scipy's spline shift to 1e-3, and the gain is 0.996–1.005 at 0° and 90°. The 2–7% small-angle overshoot in the first sweep was the same artefact. **Every sweep and diagnosis was rerun on the fixed code; only the rerun numbers are reported.** The defective run's diagnosis is kept as `diagnosis-overshoot-keys-resampler.json`.
- **Kevin's mid-work instructions (2026-11-01):** diagnose the realistic-mode sign reversal (filter, estimator, generator drift, Σ); add a Σ-calibration acceptance criterion (95% intervals cover the truth in 90–98% of patches; no confident wrong sign in unobservable directions, operationalised as ≤ 2.5% of patches wrong-signed with |g|/σ > 1.96, the rate a calibrated Gaussian Σ allows); run a fibre-orientation sweep from 0 to 90° (`configs/synth/wo002-fibre.toml`); report P = 64 at 20° as unmet, with P = 32 alongside and a recommended default. Diagnosis scripts: `scripts/wo002_diagnose_realistic.py`, `scripts/wo002_diagnose_overshoot.py`.
- **Push blocked:** `git push` to `origin` returned HTTP 403 (no GitHub access for this repository from the session). The commits are local on `claude/great-gates-licedm` until access is restored.

**Acceptance criterion added on Kevin's instruction (2026-11-01).** Σ must be calibrated across all modes and orientations: 95% intervals cover the truth in 90–98% of patches, and unobservable directions must not produce a confident wrong sign. The second clause is operationalised as ≤ 2.5% of patches wrong-signed with |g|/σ > 1.96, the rate a calibrated Gaussian Σ allows at small tilts. This is implemented as a verdict in `synth_report.calibration`. **Result: FAIL in every mode** (report §6).

**Outcome summary (details and numbers in `reports/2026-11-wo002/report.md`):**
- P1/P2 pre-registered slope criterion (θ ≤ 20°, P = 64, A1, SNR 6): **FAIL**. The cause is geometric at 20°: P·tan θ = 23.3 voxels against a 20-voxel sheet with about 6–9 voxels of edge. P = 32 also fails at 20°. Over θ ≤ 10° the slopes are 0.93–1.00, and a 40-voxel sheet gives 0.99 at 20°. Recommended default P = 64.
- Pure offset (A1) PASS; offset recovery (A1) PASS; P4 ‖r‖ (A1) PASS; the realistic-mode counterparts FAIL.
- Realistic-mode sign reversal diagnosed: not the envelope trap, present for LK, no generator drift. It is the in-band twin of the envelope trap (depth decorrelation pulls the match toward −Δd/tan θ), with first-order gain ≈ 1 − 2ℓ_t²/L². It is orientation-dependent: reversed for fibre-to-tilt angles ≤ 30°, about right at 75–90°.
- Estimator: phase correlation by the pre-stated rule; LK has about 1.5× the median efficiency. Flagged for the Planner.
- Defaults frozen as `lpsf.Params()` (report §9).
