"""
Tests for the Vantage recording agent orchestration — keeping one CameraRecorder
per assigned camera in sync with the cloud's target list, and the run loop. Uses
a fake recorder (no ffmpeg) and injected fetch/sleep/clock.
"""

from alibi.cameras.record_agent import RecordAgent, run_loop
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
