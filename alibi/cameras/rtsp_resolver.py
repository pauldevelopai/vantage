"""
RTSP URL resolver — turn a discovered camera + credentials into a real,
playable stream URL.

Discovery gives us an IP and a brand (from ONVIF scopes or the OUI table); it
does NOT give a working RTSP path, and the path differs per vendor. A default
like `rtsp://ip:554/stream1` fails on most real cameras (Dahua wants
`/cam/realmonitor?...`, Hikvision `/Streaming/Channels/101`, etc.).

This builds the correct URL from the brand + credentials, URL-encoding the
password so characters like `@ : /` don't break the URL. Main and sub streams:
detection runs on the low-res sub-stream (cheap), recording on the main.

Pure + dependency-free (stdlib only) so it's unit-testable and can run in the
agent or the cloud. ONVIF `GetStreamUri` resolution (more robust, needs the
camera creds + network reach) is a later enhancement layered on top.
"""

from typing import Optional
from urllib.parse import quote

from alibi.cameras.oui_prefixes import BRAND_RTSP_TEMPLATES

# Brand aliases seen in ONVIF names / manufacturer strings / OUI vendors.
_BRAND_ALIASES = {
    "hikvision": "Hikvision", "hiksision": "Hikvision",
    "dahua": "Dahua", "amcrest": "Amcrest", "lorex": "Dahua",
    "reolink": "Reolink", "axis": "Axis",
}


def infer_brand(cam: dict) -> Optional[str]:
    """Infer a known camera brand from a discovered-camera dict.

    Checks vendor (OUI), manufacturer + name (ONVIF scopes). Returns a brand key
    present in BRAND_RTSP_TEMPLATES, or None if we can't tell.
    """
    haystack = " ".join(str(cam.get(k, "")) for k in ("vendor", "manufacturer", "name", "model")).lower()
    for alias, brand in _BRAND_ALIASES.items():
        if alias in haystack:
            return brand
    return None


def build_rtsp_url(
    ip: str,
    brand: Optional[str],
    username: str = "",
    password: str = "",
    port: int = 554,
    stream: str = "main",
) -> Optional[str]:
    """Build a playable RTSP URL for a known brand + credentials.

    Returns None if the brand isn't in the template table (caller should fall
    back to a manual URL or ONVIF resolution). Credentials are URL-encoded.
    """
    tpl = BRAND_RTSP_TEMPLATES.get(brand or "")
    if not tpl:
        return None
    pattern = tpl.get(stream) or tpl.get("main")
    if not pattern:
        return None

    user_enc = quote(username, safe="")
    pw_enc = quote(password, safe="")
    url = pattern.format(ip=ip, user=user_enc, pw=pw_enc)

    # Templates hardcode :554 — swap if a non-standard port was discovered.
    if port and port != 554:
        url = url.replace(f"@{ip}:554/", f"@{ip}:{port}/")
    # No credentials → strip the "user:pw@" so the URL is still well-formed.
    if not username and not password:
        url = url.replace("://:@", "://")
    return url


def resolve_for_discovered(
    cam: dict, username: str = "", password: str = "", stream: str = "main"
) -> Optional[str]:
    """Resolve a stream URL for a discovered-camera dict. Returns None if the
    brand is unknown (the caller then needs a manual URL)."""
    brand = infer_brand(cam)
    if not brand:
        return None
    port = int(cam.get("port") or 554)
    return build_rtsp_url(cam.get("ip", ""), brand, username, password, port=port, stream=stream)
