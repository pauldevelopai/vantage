"""
ONVIF — ask a camera for its own stream URL instead of guessing.

Today Vantage guesses RTSP paths per vendor ("/cam/realmonitor?channel=1&subtype=0"
for Dahua, "/Streaming/Channels/101" for Hikvision, ...). That guessing is why
onboarding is fiddly: a wrong path looks identical to a wrong password. Nearly
every IP camera made in the last decade speaks ONVIF, which answers the question
directly — GetProfiles lists what the camera can send, GetStreamUri gives the exact
URL for each, main and sub stream included.

Two capabilities, both pure stdlib so this can ship inside the zipapp recorder
(which carries no dependencies by design):

  discover()        WS-Discovery: a UDP multicast probe; ONVIF devices answer with
                    the URL of their device service.
  stream_profiles() GetProfiles + GetStreamUri over SOAP: the camera's real stream
                    URLs, with resolution, so we can pick main vs sub honestly.

Authentication is WS-Security UsernameToken with a password digest:
    digest = Base64(SHA1(nonce + created + password))
so the password itself never crosses the wire.

Everything is dependency-injected (the UDP socket and the SOAP transport) so the
parsing and selection logic is unit-testable without a camera on the desk.
"""

import base64
import hashlib
import re
import socket
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple
from xml.etree import ElementTree as ET

WS_DISCOVERY_ADDR = "239.255.255.250"
WS_DISCOVERY_PORT = 3702

_NS = {
    "s": "http://www.w3.org/2003/05/soap-envelope",
    "d": "http://schemas.xmlsoap.org/ws/2005/04/discovery",
    "a": "http://schemas.xmlsoap.org/ws/2004/08/addressing",
    "trt": "http://www.onvif.org/ver10/media/wsdl",
    "tt": "http://www.onvif.org/ver10/schema",
}

_PROBE = """<?xml version="1.0" encoding="UTF-8"?>
<e:Envelope xmlns:e="http://www.w3.org/2003/05/soap-envelope"
            xmlns:w="http://schemas.xmlsoap.org/ws/2004/08/addressing"
            xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery"
            xmlns:dn="http://www.onvif.org/ver10/network/wsdl">
  <e:Header>
    <w:MessageID>uuid:{mid}</w:MessageID>
    <w:To e:mustUnderstand="true">urn:schemas-xmlsoap-org:ws:2005:04:discovery</w:To>
    <w:Action e:mustUnderstand="true">http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</w:Action>
  </e:Header>
  <e:Body>
    <d:Probe><d:Types>dn:NetworkVideoTransmitter</d:Types></d:Probe>
  </e:Body>
</e:Envelope>"""


@dataclass
class StreamProfile:
    """One thing the camera can actually send us."""
    token: str
    name: str = ""
    rtsp_url: str = ""
    width: int = 0
    height: int = 0
    encoding: str = ""              # H264 | H265 | ...
    fps: int = 0

    @property
    def pixels(self) -> int:
        return self.width * self.height

    def to_dict(self) -> Dict[str, Any]:
        return {"token": self.token, "name": self.name, "rtsp_url": self.rtsp_url,
                "width": self.width, "height": self.height,
                "encoding": self.encoding, "fps": self.fps}


@dataclass
class OnvifDevice:
    """An ONVIF device that answered a discovery probe."""
    ip: str
    xaddr: str                      # URL of its device service
    scopes: List[str] = field(default_factory=list)
    manufacturer: str = ""
    model: str = ""
    name: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"ip": self.ip, "xaddr": self.xaddr, "manufacturer": self.manufacturer,
                "model": self.model, "name": self.name, "scopes": self.scopes}


# --------------------------------------------------------------------------- #
# WS-Discovery
# --------------------------------------------------------------------------- #

def _ip_from_xaddr(xaddr: str) -> str:
    m = re.search(r"https?://\[?([^\]/:]+)\]?", xaddr or "")
    return m.group(1) if m else ""


