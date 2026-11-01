# Decision records

Each record is dated and numbered, and states context, decision, rationale, and what would reverse it. Records are never edited after the fact; a later record supersedes an earlier one.

---

## DR-001 — 2026-06-12 — Focus on Method A (coherence mapping); park B; shelve C — **SUPERSEDED by DR-002 and DR-006**

Original rationale: the June primer judged Method A a "clean gap" that implemented an open community wishlist item. **Both premises were wrong** (audit 2026-10-31, `docs/primer.md` §7):
- The quoted text ("sharpening the layers rendering… optimizing the layer 32… inference loop") is the description of **segmata**, an existing awarded community project. It is not an open wishlist item. The quote is evidence of prior art, not of a gap.
- Render-driven normal refinement already exists in several tools (segmata, `vc_objrefine`, recto-offset, Lasagna).

The June validation design (stratify by contrast; calibrate against masks and tags) is kept and extended in WO-003.

---

## DR-002 — 2026-10-31 — Re-scope Method A as LPSF, an error signal that plugs into existing refinement tools

**Context.** The research pass of 2026-10-31 (`docs/primer.md`) found confirmed prior art for refining along the normal, and partial prior art for normal-offset QC (TIFXYZ Doctor). It found no prior art for the specific estimator. The name "coherence" collides with an existing community "spectral coherence" QC project.

