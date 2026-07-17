"""
ONVIF: ask the camera for its stream URL instead of guessing vendor paths.

Guessing is why onboarding is fiddly — a wrong RTSP path is indistinguishable
from a wrong password. These pin the parsing/selection against real ONVIF
response shapes, with no camera and no network.
"""

import base64
import hashlib

from alibi.cameras.onvif import (
    discover, parse_probe_matches, parse_profiles, parse_stream_uri,
    pick_streams, stream_profiles, with_credentials, ws_security_header,
    StreamProfile,
)

PROBE_MATCH = """<?xml version="1.0"?>
<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://www.w3.org/2003/05/soap-envelope"
 xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery">
 <SOAP-ENV:Body><d:ProbeMatches><d:ProbeMatch>
   <d:Scopes>onvif://www.onvif.org/name/Dahua onvif://www.onvif.org/hardware/IPC-HDW1234
              onvif://www.onvif.org/location/country/china</d:Scopes>
   <d:XAddrs>http://192.168.3.91/onvif/device_service</d:XAddrs>
 </d:ProbeMatch></d:ProbeMatches></SOAP-ENV:Body></SOAP-ENV:Envelope>"""

GET_PROFILES = """<?xml version="1.0"?>
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
 xmlns:trt="http://www.onvif.org/ver10/media/wsdl" xmlns:tt="http://www.onvif.org/ver10/schema">
 <s:Body><trt:GetProfilesResponse>
  <trt:Profiles token="Profile_1"><tt:Name>MainStream</tt:Name>
    <tt:VideoEncoderConfiguration><tt:Encoding>H265</tt:Encoding>
      <tt:Resolution><tt:Width>2592</tt:Width><tt:Height>1944</tt:Height></tt:Resolution>
      <tt:RateControl><tt:FrameRateLimit>20</tt:FrameRateLimit></tt:RateControl>
    </tt:VideoEncoderConfiguration></trt:Profiles>
  <trt:Profiles token="Profile_2"><tt:Name>SubStream</tt:Name>
    <tt:VideoEncoderConfiguration><tt:Encoding>H264</tt:Encoding>
      <tt:Resolution><tt:Width>704</tt:Width><tt:Height>576</tt:Height></tt:Resolution>
      <tt:RateControl><tt:FrameRateLimit>15</tt:FrameRateLimit></tt:RateControl>
    </tt:VideoEncoderConfiguration></trt:Profiles>
 </trt:GetProfilesResponse></s:Body></s:Envelope>"""

def _uri(u):
    # Real cameras XML-escape the & in query strings; ET returns it decoded.
    u = u.replace("&", "&amp;")
    return f"""<?xml version="1.0"?>
    <s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
     xmlns:trt="http://www.onvif.org/ver10/media/wsdl" xmlns:tt="http://www.onvif.org/ver10/schema">
     <s:Body><trt:GetStreamUriResponse><trt:MediaUri>
       <tt:Uri>{u}</tt:Uri><tt:InvalidAfterConnect>false</tt:InvalidAfterConnect>
     </trt:MediaUri></trt:GetStreamUriResponse></s:Body></s:Envelope>"""


# --- discovery -------------------------------------------------------------- #

def test_probe_match_yields_ip_vendor_and_model():
    devs = parse_probe_matches(PROBE_MATCH)
    assert len(devs) == 1
    d = devs[0]
    assert d.ip == "192.168.3.91"
    assert d.xaddr == "http://192.168.3.91/onvif/device_service"
    assert d.manufacturer == "Dahua"
    assert d.model == "IPC-HDW1234"


def test_discover_dedupes_devices_answering_twice():
    # ONVIF devices commonly answer a probe more than once.
    devs = discover(sender=lambda probe, t: [PROBE_MATCH, PROBE_MATCH])
    assert len(devs) == 1


def test_discover_survives_garbage_replies():
    devs = discover(sender=lambda probe, t: ["not xml", "", "<a/>", PROBE_MATCH])
    assert len(devs) == 1


def test_discover_with_no_answers():
    assert discover(sender=lambda probe, t: []) == []


# --- profiles + stream uris ------------------------------------------------- #

def test_profiles_are_parsed_with_resolution_and_codec():
    ps = parse_profiles(GET_PROFILES)
    assert [p.token for p in ps] == ["Profile_1", "Profile_2"]
    main = ps[0]
    assert main.name == "MainStream" and main.encoding == "H265"
    assert (main.width, main.height) == (2592, 1944) and main.fps == 20


