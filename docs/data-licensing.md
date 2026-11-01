# Data licensing and publication rules

Sources: the villa `vesuvius` README, "Data licence" section [T3: github.com/ScrollPrize/villa/tree/main/vesuvius, read 2026-10-31]; scrollprize.org/data and /prizes [T1, accessed 2026-10-31]. This is a working summary, not legal advice. If anything here conflicts with those sources, they win. Re-check them whenever the villa pin changes.

## Which terms apply

| Data | Terms |
|---|---|
| Scrolls 1–4 and Fragments 1–6 (EduceLab-Scrolls; DLS scans before 2025) | EduceLab-Scrolls terms below. © EduceLab / University of Kentucky |
| **PHerc. Paris 4 (Scroll 1), all scans and derived materials** | **A modified CC BY-NC 4.0, running until 2027-06-25.** Users may examine, study, test and analyze the data, but may not publish scholarly claims, transcriptions, translations, editions, interpretations or **formal analyses** based on it without permission [T3: `villa_atlas_overlay`, read at pin 2026-11-01]. **We publish nothing derived from Paris 4, including FASP `state.tif` analyses, without written permission** (DR-008) |
| PHerc0139 (our study scroll) | CC BY-NC 4.0. The embargo was lifted 2026-06-25 per a comment in the site's `buildIndex.js` [T3, WO-001 survey §5] |
| PHerc1667 (Scroll 4) | Older scans fall under EduceLab terms; check each scan |
| All other Vesuvius Challenge datasets (newer scans, e.g. PHerc. 172, 139, 343, the 2025 ESRF scans) | CC BY-NC 4.0 "unless otherwise noted" |
| Curated datasets and checkpoints (Hugging Face) | Check each dataset card |

## EduceLab-Scrolls terms (summary)

- No redistribution of the data without written approval from the Vesuvius Challenge.
- No public disclosure, outside Discord, of any **revelation of hidden text, or the code associated with it**, without written approval.
- Vesuvius Challenge may use submissions and results.
- Manuscripts must include language like: *"Data used in the preparation of this article were obtained from the EduceLab-Scrolls dataset."*, citing Parsons et al. 2023, arXiv:2304.02084.
- Anything posted in Discord is licensed to other participants under the same terms.

## Acceptance

villa `main` removed the `vesuvius.accept_terms` command; its module now says nothing checked that record. Our acceptance is this file plus compliance with it. Kevin accepted the terms when registering for data and Discord. **Discord registration is required at the time of any prize submission** [T1: scrollprize.org/prizes].

## What this repo may contain

| Allowed | Never |
|---|---|
| Code (MIT) | Raw volumes, surface volumes, meshes, `.ppm`, or tifxyz from the data server |
| Segment IDs, URLs, checksums (`MANIFEST.json`) | Any rendering that reveals hidden text or ink, from any scroll, without written approval |
| Derived QC maps (shift, offset, curl fields) and summary statistics, CC BY-NC 4.0, citing the source data | Data from the Discord server |
| Field maps (ĥ, curl, ρ, shift) without the render underneath | **Any render-derived image (layer crops, overlays on renders) in the repo or a PR** (DR-008). They stay in `data/derived/figures/` for private review |
| | Anything analysing PHerc. Paris 4 before 2027-06-25 without written permission |

Rule for figures (tightened 2026-11-01, DR-008): in the repo and in PRs, show **fields alone**, never the render underneath. Render-derived images are for private review in `data/derived/figures/`. Publishing one, for example in a prize submission, needs Planner and Kevin review that confirms no legible text or ink, plus the scroll's terms.

## Attribution checklist for any report or submission

- Data: Parsons et al. 2023 (EduceLab-Scrolls) and/or "Vesuvius Challenge – CT Scans of Herculaneum Papyri" (Angelotti et al.), per the data page.
- Tools: villa (`vesuvius`, VC3D) at the pinned commit; the container image digest.
- Prior methods: everything in `docs/method-lpsf.md` §6.
