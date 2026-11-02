# WO-001 data survey

Checked 2026-10-31 to 2026-11-01. Sources: `s3://vesuvius-challenge-open-data/` [`scrollprize_data`, `open_data_repo`], dl.ash2txt.org, `/prizes` [`scrollprize_prizes`] and villa at the pin [`villa`]. Tables come from the run records in `survey/` and `run-records/`. Compute: one workstation CPU, no GPU; every volume read streamed from S3. No scroll data is in this repo.

## Decisions needed

1. **No public metadata marks any segment Approved, Defective or Reviewed.** Criteria that depend on those tags cannot be met as written (section 3). The primary WO-003 validation does not depend on tags. I used labelled stand-ins and did not call them Approved.
2. **Keep PHerc. Paris 4 out of WO-003 unless permission is obtained.** Its notice bars publishing "formal analyses" based on the data until 25/06/2027 (section 4).
3. **Decide the voxel size for WO-003.** Its amplitudes and its ±10 layer window are in voxels, and the study meshes here are 2.399 µm (section 9).

## 1. All samples with segments

From `survey/<sample>.parquet`. "Volume on S3" means the primary mesh's volume is in `<sample>/volumes/`. Survey time per sample: seconds to about 90 s.

| Sample | Segments on S3 | With tifxyz | Volume on S3 | With ink labels | Tagged | Legacy-only folders | `_superseded` |
|---|---:|---:|---:|---:|---:|---:|---:|
| PHercParis4 | 82 | 82 | 70 | 8 | 7 | 272 | 25 |
| PHerc0172 | 53 | 53 | 53 | 0 | 0 | 23 | 0 |
| PHerc0500P2 | 46 | 46 | 46 | 1 | 0 | 0 | 0 |
| PHerc0139 | 39 | 39 | 38 | 8 | 14 | 0 | 0 |
| PHerc1667 | 20 | 20 | 0 | 6 | 0 | 6 | 0 |
| PHerc0009B | 20 | 18 | 18 | 1 | 0 | 0 | 0 |
| PHerc0814 | 19 | 19 | 19 | 1 | 0 | 0 | 0 |
| PHerc1447 | 16 | 15 | 15 | 0 | 1 | 0 | 0 |
| PHercMANBp | 11 | 11 | 0 | 0 | 0 | 0 | 0 |
| PHerc0343P | 8 | 8 | 8 | 0 | 0 | 0 | 0 |
| PHerc0800 | 6 | 6 | 6 | 0 | 0 | 0 | 0 |
| PHerc0841 | 3 | 3 | 3 | 3 | 0 | 0 | 0 |
| PHerc0332 | 2 | 2 | 0 | 0 | 0 | 14 | 0 |
| PHercMAN5 | 1 | 1 | 0 | 0 | 0 | 0 | 0 |

**Layout, which differs from the primer.** Meshes are at `{sample}/segments/<dir>/mesh/<id>-on-<volume>-<res>.tifxyz/`, one folder per registered volume, plus `mesh/intermediate/tifxyz_{original,normalized,flattened}/`. Segment folders can carry a suffix (`20250108000000-w025_2025010863`). `metadata.json` at the bucket root has per-segment entries, but its `width` and `height` do not describe the `-on-` meshes, so the survey reads the TIFF headers instead. The bucket's volumes are 8-bit, Zarr v2, uncompressed, 128³ chunks, with `/`-separated keys (checked on three).

**Mesh choice.** `vch fetch` defaults to the mesh on the volume the segment was traced on. Issue #1845 reports a 0.040 AUC cost for rendering a coarse mesh carried in by transform instead of the scan's own mesh [`villa_issue1845`, T3, not replicated]. It is why we do not mix frames.

**Areas are approximate.** `area_cm2` comes from `meta.json`. `area_cm2_derived` is `area_vx2 × voxel²` of the primary mesh. They agree on PHerc0139 (median ratio 1.03) apart from one outlier, `w040` at 0.51, but on PHercParis4 the ratio has a median of 1.60 and reaches 1.69. I did not resolve why. Do not use these columns for anything beyond rough sizing.

## 2. Tag census

