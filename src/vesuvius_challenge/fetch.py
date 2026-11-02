"""Resumable download of one segment's tifxyz mesh, with a checksummed manifest."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from vesuvius_challenge.runrecord import utc_now
from vesuvius_challenge.s3 import Bucket, S3Object
from vesuvius_challenge.security import sanitize
from vesuvius_challenge.survey import MeshVariant, choose_primary, segment_id

MANIFEST = "MANIFEST.json"
HASH_CHUNK = 1 << 20


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(HASH_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_segment_prefix(bucket: Bucket, sample: str, identifier: str) -> str:
    """Find a segment directory from its timestamp or its full directory name."""
    prefixes = bucket.child_prefixes(f"{sample}/segments/")
    names = {p.rstrip("/").rpartition("/")[2]: p for p in prefixes}
    if identifier in names:
        return names[identifier]
    matches = [prefix for name, prefix in names.items() if segment_id(name) == identifier]
    if len(matches) == 1:
        return matches[0]
    found = "several directories" if matches else "no directory"
    raise ValueError(f"{found} for segment {identifier!r} in {sample}")


def select_variant(variants: list[MeshVariant], original_volume: str | None, volume: str | None) -> MeshVariant:
    """Choose the mesh for `volume`, or the primary mesh when no volume is requested."""
    if volume is None:
        chosen = choose_primary(variants, original_volume)
        if chosen is None:
            raise ValueError("this segment has no tifxyz mesh")
        return chosen
    for variant in variants:
        if variant.volume_id == volume:
            return variant
    available = sorted(v.volume_id for v in variants if v.volume_id)
    raise ValueError(f"no mesh on volume {volume}; available: {available}")


def find_volume_prefix(bucket: Bucket, sample: str, volume_id: str | None) -> str | None:
    """The uncompressed Zarr store for a volume, skipping re-encoded copies."""
    if volume_id is None:
        return None
    candidates = [p for p in bucket.child_prefixes(f"{sample}/volumes/") if p.split("/")[-2].startswith(volume_id)]
    plain = [p for p in candidates if ".vcd3d." not in p]
    return (plain or candidates or [None])[0]


def build_manifest(
    sample: str,
    identifier: str,
    variant: MeshVariant,
    bucket: Bucket,
    hashes: dict[str, str],
    volume_prefix: str | None,
) -> dict[str, Any]:
    return {
        "schema": 1,
        "sample": sample,
        "segment": identifier,
        "mesh_path": variant.prefix,
        "mesh_kind": variant.kind,
        "volume_id": variant.volume_id,
        "voxel_um": variant.voxel_um,
        "volume_path": volume_prefix,
        "volume_url": bucket.url(volume_prefix.rstrip("/")) if volume_prefix else None,
        "created_at": utc_now(),
        "files": [
            {
                "name": obj.key.rpartition("/")[2],
                "url": bucket.url(obj.key),
                "size": obj.size,
                "sha256": hashes[obj.key],
                "etag": obj.etag,
                "last_modified": obj.last_modified,
            }
            for obj in variant.objects
        ],
    }


def write_manifest(manifest: dict[str, Any], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sanitize(manifest), indent=2, sort_keys=True) + "\n")
    return path


def read_manifest(segment_dir: Path) -> dict[str, Any]:
    path = segment_dir / MANIFEST
    if not path.exists():
        raise FileNotFoundError(f"{path} is missing; create it with `vch fetch`")
    return json.loads(path.read_text())


def verify_manifest(manifest: dict[str, Any], segment_dir: Path) -> list[str]:
    """Return the names of files whose size or SHA-256 no longer match the manifest."""
    bad = []
    for entry in manifest["files"]:
        path = segment_dir / entry["name"]
        if not path.exists() or path.stat().st_size != entry["size"] or sha256_file(path) != entry["sha256"]:
            bad.append(entry["name"])
    return bad


def download_variant(
    bucket: Bucket,
    variant: MeshVariant,
    dest: Path,
    on_bytes: Callable[[int], None],
    should_stop: Callable[[], bool],
) -> tuple[dict[str, str], list[S3Object]]:
    """Fetch every file of a mesh; a complete file with a matching ETag is not fetched again."""
    known = _known_etags(dest)
    hashes: dict[str, str] = {}
    fetched: list[S3Object] = []
    for obj in variant.objects:
        target = dest / obj.key.rpartition("/")[2]
        if target.exists() and target.stat().st_size == obj.size and known.get(target.name) == obj.etag:
            on_bytes(obj.size)
        else:
            bucket.download(obj, target, on_bytes, should_stop)
            fetched.append(obj)
        hashes[obj.key] = sha256_file(target)
    return hashes, fetched


def _known_etags(dest: Path) -> dict[str, str]:
    try:
        return {entry["name"]: entry["etag"] for entry in read_manifest(dest)["files"]}
    except FileNotFoundError:
        return {}


def part_bytes(dest: Path) -> int:
    return sum(path.stat().st_size for path in dest.glob("*.part"))
