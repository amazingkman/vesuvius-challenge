# Changelog

All notable changes to this project are documented here.
Format: [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/). Versioning: [SemVer](https://semver.org/) from the first tagged release; dated entries until then.

Each entry says **what** changed, **why**, and **what it builds on** (citation keys from `docs/citations.bib`).

## [Unreleased]

### Added
- 2026-11-01 — DR-009: outcome of an external derivation review of LPSF (Gemini), each item checked by the Planner. Adopted:
  - exact tan θ geometry;
  - metric correction;
  - per-layer band-pass;
  - consistency residual replacing curl as the step detector;
  - window-averaged ground truth;
  - an estimator benchmark against the Cramér–Rao bound;
  - screened weighted integration;
  - block bootstrap.
  Planner additions:
  - signed rather than magnitude regression;
  - paired shifts in S1;
  - baseline B4 (structure-tensor normal).
  Rejected: the review's Catmull-Rom transfer-function numbers (about 4× overstated) and its curl-variance factor.
- 2026-11-01 — Planner review of WO-001: DR-002 addendum (code-search result) and DR-008 (study data PHerc0139; Paris 4 and FASP `state.tif` excluded; no public review tags; the May 2026 image is the renderer of record; WO-003 redesigned in physical units; rules for the public repo; default branch `master`). Builds on: `villa_estimate_canvas_offset`, `villa_atlas_overlay`, `villa_issue2167`.
- 2026-11-01 — `vch` CLI with `survey`, `fetch`, `render`, `verify-io` and `selftest`, at the python-lab-ux floor (banner, live progress, explanations, statistics, graceful Ctrl-C, summary, JSON run record). `vch render` runs `vc_render_tifxyz` in Podman by image digest. `verify-io` is an addition to the WO's list: objective 1 needs proof that the `vesuvius` read path and the renderer agree. Why: WO-001. Builds on: `villa`, `open_data_repo`, `scrollprize_data`.
- 2026-11-01 — WO-001 reports in `reports/2026-11-wo001/`: `upstream-audit.md`, `data-survey.md`, `code-search-hits.tsv` (every hit at the pin, with a judgment) and survey tables for all 14 samples with segments. Manifests for four PHerc0139 segments in `manifests/`. Why: closes the primer section 8 gaps and supplies the DR-002 novelty search. Builds on: `villa`, `villa_estimate_canvas_offset`, `villa_atlas_overlay`.
- 2026-11-01 — DR-004 addendum recording VILLA_SHA and the Podman image digest, including that the newest published image predates the pin by about five and a half months. Builds on: `villa`.
- 2026-11-01 — Dependencies `opencv-python-headless`, `numba` and `imagecodecs`. `vesuvius.tifxyz` does not import under `vesuvius[volume-only]` without the first two, and LZW TIFFs need the third. The villa pin did not change.
- 2026-10-31 — Repository `vesuvius-challenge` scaffolded: uv package `vesuvius_challenge`, Python 3.14, MIT license, public on GitHub. `vesuvius[volume-only]` is installed from ScrollPrize/villa at a pinned commit. Why: villa `main` requires Python 3.14 and PyPI 0.2.4 is stale (DR-004). Builds on: `villa`.
- 2026-10-31 — Planning set rewritten after the 2026-10-31 research pass:
  - `docs/primer.md` (current state, plus an audit of the June claims);
  - `docs/method-lpsf.md` (theory and falsification tests);
  - `docs/decisions.md` (DR-002 to DR-007);
  - `docs/workflow.md` (Planner / Cloud / VSCode roles);
  - `docs/data-licensing.md`;
  - `docs/citations.bib`;
  - `CLAUDE.md` and `AGENTS.md`;
  - WO-001 to WO-004 and `planning/BACKLOG.md`.
  Why: the June documents contained material errors (see Changed). Builds on: `scrollprize_prizes`, `scrollprize_winners`, `scrollprize_open_problems`, `villa`.

### Changed
- 2026-11-01 — WO-003 reissued as rev 3 (DR-009), before any real-data LPSF run: step-0 physical diagnostics and W_max; baseline B4; re-specified S1 to S3; a value claim requiring LPSF to beat or complement B4. WO-002 Addendum 2 (binding). `docs/method-lpsf.md` revised (exact geometry, metric, band-pass, estimator choice, consistency residual, failure modes, normal-field prior art).
- 2026-11-01 — WO-003 reissued as rev 2, before any real-data LPSF run:
  - stack of 81 layers at step 1 (±96 µm), with a cost probe first;
  - sinusoidal corrugations replace global ramps; amplitudes in µm;
  - `vc_objrefine` as a black-box baseline, because the offset report is not available;
  - tag and `state.tif` analyses removed.
  Why: WO-001 measured 2.399 µm voxels and a ~3-voxel texture decorrelation, and found no tags and a Paris 4 reservation.
- 2026-11-01 — WO-002 addendum: a realistic-decorrelation texture mode, a small-angle sweep and minimum detectable tilt, a cross-check against villa `_phase_correlate`, and frozen sign conventions.
- 2026-11-01 — `docs/method-lpsf.md`:
  - novelty claim narrowed to inter-layer use, now naming `estimate_canvas_offset.py`;
  - measured conventions recorded (k₀, normal sign, decorrelation length);
  - warning added against layer-axis resampling;
  - "reviewed" replaced by "published".
- 2026-11-01 — `docs/primer.md` corrected per WO-001 audit §8:
  - `vc_tifxyz_winding` removed at the pin;
  - #2358 has no offset report;
  - real mesh layout;
  - tag vocabulary;
  - `state.tif` hosted but Paris 4.
- 2026-11-01 — `docs/data-licensing.md`: Paris 4 modified-license terms, PHerc0139 status, and no render-derived images in the repo. `docs/workflow.md`: public-repo rules, and `master`.
- 2026-11-01 — Console script renamed from `vesuvius-challenge` to `vch`, as `CLAUDE.md` specifies.
- 2026-11-01 — Citation notes updated with verified PR status: #2224, #2365, #2368 and #2373 are open; #2358 is merged and holds no offset report. `tifxyz_doctor` now points at its repository.
- 2026-10-31 — Project renamed from "Vesuvius Coherence" (`vesuvius_coherence`) to "Vesuvius Challenge" (`vesuvius-challenge` / `vesuvius_challenge`). The README states the project is independent and not affiliated with the Vesuvius Challenge team.
- 2026-10-31 — Method A re-scoped and renamed from "coherence mapping" to **Layer Phase-Shift Field (LPSF)** (DR-002):
  - the refinement loop is now an error signal for existing tools (`vc_objrefine`, Lasagna) rather than a new method;
  - the novelty claim is narrowed to the inter-layer tilt estimator, offset integration, and the curl residual;
  - the primary validation is now injected perturbations on real segments.
  Why: the June "wishlist" quote turned out to be the description of segmata, which is prior art. Builds on: `segmata`, `vc_objrefine_pr2224`, `tifxyz_doctor`, `offset_sweep`.
- 2026-10-31 — Method B stays parked; Method C is dropped (DR-006). Builds on: `dinovol`.

### Removed
- 2026-11-01 — `vesuvius-challenge-docs.tar.gz`, accidentally committed in the scaffold commit.
- 2026-10-31 — `vesuvius.accept_terms` step dropped from setup. villa `main` removed the command; compliance is now documented in `docs/data-licensing.md`.
- 2026-10-31 — Superseded planning docs: the combined WO-002/003, the old WO-001, and the bootstrap/handoff note. Content was folded into the new WOs and `docs/workflow.md`.

### Fixed
- 2026-11-01 — `vch render` no longer records a skipped render as a result: `vc_render_tifxyz` exits 0 without rendering when its outputs exist, so the command now refuses to run over existing layers unless `--overwrite` is given. Why: this made a reproduction check falsely pass. Builds on: `villa`.
- 2026-10-31 — Primer corrections (full table in `docs/primer.md` §7):
  - segment 20241108120732 is Scroll 5, not Scroll 1;
  - the Kaggle pool was $200K;
  - the prize structure and hallucination rule changed;
  - layer-count conventions vary between sources.

## 2026-06-12
### Added
- Original scaffold: README, CHANGELOG, documentation contract, citation tiering policy, DR-001, WO-001 to WO-003 drafts, and the June primer.
