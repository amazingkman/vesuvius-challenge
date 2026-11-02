# WO-005 — Security hardening: anonymous run records, secret/identity scanning, CI hardening

Executor: **VSCode** (repo config and code; no data needed)  Depends on: WO-002 merged (avoid conflicts in `runrecord.py` / `render.py`)  Status: issued 2026-11-01. **Must merge before WO-003 starts**, because WO-003 writes many run records.

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
   - a local hook that rejects any `*.png|jpg|jpeg|tif|tiff|bmp|webp|svg|pdf` **not listed in `FIGURES.md`** at the repo root.
     - Each entry gives the path, the provenance class (`synthetic` or `field-map`; render-derived is never allowed) and the generating command.
     - Seed `FIGURES.md` with the seven WO-002 synthetic figures in `reports/2026-11-wo002/generated/`.
     - Also strip non-essential image metadata (the PNG text chunks) in the figure writer.
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

**Executor:** Claude Code (VSCode role) on a single workstation, 2026-11-01 to 2026-11-02 (UTC). Branch `wo-005-security-hardening`, PR #4. The WO's executor line was changed from Cloud to VSCode by Kevin, and that edit is committed here.

### Versions

| Item | Value |
|---|---|
| Villa pin | `d57c28ebee8776b618f9851c2289cc407ea99dd4`, unchanged |
| Image | `sha256:b2509de2c107852799a5077fd2038a917549a1d1e3665d5a1919c955858d698a` |
| gitleaks | 8.30.1; CI verifies tarball SHA-256 `551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb` |
| pre-commit-hooks | v6.0.0, `3e8a8703264a2f4a69428a0aa4dcb512790b2c8c` |
| Actions | `actions/checkout` v7.0.1 `3d3c42e5aac5ba805825da76410c181273ba90b1`; `astral-sh/setup-uv` v10.3.3 `68559e99cc807c1eb7e9238fd43a15bba460eec2` |
| Dev dependencies added | `pre-commit` 4.7.0, `pip-audit` 2.10.1. No runtime dependency added; the lock diff only adds packages |

Tags were resolved to commit SHAs through the GitHub API, including dereferencing annotated tags.

### Commands

```bash
uv add --dev pre-commit pip-audit
uv run pre-commit install
uv run pre-commit run --all-files
uv run pytest -q; uv run ruff check; uv run ruff format --check; uv run vch selftest; uv run vch scan
gitleaks git . --redact --no-banner --config .gitleaks.toml --log-opts="--all"
uv export --frozen --no-emit-project --no-emit-package vesuvius --format requirements-txt -o audit-requirements.txt
uv run --locked --only-dev pip-audit --strict --disable-pip --require-hashes -r audit-requirements.txt
```

### Acceptance results

| Criterion | Result |
|---|---|
| Pre-commit fails on the planted files | Yes. A plain `git commit` was refused: gitleaks, `detect-private-key`, identity scan and figure register all failed |
| CI fails on the planted files | Yes. Run 41373757272 on commit `0415699`: `gitleaks`, `identity-scan` and `test` failed, each planted file named. PR #4 went to `BLOCKED` |
| Planted commit reverted | Yes, `db8d3c4` |
| gitleaks over full history clean | Yes. With the commit allow-list removed, the 9 known hits in `7f6635f` return, so the rule works |
| Allow-listing | By full commit SHA, no wildcards, no global exemption |
| Tests | Green: 201 passed, locally and in CI, plus `vch selftest` |
| No new runtime dependencies | Yes |
| Recorded `command_shell` reproduces a render | Yes. From the repo root, with the first render moved aside, it wrote 21 new layers in 55.9 s, and all 21 pixel hashes match. Podman and local data were used for this check |
| `pip-audit` | No known vulnerabilities in the lockfile |

The planted files were a fake key header, a home path for a made-up user, and a 1×1 PNG. Hooks were skipped with `--no-verify` for that one commit, on purpose, to reach CI.

### Surprises

1. **gitleaks' default allow-list drops whole-path matches.** A plain home-path rule found nothing in a history that holds 9 known hits. The rule needs `secretGroup`, so that only the username part is tested against the allow-list.
2. **`vch selftest` crashed in CI, and I had not caught it.** It stored rich colour tags, and `sanitize()` read a closing tag as an absolute path. I had run pytest locally but not the selftest. Fixed in `2dbc72b` by storing plain text, with an end-to-end test added. The check itself was left strict.
3. **My CI monitor reported nothing when CI failed,** so Kevin asked before I knew. It was replaced by `gh pr checks --watch`.
4. **The first GitHub ruleset blocked pushes to work branches.** Kevin narrowed it to `master`. Pushes to this branch then worked, and the PR went to `BLOCKED` while CI was red. A direct push to `master` was not tested.
5. **Hostname is not covered by a gitleaks rule.** A rule would have to publish the name. `a70cd87` is listed for the record as the WO asks, but no rule can match it. The identity scan covers the current hostname in the tree.

### Decisions to check

- **Figures rule.** Deliverable 3 says any image not in `FIGURES.md`. The acceptance text and `docs/security.md` R3 and Enforcement say outside `docs/assets/`. I followed deliverable 3, which is stricter: an image in `docs/assets/` must be registered too. `docs/security.md` needs updating to match. I did not edit it.
- **`<tmp>`.** `sanitize()` also replaces the system temp directory, which the WO does not list. Without it, a run writing under temp would raise.
- **`/data`.** Container paths under `/data` pass the absolute-path check, because the recorded command needs them and they are not on this machine.
- **Generic names.** `runner`, `root` and similar are not treated as identity, so CI is not flooded by ordinary words. The path and key checks still run in CI, but the username and hostname checks only have effect on the workstation.
- **`vch scan`** is an addition, so that the scan meets the UX floor. The hooks and CI call `security.py` directly, which needs only the standard library.
- **CI triggers.** `push` to `master` was kept alongside `pull_request`, because `docs/security.md` requires CI on `master`.
- **Existing records.** Five WO-001 records were edited from `<repo>/data:/data` to `$PWD/data:/data`, so that their recorded commands run. Nothing else in them changed.
- **Existing figures.** The seven WO-002 PNGs keep matplotlib's `Software` chunk. Only the figure writers changed, and those chunks hold a version number, not identity.

### Limits

- `pip-audit` cannot look up `vesuvius` itself, a git dependency pinned by commit. Its dependencies are audited.
- CI's gitleaks scans the history of the commit under test, not every branch.
- `docs/security.md` R5 says the owner's email is public by choice, while DR-010 lists a private commit email. Commits here use the configured git identity. For the Planner and Kevin to reconcile.

