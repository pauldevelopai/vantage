#!/usr/bin/env python3
"""
Vantage Bridge — runs on the network your cameras are on.

A cloud-hosted Vantage cannot see your local WiFi, so this small agent does the
looking: it connects OUTBOUND to Vantage, waits for a "scan" request from the
console, discovers cameras on the local network, and reports them back. No
inbound ports are opened on your network.

Self-contained: standard library + urllib only (no pip installs). Optional
`zeroconf` improves mDNS discovery if present.

Run:
    python3 vantage_bridge.py --pair AB12CD34
    # (VANTAGE_URL and the pairing code can also be injected by a personalized
    #  download from the Vantage console, so there's nothing to type.)

This file has NO Vantage imports on purpose, so it runs anywhere as one file.
"""

import argparse
import ipaddress
import json
import os
import re
import socket
import struct
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError

# --- Config (a personalized download overwrites these two constants) -------- #
VANTAGE_URL = os.environ.get("VANTAGE_URL", "https://vantage.developai.co.za")
PAIRING_CODE = os.environ.get("VANTAGE_PAIRING_CODE", "")
CRED_FILE = os.environ.get("VANTAGE_BRIDGE_CREDS", os.path.expanduser("~/.vantage_bridge.json"))
POLL_SECONDS = 4

CAMERA_PORTS = (554, 8554, 80, 8000, 8080, 8899, 88, 443, 34567, 37777)
# Ports that mark a general-purpose computer / NAS — a candidate recording PC:
# SSH, SMB, RDP, VNC, AFP, NetBIOS.
COMPUTER_PORTS = (22, 445, 3389, 5900, 548, 139)
RTSP_PORTS = (554, 8554)
SCAN_PORTS = tuple(sorted(set(CAMERA_PORTS + COMPUTER_PORTS)))

# Compact camera-vendor OUI seed (brand fingerprint from MAC).
CAMERA_OUI = {
    "00:0C:43": "Hikvision", "44:19:B6": "Hikvision", "4C:BD:8F": "Hikvision",
    "C0:56:E3": "Hikvision", "E0:50:8B": "Hikvision",
    "00:12:15": "Dahua", "3C:EF:8C": "Dahua", "90:02:A9": "Dahua", "E0:61:B2": "Dahua",
    "00:40:8C": "Axis", "AC:CC:8E": "Axis", "B8:A4:4F": "Axis",
    "EC:71:DB": "Reolink", "C4:D6:55": "Reolink", "9C:8E:CD": "Amcrest",
    "FC:EC:DA": "Ubiquiti", "24:5A:4C": "Ubiquiti",
    "00:1B:86": "Bosch", "00:09:18": "Hanwha", "00:02:D1": "Vivotek",
    "00:62:6E": "Foscam", "30:DE:4B": "TP-Link", "2C:AA:8E": "Wyze",
}


# --- HTTP (stdlib urllib; no requests dependency) --------------------------- #

def _http(method, path, body=None, headers=None, timeout=30):
    url = VANTAGE_URL.rstrip("/") + path
    data = json.dumps(body).encode() if body is not None else None
    req = urlrequest.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urlrequest.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode()
            return resp.status, (json.loads(raw) if raw else {})
    except HTTPError as e:
        return e.code, {}
    except (URLError, socket.timeout, Exception):
        return 0, {}


# --- credential persistence ------------------------------------------------- #

def load_creds():
    try:
        with open(CRED_FILE) as f:
            d = json.load(f)
        if d.get("bridge_id") and d.get("token"):
            return d
    except Exception:
        pass
    return None


def save_creds(creds):
    try:
        with open(CRED_FILE, "w") as f:
            json.dump(creds, f)
        os.chmod(CRED_FILE, 0o600)   # token is a secret
    except Exception as e:
        print(f"[bridge] could not save creds: {e}")


def register(code):
    """Redeem a pairing code -> {bridge_id, token}. Returns None on failure."""
    subnet = local_subnet()
    status, body = _http("POST", "/api/cameras/bridge/register",
                         {"code": code, "name": socket.gethostname(), "site_hint": subnet})
    if status == 200 and body.get("token"):
        save_creds(body)
        return body
    print(f"[bridge] pairing failed (status {status}). Is the code correct and unexpired?")
    return None


# --- scanning (self-contained; mirrors the server scanner's strategies) ----- #

def vendor_for_mac(mac):
    if not mac:
        return None
    return CAMERA_OUI.get(mac.upper().replace("-", ":")[:8])


def parse_rtsp_options(text):
    # Any "RTSP/" response proves an RTSP server, incl. a 401 (Dahua etc. answer
    # unauthenticated OPTIONS with 401). Only RTSP servers speak the RTSP/ line.
    if not text:
        return False, None
    alive = text.startswith("RTSP/")
    m = re.search(r"Server:\s*(.+)", text)
    return alive, (m.group(1).strip() if m else None)


