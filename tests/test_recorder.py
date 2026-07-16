"""
Tests for the Vantage edge recorder — 24/7 local recording + the cheap motion
trigger. No real ffmpeg or camera: command builders are pure, and the recorder
lifecycle runs against injected fakes (spawn / scan / remove / clock).
"""

from alibi.cameras.recorder import (
    CameraRecorder,
    FileInfo,
    RetentionPolicy,
    build_motion_command,
    build_record_command,
    ffmpeg_available,
    plan_retention,
    choose_video_args,
)


class _R:
    def __init__(self, stdout="", rc=0):
        self.stdout = stdout
        self.returncode = rc


def test_choose_video_args_copies_h264():
    # Source already H.264 -> stream copy, no transcode.
    args = choose_video_args("rtsp://x", run=lambda *a, **k: _R("h264"))
    assert args == ["-c:v", "copy"]


def test_choose_video_args_uses_hardware_for_hevc():
    # H.265 source + a build with VideoToolbox -> hardware encode, not libx264.
    def run(cmd, **k):
        if "ffprobe" in cmd[0]:
            return _R("hevc")
        return _R("... h264_videotoolbox ... h264_nvenc ...")   # -encoders listing
    args = choose_video_args("rtsp://x", run=run)
    assert args[:2] == ["-c:v", "h264_videotoolbox"]


def test_choose_video_args_falls_back_to_libx264():
    def run(cmd, **k):
        if "ffprobe" in cmd[0]:
            return _R("hevc")
        return _R("(no hardware encoders here)")
    args = choose_video_args("rtsp://x", run=run)
    assert "libx264" in args


# --- pure command builders ------------------------------------------------- #

def test_record_command_is_stream_copy_and_segmented():
    cmd = build_record_command("rtsp://x/main", "/rec", segment_seconds=600, prefix="cam1")
    assert "-c:v" in cmd and cmd[cmd.index("-c:v") + 1] == "copy"     # no video re-encode = cheap CPU
    assert "-f" in cmd and cmd[cmd.index("-f") + 1] == "segment"
    assert cmd[cmd.index("-segment_time") + 1] == "600"
    assert "-rtsp_transport" in cmd and cmd[cmd.index("-rtsp_transport") + 1] == "tcp"
    assert cmd[-1].endswith("cam1_%Y%m%d_%H%M%S.mp4")
    assert cmd[-1].startswith("/rec/")


def test_record_command_drops_audio_by_default():
    # Real cameras (Dahua) send pcm_alaw audio that MP4 can't hold — default -an.
    cmd = build_record_command("rtsp://x/main", "/rec")
    assert "-an" in cmd
    assert "-c:a" not in cmd


def test_record_command_transcodes_audio_when_enabled():
    cmd = build_record_command("rtsp://x/main", "/rec", audio=True)
    assert "-an" not in cmd
    assert "-c:a" in cmd and cmd[cmd.index("-c:a") + 1] == "aac"      # MP4-compatible


def test_motion_command_uses_scene_filter():
    cmd = build_motion_command("rtsp://x/sub", "/mo", threshold=0.4, prefix="cam1")  # explicit value
    vf = cmd[cmd.index("-vf") + 1]
    assert "gt(scene,0.4)" in vf                # ffmpeg does the motion detection
    assert "format=yuvj420p" in vf              # JPEG-range for the mjpeg encoder
    assert "scale=" in vf                       # small frames for cheap upload
    assert "-strftime" in cmd                   # so %Y%m%d… expands in the filename
    assert cmd[-1].endswith("cam1_%Y%m%d_%H%M%S.jpg")


def test_motion_threshold_clamped():
    def vf_of(t):
        c = build_motion_command("u", "/d", threshold=t)
        return c[c.index("-vf") + 1]
    assert "gt(scene,1.0)" in vf_of(5.0)
    assert "gt(scene,0.0)" in vf_of(-2.0)


def test_motion_stills_are_rate_capped():
    """select runs per FRAME, so without a gap a 15fps stream writes ~15 JPEGs a
    second during motion — wasted disk + CPU, since the cloud analyses at most one
    frame per camera per 8s."""
    vf = (lambda c: c[c.index("-vf") + 1])(build_motion_command("u", "/d"))
    assert "prev_selected_t" in vf                    # min-gap enforced
    assert "gte(t-prev_selected_t,1.0)" in vf
    assert "isnan(prev_selected_t)" in vf             # first frame still allowed

    vf2 = (lambda c: c[c.index("-vf") + 1])(build_motion_command("u", "/d", min_gap_seconds=5))
    assert "gte(t-prev_selected_t,5.0)" in vf2

    vf3 = (lambda c: c[c.index("-vf") + 1])(build_motion_command("u", "/d", min_gap_seconds=0))
    assert "prev_selected_t" not in vf3               # opt out => every motion frame


