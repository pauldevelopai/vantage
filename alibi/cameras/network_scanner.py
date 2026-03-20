"""
Network Camera Scanner

Discovers IP cameras on the local network using:
1. WS-Discovery (ONVIF standard multicast probe)
2. RTSP port scanning (TCP 554)
3. mDNS/Bonjour service discovery (optional, requires zeroconf)

Designed for minimal admin: scan → one-click add.
"""

import asyncio
import socket
import struct
import uuid
import re
import ipaddress
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Set
from datetime import datetime


@dataclass
class DiscoveredCamera:
    """A camera found on the network."""
    ip: str
    port: int = 554
    source_type: str = "rtsp"           # "onvif" | "rtsp" | "mdns"
    rtsp_url: str = ""
    name: str = ""
    manufacturer: str = ""
    model: str = ""
    resolution: str = ""
    discovery_method: str = ""          # "onvif" | "rtsp_scan" | "mdns"
    already_registered: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ip": self.ip,
            "port": self.port,
            "source_type": self.source_type,
            "rtsp_url": self.rtsp_url,
            "name": self.name,
            "manufacturer": self.manufacturer,
            "model": self.model,
            "resolution": self.resolution,
            "discovery_method": self.discovery_method,
            "already_registered": self.already_registered,
        }


# Common RTSP paths used by various camera manufacturers
RTSP_PATHS = [
    "",
    "/stream1",
    "/live",
    "/cam/realmonitor?channel=1&subtype=0",
    "/h264",
    "/video1",
    "/Streaming/Channels/101",       # Hikvision
    "/live/ch00_1",                   # Dahua
    "/MediaInput/h264",              # Sony
    "/live.sdp",                     # Axis
    "/videoMain",                    # Foscam
    "/11",                           # Samsung
]


def get_local_ip() -> str:
    """Get the local IP address of this machine."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def get_local_subnet() -> str:
    """Get the local /24 subnet."""
    local_ip = get_local_ip()
    network = ipaddress.IPv4Network(f"{local_ip}/24", strict=False)
    return str(network)


class NetworkScanner:
    """
    Discovers cameras on the local network.

    Uses multiple discovery methods for maximum coverage:
    - WS-Discovery multicast (ONVIF cameras)
    - RTSP port scan (any camera with RTSP)
    - mDNS/Bonjour (consumer cameras)
    """

    def __init__(self):
        self._scanning = False
        self._progress = {"status": "idle", "found": 0, "scanned": 0, "total": 0}

    @property
    def is_scanning(self) -> bool:
        return self._scanning

    @property
    def progress(self) -> Dict:
        return dict(self._progress)

    def scan_onvif(self, timeout: float = 5.0) -> List[DiscoveredCamera]:
        """
        Discover cameras using WS-Discovery multicast probe (ONVIF standard).

        Sends a SOAP multicast to 239.255.255.250:3702 and listens for responses.
        Most IP cameras (Hikvision, Dahua, Axis, etc.) respond to this.
        """
        cameras = []

        # WS-Discovery SOAP probe for network video devices
        probe_id = str(uuid.uuid4())
        probe_message = f"""<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
               xmlns:wsa="http://schemas.xmlsoap.org/ws/2004/08/addressing"
               xmlns:wsd="http://schemas.xmlsoap.org/ws/2005/04/discovery"
               xmlns:dn="http://www.onvif.org/ver10/network/wsdl">
  <soap:Header>
    <wsa:Action>http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</wsa:Action>
    <wsa:MessageID>urn:uuid:{probe_id}</wsa:MessageID>
    <wsa:To>urn:schemas-xmlsoap-org:ws:2005:04:discovery</wsa:To>
  </soap:Header>
  <soap:Body>
    <wsd:Probe>
      <wsd:Types>dn:NetworkVideoTransmitter</wsd:Types>
    </wsd:Probe>
  </soap:Body>
