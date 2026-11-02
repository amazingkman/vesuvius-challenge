"""Keep machine identity out of run records and tracked files (`docs/security.md`, DR-010).

Standard library only: the pre-commit hook runs this file directly, without the project
environment. Run it as `security.py identity`, `security.py figures` or `security.py all`.
"""

from __future__ import annotations

import getpass
import re
import socket
import subprocess
import sys
import tempfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
REPO_MARK = "<repo>"

# Names that identify nobody. CI runs as `runner`, containers as `root`, and those words are
# ordinary English in this repository.
GENERIC_NAMES = {"admin", "ci", "github", "localhost", "root", "runner", "ubuntu", "user"}

# The character classes keep this file free of the literal strings it rejects, so that it
# does not need to be on the allow-list.
ABSOLUTE_PATH = re.compile(r"(?<![\w.~>:/$)\]-])/(?!data(?:[/\s\"':]|$))[\w.-]+|\b[A-Za-z]:\\|/(?:hom[e]|User[s])/")
HOME_PATH = re.compile(rb"/hom[e]/|/User[s]/|C:\\+User[s]")
PRIVATE_KEY = re.compile(rb"-----BEGIN [A-Z0-9 ]*PRIVATE KE[Y]")

# Only these exact files may name the patterns, because they define the rules.
ALLOWED_FILES = frozenset({"docs/security.md", "planning/WO-005-security-hardening.md", "tests/test_security.py"})

FIGURE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp", ".svg", ".pdf"})
FIGURE_REGISTER = "FIGURES.md"
FIGURE_CLASSES = frozenset({"synthetic", "field-map"})
FIGURE_ROW = re.compile(r"^\|\s*`([^`]+)`\s*\|\s*([^|]*?)\s*\|\s*(.*?)\s*\|\s*$")

# Passed to `savefig`. `None` removes the PNG text chunk matplotlib adds by default.
FIGURE_METADATA = {"Software": None}


class IdentityLeak(ValueError):
    """A value still holds an absolute path after sanitizing."""


def machine_identity() -> tuple[str, str]:
    """The current username and short hostname."""
    return getpass.getuser(), socket.gethostname().split(".")[0]


def _identifying(name: str) -> bool:
    return len(name) >= 3 and name.lower() not in GENERIC_NAMES


def _word(name: str) -> str:
    """A pattern for `name` as a whole word; hyphens and underscores count as word edges."""
    return rf"(?<![A-Za-z0-9]){re.escape(name)}(?![A-Za-z0-9])"


def _scrubber() -> Callable[[str], str]:
    """Build the replacement for one string. Longer paths go first: the repo is under home."""
    home = str(Path.home())
    user, host = machine_identity()
    prefixes = [
        (str(REPO_ROOT), REPO_MARK),
        (str(Path(tempfile.gettempdir()).resolve()), "<tmp>"),
        (tempfile.gettempdir(), "<tmp>"),
        (home, "~"),
    ]
    words = [
        (re.compile(_word(name), re.IGNORECASE), mark)
        for name, mark in ((user, "<user>"), (host, "<host>"))
        if _identifying(name)
    ]

    def scrub(text: str) -> str:
        for prefix, mark in prefixes:
            if prefix not in ("", "/"):
                text = text.replace(prefix, mark)
        for pattern, mark in words:
            text = pattern.sub(mark, text)
        if found := ABSOLUTE_PATH.search(text):
            raise IdentityLeak(f"absolute path remains after sanitizing: {text[max(found.start() - 20, 0) :][:80]!r}")
        return text

    return scrub


