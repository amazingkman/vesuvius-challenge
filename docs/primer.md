# Vesuvius Challenge primer: state as of 2026-10-31

This replaces the 2026-06-12 primer. Section 7 lists which June claims were wrong or have gone stale. All sources were accessed between 2026-10-31 and 2026-11-01. Tiers: T1 = peer-reviewed or official scrollprize.org/EduceLab; T2 = Substack and prize announcements; T3 = community repos, issues and PRs. Anything marked *unverified* must be checked before we rely on it.

## 1. Program and prizes

- **Total awarded:** $1,958,500 [T1: scrollprize.org/winners].
- **2027 Grand Prize: $1M** ($800K / $100K / $50K / $50K for places 1–4).
  - Task: fully unroll and make readable one of 13 eligible scrolls (PHerc0125, 0191, 0211, 0257, 0268, 0358, 0800, 0813, 0826, 1203, 1218, 1447, 1545).
  - Limits: at most 8 documented hours of human input; meshes in tifxyz; the pipeline must be "seamlessly integrated in the VC3D software".
  - Deadline: 25 June 2027.
  - Rules: code open source (e.g. MIT); datasets and checkpoints CC BY-NC 4.0 [T1: scrollprize.org/prizes].
- **First Letters: $50K per scroll**, up to 9 more ($450K). 10 letters within 4 cm². 21 eligible volumes; PHerc0343 is now excluded because it has been won. **PHerc. Paris 4 title: $50K.** Both deadlines are 25 June 2027 [T1].
- **Monthly progress prizes:**
  - a guaranteed $20K "Best Submission of the Month";
  - other awards, "typically $20,000, $10,000, $5,000, $2,500, $1,000, $500 or $250";
  - submission through the Google Form linked on /prizes; small PRs from one month are bundled into one submission; methods, models and datasets are submitted separately [T1].
- **Deadlines:** October's was 11:59pm PT, 31 Oct 2026. **November's was not yet posted, so check /prizes** [T1].
- **What gets rewarded** [T1: /prizes]:
  - released early;
  - actually used, with the Annotation Team commenting publicly on tools it uses;
  - shown on real data;
  - analytic tools must show they "facilitated improvements… e.g. by detecting failure-cases of existing methods on real scroll data";
  - standard formats (OME-Zarr/Zarr, tifxyz, triangle meshes);
  - designed for modular integration;
  - well documented.
- **Rules:**
  - Work must be open-sourced under a permissive license to accept a prize.
  - You must be registered on Discord when you submit.
  - Discoveries stay unpublicized until officially announced.
  - Hallucination: there is no longer a numeric window limit. "Large windows are fine, but you must demonstrate that the text is not hallucinated." Held-out validation is required [T1].

## 2. Milestones since June 2026

- **25 Jun 2026:** PHerc. 1667 fully unwrapped and read end to end. PHerc. 139 identified as Philodemus, *On Gods*, Book 8. About 140 columns of PHerc. Paris 4 shown from a 2.4 µm BM18 rescan. Preprint arXiv:2606.29085 [T2: scrollprize.substack.com/p/a-new-1m-grand-prize-for-2027; T1].
- **15 Jul 2026:** the $1M 2027 Grand Prize and the "$2M+" prize pool were announced [T2].
- **8 Oct 2026:** First Letters for PHerc. 343 ($50K) awarded to Erwin Nieuwlaar, who used the open-source spiral fitter and an average of four public 9 µm ink models [T1 winners; T2 scrollprize.substack.com/p/50k-first-letters-prize-awarded-for].
- **Progress prizes paid:** Jun $3,000; Jul $33,500; Aug $31,000; Sep $40,500 [T1]. Several awards went to segmentation QC tools: TIFXYZ Doctor, windcheck, windaudit, scroll-data-audit and tifxyz repair. None targeted sub-pixel layer alignment or render-sharpness QC.

## 3. Segmentation, the current pipeline