def local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def local_subnet():
    return str(ipaddress.IPv4Network(f"{local_ip()}/24", strict=False))


def ws_discover(timeout=4.0):
    """ONVIF WS-Discovery multicast probe. Return {ip: {name, model}}."""
    found = {}
    probe = f"""<?xml version="1.0" encoding="utf-8"?>
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
 xmlns:a="http://schemas.xmlsoap.org/ws/2004/08/addressing"
 xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery"
 xmlns:dn="http://www.onvif.org/ver10/network/wsdl">
 <s:Header><a:Action>http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</a:Action>
 <a:MessageID>urn:uuid:{uuid.uuid4()}</a:MessageID>
 <a:To>urn:schemas-xmlsoap-org:ws:2005:04:discovery</a:To></s:Header>
 <s:Body><d:Probe><d:Types>dn:NetworkVideoTransmitter</d:Types></d:Probe></s:Body></s:Envelope>"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        sock.settimeout(timeout)
        for _ in range(2):
            sock.sendto(probe.encode(), ("239.255.255.250", 3702))
            time.sleep(0.2)
        seen = set()
        while True:
            try:
                data, addr = sock.recvfrom(65535)
            except socket.timeout:
                break
            ip = addr[0]
            if ip in seen:
                continue
            seen.add(ip)
            text = data.decode(errors="ignore")
            info = {}
            for k, v in re.findall(r"onvif://www\.onvif\.org/(\w+)/([^\s<]+)", text):
                if k in ("name", "hardware"):
                    info[k] = v.replace("%20", " ")
            found[ip] = info
        sock.close()
    except Exception:
        pass
    return found


def sweep(subnet=None, timeout=1.0, max_workers=100):
    subnet = subnet or local_subnet()
    net = ipaddress.IPv4Network(subnet, strict=False)
    mine = local_ip()
    targets = [(str(ip), p) for ip in net.hosts() if str(ip) != mine for p in SCAN_PORTS]
    found = {}

    def _check(ip, port):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(timeout)
                if s.connect_ex((ip, port)) == 0:
                    return ip, port
        except Exception:
            pass
        return None

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        for fut in as_completed([ex.submit(_check, ip, p) for ip, p in targets]):
            r = fut.result()
            if r:
                found.setdefault(r[0], []).append(r[1])
    for ip in found:
        found[ip].sort()
    return found


def rtsp_probe(ip, port=554, timeout=2.5):
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect((ip, port))
            s.sendall(f"OPTIONS rtsp://{ip}:{port}/ RTSP/1.0\r\nCSeq: 1\r\n\r\n".encode())
            return parse_rtsp_options(s.recv(2048).decode(errors="ignore"))
    except Exception:
        return False, None


def read_arp():
    table = {}
    try:  # Linux
        with open("/proc/net/arp") as fh:
            next(fh)
            for line in fh:
                p = line.split()
                if len(p) >= 4 and p[3] != "00:00:00:00:00:00":
                    table[p[0]] = p[3].lower()
        if table:
            return table
    except Exception:
        pass
    try:  # macOS / BSD: no /proc, use `arp -a`
        import subprocess
        out = subprocess.run(["arp", "-a"], capture_output=True, text=True, timeout=5).stdout
        for line in out.splitlines():
            m = re.search(r"\(([\d.]+)\) at ([0-9a-fA-F:]+)", line)
            if m and m.group(2).lower() != "incomplete":
                parts = m.group(2).split(":")
                mac = ":".join(x.zfill(2) for x in parts).lower() if len(parts) == 6 else m.group(2).lower()
                table[m.group(1)] = mac
    except Exception:
        pass
    return table


def scan(subnet=None):
    """Discover cameras on the LAN. Returns a list of dicts matching the
    console's DiscoveredCamera shape."""
    cams = {}

    def _get(ip):
        return cams.setdefault(ip, {
            "ip": ip, "port": 554, "source_type": "rtsp", "rtsp_url": "",
            "name": "", "manufacturer": "", "model": "", "resolution": "",
            "discovery_method": "", "already_registered": False, "vendor": "",
            "mac": "", "open_ports": [], "rtsp_confirmed": False,
            "confidence": 0.0, "is_camera": False, "is_computer": False,
            "found_by": [],
        })

    for ip, info in ws_discover().items():
        c = _get(ip)
        c["found_by"].append("onvif")
        c["source_type"] = "onvif"
        c["discovery_method"] = c["discovery_method"] or "onvif"
        c["name"] = c["name"] or info.get("name", "")
        c["model"] = c["model"] or info.get("hardware", "")

    for ip, ports in sweep(subnet).items():
        c = _get(ip)
        c["found_by"].append("sweep")
        c["discovery_method"] = c["discovery_method"] or "rtsp_scan"
        c["open_ports"] = sorted(set(c["open_ports"]) | set(ports))

    arp = read_arp()
    for ip, c in cams.items():
        rtsp_port = next((p for p in RTSP_PORTS if p in c["open_ports"]), None)
        if rtsp_port is None and "onvif" in c["found_by"]:
            rtsp_port = 554
        if rtsp_port:
            confirmed, banner = rtsp_probe(ip, rtsp_port)
            c["rtsp_confirmed"] = confirmed
            c["port"] = rtsp_port
            c["rtsp_url"] = c["rtsp_url"] or f"rtsp://{ip}:{rtsp_port}/stream1"
        c["mac"] = arp.get(ip, "")
        c["vendor"] = vendor_for_mac(c["mac"]) or ""
        if c["vendor"] and not c["manufacturer"]:
            c["manufacturer"] = c["vendor"]
        if not c["name"]:
            c["name"] = f"{c['vendor'] or 'Camera'} ({ip})"
        # confidence
        score = 0.0
        if "onvif" in c["found_by"]:
            score += 0.6
        if c["rtsp_confirmed"]:
            score += 0.4
        if c["vendor"]:
            score += 0.3
        if any(p in c["open_ports"] for p in RTSP_PORTS):
            score += 0.2
        c["confidence"] = round(min(score, 1.0), 2)
        c["is_camera"] = bool(c["confidence"] >= 0.5 or c["rtsp_confirmed"])
        # A non-camera with computer/NAS ports is a candidate recording PC.
        c["is_computer"] = bool(
            not c["is_camera"] and any(p in c["open_ports"] for p in COMPUTER_PORTS)
        )
        if c["is_computer"] and c["name"].startswith(("Camera (", "None (")):
            c["name"] = f"Computer ({ip})"

    return sorted(cams.values(), key=lambda c: (not c["is_camera"], -c["confidence"], c["ip"]))


