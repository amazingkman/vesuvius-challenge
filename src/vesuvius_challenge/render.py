"""Podman wrapper around VC3D's `vc_render_tifxyz`. The GPL binary runs as a subprocess only."""

from __future__ import annotations

import hashlib
import os
import re
import shlex
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import tifffile

IMAGE = "ghcr.io/scrollprize/villa/volume-cartographer"
IMAGE_TAG = "edge"
BAND_PROGRESS = re.compile(r"(?:band|tile-row) (\d+)/(\d+)")


@dataclass(frozen=True)
class Crop:
    """A rectangle in output pixels of the flattened surface, as `vc_render_tifxyz` takes it."""

    x: int
    y: int
    width: int
    height: int

    @classmethod
    def parse(cls, text: str) -> Crop:
        """Parse `x,y,width,height`."""
        parts = text.split(",")
        if len(parts) != 4:
            raise ValueError(f"--crop needs x,y,width,height, got {text!r}")
        crop = cls(*(int(part) for part in parts))
        if crop.x < 0 or crop.y < 0 or crop.width <= 0 or crop.height <= 0:
            raise ValueError(f"--crop needs x,y >= 0 and width,height > 0, got {text!r}")
        return crop

    def tag(self) -> str:
        return f"x{self.x}_y{self.y}_w{self.width}_h{self.height}"


def on_surface_layer(num_slices: int) -> int | None:
    """Index of the layer with zero offset along the normal; None if no layer has it.

    `buildOffsetList` in `vc_render_tifxyz.cpp` places layer `k` at `(k - c) * step` with
    `c = (N - 1) / 2`. For even N the centre falls between two layers.
    """
    if num_slices < 1:
        raise ValueError("num_slices must be at least 1")
    return (num_slices - 1) // 2 if num_slices % 2 else None


def layer_offsets(num_slices: int, slice_step: float) -> list[float]:
    """Offset of each layer along the normal, in level-0 voxels."""
    center = 0.5 * (num_slices - 1)
    return [(k - center) * slice_step for k in range(num_slices)]


def image_digest(image: str = f"{IMAGE}:{IMAGE_TAG}") -> str:
    """The digest of the local image, as CLAUDE.md requires in every run record."""
    out = subprocess.run(
        ["podman", "image", "inspect", "--format", "{{.Digest}}", image],
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout.strip()


def container_path(path: Path, data_root: Path) -> str:
    """Translate a host path under `data_root` into its path inside the container."""
    try:
        relative = path.resolve().relative_to(data_root.resolve())
    except ValueError as error:
        raise ValueError(f"{path} must be under {data_root}, the only directory mounted") from error
    return f"/data/{relative.as_posix()}"


def build_command(
    *,
    digest: str,
    data_root: Path,
    segment_dir: Path,
    output_dir: Path,
    volume_url: str,
    num_slices: int,
    slice_step: float,
    scale: float,
    group_idx: int,
    cache_gb: int,
    crop: Crop | None,
    container_name: str,
) -> list[str]:
    """The full `podman run` command. The image is addressed by digest, so it is exact."""
    command = [
        "podman", "run", "--rm", "--name", container_name, "--userns=keep-id",
        "-v", f"{data_root.resolve()}:/data",
        f"{IMAGE}@{digest}",
        "vc_render_tifxyz",
        "--volume", "/data/raw/remote-volume",
        "--remote-url", volume_url,
        "--segmentation", container_path(segment_dir, data_root),
        "--scale", f"{scale:g}",
        "--group-idx", str(group_idx),
        "--num-slices", str(num_slices),
        "--slice-step", f"{slice_step:g}",
        "--cache-gb", str(cache_gb),
        "--tif-output", container_path(output_dir / "layers", data_root),
    ]  # fmt: skip
    if crop:
        command += [
            "--crop-x", str(crop.x), "--crop-y", str(crop.y),
            "--crop-width", str(crop.width), "--crop-height", str(crop.height),
        ]  # fmt: skip
    return command


def run_streaming(
    command: list[str], on_line: Callable[[str], None], should_stop: Callable[[], bool], container_name: str
) -> tuple[int, str]:
    """Run the renderer, passing each progress line on; a stop request stops the container."""
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if process.stdout is None:
        raise RuntimeError("no pipe to the renderer")
    log: list[str] = []
    pending = b""
    stopped = False
    while chunk := os.read(process.stdout.fileno(), 4096):
        pending += chunk
        *lines, pending = re.split(rb"[\r\n]+", pending)
        for raw in lines:
            line = raw.decode(errors="replace").strip()
            if line:
                log.append(line)
                on_line(line)
        if should_stop() and not stopped:
            stopped = True
            subprocess.run(["podman", "stop", "--time", "2", container_name], capture_output=True)
    return process.wait(), "\n".join(log)


def layer_files(output_dir: Path) -> list[Path]:
    return sorted((output_dir / "layers").glob("*.tif"))


def prepare_output(output_dir: Path, overwrite: bool) -> None:
    """Clear old layers, or refuse to run over them.

    `vc_render_tifxyz` exits successfully without rendering when all its output files
    exist, so a run over old layers would record their hashes as a fresh result.
    """
    existing = layer_files(output_dir)
    if existing and not overwrite:
        raise FileExistsError(f"{output_dir} already holds {len(existing)} layers; pass --overwrite to render again")
    for path in existing:
        path.unlink()


def layer_statistics(path: Path) -> dict[str, Any]:
    """Descriptive texture statistics for one layer. They hold no image content."""
    image = tifffile.imread(path)
    values = image.astype(np.float64)
    gradient_y, gradient_x = np.gradient(values)
    return {
        "file": path.name,
        "file_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "pixel_sha256": hashlib.sha256(image.tobytes()).hexdigest(),
        "shape": list(image.shape),
        "dtype": str(image.dtype),
        "mean": float(values.mean()),
        "std": float(values.std()),
        "p01": float(np.percentile(values, 1)),
        "p99": float(np.percentile(values, 99)),
        "zero_fraction": float((image == 0).mean()),
        "gradient_energy": float((gradient_x**2 + gradient_y**2).mean()),
    }


def shell_command(command: list[str]) -> str:
    return shlex.join(command)
