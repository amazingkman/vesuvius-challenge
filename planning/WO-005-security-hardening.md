# WO-005 — Security hardening: anonymous run records, secret/identity scanning, CI hardening

Executor: **Cloud** (repo config and code; no data needed)  Depends on: WO-002 merged (avoid conflicts in `runrecord.py` / `render.py`)  Status: issued 2026-11-01. **Must merge before WO-003 starts**, because WO-003 writes many run records.

## 1. Objective

Make it mechanically impossible to commit secrets, machine identity or render-derived images, and harden CI against supply-chain abuse, following `docs/security.md` (DR-010).

## 2. Background

`docs/security.md` sets out the threat model, rules R1–R5 and the 2026-11-01 audit. That audit found no secrets, but did find an absolute home path (with the username) in WO-001 run records, written by `vch render` when recording the Podman command, and the workstation hostname in docs. Both are scrubbed in the tree; this WO stops them recurring.

## 3. Deliverables

1. **Anonymous run records** (`runrecord.py`, `render.py`, and any other writer):
   - All recorded paths are relative to the repo root, prefixed `<repo>/`.
   - Recorded Podman commands use `-v "$PWD/data:/data"`, and run from the repo root.
   - A single `sanitize()` is applied to every record before writing. It replaces the repo root with `<repo>`, `$HOME` with `~`, and the current username and hostname (from `getpass.getuser()` and `socket.gethostname()`) with `<user>` and `<host>`, then raises if any absolute path pattern remains.
   - The recorded `command_shell` must still reproduce the run when executed from the repo root. Update the WO-001 reproduction instructions accordingly.
2. **Tests** (`tests/test_security.py`):
   - Hypothesis-generated records containing home paths, usernames and hostnames come out clean.
   - A real `vch render --dry-run` record (no Podman needed) contains no username, hostname or absolute path.
   - A repo-wide scan test fails on any tracked file containing `/home/`, `/Users/`, `C:\\Users`, the current username or hostname, or a private-key header.
     The scan allow-lists **by exact file path only** the files that must name these patterns in order to define the rules: `docs/security.md`, this WO and the scanner's own test fixtures. Any other occurrence fails.
3. **Pre-commit** (`.pre-commit-config.yaml`, hooks pinned by tag and SHA):
   - gitleaks;
   - `detect-private-key`, `check-added-large-files` (500 kB), `check-merge-conflict`;
   - a local hook running the identity/path scan from item 2;
   - a local hook rejecting `*.png|jpg|jpeg|tif|tiff|bmp|webp` outside `docs/assets/`.
   Document `uv run pre-commit install` in the README.
4. **CI** (`.github/workflows/ci.yml`, extending WO-002's):
   - `permissions: contents: read`;
   - every action pinned by full commit SHA;
   - `pull_request` only, never `pull_request_target`;
   - jobs: gitleaks over full history (`fetch-depth: 0`), the identity/path scan, a `uv` dependency vulnerability audit (`pip-audit` against the exported lockfile), ruff, pytest.
   - No secrets referenced anywhere.
5. **`.gitignore` additions:** `.env*`, `*.pem`, `*.key`, `id_*`, `*.p12`, `.netrc`, `.aws/`, `.ssh/`, `secrets*`, `*.token`.
6. **`SECURITY.md`** at the repo root: how to report a vulnerability privately (GitHub private vulnerability reporting), pointing to `docs/security.md`.
7. **`.github/dependabot.yml`:** weekly updates for GitHub Actions. pip updates are disabled, because the villa pin and `uv.lock` are bumped only through WOs (DR-004). Dependabot *alerts* stay on.
8. README ("Security" section) and CHANGELOG.

## 4. Acceptance criteria

- Pre-commit and CI both fail on a planted test file containing a fake private-key header, an absolute home path or a `.png` outside `docs/assets/`. Show this in the PR with a throwaway commit that is then reverted.
- gitleaks over full history is clean. The known history items (username path, hostname) are allow-listed **by commit SHA**, with a comment pointing to the `docs/security.md` audit log; no wildcards.
- All tests green. No new runtime dependencies in the package; dev-only additions are pre-commit and pip-audit.

## 5. Out of scope

- History rewriting (the owner's decision, DR-010).
- GitHub settings changes: Kevin does those; list them in the PR description as a checklist.

## 6. Provenance log (executor appends below)

---
