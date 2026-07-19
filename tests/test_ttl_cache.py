"""TTL cache — fresh hits reuse, stale recompute, errors not cached."""

from alibi import ttl_cache


def setup_function():
    ttl_cache.invalidate("")


def test_fresh_hit_reuses_value():
    calls = []
    clock = [100.0]
    def produce():
        calls.append(1); return len(calls)
    v1 = ttl_cache.cached("k", 30, produce, now=lambda: clock[0])
    clock[0] = 120.0                       # within TTL
    v2 = ttl_cache.cached("k", 30, produce, now=lambda: clock[0])
    assert v1 == v2 == 1 and len(calls) == 1


def test_stale_recomputes():
    calls = []
    clock = [100.0]
    produce = lambda: (calls.append(1), len(calls))[1]
    ttl_cache.cached("k", 30, produce, now=lambda: clock[0])
    clock[0] = 140.0                       # past TTL
    ttl_cache.cached("k", 30, produce, now=lambda: clock[0])
    assert len(calls) == 2


def test_exception_not_cached():
    state = {"fail": True}
    def produce():
        if state["fail"]:
            raise RuntimeError("boom")
        return "ok"
    try:
        ttl_cache.cached("k", 30, produce)
    except RuntimeError:
        pass
    state["fail"] = False
    assert ttl_cache.cached("k", 30, produce) == "ok"   # recomputed, not cached error


def test_invalidate_prefix():
    ttl_cache.cached("metrics:24h", 999, lambda: 1)
    ttl_cache.cached("brief:x", 999, lambda: 2)
    ttl_cache.invalidate("metrics:")
    hits = []
    ttl_cache.cached("metrics:24h", 999, lambda: hits.append(1) or 9)
    ttl_cache.cached("brief:x", 999, lambda: hits.append(1) or 9)
    assert len(hits) == 1                  # only metrics recomputed
