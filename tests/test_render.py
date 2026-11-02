"""The Podman wrapper's pure logic, and verify-io on synthetic volumes. No container runs here."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import tifffile
from hypothesis import given
from hypothesis import strategies as st
from scipy.ndimage import gaussian_filter

from vesuvius_challenge import render, verify
from vesuvius_challenge.render import Crop


@given(st.integers(1, 301), st.floats(0.25, 8))
def test_on_surface_layer_is_the_zero_offset_layer(num_slices: int, step: float) -> None:
    zeros = [k for k, offset in enumerate(render.layer_offsets(num_slices, step)) if offset == 0]
    assert render.on_surface_layer(num_slices) == (zeros[0] if zeros else None)


def test_known_layer_conventions() -> None:
    assert render.on_surface_layer(21) == 10
    assert render.on_surface_layer(65) == 32
    assert render.on_surface_layer(1) == 0
    assert render.on_surface_layer(28) is None
    assert render.layer_offsets(3, 2.0) == [-2.0, 0.0, 2.0]


def test_zero_slices_rejected() -> None:
    with pytest.raises(ValueError, match="at least 1"):
        render.on_surface_layer(0)


def test_crop_parse_and_tag() -> None:
    crop = Crop.parse("1,2,30,40")
    assert crop == Crop(1, 2, 30, 40)
    assert crop.tag() == "x1_y2_w30_h40"


@pytest.mark.parametrize("text", ["1,2,3", "1,2,3,4,5", "-1,0,5,5", "0,0,0,5"])
def test_bad_crops_rejected(text: str) -> None:
    with pytest.raises(ValueError, match="crop"):
        Crop.parse(text)


def test_container_path_refuses_paths_outside_the_mount(tmp_path: Path) -> None:
    root = tmp_path / "data"
    (root / "segments").mkdir(parents=True)
    assert render.container_path(root / "segments", root) == "/data/segments"
    with pytest.raises(ValueError, match="must be under"):
        render.container_path(tmp_path, root)


def build(tmp_path: Path, crop: Crop | None, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    monkeypatch.chdir(tmp_path)
    root = tmp_path / "data"
    return render.build_command(
        digest="sha256:abc",
        data_root=root,
        segment_dir=root / "segments" / "S" / "1",
        output_dir=root / "renders" / "S" / "1" / "t",
        volume_url="https://example.invalid/v.zarr",
        num_slices=21,
        slice_step=1.0,
        scale=1.0,
        group_idx=0,
        cache_gb=4,
        crop=crop,
        container_name="c",
    )


def test_command_pins_the_image_and_states_every_layer_flag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    command = build(tmp_path, Crop(1, 2, 30, 40), monkeypatch)
    assert f"{render.IMAGE}@sha256:abc" in command
    assert "--userns=keep-id" in command
    for flag, value in [("--num-slices", "21"), ("--slice-step", "1"), ("--crop-x", "1"), ("--crop-height", "40")]:
        assert command[command.index(flag) + 1] == value
    assert command[command.index("--tif-output") + 1] == "/data/renders/S/1/t/layers"


def test_full_surface_command_has_no_crop_flags(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert not any(part.startswith("--crop") for part in build(tmp_path, None, monkeypatch))


def test_recorded_mount_is_anonymous_and_expands_only_to_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    command = build(tmp_path, None, monkeypatch)
    assert command[command.index("-v") + 1] == "$PWD/data:/data"
    assert str(tmp_path) not in " ".join(command)
    assert render.expand_pwd(command)[command.index("-v") + 1] == f"{tmp_path.resolve()}/data:/data"
    assert '-v "$PWD/data:/data" ' in render.shell_command(command)


def test_data_root_outside_the_working_directory_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "work").mkdir()
    monkeypatch.chdir(tmp_path / "work")
    with pytest.raises(ValueError, match="repo root"):
        render.mount_argument(tmp_path / "data")


@pytest.mark.parametrize("line", ["  band 3/8 (37%)  0.1 bands/s", "tile-row 3/8 (37%)  1.0 chunks/s"])
def test_progress_lines_parse(line: str) -> None:
    found = render.BAND_PROGRESS.search(line)
    assert found is not None
    assert (found[1], found[2]) == ("3", "8")


def test_layer_statistics_are_true_and_hash_pixels(tmp_path: Path) -> None:
    image = np.zeros((8, 8), dtype=np.uint8)
    image[:4] = 100
    path = tmp_path / "10.tif"
    tifffile.imwrite(path, image)
    stats = render.layer_statistics(path)
    assert stats["shape"] == [8, 8]
    assert stats["dtype"] == "uint8"
    assert stats["mean"] == pytest.approx(50)
    assert stats["zero_fraction"] == pytest.approx(0.5)
    other = tmp_path / "other.tif"
    tifffile.imwrite(other, image, compression="deflate")
    assert render.layer_statistics(other)["pixel_sha256"] == stats["pixel_sha256"]
    assert render.layer_statistics(other)["file_sha256"] != stats["file_sha256"]


def test_existing_layers_stop_a_render_unless_overwritten(tmp_path: Path) -> None:
    layers = tmp_path / "layers"
    layers.mkdir()
    (layers / "00.tif").write_bytes(b"old")
    (layers / "notes.txt").write_bytes(b"keep")
    with pytest.raises(FileExistsError, match="--overwrite"):
        render.prepare_output(tmp_path, overwrite=False)
    assert (layers / "00.tif").exists()
    render.prepare_output(tmp_path, overwrite=True)
    assert not (layers / "00.tif").exists()
    assert (layers / "notes.txt").exists()


def test_empty_output_needs_no_overwrite(tmp_path: Path) -> None:
    render.prepare_output(tmp_path, overwrite=False)


def textured_stack() -> tuple[np.ndarray, np.ndarray, np.ndarray, list[np.ndarray]]:
    """A random volume, a flat surface through it, and that surface's own 'rendered' layers."""
    rng = np.random.default_rng(7)
    block = gaussian_filter(rng.normal(size=(40, 48, 48)), 1.5).astype(np.float32)
    z, y, x = 20.0, *np.mgrid[6:42, 6:42].astype(np.float32)
    points = np.stack([np.full_like(y, z), y, x], axis=-1)
    normals = np.zeros_like(points)
    normals[..., 0] = 1.0
    layers = [block[int(z) + k - 5, 6:42, 6:42] for k in range(11)]
    return block, points, normals, layers


