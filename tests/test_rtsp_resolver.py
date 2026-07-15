"""
Tests for the RTSP URL resolver — turning a discovered camera + creds into a
playable, brand-correct stream URL.

The bug this prevents: adding a real Dahua/Hikvision camera with a default
`/stream1` path, which never connects.
"""

from alibi.cameras.rtsp_resolver import build_rtsp_url, infer_brand, resolve_for_discovered


class TestInferBrand:
    def test_from_onvif_name(self):
        # Our live scan showed Dahuas with name="Dahua", vendor="".
        assert infer_brand({"name": "Dahua", "vendor": ""}) == "Dahua"

    def test_from_vendor(self):
        assert infer_brand({"vendor": "Hikvision"}) == "Hikvision"

    def test_from_model_string(self):
        assert infer_brand({"model": "DH-IPC-HFW3441E-AS-S2", "name": "Dahua"}) == "Dahua"

    def test_lorex_maps_to_dahua_oem(self):
        assert infer_brand({"manufacturer": "Lorex"}) == "Dahua"

    def test_unknown(self):
        assert infer_brand({"name": "Camera (192.168.3.1)"}) is None


class TestBuildUrl:
    def test_dahua_main_and_sub_paths(self):
        main = build_rtsp_url("192.168.3.91", "Dahua", "admin", "pass", stream="main")
        sub = build_rtsp_url("192.168.3.91", "Dahua", "admin", "pass", stream="sub")
        assert main == "rtsp://admin:pass@192.168.3.91:554/cam/realmonitor?channel=1&subtype=0"
        assert sub.endswith("subtype=1")

    def test_hikvision_path(self):
        url = build_rtsp_url("10.0.0.5", "Hikvision", "admin", "pw")
        assert url == "rtsp://admin:pw@10.0.0.5:554/Streaming/Channels/101"

    def test_password_is_url_encoded(self):
        # A password with @ : / must not corrupt the URL.
        url = build_rtsp_url("10.0.0.5", "Dahua", "admin", "p@ss:w/rd")
        assert "admin:p%40ss%3Aw%2Frd@10.0.0.5" in url
        assert url.count("@") == 1   # only the credentials separator

    def test_non_standard_port(self):
        url = build_rtsp_url("10.0.0.5", "Dahua", "a", "b", port=8554)
        assert "@10.0.0.5:8554/" in url

    def test_unknown_brand_returns_none(self):
        assert build_rtsp_url("10.0.0.5", "NoName", "a", "b") is None
        assert build_rtsp_url("10.0.0.5", None, "a", "b") is None


class TestResolveForDiscovered:
    def test_resolves_dahua_from_scan_shape(self):
        # The exact shape our scanner/agent emits for the Dahua cameras.
        cam = {"ip": "192.168.3.92", "port": 554, "vendor": "",
               "manufacturer": "", "name": "Dahua", "model": "DH-IPC-HFW3441E"}
        url = resolve_for_discovered(cam, "admin", "secret", stream="sub")
        assert url == "rtsp://admin:secret@192.168.3.92:554/cam/realmonitor?channel=1&subtype=1"

    def test_unknown_brand_returns_none(self):
        assert resolve_for_discovered({"ip": "10.0.0.9", "name": "Camera"}, "a", "b") is None