def _walk(value: Any, scrub: Callable[[str], str]) -> Any:
    if isinstance(value, dict):
        return {_walk(key, scrub): _walk(item, scrub) for key, item in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [_walk(item, scrub) for item in value]
    if isinstance(value, Path):
        return scrub(str(value))
    if isinstance(value, str):
        return scrub(value)
    return value


def sanitize(record: Any) -> Any:
    """Return `record` with the repo root, home, username and hostname replaced.

    Applied to every record before writing. Raises `IdentityLeak` if an absolute path
    remains. Paths inside the container, under `/data`, are not on this machine and stay.
    """
    return _walk(record, _scrubber())


def repo_path(path: Path | str) -> str:
    """The `<repo>/...` form of a path, which is how run records store paths."""
    resolved = Path(path).resolve()
    if resolved.is_relative_to(REPO_ROOT):
        return f"{REPO_MARK}/{resolved.relative_to(REPO_ROOT).as_posix()}"
    return str(resolved)


def from_repo_path(text: str) -> Path:
    """Turn a recorded path back into a real one; plain relative paths pass through."""
    prefix = f"{REPO_MARK}/"
    return REPO_ROOT / text.removeprefix(prefix) if text.startswith(prefix) else Path(text)


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    rule: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.rule}"


def tracked_files(root: Path) -> list[str]:
    """Every path in the git index, which includes files staged for the next commit."""
    listing = subprocess.run(["git", "ls-files", "-z"], capture_output=True, check=True, cwd=root).stdout
    return [name for name in listing.decode().split("\0") if name]


def identity_rules(user: str, host: str) -> list[tuple[str, re.Pattern[bytes]]]:
    rules = [("absolute home path", HOME_PATH), ("private key header", PRIVATE_KEY)]
    for label, name in (("username", user), ("hostname", host)):
        if _identifying(name):
            rules.append((label, re.compile(_word(name).encode(), re.IGNORECASE)))
    return rules


def scan_bytes(path: str, data: bytes, rules: Iterable[tuple[str, re.Pattern[bytes]]]) -> list[Finding]:
    """One finding per match. The matched text is not reported, so logs do not repeat a leak."""
    return [
        Finding(path, data.count(b"\n", 0, match.start()) + 1, rule)
        for rule, pattern in rules
        for match in pattern.finditer(data)
    ]


def scan_identity(root: Path, identity: tuple[str, str] | None = None) -> list[Finding]:
    """Check the name and contents of every tracked file, apart from `ALLOWED_FILES`."""
    rules = identity_rules(*(identity or machine_identity()))
    findings: list[Finding] = []
    for name in tracked_files(root):
        if name in ALLOWED_FILES:
            continue
        findings += [Finding(name, 0, f"{rule} in file name") for rule, _ in _name_hits(name, rules)]
        path = root / name
        if path.is_file():
            findings += scan_bytes(name, path.read_bytes(), rules)
    return findings


def _name_hits(name: str, rules: Iterable[tuple[str, re.Pattern[bytes]]]) -> list[tuple[str, re.Pattern[bytes]]]:
    return [(rule, pattern) for rule, pattern in rules if pattern.search(name.encode())]


def parse_figure_register(text: str) -> dict[str, tuple[str, str]]:
    """Map each `FIGURES.md` table row's path to its provenance class and command."""
    return {row[1]: (row[2], row[3]) for line in text.splitlines() if (row := FIGURE_ROW.match(line))}


def scan_figures(root: Path) -> list[Finding]:
    """Every tracked image must be registered, as synthetic or field-map, with its command."""
    register_path = root / FIGURE_REGISTER
    register = parse_figure_register(register_path.read_text()) if register_path.exists() else {}
    names = tracked_files(root)
    findings = [
        Finding(name, 0, f"image not listed in {FIGURE_REGISTER}")
        for name in names
        if Path(name).suffix.lower() in FIGURE_SUFFIXES and name not in register
    ]
    for name, (provenance, command) in register.items():
        if provenance not in FIGURE_CLASSES:
            findings.append(Finding(name, 0, f"provenance {provenance!r} is not allowed"))
        if not command:
            findings.append(Finding(name, 0, "no generating command"))
        if name not in names:
            findings.append(Finding(name, 0, f"listed in {FIGURE_REGISTER} but not tracked"))
    return findings


def main(argv: list[str]) -> int:
    checks = {"identity": scan_identity, "figures": scan_figures}
    mode = argv[0] if argv else "all"
    if mode not in (*checks, "all"):
        print(f"usage: security.py [{' | '.join(checks)} | all]", file=sys.stderr)
        return 2
    findings = [item for name, check in checks.items() if mode in (name, "all") for item in check(REPO_ROOT)]
    for finding in findings:
        print(finding)
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
