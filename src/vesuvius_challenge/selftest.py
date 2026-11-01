"""Fast path against slow reference checks. Synthetic data only, generated in-process."""

from __future__ import annotations

import hashlib
import http.server
import json
import tempfile
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from xml.sax.saxutils import escape

import numpy as np

from vesuvius_challenge import fetch, render, survey
from vesuvius_challenge.s3 import Bucket, parse_listing


def listing_xml(entries: list[tuple[str, int, str]], prefixes: tuple[str, ...] = (), token: str | None = None) -> bytes:
    """A ListObjectsV2 response body, in the shape S3 sends."""
    body = "".join(
        f"<Contents><Key>{escape(key)}</Key><LastModified>2026-01-01T00:00:00.000Z</LastModified>"
        f"<ETag>&quot;{etag}&quot;</ETag><Size>{size}</Size></Contents>"
        for key, size, etag in entries
    )
    body += "".join(f"<CommonPrefixes><Prefix>{escape(p)}</Prefix></CommonPrefixes>" for p in prefixes)
    if token:
        body += f"<NextContinuationToken>{token}</NextContinuationToken>"
    return f'<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">{body}</ListBucketResult>'.encode()


class FakeBucket(http.server.ThreadingHTTPServer):
    """An in-process S3 lookalike: paged listings, ranged GETs, `If-Range`, injected failures."""

    def __init__(self, objects: dict[str, bytes], page_size: int = 2) -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        self.objects = objects
        self.page_size = page_size
        self.ranges_served: list[str] = []
        self.fail_after: dict[str, int] = {}

    @property
    def endpoint(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}"


