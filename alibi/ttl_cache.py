"""
Tiny in-process TTL cache for expensive read-mostly summaries.

Some endpoints (metrics, the LLM-phrased security brief) decrypt large stores
or make a paid Claude call on every page load — fine once, but the console
re-fetches them and they don't need per-second freshness. This memoises a
result for a short window so the page loads instantly (and the brief stops
burning credits on every view). Cache is per-process; a restart clears it.

`now()` is injectable so tests don't depend on the wall clock.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, Dict, Tuple

_store: Dict[str, Tuple[float, Any]] = {}
_lock = threading.Lock()


def cached(key: str, ttl_seconds: float, produce: Callable[[], Any],
           now: Callable[[], float] = time.monotonic) -> Any:
    """Return a cached value for `key` if fresh, else call `produce()`, store,
    and return it. Thread-safe. A produce() exception is not cached."""
    t = now()
    with _lock:
        hit = _store.get(key)
        if hit is not None and (t - hit[0]) < ttl_seconds:
            return hit[1]
    value = produce()                      # outside the lock — may be slow/IO
    with _lock:
        _store[key] = (now(), value)
    return value


def invalidate(prefix: str = "") -> None:
    """Drop cache entries whose key starts with `prefix` ('' clears all)."""
    with _lock:
        for k in [k for k in _store if k.startswith(prefix)]:
            _store.pop(k, None)
