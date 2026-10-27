"""Capture path selection: WDA HTTP first, go-ios fallback. No phone needed."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from phone_harness import capture  # noqa: E402
from phone_harness.wda_client import WDAError  # noqa: E402


class StubWDA:
    def __init__(self, png=b"wda-frame", error=None):
        self.png = png
        self.error = error
        self.calls = 0

    def screenshot(self):
        self.calls += 1
        if self.error:
            raise self.error
        return self.png


@pytest.fixture()
def fresh(monkeypatch):
    """Reset capture's module state so tests cannot leak into each other."""
    monkeypatch.setattr(capture, "_last_png", None)
    monkeypatch.setattr(capture, "_last_at", 0.0)
    monkeypatch.setattr(capture, "_wda_dead_until", 0.0)

    def use(stub):
        monkeypatch.setattr(capture, "_wda", stub)
        return stub

    return use


def test_screenshot_prefers_wda_http(fresh, monkeypatch):
    stub = fresh(StubWDA())
    # go-ios must not even be consulted when WDA answers
    monkeypatch.setattr(capture.device, "ios_path", lambda: pytest.fail("spawned"))
    assert capture.screenshot_png() == b"wda-frame"
    assert stub.calls == 1


def test_screenshot_falls_back_to_go_ios_when_wda_down(fresh, monkeypatch):
    fresh(StubWDA(error=WDAError("down")))
    monkeypatch.setattr(capture, "_go_ios_screenshot", lambda: b"go-ios-frame")
    assert capture.screenshot_png() == b"go-ios-frame"


def test_wda_failure_backs_off(fresh, monkeypatch):
    stub = fresh(StubWDA(error=WDAError("down")))
    monkeypatch.setattr(capture, "_go_ios_screenshot", lambda: b"go-ios-frame")
    capture.screenshot_png()
    capture.screenshot_png()  # inside the back-off window: WDA not retried
    assert stub.calls == 1


def test_max_age_serves_cached_frame(fresh):
    stub = fresh(StubWDA())
    assert capture.screenshot_png(max_age=5.0) == b"wda-frame"
    assert capture.screenshot_png(max_age=5.0) == b"wda-frame"
    assert stub.calls == 1


def test_no_go_ios_and_no_wda_raises(fresh, monkeypatch):
    fresh(StubWDA(error=WDAError("down")))
    monkeypatch.setattr(capture.device, "ios_path", lambda: None)
    with pytest.raises(capture.CaptureError, match="go-ios not found"):
        capture.screenshot_png()

def _minimal_test_png(w: int = 1284, h: int = 2778) -> bytes:
    import struct
    # Deliberately just PNG signature+IHDR for capture's framing validation;
    # device screenshots were independently verified as real PNGs.
    # Enough structure for quick framing checks; image decompression is a
    # separate go-ios concern and not tested by synthetic screenshot bytes.
    return (b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR"
            + struct.pack(">II", w, h) + b"\x08\x06\x00\x00\x00"
            + b"\x00\x00\x00\x00"  # IHDR CRC not decoded by this layer
            + b"\x00\x00\x00\x00IEND\xaeB\x60\x82")


def test_go_ios_capture_pins_active_tunnel_and_device(monkeypatch):
    import subprocess
    monkeypatch.setattr(capture.device, "ios_path", lambda: r"C:\Tools\ios.exe")
    monkeypatch.setattr(capture.device, "pin_udid",
                        lambda args: [*args, "--udid=expected-device"])
    monkeypatch.setattr(capture.config, "GO_IOS_AGENT_PORT", "28100")
    seen = []

    def fake_run(args, **kwargs):
        seen.append(args)
        assert args[0] == r"C:\Tools\ios.exe"
        assert "--tunnel-info-port=28100" in args
        assert "--udid=expected-device" in args
        assert kwargs["timeout"] == 30
        out = Path(args[args.index("--output") + 1])
        out.write_bytes(_minimal_test_png())
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(capture.subprocess, "run", fake_run)
    assert capture._go_ios_screenshot() == _minimal_test_png()
    assert len(seen) == 1


@pytest.mark.parametrize("invalid", ["", "0", "-1", "65536", "other"])
def test_go_ios_capture_rejects_invalid_tunnel_port(monkeypatch, invalid):
    monkeypatch.setattr(capture.config, "GO_IOS_AGENT_PORT", invalid)
    monkeypatch.setattr(capture.device, "ios_path", lambda: r"C:\Tools\ios.exe")
    monkeypatch.setattr(capture.subprocess, "run",
                        lambda *a, **k: pytest.fail("must not spawn"))
    with pytest.raises(capture.CaptureError, match="GO_IOS_AGENT_PORT"):
        capture._go_ios_screenshot()


@pytest.mark.parametrize("payload", [b"", b"error text", b"\x89PNG\r\n\x1a\n", _minimal_test_png(0, 5)])
def test_go_ios_capture_never_caches_invalid_image(monkeypatch, payload):
    import subprocess
    monkeypatch.setattr(capture.config, "GO_IOS_AGENT_PORT", "28100")
    monkeypatch.setattr(capture.device, "ios_path", lambda: r"C:\Tools\ios.exe")
    def fake_run(args, **kw):
        Path(args[args.index("--output") + 1]).write_bytes(payload)
        return subprocess.CompletedProcess(args, 0, "", "")
    monkeypatch.setattr(capture.subprocess, "run", fake_run)
    with pytest.raises(capture.CaptureError, match="PNG|screenshot file|dimensions"):
        capture._go_ios_screenshot()


def test_go_ios_capture_rejects_nonzero_exit_even_if_png_exists(monkeypatch):
    import subprocess
    monkeypatch.setattr(capture.config, "GO_IOS_AGENT_PORT", "28100")
    monkeypatch.setattr(capture.device, "ios_path", lambda: r"C:\Tools\ios.exe")
    def fake_run(args, **kw):
        Path(args[args.index("--output") + 1]).write_bytes(_minimal_test_png())
        return subprocess.CompletedProcess(args, 1, "", "device not found")
    monkeypatch.setattr(capture.subprocess, "run", fake_run)
    with pytest.raises(capture.CaptureError, match="device not found"):
        capture._go_ios_screenshot()