def test_stream_uri_is_extracted():
    assert parse_stream_uri(_uri("rtsp://192.168.3.91:554/cam/realmonitor?channel=1&subtype=0")) \
        == "rtsp://192.168.3.91:554/cam/realmonitor?channel=1&subtype=0"


def test_non_rtsp_uri_is_ignored():
    assert parse_stream_uri(_uri("http://192.168.3.91/snapshot")) == ""


def test_end_to_end_gets_real_urls_without_guessing_paths():
    """The whole point: the camera tells us its path — we never guess."""
    calls = []
    def send(url, xml, timeout):
        calls.append(xml)
        if "GetProfiles" in xml:
            return GET_PROFILES
        if "Profile_1" in xml:
            return _uri("rtsp://192.168.3.91:554/cam/realmonitor?channel=1&subtype=0")
        return _uri("rtsp://192.168.3.91:554/cam/realmonitor?channel=1&subtype=1")

    ps = stream_profiles("http://192.168.3.91/onvif/device_service",
                         "admin", "secret", send=send)
    assert len(ps) == 2
    assert ps[0].rtsp_url.endswith("subtype=0")
    assert ps[1].rtsp_url.endswith("subtype=1")
    assert "admin:secret@" in ps[0].rtsp_url        # usable by the recorder as-is


def test_a_camera_that_refuses_returns_nothing_rather_than_raising():
    def boom(url, xml, timeout):
        raise OSError("unauthorized")
    assert stream_profiles("http://1.2.3.4/onvif/device_service", "a", "b", send=boom) == []


# --- credentials ------------------------------------------------------------ #

def test_credentials_are_injected_and_escaped():
    u = with_credentials("rtsp://192.168.3.91:554/live", "admin", "p@ss/word")
    assert u.startswith("rtsp://admin:p%40ss%2Fword@192.168.3.91")


def test_credentials_not_added_twice():
    already = "rtsp://admin:x@192.168.3.91:554/live"
    assert with_credentials(already, "admin", "x") == already


# --- WS-Security ------------------------------------------------------------ #

def test_password_digest_matches_the_onvif_spec():
    nonce, created, pw = b"0123456789abcdef", "2026-07-17T05:00:00Z", "secret"
    hdr = ws_security_header("admin", pw, nonce=nonce, created=created)
    expected = base64.b64encode(hashlib.sha1(nonce + created.encode() + pw.encode()).digest()).decode()
    assert expected in hdr
    assert pw not in hdr                    # the password itself never goes on the wire
    assert base64.b64encode(nonce).decode() in hdr


# --- choosing main vs sub --------------------------------------------------- #

def test_picks_biggest_for_recording_and_smallest_for_motion():
    main, sub = pick_streams([
        StreamProfile(token="a", rtsp_url="rtsp://x/sub", width=704, height=576),
        StreamProfile(token="b", rtsp_url="rtsp://x/main", width=2592, height=1944),
    ])
    assert main.rtsp_url == "rtsp://x/main"     # record the detail
    assert sub.rtsp_url == "rtsp://x/sub"       # motion + live stay cheap


def test_single_profile_camera_uses_it_for_both():
    only = StreamProfile(token="a", rtsp_url="rtsp://x/only", width=1280, height=720)
    main, sub = pick_streams([only])
    assert main is only and sub is only


def test_profiles_without_a_url_are_not_offered():
    main, sub = pick_streams([StreamProfile(token="a", width=1920, height=1080)])
    assert main is None and sub is None


# --- the recorder bundle ---------------------------------------------------- #

def test_onvif_ships_inside_the_recorder_zipapp():
    """The recorder is a dependency-free zipapp: a module that isn't bundled
    simply isn't there on the user's machine, and the failure is silent."""
    import io, zipfile
    from alibi.alibi_api import _build_recorder_zipapp
    z = zipfile.ZipFile(io.BytesIO(_build_recorder_zipapp("https://x", "CODE")))
    assert "onvif.py" in z.namelist()
    assert "bridge_agent.py" in z.namelist()


def test_scan_survives_a_camera_that_cannot_be_reached():
    # The flat-layout import plus a dead camera must not break the whole scan.
    from alibi.cameras.bridge_agent import onvif_stream_urls
    assert onvif_stream_urls("http://192.0.2.1/onvif/device_service", "u", "p") == ("", "", "")