| Where | Files read | `approved` | `defective` | `reviewed` | `inspect` | `partial_review` |
|---|---:|---:|---:|---:|---:|---:|
| S3, all `meta.json` under `mesh/`, 14 samples | 1,539 | 0 | 0 | 0 | 21 segments | 1 segment |
| Legacy `paths/*/meta.json`, 7 samples with readable files | 345 | 0 | 0 | 0 | 0 | 0 |

Tagged segments: PHerc0139 14 `inspect`, PHercParis4 7 `inspect` (the `5753_*` series), PHerc1447 1 `partial_review` (`20250703034159`). The segment-level counts are in the run records. The two file counts come from a one-off scan, kept in the provenance log, and fragment samples in the legacy tree were part of that scan only.

Three other places were checked. `used_approved_segments` appears in `meta.json` on PHerc0814 and PHerc0009B, but it is an empty list every time. The site's `data_browser/index.json` at the pin has no `approved`, `defective` or `inspect`. Legacy `meta.json` holds `name`, `type`, `uuid`, `vcps`, `volume`, `vcano`.

**Reading this.** No tag does not mean unreviewed. VC3D stores review tags as record tags in its object store (`upstream-audit.md` section 5), so the team may keep them somewhere that is not public. **Still unverified: where the team's review tags live, and whether they can be shared.** Kevin can ask on Discord.

**`inspect` is not a quality signal.** It marks something to look at, not a failure. `w044` carries it, and it has the highest published ink AUC in issue #1912's table (0.966) [`villa_issue1912`, T3]. I do not treat it as a stand-in for Defective.

## 3. What the missing tags block

| Item | Effect |
|---|---|
| WO-001 deliverable 5, "one Approved segment" | **Not met.** The I/O proof used an untagged stand-in. The proof does not depend on review status |
| WO-001 deliverable 6, Approved tag, Defective counterpart | **Not met.** Stand-ins and evidence-based counterparts in section 8 |
| Second sample "with many reviewed segments" | No sample has any. Chosen by the tags that exist, plus usability (section 5) |
| WO-003 method step 7, Approved vs. Defective | Skips by its own condition ("if WO-001 found tagged Defective segments") |
| `method-lpsf.md` section 5, "a published, reviewed tifxyz segment" | Weakened to "published". Paired differences cancel pre-existing error, so primary validation survives |

## 4. PHercParis4 (Scroll 1)

82 segments on S3, all with tifxyz. 70 have their primary mesh on the 2.4 µm volume `20260411134726`, and 12 on `20230205180739` (7.91 µm), which is not under `volumes/`. Tags: 7 `inspect`. In the legacy tree, 25 folders end in `_superseded`, and 272 folders are not on S3.

| June candidate | On S3? | Legacy `paths/` | Status |
|---|---|---|---|
| 20230827161846 | **No** | `20230827161846_superseded/` | Superseded. No tifxyz, no tags |
| 20231210121321 | Yes, with meshes on 7.91, 2.4, 1.129 and 45.532 µm volumes | `20231210121321/` | Usable. Has ink labels, no tags |
| 20230902141231 | **No** | `20230902141231/` | Legacy only. No tifxyz, no tags |

20241108120732 is not in this sample, as the primer says. The data browser's count of 82 matches.

**Publication reservation: scope, closing the primer gap.** From the site's Paris 4 notice [`villa_atlas_overlay`, read at the pin; the live page was not checked separately]:

- It covers "the raw scan data, virtually unwrapped segments, ink-enhanced data, ink identifications, and related derived materials".
- Users "may examine, study, test, and analyze the data, but may not publish scholarly claims, transcriptions, translations, editions, interpretations, or formal analyses based on the data without permission".
- It is "a modification of the CC BY-NC 4.0 license" and "runs until 25/06/2027".

A WO-003 report of results on this scroll could count as a "formal analysis". Whether a QC method report does is a question for the Vesuvius Challenge, not for us. Until it is answered, treat it as barred, as `docs/data-licensing.md` already says. This survey publishes only IDs and counts.

## 5. Second sample: PHerc0139

| | PHerc0139 | PHerc1667 |
|---|---|---|
| Segments | 39 | 20 |
| Tags | 14 `inspect` | None |
| Ink labels | 8 | 6 |
| Primary mesh | 2.399 µm, volume on S3 (38 of 39) | 7.91 µm, that volume **not** under `volumes/`. A 2.399 µm volume exists and meshes may be available, not checked |
| Status | CC BY-NC per `docs/data-licensing.md`. Embargo lifted 2026-06-25 per a comment in the site's `buildIndex.js` | Scroll 4: EduceLab terms for its older scans, so check the terms per scan. Same embargo note |

