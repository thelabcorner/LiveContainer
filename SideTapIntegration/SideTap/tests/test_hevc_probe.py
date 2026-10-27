from __future__ import annotations

import struct
import subprocess
from pathlib import Path

import pytest

from phone_harness import config, hevc_probe, wireless


def packet(ts: int, *, marker: bool = True, payload: bytes = b"\x26\x01\xff", csrcs: int = 0) -> bytes:
    h = bytes([0x80 | csrcs, (0x80 if marker else 0) | 123]) + struct.pack(
        ">HII", 3, ts, 12345
    )
    return h + (b"\x00" * (4 * csrcs)) + payload


def dump(*packets: bytes) -> bytes:
    return b"".join(struct.pack(">I", len(p)) + p for p in packets)


def test_hevc_summary_counts_distinct_frames_not_fragments():
    raw = dump(packet(1000, marker=False),
               packet(1000, marker=True),
               packet(2000, marker=False),
               packet(2000, marker=True),
               packet(3000))
    result = hevc_probe.summarize_rtp_dump(raw, duration=4)
    assert result["stream_verified"] is True
    assert result["packets"] == 5
    assert result["distinct_timestamps"] == 3
    assert result["observed_timestamp_rate"] == 0.75
    assert result["frame_markers"] == 3
    assert result["hevc_header_packets"] == 5
    assert result["payload_bytes"] == 15
    assert result["mean_payload_kbps"] == 0.0 or result["mean_payload_kbps"] == 0.03


@pytest.mark.parametrize("raw", [
    b"\x00\x00", b"\x00\x00\x00\x0b" + b"x" * 11,
    b"\x00\x00\xff\xff" + b"x" * 5,
    dump(b"\x00" * 12),
    dump(b"\x80" + b"\x00" * 11),
    dump(packet(1000)[:12]),
    dump(b"\x90\xfb" + b"\x00" * 10),
])
def test_hevc_parser_rejects_malformed_stream(raw):
    with pytest.raises(hevc_probe.HEVCProbeError):
        hevc_probe.summarize_rtp_dump(raw, duration=4)


def test_hevc_zero_packets_never_claims_video():
    result = hevc_probe.summarize_rtp_dump(b"", duration=4)
    assert result["stream_verified"] is False
    assert result["observed_timestamp_rate"] == 0


def test_hevc_requires_explicit_confirmation_and_bounded_duration(monkeypatch):
    spawn = lambda *a, **k: pytest.fail("Unconfirmed probe cannot touch device")
    monkeypatch.setattr(hevc_probe.subprocess, "run", spawn)
    with pytest.raises(hevc_probe.HEVCProbeError, match="--confirm"):
        hevc_probe.probe()
    for seconds in (-1, 0, 1, 11, 300):
        with pytest.raises(hevc_probe.HEVCProbeError, match="duration"):
            hevc_probe.probe(duration=seconds, confirm=True)


def test_hevc_without_network_never_starts_capture(monkeypatch):
    monkeypatch.setattr(config, "SIDETAP_UDID", "pinned-iphone")
    monkeypatch.setattr(wireless, "require_wifi",
                        lambda: (_ for _ in ()).throw(wireless.WirelessError("phone offline")))
    monkeypatch.setattr(hevc_probe.subprocess, "run",
                        lambda *a, **k: pytest.fail("No executable if Wi-Fi absent"))
    with pytest.raises(hevc_probe.HEVCProbeError, match="phone offline"):
        hevc_probe.probe(confirm=True)


def test_hevc_uses_same_verified_device_and_erases_recorded_video(monkeypatch):
    monkeypatch.setattr(config, "SIDETAP_UDID", "pinned-iphone")
    monkeypatch.setattr(wireless, "require_wifi", lambda: "pinned-iphone")
    monkeypatch.setattr(wireless, "media_capabilities", lambda: {
        "media_service_ready": True, "stream_status_ready": True, "reason": "ready"
    })
    monkeypatch.setenv("PYMOBILEDEVICE3_TUNNEL", "other-device")
    files = []
    def fake_run(args, **kwargs):
        assert args[1:7] == ["-m", "pymobiledevice3", "developer", "core-device",
                              "display", "start-video-stream"]
        assert args[-1] == "--userspace"
        assert kwargs["env"]["PYMOBILEDEVICE3_UDID"] == "pinned-iphone"
        assert "PYMOBILEDEVICE3_TUNNEL" not in kwargs["env"]
        path = Path(args[7])
        files.append(path)
        path.write_bytes(dump(packet(5000), packet(6000), packet(7000)))
        return subprocess.CompletedProcess(args, 0, "", "")
    monkeypatch.setattr(hevc_probe.subprocess, "run", fake_run)
    data = hevc_probe.probe(confirm=True)
    assert data["stream_verified"] is True
    assert data["packets"] == 3
    assert data["hevc_decode_verified"] is False
    assert data["device_pinned"] is True
    assert data["transport"] == "paired-wifi-userspace"
    assert files and not files[0].exists()


def test_hevc_refuses_nonmatching_device_or_missing_media(monkeypatch):
    monkeypatch.setattr(config, "SIDETAP_UDID", "pinned-iphone")
    monkeypatch.setattr(wireless, "require_wifi", lambda: "wrong-iphone")
    monkeypatch.setattr(hevc_probe.subprocess, "run",
                        lambda *a, **k: pytest.fail("Wrong device may not receive a stream"))
    with pytest.raises(hevc_probe.HEVCProbeError, match="pinned identity"):
        hevc_probe.probe(confirm=True)
    monkeypatch.setattr(wireless, "require_wifi", lambda: "pinned-iphone")
    monkeypatch.setattr(wireless, "media_capabilities", lambda: {
        "media_service_ready": False, "stream_status_ready": False, "reason": "no service",
    })
    with pytest.raises(hevc_probe.HEVCProbeError, match="no service"):
        hevc_probe.probe(confirm=True)


def test_hevc_error_never_leaks_raw_cli_stderr(monkeypatch):
    monkeypatch.setattr(config, "SIDETAP_UDID", "pinned-iphone")
    monkeypatch.setattr(wireless, "require_wifi", lambda: "pinned-iphone")
    monkeypatch.setattr(wireless, "media_capabilities", lambda: {
        "media_service_ready": True, "stream_status_ready": True
    })
    monkeypatch.setattr(hevc_probe.subprocess, "run", lambda args, **k:
                        subprocess.CompletedProcess(args, 1, "", "SECRET PAIRING DATA"))
    with pytest.raises(hevc_probe.HEVCProbeError) as exc:
        hevc_probe.probe(confirm=True)
    assert "SECRET" not in str(exc.value)


def test_one_video_frame_then_silence_is_not_a_working_stream():
    # Regression for upstream issue #1759: one HEVC keyframe can arrive and
    # /stream.bin then hang forever. This must not certify continuous viewing.
    data = hevc_probe.summarize_rtp_dump(
        dump(packet(1000, marker=False), packet(1000, marker=True)),
        duration=4,
    )
    assert data["rtp_packets_received"] is True
    assert data["distinct_timestamps"] == 1
    assert data["stream_verified"] is False
    assert data["hevc_decode_verified"] is False
