# WO-001 — Environment verification, upstream audit, data survey

Executor: **VSCode** (needs network data access, Podman, the local disk)  Depends on: scaffold commit  Status: issued 2026-10-31

## 1. Objective

Turn every *unverified* item in `docs/primer.md` §8 into a recorded fact, and prove the full I/O path on one segment:

1. pinned villa → `vesuvius` reads a tifxyz mesh and streams its volume;
2. Podman VC3D → `vc_render_tifxyz` renders a small surface volume with explicit layer flags.

At the end you choose the study segments for WO-003, giving reasons.

## 2. Background & citations

- DR-004 (stack) and DR-002 (the novelty gate requires a villa code search). Primer §4–§5 covers tooling, data layout, and inconsistent layer conventions.
- Data layout: `{sample}/segments/<id>/mesh/tifxyz/{x,y,z}.tif + meta.json`, `surface-volumes/…` [T3: `open_data_repo`]. Anonymous S3 is at `s3://vesuvius-challenge-open-data/` [T1: `scrollprize_data`].
- Renderer: `vc_render_tifxyz --num-slices --slice-step` [T3: `villa`, `fasp`].
- Data rules: `docs/data-licensing.md`. Nothing from the server is committed.

## 3. Inputs

- The repo at `main`, after `uv sync`.
- Podman image `ghcr.io/scrollprize/villa/volume-cartographer:edge` (already pulled).
- A shallow reference clone of villa **at the pinned SHA, outside the repo** (e.g. `~/src/villa`), used for reading code only.

## 4. Deliverables