**Choice: PHerc0139.** It has more segments, the only tags available in a usable sample, and needs no second volume lookup. It also has public defect measurements [`pherc0139_defects`] and a published winding table, which give it evidence that tags do not. Winding numbers in this report follow that table's names.

## 6. FASP `state.tif`

**It still exists.**

| Field | Value |
|---|---|
| URL | `https://dl.ash2txt.org/community-uploads/waldkauz/fasp/v1/masks/state.tif` |
| Size | 17,022 bytes |
| SHA-256 | `235b655516a04c91affc791221a9c446ab57686366e752af19f80acbebcb5eac` |
| Server date | 2024-12-31 |
| Contents | 156 × 1676, `uint8`. Values: 0 (40,238 px, 15.4%), 80 (60,599 px, 23.2%), 100 (160,619 px, 61.4%), matching the documented 0/80/100 |

It describes the surface `v1/fasp_fill_hr_20241230145834485`, which is also there, and a later erratum makes `v3` and `v4` the corrected surfaces. **That surface is almost certainly Paris 4**: FASP's goal was to reproduce the 2023 Grand Prize result, and the mesh bbox fits Scroll 1. That is my inference, not a stated fact, and it would put WO-003's `state.tif` AUROC under the reservation in section 4.

## 7. Deadline

Checked 2026-11-01 05:01 UTC, which is still 2026-10-31 in Pacific time. `/prizes` says "The next deadline is 11:59pm Pacific, October 31st, 2026!", last modified 2026-10-30. **The November deadline is still not posted, so this stays unverified.** Open prize pool on the same page: $2,140,000. Grand Prize, First Letters and Paris 4 title deadlines: June 25th, 2027, 11:59pm Pacific. Re-check `/prizes` after the October window closes.

## 8. Study segments for WO-003

**None of these is Approved.** All are PHerc0139 on volume `20260102150214` (2.399 µm), with fiber texture I confirmed by eye at their central crops. Ink-label AUCs are from #1912's table, on this same scan's published surface volume [T3, not replicated].

| Priority | Segment | Winding | Tag | Ink labels | AUC | Why |
|---|---|---:|---|---|---:|---|
| 1 | 20260112000000 | w043 | None | Yes | 0.920 | Best stand-in for "reviewed": labelled and read well, no flag |
| 2 | 20260127000000 | w057 | None | No | Not measured | No flag. No labels, so fewer ink worries in figures. The I/O proof segment |
| 3 | 20260115000000 | w044 | `inspect` | Yes | 0.966 | Neighbour of w043; tests whether `inspect` says anything |
| 4 | 20260210000000 | w058 | `inspect` | No | Not measured | Neighbour of w057. **Dark letter-scale shapes in its crop: see section 10** |

**Defective counterpart: none tagged. Two evidence-based options**, neither pre-registered, so adding either is the Planner's call:

- **w044 on the March scan.** Mesh `20260115000000-on-20260319133554-2.403um.tifxyz` exists, and #1912 reports the ink about 96 µm off it (AUC 0.70, against 0.90 after a depth correction). Same papyrus, one good mesh and one bad. But 96 µm is about 40 voxels, well outside ±10 layers, and a constant offset is invisible to the shift field (`method-lpsf.md`). LPSF should only see any non-constant part.
- **w034 to w036.** [`pherc0139_defects`, `villa_issue2167`] measures real geometry errors there: w036 inside w034 on 42% of rays in the sector missing from w035, with example vertices. Issue #2167 is open. Whether these are errors, or real geometry, is unresolved.

## 9. Voxel size and cost for WO-003

WO-003 sets its values in voxels. At 2.399 µm:

| Quantity | Voxels | Physical |
|---|---:|---:|
| 21 layers at step 1 | ±10 | ±24 µm |
| Bump amplitudes | 1 to 8 | 2.4 to 19 µm |
| Crop of 1 cm² | 4,168 px on a side | 17.4 Mpx |

