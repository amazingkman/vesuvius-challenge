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
├── scripts/  notebooks/  reports/YYYY-MM-name/
└── data/                    # gitignored: raw/ segments/ renders/ derived/
```

## Setup

Python 3.14 is required because villa `main`'s `vesuvius` package declares `requires-python = ">=3.14,<3.15"` (checked 2026-10-31).

```bash
uv sync                      # resolves the pinned villa commit from uv.lock
uv run vch --help            # available once WO-002 lands
podman pull ghcr.io/scrollprize/villa/volume-cartographer:edge   # renderer, needed from WO-001 on
```

Dependencies (see `pyproject.toml`): vesuvius[volume-only] (git, pinned), numpy, scipy, scikit-image, tifffile, zarr, matplotlib, xarray, rich, typer, humanize, psutil, pydantic, tomli-w, pyarrow, duckdb; dev: pytest, hypothesis, ruff, pyinstrument.

## Data and attribution

Scroll data is never committed or redistributed. Scrolls 1–4 and Fragments 1–6 are EduceLab-Scrolls data, © EduceLab/University of Kentucky. Cite Parsons et al. 2023 (arXiv:2304.02084) and use the required methods-section sentence. Newer scans are CC BY-NC 4.0. The full terms, and what we may publish, are in `docs/data-licensing.md`.

## Status

See `CHANGELOG.md` and `planning/`. As of 2026-10-31: the environment is scaffolded and WO-001 to WO-004 are issued.
