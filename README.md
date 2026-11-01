# vesuvius-challenge

Independent, open-source contributions to the [Vesuvius Challenge](https://scrollprize.org) by Kevin Couch. **Not affiliated with or endorsed by the Vesuvius Challenge team / Curious Cases, Inc.**

Current focus: a **label-free diagnostic for segmentation surfaces**. It measures how papyrus texture slides between adjacent layers of a rendered surface volume, turns that into a per-patch *tilt-error* field, and reconstructs a *normal-offset* field from it. The output feeds the community's existing QC and refinement tools (VC3D, `vc_objrefine`, Lasagna); it does not replace them.

## Why this, and why it is built this way

- **Label quality is a named bottleneck.** The official Open Problems page (updated 2026-10-14) calls label quality "one of the main unwrapping bottlenecks" and asks for diagnostics that separate failure modes. [T1: scrollprize.org/2026_open_problems, accessed 2026-10-31]
- **Analytic tools only count if they lead to improvements.** The prize page says analytic tools must "show how they facilitated improvements… for example by detecting failure-cases of existing methods on real scroll data." [T1: scrollprize.org/prizes, accessed 2026-10-31]
- **Moving a surface along its normal using render data already exists.** segmata, `vc_objrefine`, recto-offset, `snap_labels` and Lasagna's local-correction mode all do this. Our contribution is a new *error signal* with known physics and a documented failure envelope, designed to plug into those tools. See `docs/decisions.md` DR-002 and `docs/method-lpsf.md`.

## Method in one paragraph (Layer Phase-Shift Field, LPSF)

Render a segment's surface volume (layers stepped along the mesh normal). For each patch and each pair of adjacent layers, estimate the sub-pixel in-plane translation with Fourier phase correlation [Foroosh et al. 2002; Guizar-Sicairos et al. 2008]. If the mesh is tilted by angle θ relative to the true papyrus sheet, texture that persists through the sheet's thickness slides by Δd·sin θ per layer step Δd. A correctly oriented mesh shows no slide, and a constant offset also shows none. The shift field therefore measures the **gradient of the normal-offset error**. Integrating it (Frankot–Chellappa) recovers the offset up to a constant, and the per-patch depth profile of correlation and intensity pins that constant. The derivation, assumptions and falsification tests are in `docs/method-lpsf.md`. Until WO-002 confirms it on synthetic sheets, the derivation is a hypothesis.

## Built on (we use these tools rather than re-implementing them)

| Tool | Role here | License |
|---|---|---|
| `vesuvius` (ScrollPrize/villa, pinned commit) | Volume / S3 access, `vesuvius.tifxyz` mesh I/O | MIT |
| VC3D `vc_render_tifxyz` (container `ghcr.io/scrollprize/villa/volume-cartographer:edge`, run with Podman) | Render surface volumes with controlled `--num-slices` / `--slice-step` | GPL-3.0 (invoked as an external binary, not linked) |
| VC3D `vc_objrefine` and its offset report (villa PR #2224) | Baseline to beat, and the target for integration | GPL-3.0 (external) |
| TIFXYZ Doctor, offset-sweep | Baselines and prior results we must cite and compare against | see their repos |

## Repository layout

```
vesuvius-challenge/
├── README.md  CHANGELOG.md  LICENSE (MIT)  CLAUDE.md  AGENTS.md
├── pyproject.toml  uv.lock  .python-version (3.14)
├── docs/
│   ├── primer.md            # state of the Challenge (2026-10-31) + claim corrections
│   ├── method-lpsf.md       # LPSF theory, assumptions, falsification tests
│   ├── decisions.md         # dated decision records (DR-NNN)
│   ├── workflow.md          # Planner / Cloud / VSCode roles, WO lifecycle
│   ├── data-licensing.md    # data terms, attribution, what may be published
│   └── citations.bib        # every source, tiered T1/T2/T3, access dates
├── planning/
│   ├── WO-NNN-*.md          # work orders (each names its executor)
│   └── BACKLOG.md
├── src/vesuvius_challenge/  # installable package (CLI: `vch`)
├── tests/                   # pytest + hypothesis; synthetic fixtures only (no scroll data)
├── manifests/               # IDs, URLs, checksums of fetched segments (no scroll data)
├── scripts/  notebooks/  reports/YYYY-MM-name/
└── data/                    # gitignored: raw/ segments/ renders/ derived/
```

## Setup

Python 3.14 is required because villa `main`'s `vesuvius` package declares `requires-python = ">=3.14,<3.15"` (checked 2026-10-31).

```bash
uv sync                      # resolves the pinned villa commit from uv.lock
uv run vch --help            # stages: survey, fetch, render, verify-io, selftest
uv run vch selftest          # fast paths against slow references; synthetic data only
podman pull ghcr.io/scrollprize/villa/volume-cartographer:edge   # renderer, needed from WO-001 on
```

Dependencies (see `pyproject.toml`): vesuvius[volume-only] (git, pinned), numpy, scipy, scikit-image, tifffile, zarr, matplotlib, xarray, rich, typer, humanize, psutil, pydantic, tomli-w, pyarrow, duckdb, opencv-python-headless, numba, imagecodecs; dev: pytest, hypothesis, ruff, pyinstrument.

## Data access

All reads are anonymous. `vch survey` and `vch fetch` use plain HTTPS against `s3://vesuvius-challenge-open-data/`, so no AWS account or credentials are needed.

```bash
uv run vch survey PHerc0139              # data/derived/survey/PHerc0139.parquet + .run.json
uv run vch fetch PHerc0139 20260127000000  # data/segments/PHerc0139/20260127000000/
```

- **Survey output:** one row per segment, with `id`, `has_tifxyz`, mesh size, `tags`, area, `path` and `superseded`, plus which volume the mesh belongs to and whether that volume is on S3. Legacy `paths/` folders on dl.ash2txt.org are included unless you pass `--no-legacy`, because `_superseded` folders exist only there.
- **Mesh layout on S3:** `{sample}/segments/<dir>/mesh/<id>-on-<volume>-<res>.tifxyz/{x,y,z}.tif + meta.json`. A segment has one such folder per registered volume. Pick the one matching the volume you render. `vch fetch` picks the volume the segment was traced on; `--volume` overrides that.
- **Tags:** public `meta.json` files carry no `approved` or `defective` tags, on S3 or in legacy folders. See `reports/2026-11-wo001/data-survey.md` before relying on review status.
- **Resume and integrity:** an interrupted `vch fetch` keeps a `.part` file and continues from it with `Range` and `If-Range`. `MANIFEST.json` records URL, size, ETag and SHA-256, and a copy goes to `manifests/`, which is committed. The data itself never is.
- **`vesuvius.Volume`:** use the `s3://` form with `anon=True`. Over `https://` it cannot list the group's arrays.

## Rendering

`vch render` runs VC3D's `vc_render_tifxyz` in Podman, as an external process, by image digest. It streams the volume from S3, so only the voxels near the crop are read.

```bash
uv run vch render data/segments/PHerc0139/20260127000000 \
    --num-slices 21 --slice-step 1 --crop 18528,14248,1024,1024
uv run vch verify-io data/renders/PHerc0139/20260127000000/n21_s1_x18528_y14248_w1024_h1024
```

- **Output:** `data/renders/<sample>/<segment>/<settings>/layers/NN.tif`, plus `render.run.json` holding the full command, image digest, flags, on-surface layer and a pixel hash for each layer. `vch render` stops if the layers already exist, because `vc_render_tifxyz` then exits successfully without rendering; `--overwrite` renders again.
- **On-surface layer:** layer `k` sits at `(k - (N-1)/2) * step` voxels, so `k0 = (N-1)/2` for odd `N` (21 layers: `k0 = 10`). **An even `N` has no on-surface layer.** Layer numbers are in our own renders; published surface volumes use other conventions.
- **Direction:** with this image, rising layer number moves along the *negative* `vesuvius` normal (measured, see `reports/2026-11-wo001/upstream-audit.md`).
- **Crop:** `x,y,width,height` in output pixels. At `--scale 1 --group-idx 0`, one pixel is one level-0 voxel and the surface measures `grid size / meta.json scale`.
- **`verify-io`:** reads the same surface through `vesuvius.tifxyz` and `vesuvius.Volume` and correlates it with the render, which proves both paths agree.
- **Image age:** the newest published image dates from 2026-05-13, older than our villa pin (DR-004 addendum), and it has no `--flip-normals` flag.

## Data and attribution

Scroll data is never committed or redistributed. Scrolls 1–4 and Fragments 1–6 are EduceLab-Scrolls data, © EduceLab/University of Kentucky. Cite Parsons et al. 2023 (arXiv:2304.02084) and use the required methods-section sentence. Newer scans are CC BY-NC 4.0. The full terms, and what we may publish, are in `docs/data-licensing.md`.

## Status

See `CHANGELOG.md` and `planning/`. As of 2026-11-01: WO-001 is complete apart from the open items in `reports/2026-11-wo001/`, and WO-002 to WO-004 are issued.