For scale, #2167's note gives a local winding pitch of about 113 µm in part of this scroll, so the whole stack spans less than half of one sheet spacing. That may suit tilt estimation and may be too narrow to reach a sheet boundary. It is a design question. WO-003's thresholds are pre-registered, so a change has to be made before data is seen. The alternative is the 9.362 µm mesh on `20250728140407` of the same segments, where the same flags span ±94 µm.

Texture stays correlated over only a few voxels here. Between the on-surface layer and Python samples along the normal, Pearson r falls to 0.92 to 0.94 at ±1 voxel, 0.75 to 0.81 at ±2 and 0.56 to 0.65 at ±3 (four segments, record `pearson_by_python_offset`). The on-surface value is 0.99.

**Cost estimate:** a 1 Mpx crop took 44 to 59 s to render and 12 MB per 21-layer stack, streaming from S3. If that scales linearly, which I did not measure, 1 cm² takes about 15 minutes and 210 MB per render. WO-003's 19 perturbations plus the original at one slice step would then need about 5 hours and 4 GB per segment, and P1's extra slice steps add to that. Caching the needed volume region locally should reduce the time.

## 10. I/O proof

**Segment:** `PHerc0139/20260127000000-w057_2026012713`, a labelled stand-in, **not Approved**. Mesh `20260127000000-on-20260102150214-2.399um.tifxyz`, manifest in `manifests/PHerc0139/`.

All 21 layers at `--num-slices 21 --slice-step 1 --scale 1 --group-idx 0`, crop 1024×1024, k₀ = 10. r is Pearson between rendered layer 10 and an independent read: mesh through `vesuvius.tifxyz`, voxels through `vesuvius.Volume`, 65,536 points. Best offset is in voxels along the normal.

| Segment | Shape | dtype | Voxel | Render | `Volume` read | r at k₀ | Best offset | k₀ mean | k₀ std | k₀ gradient energy |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| w057 | 1024×1024 × 21 | uint8 | 2.399 µm | 53 s | 60 s | 0.994 | 0 | 120.1 | 37.2 | 51.5 |
| w058 | 1024×1024 × 21 | uint8 | 2.399 µm | 44 s | 62 s | 0.995 | 0 | 91.9 | 42.1 | 55.5 |
| w043 | 1024×1024 × 21 | uint8 | 2.399 µm | 59 s | 60 s | 0.994 | 0 | 90.6 | 37.3 | 62.3 |
| w044 | 1024×1024 × 21 | uint8 | 2.399 µm | 55 s | 79 s | 0.992 | 0 | 91.4 | 32.0 | 57.5 |

The render and the `vesuvius` read agree across all four segments, and each best offset is zero, so the pinned `vesuvius` and the May renderer agree on geometry and on the volume at the pixel level.

**Reproduction:** re-running the logged `command_shell` unchanged, with the first render moved aside, wrote 21 new layers in 55.5 s, and 21 of 21 match the record's pixel hashes (21 of 21 byte-identical files). See `run-records/20260127000000.reproduce-check.json`. The logged command writes to the same path, so re-running it needs the old `layers/` moved first, and it must run from the repo root, because it mounts `$PWD/data` (WO-005).

**A failure worth recording.** My first reproduction check passed 21 of 21 in 1.6 s and was **false**. `vc_render_tifxyz` exits 0 without rendering when all its output files exist, so it compared old files with themselves. `vch render` now refuses to run over existing layers, and the result above comes from a re-run with the first render moved aside. Any tool wrapping this binary should do the same.

**Figures: not committed.** Figures of layers 9, 10 and 11 exist for the four segments in `data/derived/figures/`, which git ignores. I did not recognise any letter in them. But each crop is only 2.46 mm wide, about one letter, and they contain dark shapes at that scale, strongest in w058. I cannot rule out ink. `docs/data-licensing.md` says that if in doubt, show the field alone, so these need review by Kevin and the Planner before any use. For the record, the WO's own rule ("only if no text is legible") permitted saving them; the repo rule on committing is the stricter one.

## 11. Attribution

Data: "Vesuvius Challenge – CT Scans of Herculaneum Papyri" (Angelotti et al.) per the data page; Parsons et al. 2023 [`parsons2023`] for Scrolls 1–4. Tools: villa at the pin, image digest in DR-004.
