"""
Tests for the Vantage recording agent orchestration — keeping one CameraRecorder
per assigned camera in sync with the cloud's target list, and the run loop. Uses
a fake recorder (no ffmpeg) and injected fetch/sleep/clock.
"""

from alibi.cameras.record_agent import (
    RecordAgent, run_loop, HlsStreamer, hls_loop, FrameUploader, frame_loop,
)
from alibi.cameras.recorder import build_hls_command
from alibi.cameras.rtsp_resolver import derive_substream_url


class FakeRecorder:
    def __init__(self, target):
        self.camera_id = target["camera_id"]
        self.record_url = target["record_url"]
        self.motion_url = target.get("motion_url")
        self.started = False
        self.stopped = False
        self.polls = 0
        self.retentions = 0
    def start(self): self.started = True
    def stop(self): self.stopped = True
    def poll(self, now=None): self.polls += 1
    def apply_retention(self, now=None): self.retentions += 1


def _agent():
    created = []
    def factory(t):
        r = FakeRecorder(t)
        created.append(r)
        return r
    return RecordAgent(base_dir="/tmp/x", recorder_factory=factory), created


def _t(cam_id, url, motion=None):
    return {"camera_id": cam_id, "record_url": url, "motion_url": motion or url}


# --- sync_targets ---------------------------------------------------------- #

def test_starts_recorders_for_new_targets():
    agent, created = _agent()
    agent.sync_targets([_t("cam1", "rtsp://a"), _t("cam2", "rtsp://b")])
    assert agent.status()["count"] == 2
    assert all(r.started for r in created)


def test_stops_recorders_for_removed_targets():
    agent, created = _agent()
    agent.sync_targets([_t("cam1", "rtsp://a"), _t("cam2", "rtsp://b")])
    agent.sync_targets([_t("cam1", "rtsp://a")])              # cam2 gone
    assert agent.status()["recording"] == ["cam1"]
    cam2 = next(r for r in created if r.camera_id == "cam2")
    assert cam2.stopped is True


def test_idempotent_no_restart_when_unchanged():
    agent, created = _agent()
    agent.sync_targets([_t("cam1", "rtsp://a")])
    agent.sync_targets([_t("cam1", "rtsp://a")])              # same URL
    assert len(created) == 1                                  # not re-created
    assert created[0].stopped is False


def test_restarts_when_url_changes():
    agent, created = _agent()
    agent.sync_targets([_t("cam1", "rtsp://a")])
    agent.sync_targets([_t("cam1", "rtsp://a-new")])          # creds/URL changed
    assert len(created) == 2
    assert created[0].stopped is True                         # old torn down
    assert created[1].record_url == "rtsp://a-new"


def test_targets_without_record_url_are_ignored():
    agent, created = _agent()
    agent.sync_targets([{"camera_id": "cam1", "record_url": ""}, _t("cam2", "rtsp://b")])
    assert agent.status()["recording"] == ["cam2"]


def test_tick_polls_and_applies_retention():
    agent, created = _agent()
    agent.sync_targets([_t("cam1", "rtsp://a")])
    agent.tick(); agent.tick()
    assert created[0].polls == 2 and created[0].retentions == 2


def test_stop_all():
    agent, created = _agent()
    agent.sync_targets([_t("cam1", "rtsp://a"), _t("cam2", "rtsp://b")])
    agent.stop_all()
    assert agent.status()["count"] == 0
    assert all(r.stopped for r in created)


# --- run_loop -------------------------------------------------------------- #

def test_run_loop_refreshes_and_ticks():
    agent, created = _agent()
    fetched = {"n": 0}
    def fetch():
        fetched["n"] += 1
        return [_t("cam1", "rtsp://a")]

    # virtual clock advances 100s per sleep so refresh (60s) always fires
    ticks = {"n": 0}
    t = {"now": 0.0}
    def clock(): return t["now"]
    def sleep(_): t["now"] += 100; ticks["n"] += 1
    def should_run(): return ticks["n"] < 3

    run_loop(agent, fetch, sleep, poll_seconds=15, refresh_seconds=60,
             clock=clock, should_run=should_run)
    assert fetched["n"] >= 1
    assert agent.status()["recording"] == ["cam1"]
    assert created[0].polls >= 1


def test_run_loop_survives_fetch_error():
    agent, _ = _agent()
    def fetch(): raise RuntimeError("cloud down")
    ticks = {"n": 0}
    def sleep(_): ticks["n"] += 1
    def should_run(): return ticks["n"] < 2
    # must not raise despite fetch throwing
    run_loop(agent, fetch, sleep, refresh_seconds=0, clock=lambda: 0.0, should_run=should_run)
    assert agent.status()["count"] == 0


# --- on-demand HLS live view ----------------------------------------------- #