def test_ffmpeg_available_true_and_false():
    class R:  # fake completed process
        def __init__(self, rc): self.returncode = rc
    assert ffmpeg_available(run=lambda *a, **k: R(0)) is True
    assert ffmpeg_available(run=lambda *a, **k: R(1)) is False

    def boom(*a, **k): raise OSError("no ffmpeg")
    assert ffmpeg_available(run=boom) is False


# --- retention planning (pure) --------------------------------------------- #

def _f(path, size, mtime):
    return FileInfo(path=path, size=size, mtime=mtime)

def test_retention_age_cap():
    files = [_f("old.mp4", 10, 0), _f("new.mp4", 10, 1000)]
    policy = RetentionPolicy(max_age_seconds=500)
    # now=1000: old.mp4 is 1000s old (> 500) → delete; new.mp4 is fresh → keep
    assert plan_retention(files, now=1000, policy=policy) == ["old.mp4"]


def test_retention_byte_budget_oldest_first():
    files = [_f("a", 100, 1), _f("b", 100, 2), _f("c", 100, 3)]
    policy = RetentionPolicy(max_bytes=250)   # 300 total → must drop 1 (the oldest)
    assert plan_retention(files, now=10, policy=policy) == ["a"]


def test_retention_combines_age_then_size():
    files = [_f("ancient", 100, 0), _f("a", 100, 1000), _f("b", 100, 1100)]
    policy = RetentionPolicy(max_bytes=150, max_age_seconds=500)
    # now=1200: ancient (1200s old) exceeds the age cap → deleted. a (200s) and
    # b (100s) are within age; their 200 bytes exceed the 150 budget → drop the
    # oldest remaining (a). b kept.
    assert plan_retention(files, now=1200, policy=policy) == ["ancient", "a"]


def test_retention_no_policy_deletes_nothing():
    files = [_f("a", 999, 1)]
    assert plan_retention(files, now=10, policy=RetentionPolicy()) == []


# --- recorder lifecycle (injected fakes) ----------------------------------- #

class FakeProc:
    def __init__(self, cmd):
        self.cmd = cmd
        self._exit = None       # None = running
        self.terminated = False
    def poll(self):
        return self._exit
    def die(self, code=1):
        self._exit = code
    def terminate(self):
        self.terminated = True
        self._exit = -15


def _recorder(tmp_path, **kw):
    spawned = []
    def spawn(cmd):
        p = FakeProc(cmd)
        spawned.append(p)
        return p
    kw.setdefault("probe", lambda url: None)   # never touch a real ffprobe/network
    rec = CameraRecorder(
        camera_id="cam1",
        record_url="rtsp://x/main",
        motion_url="rtsp://x/sub",
        base_dir=str(tmp_path),
        spawn=spawn,
        clock=lambda: _recorder.now,   # settable virtual clock
        **kw,
    )
    return rec, spawned
_recorder.now = 0.0


def test_start_spawns_record_and_motion(tmp_path):
    rec, spawned = _recorder(tmp_path)
    rec.start()
    assert len(spawned) == 2                       # record + motion
    names = rec.status()["jobs"]
    assert names["record"]["alive"] and names["motion"]["alive"]
    # motion job points at the sub-stream, record at the main
    record_cmd = spawned[0].cmd
    motion_cmd = spawned[1].cmd
    assert "rtsp://x/main" in record_cmd
    assert "rtsp://x/sub" in motion_cmd


def test_record_only_when_motion_disabled(tmp_path):
    rec, spawned = _recorder(tmp_path, record_motion=False)
    rec.start()
    assert len(spawned) == 1
    assert "motion" not in rec.status()["jobs"]


def test_poll_restarts_a_dead_job_after_backoff(tmp_path):
    rec, spawned = _recorder(tmp_path)
    _recorder.now = 0.0
    rec.start()
    spawned[0].die()                               # record ffmpeg crashes

    # too soon (within backoff) — no restart yet
    _recorder.now = 5.0
    st = rec.poll()
    # still counts as not-yet-restarted at t=5 (backoff is 10s from t=0 default 0)
    # first poll respawns because next_retry starts at 0.0 and now>=0
    assert st["record"]["restarts"] == 1
    assert len(spawned) == 3                        # respawned record

    # the fresh proc is alive
    assert rec.status()["jobs"]["record"]["alive"] is True


