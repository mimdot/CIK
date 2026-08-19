"""core.http_cache — persistent conditional-GET cache (M2).

A small SQLite store of the ETag / Last-Modified validators plus the last body
per URL, so repeat crawls revalidate with ``If-None-Match`` / ``If-Modified-Since``
and reuse the cached body on ``304 Not Modified`` instead of re-downloading. One
store is shared process-wide (thread-safe) across the concurrent per-source
:class:`~core.http.Http` workers.

Disabled under ``ASTRA_TESTING`` (so the test suite is unaffected) and bypassed by
``--force-refresh``. Every failure degrades to "no cache" — caching must never
break a crawl.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
import time
from typing import Optional
from urllib.parse import urlencode

log = logging.getLogger("core.http_cache")


class HttpCache:
    """SQLite-backed validator+body store, safe to share across threads."""

    def __init__(self, path: str):
        self.path = path
        self._lock = threading.Lock()
        # check_same_thread=False + our own lock: the concurrent per-source
        # workers all share this one connection.
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS http_cache ("
            "url TEXT PRIMARY KEY, etag TEXT, last_modified TEXT, "
            "encoding TEXT, body BLOB, fetched_at REAL)")
        self._conn.commit()

    def get_entry(self, key: str) -> Optional[dict]:
        """The full cached record (validators + body) for a key, or None."""
        with self._lock:
            row = self._conn.execute(
                "SELECT etag, last_modified, encoding, body FROM http_cache "
                "WHERE url = ?", (key,)).fetchone()
        if row is None:
            return None
        return {"etag": row[0], "last_modified": row[1],
                "encoding": row[2], "body": row[3]}

    def store(self, key: str, etag: Optional[str], last_modified: Optional[str],
              body: bytes, encoding: Optional[str] = None) -> None:
        with self._lock:
            try:
                self._conn.execute(
                    "INSERT OR REPLACE INTO http_cache "
                    "(url, etag, last_modified, encoding, body, fetched_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (key, etag, last_modified, encoding, body, time.time()))
                self._conn.commit()
            except sqlite3.Error as exc:  # never let caching break a run
                log.debug("http cache store failed for %s: %s", key, exc)

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except Exception:  # pragma: no cover - defensive
                pass


_CACHES: dict[str, HttpCache] = {}
_CACHES_LOCK = threading.Lock()


def get_http_cache(cfg) -> Optional[HttpCache]:
    """The shared cache for this run, or None when caching is off.

    Off under ``ASTRA_TESTING`` or when ``cfg.http_cache`` is False. The store
    lives next to the run's state file so it is gitignored and per-workspace."""
    if os.environ.get("ASTRA_TESTING") == "1":
        return None
    if not getattr(cfg, "http_cache", True):
        return None
    state_path = getattr(cfg, "state_path", ".seen_positions.json") or ""
    directory = os.path.dirname(state_path) or "."
    path = os.path.join(directory, ".http_cache.sqlite")
    with _CACHES_LOCK:
        cache = _CACHES.get(path)
        if cache is None:
            try:
                cache = HttpCache(path)
            except Exception as exc:  # never let caching break a run
                log.warning("HTTP cache disabled (%s): %s", path, exc)
                return None
            _CACHES[path] = cache
        return cache


def cache_key(url: str, params=None) -> str:
    """Stable key for a request: the URL with any query params folded in."""
    if not params:
        return url
    try:
        query = urlencode(sorted(params.items()))
    except Exception:  # non-dict params
        query = urlencode(params)
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}{query}"


def apply_validators(headers: dict, entry: dict) -> None:
    """Add conditional-GET headers from a cached entry (mutates ``headers``)."""
    if entry.get("etag"):
        headers["If-None-Match"] = entry["etag"]
    if entry.get("last_modified"):
        headers["If-Modified-Since"] = entry["last_modified"]


def response_from_cache(url: str, entry: dict):
    """Build a 200 ``requests.Response`` from a cached entry (used on 304)."""
    import requests
    r = requests.Response()
    r.status_code = 200
    r._content = entry.get("body") or b""
    r.url = url
    r.encoding = entry.get("encoding") or "utf-8"
    if entry.get("etag"):
        r.headers["ETag"] = entry["etag"]
    if entry.get("last_modified"):
        r.headers["Last-Modified"] = entry["last_modified"]
    r.headers["X-Cache"] = "HIT"
    return r