# --- agent loop ------------------------------------------------------------- #

def poll_once(headers):
    """One poll cycle: pick up a job and scan, or heartbeat. Returns a short
    status string ('scanned' | 'idle' | 'unauthorized' | 'offline')."""
    status, body = _http("GET", "/api/cameras/bridge/jobs", headers=headers)
    if status == 401:
        return "unauthorized"
    if status != 200:
        return "offline"
    job = (body or {}).get("job")
    if not job:
        _http("POST", "/api/cameras/bridge/heartbeat",
              {"site_hint": local_subnet()}, headers=headers)
        return "idle"
    try:
        cameras = scan((job.get("params") or {}).get("cidr"))
        _http("POST", f"/api/cameras/bridge/jobs/{job['job_id']}/results",
              {"cameras": cameras}, headers=headers)
        print(f"[bridge] reported {sum(1 for c in cameras if c['is_camera'])} camera(s).")
    except Exception as e:
        _http("POST", f"/api/cameras/bridge/jobs/{job['job_id']}/results",
              {"cameras": [], "error": str(e)}, headers=headers)
    return "scanned"


def run_forever(creds):
    headers = {"X-Bridge-Id": creds["bridge_id"], "X-Bridge-Token": creds["token"]}
    print(f"[bridge] connected to {VANTAGE_URL} as {creds['bridge_id']}. Waiting for scan requests...")
    while True:
        if poll_once(headers) == "unauthorized":
            print("[bridge] credentials rejected — re-pair this bridge.")
            return
        time.sleep(POLL_SECONDS)


def main(argv=None):
    global VANTAGE_URL
    ap = argparse.ArgumentParser(description="Vantage Bridge — local camera-discovery agent")
    ap.add_argument("--pair", default=PAIRING_CODE, help="pairing code from the Vantage console")
    ap.add_argument("--url", default=VANTAGE_URL, help="Vantage base URL")
    ap.add_argument("--scan-once", action="store_true", help="scan the LAN once, print JSON, exit")
    args = ap.parse_args(argv)

    VANTAGE_URL = args.url

    if args.scan_once:
        print(json.dumps(scan(), indent=2))
        return 0

    creds = load_creds()
    if not creds:
        if not args.pair:
            print("No saved bridge and no pairing code. Get a code from the Vantage "
                  "console (Cameras -> Add cameras on my network) and run:\n"
                  "  python3 vantage_bridge.py --pair YOURCODE")
            return 1
        creds = register(args.pair)
        if not creds:
            return 1
        print("[bridge] paired successfully.")

    try:
        run_forever(creds)
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
