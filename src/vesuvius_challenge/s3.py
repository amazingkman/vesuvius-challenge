"""Anonymous access to the public Vesuvius Challenge bucket over plain HTTPS."""

from __future__ import annotations

import gzip
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

BUCKET = "vesuvius-challenge-open-data"
ENDPOINT = f"https://{BUCKET}.s3.amazonaws.com"
CHUNK_BYTES = 1 << 20
RETRYABLE_HTTP = {429, 500, 502, 503, 504}

_NS = {"s": "http://s3.amazonaws.com/doc/2006-03-01/"}


@dataclass(frozen=True)
class S3Object:
    key: str
    size: int
    etag: str
    last_modified: str


class IncompleteDownload(Exception):
    """A stop was requested before the file finished; the `.part` file is kept."""


def parse_listing(xml: bytes) -> tuple[list[S3Object], list[str], str | None]:
    """Parse a ListObjectsV2 page into objects, common prefixes and the next token."""
    root = ET.fromstring(xml)
    objects = [
        S3Object(
            key=item.findtext("s:Key", namespaces=_NS) or "",
            size=int(item.findtext("s:Size", default="0", namespaces=_NS)),
            etag=(item.findtext("s:ETag", default="", namespaces=_NS)).strip('"'),
            last_modified=item.findtext("s:LastModified", default="", namespaces=_NS),
        )
        for item in root.findall("s:Contents", _NS)
    ]
    prefixes = [item.findtext("s:Prefix", default="", namespaces=_NS) for item in root.findall("s:CommonPrefixes", _NS)]
    return objects, prefixes, root.findtext("s:NextContinuationToken", namespaces=_NS)


def decode_json(body: bytes) -> Any:
    """Parse JSON, transparently gunzipping objects stored with gzip encoding."""
    if body[:2] == b"\x1f\x8b":
        body = gzip.decompress(body)
    return json.loads(body)


class Bucket:
    """Read-only client. `endpoint` is overridable so tests can use an in-process server."""

    def __init__(self, endpoint: str = ENDPOINT, timeout: float = 60.0, retries: int = 4) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.timeout = timeout
        self.retries = retries

    def url(self, key: str) -> str:
        return f"{self.endpoint}/{urllib.parse.quote(key)}"

    @staticmethod
    def s3_uri(https_url: str) -> str:
        """The `s3://` form of a bucket URL. `vesuvius.Volume` cannot list a group over HTTPS."""
        return https_url.replace(f"{ENDPOINT}/", f"s3://{BUCKET}/")

    def _read(self, url: str, headers: dict[str, str] | None = None) -> bytes:
        return self._retry(lambda: self._open(url, headers).read())

    def _open(self, url: str, headers: dict[str, str] | None = None) -> Any:
        return urllib.request.urlopen(urllib.request.Request(url, headers=headers or {}), timeout=self.timeout)

    def _retry(self, attempt: Callable[[], Any]) -> Any:
        for tries_left in range(self.retries, -1, -1):
            try:
                return attempt()
            except urllib.error.HTTPError as error:
                if error.code not in RETRYABLE_HTTP or not tries_left:
                    raise
            except urllib.error.URLError, TimeoutError, ConnectionError:
                if not tries_left:
                    raise
            time.sleep(0.5 * 2 ** (self.retries - tries_left))
        raise AssertionError("unreachable")

    def list(self, prefix: str, delimiter: str | None = None) -> tuple[list[S3Object], list[str]]:
        """List every object and common prefix under `prefix`, following pagination."""
        objects: list[S3Object] = []
        prefixes: list[str] = []
        token: str | None = None
        while True:
            query = {"list-type": "2", "prefix": prefix, "max-keys": "1000"}
            if delimiter:
                query["delimiter"] = delimiter
            if token:
                query["continuation-token"] = token
            page, common, token = parse_listing(self._read(f"{self.endpoint}/?{urllib.parse.urlencode(query)}"))
            objects += page
            prefixes += common
            if token is None:
                return objects, prefixes

    def child_prefixes(self, prefix: str) -> list[str]:
        """The immediate sub-prefixes of `prefix`, excluding a folder marker for itself."""
        return [p for p in self.list(prefix, delimiter="/")[1] if p != prefix]

    def get_json(self, key: str) -> Any:
        return decode_json(self._read(self.url(key)))

    def get_url_bytes(self, url: str) -> bytes:
        return self._read(url)

    def get_range(self, key: str, start: int, length: int) -> bytes:
        return self._read(self.url(key), {"Range": f"bytes={start}-{start + length - 1}"})

    def download(
        self,
        obj: S3Object,
        dest: Path,
        on_bytes: Callable[[int], None] = lambda _: None,
        should_stop: Callable[[], bool] = lambda: False,
    ) -> None:
        """Download `obj` to `dest`, resuming from `dest.part` if an earlier run stopped.

        `If-Range` makes the server send the whole object when its ETag has changed, so a
        resumed file can never mix two versions of the object.
        """
        part = dest.with_name(dest.name + ".part")
        dest.parent.mkdir(parents=True, exist_ok=True)

        counted = 0

        def report(position: int) -> None:
            nonlocal counted
            on_bytes(position - counted)
            counted = position

        def attempt() -> None:
            have = part.stat().st_size if part.exists() else 0
            if have > obj.size:
                part.unlink()
                have = 0
            if have == obj.size:
                report(have)
                return
            headers = {"Range": f"bytes={have}-", "If-Range": f'"{obj.etag}"'} if have else {}
            with self._open(self.url(obj.key), headers) as response:
                position = have if response.status == 206 else 0
                report(position)
                with part.open("ab" if position else "wb") as out:
                    while chunk := response.read(CHUNK_BYTES):
                        out.write(chunk)
                        position += len(chunk)
                        report(position)
                        if should_stop():
                            raise IncompleteDownload(obj.key)
            # A connection cut mid-body ends the read loop without an exception.
            if position != obj.size:
                raise ConnectionError(f"{obj.key}: stopped at {position} of {obj.size} bytes")

        self._retry(attempt)
        part.replace(dest)