1. **Pin record.** Put VILLA_SHA (from `uv.lock`) and the Podman image digest in a dated addendum to `docs/decisions.md` DR-004 (append; don't edit the record).
2. **Upstream audit**, in `reports/2026-11-wo001/upstream-audit.md`:
   - Whether PRs #2224 (objrefine offset report), #2358, #2365 (tifxyz extra / write), #2368 (snap_labels) and #2373 (Python tifxyz renderer) are present at the pinned SHA. Check with `git log --oneline` and grep in the reference clone.
   - The actual public API of `vesuvius.tifxyz`: read, write, normals, grid scale. If there is no writer, document the exact on-disk format from the code (dtype, NaN/invalid convention, meta.json fields) so WO-003 can write tifxyz with `tifffile`.
   - **The novelty code search for DR-002.** `rg -n -i` across villa for `phase_cross_correlation`, `phase.?corr`, `cross.?power`, `registration`, `fft.*shift`, `layer.?32`, `sharp`, `focus`, `normal.?offset`, `alpha.?composite`. List every hit with its path, plus a one-line judgment: unrelated, related, or prior art.
   - `--help` output of `vc_render_tifxyz`, `vc_objrefine` and `vc_tifxyz_winding` from the container: flags, crop options, output format, and what the on-surface layer index is for a given `--num-slices`.
   - The VC3D tag vocabulary in `meta.json` (confirm Approved/Defective/Reviewed/Revisit/Inspect from the code).
3. **Package skeleton plus three CLI commands**, all at the python-lab-ux floor (`CLAUDE.md`):
   - `vch survey <sample>`: anonymous S3 listing of segments → Parquet with columns: id, has_tifxyz, mesh size, tags, area, path, `_superseded` flag. Plus a summary table.
   - `vch fetch <sample> <segment-id>`: resumable download of the tifxyz mesh and meta.json into `data/segments/<sample>/<id>/`, writing `MANIFEST.json` with URL, size and SHA-256. Manifests may be committed under `manifests/`; the data itself may not.
   - `vch render <segment-dir> --num-slices N --slice-step s [--crop …]`: a Podman wrapper around `vc_render_tifxyz`. It writes to `data/renders/` and records in the run record the full command, image digest, flags and the on-surface layer index.
   - `vch selftest`: at minimum, a round trip of the manifest/IO fixtures.
4. **Data survey**, in `reports/2026-11-wo001/data-survey.md`:
   - **PHercParis4 (Scroll 1):** segment count, tag distribution, and the status of 20230827161846, 20231210121321 and 20230902141231.
   - **One more sample with many reviewed segments.** Candidates: PHerc0139 or PHerc1667. Pick by tag availability.
   - **FASP `state.tif`:** check whether it still exists at dl.ash2txt.org/community-uploads/waldkauz/fasp/ and record the path, size and checksum if so.
   - **Deadline:** the November progress-prize deadline as shown on /prizes, and the date you checked.
5. **I/O proof.**
   - Render a ~1024×1024 px crop of one Approved segment at `--num-slices 21 --slice-step 1`.
   - Save a figure of layers k₀−1, k₀ and k₀+1 **only if no text is legible**; otherwise save texture statistics only.
   - Record shape, dtype, voxel size and timing.
6. **Study-segment choice.** List 2–4 segments for WO-003, each with its reason: Approved tag, fiber texture visible, and ideally a Defective counterpart from the same scroll.
7. README ("Data access" and "Rendering" sections) and CHANGELOG entries.

## 5. Acceptance criteria

- `uv run pytest` and `uv run ruff check` pass. Tests use synthetic fixtures only.
- `git ls-files data/` returns nothing.
- Every primer §8 gap is closed, or explicitly marked "still unverified" with the reason.
- The render run record reproduces the render exactly when the logged command is re-run.
- The code-search table is complete enough for the Planner to write the DR-002 novelty addendum.

## 6. Out of scope

Any phase-correlation or estimator code (that is WO-002, owned by Cloud); perturbation experiments; GPU code; changes to villa.

## 7. Provenance log (executor appends below)

---

**Executor:** Claude Code (VSCode role) on Duskrider, 2026-10-31 to 2026-11-01. Branch `wo-001-environment-and-data-survey`, from `master` (the WO says `main`; the repo's default branch is `master`).

### Pins

| Item | Value |
|---|---|
| Villa | `d57c28ebee8776b618f9851c2289cc407ea99dd4` (`uv.lock`, unchanged) |
| Image | `ghcr.io/scrollprize/villa/volume-cartographer`, `.Digest` `sha256:b2509de2c107852799a5077fd2038a917549a1d1e3665d5a1919c955858d698a`, built 2026-05-13 from `1e3f4c0` |
| Reference clone | `~/src/villa`, depth 400, plus the single commit `1e3f4c0` |
| Python | 3.14.10, uv 0.13.6 |

### Commands

```bash
uv sync
uv add opencv-python-headless numba imagecodecs
uv run vch selftest
for s in PHercParis4 PHerc0139 PHerc1667 PHerc0172 PHerc0500P2 PHerc0009B PHerc0814 PHerc1447 \
         PHercMANBp PHerc0343P PHerc0800 PHerc0841 PHerc0332 PHercMAN5; do
  uv run vch survey $s --out reports/2026-11-wo001/survey
done
uv run vch fetch PHerc0139 20260127000000      # also 20260210000000, 20260112000000, 20260115000000
uv run vch render data/segments/PHerc0139/20260127000000 -n 21 -s 1 --crop 18528,14248,1024,1024 --overwrite
uv run vch verify-io data/renders/PHerc0139/20260127000000/n21_s1_x18528_y14248_w1024_h1024 --figure
# likewise: 20260210000000 crop 18688,14088; 20260112000000 crop 15288,11368; 20260115000000 crop 15368,11248
# reproduction: mv layers layers.first, then run results.command_shell from render.run.json
uvx --from ripgrep rg -n -i --no-heading --hidden -g '!.git' -- '<pattern>' .    # in ~/src/villa, one per pattern
gh pr view <n> --repo ScrollPrize/villa
```

`ripgrep` was not installed, so it ran through `uvx` (15.1.0). The judgments in `code-search-hits.tsv` came from a one-off rule script that is not committed. The rule behind each row is its `reason` column.

### Data

Segments fetched: PHerc0139 20260127000000, 20260210000000, 20260112000000, 20260115000000, each on volume 20260102150214 (2.399 µm). IDs, URLs, sizes, ETags and SHA-256 are in `manifests/PHerc0139/`. Volume: `PHerc0139/volumes/20260102150214-2.399um-0.2m-78keV-masked.zarr`, streamed. FASP `state.tif`: see `reports/2026-11-wo001/data-survey.md`. A Paris 4 mesh (`20260701183148`) was downloaded to a scratch folder to test resume, then deleted. Compute: 16 CPU threads, 59 GB RAM; no GPU. Disk under `data/`: about 160 MB.

### Blocked or not met

- **Deliverables 5 and 6, "Approved" and "Defective":** no public metadata carries those tags (`data-survey.md` sections 2 and 3). Per CLAUDE.md rule 3 this was not redesigned around. The I/O proof ran on a labelled stand-in, and the study list is marked as containing no Approved segment. **Needs Kevin or the Planner.**
- **Figure:** saved under `data/derived/figures/` (gitignored), not committed. No letters recognised, but ink cannot be ruled out at this scale. **Needs review.**
- **Still unverified:** the November deadline (`/prizes` still showed October 31 at 2026-11-01 06:09 UTC), Discord (Kevin), and where team review tags live.

### Surprises

1. The newest published image is 5.5 months older than the pin; `:edge` equals `:main`.
2. `estimate_canvas_offset.py` in villa already does tile-wise phase correlation of renders, for a different purpose.
3. `vc_tifxyz_winding` is removed at the pin, and #2358 holds no offset report.
4. `vesuvius.tifxyz` does not import under `volume-only`. Three dependencies added, pin unchanged.
5. Mesh layout differs from the primer. `metadata.json` `width` and `height` do not describe `-on-` meshes, and 90 meshes are BigTIFF.
6. Rising layer number runs along the negative `vesuvius` normal (measured on four segments).
7. `vc_render_tifxyz` exits 0 and renders nothing when its outputs exist. This made my first reproduction check falsely pass, in 1.6 s. Fixed in `vch render`, and that check and the renders were redone.
8. The Paris 4 notice bars publishing formal analyses until 25/06/2027, which affects WO-003 and probably `state.tif`.
9. `inspect` does not mean poor: w044 has it and the highest ink AUC in villa issue #1912.

### Scope notes

`vch verify-io` was added beyond the WO's listed commands, because objective 1 needs a check that the `vesuvius` read path works. No estimator or phase-correlation code was written. `docs/citations.bib` notes were updated; `docs/primer.md` was not edited, and corrections for it are in `upstream-audit.md` section 8. `vesuvius-challenge-docs.tar.gz` and the empty `vesuvius-challenge/` folder in the repo root predate this WO and were left alone.