def test_hls_command_transcodes_to_h264():
    cmd = build_hls_command("rtsp://x/sub", "/hls/cam1")
    assert cmd[cmd.index("-c:v") + 1] == "libx264"      # browsers can't play HEVC
    assert "-an" in cmd                                  # no audio
    assert cmd[cmd.index("-f") + 1] == "hls"
    assert cmd[-1].endswith("index.m3u8")
    assert "delete_segments" in cmd[cmd.index("-hls_flags") + 1]  # rolling live window


def test_hls_command_is_bandwidth_tuned():
    cmd = build_hls_command("rtsp://x/sub", "/hls/cam1", fps=12, maxrate_kbps=800)
    assert cmd[cmd.index("-r") + 1] == "12"              # framerate cap
    assert cmd[cmd.index("-maxrate") + 1] == "800k"      # hard bitrate ceiling
    assert "-bufsize" in cmd and "-crf" in cmd           # quality target + smoothing


def test_hls_command_defaults_are_nimble():
    cmd = build_hls_command("rtsp://x/sub", "/hls/cam1")
    assert cmd[cmd.index("-r") + 1] == "8"               # low fps by default
    assert cmd[cmd.index("-maxrate") + 1] == "500k"      # low ceiling for scale
    assert cmd[cmd.index("-hls_time") + 1] == "4"        # bigger segments ride out relay jitter


class _FakeProc:
    def __init__(self, cmd): self.cmd = cmd; self._exit = None; self.terminated = False
    def poll(self): return self._exit
    def terminate(self): self.terminated = True; self._exit = -15


def _streamer():
    spawned, uploaded = [], []
    files = {}   # dir -> {name: bytes}
    def spawn(cmd):
        p = _FakeProc(cmd); spawned.append(p); return p
    def lister(d): return list(files.get(d, {}))
    def reader(p):
        import os as _os
        return files[_os.path.dirname(p)][_os.path.basename(p)]
    def upload(cid, name, data): uploaded.append((cid, name, data)); return True
    s = HlsStreamer(base_dir="/hls", upload=upload, spawn=spawn,
                    lister=lister, reader=reader)
    return s, spawned, uploaded, files


def test_hls_starts_stream_only_for_watched(monkeypatch):
    s, spawned, _u, _f = _streamer()
    monkeypatch.setattr("os.makedirs", lambda *a, **k: None)
    s.sync([{"camera_id": "cam1", "url": "rtsp://x/1"}])
    assert s.active == ["cam1"] and len(spawned) == 1
    assert "rtsp://x/1" in spawned[0].cmd
    # a second sync with the same watch does not respawn
    s.sync([{"camera_id": "cam1", "url": "rtsp://x/1"}])
    assert len(spawned) == 1


def test_hls_stops_when_unwatched(monkeypatch):
    s, spawned, _u, _f = _streamer()
    monkeypatch.setattr("os.makedirs", lambda *a, **k: None)
    s.sync([{"camera_id": "cam1", "url": "rtsp://x/1"}])
    s.sync([])                                            # viewer left
    assert s.active == []
    assert spawned[0].terminated is True                  # ffmpeg killed


def test_hls_uploads_changed_files_once(monkeypatch):
    s, spawned, uploaded, files = _streamer()
    monkeypatch.setattr("os.makedirs", lambda *a, **k: None)
    mtimes = {}
    monkeypatch.setattr("os.path.getmtime", lambda p: mtimes.get(p, 1.0))
    monkeypatch.setattr("os.path.getsize", lambda p: len(files["/hls/cam1"][p.split("/")[-1]]))
    monkeypatch.setattr("os.path.isdir", lambda p: True)

    s.sync([{"camera_id": "cam1", "url": "rtsp://x/1"}])
    files["/hls/cam1"] = {"index.m3u8": b"#EXTM3U", "seg0.ts": b"aaa"}
    s.pump()
    assert ("cam1", "seg0.ts", b"aaa") in uploaded
    assert ("cam1", "index.m3u8", b"#EXTM3U") in uploaded
    n = len(uploaded)
    s.pump()                                              # nothing changed
    assert len(uploaded) == n
    # playlist changes -> re-uploaded; new segment -> uploaded
    files["/hls/cam1"]["index.m3u8"] = b"#EXTM3U v2"
    files["/hls/cam1"]["seg1.ts"] = b"bbb"
    mtimes["/hls/cam1/index.m3u8"] = 2.0
    s.pump()
    assert ("cam1", "index.m3u8", b"#EXTM3U v2") in uploaded
    assert ("cam1", "seg1.ts", b"bbb") in uploaded


def test_hls_loop_survives_errors():
    s, _sp, _u, _f = _streamer()
    def boom(): raise RuntimeError("cloud down")
    ticks = {"n": 0}
    def sleep(_): ticks["n"] += 1
    hls_loop(s, boom, sleep, should_run=lambda: ticks["n"] < 2)  # must not raise


