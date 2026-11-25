"""Minimal Cloudflare R2 client over the Cloudflare REST API (no S3 SDK, no extra dependencies).

Configuration (environment):
  CLOUDFLARE_ACCOUNT_ID   required
  CLOUDFLARE_API_TOKEN    bearer token with "Workers R2 Storage: Edit". In GitHub Actions it comes from a
                          repository secret. In Claude Code cloud sessions it may be injected by the network
                          proxy instead, in which case leave it unset.
  ODC_R2_BUCKET           default "librarycard-data"

Never commit any of these values. Object PUTs are limited to ~100 MB per object here; the mirror
writer keeps pack files below that.
"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import quote

import httpx

from .http import USER_AGENT, SourceError

API = "https://api.cloudflare.com/client/v4"
MAX_OBJECT_BYTES = 100_000_000


class R2:
    def __init__(self, bucket: str | None = None, account_id: str | None = None):
        self.account = account_id or os.environ.get("CLOUDFLARE_ACCOUNT_ID")
        if not self.account:
            raise SourceError("CLOUDFLARE_ACCOUNT_ID is not set", kind="network")
        self.bucket = bucket or os.environ.get("ODC_R2_BUCKET", "librarycard-data")
        headers = {"User-Agent": USER_AGENT}
        token = os.environ.get("CLOUDFLARE_API_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self.client = httpx.Client(headers=headers, timeout=httpx.Timeout(600, connect=30))
        self.base = f"{API}/accounts/{self.account}/r2/buckets/{self.bucket}/objects/"

    def _url(self, key: str) -> str:
        return self.base + quote(key, safe="/")

    def put(self, key: str, data: bytes | Path, content_type: str = "application/octet-stream") -> None:
        body = data.read_bytes() if isinstance(data, Path) else data
        if len(body) > MAX_OBJECT_BYTES:
            raise ValueError(f"{key}: {len(body)} bytes exceeds MAX_OBJECT_BYTES")
        for attempt in range(3):
            r = self.client.put(self._url(key), content=body, headers={"content-type": content_type})
            if r.status_code == 200:
                return
            if r.status_code >= 500 and attempt < 2:
                continue
            raise SourceError(f"R2 PUT {key} -> {r.status_code}: {r.text[:300]}", kind="http", status=r.status_code)

    def get(self, key: str) -> bytes | None:
        r = self.client.get(self._url(key))
        if r.status_code == 404:
            return None
        if r.status_code != 200:
            raise SourceError(f"R2 GET {key} -> {r.status_code}: {r.text[:300]}", kind="http", status=r.status_code)
        return r.content

    def delete(self, key: str) -> None:
        r = self.client.delete(self._url(key))
        if r.status_code not in (200, 404):
            raise SourceError(f"R2 DELETE {key} -> {r.status_code}: {r.text[:300]}", kind="http", status=r.status_code)

    def list(self, prefix: str) -> list[str]:
        keys, cursor = [], None
        while True:
            params = {"prefix": prefix, "per_page": 1000}
            if cursor:
                params["cursor"] = cursor
            r = self.client.get(f"{API}/accounts/{self.account}/r2/buckets/{self.bucket}/objects", params=params)
            if r.status_code != 200:
                raise SourceError(f"R2 LIST {prefix} -> {r.status_code}: {r.text[:300]}", kind="http", status=r.status_code)
            d = r.json()
            keys += [o["key"] for o in d.get("result", [])]
            cursor = (d.get("result_info") or {}).get("cursor")
            if not cursor or not (d.get("result_info") or {}).get("is_truncated"):
                return keys
