"""
Tests for the multi-strategy camera scanner.

No real network: the per-strategy methods are stubbed and we assert the
orchestration (merge -> confirm -> fingerprint -> score -> sort) and the
public contract the API/console rely on.
"""

import pytest

from alibi.cameras import network_scanner as ns
from alibi.cameras.network_scanner import (
    DiscoveredCamera,
    NetworkScanner,
    get_network_scanner,
    parse_rtsp_options,
)
from alibi.cameras.oui_prefixes import BRAND_RTSP_TEMPLATES, vendor_for_mac


# --- pure helpers ---------------------------------------------------------- #

class TestRtspOptionsParsing:
    def test_valid_200(self):
        alive, banner = parse_rtsp_options(
            "RTSP/1.0 200 OK\r\nCSeq: 1\r\nServer: Hipcam RealServer/V1.0\r\n\r\n"
        )
        assert alive is True
        assert banner == "Hipcam RealServer/V1.0"

    def test_public_header_counts_as_alive(self):
        alive, _ = parse_rtsp_options("RTSP/1.0 401 Unauthorized\r\nPublic: OPTIONS, DESCRIBE\r\n")
        assert alive is True

    def test_401_without_public_still_counts(self):
        """Dahua etc. answer unauthenticated OPTIONS with a bare 401 — still RTSP."""
        alive, _ = parse_rtsp_options(
            "RTSP/1.0 401 Unauthorized\r\nWWW-Authenticate: Digest realm=x\r\n\r\n")
        assert alive is True

    def test_http_response_is_not_rtsp(self):
        alive, banner = parse_rtsp_options("HTTP/1.1 200 OK\r\nServer: nginx\r\n")
        assert alive is False
        # banner regex still matches "Server:", but alive is the gate
        assert banner == "nginx"

    def test_empty(self):
        assert parse_rtsp_options("") == (False, None)


class TestOui:
    def test_known_vendor(self):
        assert vendor_for_mac("44:19:B6:00:11:22") == "Hikvision"
        assert vendor_for_mac("ec:71:db:aa:bb:cc") == "Reolink"  # case-insensitive

    def test_unknown_vendor(self):
        assert vendor_for_mac("de:ad:be:ef:00:11") is None

    def test_none(self):
        assert vendor_for_mac(None) is None

    def test_macos_arp_fallback_parses_short_octets(self, monkeypatch):
        """macOS `arp -a` prints '0:c:43' — must zero-pad to match the OUI table."""
        import subprocess
        sample = (
            "router (192.168.3.1) at 0:c:43:aa:bb:cc on en0 ifscope [ethernet]\n"
            "? (192.168.3.90) at b4:4c:3b:5f:16:82 on en0 ifscope [ethernet]\n"
            "? (192.168.3.5) at (incomplete) on en0 ifscope [ethernet]\n"
        )
        # Force the Linux path to miss so the macOS branch runs, and stub `arp -a`.
        monkeypatch.setattr("builtins.open", lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError()))
        monkeypatch.setattr(subprocess, "run",
                            lambda *a, **k: type("R", (), {"stdout": sample})())
        table = ns._read_arp_table()
        assert table["192.168.3.1"] == "00:0c:43:aa:bb:cc"     # zero-padded
        assert table["192.168.3.90"] == "b4:4c:3b:5f:16:82"
        assert "192.168.3.5" not in table                       # incomplete skipped
        assert vendor_for_mac(table["192.168.3.1"]) == "Hikvision"

    def test_brand_templates_are_urlencodable_placeholders(self):
        for brand, tpl in BRAND_RTSP_TEMPLATES.items():
            for kind, url in tpl.items():
                assert "{ip}" in url and "{user}" in url and "{pw}" in url


class TestConfidenceScoring:
    def test_onvif_plus_rtsp_is_high(self):
        c = DiscoveredCamera(ip="10.0.0.5")
        c.found_by = {"onvif"}
        c.rtsp_confirmed = True
        c.score()
        assert c.confidence >= 0.9 and c.is_camera

    def test_rtsp_port_open_but_unconfirmed_is_uncertain(self):
        c = DiscoveredCamera(ip="10.0.0.6")
        c.found_by = {"sweep"}
        c.open_ports = [554]
        c.score()
        assert c.confidence == 0.2
        assert c.is_camera is False   # open port alone is not a camera

    def test_confirmed_rtsp_alone_is_a_camera(self):
        c = DiscoveredCamera(ip="10.0.0.7")
        c.found_by = {"sweep"}
        c.open_ports = [8554]
        c.rtsp_confirmed = True
        c.score()
        assert c.is_camera is True

    def test_vendor_and_rtsp_port(self):
        c = DiscoveredCamera(ip="10.0.0.8")
        c.found_by = {"sweep"}
        c.vendor = "Dahua"
        c.open_ports = [554, 80]
        c.score()
        assert c.confidence == 0.5 and c.is_camera


