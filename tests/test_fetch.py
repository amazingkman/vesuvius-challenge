"""Mesh download and manifests against an in-process bucket."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from vesuvius_challenge import fetch, survey
from vesuvius_challenge.s3 import Bucket
from vesuvius_challenge.selftest import fake_bucket, synthetic_objects


def variants(bucket: Bucket) -> list[survey.MeshVariant]:
    prefix = fetch.resolve_segment_prefix(bucket, "S", "20250101000000")
    return survey.find_mesh_variants(bucket.list(prefix + "mesh/")[0])


def test_resolve_accepts_timestamp_and_full_name() -> None:
    with fake_bucket(synthetic_objects()) as server:
        bucket = Bucket(server.endpoint)
        expected = "S/segments/20250101000000-w001/"
        assert fetch.resolve_segment_prefix(bucket, "S", "20250101000000") == expected
        assert fetch.resolve_segment_prefix(bucket, "S", "20250101000000-w001") == expected
        with pytest.raises(ValueError, match="no directory"):
            fetch.resolve_segment_prefix(bucket, "S", "19990101000000")


def test_select_variant_by_volume_and_reports_alternatives() -> None:
    with fake_bucket(synthetic_objects()) as server:
        found = variants(Bucket(server.endpoint))
    assert fetch.select_variant(found, "20250202000000", None).kind == "on-volume"
    assert fetch.select_variant(found, None, "20250202000000").kind == "on-volume"
    with pytest.raises(ValueError, match="20250202000000"):
        fetch.select_variant(found, None, "111")


def test_no_mesh_is_a_clear_error() -> None:
    with pytest.raises(ValueError, match="no tifxyz"):
        fetch.select_variant([], None, None)


def test_volume_prefix_skips_the_recoded_copy() -> None:
    objects = {
        "S/volumes/20260101-2.4um-lpc-q1-v0.2.0.vcd3d.zarr/.zgroup": b"{}",
        "S/volumes/20260101-2.4um-masked.zarr/.zgroup": b"{}",
    }
    with fake_bucket(objects) as server:
        bucket = Bucket(server.endpoint)
        assert fetch.find_volume_prefix(bucket, "S", "20260101") == "S/volumes/20260101-2.4um-masked.zarr/"
        assert fetch.find_volume_prefix(bucket, "S", "999") is None
        assert fetch.find_volume_prefix(bucket, "S", None) is None


def fetch_all(bucket: Bucket, dest: Path) -> dict:
    variant = fetch.select_variant(variants(bucket), "20250202000000", None)
    hashes, _ = fetch.download_variant(bucket, variant, dest, lambda _: None, lambda: False)
    manifest = fetch.build_manifest("S", "20250101000000", variant, bucket, hashes, None)
    fetch.write_manifest(manifest, dest / fetch.MANIFEST)
    return manifest


def test_manifest_records_each_file_with_true_hash(tmp_path: Path) -> None:
    objects = synthetic_objects()
    with fake_bucket(objects) as server:
        manifest = fetch_all(Bucket(server.endpoint), tmp_path)
    assert sorted(entry["name"] for entry in manifest["files"]) == ["meta.json", "x.tif", "y.tif", "z.tif"]
    for entry in manifest["files"]:
        body = (tmp_path / entry["name"]).read_bytes()
        assert entry["size"] == len(body)
        assert entry["sha256"] == hashlib.sha256(body).hexdigest()
    assert json.loads((tmp_path / fetch.MANIFEST).read_text()) == manifest


def test_second_fetch_downloads_nothing(tmp_path: Path) -> None:
    with fake_bucket(synthetic_objects()) as server:
        bucket = Bucket(server.endpoint)
        fetch_all(bucket, tmp_path)
        variant = fetch.select_variant(variants(bucket), "20250202000000", None)
        _, fetched = fetch.download_variant(bucket, variant, tmp_path, lambda _: None, lambda: False)
    assert fetched == []


def test_verify_reports_a_changed_file(tmp_path: Path) -> None:
    with fake_bucket(synthetic_objects()) as server:
        manifest = fetch_all(Bucket(server.endpoint), tmp_path)
    assert fetch.verify_manifest(manifest, tmp_path) == []
    (tmp_path / "z.tif").unlink()
    assert fetch.verify_manifest(manifest, tmp_path) == ["z.tif"]


def test_read_manifest_explains_a_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="vch fetch"):
        fetch.read_manifest(tmp_path)
