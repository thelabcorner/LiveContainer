"""Opt-in Wi-Fi discovery for the real SideTap Python harness.

A paired iPhone can carry lockdown and iOS 17+ developer services over Wi-Fi
when the host's Apple Mobile Device Service supports it. Do not infer support
from an iOS device being connected to a browser-hosted SideTap viewer.

Probes are read-only and bounded. Wi-Fi setting changes require --confirm,
a pinned UDID, and a real USB device. This code never installs drivers.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Any

from . import config


class WirelessError(RuntimeError):
    pass


def mode() -> str:
    selected = (config.get("SIDETAP_TRANSPORT", "usb") or "usb").strip().lower()
    if selected not in ("usb", "wifi"):
        raise WirelessError("SIDETAP_TRANSPORT must be usb or wifi")
    return selected


def _run(args: list[str], timeout: float = 10) -> Any:
    # RSD-backed developer subcommands do not support --udid; the selected
    # identity is resolved by the real CLI from PYMOBILEDEVICE3_UDID. The
    # verified Wi-Fi-only preflight runs *before* these commands.
    child_env = None
    if args and args[0] == "developer":
        selected = config.SIDETAP_UDID
        if not selected:
            raise WirelessError("Cannot start developer service without a pinned device")
        child_env = os.environ.copy()
        child_env["PYMOBILEDEVICE3_UDID"] = str(selected)
        # Avoid inheriting incompatible alternate tunnel switches.
        child_env.pop("PYMOBILEDEVICE3_TUNNEL", None)
        child_env.pop("PYMOBILEDEVICE3_NATIVE", None)
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pymobiledevice3", *args],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
            if sys.platform == "win32" else 0,
            **({"env": child_env} if child_env is not None else {}),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise WirelessError("Wireless discovery timed out or pymobiledevice3 is unavailable") from exc
    if proc.returncode:
        detail = (proc.stderr or proc.stdout).strip()
        if "Failed to start service" in detail or "InvalidService" in detail:
            # The current iOS 18.7.7 device exposes RSD display metadata but
            # rejects the separate screen/HID services. Do not imply a
            # successful tunnel means the requested feature is available.
            raise WirelessError("Device rejected the requested CoreDevice service "
                                "(unsupported, unavailable, or missing required privileges)")
        raise WirelessError("Apple device service rejected the probe: " + detail[-320:])
    # The mutating 'lockdown wifi-connections on' command normally prints
    # nothing on success. Probes expecting lists still reject this None.
    if not proc.stdout.strip():
        return None
    try:
        return json.loads(proc.stdout)
    except (ValueError, TypeError) as exc:
        raise WirelessError("Unexpected JSON from pymobiledevice3") from exc


def _udids(values: Any, detail: bool = False) -> list[str]:
    if not isinstance(values, list):
        raise WirelessError("Expected a JSON list of devices")
    found: set[str] = set()
    for item in values:
        if isinstance(item, str) and not detail:
            value = item
        elif isinstance(item, dict) and detail:
            value = item.get("UniqueDeviceID") or item.get("Identifier") or item.get("udid")
        else:
            raise WirelessError("Unexpected device discovery record")
        if not isinstance(value, str) or not value or any(c.isspace() for c in value):
            raise WirelessError("Invalid device identifier")
        found.add(value)
    return sorted(found)


def status() -> dict:
    """Read-only, verified network lockdown preflight; not just mDNS presence."""
    requested = mode()
    selected = config.SIDETAP_UDID
    result = {
        "transport": requested,
        "pinned": bool(selected),
        "ready": False,
        "verified_network_device": False,
        "coredevice_service_ready": False,
        "hid_service_ready": False,
        "untethered": False,
        "usb_attached": False,
        "wda_ui_tree": False,
        "additional_app_slot_needed_for_coredevice": False,
    }
    if requested != "wifi":
        result["reason"] = "Wi-Fi not selected; USB transport unchanged"
        return result
    if not selected:
        result["reason"] = "Set SIDETAP_UDID to identify the exact paired iPhone"
        return result
    try:
        candidates = _udids(_run(["usbmux", "list", "--network", "--simple"]))
        if selected not in candidates:
            result["reason"] = (
                "No paired Wi-Fi iPhone exposed by usbmux. Enable Wi-Fi connections "
                "over USB and check Bonjour and the Windows Apple Mobile Device Service."
            )
            return result
        # Opening each device's lockdown session in network-only mode prevents
        # a stale usbmux network entry from being mistaken for a usable link.
        verified = _udids(_run(["usbmux", "list", "--network"], timeout=12), detail=True)
        if selected not in verified:
            result["reason"] = "Wi-Fi device did not answer paired lockdown"
            return result
        result["verified_network_device"] = True
        # A network entry does not prove the CoreDevice tunnel will avoid USB.
        # In strict Wi-Fi mode, require the selected phone to be unplugged.
        usb = _udids(_run(["usbmux", "list", "--usb", "--simple"]))
        result["usb_attached"] = selected in usb
        if result["usb_attached"]:
            result["reason"] = (
                "Paired Wi-Fi lockdown answered, but this iPhone is also attached "
                "by USB. Unplug it to prove untethered operation."
            )
            return result
    except WirelessError as exc:
        result["reason"] = str(exc)
        return result
    result.update(
        ready=True,
        verified_network_device=True,
        untethered=True,
        reason="Paired network lockdown answered without USB; CoreDevice service not yet checked",
    )
    return result


def control_status() -> dict:
    """Probe a read-only developer service across an actual RSD tunnel.

    This does not prove touchscreen HID delivery, which can only be confirmed
    by an explicitly requested gesture on the actual device.
    """
    probe = status()
    probe["lockdown_ready"] = probe["ready"]
    # A working lockdown session is not yet a working developer-control link.
    probe["ready"] = False
    if not probe["lockdown_ready"]:
        return probe
    selected = str(config.SIDETAP_UDID)
    try:
        display = _run(
            ["developer", "core-device", "get-display-info",
             "--userspace"],
            timeout=25,
        )
        if not isinstance(display, dict) or not display:
            raise WirelessError("CoreDevice returned no structured display information")
    except WirelessError as exc:
        probe["reason"] = "Wi-Fi lockdown available, but CoreDevice RSD is not: " + str(exc)
        return probe
    probe["coredevice_service_ready"] = True
    # get-display-info is NOT proof of touchscreen availability. On the real
    # iOS 18.7.7 phone, this succeeds while universal-hid-service fails at
    # service launch. Check the actual HID service without injecting touches.
    try:
        hid = _run(
            ["developer", "core-device", "universal-hid-service",
             "list-connected", "--userspace"],
            timeout=25,
        )
        if not isinstance(hid, (dict, list)):
            raise WirelessError("Unexpected CoreDevice HID service response")
    except WirelessError as exc:
        probe["reason"] = "CoreDevice display works, but HID service is unavailable: " + str(exc)
        return probe
    probe.update(
        ready=True,
        hid_service_ready=True,
        reason="Verified wireless CoreDevice display + HID service; touch delivery still untested",
    )
    return probe


def require_hid() -> str:
    """Demand a live read-only HID-service handshake before any input command."""
    probe = control_status()
    if not probe["ready"]:
        raise WirelessError(probe["reason"])
    return str(config.SIDETAP_UDID)


def require_wifi() -> str:
    state = status()
    if not state["ready"]:
        raise WirelessError(state["reason"])
    return str(config.SIDETAP_UDID)


def enable_wifi_connections(*, confirm: bool = False) -> str:
    """Explicit one-time setting change, never performed by discovery or MCP."""
    if not confirm:
        raise WirelessError("Changing the iPhone Wi-Fi setting requires --confirm")
    selected = config.SIDETAP_UDID
    if not selected:
        raise WirelessError("Set SIDETAP_UDID before changing device settings")
    usb = _udids(_run(["usbmux", "list", "--usb", "--simple"]))
    if selected not in usb:
        raise WirelessError("Selected iPhone is not available via verified USB")
    _run(["lockdown", "wifi-connections", "on", f"--udid={selected}"], timeout=15)
    return "Wi-Fi connections enabled; physically unplug to verify untethered mode"


def discovery() -> dict:
    """Read-only USB, Apple mux Wi-Fi, and Bonjour comparison."""
    result = {}
    for label, args, detail in (
        ("usb", ["usbmux", "list", "--usb", "--simple"], False),
        ("wifi_mux", ["usbmux", "list", "--network", "--simple"], False),
        ("bonjour", ["bonjour", "mobdev2", "--timeout", "3"], True),
    ):
        try:
            result[label] = _udids(_run(args, timeout=10), detail)
        except WirelessError as exc:
            result[label] = []
            result[label + "_error"] = str(exc)
    result["mode"] = mode()
    result["pin_matches_wifi"] = bool(
        config.SIDETAP_UDID and config.SIDETAP_UDID in result["wifi_mux"]
    )
    return result


def wireless_status() -> dict:
    """Read-only MCP tool. Never enables a service or changes the phone."""
    return control_status()