def write_layers(layers: list[np.ndarray], folder: Path) -> list[Path]:
    paths = [folder / f"{k:02d}.tif" for k in range(len(layers))]
    for path, layer in zip(paths, layers, strict=True):
        tifffile.imwrite(path, layer)
    return paths


def test_compare_finds_alignment_and_normal_direction(tmp_path: Path) -> None:
    block, points, normals, layers = textured_stack()
    paths = write_layers(layers, tmp_path)
    result = verify.compare_with_render(block, np.zeros(3, np.float32), points, normals, paths, 5, 1, 3)
    assert result["pearson_k0"] > 0.999
    assert result["best_python_offset"] == 0
    assert result["pearson_probe_plus_normal"] > 0.999
    assert result["pearson_probe_minus_normal"] < 0.5


def test_compare_detects_a_flipped_normal(tmp_path: Path) -> None:
    block, points, normals, layers = textured_stack()
    paths = write_layers(layers, tmp_path)
    result = verify.compare_with_render(block, np.zeros(3, np.float32), points, -normals, paths, 5, 1, 3)
    assert result["pearson_probe_minus_normal"] > 0.999
    assert result["pearson_probe_plus_normal"] < 0.5


def test_block_bounds_clip_to_the_volume() -> None:
    points = np.array([[[1.0, 2.0, 3.0], [np.nan, np.nan, np.nan], [8.0, 90.0, 4.0]]])
    assert verify.block_bounds(points, (10, 100, 100), 5) == ((0, 10), (0, 96), (0, 10))


def test_pearson_ignores_nan_and_handles_flat_input() -> None:
    a = np.array([1.0, 2.0, 3.0, np.nan])
    assert verify.pearson(a, 2 * a) == pytest.approx(1.0)
    assert np.isnan(verify.pearson(np.ones(4), np.arange(4.0)))
