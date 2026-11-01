"""Survey parsing and merging on synthetic listings."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import tifffile

from vesuvius_challenge import survey
from vesuvius_challenge.s3 import Bucket, S3Object
from vesuvius_challenge.selftest import fake_bucket, synthetic_objects


def objects_in(folder: str, names: tuple[str, ...] = survey.TIFXYZ_FILES, size: int = 10) -> list[S3Object]:
    return [S3Object(f"{folder}/{name}", size, "e", "t") for name in names]


def test_on_volume_folder_yields_volume_and_voxel_size() -> None:
    found = survey.find_mesh_variants(objects_in("S/segments/1/mesh/1-on-20260102150214-2.399um.tifxyz"))
    assert [(v.kind, v.volume_id, v.voxel_um, v.bytes) for v in found] == [("on-volume", "20260102150214", 2.399, 40)]


def test_incomplete_mesh_folder_is_ignored() -> None:
    assert survey.find_mesh_variants(objects_in("S/segments/1/mesh/x", ("x.tif", "meta.json"))) == []


def test_intermediate_folders_are_named_by_kind() -> None:
    found = survey.find_mesh_variants(objects_in("S/segments/1/mesh/intermediate/tifxyz_flattened"))
    assert found[0].kind == "flattened"
    assert found[0].volume_id is None


def test_primary_prefers_the_tracing_volume_then_original_then_finest() -> None:
    a = survey.MeshVariant("a/", "on-volume", 1, volume_id="111", voxel_um=9.0)
    b = survey.MeshVariant("b/", "on-volume", 1, volume_id="222", voxel_um=2.4)
    original = survey.MeshVariant("o/", "original", 1)
    assert survey.choose_primary([a, b, original], "111") is a
    assert survey.choose_primary([a, b, original], "999") is original
    assert survey.choose_primary([a, b], None) is b
    assert survey.choose_primary([], None) is None


@pytest.mark.parametrize(
    ("meta", "expected"),
    [
        ({"tags": {"approved": {"user": "x"}, "inspect": {}}}, ["approved", "inspect"]),
        ({"tags": ["reviewed", "defective"]}, ["defective", "reviewed"]),
        ({"tags": {}}, []),
        ({"tags": None}, []),
        ({}, []),
    ],
)
def test_tags_read_both_vc3d_shapes(meta: dict[str, Any], expected: list[str]) -> None:
    assert survey.tags_from_meta(meta) == expected


@pytest.mark.parametrize(
    ("dirname", "expected"),
    [
        ("20250108000000-w025_2025010863", "20250108000000"),
        ("20230827161846_superseded", "20230827161846"),
        ("20231210121321", "20231210121321"),
    ],
)
def test_segment_id(dirname: str, expected: str) -> None:
    assert survey.segment_id(dirname) == expected


@pytest.mark.parametrize("byteorder", ["<", ">"])
@pytest.mark.parametrize("compression", [None, "lzw"])
@pytest.mark.parametrize("bigtiff", [False, True])
def test_tiff_size_reads_the_header_without_the_pixels(byteorder: str, compression: str | None, bigtiff: bool) -> None:
    buffer = io.BytesIO()
    image = np.zeros((70, 300), np.float32)
    tifffile.imwrite(buffer, image, byteorder=byteorder, compression=compression, bigtiff=bigtiff)
    with fake_bucket({"m/x.tif": buffer.getvalue()}) as server:
        assert survey.tiff_size(Bucket(server.endpoint), "m/x.tif") == (300, 70)


def test_tiff_size_declines_what_is_not_a_tiff() -> None:
    with fake_bucket({"m/x.tif": b"not a tiff at all"}) as server:
        assert survey.tiff_size(Bucket(server.endpoint), "m/x.tif") is None


def test_autoindex_keeps_only_subdirectories() -> None:
    html = (
        '<a href="../">up</a><a href="/x/">root</a><a href="123/">d</a>'
        '<a href="f.txt">f</a><a href="9_superseded/">s</a>'
    )
    assert survey.parse_autoindex(html) == ["123", "9_superseded"]


def test_segment_row_collects_tags_and_area_across_variants() -> None:
    with fake_bucket(synthetic_objects()) as server:
        row = survey.survey_s3_segment(
            Bucket(server.endpoint),
            "S",
            "S/segments/20250101000000-w001/",
            {
                "segments": {
                    "20250101000000": {"original_volume_id": "20250202000000", "data": [{"type": "ink-labels"}]}
                }
            },
            {"20250202000000": "S/volumes/x/"},
        )
    assert row["id"] == "20250101000000"
    assert row["has_tifxyz"] and row["n_mesh_variants"] == 2
    assert row["mesh_kind"] == "on-volume" and row["volume_on_s3"]
    assert row["tags"] == ["inspect"]
    assert row["area_cm2"] == 1.5
    assert row["has_ink_labels"]
    assert row["area_cm2_derived"] == pytest.approx(1e6 * (2.4e-4) ** 2)


def test_area_vx2_comes_from_the_primary_mesh_not_another_variant() -> None:
    objects = synthetic_objects()
    original = "S/segments/20250101000000-w001/mesh/intermediate/tifxyz_original/meta.json"
    objects[original] = b'{"area_vx2": 5.0}'
    with fake_bucket(objects) as server:
        row = survey.survey_s3_segment(
            Bucket(server.endpoint),
            "S",
            "S/segments/20250101000000-w001/",
            {"segments": {"20250101000000": {"original_volume_id": "20250202000000"}}},
            {},
        )
    assert row["area_vx2"] == 1e6


def test_segment_without_mesh_is_reported_not_dropped() -> None:
    with fake_bucket(synthetic_objects()) as server:
        row = survey.survey_s3_segment(Bucket(server.endpoint), "S", "S/segments/20250303000000/", {}, {})
    assert not row["has_tifxyz"]
    assert row["mesh_path"] is None


def legacy_row(name: str, tags: list[str] | None = None) -> dict[str, Any]:
    return {
        "dirname": name,
        "id": survey.segment_id(name),
        "source": "legacy",
        "superseded": survey.SUPERSEDED in name,
        "tags": tags or [],
        "legacy_path": f"p/{name}/",
    }


def s3_row(name: str) -> dict[str, Any]:
    return {
        "dirname": name,
        "id": survey.segment_id(name),
        "source": "s3",
        "superseded": False,
        "tags": [],
        "legacy_path": None,
    }


def test_merge_joins_by_id_and_keeps_legacy_only_rows() -> None:
    rows = survey.merge_rows(
        [s3_row("100-w1")],
        [legacy_row("100", ["reviewed"]), legacy_row("200"), legacy_row("100_superseded")],
    )
    by_name = {row["dirname"]: row for row in rows}
    assert by_name["100-w1"]["source"] == "both"
    assert by_name["100-w1"]["tags"] == ["reviewed"]
    assert by_name["200"]["source"] == "legacy"
    assert by_name["100_superseded"]["source"] == "legacy", "a superseded folder must not merge into its successor"


def test_summary_counts_only_s3_segments_as_on_s3() -> None:
    row = {
        **s3_row("1"),
        "has_tifxyz": True,
        "has_ink_labels": False,
        "tags": ["inspect"],
        "mesh_bytes": 5,
    }
    stats = survey.summarise(
        [row, {**legacy_row("2_superseded", ["approved"]), "has_tifxyz": False, "has_ink_labels": False}]
    )
    assert stats["segments_on_s3"] == 1
    assert stats["legacy_only"] == 1
    assert stats["superseded"] == 1
    assert stats["tag_distribution"] == {"inspect": 1}
    assert stats["tag_distribution_legacy_only"] == {"approved": 1}


def test_tables_share_a_schema_even_when_a_column_is_all_empty(tmp_path: Path) -> None:
    with fake_bucket(synthetic_objects()) as server:
        empty = survey.survey_s3_segment(Bucket(server.endpoint), "S", "S/segments/20250303000000/", {}, {})
    assert empty["tags"] == []
    pq.write_table(pa.Table.from_pylist([empty], schema=survey.SCHEMA), tmp_path / "a.parquet")
    pq.write_table(pa.Table.from_pylist([{**empty, "tags": ["inspect"]}], schema=survey.SCHEMA), tmp_path / "b.parquet")
    read_a = pq.read_table(tmp_path / "a.parquet")
    assert read_a.schema.field("tags").type == pa.list_(pa.string())
    assert read_a.schema.equals(pq.read_table(tmp_path / "b.parquet").schema)
