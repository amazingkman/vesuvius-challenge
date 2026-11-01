# Security and privacy policy for this public repository

The repository is public on purpose, so researchers can use it (DR-007). Nothing in it may help anyone reach, identify or attack the owner's machine or accounts. This policy is binding on every agent and every PR (DR-010).

## Threat model: how a public research repo can actually hurt you

1. **Leaked credentials.** API tokens, SSH or GPG private keys, cloud keys, `.env` files, `.netrc`, Hugging Face or GitHub tokens. *This is the only direct route from a repo to account or machine compromise.*
2. **Supply chain.** Untrusted code runs on the workstation: a malicious PR, a compromised dependency, a hijacked git dependency, or a CI workflow that runs fork code with secrets.
3. **Reconnaissance.** Usernames, hostnames, home paths, internal IPs, OS and hardware details, emails. None of these grants access by itself, but they make phishing, credential-stuffing and targeted attacks easier. Low severity, cheap to prevent.
4. **Data-terms leakage.** Scroll renders or Discord material (`docs/data-licensing.md`). This is a separate obligation, enforced by the same scanning.

## Rules (binding on every PR)

- **R1. No secrets, ever.** No tokens, keys, passwords or credential files. `.env`, `*.pem`, `id_*`, `*.key`, `.netrc`, `.aws/`, `.ssh/` and similar are gitignored. Code reads credentials from the environment only, and we use none at present: all data access is anonymous.
- **R2. No machine identity.**
  - No absolute paths (`/home/…`, `/Users/…`, `C:\…`), usernames, hostnames, machine nicknames, IPs (other than `127.0.0.1` in tests), MAC addresses, or serial numbers.
  - **Run records** store paths relative to the repo root (`<repo>/data/...`). The Podman mount in recorded commands is written `$PWD/data:/data`, which is reproducible and anonymous.
  - Hardware is described generically: "single workstation, 24 GB GPU".
- **R3. No render-derived images** in the repo or PRs (DR-008). Pre-commit and CI block image formats outside `docs/assets/` (which holds synthetic figures only).
- **R4. Supply chain.**
  - Dependencies are locked with hashes (`uv.lock`); the villa git dependency is pinned to a commit.
  - CI actions are pinned by commit SHA; workflows use `permissions: contents: read`, have no secrets, and never use `pull_request_target`.
  - Code from PRs by anyone other than Kevin or our agents is never run on the workstation before review.
- **R5. Contact identity.** The owner's email is public **by choice**, so researchers can reach him. That makes it a known phishing target: 2FA is on for every account (confirmed by the owner 2026-11-01), and no other personal identifiers are published.

## Enforcement

- **Pre-commit hooks** (WO-005): gitleaks; `detect-private-key`; a local identity/path scan (R2); an image-file block (R3); large-file check.
- **CI**, on every PR and on `master`: gitleaks over full history, the same identity/path scan, a dependency vulnerability audit, ruff and pytest.
- **GitHub settings** (Kevin): secret scanning and push protection on; Dependabot alerts on; branch protection on `master` (PRs required, CI must pass, no force-push); 2FA on the account; the Cloud GitHub App limited to this repository only.
- **Planner review:** every report PR is spot-checked against this file before merge.

## Audit log

### 2026-11-01 — first full audit (Planner)

**Scope:** every file in every commit on every branch, 82 distinct paths, including the deleted docs tarball.

**Tools:** detect-secrets (all files), regex scans for private-key headers and GitHub/AWS/OpenAI/Hugging Face/Slack token formats, and identity scans (absolute paths, username, hostname, IPs, emails).

**Results:**
- **Secrets: none.** All high-entropy hits were SHA-256 checksums, ETags, git commit SHAs and image digests.
- **Home path with username:** `/home/<user>/vesuvius-challenge` in five WO-001 run-record files (commit `7f6635f`). **Scrubbed from the current tree** (replaced with `<repo>`). It remains in git history and in GitHub's immutable `refs/pull/1/head` (see below).
- **Workstation hostname:** in three docs. Scrubbed from the current tree; remains in history.
- **Owner email:** in `pyproject.toml` `authors` and in commit metadata. Public by the owner's choice (R5).
- **`127.0.0.1`:** test fixture only. Fine.

**On history:** a username and hostname are reconnaissance-grade (threat 3), not access. Rewriting history (`git filter-repo --replace-text`, then a force-push) would remove them from branches. But GitHub keeps PR refs (`refs/pull/1/head`) and cached views, which only GitHub Support can purge, and any existing clone keeps them. **Decision (DR-010): fix forward and harden; history rewrite is optional and the owner's call.**
