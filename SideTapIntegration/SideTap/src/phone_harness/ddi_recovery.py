"""Explicit, bounded restoration of the signed Developer Disk Image after reboot.

iOS 18 drops its mounted DDI on reboot; on this device the official
pymobiledevice3 userspace RSD mount succeeded over paired Wi-Fi where direct
lockdown mounter returned ConnectionTerminatedError. This is NOT an IPA install,
does not change pairing and does not enable developer mode.
"""
from __future__ import annotations

import subprocess
import sys

from . import config, wireless


class DDIMountError(RuntimeError):
    pass


def mount(*, confirm: bool = False) -> dict:
    if not confirm:
        raise DDIMountError("DDI mount changes the iPhone's developer state; explicit --confirm required")
    target = config.SIDETAP_UDID
    if not target:
        raise DDIMountError("SIDETAP_UDID must be pinned before developer-image mounting")
    try:
        verified = wireless.require_wifi()
    except wireless.WirelessError as exc:
        raise DDIMountError("A verified paired Wi-Fi device is required: " + str(exc)) from exc
    if target != verified:
        raise DDIMountError("Verified device does not match selected iPhone")
    cmd = [
        sys.executable, "-m", "pymobiledevice3", "mounter",
        "auto-mount", "--userspace", "--udid", target,
    ]
    try:
        child = subprocess.run(
            cmd, stdin=subprocess.DEVNULL,
            capture_output=True, text=True, timeout=150,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
            if sys.platform == "win32" else 0,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise DDIMountError("Official DDI auto-mount failed to complete within its deadline") from exc
    if child.returncode:
        # Error streams may include device identity or pairing details.
        raise DDIMountError("Official userspace DDI mount did not complete")
    return {"mounted": True, "transport": "paired-wifi-userspace",
            "device_identity_verified": True}
