"""
VMS Connection Helpers

Translates VMS connection details into RTSP URLs that RTSPReader can consume.
Supports direct RTSP, ONVIF discovery, Milestone XProtect, and Genetec Security Center.
"""

from typing import Dict, Any, Optional
from urllib.parse import quote

from alibi.cameras.camera_store import Camera


def rtsp_url_from_config(camera: Camera) -> str:
    """
    Build an RTSP URL from camera configuration.

    Args:
        camera: Camera with source_type and vms_config

    Returns:
        RTSP URL string
    """
    source_type = camera.source_type
    vms = camera.vms_config or {}

    if source_type == "rtsp":
        return camera.source

    if source_type == "mobile":
        return ""  # Mobile cameras don't use RTSP

    username = quote(vms.get("username", ""), safe="")
    password = quote(vms.get("password", ""), safe="")
    host = vms.get("host", "")
    port = vms.get("port", 554)
    camera_guid = vms.get("camera_guid", "")
    path = vms.get("path", "")

    auth = f"{username}:{password}@" if username else ""

    if source_type == "onvif":
        # ONVIF: try standard profile stream path
        # Most ONVIF cameras expose RTSP at /stream1 or similar
        stream_path = path or "stream1"
        return f"rtsp://{auth}{host}:{port}/{stream_path}"

    if source_type == "milestone":
        # Milestone XProtect RTSP bridge
        # Format: rtsp://user:pass@host:port/live/camera_guid
        rtsp_port = vms.get("rtsp_port", 554)
        return f"rtsp://{auth}{host}:{rtsp_port}/live/{camera_guid}"

    if source_type == "genetec":
        # Genetec Security Center RTSP
        # Format: rtsp://user:pass@host:port/camera_guid
        rtsp_port = vms.get("rtsp_port", 554)
        return f"rtsp://{auth}{host}:{rtsp_port}/{camera_guid}"

    # Fallback: treat source as direct URL
    return camera.source


def test_connection(camera: Camera) -> Dict[str, Any]:
    """
    Test camera connection by reading one frame.

    Returns:
        {"ok": True, "resolution": "1920x1080", "fps": 25.0} on success
        {"ok": False, "error": "reason"} on failure
    """
    if camera.source_type == "mobile":
        return {"ok": True, "resolution": "mobile", "fps": 0, "note": "Mobile cameras connect on demand"}

    url = rtsp_url_from_config(camera)
    if not url:
        return {"ok": False, "error": "No RTSP URL could be constructed"}

    try:
        import cv2
    except ImportError:
        return {"ok": False, "error": "OpenCV not installed"}

    try:
        cap = cv2.VideoCapture(url)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        if not cap.isOpened():
            return {"ok": False, "error": f"Failed to open stream"}

        fps = cap.get(cv2.CAP_PROP_FPS) or 0
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        ret, frame = cap.read()
        cap.release()

        if not ret or frame is None:
            return {"ok": False, "error": "Connected but failed to read frame"}

        return {
            "ok": True,
            "resolution": f"{width}x{height}",
            "fps": round(fps, 1),
        }

    except Exception as e:
        return {"ok": False, "error": str(e)}
