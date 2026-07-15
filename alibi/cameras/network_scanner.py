"""
Network Camera Scanner — multi-strategy LAN camera discovery.

Runs several detection methods and merges results per host, then scores a
confidence + is_camera verdict for each:

1. ONVIF WS-Discovery  (multicast UDP 239.255.255.250:3702)  -> ONVIF NVTs
2. mDNS / Bonjour       (_onvif._tcp, _rtsp._tcp, _axis-video._tcp, ...) -> cams that advertise
3. Subnet sweep         (TCP connect to common camera ports)  -> everything, incl. locked-down cams
4. RTSP OPTIONS probe   (confirms a host actually speaks RTSP + grabs Server banner)
5. MAC/OUI fingerprint  (ARP table -> vendor)                 -> brand even without ONVIF

Kept synchronous (ThreadPoolExecutor) to match the existing architecture and the
endpoint that calls it. zeroconf (mDNS) is optional and degrades gracefully.

Public contract (unchanged, relied on by the API + console):
    get_network_scanner() -> NetworkScanner
    scanner.scan_all(timeout, verify) -> List[DiscoveredCamera]
    scanner.is_scanning / scanner.progress
    DiscoveredCamera.to_dict()
"""

import ipaddress
import re
import socket
import struct
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from alibi.cameras.oui_prefixes import vendor_for_mac

# Ports commonly exposed by IP cameras / NVRs.
# 554/8554 RTSP, 80/8000/8080/8899 HTTP+ONVIF, 88 Reolink, 443 TLS,
# 34567 Dahua/XM, 37777 Dahua.
CAMERA_PORTS = (554, 8554, 80, 8000, 8080, 8899, 88, 443, 34567, 37777)
RTSP_PORTS = (554, 8554)

# mDNS service types that cameras advertise.
MDNS_TYPES = (
    "_onvif._tcp.local.",
    "_rtsp._tcp.local.",
    "_axis-video._tcp.local.",
    "_amcrest._tcp.local.",
    "_http._tcp.local.",
)

# Common RTSP paths tried during optional cv2 verification.
RTSP_PATHS = [
    "/stream1", "/live", "/cam/realmonitor?channel=1&subtype=0", "/h264",
    "/Streaming/Channels/101", "/live/ch00_1", "/live.sdp", "/videoMain", "/11",
]


@dataclass
class DiscoveredCamera:
    """A camera candidate found on the network."""
    ip: str
    port: int = 554
    source_type: str = "rtsp"           # "onvif" | "rtsp" | "mdns"
    rtsp_url: str = ""
    name: str = ""
    manufacturer: str = ""              # from ONVIF scopes or OUI vendor
    model: str = ""
    resolution: str = ""
    discovery_method: str = ""          # primary method (back-compat)
    already_registered: bool = False
    # Richer signal from the multi-strategy merge:
    vendor: str = ""                    # OUI-fingerprinted vendor
    mac: str = ""
    open_ports: List[int] = field(default_factory=list)
    rtsp_confirmed: bool = False        # spoke RTSP to an OPTIONS probe
    rtsp_banner: str = ""
    onvif_xaddr: str = ""
    found_by: Set[str] = field(default_factory=set)
    confidence: float = 0.0
    is_camera: bool = False

    def score(self) -> None:
        """Compute confidence + is_camera from the evidence collected."""
        c = 0.0
        if "onvif" in self.found_by:
            c += 0.6                     # ONVIF NVT = almost certainly a camera
        if "mdns" in self.found_by:
            c += 0.5
        if self.rtsp_confirmed:
            c += 0.4
        if self.vendor:                  # known camera-vendor OUI
            c += 0.3
        if any(p in self.open_ports for p in RTSP_PORTS):
            c += 0.2
        self.confidence = round(min(c, 1.0), 2)
        self.is_camera = bool(
            self.confidence >= 0.5 or self.onvif_xaddr or self.rtsp_confirmed
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ip": self.ip,
            "port": self.port,
            "source_type": self.source_type,
            "rtsp_url": self.rtsp_url,
            "name": self.name,
            "manufacturer": self.manufacturer or self.vendor,
            "model": self.model,
            "resolution": self.resolution,
            "discovery_method": self.discovery_method,
            "already_registered": self.already_registered,
            "vendor": self.vendor,
            "mac": self.mac,
            "open_ports": self.open_ports,
            "rtsp_confirmed": self.rtsp_confirmed,
            "confidence": self.confidence,
            "is_camera": self.is_camera,
            "found_by": sorted(self.found_by),
        }