def parse_probe_matches(xml_text: str) -> List[OnvifDevice]:
    """Turn one ProbeMatch response into devices. Pure — the parsing is the part
    worth testing."""
    out: List[OnvifDevice] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return out
    for match in root.iter():
        if not match.tag.endswith("ProbeMatch"):
            continue
        xaddrs = scopes_text = ""
        for child in match:
            if child.tag.endswith("XAddrs"):
                xaddrs = (child.text or "").strip()
            elif child.tag.endswith("Scopes"):
                scopes_text = (child.text or "").strip()
        if not xaddrs:
            continue
        xaddr = xaddrs.split()[0]
        scopes = scopes_text.split()
        dev = OnvifDevice(ip=_ip_from_xaddr(xaddr), xaddr=xaddr, scopes=scopes)
        for s in scopes:
            # onvif://www.onvif.org/name/Dahua  ->  ("name", "Dahua")
            m = re.search(r"onvif://www\.onvif\.org/(\w+)/(.+)$", s)
            if not m:
                continue
            key, val = m.group(1).lower(), _unquote(m.group(2))
            if key == "hardware":
                dev.model = val
            elif key == "name":
                dev.name = val
                if not dev.manufacturer:
                    dev.manufacturer = val.split()[0]
        out.append(dev)
    return out


def _unquote(s: str) -> str:
    try:
        from urllib.parse import unquote
        return unquote(s).replace("_", " ").strip()
    except Exception:
        return s


def discover(timeout: float = 4.0, sender: Optional[Callable] = None) -> List[OnvifDevice]:
    """Multicast a WS-Discovery probe and collect the cameras that answer.

    `sender(probe_xml, timeout) -> list[str]` is injectable so tests never touch
    the network.
    """
    probe = _PROBE.format(mid=uuid.uuid4())
    if sender is not None:
        replies = sender(probe, timeout)
    else:
        replies = _multicast(probe, timeout)

    devices: Dict[str, OnvifDevice] = {}
    for r in replies or []:
        for dev in parse_probe_matches(r):
            if dev.ip and dev.ip not in devices:      # first answer per device wins
                devices[dev.ip] = dev
    return sorted(devices.values(), key=lambda d: d.ip)


def _multicast(probe: str, timeout: float) -> List[str]:  # pragma: no cover - needs a LAN
    replies: List[str] = []
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        sock.settimeout(timeout)
        sock.sendto(probe.encode(), (WS_DISCOVERY_ADDR, WS_DISCOVERY_PORT))
        deadline = _now_monotonic() + timeout
        while _now_monotonic() < deadline:
            try:
                data, _ = sock.recvfrom(65535)
                replies.append(data.decode("utf-8", "replace"))
            except socket.timeout:
                break
            except OSError:
                break
    except OSError:
        pass
    finally:
        sock.close()
    return replies


def _now_monotonic() -> float:
    import time
    return time.monotonic()


# --------------------------------------------------------------------------- #
# SOAP: GetProfiles / GetStreamUri
# --------------------------------------------------------------------------- #

def ws_security_header(username: str, password: str,
                       nonce: Optional[bytes] = None,
                       created: Optional[str] = None) -> str:
    """WS-Security UsernameToken with a password digest.

    digest = Base64(SHA1(nonce + created + password)) — so the password itself is
    never sent. nonce/created are injectable to make this deterministic in tests.
    """
    nonce = nonce if nonce is not None else uuid.uuid4().bytes
    created = created or datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    digest = base64.b64encode(
        hashlib.sha1(nonce + created.encode() + password.encode()).digest()
    ).decode()
    return (
        '<s:Header><Security s:mustUnderstand="1" '
        'xmlns="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd">'
        f"<UsernameToken><Username>{_esc(username)}</Username>"
        f'<Password Type="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-username-token-profile-1.0#PasswordDigest">{digest}</Password>'
        f'<Nonce EncodingType="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-soap-message-security-1.0#Base64Binary">{base64.b64encode(nonce).decode()}</Nonce>'
        f"<Created xmlns=\"http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd\">{created}</Created>"
        "</UsernameToken></Security></s:Header>"
    )


def _esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _envelope(header: str, body: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" '
        'xmlns:trt="http://www.onvif.org/ver10/media/wsdl" '
        'xmlns:tt="http://www.onvif.org/ver10/schema">'
        f"{header}<s:Body>{body}</s:Body></s:Envelope>"
    )


