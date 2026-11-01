# CLAUDE.md: instructions for Cloud and VSCode agents

You are executing a work order (WO) for `vesuvius-challenge`. The Planner (a separate claude.ai Project) wrote it, and Kevin reviews your PR. Read these first: `planning/WO-NNN-*.md` (your task), `docs/workflow.md` (roles and lifecycle), `docs/decisions.md` (binding decisions), and `docs/data-licensing.md` (hard rules).

## Hard rules

1. **Never commit scroll data.** Nothing from the data server goes under git: no volumes, surface volumes, tifxyz meshes, `.obj`, `.ppm`, or renders. `data/` is gitignored; keep it that way. Manifests (IDs, URLs, checksums) are fine.
2. **Never publish or commit renders that show legible text or ink** (`docs/data-licensing.md`).
3. **Stay in scope.** Do what the WO says and nothing in its "Out of scope" section. If the WO is wrong or blocked, stop and write the problem in the provenance log. Don't improvise a redesign.
4. **Use upstream tools; don't re-implement them.** Use `vesuvius` (Volume, `vesuvius.tifxyz`) and VC3D binaries (`vc_render_tifxyz`, `vc_objrefine`) through the Podman image. Never vendor or link GPL code; run VC3D tools as subprocesses.
5. **Cite.** Every methodological claim in docs or reports gets a key in `docs/citations.bib` with a tier (T1/T2/T3), URL and access date. Never cite from memory. Mark anything unverified.
6. **Report honestly.** Negative results and failure envelopes are deliverables. Quantify before using adjectives. State the compute used.

## Environment

- Python 3.14 via uv. `uv sync`; `uv run pytest`; `uv run ruff check`; `uv run ruff format`.
- `vesuvius` is installed from ScrollPrize/villa at the commit pinned in `uv.lock`. Do not bump it unless the WO says to.
- Package: `src/vesuvius_challenge/`. CLI: `vch` (Typer), with one subcommand per stage.
- Tests use synthetic fixtures generated in-process only. CI and Cloud have no scroll data.
- VSCode only: Podman, image `ghcr.io/scrollprize/villa/volume-cartographer:edge`. Record `podman image inspect --format '{{.Digest}}'` in run records. Mount data with `-v "$PWD/data:/data" --userns=keep-id`.
- **Cloud:** if a step needs data, Podman or a GPU, it is not your step. Note it in the provenance log and leave it for VSCode.

## UX floor for every program (python-lab-ux)

`rich` + `typer` + `humanize`. Required on every program:

- a startup banner (what it does, key settings, output path);
- `rich.progress` bars with M of N, throughput, elapsed time and ETA;
- a live "what this stage is doing and why" panel;
- live running statistics;
- graceful Ctrl-C that saves partial results with `partial: true`;
- a final summary table with interpretation lines and the exact command to reproduce;
- a JSON run record (all params, seed, timestamps, versions, villa SHA, image digest, source-file hash, results) written next to Parquet outputs;
- a `selftest` command that checks the fast path against a slow reference, using hypothesis where inputs can be generated;
- `rich.traceback.install(show_locals=False)`.

Figures and reports read only from saved run records. Add nvitop and the GPU hardware panel when a WO introduces GPU work.

## Definition of done (every WO)

- Tests green and ruff clean.
- README and CHANGELOG (Keep a Changelog, under `[Unreleased]`) updated **in the same PR**.
- Provenance log appended to the WO file: commands, villa SHA, image digest, data IDs and checksums, surprises.
- Branch `wo-NNN-short-name`, conventional commits, PR description linking the WO.
