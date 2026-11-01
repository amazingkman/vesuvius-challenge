"""Cross-check a VC3D render against an independent read through the `vesuvius` package."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import tifffile
from scipy.ndimage import map_coordinates

from vesuvius_challenge.render import Crop


def pearson(a: np.ndarray, b: np.ndarray) -> float:
    """Pearson correlation over the positions where both inputs are finite."""
    keep = np.isfinite(a) & np.isfinite(b)
    if keep.sum() < 3 or a[keep].std() == 0 or b[keep].std() == 0:
        return float("nan")
    return float(np.corrcoef(a[keep], b[keep])[0, 1])


def block_bounds(points: np.ndarray, shape: tuple[int, ...], pad: int) -> tuple[tuple[int, int], ...]:
    """Inclusive-exclusive z, y, x ranges that hold `points` plus `pad` voxels on each side."""
    low = np.floor(np.nanmin(points.reshape(-1, 3), axis=0)).astype(int) - pad
    high = np.ceil(np.nanmax(points.reshape(-1, 3), axis=0)).astype(int) + pad + 1
    return tuple((max(int(a), 0), min(int(b), size)) for a, b, size in zip(low, high, shape, strict=True))


def sample_block(block: np.ndarray, origin: np.ndarray, points: np.ndarray) -> np.ndarray:
    """Trilinear samples of `block` at z, y, x `points`; NaN outside the block."""
    coordinates = np.moveaxis(points - origin, -1, 0)
    return map_coordinates(block.astype(np.float32), coordinates, order=1, mode="constant", cval=np.nan)


def surface_points(segment_dir: Path, crop: Crop, stride: int) -> dict[str, Any]:
    """Read the mesh with `vesuvius.tifxyz` and return z, y, x points and normals in the crop."""
    from vesuvius.tifxyz import read_tifxyz

    surface = read_tifxyz(segment_dir)
    full_shape = surface.full_resolution_shape
    surface.use_full_resolution()
    rows = (crop.y, crop.y + crop.height)
    cols = (crop.x, crop.x + crop.width)
    x, y, z, valid = surface[rows[0] : rows[1], cols[0] : cols[1]]
    nx, ny, nz = surface.get_normals(rows[0], rows[1], cols[0], cols[1])
    points = np.stack([z, y, x], axis=-1).astype(np.float32)[::stride, ::stride]
    normals = np.stack([nz, ny, nx], axis=-1).astype(np.float32)[::stride, ::stride]
    usable = np.asarray(valid)[::stride, ::stride] & np.isfinite(normals).all(axis=-1)
    points[~usable] = np.nan
    normals[~usable] = np.nan
    return {
        "points": points,
        "normals": normals,
        "stored_shape": list(surface._stored_shape),
        "full_shape": list(full_shape),
        "scale": list(surface.get_scale_tuple()),
        "valid_fraction": float(usable.mean()),
    }


def compare_with_render(
    block: np.ndarray,
    origin: np.ndarray,
    points: np.ndarray,
    normals: np.ndarray,
    layers: list[Path],
    k0: int,
    stride: int,
    probe: int,
) -> dict[str, Any]:
    """Correlate rendered layers with samples taken along the normal in Python.

    `shift` is the integer offset of the Python sample relative to the rendered layer. Its
    best value should be zero for the on-surface layer. The two `probe` entries show whether
    a rendered layer above k0 lies along the positive or the negative `vesuvius` normal.
    """
    rendered = tifffile.imread(layers[k0]).astype(np.float32)[::stride, ::stride]
    at_surface = sample_block(block, origin, points)
    per_offset = {
        offset: pearson(sample_block(block, origin, points + offset * normals), rendered) for offset in range(-3, 4)
    }
    above = tifffile.imread(layers[k0 + probe]).astype(np.float32)[::stride, ::stride]
    return {
        "pearson_k0": pearson(at_surface, rendered),
        "pearson_by_python_offset": {str(key): value for key, value in per_offset.items()},
        "best_python_offset": max(per_offset, key=lambda key: per_offset[key]),
        "probe_layer": k0 + probe,
        "pearson_probe_plus_normal": pearson(sample_block(block, origin, points + probe * normals), above),
        "pearson_probe_minus_normal": pearson(sample_block(block, origin, points - probe * normals), above),
        "samples": int(np.isfinite(at_surface).sum()),
    }


def save_layer_figure(layers: list[Path], k0: int, path: Path) -> Path:
    """Save layers k0-1, k0 and k0+1 side by side. Callers decide whether it may be kept."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    picks = (k0 - 1, k0, k0 + 1)
    images = [tifffile.imread(layers[k]) for k in picks]
    low, high = np.percentile(images[1], [1, 99])
    figure, axes = plt.subplots(1, 3, figsize=(12, 4.3), constrained_layout=True)
    for axis, image, k in zip(axes, images, picks, strict=True):
        axis.imshow(image, cmap="gray", vmin=low, vmax=high, interpolation="nearest")
        axis.set_title(f"layer {k} ({k - k0:+d} from k0)")
        axis.set_axis_off()
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=170)
    plt.close(figure)
    return path