# --- orchestration (mocked strategies) ------------------------------------- #

@pytest.fixture
def scanner(monkeypatch):
    s = NetworkScanner()
    # No real ARP / registered-store lookups.
    monkeypatch.setattr(ns, "_read_arp_table", lambda: {
        "192.168.1.10": "44:19:b6:00:00:01",   # Hikvision
        "192.168.1.30": "de:ad:be:ef:00:99",   # unknown vendor
    })
    monkeypatch.setattr(s, "_mark_registered", lambda cams: None)
    return s


def test_scan_all_merges_and_scores(scanner, monkeypatch):
    # ONVIF found .10 ; mDNS found .20 ; sweep found .10, .20, .30
    monkeypatch.setattr(scanner, "scan_onvif", lambda timeout=5.0: {
        "192.168.1.10": {"xaddr": "http://192.168.1.10/onvif/device_service",
                         "name": "Front Door", "manufacturer": "Hikvision"},
    })
    monkeypatch.setattr(scanner, "scan_mdns", lambda timeout=3.0: {
        "192.168.1.20": {"name": "Axis-Garage"},
    })
    monkeypatch.setattr(scanner, "subnet_sweep", lambda timeout=1.5: {
        "192.168.1.10": [80, 554],
        "192.168.1.20": [554, 8554],
        "192.168.1.30": [80],          # http only, not RTSP
    })
    # RTSP confirms on .10 and .20, not reachable on .30
    monkeypatch.setattr(scanner, "rtsp_probe",
                        lambda ip, port=554, timeout=2.5:
                        (True, "GStreamer") if ip in ("192.168.1.10", "192.168.1.20") else (False, None))

    cams = scanner.scan_all(timeout=1.0)
    by_ip = {c.ip: c for c in cams}

    # Three hosts merged
    assert set(by_ip) == {"192.168.1.10", "192.168.1.20", "192.168.1.30"}

    # .10: onvif + sweep + rtsp confirmed + Hikvision OUI -> top camera
    ten = by_ip["192.168.1.10"]
    assert "onvif" in ten.found_by and "sweep" in ten.found_by
    assert ten.rtsp_confirmed and ten.vendor == "Hikvision"
    assert ten.is_camera and ten.confidence >= 0.9
    assert ten.name == "Front Door"

    # .20: mdns + sweep + rtsp confirmed -> camera
    assert by_ip["192.168.1.20"].is_camera

    # .30: only http port, no rtsp, unknown vendor -> NOT a camera
    assert by_ip["192.168.1.30"].is_camera is False

    # Sorted cameras-first, highest confidence first
    assert cams[0].ip == "192.168.1.10"
    assert cams[-1].ip == "192.168.1.30"


def test_scan_all_is_failsafe_when_a_strategy_raises(scanner, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("multicast blocked")
    monkeypatch.setattr(scanner, "scan_onvif", boom)
    monkeypatch.setattr(scanner, "scan_mdns", lambda timeout=3.0: {})
    monkeypatch.setattr(scanner, "subnet_sweep", lambda timeout=1.5: {})

    cams = scanner.scan_all(timeout=1.0)   # must not raise
    assert cams == []
    assert scanner.is_scanning is False
    assert "error" in scanner.progress["status"]


def test_to_dict_keeps_backcompat_keys(scanner, monkeypatch):
    """The console relies on the original key set — it must survive the upgrade."""
    monkeypatch.setattr(scanner, "scan_onvif", lambda timeout=5.0: {})
    monkeypatch.setattr(scanner, "scan_mdns", lambda timeout=3.0: {})
    monkeypatch.setattr(scanner, "subnet_sweep", lambda timeout=1.5: {"192.168.1.10": [554]})
    monkeypatch.setattr(scanner, "rtsp_probe", lambda ip, port=554, timeout=2.5: (True, "x"))

    d = scanner.scan_all(timeout=1.0)[0].to_dict()
    for key in ("ip", "port", "source_type", "rtsp_url", "name", "manufacturer",
                "model", "resolution", "discovery_method", "already_registered"):
        assert key in d, f"back-compat key {key} missing"
    # And the new richer keys
    for key in ("vendor", "confidence", "is_camera", "open_ports", "rtsp_confirmed", "found_by"):
        assert key in d


def test_singleton_contract():
    a = get_network_scanner()
    b = get_network_scanner()
    assert a is b
    assert hasattr(a, "scan_all") and hasattr(a, "is_scanning") and hasattr(a, "progress")
