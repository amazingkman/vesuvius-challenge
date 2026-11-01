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
- **VSCode** (Claude Code on the local workstation): anything touching data, Podman/VC3D, real renders, or long runs.

Every WO names exactly one executor. Kevin reviews and merges.

---

## DR-006 — 2026-10-31 — Method B stays parked; Method C dropped

- **B (topological defect auditing).** Winding-consistency tools already exist (winding-sync, windaudit, spiralcheck, windcheck, and the spiral fit's global prior), and `vesuvius.compute_st` already provides structure tensors. Only the disclination-charge formalism lacks prior art. B stays parked. It may come back only as an *extra evidence channel* for an existing winding tool, under DR-003.
- **C (JEPA pretraining).** Dropped. Self-supervised learning on scroll CT is crowded (dinovol 3D DINO with released checkpoints, ScrollMAE, Large Scroll Model, DINOv2-vesuvius). If learned features are ever needed, use the dinovol checkpoints.

---

## DR-007 — 2026-10-31 — Repository name, license, visibility

The repository is `vesuvius-challenge`, MIT licensed, and public. The README states it is not affiliated with the Vesuvius Challenge team. Public from day one serves the prize criterion "released or open-sourced early" [T1: scrollprize.org/prizes]. No scroll data and no hidden-text revelations ever enter the repo (`docs/data-licensing.md`).

---

## DR-002 addendum — 2026-11-01 — Code-search result (WO-001)

The full-text search of villa at `d57c28e` judged all 2,483 hits (`reports/2026-11-wo001/upstream-audit.md` §6). It found one piece of prior art not known before: `estimate_canvas_offset.py`, which uses tile-wise phase correlation on renders to audit a constant 2-D canvas offset. DR-002 items (a)–(c) are not anticipated, so the decision stands. The novelty wording in `method-lpsf.md` §6 now names that file and claims only the inter-layer use and what is built on it. **Discord check: still pending (Kevin).**

---

## DR-008 — 2026-11-01 — WO-001 outcomes: study data, renderer of record, WO-003 redesign

**Context.** WO-001 (`reports/2026-11-wo001/`) closed most primer gaps and raised five decisions.

**Decisions.**
1. **Study scroll: PHerc0139, 2.399 µm volume `20260102150214`, native meshes only.** Segments: w043, w057, w044, w058, in WO-001's priority order. Reasons:
   - CC BY-NC (embargo lifted 2026-06-25 per site code; T3);
   - meshes traced on that volume, which avoids the cross-frame cost reported in issue #1845;
   - public defect measurements exist (#2167; ChaseHendrick notes).
2. **PHerc. Paris 4 is excluded from all published analysis, and so is FASP `state.tif`.** The Paris 4 notice bars "formal analyses" based on the data until 2027-06-25 without permission. WO-001 judged `state.tif` "almost certainly" Paris 4; we treat it as Paris 4 until shown otherwise. Kevin may ask the team for permission. Until a written yes, these stay out.
3. **No review tags are public.** The paired-perturbation design does not need them. Tag-based analysis is dropped from WO-003 and stays a backlog item, pending Kevin asking on Discord where the team keeps review tags. `inspect` is not treated as a quality label.
4. **Renderer of record: the published Podman image** (built 2026-05-13 from `1e3f4c0`, digest in DR-004). WO-001 showed it agrees with the pinned `vesuvius` read path (r 0.992–0.995, best offset 0) at `--group-idx 0`. Building VC3D from source is deferred until a WO needs a flag the image lacks. Always render at `--group-idx 0` and with odd `--num-slices`.
5. **WO-003 is pre-registered in physical units, and redesigned before any LPSF output on real data exists.**
   - **Stack:** 81 layers at step 1 voxel (±96 µm). This is close to one local sheet pitch (~113 µm per #2167), wide enough for realistic offsets and the neighbouring-sheet test. P1 is tested by subsampling, with no extra renders.
   - **Perturbations:** sinusoidal corrugations replace global ramps, because a 20° ramp across a crop moves the mesh hundreds of voxels off the sheet. Amplitudes are now in µm, at realistic error scales.
   - **Baseline B2:** `vc_objrefine` run as a black box, since the offset report (PR #2224) is not available.
   - Full revision: `planning/WO-003-…` rev 2.
6. **Repository stays public.** The Planner-review gate in `docs/workflow.md` applies to *announcements and prize submissions*, not to PR contents. To make that safe, PRs never contain images derived from renders, only fields, statistics, IDs and checksums.
7. **Default branch is `master`.** Docs updated.

**Reversal.** If the Vesuvius Challenge grants written permission for Paris 4 QC analysis, item 2 can be revisited for a secondary analysis. If WO-003's step 0 cost probe shows the 81-layer design cannot fit the compute budget, the Planner re-issues WO-003 before any LPSF run on real data.

---

## DR-009 — 2026-11-01 — External derivation review of LPSF: what we adopt, what we reject

**Context.** Kevin put nine physics, statistics and estimation questions about LPSF to Gemini (current flagship model). Every claim came back tagged as derived, established, estimate or unknown. The Planner checked the derivations by hand and the key numbers by script (Project note `notes/2026-11-01-gemini-review.md`). No real-data LPSF output exists yet, so changes to pre-registered criteria are still legitimate.

**Adopted (each verified by the Planner):**
1. **s = Δd·tan θ·t**, exactly, for planar mesh and sheet; **s/Δd = ∇h** exactly when h is measured along **n**. This replaces the first-order sin θ form.
2. **Metric correction:** ∂ᵢh = (1/Δd)·g_ij·s^j. It prevents a ≈2ε error on stretched parameterizations.
3. **In-plane band-pass on each layer** before estimation, because the thickness envelope slides about −Δd/tan θ per layer, the opposite direction to the texture.
4. **Curl is not a step detector.** A straight step has a curl-free gradient along its interior. Replaced by the **consistency residual ∇z* − g** (sheet position versus tilt).
5. **Validation ground truth must be window-averaged.** A 64-px patch attenuates a 0.3 mm sinusoid's slope to about 0.62. Regressing against the point slope would fail a correct estimator.
6. **Estimator choice is an experiment, not an assumption.** Phase correlation versus a multi-layer gradient estimator (Lucas–Kanade / 3D structure-tensor flow), both benchmarked against the Cramér–Rao bound in WO-002.
7. **Integration:** a screened, anisotropically weighted least-squares solve, with z* pinning low frequencies. Frankot–Chellappa is kept only as a reference.
8. **Dependence-aware statistics:** spatial block bootstrap within segment strata; step-line labels with a buffer zone; partial AUROC reported.
9. **Extra diagnostics:** gap-layer shift (fixed-pattern artifacts) and void-region correlation (PSF versus material).

**Added by the Planner (missed by the review):**
- **Never regress |s|.** Noise biases a magnitude upward. Use the signed component along the known tilt direction, or vector regression.
- **Use paired shifts, Δs = s(perturbed) − s(original),** in S1. Otherwise the original mesh's own tilt errors contaminate the regression.
- **Baseline B4:** tilt from the volume's 3D structure-tensor normal (`vesuvius.compute_st`) versus the mesh normal. It measures the same θ by a different physical route and is the strongest competitor (Lasagna already optimizes against normal volumes). LPSF's value claim now requires beating B4 or adding to it.

**Rejected or corrected (verified wrong):**
- **Catmull-Rom transfer function:** the review's closed form is incorrect, and its table overstates errors about fourfold. By direct simulation, the RMS error of the realized sinusoid is 1.9% / 0.17% / 0.02% in h and 7.9% / 1.9% / 0.5% in slope at λ = 125 / 250 / 500 voxels. The fundamental amplitude is 0.988 / 0.999 / 1.000. The review's own snippet was not run.
- **Curl null variance with 50% overlap:** under the review's own correlation model, it is 0.75·Tr(Σ), not 0.375·Tr(Σ). Moot anyway: the null comes from Monte Carlo.
- **Papyrus microstructure figures** (Q4: carbonized sheet 50–90 µm, layer 25–45 µm, cell sizes): several citations are garbled or uncertain. Not adopted as facts. They are treated as hypotheses, and WO-003 step 0 measures sheet thickness and gap on our own renders instead.

**Consequences.** WO-002 gets a second binding addendum. WO-003 is reissued as rev 3. `method-lpsf.md` is revised.

---

## DR-010 — 2026-11-01 — Security and privacy policy for the public repository

**Context.** Kevin requires the highest security and privacy standard for anything on GitHub, while the repository stays public for researchers. The Planner audited every file in every commit (`docs/security.md`, audit log). It found **no secrets**. It did find the owner's username, in an absolute home path written by `vch render` into five WO-001 run records, and the workstation hostname in three docs.

**Decision.**
1. Adopt `docs/security.md`: a threat model, plus rules R1–R5 (no secrets; no machine identity; no render-derived images; supply-chain hardening; private commit email).
2. **Fix forward:**
   - The current tree is scrubbed now. *Redaction exception:* the hostname is removed from DR-005's text. This is the only permitted edit to an earlier record, and it changes no decision.
   - WO-005 (Cloud) makes recurrence mechanically impossible: anonymous run records, pre-commit, CI secret and identity scanning, pinned actions, least-privilege workflows. **WO-005 must merge before WO-003.**
3. **History rewrite is optional and Kevin's call.** The leaked items are reconnaissance-grade, not access-grade. A rewrite cannot reach GitHub's immutable PR refs, cached views or existing clones without GitHub Support.
4. **GitHub settings** (Kevin): secret scanning and push protection; Dependabot alerts; branch protection on `master`; 2FA; Cloud app scoped to this repo; private commit email.

**Reversal.** None. Security rules only tighten.

---

## DR-011 — 2026-11-01 — WO-002 outcome: accepted with failed criteria on record; real-data feasibility pilot gates WO-003

**Context.** WO-002 (PR #2, `reports/2026-11-wo002/report.md`) was run on synthetic data only: 1,460 cases. Four outcomes matter:
- the pre-registered P1/P2 slope criterion **failed**;
- the new Σ-calibration criterion **failed** in every mode;
- offset recovery, the consistency-residual step detector and window placement **passed** in A1 mode;
- in the realistic-decorrelation mode (matched to WO-001's measured r(d)), slopes are **orientation-dependent and sign-reversed** when fibres run within about 30° of the tilt direction, for both estimators.

**Planner review.**
1. **The P1/P2 failure is a validity envelope, not a falsification.** Within θ ≤ 10° on a 20-voxel sheet, and up to 20° on a 40-voxel sheet, the ratio is 0.93–1.01. The collapse at 20° comes from P·tan θ exceeding the *effective* sheet thickness (nominal thickness minus about 6–9 voxels of edge). **The criterion as written stays recorded as FAILED.** It is not relabelled. The method doc gains the envelope (P·tan θ ≲ T_eff − 6 voxels). This is **not** a DR-002 reversal: the reversal condition was falsification on A1 sheets inside the model's domain, and inside that domain the physics held.
2. **The decorrelation pull is the decisive risk.** When texture decorrelates with depth over a length L, the correlation maximum is pulled toward constant depth. The first-order gain derived by Cloud is ≈ 1 − 2ℓ_t²/L², where ℓ_t is the in-plane correlation length along the tilt direction. The predicted sign, trend and limit match the measurements; the size of the effect across fibres is not explained. On real papyrus, noise is small (DR-009 fit) and blur can only *raise* depth correlation, so WO-001's falling r(d) points to **material** decorrelation. **Prior expectation: real data behaves like the realistic mode**, with usable across-fibre components and biased along-fibre ones. This must be measured before WO-003 spends roughly 24 hours of rendering.
3. **Estimator:** phase correlation stays the default, per the rule pre-stated before the runs. Changing it after seeing results would be post hoc. LK runs as a **pre-specified secondary** estimator in WO-003. Both are reported.
4. **Σ must be calibrated before any real-data use** (WO-006). No QC threshold or integration weight relies on the uncalibrated Σ.
5. **The PR is accepted for merge:** CI green; no identity leaks in the added files (Planner scan); figures are synthetic and carry only Matplotlib metadata.

**Decisions.**
- **WO-006 (Cloud) before WO-003:**
  - calibrate Σ (κ and a relative floor);
  - add a per-patch decorrelation-gain diagnostic from measured L and ℓ_t;
  - add a directional variant that keeps only the across-fibre component and reports the along-fibre component as unobserved;
  - validate all three on synthetic data across fibre orientations.
- **WO-003 rev 4: a go/no-go feasibility pilot on a held-out PHerc0139 segment comes first** (pre-registered below and in the WO). A no-go stops WO-003 and returns to the Planner.
- **Gap-width stratification** (clear / narrow / touching wraps, from step 0) becomes a pre-specified secondary analysis of S2 and the value claim, following the B4-versus-LPSF physics in Argon's note (`notes/2026-11-01-gemini-review.md` follow-up).
- **Honest prior for the value claim:** B4 (structure-tensor normal) does not suffer the decorrelation pull. If the pilot shows that only across-fibre components are usable, LPSF's claim narrows to "complementary where boundary contrast fails". That claim survives only if the gap-stratified fusion test shows it.

**Reversal.** If the pilot passes cleanly on full 2-D slopes (not only across-fibre), the directional restriction can be dropped for WO-003.

---

## DR-012 — 2026-11-01 — Upstream contribution policy: no low-value PRs to villa

**Context.** A VC3D maintainer (Discord, 2026-11-01; T3, Project note only) announced that scripts the team no longer uses will be retired, because PRs to unused scripts, many of them LLM-generated, have become a major time sink.

**Decision.**
1. **WO-004 (the villa README `accept_terms` fix) is cancelled.** Even a correct docs fix is the kind of low-value, LLM-authored PR the team asked people to stop sending. We mention the stale line once on Discord, or in issue #199, only if it comes up naturally.
2. **No PR to villa without the team's prior interest.** Upstream integration (BACKLOG) starts with a Discord conversation that shows the Annotation Team or maintainers want it. Until then, our tools read and write their formats standalone.
3. Bug reports go to existing issues, with a minimal reproduction, only for tools the team actively uses. For example, the `vc_render_tifxyz` skip-on-existing-outputs behaviour is reported only if the team confirms it affects them.
4. Our PRs, when invited, are small, human-reviewed by Kevin, and disclose AI assistance.