# --------------------------------------------------------------------------- #
# Pure helpers (unit-testable without a network)
# --------------------------------------------------------------------------- #

def parse_rtsp_options(text: str) -> Tuple[bool, Optional[str]]:
    """Parse an RTSP OPTIONS response: return (speaks_rtsp, server_banner).

    ANY response beginning with "RTSP/" proves an RTSP server — including a
    401 Unauthorized, which many cameras (e.g. Dahua) return to an
    unauthenticated OPTIONS. Only RTSP servers speak the RTSP/ status line;
    HTTP servers answer "HTTP/..".
    """
    if not text:
        return False, None
    alive = text.startswith("RTSP/")
    m = re.search(r"Server:\s*(.+)", text)
    banner = m.group(1).strip() if m else None
    return alive, banner


def get_local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def get_local_subnet() -> str:
    return str(ipaddress.IPv4Network(f"{get_local_ip()}/24", strict=False))


def _normalise_mac(mac: str) -> str:
    """Zero-pad each octet — macOS `arp` prints '0:c:43' not '00:0c:43'."""
    parts = mac.split(":")
    if len(parts) == 6:
        return ":".join(p.zfill(2) for p in parts).lower()
    return mac.lower()


def _read_arp_table() -> Dict[str, str]:
    """Map ip -> mac from the kernel ARP cache.

    Linux: /proc/net/arp. macOS/BSD: fall back to the `arp -a` command (there is
    no /proc there), so vendor fingerprinting works when the bridge runs on a Mac.
    """
    table: Dict[str, str] = {}
    try:  # Linux
        with open("/proc/net/arp") as fh:
            next(fh)  # header
            for line in fh:
                parts = line.split()
                if len(parts) >= 4 and parts[3] != "00:00:00:00:00:00":
                    table[parts[0]] = parts[3].lower()
        if table:
            return table
    except Exception:
        pass
    try:  # macOS / BSD
        import subprocess
        out = subprocess.run(["arp", "-a"], capture_output=True, text=True, timeout=5).stdout
        for line in out.splitlines():
            m = re.search(r"\(([\d.]+)\) at ([0-9a-fA-F:]+)", line)
            if m and m.group(2).lower() != "incomplete":
                table[m.group(1)] = _normalise_mac(m.group(2))
    except Exception:
        pass
    return table