- **VC3D** (villa `volume-cartographer/`) is the team's main tool. It is semi-automated: GrowPatch (Ceres optimization along the recto surface prediction), Copy Out/In for neighbouring wraps (including a neural version), and a neural-tracer panel. Releases: "VC3D Stable" 2 Aug 2026 and "VC3D Latest" 6 Oct 2026. Container: `ghcr.io/scrollprize/villa/volume-cartographer:edge` [T1 Open Problems; T3 villa].
- **Spiral fitting** (Henderson, WACV 2026, arXiv:2512.04927) is described as "our current state of the art" for whole-scroll segmentation, and a July award made it run on 12 GB GPUs [T1].
- **Lasagna** (villa `lasagna/`) is PyTorch multi-sheet optimization and fiber tracing. It has a local-correction mode that moves a draft surface toward the true one [T1].
- **Deprecated:** ThaumatoAnakalyptor, now in villa `deprecated/`. **Historical:** FASP, whose tools survive in VC3D (`vc_grow_seg_from_segments`, `vc_tifxyz_winding`) [T3].
- **Kaggle Surface Detection (2026):** $200K pool. Metric 0.30·TopoScore + 0.35·SurfaceDice@2 + 0.35·VOI. Won by a long-trained nnU-Net ensemble, released as `surface_m7_nnunet` [T1 winners; T3 writeups].
- **QC today:**
  - human inspection in VC3D ("check if you can visually follow horizontal papyrus fibers") with meta.json tags;
  - winding annotations feeding the spiral fit;
  - `vc_tifxyz_winding`;
  - community checkers (TIFXYZ Doctor, windcheck, spiralcheck, windaudit, scroll-data-audit).
  The team has **no official automated quality metric**. Open Problems lists "stronger diagnostics" and scan-quality metrics as needs [T1].

## 4. Tooling we build on

- **`vesuvius` Python package** (villa `vesuvius/`, MIT):
  - **Version:** PyPI 0.2.4 is stale. villa `main` requires Python 3.14. Pin a commit (DR-004).
  - **Core API:** `vesuvius.Volume` streams OME-Zarr from S3 with caching. Reading meshes uses `vesuvius.tifxyz.Tifxyz` / `read_tifxyz()`.
  - **CLI entry points** (from pyproject): `predict`, `compute_st`, `voxelize_obj`, `refine_labels`, `train`, `zarr_tasks`, `find_patches`, `surface_preflight`, and others.
  - **Removed:** `accept_terms` (see `docs/data-licensing.md`). The README table still lists it; WO-004 fixes that.
  - **Unverified:** whether PR #2365 (tifxyz extra, read+write) and PR #2373 (Python tifxyz renderer) are merged at our pin.
  [T3]
- **`vc_render_tifxyz`** (VC3D, C++): `--num-slices N --slice-step s`, can stream with `--remote-url`. FASP-era docs describe 21 layers 1 voxel apart, with layer 10 central [T3].
- **`vc_objrefine`:** per-vertex alpha-composite normal offset. PR #2224 adds an offset report, and PR #2358 ports it to `refine_surface` [T3]. These are our baseline and integration target.
- **Issue fit:** villa #193, "methods for generating surface, fiber or ink labels" (help wanted / progress-prize candidate), is the closest home for LPSF. No issue exists about layer-32 optimization or render sharpness [T3].

## 5. Data

- **Where it lives:**
  - `s3://vesuvius-challenge-open-data/`, also on the AWS Open Data registry; anonymous reads work;
  - dl.ash2txt.org for legacy `.volpkg` data and community uploads;
  - Hugging Face for curated sets.
  [T1 scrollprize.org/data; T3 open-data README]
- **Layout** (open-data README): `{sample}/volumes|segments|representations`. A segment has `mesh/tifxyz/{x,y,z}.tif + meta.json`, `mesh/intermediate/*.obj`, and `surface-volumes/{res}-{energy}-volume-{id}.zarr|.tifs`. Volumes are 8-bit OME-Zarr with 128³ chunks [T3].
- **Layer conventions are inconsistent, so check per segment:**
  - legacy VC: 65 layers, 32 = middle [T1 tutorial_VC];
  - FASP / `vc_render_tifxyz` examples: 21 layers, 10 = middle;
  - published 9 µm segments: 28 layers;
  - the open-data README labels "00.tif # Layer 0 (surface)", which contradicts the others.
  **We render our own surface volumes with explicit flags** and avoid this ambiguity entirely.