</soap:Envelope>"""

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.settimeout(timeout)

            # Join multicast group
            mreq = struct.pack(
                "4sl",
                socket.inet_aton("239.255.255.250"),
                socket.INADDR_ANY,
            )
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)

            # Send probe
            sock.sendto(
                probe_message.encode("utf-8"),
                ("239.255.255.250", 3702),
            )

            print(f"[NetworkScanner] ONVIF WS-Discovery probe sent, waiting {timeout}s...")

            seen_ips: Set[str] = set()

            while True:
                try:
                    data, addr = sock.recvfrom(65535)
                    ip = addr[0]

                    if ip in seen_ips:
                        continue
                    seen_ips.add(ip)

                    # Parse response for device info
                    response_text = data.decode("utf-8", errors="ignore")
                    camera = self._parse_onvif_response(ip, response_text)
                    if camera:
                        cameras.append(camera)
                        print(f"[NetworkScanner] ONVIF found: {ip} - {camera.name or camera.manufacturer or 'Unknown'}")

                except socket.timeout:
                    break

            sock.close()

        except Exception as e:
            print(f"[NetworkScanner] ONVIF scan error: {e}")

        return cameras

    def _parse_onvif_response(self, ip: str, xml_text: str) -> Optional[DiscoveredCamera]:
        """Extract camera info from WS-Discovery response XML."""
        camera = DiscoveredCamera(
            ip=ip,
            port=80,
            source_type="onvif",
            discovery_method="onvif",
        )

        # Extract XAddrs (service URL)
        xaddrs_match = re.search(r"<[^>]*XAddrs[^>]*>([^<]+)</", xml_text)
        if xaddrs_match:
            xaddrs = xaddrs_match.group(1).strip()
            # Extract port from URL
            port_match = re.search(r":(\d+)/", xaddrs)
            if port_match:
                camera.port = int(port_match.group(1))

        # Extract scopes (contains manufacturer, model info)
        scopes_match = re.search(r"<[^>]*Scopes[^>]*>([^<]+)</", xml_text)
        if scopes_match:
            scopes = scopes_match.group(1).strip()
            # Parse ONVIF scopes
            for scope in scopes.split():
                if "hardware" in scope.lower():
                    camera.model = scope.split("/")[-1]
                elif "name" in scope.lower():
                    camera.name = scope.split("/")[-1].replace("%20", " ")
                elif "manufacturer" in scope.lower() or "mfr" in scope.lower():
                    camera.manufacturer = scope.split("/")[-1].replace("%20", " ")

        # Build default RTSP URL for ONVIF cameras
        camera.rtsp_url = f"rtsp://{ip}:{554}/stream1"

        if not camera.name:
            camera.name = f"ONVIF Camera ({ip})"

        return camera

    def scan_rtsp(self, subnet: Optional[str] = None, timeout: float = 1.5, max_workers: int = 50) -> List[DiscoveredCamera]:
        """
        Scan local subnet for open RTSP ports (TCP 554).

        Args:
            subnet: CIDR notation (e.g., "192.168.1.0/24"). Auto-detected if None.
            timeout: Connection timeout per host in seconds.
            max_workers: Max concurrent connections.
        """
        if subnet is None:
            subnet = get_local_subnet()

        network = ipaddress.IPv4Network(subnet, strict=False)
        local_ip = get_local_ip()
        hosts = [str(ip) for ip in network.hosts() if str(ip) != local_ip]

        cameras = []
        self._progress["total"] = len(hosts)
        self._progress["scanned"] = 0

        print(f"[NetworkScanner] RTSP scanning {len(hosts)} hosts on {subnet}...")

        def check_host(ip: str) -> Optional[DiscoveredCamera]:
            """Check if host has RTSP port open."""
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(timeout)
                result = sock.connect_ex((ip, 554))
                sock.close()

                if result == 0:
                    return DiscoveredCamera(
                        ip=ip,
                        port=554,
                        source_type="rtsp",
                        rtsp_url=f"rtsp://{ip}:554/stream1",
                        name=f"Camera ({ip})",
                        discovery_method="rtsp_scan",
                    )
            except Exception:
                pass
            return None

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(check_host, ip): ip for ip in hosts}

            for future in as_completed(futures):
                self._progress["scanned"] += 1
                try:
                    result = future.result()
                    if result:
                        cameras.append(result)
                        self._progress["found"] = len(cameras)
                        print(f"[NetworkScanner] RTSP found: {result.ip}:554")
                except Exception:
                    pass

        return cameras

    def scan_rtsp_verify(self, cameras: List[DiscoveredCamera], timeout: float = 3.0) -> List[DiscoveredCamera]:
        """
        Verify RTSP cameras by attempting to connect and trying common paths.
        Updates rtsp_url and resolution on each camera.
        """
        try:
            import cv2
        except ImportError:
            print("[NetworkScanner] OpenCV not available for RTSP verification")
            return cameras

        verified = []

        for camera in cameras:
            found = False
            for path in RTSP_PATHS:
                url = f"rtsp://{camera.ip}:{camera.port}{path}" if path.startswith("/") else f"rtsp://{camera.ip}:{camera.port}/{path}"

                try:
                    cap = cv2.VideoCapture(url)
                    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

                    if cap.isOpened():
                        ret, frame = cap.read()
                        if ret and frame is not None:
                            h, w = frame.shape[:2]
                            camera.rtsp_url = url
                            camera.resolution = f"{w}x{h}"
                            found = True
                            print(f"[NetworkScanner] Verified: {url} ({w}x{h})")
                        cap.release()
                        if found:
                            break
                    else:
                        cap.release()
                except Exception:
                    pass

            if found:
                verified.append(camera)

        return verified

    def scan_mdns(self, timeout: float = 3.0) -> List[DiscoveredCamera]:
        """
        Discover cameras via mDNS/Bonjour (requires zeroconf library).
        Looks for _rtsp._tcp services.
        """
        cameras = []

        try:
            from zeroconf import Zeroconf, ServiceBrowser

            class Listener:
                def __init__(self):
                    self.found = []

                def add_service(self, zc, service_type, name):
                    info = zc.get_service_info(service_type, name)
                    if info:
                        ip = socket.inet_ntoa(info.addresses[0]) if info.addresses else None
                        if ip:
                            self.found.append(DiscoveredCamera(
                                ip=ip,
                                port=info.port or 554,
                                source_type="rtsp",
                                rtsp_url=f"rtsp://{ip}:{info.port or 554}/",
                                name=name.replace("._rtsp._tcp.local.", ""),
                                discovery_method="mdns",
                            ))

                def remove_service(self, zc, service_type, name):
                    pass

                def update_service(self, zc, service_type, name):
                    pass

            zc = Zeroconf()
            listener = Listener()
            browser = ServiceBrowser(zc, "_rtsp._tcp.local.", listener)

            import time
            time.sleep(timeout)

            zc.close()
            cameras = listener.found
            print(f"[NetworkScanner] mDNS found {len(cameras)} cameras")

        except ImportError:
            print("[NetworkScanner] zeroconf not installed, skipping mDNS scan")
        except Exception as e:
            print(f"[NetworkScanner] mDNS scan error: {e}")

        return cameras

    def scan_all(self, timeout: float = 10.0, verify: bool = False) -> List[DiscoveredCamera]:
        """
        Run all discovery methods and return deduplicated results.

        Args:
            timeout: Total timeout for scanning
            verify: If True, verify RTSP connections by reading a frame (slower but more accurate)
        """
        self._scanning = True
        self._progress = {"status": "scanning", "found": 0, "scanned": 0, "total": 0}

        all_cameras: Dict[str, DiscoveredCamera] = {}

        try:
            # Phase 1: ONVIF discovery (fast, multicast)
            self._progress["status"] = "onvif_discovery"
            onvif_cameras = self.scan_onvif(timeout=min(timeout / 2, 5.0))
            for cam in onvif_cameras:
                all_cameras[cam.ip] = cam

            # Phase 2: RTSP port scan (covers non-ONVIF cameras)
            self._progress["status"] = "rtsp_scanning"
            rtsp_cameras = self.scan_rtsp(timeout=min(timeout / 4, 1.5))
            for cam in rtsp_cameras:
                if cam.ip not in all_cameras:
                    all_cameras[cam.ip] = cam

            # Phase 3: mDNS (bonus, if available)
            self._progress["status"] = "mdns_discovery"
            mdns_cameras = self.scan_mdns(timeout=min(timeout / 4, 3.0))
            for cam in mdns_cameras:
                if cam.ip not in all_cameras:
                    all_cameras[cam.ip] = cam

            # Phase 4: Optional RTSP verification
            if verify and all_cameras:
                self._progress["status"] = "verifying"
                unverified = [c for c in all_cameras.values() if not c.resolution]
                verified = self.scan_rtsp_verify(unverified)
                for cam in verified:
                    all_cameras[cam.ip] = cam

            # Mark already registered cameras
            self._mark_registered(list(all_cameras.values()))

            self._progress["status"] = "complete"
            self._progress["found"] = len(all_cameras)

        except Exception as e:
            print(f"[NetworkScanner] Scan error: {e}")
            self._progress["status"] = f"error: {e}"

        finally:
            self._scanning = False

        cameras = list(all_cameras.values())
        print(f"[NetworkScanner] Total discovered: {len(cameras)} cameras")
        return cameras

    def _mark_registered(self, cameras: List[DiscoveredCamera]):
        """Mark cameras that are already in the CameraStore."""
        try:
            from alibi.cameras.camera_store import get_camera_store

            store = get_camera_store()
            registered = store.list_all()
            registered_ips = set()

            for cam in registered:
                # Extract IP from source URL
                if cam.source and "://" in cam.source:
                    match = re.search(r"://([^:/]+)", cam.source)
                    if match:
                        registered_ips.add(match.group(1))

            for cam in cameras:
                cam.already_registered = cam.ip in registered_ips

        except Exception:
            pass


# Global singleton
_scanner: Optional[NetworkScanner] = None


def get_network_scanner() -> NetworkScanner:
    """Get the global NetworkScanner instance."""
    global _scanner
    if _scanner is None:
        _scanner = NetworkScanner()
    return _scanner
