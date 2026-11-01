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