- **Scroll 1 segments:**
  - The data browser lists 82 segments.
  - Some legacy `paths/` folders now carry a `_superseded` suffix (villa PR #2132, 21 Oct 2026).
  - June candidate IDs 20230827161846, 20231210121321 and 20230902141231 are **unverified**.
  - **20241108120732 is Scroll 5 (PHerc. 172), not Scroll 1.**
- **FASP `state.tif`** (0 = no surface / 80 = infilled / 100 = high quality) was documented at dl.ash2txt.org/community-uploads/waldkauz/fasp/; current hosting is **unverified** [T3].

## 6. Self-supervised learning (context for DR-006)

- dinovol 3D DINO in villa, with released checkpoints such as `dinovol_v2_ps8_with_paris4_352500` [T1].
- ScrollMAE, Large Scroll Model, DINOv2-vesuvius, and DINO-guided fiber/ink models [T1 community_projects].

## 7. Audit of the June 2026 documents

| June claim | Status now |
|---|---|
| $1,800,500 awarded | Stale. Now $1,958,500 |
| First Letters / First Title $60K each, Scrolls 2–3 | Changed. First Letters $50K per scroll (21 volumes); title prize only for PHerc. Paris 4 ($50K) |
| $200K Read Entire Scroll | Superseded by the $1M 2027 Grand Prize |
| Gold Aureus / Denarius / Sestertius / Papyrus tiers | Changed. Guaranteed $20K plus typical amounts; coin names gone |
| Roth & Nowak First Title, PHerc. 172, Philodemus *On Vices* | True (May 2025); "Book 1, though just possibly Book 4" |
| ~70% of PHerc. 172 unwrapped | True ("bottom 70%") |
| "Sharpening the layers rendering… layer 32…" is an open wishlist item | **Wrong.** It is segmata's own project description, which makes it prior art (DR-001 superseded) |
| Method A is a "clean gap" with HIGH novelty | **Wrong.** Refinement is prior art; QC is partial prior art; only the estimator kernel is new (DR-002) |
| VC3D tags Approved/Defective/Reviewed/Revisit/Inspect | Probably true; one snapshot omits Revisit. Verify in WO-001 |
| VC fork lineage; maintained in villa | True |
| Team trained a 3D DINO | True (dinovol) |
| Standalone ScrollPrize/vesuvius archived | True (21 Nov 2024) |
| Kaggle Surface Detection $100K; Surface Dice/TopoScore/VOI | Partly wrong. The pool was $200K; the metrics are right (0.30/0.35/0.35) |
| Windows > 0.5×0.5 mm discouraged | Changed. No numeric limit now; you must demonstrate no hallucination |
| 64×64 patch default justified by the 0.5 mm window rule | **Justification void.** 64×64 stays only as a starting point; WO-002 chooses patch size from the accuracy/resolution trade-off |
| Segment 20241108120732 listed as an example Scroll 1 GP segment | **Wrong.** It is Scroll 5 |
| ~65 layers, middle = on-surface, treated as universal | Wrong as a universal. Conventions vary (§5) |
| `pip install vesuvius` + `vesuvius.accept_terms --yes` | Stale. PyPI is older than villa main, and accept_terms was removed |
| Validation against FASP `state.tif` as the primary statistic | Demoted. Hosting is unverified, and injected perturbations give real ground truth (DR-002) |

## 8. Gaps we did not close

- **Not searched:** Discord; villa full code text.
- **Unverified merge status:** PRs #2224, #2365, #2368, #2373.
- **Not posted yet:** the November deadline.
- **Unknown scope:** the Paris 4 publication reservation.

WO-001 closes the checkable ones.
