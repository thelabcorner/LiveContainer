"""CoreDevice transport for SideTap, without an iOS-side app install."""
from __future__ import annotations

import math
import os
import subprocess
import sys

from . import config, device, wda_client, wireless


class CoreDeviceError(RuntimeError):
    pass


def _coordinate(value: float) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError("Screen coordinates must be finite fractions from 0 to 1")
    return round(value * 65535)


def direct_status() -> dict:
    """Read-only status; cannot control the device."""
    enabled = config.get("SIDETAP_DIRECT_ENABLE", "0") == "1"
    if wireless.mode() == "wifi":
        probe = wireless.control_status()
        return {**probe, "enabled": enabled,
                "ready": enabled and probe["ready"] and not wda_client.stop_engaged(),
                "stop": wda_client.stop_engaged(), "wda_ui_tree": False}
    try:
        devices = sorted(set(device.list_devices()))
    except (OSError, subprocess.TimeoutExpired, device.DeviceError) as exc:
        return {"enabled": enabled, "ready": False, "reason": str(exc)}
    selected = config.SIDETAP_UDID
    return {"enabled": enabled, "ready": enabled and not wda_client.stop_engaged() and len(devices) == 1 and (not selected or selected == devices[0]), "device_count": len(devices), "stop": wda_client.stop_engaged(), "wda_ui_tree": False}


def _run(args: list[str], activity: str, timeout: float = 25) -> None:
    if config.get("SIDETAP_DIRECT_ENABLE", "0") != "1":
        raise CoreDeviceError("Direct HID disabled. Set SIDETAP_DIRECT_ENABLE=1 explicitly.")
    if wda_client.stop_engaged():
        raise CoreDeviceError("STOP is engaged")
    extra_env = None
    if wireless.mode() == "wifi":
        try:
            selected = wireless.require_wifi()
        except wireless.WirelessError as exc:
            raise CoreDeviceError(str(exc)) from exc
        extra_env = os.environ.copy()
        extra_env["PYMOBILEDEVICE3_UDID"] = selected
    else:
        try:
            phones = sorted(set(device.list_devices()))
        except (OSError, subprocess.TimeoutExpired, device.DeviceError) as exc:
            raise CoreDeviceError("Could not verify attached iPhone") from exc
        if len(phones) != 1 or (config.SIDETAP_UDID and config.SIDETAP_UDID != phones[0]):
            raise CoreDeviceError("Exactly one selected, physically attached iPhone is required")
    cmd = [sys.executable, "-m", "pymobiledevice3", "developer", "core-device", "universal-hid-service", *args, "--userspace"]
    kwargs = {"env": extra_env} if extra_env is not None else {}
    try:
        proc = subprocess.run(
            cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True,
            timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0,
            **kwargs,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CoreDeviceError("Delivery unknown: do not automatically repeat input") from exc
    if proc.returncode:
        raise CoreDeviceError("CoreDevice failed: " + (proc.stderr or proc.stdout)[-350:])
    wda_client._append_activity(activity)


def direct_tap(x: float, y: float) -> str:
    """Tap with normalized screen coordinates; opt-in CoreDevice instead of WDA."""
    _run(["tap", str(_coordinate(x)), str(_coordinate(y))], "direct tap")
    return "tap sent"


def direct_drag(x1: float, y1: float, x2: float, y2: float, seconds: float = 0.4) -> str:
    """Drag with real touch contact; CoreDevice swipe is only pointer motion."""
    points = [str(_coordinate(v)) for v in (x1, y1, x2, y2)]
    if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not math.isfinite(seconds) or not 0.05 <= seconds <= 5:
        raise ValueError("Invalid drag duration")
    _run(["drag", *points, "--steps", "24", "--duration", str(seconds)], "direct drag")
    return "drag sent"


def direct_type_ascii(text: str) -> str:
    """HID keyboard typing (ASCII only), not a message send."""
    if not isinstance(text, str) or not 0 < len(text) <= 1024 or any(ord(c) > 126 or (ord(c) < 32 and c not in (chr(10), chr(9))) for c in text):
        raise ValueError("Only printable ASCII, tab and newline, up to 1024 characters")
    _run(["type", text], f"direct type ({len(text)} chars)", max(25.0, 15 + 0.13 * len(text)))
    return f"typed {len(text)} characters"