class NetworkScanner:
    """Discovers cameras on the local network via several strategies."""

    def __init__(self):
        self._scanning = False
        self._progress = {"status": "idle", "found": 0, "scanned": 0, "total": 0}

    @property
    def is_scanning(self) -> bool:
        return self._scanning

    @property
    def progress(self) -> Dict:
        return dict(self._progress)

    # --- Strategy 1: ONVIF WS-Discovery ---------------------------------- #

    def scan_onvif(self, timeout: float = 5.0) -> Dict[str, dict]:
        """Multicast Probe; return {ip: {xaddr, name, model}} for responders."""
        found: Dict[str, dict] = {}
        probe = f"""<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
 xmlns:wsa="http://schemas.xmlsoap.org/ws/2004/08/addressing"
 xmlns:wsd="http://schemas.xmlsoap.org/ws/2005/04/discovery"
 xmlns:dn="http://www.onvif.org/ver10/network/wsdl">
 <soap:Header>
  <wsa:Action>http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</wsa:Action>
  <wsa:MessageID>urn:uuid:{uuid.uuid4()}</wsa:MessageID>
  <wsa:To>urn:schemas-xmlsoap-org:ws:2005:04:discovery</wsa:To>
 </soap:Header>
 <soap:Body><wsd:Probe><wsd:Types>dn:NetworkVideoTransmitter</wsd:Types></wsd:Probe></soap:Body>
</soap:Envelope>"""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
            sock.settimeout(timeout)
            mreq = struct.pack("4sl", socket.inet_aton("239.255.255.250"), socket.INADDR_ANY)
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
            for _ in range(2):
                sock.sendto(probe.encode(), ("239.255.255.250", 3702))
                time.sleep(0.2)
            seen: Set[str] = set()
            while True:
                try:
                    data, addr = sock.recvfrom(65535)
                except socket.timeout:
                    break
                ip = addr[0]
                if ip in seen:
                    continue
                seen.add(ip)
                found[ip] = self._parse_onvif_scopes(data.decode(errors="ignore"))
            sock.close()
        except Exception as e:
            print(f"[NetworkScanner] ONVIF scan error: {e}")
        return found

    @staticmethod
    def _parse_onvif_scopes(xml_text: str) -> dict:
        info: dict = {}
        m = re.search(r"XAddrs>([^<]+)<", xml_text)
        if m:
            info["xaddr"] = m.group(1).split()[0]
        for k, v in re.findall(r"onvif://www\.onvif\.org/(\w+)/([^\s<]+)", xml_text):
            if k in ("name", "hardware", "manufacturer"):
                info[k] = v.replace("%20", " ")
        return info

    # --- Strategy 3: subnet sweep (multi-port) --------------------------- #

    def subnet_sweep(
        self, subnet: Optional[str] = None, ports=CAMERA_PORTS,
        timeout: float = 1.0, max_workers: int = 100,
    ) -> Dict[str, List[int]]:
        """TCP connect scan across all camera ports. Return {ip: [open_ports]}."""
        subnet = subnet or get_local_subnet()
        network = ipaddress.IPv4Network(subnet, strict=False)
        local_ip = get_local_ip()
        targets = [(str(ip), p) for ip in network.hosts()
                   if str(ip) != local_ip for p in ports]

        found: Dict[str, List[int]] = {}
        self._progress["total"] = len(targets)
        self._progress["scanned"] = 0

        def _check(ip: str, port: int) -> Optional[Tuple[str, int]]:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(timeout)
                    if s.connect_ex((ip, port)) == 0:
                        return (ip, port)
            except Exception:
                pass
            return None

        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futures = [ex.submit(_check, ip, p) for ip, p in targets]
            for fut in as_completed(futures):
                self._progress["scanned"] += 1
                res = fut.result()
                if res:
                    ip, port = res
                    found.setdefault(ip, []).append(port)
                    self._progress["found"] = len(found)
        for ip in found:
            found[ip].sort()
        return found

    # --- Strategy 4: RTSP OPTIONS probe ---------------------------------- #

    def rtsp_probe(self, ip: str, port: int = 554, timeout: float = 2.5) -> Tuple[bool, Optional[str]]:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(timeout)
                s.connect((ip, port))
                s.sendall(
                    f"OPTIONS rtsp://{ip}:{port}/ RTSP/1.0\r\n"
                    f"CSeq: 1\r\nUser-Agent: Vantage-Scanner\r\n\r\n".encode()
                )
                data = s.recv(2048)
            return parse_rtsp_options(data.decode(errors="ignore"))
        except Exception:
            return False, None

    # --- Strategy 2: mDNS (optional) ------------------------------------- #

    def scan_mdns(self, timeout: float = 3.0) -> Dict[str, dict]:
        found: Dict[str, dict] = {}
        try:
            from zeroconf import Zeroconf, ServiceBrowser
        except ImportError:
            print("[NetworkScanner] zeroconf not installed, skipping mDNS")
            return found

        class Listener:
            def add_service(self, zc, stype, name):
                info = zc.get_service_info(stype, name)
                if info and info.addresses:
                    ip = socket.inet_ntoa(info.addresses[0])
                    found[ip] = {"name": name.split(".")[0]}

            def remove_service(self, *a):
                pass

            def update_service(self, *a):
                pass

        try:
            zc = Zeroconf()
            for stype in MDNS_TYPES:
                ServiceBrowser(zc, stype, Listener())
            time.sleep(timeout)
            zc.close()
        except Exception as e:
            print(f"[NetworkScanner] mDNS scan error: {e}")
        return found

    # --- optional cv2 frame verification --------------------------------- #

    def scan_rtsp_verify(self, cameras: List[DiscoveredCamera], timeout: float = 3.0):
        try:
            import cv2
        except ImportError:
            return
        for cam in cameras:
            for path in RTSP_PATHS:
                url = f"rtsp://{cam.ip}:{cam.port}{path}"
                try:
                    cap = cv2.VideoCapture(url)
                    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                    if cap.isOpened():
                        ret, frame = cap.read()
                        if ret and frame is not None:
                            h, w = frame.shape[:2]
                            cam.rtsp_url = url
                            cam.resolution = f"{w}x{h}"
                            cap.release()
                            break
                    cap.release()
                except Exception:
                    pass

    # --- Orchestrator ---------------------------------------------------- #

    def scan_all(self, timeout: float = 15.0, verify: bool = False) -> List[DiscoveredCamera]:
        self._scanning = True
        self._progress = {"status": "scanning", "found": 0, "scanned": 0, "total": 0}
        cams: Dict[str, DiscoveredCamera] = {}

        def _get(ip: str) -> DiscoveredCamera:
            return cams.setdefault(ip, DiscoveredCamera(ip=ip))

        try:
            # 1. ONVIF WS-Discovery
            self._progress["status"] = "onvif_discovery"
            for ip, info in self.scan_onvif(timeout=min(timeout / 3, 5.0)).items():
                cam = _get(ip)
                cam.found_by.add("onvif")
                cam.discovery_method = cam.discovery_method or "onvif"
                cam.source_type = "onvif"
                cam.onvif_xaddr = info.get("xaddr", "")
                cam.name = cam.name or info.get("name", "")
                cam.model = cam.model or info.get("hardware", "")
                cam.manufacturer = cam.manufacturer or info.get("manufacturer", "")

            # 2. mDNS
            self._progress["status"] = "mdns_discovery"
            for ip, info in self.scan_mdns(timeout=min(timeout / 4, 3.0)).items():
                cam = _get(ip)
                cam.found_by.add("mdns")
                cam.discovery_method = cam.discovery_method or "mdns"
                cam.name = cam.name or info.get("name", "")

            # 3. Subnet sweep (all camera ports)
            self._progress["status"] = "rtsp_scanning"
            for ip, ports in self.subnet_sweep(timeout=min(timeout / 4, 1.5)).items():
                cam = _get(ip)
                cam.found_by.add("sweep")
                cam.discovery_method = cam.discovery_method or "rtsp_scan"
                cam.open_ports = sorted(set(cam.open_ports) | set(ports))

            # 4. RTSP OPTIONS confirmation
            self._progress["status"] = "rtsp_confirm"
            for cam in cams.values():
                rtsp_port = next((p for p in RTSP_PORTS if p in cam.open_ports), None)
                if rtsp_port is None and cam.onvif_xaddr:
                    rtsp_port = 554
                if rtsp_port:
                    cam.rtsp_confirmed, cam.rtsp_banner = self.rtsp_probe(cam.ip, rtsp_port)
                    cam.port = rtsp_port
                    if not cam.rtsp_url:
                        cam.rtsp_url = f"rtsp://{cam.ip}:{rtsp_port}/stream1"

            # 5. MAC / vendor fingerprint + score
            arp = _read_arp_table()
            for ip, cam in cams.items():
                cam.mac = arp.get(ip, "")
                cam.vendor = vendor_for_mac(cam.mac) or ""
                if cam.vendor and not cam.manufacturer:
                    cam.manufacturer = cam.vendor
                if not cam.name:
                    cam.name = f"{cam.vendor or 'Camera'} ({ip})"
                cam.score()

            if verify:
                self._progress["status"] = "verifying"
                self.scan_rtsp_verify([c for c in cams.values() if not c.resolution])

            self._mark_registered(list(cams.values()))
            self._progress["status"] = "complete"
            self._progress["found"] = len(cams)
        except Exception as e:
            print(f"[NetworkScanner] Scan error: {e}")
            self._progress["status"] = f"error: {e}"
        finally:
            self._scanning = False

        # Cameras first, then by confidence, then IP.
        return sorted(
            cams.values(),
            key=lambda c: (not c.is_camera, -c.confidence, ipaddress.ip_address(c.ip)),
        )

    def _mark_registered(self, cameras: List[DiscoveredCamera]):
        try:
            from alibi.cameras.camera_store import get_camera_store
            registered_ips = set()
            for cam in get_camera_store().list_all():
                if cam.source and "://" in cam.source:
                    m = re.search(r"://(?:[^@/]+@)?([^:/]+)", cam.source)
                    if m:
                        registered_ips.add(m.group(1))
            for cam in cameras:
                cam.already_registered = cam.ip in registered_ips
        except Exception:
            pass


_scanner: Optional[NetworkScanner] = None


def get_network_scanner() -> NetworkScanner:
    global _scanner
    if _scanner is None:
        _scanner = NetworkScanner()
    return _scanner
