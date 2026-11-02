"""Identity is kept out of records and tracked files. Secret-like strings here are fixtures."""

from __future__ import annotations

import json
import shutil
import struct
import subprocess
from pathlib import Path

import numpy as np
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from typer.testing import CliRunner

from vesuvius_challenge import cli, render, security, verify
from vesuvius_challenge.runrecord import RunRecord
from vesuvius_challenge.security import IdentityLeak, repo_path, sanitize

REPO = Path(__file__).parent.parent
USER = "alice-smith"
HOST = "workbench7"
KEY_HEADER = "-----BEGIN " + "RSA PRIVATE KEY-----"


@pytest.fixture
def identity(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """A made-up user on a made-up machine, with the repo under its home."""
    home = tmp_path / "home" / USER
    repo = home / "work" / "repo"
    repo.mkdir(parents=True)
    monkeypatch.setattr(security, "machine_identity", lambda: (USER, HOST))
    monkeypatch.setattr(security, "REPO_ROOT", repo)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr(security.tempfile, "gettempdir", lambda: "/nonexistent-tmp")
    return repo


def test_repo_root_home_user_and_host_are_replaced(identity: Path) -> None:
    home = str(identity.parents[1])
    record = {
        "repo": f"{identity}/data/x",
        "home": f"{home}/notes.txt",
        "who": f"{USER} on {HOST}",
        f"{identity}/key": ["cwd", (f"{home}/y",)],
    }
    assert sanitize(record) == {
        "repo": "<repo>/data/x",
        "home": "~/notes.txt",
        "who": "<user> on <host>",
        "<repo>/key": ["cwd", ["~/y"]],
    }


def test_identity_matches_any_case_and_inside_hyphenated_names(identity: Path) -> None:
    assert sanitize("pytest-of-ALICE-SMITH and WORKBENCH7.local") == "pytest-of-<user> and <host>.local"


def test_generic_names_are_left_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(security, "machine_identity", lambda: ("runner", "root"))
    assert sanitize("the test runner uses data_root") == "the test runner uses data_root"


@pytest.mark.parametrize(
    "leak",
    [
        "/etc/passwd",
        "see /var/log/x",
        "--out=/mnt/disk/run",
        "C:\\Users\\me",
        "D:\\temp",
        "file:///home/x/y",
        "/Users/x",
    ],
)
def test_any_other_absolute_path_raises(identity: Path, leak: str) -> None:
    with pytest.raises(IdentityLeak):
        sanitize({"nested": [leak]})


@pytest.mark.parametrize(
    "fine",
    [
        "/data/segments/S/1",
        "/data",
        "$PWD/data:/data",
        "<repo>/data/x",
        "~/src/villa",
        "https://example.invalid/a/b.zarr",
        "s3://bucket/a/b",
        "ghcr.io/scrollprize/villa/volume-cartographer@sha256:abc",
        "data/renders/S/1/layers/10.tif",
        "band 3/8 (37%)",
        'podman run -v "$PWD/data:/data" img --tif-output /data/renders/x/layers',
    ],
)
def test_ordinary_values_pass_unchanged(identity: Path, fine: str) -> None:
    assert sanitize(fine) == fine


names = st.text("abcdefghij0123456789_-", min_size=1, max_size=10)
paths = st.lists(names, min_size=1, max_size=4).map("/".join)


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(paths, paths, names)
def test_generated_records_come_out_clean(identity: Path, under_repo: str, under_home: str, noise: str) -> None:
    home = str(identity.parents[1])
    record = {
        "outputs": [f"{identity}/{under_repo}", f"{home}/{under_home}"],
        "note": f"{noise} ran as {USER} on {HOST}",
        "numbers": [1, 2.5, None, True],
    }
    clean = sanitize(record)
    text = json.dumps(clean)
    assert home not in text
    assert USER not in text
    assert HOST not in text
    assert clean["numbers"] == record["numbers"]
    assert sanitize(clean) == clean


def test_finish_scrubs_everything_including_non_json_values(identity: Path, tmp_path: Path) -> None:
    class Odd:
        def __str__(self) -> str:
            return f"{identity}/odd"

    record = RunRecord("t", {"a": 1})
    record.results = {"odd": Odd(), "path": identity / "data", "who": USER}
    path = record.finish(tmp_path / "r.json")
    text = path.read_text()
    assert str(identity) not in text and USER not in text
    assert json.loads(text)["results"] == {"odd": "<repo>/odd", "path": "<repo>/data", "who": "<user>"}


def test_unsafe_settings_fail_before_any_work(identity: Path) -> None:
    with pytest.raises(IdentityLeak):
        RunRecord("t", {"out": "/mnt/disk/run"})


def test_repo_path_round_trip(identity: Path) -> None:
    recorded = repo_path(identity / "data" / "segments")
    assert recorded == "<repo>/data/segments"
    assert security.from_repo_path(recorded) == identity / "data" / "segments"
    assert security.from_repo_path("data/old-style") == Path("data/old-style")


def test_dry_run_record_is_anonymous(identity: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A real `vch render --dry-run` through the CLI. Podman is not needed."""
    segment = identity / "data" / "segments" / "S" / "1"
    segment.mkdir(parents=True)
    manifest = {"sample": "S", "segment": "1", "volume_url": "https://example.invalid/v.zarr"}
    (segment / "MANIFEST.json").write_text(json.dumps(manifest))
    monkeypatch.chdir(identity)
    monkeypatch.setattr(render, "image_digest", lambda: (_ for _ in ()).throw(FileNotFoundError("podman")))
    arguments = ["render", "data/segments/S/1", "-n", "21", "-s", "1", "--crop", "0,0,8,8", "--dry-run"]
    result = CliRunner().invoke(cli.app, arguments)
    assert result.exit_code == 0, result.output

    path = identity / "data" / "renders" / "S" / "1" / "n21_s1_x0_y0_w8_h8" / "render.dry-run.run.json"
    text = path.read_text()
    saved = json.loads(text)
    assert USER not in text and HOST not in text and str(identity.parent) not in text
    assert saved["params"]["segment_dir"] == "<repo>/data/segments/S/1"
    assert '-v "$PWD/data:/data"' in saved["results"]["command_shell"]
    assert saved["results"]["command"][saved["results"]["command"].index("-v") + 1] == "$PWD/data:/data"
    assert saved["results"]["on_surface_layer"] == 10
    assert saved["partial"] is True


def test_a_real_run_refuses_without_a_digest(identity: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    segment = identity / "data" / "segments" / "S" / "1"
    segment.mkdir(parents=True)
    (segment / "MANIFEST.json").write_text('{"sample": "S", "segment": "1", "volume_url": "https://e.invalid/v"}')
    monkeypatch.chdir(identity)
    monkeypatch.setattr(render, "image_digest", lambda: (_ for _ in ()).throw(FileNotFoundError("podman")))
    result = CliRunner().invoke(cli.app, ["render", "data/segments/S/1", "-n", "3", "-s", "1"])
    assert result.exit_code != 0


def test_tracked_files_pass_both_scans() -> None:
    assert [str(finding) for finding in security.scan_identity(REPO)] == []
    assert [str(finding) for finding in security.scan_figures(REPO)] == []


def git(root: Path, *arguments: str) -> None:
    subprocess.run(["git", *arguments], cwd=root, check=True, capture_output=True)


def repository(tmp_path: Path, files: dict[str, str]) -> Path:
    root = tmp_path / "planted"
    root.mkdir()
    git(root, "init", "-q")
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    git(root, "add", "--all", "--force")
    return root


@pytest.mark.parametrize(
    ("content", "rule"),
    [
        ("mount /home/someone/data here", "absolute home path"),
        ("mount /Users/someone/data here", "absolute home path"),
        ("mount C:\\Users\\someone\\data here", "absolute home path"),
        ("mount C:\\\\Users\\\\someone in JSON", "absolute home path"),
        (KEY_HEADER, "private key header"),
        (f"logged in as {USER.upper()}", "username"),
        (f"built on {HOST}", "hostname"),
    ],
)
def test_scan_finds_each_planted_pattern(tmp_path: Path, content: str, rule: str) -> None:
    root = repository(tmp_path, {"docs/note.md": f"first line\n{content}\n"})
    assert [str(f) for f in security.scan_identity(root, (USER, HOST))] == [f"docs/note.md:2: {rule}"]


def test_scan_reports_where_but_never_the_matched_text(tmp_path: Path) -> None:
    root = repository(tmp_path, {"a.md": f"{USER}\n"})
    assert USER not in " ".join(str(f) for f in security.scan_identity(root, (USER, HOST)))


def test_scan_checks_file_names(tmp_path: Path) -> None:
    root = repository(tmp_path, {f"logs/{USER}.txt": "clean\n"})
    assert [f.rule for f in security.scan_identity(root, (USER, HOST))] == ["username in file name"]


def test_allow_list_is_by_exact_path_only(tmp_path: Path) -> None:
    leak = "/home/someone/x\n"
    root = repository(
        tmp_path,
        {
            "docs/security.md": leak,
            "planning/WO-005-security-hardening.md": leak,
            "tests/test_security.py": leak,
            "other/docs/security.md": leak,
            "docs/security.md.bak": leak,
            "tests/test_security_extra.py": leak,
        },
    )
    assert sorted(f.path for f in security.scan_identity(root, (USER, HOST))) == [
        "docs/security.md.bak",
        "other/docs/security.md",
        "tests/test_security_extra.py",
    ]


def test_generic_identity_is_not_searched(tmp_path: Path) -> None:
    root = repository(tmp_path, {"a.md": "the runner is root on localhost\n"})
    assert security.scan_identity(root, ("runner", "localhost")) == []


REGISTER_HEAD = "| Path | Provenance | Generating command |\n|---|---|---|\n"


@pytest.mark.parametrize("suffix", sorted(security.FIGURE_SUFFIXES))
def test_unregistered_image_of_every_format_is_rejected(tmp_path: Path, suffix: str) -> None:
    root = repository(tmp_path, {f"docs/assets/a{suffix}": "x", "FIGURES.md": REGISTER_HEAD})
    assert [f.path for f in security.scan_figures(root)] == [f"docs/assets/a{suffix}"]


def test_image_suffix_case_does_not_matter(tmp_path: Path) -> None:
    root = repository(tmp_path, {"a.PNG": "x", "FIGURES.md": REGISTER_HEAD})
    assert [f.path for f in security.scan_figures(root)] == ["a.PNG"]


def test_registered_image_passes(tmp_path: Path) -> None:
    register = REGISTER_HEAD + "| `figs/a.png` | synthetic | `uv run vch synth report x` |\n"
    root = repository(tmp_path, {"figs/a.png": "x", "FIGURES.md": register})
    assert security.scan_figures(root) == []


def test_missing_register_rejects_every_image(tmp_path: Path) -> None:
    assert [f.path for f in security.scan_figures(repository(tmp_path, {"a.png": "x"}))] == ["a.png"]


@pytest.mark.parametrize("provenance", ["render-derived", "render", "", "Synthetic"])
def test_only_the_allowed_classes_register(tmp_path: Path, provenance: str) -> None:
    register = REGISTER_HEAD + f"| `a.png` | {provenance} | `cmd` |\n"
    root = repository(tmp_path, {"a.png": "x", "FIGURES.md": register})
    assert any("is not allowed" in f.rule for f in security.scan_figures(root))


def test_entry_needs_a_command(tmp_path: Path) -> None:
    root = repository(tmp_path, {"a.png": "x", "FIGURES.md": REGISTER_HEAD + "| `a.png` | synthetic |  |\n"})
    assert [f.rule for f in security.scan_figures(root)] == ["no generating command"]


def test_stale_register_entry_is_reported(tmp_path: Path) -> None:
    root = repository(tmp_path, {"FIGURES.md": REGISTER_HEAD + "| `gone.png` | synthetic | `cmd` |\n"})
    assert [f.rule for f in security.scan_figures(root)] == ["listed in FIGURES.md but not tracked"]


def png_chunks(path: Path) -> list[bytes]:
    data = path.read_bytes()
    chunks, position = [], 8
    while position < len(data):
        length, kind = struct.unpack(">I4s", data[position : position + 8])
        chunks.append(kind)
        position += 12 + length
    return chunks


def test_figure_writer_strips_png_text_chunks(tmp_path: Path) -> None:
    layers = []
    for k in range(3):
        path = tmp_path / f"{k:02d}.tif"
        verify.tifffile.imwrite(path, np.full((8, 8), k * 40, np.uint8))
        layers.append(path)
    figure = verify.save_layer_figure(layers, 1, tmp_path / "figure.png")
    chunks = png_chunks(figure)
    assert b"IDAT" in chunks
    assert not {b"tEXt", b"iTXt", b"zTXt", b"tIME"} & set(chunks)


def test_hook_entry_runs_without_the_project_environment() -> None:
    """The pre-commit hook runs this file directly, so it must import only the standard library."""
    python = shutil.which("python3")
    assert python
    done = subprocess.run(
        [python, "-I", str(REPO / "src/vesuvius_challenge/security.py"), "nonsense"], capture_output=True
    )
    assert done.returncode == 2, done.stderr


@pytest.mark.parametrize(
    "line",
    [
        ".env.local",
        "server.pem",
        "deploy.key",
        "id_ed25519",
        "cert.p12",
        ".netrc",
        ".aws/x",
        ".ssh/x",
        "secrets.toml",
        "a.token",
    ],
)
def test_credential_files_are_ignored(line: str) -> None:
    assert subprocess.run(["git", "check-ignore", "-q", line], cwd=REPO).returncode == 0
