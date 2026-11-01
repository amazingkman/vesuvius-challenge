"""Survey the segments of one sample: what exists, in which form, and with which tags."""

from __future__ import annotations

import re
import struct
import urllib.error
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any

import pyarrow as pa

from vesuvius_challenge.s3 import Bucket, S3Object, decode_json

ON_VOLUME = re.compile(r"-on-(?P<volume>\d+)-(?P<um>[\d.]+)um\.tifxyz$")
HREF = re.compile(r'href="([^"]+)"')
SUPERSEDED = "_superseded"
UM_PER_CM = 1e4
TIFXYZ_FILES = ("x.tif", "y.tif", "z.tif", "meta.json")
TIFF_IMAGE_WIDTH = 256
TIFF_IMAGE_LENGTH = 257
TIFF_ENTRY_BYTES = 12

# Fixed, so that tables from different samples combine even where a column is all empty.
SCHEMA = pa.schema(
    [
        ("sample", pa.string()),
        ("id", pa.string()),
        ("dirname", pa.string()),
        ("source", pa.string()),
        ("has_tifxyz", pa.bool_()),
        ("n_mesh_variants", pa.int32()),
        ("mesh_kind", pa.string()),
        ("mesh_path", pa.string()),
        ("mesh_volume_id", pa.string()),
        ("mesh_voxel_um", pa.float64()),
        ("mesh_bytes", pa.int64()),
        ("mesh_grid_width", pa.int64()),
        ("mesh_grid_height", pa.int64()),
        ("mesh_scale", pa.float64()),
        ("mesh_width_px", pa.int64()),
        ("mesh_height_px", pa.int64()),
        ("original_volume_id", pa.string()),
        ("volume_on_s3", pa.bool_()),
        ("tags", pa.list_(pa.string())),
        ("area_cm2", pa.float64()),
        ("area_vx2", pa.float64()),
        ("area_cm2_derived", pa.float64()),
        ("path", pa.string()),
        ("legacy_path", pa.string()),
        ("superseded", pa.bool_()),
        ("has_ink_labels", pa.bool_()),
        ("has_surface_volume", pa.bool_()),
    ]
)


@dataclass
class MeshVariant:
    """One tifxyz directory of a segment. A segment can hold several, one per volume."""

    prefix: str
    kind: str
    bytes: int
    objects: list[S3Object] = field(default_factory=list)
    volume_id: str | None = None
    voxel_um: float | None = None


def find_mesh_variants(objects: list[S3Object]) -> list[MeshVariant]:
    """Group a listing of `<segment>/mesh/` into complete tifxyz directories."""
    folders: dict[str, dict[str, S3Object]] = {}
    for obj in objects:
        folder, _, name = obj.key.rpartition("/")
        folders.setdefault(folder, {})[name] = obj
    variants = []
    for folder, files in sorted(folders.items()):
        if not all(name in files for name in TIFXYZ_FILES):
            continue
        name = folder.rpartition("/")[2]
        match = ON_VOLUME.search(name)
        kind = "on-volume" if match else name.removeprefix("tifxyz_")
        kept = [files[name] for name in TIFXYZ_FILES]
        variants.append(
            MeshVariant(
                prefix=folder + "/",
                kind=kind,
                bytes=sum(o.size for o in kept),
                objects=kept,
                volume_id=match["volume"] if match else None,
                voxel_um=float(match["um"]) if match else None,
            )
        )
    return variants


def choose_primary(variants: list[MeshVariant], original_volume_id: str | None) -> MeshVariant | None:
    """Pick the mesh in the coordinates of the volume the segment was traced on."""
    for variant in variants:
        if variant.volume_id is not None and variant.volume_id == original_volume_id:
            return variant
    for variant in variants:
        if variant.kind == "original":
            return variant
    on_volume = [v for v in variants if v.voxel_um is not None]
    if on_volume:
        return min(on_volume, key=lambda v: v.voxel_um or 0.0)
    return variants[0] if variants else None


def tags_from_meta(meta: dict[str, Any]) -> list[str]:
    """Tag names from a meta.json. VC3D writes an object keyed by tag; older tools a list."""
    tags = meta.get("tags")
    if isinstance(tags, dict):
        return sorted(tags)
    if isinstance(tags, list):
        return sorted(str(tag) for tag in tags)
    return []