def parse_profiles(xml_text: str) -> List[StreamProfile]:
    """GetProfilesResponse -> profiles. Pure."""
    profiles: List[StreamProfile] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return profiles
    for node in root.iter():
        if not node.tag.endswith("Profiles"):
            continue
        token = node.get("token") or ""
        if not token:
            continue
        p = StreamProfile(token=token)
        for child in node.iter():
            tag = child.tag.split("}")[-1]
            if tag == "Name" and not p.name:
                p.name = (child.text or "").strip()
            elif tag == "Encoding" and not p.encoding:
                p.encoding = (child.text or "").strip()
            elif tag == "Width" and not p.width:
                p.width = _int(child.text)
            elif tag == "Height" and not p.height:
                p.height = _int(child.text)
            elif tag == "FrameRateLimit" and not p.fps:
                p.fps = _int(child.text)
        profiles.append(p)
    return profiles


def parse_stream_uri(xml_text: str) -> str:
    """GetStreamUriResponse -> the RTSP URL. Pure."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return ""
    for node in root.iter():
        if node.tag.endswith("Uri") and (node.text or "").strip().lower().startswith("rtsp://"):
            return node.text.strip()
    return ""


def _int(text) -> int:
    try:
        return int(float((text or "0").strip()))
    except (TypeError, ValueError):
        return 0


def with_credentials(rtsp_url: str, username: str, password: str) -> str:
    """Put credentials into an RTSP URL. Cameras hand back a bare URL; our
    recorder needs one it can actually open."""
    if not rtsp_url or not username:
        return rtsp_url
    if "@" in rtsp_url.split("//", 1)[-1].split("/", 1)[0]:
        return rtsp_url                                    # already has them
    from urllib.parse import quote
    return rtsp_url.replace("rtsp://", f"rtsp://{quote(username, safe='')}:{quote(password, safe='')}@", 1)


def stream_profiles(xaddr: str, username: str = "", password: str = "",
                    send: Optional[Callable] = None,
                    timeout: float = 6.0) -> List[StreamProfile]:
    """Ask a camera what it can send, and for the URL of each.

    `send(url, xml, timeout) -> str` is injectable; the default posts SOAP.
    """
    media_url = _media_url(xaddr)
    poster = send or _post
    header = ws_security_header(username, password) if username else ""

    try:
        resp = poster(media_url, _envelope(header, "<trt:GetProfiles/>"), timeout)
    except Exception:
        return []
    profiles = parse_profiles(resp or "")

    for p in profiles:
        body = (f"<trt:GetStreamUri><trt:StreamSetup>"
                f"<tt:Stream>RTP-Unicast</tt:Stream>"
                f"<tt:Transport><tt:Protocol>RTSP</tt:Protocol></tt:Transport>"
                f"</trt:StreamSetup><trt:ProfileToken>{_esc(p.token)}</trt:ProfileToken>"
                f"</trt:GetStreamUri>")
        hdr = ws_security_header(username, password) if username else ""
        try:
            r = poster(media_url, _envelope(hdr, body), timeout)
        except Exception:
            continue
        uri = parse_stream_uri(r or "")
        if uri:
            p.rtsp_url = with_credentials(uri, username, password)
    return profiles


def _media_url(xaddr: str) -> str:
    """The media service usually lives beside the device service."""
    if not xaddr:
        return ""
    return re.sub(r"/onvif/device_service/?$", "/onvif/media_service", xaddr) \
        if "device_service" in xaddr else xaddr


def _post(url: str, xml: str, timeout: float) -> str:  # pragma: no cover - network
    from urllib import request
    req = request.Request(url, data=xml.encode(),
                          headers={"Content-Type": "application/soap+xml; charset=utf-8"})
    with request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


# --------------------------------------------------------------------------- #
# Choosing streams
# --------------------------------------------------------------------------- #

def pick_streams(profiles: List[StreamProfile]) -> Tuple[Optional[StreamProfile], Optional[StreamProfile]]:
    """(main, sub): the biggest for recording, a smaller one for motion + live.

    Vantage records the main stream and runs motion/live off the sub — that split
    is what keeps the recorder cheap. With one profile, it's both.
    """
    usable = [p for p in profiles if p.rtsp_url]
    if not usable:
        return None, None
    by_size = sorted(usable, key=lambda p: p.pixels, reverse=True)
    main = by_size[0]
    sub = by_size[-1] if len(by_size) > 1 else main
    return main, sub
