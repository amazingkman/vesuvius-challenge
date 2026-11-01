"""Run records, the CLI surface, and repository guarantees."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from vesuvius_challenge import cli, selftest
from vesuvius_challenge.runrecord import RunRecord, source_sha256, villa_sha

REPO = Path(__file__).parent.parent
PIN = "d57c28ebee8776b618f9851c2289cc407ea99dd4"


@pytest.mark.parametrize("command", ["survey", "fetch", "render", "verify-io", "selftest", "synth"])
def test_every_stage_has_help(command: str) -> None:
    assert CliRunner().invoke(cli.app, [command, "--help"]).exit_code == 0


@pytest.mark.parametrize(("name", "check"), selftest.CHECKS)
def test_selftest_checks_pass(name: str, check) -> None:
    check()


def test_record_stays_partial_until_finished(tmp_path: Path) -> None:
    record = RunRecord("t", {"a": 1})
    assert record.partial
    path = record.finish(tmp_path / "sub" / "run.json")
    saved = json.loads(path.read_text())
    assert saved["partial"] is False
    assert saved["params"] == {"a": 1}
    assert saved["finished_at"] is not None


def test_interrupted_record_is_marked_partial(tmp_path: Path) -> None:
    saved = json.loads(RunRecord("t", {}).finish(tmp_path / "r.json", partial=True).read_text())
    assert saved["partial"] is True


def test_record_holds_the_provenance_claude_md_requires(tmp_path: Path) -> None:
    saved = json.loads(RunRecord("t", {}).finish(tmp_path / "r.json").read_text())
    for key in ("seed", "started_at", "finished_at", "versions", "villa_sha", "image_digest", "source_sha256"):
        assert key in saved
    assert saved["versions"]["python"].startswith("3.14")


def test_installed_vesuvius_is_the_pinned_commit() -> None:
    assert villa_sha() == PIN


def test_source_hash_is_stable() -> None:
    assert source_sha256() == source_sha256()


def test_no_data_under_git() -> None:
    tracked = subprocess.run(["git", "ls-files", "data/"], capture_output=True, text=True, cwd=REPO, check=True)
    assert tracked.stdout == ""


@pytest.mark.parametrize("path", ["data/x", "a.tif", "b.tiff", "c.obj", "d.ppm", "e.zarr/0/0"])
def test_scroll_data_patterns_stay_ignored(path: str) -> None:
    assert subprocess.run(["git", "check-ignore", "-q", path], cwd=REPO).returncode == 0
