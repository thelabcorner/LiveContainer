"""Read-only, bounded HEVC/RTP capture certification for SideTap Wi-Fi.

An RTP frame probe deliberately avoids exposing pymobiledevice3's serve-web
HID, clipboard and HTTP endpoints. It never saves phone pixels permanently:
temporary length-prefixed packets are discarded and only aggregate statistics
are returned. Nothing is advertised as a working stream without actual RTP.
"""
from __future__ import annotations

import os
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from . import config, wireless


class HEVCProbeError(RuntimeError):
    pass


def summarize_rtp_dump(data: bytes, *, duration: float) -> dict:
    """Inspect source-owned, four-byte length-prefixed RTP datagrams.

    The underlying tool's capture uses RTP packets: length[4] then bytes.
    RTP timestamps, not packet counts, distinguish frames from fragmentation.
    Reject malformed, huge or non-video output rather than fabricating FPS.
    """
    if duration <= 0:
        raise HEVCProbeError("Capture duration must be positive")
    offset = 0
    n = 0
    payload_bytes = 0
    frame_timestamps: set[int] = set()
    marker_count = 0
    first_timestamp: int | None = None
    last_timestamp: int | None = None
    hevc_headers = 0
    while offset < len(data):
        if len(data) - offset < 4:
            raise HEVCProbeError("Truncated RTP record prefix")
        size = struct.unpack_from(">I", data, offset)[0]
        offset += 4
        if size < 12 or size > 65535 or size > len(data) - offset:
            raise HEVCProbeError("Malformed RTP record length")
        packet = data[offset:offset + size]
        offset += size
        if packet[0] >> 6 != 2:
            raise HEVCProbeError("RTP protocol version mismatch")
        if 200 <= packet[1] <= 204:
            continue  # RTCP control, not a video frame.
        csrcs = packet[0] & 15
        header_end = 12 + 4 * csrcs
        if header_end > len(packet):
            raise HEVCProbeError("RTP CSRC header truncated")
        if packet[0] & 0x10:
            if header_end + 4 > len(packet):
                raise HEVCProbeError("RTP extension truncated")
            ext_words = struct.unpack_from(">H", packet, header_end + 2)[0]
            header_end += 4 + ext_words * 4
            if header_end > len(packet):
                raise HEVCProbeError("RTP extension exceeds packet")
        if len(packet) - header_end < 2:
            raise HEVCProbeError("Missing HEVC payload header")
        nal_type = (packet[header_end] >> 1) & 0x3f
        if nal_type <= 50:
            hevc_headers += 1
        ts = struct.unpack_from(">I", packet, 4)[0]
        if first_timestamp is None:
            first_timestamp = ts
        last_timestamp = ts
        frame_timestamps.add(ts)
        n += 1
        marker_count += bool(packet[1] & 0x80)
        payload_bytes += size - header_end
    frame_count = len(frame_timestamps)
    return {
        # One keyframe then silence is a known failure class of the upstream
        # serve-web implementation. A received RTP packet is not continuous
        # streaming; demand at least three completed frame markers/timestamps.
        "stream_verified": frame_count >= 3 and marker_count >= 3 and hevc_headers >= 3,
        "rtp_packets_received": n > 0,
        "hevc_decode_verified": False,
        "packets": n,
        "distinct_timestamps": frame_count,
        "frame_markers": marker_count,
        "hevc_header_packets": hevc_headers,
        "payload_bytes": payload_bytes,
        "mean_payload_kbps": round(payload_bytes * 8 / (duration * 1000), 1),
        # This is an observed *distinct-timestamp rate*, not decoded or
        # displayed FPS; dropped/partial frames may inflate or lower it.
        "observed_timestamp_rate": round(frame_count / duration, 2),
        "requested_seconds": duration,
    }


def probe(*, duration: float = 4.0, confirm: bool = False) -> dict:
    if not confirm:
        raise HEVCProbeError("Starting an HEVC media stream requires explicit --confirm")
    if not 2 <= duration <= 10:
        raise HEVCProbeError("HEVC probe duration must be between 2 and 10 seconds")
    selected = config.SIDETAP_UDID
    if not selected:
        raise HEVCProbeError("A pinned iPhone identity is required")
    try:
        active = wireless.require_wifi()
    except wireless.WirelessError as exc:
        raise HEVCProbeError("Network-only iPhone verification failed: " + str(exc)) from exc
    if active != selected:
        raise HEVCProbeError("Verified Wi-Fi phone does not match pinned identity")
    media = wireless.media_capabilities()
    if not (media["media_service_ready"] and media["stream_status_ready"]):
        raise HEVCProbeError("HEVC DisplayService unavailable: " + media["reason"])

    with tempfile.TemporaryDirectory(prefix="sidetap-hevc-") as td:
        path = Path(td) / "bounded.rtp"
        env = os.environ.copy()
        env["PYMOBILEDEVICE3_UDID"] = selected
        env.pop("PYMOBILEDEVICE3_TUNNEL", None)
        env.pop("PYMOBILEDEVICE3_NATIVE", None)
        cmd = [
            sys.executable, "-m", "pymobiledevice3", "developer",
            "core-device", "display", "start-video-stream",
            str(path), "--duration", str(duration), "--userspace",
        ]
        start = time.monotonic()
        try:
            run = subprocess.run(
                cmd, env=env, capture_output=True, stdin=subprocess.DEVNULL,
                text=True, timeout=min(55.0, duration + 40),
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
                if sys.platform == "win32" else 0,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise HEVCProbeError("HEVC negotiation/receive failed or exceeded deadline") from exc
        if run.returncode != 0:
            # Upstream error text can include device names, addresses, tokens.
            raise HEVCProbeError("HEVC streaming command exited unsuccessfully")
        if not path.is_file():
            raise HEVCProbeError("HEVC streaming reported success without RTP data")
        if path.stat().st_size > 64 * 1024 * 1024:
            raise HEVCProbeError("HEVC stream probe exceeded the 64 MiB cap")
        statistics = summarize_rtp_dump(path.read_bytes(), duration=duration)
        statistics["wall_seconds"] = round(time.monotonic() - start, 2)
        statistics["transport"] = "paired-wifi-userspace"
        statistics["device_pinned"] = True
        if not statistics["stream_verified"]:
            raise HEVCProbeError("The HEVC service started but returned no verified RTP video packets")
        return statistics
