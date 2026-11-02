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

from vesuvius_challenge import fetch, render, security, survey
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


def _fourier_shift(img: np.ndarray, shift: np.ndarray) -> np.ndarray:
    """``out(x) = img(x + shift)`` for a periodic, band-limited image."""
    f = np.fft.fftfreq(img.shape[0])
    phase = np.exp(2j * np.pi * (f[:, None] * shift[0] + f[None, :] * shift[1]))
    return np.real(np.fft.ifft2(np.fft.fft2(img) * phase))


def check_phase_correlation_vs_skimage() -> None:
    """WO-002 §3.3: fast path vs skimage (guizar2008), shift error < 0.02 px on noiseless generated patches."""
    from hypothesis import given, settings
    from hypothesis import strategies as st
    from skimage.registration import phase_cross_correlation

    from vesuvius_challenge import lpsf
    from vesuvius_challenge.synthetic import Texture, texture_2d

    @settings(max_examples=60, deadline=None)
    @given(
        st.sampled_from([32, 48, 64]),
        st.floats(7.0, 16.0),
        st.floats(-4.0, 4.0),
        st.floats(-4.0, 4.0),
        st.integers(0, 2**31 - 1),
    )
    def agrees(patch: int, wavelength: float, sv: float, su: float, seed: int) -> None:
        rng = np.random.default_rng(seed)
        a = texture_2d((patch, patch), Texture(spread_deg=None, wavelength=wavelength, bandwidth=0.3), rng)
        truth = np.array([sv, su])
        b = _fourier_shift(a, truth)
        fast = lpsf.phase_correlate(a[None], b[None], lpsf.Params(window=False, beta=1.0)).shift[0]
        slow = phase_cross_correlation(a, b, upsample_factor=100, normalization="phase")[0]
        assert np.abs(fast - truth).max() < 0.02, f"fast {fast} vs truth {truth}"
        assert np.abs(fast - slow).max() < 0.02, f"fast {fast} vs skimage {slow}"

    agrees()


def check_villa_convention() -> None:
    """villa ``_phase_correlate`` (addendum 1 item 3) uses our sign convention; it is cross-checked, not reused."""
    from vesuvius.tifxyz_label_transfer.estimate_canvas_offset import _phase_correlate

    from vesuvius_challenge import lpsf
    from vesuvius_challenge.synthetic import Texture, texture_2d

    rng = np.random.default_rng(7)
    a = texture_2d((64, 64), Texture(spread_deg=None, wavelength=6.0), rng)
    truth = np.array([1.3, -2.2])
    b = _fourier_shift(a, truth)
    villa = np.array(_phase_correlate(a, b)[0])
    fast = lpsf.phase_correlate(a[None], b[None], lpsf.Params(window=False, beta=1.0)).shift[0]
    assert np.abs(villa - truth).max() < 0.5, f"villa {villa} disagrees in sign or scale with truth {truth}"
    assert np.abs(fast - truth).max() < 0.02


def check_integration_analytic() -> None:
    """Screened LSQ and Frankot–Chellappa reproduce an analytic surface from its exact gradient."""
    from vesuvius_challenge import lpsf

    v, u = np.mgrid[0:24, 0:30].astype(np.float64)
    spacing = 32.0
    h = 3 * np.sin(2 * np.pi * u / 25) * np.cos(2 * np.pi * v / 31) + 0.002 * (u - 15) ** 2
    gv = np.gradient(h, axis=0) / spacing
    gu = np.gradient(h, axis=1) / spacing
    cov = np.broadcast_to(1e-4 * np.eye(2), (*h.shape, 2, 2))
    mask = np.ones(h.shape, bool)
    for name, got in (
        ("lsq", lpsf.screened_lsq(gv, gu, cov, spacing, mask)),
        ("lsq screened", lpsf.screened_lsq(gv, gu, cov, spacing, mask, h, mask, zstar_sigma=10.0)),
        ("fc", lpsf.frankot_chellappa(gv, gu, spacing)),
    ):
        err = (got - got.mean()) - (h - h.mean())
        assert np.sqrt(np.mean(err**2)) < 0.12 * h.std(), f"{name}: rms {np.sqrt(np.mean(err**2)):.3f}"


def check_crlb_consistency() -> None:
    """The multi-layer Fisher information with two layers equals the pair formula."""
    from vesuvius_challenge import crlb
    from vesuvius_challenge.synthetic import Sheet, Texture, realistic_texture

    for texture in (Texture(), realistic_texture(6.0)):
        a = crlb.fisher_pair(texture, Sheet(), 1.0, 64)
        b = crlb.fisher_stack(texture, Sheet(), 1.0, 64, 2)
        assert np.allclose(a, b, rtol=1e-6), (a, b)


def check_cubic_resampler() -> None:
    """Patch resampling (prefiltered cubic B-spline) against scipy's cubic spline shift."""
    from scipy import ndimage

    from vesuvius_challenge import lpsf
    from vesuvius_challenge.synthetic import Texture, texture_2d

    rng = np.random.default_rng(3)
    img = texture_2d((96, 96), Texture(spread_deg=None, wavelength=12.0), rng).astype(np.float32)
    shift = np.array([[0.37, -1.62]])
    coef = lpsf.spline_coefficients(img[None])
    got = lpsf.resample_patches(coef, np.array([0]), np.array([16]), np.array([16]), 64, shift)[0]
    want = ndimage.shift(img.astype(np.float64), shift[0], order=3, mode="mirror")[16:80, 16:80]
    assert np.abs(got - want).max() < 1e-3 * np.abs(want).max(), np.abs(got - want).max()