def segment_id(dirname: str) -> str:
    """The leading timestamp of a segment directory name."""
    return dirname.removesuffix(SUPERSEDED).split("-")[0]


def parse_autoindex(html: str) -> list[str]:
    """Sub-directory names from a dl.ash2txt.org directory listing."""
    return [h.rstrip("/") for h in HREF.findall(html) if h.endswith("/") and not h.startswith(("/", ".", "?"))]


def tiff_size(bucket: Bucket, key: str) -> tuple[int, int] | None:
    """Width and height from a classic TIFF header, using ranged reads only."""
    head = bucket.get_range(key, 0, 8)
    order = {b"II": "<", b"MM": ">"}.get(head[:2])
    if order is None or struct.unpack(order + "H", head[2:4])[0] != 42:
        return None
    ifd = struct.unpack(order + "I", head[4:8])[0]
    count = struct.unpack(order + "H", bucket.get_range(key, ifd, 2))[0]
    entries = bucket.get_range(key, ifd + 2, count * TIFF_ENTRY_BYTES)
    size: dict[int, int] = {}
    for index in range(count):
        tag, kind = struct.unpack_from(order + "HH", entries, index * TIFF_ENTRY_BYTES)
        if tag in (TIFF_IMAGE_WIDTH, TIFF_IMAGE_LENGTH):
            size[tag] = struct.unpack_from(order + ("H" if kind == 3 else "I"), entries, index * TIFF_ENTRY_BYTES + 8)[
                0
            ]
    if len(size) != 2:
        return None
    return size[TIFF_IMAGE_WIDTH], size[TIFF_IMAGE_LENGTH]


def _bucket_entry(sample_meta: dict[str, Any], identifier: str) -> dict[str, Any]:
    return sample_meta.get("segments", {}).get(identifier, {})


def _data_types(entry: dict[str, Any]) -> set[str]:
    return {item.get("type", "") for item in entry.get("data", [])}


def survey_s3_segment(
    bucket: Bucket, sample: str, prefix: str, sample_meta: dict[str, Any], volumes: dict[str, str]
) -> dict[str, Any]:
    """Build the row for one segment directory in the bucket."""
    dirname = prefix.rstrip("/").rpartition("/")[2]
    identifier = segment_id(dirname)
    entry = _bucket_entry(sample_meta, identifier)
    original_volume = entry.get("original_volume_id")
    variants = find_mesh_variants(bucket.list(prefix + "mesh/")[0])
    primary = choose_primary(variants, original_volume)

    tags: set[str] = set()
    area_cm2 = area_vx2 = None
    primary_area = primary_scale = None
    for variant in variants:
        meta = bucket.get_json(variant.prefix + "meta.json")
        tags.update(tags_from_meta(meta))
        area_cm2 = area_cm2 if area_cm2 is not None else meta.get("area_cm2")
        area_vx2 = area_vx2 if area_vx2 is not None else meta.get("area_vx2")
        if variant is primary:
            primary_area = meta.get("area_vx2")
            primary_scale = (meta.get("scale") or [None])[0]

    grid = tiff_size(bucket, primary.prefix + "x.tif") if primary else None
    grid_width, grid_height = grid or (None, None)
    full = [round(side / primary_scale) if side and primary_scale else None for side in (grid_width, grid_height)]
    types = _data_types(entry)
    voxel_um = primary.voxel_um if primary else None
    derived = primary_area * (voxel_um / UM_PER_CM) ** 2 if primary_area and voxel_um else None
    return {
        "sample": sample,
        "id": identifier,
        "dirname": dirname,
        "source": "s3",
        "has_tifxyz": bool(variants),
        "n_mesh_variants": len(variants),
        "mesh_kind": primary.kind if primary else None,
        "mesh_path": primary.prefix if primary else None,
        "mesh_volume_id": primary.volume_id if primary else None,
        "mesh_voxel_um": voxel_um,
        "mesh_bytes": primary.bytes if primary else None,
        "mesh_grid_width": grid_width,
        "mesh_grid_height": grid_height,
        "mesh_scale": primary_scale,
        "mesh_width_px": full[0],
        "mesh_height_px": full[1],
        "original_volume_id": original_volume,
        "volume_on_s3": bool(primary and primary.volume_id in volumes),
        "tags": sorted(tags),
        "area_cm2": area_cm2,
        "area_vx2": area_vx2,
        "area_cm2_derived": derived,
        "path": prefix,
        "legacy_path": None,
        "superseded": SUPERSEDED in dirname,
        "has_ink_labels": "ink-labels" in types,
        "has_surface_volume": "layers-zarr" in types,
    }


