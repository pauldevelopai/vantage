"""
Camera-vendor MAC OUI prefixes (seed list).

Maps the first 3 octets of a MAC (OUI) to a camera/NVR vendor, so the scanner
can fingerprint a device's brand even when it doesn't answer ONVIF.

This is a SEED list of the most common vendors — not exhaustive. For full
coverage, load the official IEEE OUI registry at startup and merge it in:
    https://standards-oui.ieee.org/oui/oui.csv

Format: "AA:BB:CC" -> "Vendor"  (uppercase, colon-separated, first 8 chars)
"""

CAMERA_OUI: dict[str, str] = {
    # Hikvision
    "00:0C:43": "Hikvision", "44:19:B6": "Hikvision", "4C:BD:8F": "Hikvision",
    "58:03:FB": "Hikvision", "BC:AD:28": "Hikvision", "C0:56:E3": "Hikvision",
    "E0:50:8B": "Hikvision",
    # Dahua (also OEMs Amcrest, Lorex, etc.)
    "00:12:15": "Dahua", "3C:EF:8C": "Dahua", "90:02:A9": "Dahua",
    "E0:61:B2": "Dahua", "14:A7:8B": "Dahua",
    # Axis
    "00:40:8C": "Axis", "AC:CC:8E": "Axis", "B8:A4:4F": "Axis",
    # Reolink
    "EC:71:DB": "Reolink", "C4:D6:55": "Reolink",
    # Amcrest
    "9C:8E:CD": "Amcrest",
    # Ubiquiti (UniFi Protect)
    "FC:EC:DA": "Ubiquiti", "24:5A:4C": "Ubiquiti", "78:8A:20": "Ubiquiti",
    # Bosch
    "00:1B:86": "Bosch", "00:07:5F": "Bosch",
    # Hanwha / Samsung Techwin
    "00:09:18": "Hanwha", "00:16:6C": "Hanwha",
    # Vivotek
    "00:02:D1": "Vivotek",
    # Mobotix
    "00:03:C5": "Mobotix",
    # Panasonic / i-PRO
    "00:80:F0": "Panasonic",
    # Foscam
    "00:62:6E": "Foscam",
    # TP-Link (Tapo / VIGI)
    "00:31:92": "TP-Link", "30:DE:4B": "TP-Link",
    # Wyze
    "2C:AA:8E": "Wyze", "7C:78:B2": "Wyze",
}


# Brand -> RTSP URL templates. Used to build a URL from credentials when a
# camera is fingerprinted by vendor but does not answer ONVIF. {ip}/{user}/{pw}
# are filled in by the caller (password must be URL-encoded).
BRAND_RTSP_TEMPLATES: dict[str, dict[str, str]] = {
    "Hikvision": {
        "main": "rtsp://{user}:{pw}@{ip}:554/Streaming/Channels/101",
        "sub": "rtsp://{user}:{pw}@{ip}:554/Streaming/Channels/102",
    },
    "Dahua": {
        "main": "rtsp://{user}:{pw}@{ip}:554/cam/realmonitor?channel=1&subtype=0",
        "sub": "rtsp://{user}:{pw}@{ip}:554/cam/realmonitor?channel=1&subtype=1",
    },
    "Amcrest": {
        "main": "rtsp://{user}:{pw}@{ip}:554/cam/realmonitor?channel=1&subtype=0",
        "sub": "rtsp://{user}:{pw}@{ip}:554/cam/realmonitor?channel=1&subtype=1",
    },
    "Reolink": {
        "main": "rtsp://{user}:{pw}@{ip}:554/h264Preview_01_main",
        "sub": "rtsp://{user}:{pw}@{ip}:554/h264Preview_01_sub",
    },
    "Axis": {
        "main": "rtsp://{user}:{pw}@{ip}:554/axis-media/media.amp",
        "sub": "rtsp://{user}:{pw}@{ip}:554/axis-media/media.amp?resolution=640x480",
    },
}


def vendor_for_mac(mac: str | None) -> str | None:
    """Return the camera vendor for a MAC address, or None if unknown."""
    if not mac:
        return None
    prefix = mac.upper().replace("-", ":")[:8]
    return CAMERA_OUI.get(prefix)