**Decision.**
1. Rename to **Layer Phase-Shift Field (LPSF)**. The per-patch metric names are *shift* **s**, *peak correlation* ρ, and *curl residual*.
2. Claim novelty **only** for (a) inter-layer phase-correlation tilt estimation, (b) integration of that tilt into an offset field, and (c) the curl residual as a diagnostic (`docs/method-lpsf.md` §6). The refinement loop is presented as **a new error signal for `vc_objrefine` / Lasagna**, not as a new refinement method.
3. The primary validation is **injected perturbations on real segments**, with paired differences (method-lpsf §5). AUROC against VC3D tags and FASP `state.tif` is secondary.
4. The baselines to beat on identical inputs are: brightest-layer snap, the `vc_objrefine` offset report (if PR #2224 is available at the pinned commit), and TIFXYZ Doctor's normal-offset cue.

**Rationale.** This follows the project's innovation policy (DR-003): extend existing work explicitly, and keep the novel kernel small and testable.

**Reversal.** If WO-002 falsifies P1 or P2 on synthetic sheets, stop LPSF and record the null result. If WO-003 shows LPSF does no better than the brightest-layer snap and the `vc_objrefine` offset on injected perturbations, publish the comparison as a negative result (still useful to the community) and do not build refinement integration.

**Before any public novelty claim:** WO-001 runs a code search of villa for phase correlation and related terms, and Kevin manually checks Discord (#segmentation and related channels). Both results are recorded here as an addendum.

---

## DR-003 — 2026-10-31 — Innovation policy

We build something new only if:
1. it **explicitly extends** existing Vesuvius Challenge work or tools, cited by name, commit or PR; or
2. its novelty is **airtight**: a documented prior-art search (including villa code and Discord), a falsifiable derivation, synthetic validation with known ground truth, and real-data validation against named baselines.

Our own design choices are always welcome: the interface, rigor, documentation, and how tools are combined. Re-implementing something a ScrollPrize tool already does is not. If an upstream tool does the job, we call it.

---

## DR-004 — 2026-10-31 — Stack: Python 3.14, pinned villa commit, Podman-run VC3D

- **Python 3.14.** villa `main` `vesuvius/pyproject.toml` declares `requires-python = ">=3.14,<3.15"` (read 2026-10-31). PyPI `vesuvius` 0.2.4 is older and capped below 3.14, so it is not used.
- **`vesuvius[volume-only]` from git, pinned.** It is installed from villa `main`, pinned to the commit Kevin resolved on 2026-10-31. **VILLA_SHA = `<fill in from uv.lock in WO-001>`.** We bump the pin only through a WO that re-runs the full test suite.
- **No `accept_terms` step.** villa `main` removed that command: the module now notes that nothing checked the record, and the terms live in the README "Data licence" section. Compliance is documented in `docs/data-licensing.md` instead.
- **VC3D binaries via Podman**, using image `ghcr.io/scrollprize/villa/volume-cartographer:edge`, pulled successfully by Kevin on 2026-10-31. Record the image digest in every run record. We run its tools as external processes and never link the GPL code.
- **Phase 1 is CPU-only.** torch and nvitop are added when the first GPU work order arrives.
- **UX floor:** every program meets the `python-lab-ux` conventions (rich, typer CLI `vch` with `selftest`/`run`/`report`, JSON run records, graceful interrupt).

**Addendum 2026-11-01 (WO-001, pin record).** The record above stands; these are the values it left open.

- **VILLA_SHA = `d57c28ebee8776b618f9851c2289cc407ea99dd4`** (from `uv.lock`; commit dated 2026-10-31 11:23:44 -0500). The installed package reports the same commit.
- **Podman image digest = `sha256:b2509de2c107852799a5077fd2038a917549a1d1e3665d5a1919c955858d698a`**, from `podman image inspect --format '{{.Digest}}'`. This is the linux/amd64 manifest. The multi-arch index that `:edge` resolves to is `sha256:bad516f66001abca759454cc43e4fd11e5b19aa55d36bdc2043817291c8083c4`. `vch render` addresses the image by the amd64 digest.
- **The image and the pin are different code.** The image was built on 2026-05-13 from villa `1e3f4c021f4e53bea3867772ed05f51a7e586a9c`, about five and a half months before VILLA_SHA. `:edge` and `:main` on GHCR both still resolve to that build (checked 2026-11-01), so this is the newest published image, not a stale local pull. Our Python runs VILLA_SHA; our renders run May code. Details and consequences: `reports/2026-11-wo001/upstream-audit.md`.
- **Dependencies added beside the pin, which did not move:** `opencv-python-headless` and `numba`, which `vesuvius.tifxyz` imports but `vesuvius[volume-only]` does not install, and `imagecodecs`, which LZW-compressed TIFFs need.

---

## DR-005 — 2026-10-31 — Roles: Planner, Cloud, VSCode

There are three roles. See `docs/workflow.md` for details.
- **Planner** (this claude.ai Project): research, design review, docs, and work orders. Writes no implementation code.
- **Cloud** (claude.ai/code on the GitHub repo): pure-code work orders that need no scroll data, no GPU and no containers, such as the estimator, synthetic harness, tests, CI, docs, and upstream villa PR drafts.
- **VSCode** (Claude Code on Duskrider): anything touching data, Podman/VC3D, real renders, or long runs.

Every WO names exactly one executor. Kevin reviews and merges.

---

## DR-006 — 2026-10-31 — Method B stays parked; Method C dropped

- **B (topological defect auditing).** Winding-consistency tools already exist (winding-sync, windaudit, spiralcheck, windcheck, and the spiral fit's global prior), and `vesuvius.compute_st` already provides structure tensors. Only the disclination-charge formalism lacks prior art. B stays parked. It may come back only as an *extra evidence channel* for an existing winding tool, under DR-003.
- **C (JEPA pretraining).** Dropped. Self-supervised learning on scroll CT is crowded (dinovol 3D DINO with released checkpoints, ScrollMAE, Large Scroll Model, DINOv2-vesuvius). If learned features are ever needed, use the dinovol checkpoints.

---

## DR-007 — 2026-10-31 — Repository name, license, visibility

The repository is `vesuvius-challenge`, MIT licensed, and public. The README states it is not affiliated with the Vesuvius Challenge team. Public from day one serves the prize criterion "released or open-sourced early" [T1: scrollprize.org/prizes]. No scroll data and no hidden-text revelations ever enter the repo (`docs/data-licensing.md`).
