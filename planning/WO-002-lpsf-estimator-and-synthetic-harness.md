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

## 6. Provenance log (executor appends below)

---