class _Handler(http.server.BaseHTTPRequestHandler):
    server: FakeBucket

    def log_message(self, format: str, *args: object) -> None:
        pass

    def _send(self, status: int, body: bytes, headers: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Length", str(len(body)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        from urllib.parse import parse_qs, unquote, urlsplit

        url = urlsplit(self.path)
        if "list-type=2" in url.query:
            self._list({key: values[0] for key, values in parse_qs(url.query).items()})
            return
        key = unquote(url.path.lstrip("/"))
        body = self.server.objects.get(key)
        if body is None:
            self._send(404, b"")
            return
        etag = f'"{hashlib.md5(body).hexdigest()}"'
        start, end = 0, len(body)
        requested = self.headers.get("Range")
        honoured = requested is not None and self.headers.get("If-Range") in (None, etag)
        if requested is not None and honoured:
            first, _, last = requested.removeprefix("bytes=").partition("-")
            start, end = int(first), int(last) + 1 if last else len(body)
            if self.headers.get("If-Range"):
                self.server.ranges_served.append(requested)
        payload = body[start:end]
        limit = self.server.fail_after.pop(key, None)
        self.send_response(206 if honoured else 200)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("ETag", etag)
        self.end_headers()
        self.wfile.write(payload if limit is None else payload[:limit])
        if limit is not None:
            self.close_connection = True

    def _list(self, query: dict[str, str]) -> None:
        prefix = query.get("prefix", "")
        delimiter = query.get("delimiter")
        keys = sorted(key for key in self.server.objects if key.startswith(prefix))
        entries: list[tuple[str, int, str]] = []
        prefixes: set[str] = set()
        for key in keys:
            rest = key[len(prefix) :]
            if delimiter and delimiter in rest:
                prefixes.add(prefix + rest.split(delimiter)[0] + delimiter)
            else:
                body = self.server.objects[key]
                entries.append((key, len(body), hashlib.md5(body).hexdigest()))
        start = int(query.get("continuation-token", "0"))
        end = start + self.server.page_size
        token = str(end) if end < len(entries) else None
        self._send(200, listing_xml(entries[start:end], tuple(sorted(prefixes)), token))


@contextmanager
def fake_bucket(objects: dict[str, bytes], page_size: int = 2) -> Iterator[FakeBucket]:
    server = FakeBucket(objects, page_size)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()


def synthetic_objects(size: int = 300_000) -> dict[str, bytes]:
    """A two-segment sample whose mesh bytes are random and whose metadata is minimal."""
    rng = np.random.default_rng(2026)
    mesh = "S/segments/20250101000000-w001/mesh/20250101000000-on-20250202000000-2.4um.tifxyz/"
    objects = {mesh + name: rng.bytes(size) for name in ("x.tif", "y.tif", "z.tif")}
    objects[mesh + "meta.json"] = json.dumps({"scale": [0.05, 0.05], "area_vx2": 1e6}).encode()
    original = "S/segments/20250101000000-w001/mesh/intermediate/tifxyz_original/"
    objects |= {original + name: rng.bytes(64) for name in ("x.tif", "y.tif", "z.tif")}
    objects[original + "meta.json"] = json.dumps({"tags": {"inspect": {"date": "1"}}, "area_cm2": 1.5}).encode()
    objects["S/segments/20250303000000/mesh/notes.txt"] = b"no tifxyz here"
    objects["S/volumes/20250202000000-2.4um-masked.zarr/.zgroup"] = b"{}"
    return objects


def check_listing_pagination() -> None:
    objects = synthetic_objects()
    with fake_bucket(objects) as server:
        found, _ = Bucket(server.endpoint).list("S/")
    assert sorted(o.key for o in found) == sorted(objects), "pagination lost or repeated keys"


def check_hash_matches_reference() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "blob"
        body = np.random.default_rng(1).bytes(3 * fetch.HASH_CHUNK + 17)
        path.write_bytes(body)
        assert fetch.sha256_file(path) == hashlib.sha256(body).hexdigest()


def check_resume_after_interruption() -> None:
    objects = synthetic_objects()
    key = next(k for k in objects if k.endswith("x.tif") and "-on-" in k)
    with tempfile.TemporaryDirectory() as tmp, fake_bucket(objects) as server:
        bucket = Bucket(server.endpoint, retries=2)
        found = next(o for o in bucket.list("S/")[0] if o.key == key)
        server.fail_after[key] = 100_000
        target = Path(tmp) / "x.tif"
        bucket.download(found, target)
        assert target.read_bytes() == objects[key], "resumed bytes differ from the object"
        assert server.ranges_served == ["bytes=100000-"], f"expected one resume, saw {server.ranges_served}"


def check_manifest_round_trip() -> None:
    objects = synthetic_objects()
    with tempfile.TemporaryDirectory() as tmp, fake_bucket(objects) as server:
        bucket = Bucket(server.endpoint)
        prefix = fetch.resolve_segment_prefix(bucket, "S", "20250101000000")
        variants = survey.find_mesh_variants(bucket.list(prefix + "mesh/")[0])
        variant = fetch.select_variant(variants, "20250202000000", None)
        dest = Path(tmp) / "segment"
        hashes, _ = fetch.download_variant(bucket, variant, dest, lambda _: None, lambda: False)
        volume = fetch.find_volume_prefix(bucket, "S", variant.volume_id)
        manifest = fetch.build_manifest("S", "20250101000000", variant, bucket, hashes, volume)
        fetch.write_manifest(manifest, dest / fetch.MANIFEST)
        assert fetch.read_manifest(dest) == manifest, "manifest changed on the way through JSON"
        assert fetch.verify_manifest(manifest, dest) == [], "fresh download failed verification"
        (dest / "y.tif").write_bytes(b"corrupted")
        assert fetch.verify_manifest(manifest, dest) == ["y.tif"], "corruption went undetected"


def check_tifxyz_round_trip() -> None:
    from vesuvius.tifxyz import Tifxyz, read_tifxyz, write_tifxyz

    rows, cols = np.mgrid[0:32, 0:48].astype(np.float32)
    x, y, z = cols * 20, rows * 20, 100 + 2 * cols
    x[3, 5] = y[3, 5] = z[3, 5] = -1
    with tempfile.TemporaryDirectory() as tmp:
        surface = Tifxyz(_x=x, _y=y, _z=z, uuid="synthetic", _scale=(0.05, 0.05))
        write_tifxyz(Path(tmp) / "s", surface, write_mask=False)
        loaded = read_tifxyz(Path(tmp) / "s")
        assert loaded.full_resolution_shape == (640, 960), loaded.full_resolution_shape
        got_x, got_y, got_z, valid = loaded[0:32, 0:48]
        assert np.array_equal(np.nan_to_num(got_z, nan=-1), z), "z changed in the round trip"
        assert not valid[3, 5], "the -1 sentinel must read as invalid"


def check_on_surface_layer() -> None:
    from hypothesis import given, settings
    from hypothesis import strategies as st

    @settings(max_examples=200, deadline=None)
    @given(st.integers(1, 501), st.floats(0.25, 8))
    def fast_matches_reference(num_slices: int, step: float) -> None:
        offsets = render.layer_offsets(num_slices, step)
        zero = [k for k, offset in enumerate(offsets) if offset == 0]
        assert render.on_surface_layer(num_slices) == (zero[0] if zero else None)

    fast_matches_reference()


def check_crop_parsing() -> None:
    from hypothesis import given
    from hypothesis import strategies as st

    @given(st.integers(0, 10**6), st.integers(0, 10**6), st.integers(1, 10**5), st.integers(1, 10**5))
    def round_trips(x: int, y: int, width: int, height: int) -> None:
        assert render.Crop.parse(f"{x},{y},{width},{height}") == render.Crop(x, y, width, height)

    round_trips()


def check_listing_parser() -> None:
    from hypothesis import given
    from hypothesis import strategies as st

    names = st.text(st.characters(codec="ascii", categories=("L", "N")), min_size=1, max_size=20)

    @given(st.lists(st.tuples(names, st.integers(0, 2**40), st.text("abcdef0123", min_size=32, max_size=32))))
    def round_trips(entries: list[tuple[str, int, str]]) -> None:
        parsed, prefixes, token = parse_listing(listing_xml(entries))
        assert [(o.key, o.size, o.etag) for o in parsed] == entries
        assert prefixes == [] and token is None

    round_trips()


CHECKS: list[tuple[str, Callable[[], None]]] = [
    ("listing parser, generated pages", check_listing_parser),
    ("listing pagination against a fake bucket", check_listing_pagination),
    ("streamed SHA-256 against one-shot hashlib", check_hash_matches_reference),
    ("download resumes with a byte range after a cut connection", check_resume_after_interruption),
    ("manifest round trip and corruption detection", check_manifest_round_trip),
    ("tifxyz write/read round trip through vesuvius", check_tifxyz_round_trip),
    ("on-surface layer against the renderer's offset list", check_on_surface_layer),
    ("crop flag parsing, generated values", check_crop_parsing),
]
