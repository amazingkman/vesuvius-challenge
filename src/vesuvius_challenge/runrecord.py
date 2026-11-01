"""JSON run records: everything needed to reproduce and audit a run."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import platform
import shlex
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PACKAGE_DIR = Path(__file__).parent
TRACKED_PACKAGES = ("numpy", "pyarrow", "rich", "scipy", "tifffile", "typer", "vesuvius", "zarr")


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def villa_sha() -> str | None:
    """The villa commit `vesuvius` was installed from, as recorded by the installer."""
    try:
        direct_url = importlib.metadata.distribution("vesuvius").read_text("direct_url.json")
    except importlib.metadata.PackageNotFoundError:
        return None
    return json.loads(direct_url or "{}").get("vcs_info", {}).get("commit_id")


def source_sha256() -> str:
    """Hash of every Python source file in this package, in sorted path order."""
    digest = hashlib.sha256()
    for path in sorted(PACKAGE_DIR.rglob("*.py")):
        digest.update(path.relative_to(PACKAGE_DIR).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def git_commit() -> str | None:
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True, cwd=PACKAGE_DIR)
    except OSError, subprocess.CalledProcessError:
        return None
    return out.stdout.strip()


def versions() -> dict[str, str]:
    found = {"python": platform.python_version()}
    for name in TRACKED_PACKAGES:
        try:
            found[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            found[name] = "not installed"
    return found


def reproduce_command() -> str:
    """The exact `vch` invocation of this process."""
    return shlex.join(["uv", "run", "vch", *sys.argv[1:]])


@dataclass
class RunRecord:
    """One run of a `vch` stage. `partial` stays true until the stage finishes cleanly."""

    stage: str
    params: dict[str, Any]
    seed: int | None = None
    started_at: str = field(default_factory=utc_now)
    finished_at: str | None = None
    partial: bool = True
    versions: dict[str, str] = field(default_factory=versions)
    villa_sha: str | None = field(default_factory=villa_sha)
    image_digest: str | None = None
    repo_commit: str | None = field(default_factory=git_commit)
    source_sha256: str = field(default_factory=source_sha256)
    reproduce: str = field(default_factory=reproduce_command)
    results: dict[str, Any] = field(default_factory=dict)
    outputs: list[str] = field(default_factory=list)

    def finish(self, path: Path, partial: bool = False) -> Path:
        """Stamp the end time and write the record as JSON."""
        self.finished_at = utc_now()
        self.partial = partial
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2, sort_keys=True, default=str) + "\n")
        return path


def load_record(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())