def test_poll_respects_backoff_window(tmp_path):
    rec, spawned = _recorder(tmp_path)
    _recorder.now = 100.0
    rec.start()
    st = rec.poll()                                 # all alive, no spawn
    assert st["record"]["restarts"] == 0
    spawned[0].die()
    _recorder.now = 101.0
    rec.poll()                                      # restart #1, next_retry=111
    assert len(spawned) == 3
    spawned[2].die()
    _recorder.now = 105.0                           # still < 111 → no restart
    st = rec.poll()
    assert st["record"]["restarts"] == 1
    assert len(spawned) == 3                        # unchanged

    _recorder.now = 112.0                           # past backoff → restart #2
    rec.poll()
    assert len(spawned) == 4


def test_apply_retention_deletes_and_reports(tmp_path):
    rec, _ = _recorder(tmp_path, retention=RetentionPolicy(max_bytes=150))
    removed = []
    fake_files = {
        rec.recordings_dir: [_f("a", 100, 1), _f("b", 100, 2)],   # 200 > 150 → drop a
        rec.motion_dir: [],
    }
    deleted = rec.apply_retention(
        now=10,
        scan=lambda d: fake_files.get(d, []),
        remove=lambda p: removed.append(p),
    )
    assert deleted == ["a"]
    assert removed == ["a"]


def test_stop_terminates_running_jobs(tmp_path):
    rec, spawned = _recorder(tmp_path)
    rec.start()
    rec.stop()
    assert all(p.terminated for p in spawned)


def test_default_motion_threshold_is_in_surveillance_range():
    """The scene score is the FRACTION of frame changed: a person entering scores
    ~0.01-0.05, a hard scene cut ~0.4. A default up at 0.4 never fires, which
    starves the whole cloud AI pipeline (no motion stills => no frames). Pin the
    default to a range that actually triggers on people/vehicles."""
    from alibi.cameras.recorder import DEFAULT_MOTION_THRESHOLD
    assert 0.005 <= DEFAULT_MOTION_THRESHOLD <= 0.06, (
        f"motion threshold {DEFAULT_MOTION_THRESHOLD} is outside the range that "
        "detects real surveillance motion"
    )
    # and the default must reach the ffmpeg filter
    cmd = build_motion_command("rtsp://x/sub", "/mo")
    vf = cmd[cmd.index("-vf") + 1]
    assert f"gt(scene,{DEFAULT_MOTION_THRESHOLD})" in vf


# --- HEVC recordings must be playable on macOS ----------------------------- #

def test_hevc_recording_is_tagged_hvc1_so_quicktime_can_play_it():
    """ffmpeg tags copied H.265 as `hev1` by default, which QuickTime/Finder
    silently refuse to open. The camera's own bytes are fine — only the tag
    differs — so an H.265 source must be written as `hvc1`."""
    cmd = build_record_command("rtsp://x/main", "/rec", video_codec="hevc")
    assert cmd[cmd.index("-tag:v") + 1] == "hvc1"
    assert cmd[cmd.index("-c:v") + 1] == "copy"     # still no re-encode


def test_h264_recording_is_not_mistagged():
    # hvc1 is an HEVC-only tag; an H.264 copy must not get it.
    cmd = build_record_command("rtsp://x/main", "/rec", video_codec="h264")
    assert "-tag:v" not in cmd
    cmd_unknown = build_record_command("rtsp://x/main", "/rec")   # probe failed
    assert "-tag:v" not in cmd_unknown


def test_recorder_probes_codec_once_and_tags_the_record_job(tmp_path):
    calls = []
    def probe(url):
        calls.append(url)
        return "hevc"
    rec, spawned = _recorder(tmp_path, probe=probe)
    rec.start()
    record_cmd = spawned[0].cmd
    assert record_cmd[record_cmd.index("-tag:v") + 1] == "hvc1"
    assert calls == ["rtsp://x/main"]              # probed the RECORD url, once
    rec._build_jobs()                              # rebuilds don't re-probe
    assert len(calls) == 1


def test_probe_failure_still_records(tmp_path):
    def boom(url): raise OSError("no ffprobe")
    rec, spawned = _recorder(tmp_path, probe=boom)
    rec.start()                                    # must not raise
    assert "-tag:v" not in spawned[0].cmd
