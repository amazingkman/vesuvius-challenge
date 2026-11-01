# Workflow: Planner → work order → Cloud or VSCode → Kevin

## Roles

| Role | Where | Can | Cannot |
|---|---|---|---|
| **Planner** | claude.ai Project "Vesuvius Challenge" | Research, design review, decision records, work orders, report review | Write implementation code; access the repo or data directly |
| **Cloud** | claude.ai/code on GitHub `vesuvius-challenge` | Pure-code WOs: library code, synthetic harness, tests, CI, docs, upstream PR drafts | Access scroll data; run Podman/VC3D; use a GPU; run long jobs |
| **VSCode** | Claude Code in VSCode on Duskrider (Ubuntu 24.04, RTX Pro 4000 Blackwell 24 GB, 64 GB RAM) | Data download, Podman/VC3D renders, real-data runs, profiling | Commit anything under `data/` |
| **Kevin** | — | Reviews and merges every PR; Discord checks; prize submissions; anything public | — |

## Work order lifecycle

1. Planner writes `planning/WO-NNN-short-name.md`, naming one **Executor** (Cloud or VSCode). Kevin commits it to `main`.
2. Kevin tells the executor: "Execute planning/WO-NNN-short-name.md".
3. The executor works on branch `wo-NNN-short-name` and opens a PR. Every WO ends with:
   - tests green (`uv run pytest`) and `uv run ruff check` clean;
   - README and CHANGELOG updated in the same PR;
   - a provenance log appended to the WO file: commands run, villa SHA, container image digest, data identifiers, anything surprising;
   - commits using conventional prefixes (`feat:`, `fix:`, `docs:`, `test:`, `chore:`).
4. Kevin reviews and merges. Any WO that produced findings, figures or a report goes back to the Planner for review before anything is public.

## Work order template

```
# WO-NNN — Title
Executor: Cloud | VSCode     Depends on: WO-…     Status: issued
1. Objective (one testable paragraph)
2. Background & citations (what this builds on; bib keys)
3. Inputs
4. Deliverables (files; always README + CHANGELOG)
5. Acceptance criteria (objective checks)
6. Out of scope
7. Provenance log (executor appends)
```

## Hand-offs between executors

Cloud writes code that never needs scroll data: all tests use synthetic fixtures generated in-process. VSCode runs that code on real data. When a VSCode WO depends on Cloud's code, it starts from merged `main`.
