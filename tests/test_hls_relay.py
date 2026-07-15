"""
Tests for the on-demand HLS live-video relay: watch signalling (expiry),
segment/playlist storage, and the filename-safety guard (no path traversal).
"""

import pytest

from alibi.cameras.hls_relay import HlsRelay, is_safe_hls_name


@pytest.fixture
def relay(tmp_path):
    return HlsRelay(base_dir=str(tmp_path / "hls"))


# --- watch signalling ------------------------------------------------------ #

def test_watch_active_then_expires(relay):
    relay.request_watch("cam1", now=1000, ttl=12)
    assert relay.active_watches(now=1005) == ["cam1"]
    assert relay.is_watched("cam1", now=1005) is True
    assert relay.active_watches(now=1013) == []          # 12s TTL passed
    assert relay.is_watched("cam1", now=1013) is False


def test_watch_heartbeat_extends(relay):
    relay.request_watch("cam1", now=1000, ttl=12)
    relay.request_watch("cam1", now=1010, ttl=12)        # heartbeat
    assert relay.is_watched("cam1", now=1018) is True    # extended to 1022


def test_multiple_watches(relay):
    relay.request_watch("cam1", now=1000)
    relay.request_watch("cam2", now=1000)
    assert relay.active_watches(now=1001) == ["cam1", "cam2"]


def test_expired_entries_pruned_on_write(relay):
    relay.request_watch("old", now=0)
    relay.request_watch("new", now=1000)                 # now=1000 prunes 'old'
    assert relay.active_watches(now=1001) == ["new"]


# --- file storage ---------------------------------------------------------- #

def test_put_and_get_files(relay):
    assert relay.put_file("cam1", "index.m3u8", b"#EXTM3U") is True
    assert relay.put_file("cam1", "seg0.ts", b"\x00\x01\x02") is True
    assert relay.get_file("cam1", "index.m3u8") == b"#EXTM3U"
    assert relay.get_file("cam1", "seg0.ts") == b"\x00\x01\x02"
    assert relay.get_file("cam1", "missing.ts") is None


def test_clear_camera(relay):
    relay.put_file("cam1", "seg0.ts", b"x")
    relay.clear_camera("cam1")
    assert relay.get_file("cam1", "seg0.ts") is None


# --- filename safety (path traversal) -------------------------------------- #

def test_safe_name_guard():
    assert is_safe_hls_name("index.m3u8")
    assert is_safe_hls_name("seg12.ts")
    assert not is_safe_hls_name("../../etc/passwd")
    assert not is_safe_hls_name("seg0.ts/../x")
    assert not is_safe_hls_name("evil.sh")
    assert not is_safe_hls_name("a/b.ts")
    assert not is_safe_hls_name("")


def test_put_rejects_unsafe_names(relay):
    assert relay.put_file("cam1", "../escape.ts", b"x") is False
    assert relay.put_file("cam1", "hack.sh", b"x") is False
    assert relay.get_file("cam1", "../escape.ts") is None


def test_camera_id_is_sanitized(relay):
    # a nasty camera_id can't escape the base dir
    relay.put_file("../../evil", "seg0.ts", b"x")
    # it's stored under a sanitized name, retrievable only via the same id
    assert relay.get_file("../../evil", "seg0.ts") == b"x"