def check_sanitize() -> None:
    from hypothesis import given
    from hypothesis import strategies as st

    user, host = security.machine_identity()
    home = str(Path.home())
    suffix = st.text("abcdefgh0123456789_-", min_size=1, max_size=12)

    @given(suffix, suffix)
    def scrubs_identity(first: str, second: str) -> None:
        clean = security.sanitize({f"{home}/{first}": [f"{user} on {host}", f"{security.REPO_ROOT}/{second}"]})
        text = json.dumps(clean)
        assert home not in text and str(security.REPO_ROOT) not in text
        assert security.sanitize(clean) == clean, "sanitizing twice must change nothing"

    scrubs_identity()


def check_scanner_finds_planted_lines() -> None:
    """`scan_bytes` against a slow reference: a plain search, one line at a time."""
    from hypothesis import given
    from hypothesis import strategies as st

    planted = b"/ho" + b"me/x"
    rules = security.identity_rules("nobody-here", "no-such-host")

    @given(st.lists(st.sampled_from([b"clean text", b"", planted, b"also clean"]), max_size=20))
    def finds_every_line(lines: list[bytes]) -> None:
        expected = [number for number, line in enumerate(lines, 1) if planted in line]
        found = [finding.line for finding in security.scan_bytes("f", b"\n".join(lines), rules)]
        assert sorted(found) == expected

    finds_every_line()


def check_gain_tensor() -> None:
    """`gain_map`'s first-order tensor against a numerical maximum of the correlation model."""
    from hypothesis import given, settings
    from hypothesis import strategies as st
    from scipy import optimize

    @settings(max_examples=30, deadline=None)
    @given(st.floats(1.2, 5.0), st.floats(1.0, 2.0), st.floats(4.0, 30.0), st.floats(0.0, 3.1), st.floats(0.0, 3.1))
    def matches(along: float, across: float, length: float, fibre: float, azimuth: float) -> None:
        e = np.array([np.cos(fibre), np.sin(fibre)])
        n = np.array([-e[1], e[0]])
        tensor = np.outer(e, e) / along**2 + np.outer(n, n) / across**2
        tilt = np.array([np.cos(azimuth), np.sin(azimuth)])
        tan = np.tan(np.deg2rad(0.05))

        def negative(shift: np.ndarray) -> float:
            x = shift - tan * tilt
            return 0.5 * float(x @ tensor @ x) + (1.0 + float(shift @ tilt) * tan) ** 2 / length**2

        found = optimize.minimize(negative, np.zeros(2), tol=1e-12).x
        expected = (np.eye(2) - 2 / length**2 * np.linalg.inv(tensor)) @ tilt * tan
        assert np.abs(found - expected).max() < 2e-3 * tan * (1 + along**2)

    matches()


def check_processing_transfer() -> None:
    """The unsharp mask's frequency response against the mask applied with a real-space Gaussian."""
    from scipy import ndimage

    from vesuvius_challenge.synthetic import processing_transfer

    image = np.random.default_rng(2026).standard_normal((48, 48, 48))
    k = 2 * np.pi * np.fft.fftfreq(48)
    k2 = k[:, None, None] ** 2 + k[None, :, None] ** 2 + k[None, None, :] ** 2
    fast = np.real(np.fft.ifftn(np.fft.fftn(image) * processing_transfer(k2, 0.0, 4.0, 1.2)))
    slow = 5.0 * image - 4.0 * ndimage.gaussian_filter(image, 1.2, mode="wrap", truncate=8.0)
    assert np.std(fast - slow) < 0.02 * np.std(slow)


CHECKS: list[tuple[str, Callable[[], None]]] = [
    ("listing parser, generated pages", check_listing_parser),
    ("listing pagination against a fake bucket", check_listing_pagination),
    ("streamed SHA-256 against one-shot hashlib", check_hash_matches_reference),
    ("download resumes with a byte range after a cut connection", check_resume_after_interruption),
    ("manifest round trip and corruption detection", check_manifest_round_trip),
    ("tifxyz write/read round trip through vesuvius", check_tifxyz_round_trip),
    ("on-surface layer against the renderer's offset list", check_on_surface_layer),
    ("crop flag parsing, generated values", check_crop_parsing),
    ("sanitize removes generated identity and is idempotent", check_sanitize),
    ("identity scan against a line-by-line reference", check_scanner_finds_planted_lines),
    ("gain tensor against a numerical correlation maximum", check_gain_tensor),
    ("processed-noise filter against a real-space unsharp mask", check_processing_transfer),
    ("LPSF phase correlation vs skimage, generated patches", check_phase_correlation_vs_skimage),
    ("villa _phase_correlate sign convention", check_villa_convention),
    ("integration of analytic gradient fields", check_integration_analytic),
    ("CRLB: two-layer stack equals pair formula", check_crlb_consistency),
    ("cubic patch resampler vs scipy spline shift", check_cubic_resampler),
]
