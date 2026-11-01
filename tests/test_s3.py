"""Bucket client against an in-process server. No network, no scroll data."""

from __future__ import annotations

import gzip
import json
import urllib.error
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from vesuvius_challenge.s3 import Bucket, IncompleteDownload, decode_json, parse_listing
from vesuvius_challenge.selftest import fake_bucket, listing_xml, synthetic_objects


def mesh_key(objects: dict[str, bytes]) -> str:
    return next(key for key in objects if key.endswith("x.tif") and "-on-" in key)


def test_list_follows_every_page() -> None:
    objects = synthetic_objects()
    with fake_bucket(objects, page_size=1) as server:
        found, _ = Bucket(server.endpoint).list("S/")
    assert sorted(o.key for o in found) == sorted(objects)


def test_child_prefixes_are_immediate_only() -> None:
    with fake_bucket(synthetic_objects()) as server:
        found = Bucket(server.endpoint).child_prefixes("S/segments/")
    assert found == ["S/segments/20250101000000-w001/", "S/segments/20250303000000/"]


def test_listing_carries_size_etag_and_token() -> None:
    objects, prefixes, token = parse_listing(listing_xml([("a/b", 7, "abc")], ("a/",), "next"))
    assert (objects[0].key, objects[0].size, objects[0].etag) == ("a/b", 7, "abc")
    assert prefixes == ["a/"]
    assert token == "next"


@given(st.dictionaries(st.text(max_size=8), st.integers(), max_size=5))
def test_decode_json_handles_plain_and_gzip(payload: dict[str, int]) -> None:
    body = json.dumps(payload).encode()
    assert decode_json(body) == payload
    assert decode_json(gzip.compress(body)) == payload


def test_missing_key_is_not_retried_forever() -> None:
    with fake_bucket({}) as server, pytest.raises(urllib.error.HTTPError):
        Bucket(server.endpoint).get_json("absent.json")


def test_download_resumes_from_part_left_by_earlier_run(tmp_path: Path) -> None:
    objects = synthetic_objects()
    key = mesh_key(objects)
    target = tmp_path / "x.tif"
    target.with_name("x.tif.part").write_bytes(objects[key][:1000])
    seen: list[int] = []
    with fake_bucket(objects) as server:
        bucket = Bucket(server.endpoint)
        found = next(o for o in bucket.list("S/")[0] if o.key == key)
        bucket.download(found, target, seen.append)
        assert server.ranges_served == ["bytes=1000-"]
    assert target.read_bytes() == objects[key]
    assert sum(seen) == len(objects[key])


def test_download_restarts_when_the_object_changed(tmp_path: Path) -> None:
    objects = synthetic_objects()
    key = mesh_key(objects)
    target = tmp_path / "x.tif"
    target.with_name("x.tif.part").write_bytes(b"stale bytes from an older object")
    with fake_bucket(objects) as server:
        bucket = Bucket(server.endpoint)
        found = next(o for o in bucket.list("S/")[0] if o.key == key)
        stale = type(found)(found.key, found.size, "0" * 32, found.last_modified)
        bucket.download(stale, target)
        assert server.ranges_served == []
    assert target.read_bytes() == objects[key]


def test_stop_request_keeps_the_part_file(tmp_path: Path) -> None:
    objects = {"big": b"x" * (3 << 20)}
    target = tmp_path / "big"
    with fake_bucket(objects) as server, pytest.raises(IncompleteDownload):
        bucket = Bucket(server.endpoint)
        bucket.download(bucket.list("")[0][0], target, should_stop=lambda: True)
    assert not target.exists()
    assert target.with_name("big.part").stat().st_size > 0


def test_s3_uri_form() -> None:
    assert Bucket.s3_uri(Bucket().url("S/volumes/v.zarr")) == "s3://vesuvius-challenge-open-data/S/volumes/v.zarr"
