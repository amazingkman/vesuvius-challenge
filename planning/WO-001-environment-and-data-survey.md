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
