"""Screen capture: WDA's HTTP screenshot when the session is up, go-ios otherwise.

`ios screenshot` uses the mounted Developer Disk Image's screenshot service,
so perception (viewing, OCR, wait_stable) works with zero app signing — but it
spawns a fresh subprocess + temp file per frame (~100-300ms each on Windows).
Once WDA answers, its GET /screenshot over the already-forwarded :8100
connection is much cheaper, so hot paths like wait_stable() prefer it.
Only touch INPUT needs the signed WDA driver.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import time
from pathlib import Path

from . import config, device, wireless
from .wda_client import WDAClient, WDAError


class CaptureError(RuntimeError):
    pass


_last_png: bytes | None = None
_last_at: float = 0.0
_last_transport: tuple[str, bool] | None = None

# One sessionless client for GET /screenshot (it never creates a WDA session,
# so it cannot steal the single session helpers/viewer hold). When WDA is down
# we back off instead of paying a connection error on every frame.
_wda: WDAClient | None = None
_wda_dead_until: float = 0.0
_WDA_RETRY_SECONDS = 10.0


def _wda_screenshot() -> bytes | None:
    """PNG via WDA's HTTP endpoint, or None if WDA is not answering."""
    global _wda, _wda_dead_until
    if time.time() < _wda_dead_until:
        return None
    if _wda is None:
        _wda = WDAClient(timeout=5)
    try:
        return _wda.screenshot()
    except WDAError:
        _wda_dead_until = time.time() + _WDA_RETRY_SECONDS
        return None


def _go_ios_screenshot() -> bytes:
    """PNG via `ios screenshot` (subprocess). Works with zero app signing."""
    exe = device.ios_path()
    if not exe:
        raise CaptureError(
            "go-ios not found on PATH. Install it: npm install -g go-ios"
        )

    # iOS 17+ screenshots use a RemoteServiceDiscovery tunnel. Its agent is
    # *not* guaranteed to be at the go-ios default: SideTap keeps a dedicated
    # low-port agent (GO_IOS_AGENT_PORT), particularly on Windows/Hyper-V.
    # Always use the configured local agent explicitly, rather than relying
    # on an inherited environment from an unrelated caller or OXP process.
    try:
        tunnel_port = int(config.GO_IOS_AGENT_PORT)
    except (ValueError, TypeError) as exc:
        raise CaptureError("Invalid GO_IOS_AGENT_PORT") from exc
    if not 1 <= tunnel_port <= 65535:
        raise CaptureError("GO_IOS_AGENT_PORT must be a valid TCP port")
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "shot.png"
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
        args = ["screenshot", "--output", str(out), f"--tunnel-info-port={tunnel_port}"]
        try:
            proc = subprocess.run(
                [exe, *device.pin_udid(args)],
                capture_output=True,
                text=True,
                timeout=30,
                creationflags=flags,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise CaptureError("go-ios screenshot timed out or failed to start") from exc
        if proc.returncode:
            raise CaptureError("go-ios tunnel/screenshot failed: " + (proc.stderr or proc.stdout).strip()[-300:])
        if not out.is_file():
            raise CaptureError("go-ios reported success but created no screenshot file")
        png = out.read_bytes()
        # Reject success-shaped failures and truncated files before populating
        # the global frame cache or exposing a misleading 'live phone' view.
        if (len(png) < 45 or png[:8] != b"\x89PNG\r\n\x1a\n"
                or png[8:16] != b"\x00\x00\x00\x0dIHDR"
                or png[-12:] != b"\x00\x00\x00\x00IEND\xaeB\x60\x82"):
            raise CaptureError("go-ios returned incomplete or non-PNG screenshot content")
        width, height = __import__("struct").unpack(">II", png[16:24])
        if not (0 < width <= 16384 and 0 < height <= 16384):
            raise CaptureError("go-ios screenshot dimensions are invalid")
        return png


def screenshot_png(max_age: float = 0.0) -> bytes:  # noqa: vulture  (called from viewer.py/mcp_server.py)
    """Return the current screen as PNG bytes.

    max_age > 0 returns a cached frame if it is younger than max_age seconds,
    which keeps the viewer smooth without hammering the device.
    """
    global _last_png, _last_at, _last_transport
    route = (wireless.mode(), config.get("SIDETAP_DIRECT_ENABLE", "0") == "1")
    if (max_age and _last_png is not None and _last_transport == route
            and (time.time() - _last_at) < max_age):
        return _last_png

    if route == ("wifi", True):
        # Never mix an unrelated/stale WDA frame with coordinates going to
        # the explicitly pinned CoreDevice Wi-Fi phone.
        wireless.require_wifi()
        png = _go_ios_screenshot()
    else:
        png = _wda_screenshot()
        if png is None:
            png = _go_ios_screenshot()

    _last_png, _last_at, _last_transport = png, time.time(), route
    return png