def survey_legacy_segment(bucket: Bucket, sample: str, legacy_url: str, name: str) -> dict[str, Any]:
    """Build the row for one legacy `paths/` directory on dl.ash2txt.org."""
    path = f"{legacy_url.rstrip('/')}/paths/{name}/"
    try:
        files = set(HREF.findall(bucket.get_url_bytes(path).decode(errors="replace")))
    except urllib.error.HTTPError:
        files = set()
    tags = tags_from_meta(decode_json(bucket.get_url_bytes(path + "meta.json"))) if "meta.json" in files else []
    return {
        "sample": sample,
        "id": segment_id(name),
        "dirname": name,
        "source": "legacy",
        "has_tifxyz": "x.tif" in files,
        "n_mesh_variants": 0,
        "mesh_kind": None,
        "mesh_path": None,
        "mesh_volume_id": None,
        "mesh_voxel_um": None,
        "mesh_bytes": None,
        "mesh_grid_width": None,
        "mesh_grid_height": None,
        "mesh_scale": None,
        "mesh_width_px": None,
        "mesh_height_px": None,
        "original_volume_id": None,
        "volume_on_s3": False,
        "tags": tags,
        "area_cm2": None,
        "area_vx2": None,
        "area_cm2_derived": None,
        "path": path,
        "legacy_path": path,
        "superseded": SUPERSEDED in name,
        "has_ink_labels": False,
        "has_surface_volume": False,
    }


def merge_rows(s3_rows: list[dict[str, Any]], legacy_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Join S3 and legacy rows by directory name, keeping legacy-only directories as rows."""
    by_name = {row["dirname"]: row for row in s3_rows}
    by_id = {row["id"]: row for row in s3_rows}
    merged = list(s3_rows)
    for legacy in legacy_rows:
        twin = by_name.get(legacy["dirname"]) or (by_id.get(legacy["id"]) if not legacy["superseded"] else None)
        if twin is None:
            merged.append(legacy)
            continue
        twin["source"] = "both"
        twin["legacy_path"] = legacy["legacy_path"]
        twin["tags"] = sorted(set(twin["tags"]) | set(legacy["tags"]))
    return sorted(merged, key=lambda row: row["dirname"])


def summarise(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate counts for the run record and the summary table."""
    on_s3 = [row for row in rows if row["source"] in ("s3", "both")]
    tags = Counter(tag for row in on_s3 for tag in row["tags"])
    legacy_tags = Counter(tag for row in rows if row["source"] == "legacy" for tag in row["tags"])
    return {
        "segments_on_s3": len(on_s3),
        "with_tifxyz": sum(row["has_tifxyz"] for row in on_s3),
        "legacy_only": sum(row["source"] == "legacy" for row in rows),
        "superseded": sum(row["superseded"] for row in rows),
        "with_ink_labels": sum(row["has_ink_labels"] for row in on_s3),
        "tag_distribution": dict(tags.most_common()),
        "tag_distribution_legacy_only": dict(legacy_tags.most_common()),
        "segments_with_any_tag": sum(bool(row["tags"]) for row in on_s3),
        "mesh_bytes_primary": sum(row["mesh_bytes"] or 0 for row in on_s3),
    }


def run_parallel(tasks: list[Any], work: Any, workers: int, on_done: Any, should_stop: Any) -> list[Any]:
    """Run `work` over `tasks`, stopping new work when asked and keeping what finished."""
    results = []
    with ThreadPoolExecutor(workers) as pool:
        futures = {pool.submit(work, task): task for task in tasks}
        for future in as_completed(futures):
            if should_stop():
                for pending in futures:
                    pending.cancel()
            if future.cancelled():
                continue
            results.append(future.result())
            on_done(results[-1])
    return results
