"""Read-only, identity-pinned RSD service inventory for SideTap.

The phone's RSD service directory is authoritative for availability.
A functioning tunnel and mounted DDI do NOT imply that DisplayService or
UniversalHIDService is published. Never invent a fallback service port.
"""
from __future__ import annotations

import asyncio

TARGETS = (
    "com.apple.coredevice.displayservice",
    "com.apple.coredevice.screencaptureservice",
    "com.apple.coredevice.hid.universalhidservice",
)
INSTRUMENTS = "com.apple.instruments.dtservicehub"


class RSDInventoryError(RuntimeError):
    pass


def summarize_services(services: dict) -> dict:
    if not isinstance(services, dict):
        raise RSDInventoryError("RSD did not supply a service directory")
    result = {
        "rsd_connected": True,
        "service_count": len(services),
        "coredevice_service_count": sum(k.startswith("com.apple.coredevice.") for k in services),
        "services": {k: k in services for k in TARGETS},
        "instruments_dvt_present": INSTRUMENTS in services,
    }
    result["hevc_display_advertised"] = result["services"][TARGETS[0]]
    return result


async def _probe(udid: str) -> dict:
    from pymobiledevice3.remote.userspace_tunnel import UserspaceRsdTunnel
    async with asyncio.timeout(17):
        async with UserspaceRsdTunnel(serial=udid, autopair=False) as rsd:
            if rsd.udid != udid:
                raise RSDInventoryError("RSD device does not match pinned iPhone")
            info = rsd.peer_info
            if not isinstance(info, dict) or not isinstance(info.get("Services"), dict):
                raise RSDInventoryError("RSD directory missing or malformed")
            return summarize_services(info["Services"])


def probe(udid: str) -> dict:
    if not isinstance(udid, str) or not udid or any(ch.isspace() for ch in udid):
        raise RSDInventoryError("A pinned iPhone UDID is required")
    try:
        return asyncio.run(_probe(udid))
    except RSDInventoryError:
        raise
    except Exception as exc:
        # Do not include paired device metadata, service handshake dumps or
        # network addresses in companion error responses.
        raise RSDInventoryError("Unable to read paired RSD service directory: " + type(exc).__name__) from exc
