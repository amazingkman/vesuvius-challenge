# Changelog

All notable changes to this project are documented here.
Format: [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/). Versioning: [SemVer](https://semver.org/) from the first tagged release; dated entries until then.

Each entry says **what** changed, **why**, and **what it builds on** (citation keys from `docs/citations.bib`).

## [Unreleased]

### Added
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
- 2026-10-31 — Project renamed from "Vesuvius Coherence" (`vesuvius_coherence`) to "Vesuvius Challenge" (`vesuvius-challenge` / `vesuvius_challenge`). The README states the project is independent and not affiliated with the Vesuvius Challenge team.
- 2026-10-31 — Method A re-scoped and renamed from "coherence mapping" to **Layer Phase-Shift Field (LPSF)** (DR-002):
  - the refinement loop is now an error signal for existing tools (`vc_objrefine`, Lasagna) rather than a new method;
  - the novelty claim is narrowed to the inter-layer tilt estimator, offset integration, and the curl residual;
  - the primary validation is now injected perturbations on real segments.
  Why: the June "wishlist" quote turned out to be the description of segmata, which is prior art. Builds on: `segmata`, `vc_objrefine_pr2224`, `tifxyz_doctor`, `offset_sweep`.
- 2026-10-31 — Method B stays parked; Method C is dropped (DR-006). Builds on: `dinovol`.

### Removed
- 2026-10-31 — `vesuvius.accept_terms` step dropped from setup. villa `main` removed the command; compliance is now documented in `docs/data-licensing.md`.
- 2026-10-31 — Superseded planning docs: the combined WO-002/003, the old WO-001, and the bootstrap/handoff note. Content was folded into the new WOs and `docs/workflow.md`.

### Fixed
- 2026-10-31 — Primer corrections (full table in `docs/primer.md` §7):
  - segment 20241108120732 is Scroll 5, not Scroll 1;
  - the Kaggle pool was $200K;
  - the prize structure and hallucination rule changed;
  - layer-count conventions vary between sources.

## 2026-06-12
### Added
- Original scaffold: README, CHANGELOG, documentation contract, citation tiering policy, DR-001, WO-001 to WO-003 drafts, and the June primer.