# --- frame AI upload (phase 4) --------------------------------------------- #

def _frame_uploader(interval=8):
    uploaded = []
    files = {}   # dir -> {name: bytes}
    t = {"now": 1000.0}
    def lister(d): return list(files.get(d, {}))
    def reader(p):
        import os as _os
        return files[_os.path.dirname(p)][_os.path.basename(p)]
    def upload(cid, data): uploaded.append((cid, data)); return True
    up = FrameUploader(base_dir="/rec", upload=upload, interval=interval,
                       lister=lister, reader=reader, clock=lambda: t["now"])
    return up, uploaded, files, t


def test_frame_uploader_sends_newest_motion_frame():
    up, uploaded, files, t = _frame_uploader()
    files["/rec"] = {"cam1": {}}                       # base lists camera dirs
    files["/rec/cam1/motion"] = {"cam1_01.jpg": b"a", "cam1_02.jpg": b"b"}
    up.tick()
    assert uploaded == [("cam1", b"b")]                # newest only


def test_frame_uploader_skips_hls_and_empty():
    up, uploaded, files, t = _frame_uploader()
    files["/rec"] = {"cam1": {}, "_hls": {}}
    files["/rec/cam1/motion"] = {}                     # no frames
    up.tick()
    assert uploaded == []


def test_frame_uploader_rate_limits_and_dedupes():
    up, uploaded, files, t = _frame_uploader(interval=8)
    files["/rec"] = {"cam1": {}}
    files["/rec/cam1/motion"] = {"a.jpg": b"a"}
    up.tick()
    assert len(uploaded) == 1
    up.tick()                                          # same file -> skip
    assert len(uploaded) == 1
    files["/rec/cam1/motion"]["b.jpg"] = b"b"          # new file, but within interval
    up.tick()
    assert len(uploaded) == 1
    t["now"] += 9                                      # past the interval
    up.tick()
    assert uploaded[-1] == ("cam1", b"b")


def test_frame_loop_survives_errors():
    up, _u, _f, _t = _frame_uploader()
    def boom(): raise RuntimeError("x")
    up.tick = boom
    ticks = {"n": 0}
    def sleep(_): ticks["n"] += 1
    frame_loop(up, sleep, should_run=lambda: ticks["n"] < 2)   # must not raise


# --- storage stats --------------------------------------------------------- #

def test_storage_stats():
    from alibi.cameras.record_agent import storage_stats

    class St:
        def __init__(self, size, mtime): self.st_size = size; self.st_mtime = mtime

    files = {
        "/rec": ["cam1", "_hls"],                       # _hls skipped
        "/rec/cam1/recordings": ["a.mp4", "b.mp4"],
        "/rec/cam1/motion": ["m.jpg"],
    }
    sizes = {
        "/rec/cam1/recordings/a.mp4": St(100, 1.0),
        "/rec/cam1/recordings/b.mp4": St(200, 5.0),
        "/rec/cam1/motion/m.jpg": St(10, 3.0),
    }
    class Du:
        def __init__(self, total, used, free): self.total = total; self.used = used; self.free = free

    s = storage_stats("/rec", lister=lambda d: files.get(d, []), statter=lambda p: sizes[p],
                      disk_usage=lambda p: Du(1000, 690, 310))
    assert s["total_bytes"] == 310
    assert s["files"] == 3
    cam = s["cameras"]["cam1"]
    assert cam["bytes"] == 310 and cam["files"] == 3
    # newest few actual files, sorted newest-first, with kind
    assert [f["name"] for f in cam["recent"]] == ["b.mp4", "m.jpg", "a.mp4"]
    assert cam["recent"][0] == {"name": "b.mp4", "bytes": 200, "mtime": 5.0, "kind": "recording"}
    assert cam["recent"][1]["kind"] == "motion"
    assert s["disk"] == {"total": 1000, "used": 690, "free": 310}
    assert s["oldest"] == 1.0 and s["newest"] == 5.0
    assert s["dir"].endswith("/rec")


# --- sub-stream derivation ------------------------------------------------- #

def test_derive_substream_dahua():
    main = "rtsp://admin:pw@10.0.0.1:554/cam/realmonitor?channel=1&subtype=0"
    assert derive_substream_url(main).endswith("subtype=1")


def test_derive_substream_hikvision():
    main = "rtsp://admin:pw@10.0.0.1:554/Streaming/Channels/101"
    assert derive_substream_url(main).endswith("/Streaming/Channels/102")


def test_derive_substream_unknown_returns_none():
    assert derive_substream_url("rtsp://admin:pw@10.0.0.1:554/live") is None
    assert derive_substream_url("") is None
