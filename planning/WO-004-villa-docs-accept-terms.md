# WO-004 — Upstream docs fix in villa: the stale `vesuvius.accept_terms` reference

Executor: **Cloud** (Kevin first forks ScrollPrize/villa to his account and attaches the fork to the Cloud session; fallback: VSCode with `gh`)  Depends on: none  Status: issued 2026-10-31

## 1. Objective

Prepare a minimal, correct documentation PR to ScrollPrize/villa. It removes or corrects references to the `vesuvius.accept_terms` command, which no longer exists on `main`: it is not in `[project.scripts]`, and the `install/accept_terms.py` docstring says the licence now lives in the README "Data licence" section. Kevin reviews the diff before the PR is opened.

## 2. Background & citations

- Checked 2026-10-31 on villa `main`. The `vesuvius/README.md` command table lists `vesuvius.accept_terms` with "pass `--yes`…", but `vesuvius/pyproject.toml` `[project.scripts]` has no such entry. Running `uv run vesuvius.accept_terms --yes` fails with "Failed to spawn". [T3: `villa`]
- This fits villa issue #199 (out-of-date documentation; help wanted). The prize page says small fixes from one month are bundled into one submission [T1: `scrollprize_prizes`].

## 3. Steps

1. Read villa `CONTRIBUTING.md`, `CLAUDE.md` and `AGENTS.md`, and follow them. Their conventions override ours inside villa.
2. `rg -n "accept_terms"` across the whole villa repo: READMEs, docs, notebooks, the scrollprize.org docs and Python. List every hit.
3. Pick the fix for each hit:
   - docs that tell users to run the command → remove, or point to the README "Data licence" section;
   - code that imports `install.accept_terms` for `get_installation_path` → leave it alone.
4. Branch `docs/remove-accept-terms-references` in the fork, one commit, with a PR description that cites the evidence and references #199.
5. **Do not open the PR.** Put the full diff and the drafted PR text in `reports/2026-11-wo004/pr-draft.md` in our repo for Kevin to review.

## 4. Acceptance criteria

- Every hit is listed and dispositioned.
- The diff is docs-only, and minimal.
- It follows villa's contribution conventions.

## 5. Out of scope

Any code change in villa; other doc fixes (list them in the report as candidates for a later WO instead).

## 6. Provenance log (executor appends below)

---
