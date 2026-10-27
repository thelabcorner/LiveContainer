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


def test_wifi_dvt_capture_pins_target_and_requires_wifi_preflight(monkeypatch):
    monkeypatch.setattr(capture.config, "SIDETAP_UDID", "pinned-iphone")
    monkeypatch.setattr(capture.config, "get", lambda key, default=None: "subprocess" if key == "SIDETAP_WIFI_CAPTURE_BACKEND" else default)
    import subprocess
    monkeypatch.setattr(capture.wireless, "require_wifi", lambda: "pinned-iphone")
    monkeypatch.setenv("PYMOBILEDEVICE3_TUNNEL", "wrong-session")
    monkeypatch.setenv("PYMOBILEDEVICE3_UDID", "wrong-device")
    monkeypatch.setenv("PYMOBILEDEVICE3_NATIVE", "1")
    calls = []
    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        assert args[1:6] == ["-m", "pymobiledevice3", "developer", "dvt", "screenshot"]
        assert args[-1] == "--userspace"
        assert kwargs["env"]["PYMOBILEDEVICE3_UDID"] == "pinned-iphone"
        assert "PYMOBILEDEVICE3_TUNNEL" not in kwargs["env"]
        assert "PYMOBILEDEVICE3_NATIVE" not in kwargs["env"]
        assert kwargs["timeout"] == 25
        Path(args[-2]).write_bytes(_minimal_test_png())
        return subprocess.CompletedProcess(args, 0, "", "")
    monkeypatch.setattr(capture.subprocess, "run", fake_run)
    assert capture._wifi_dvt_screenshot() == _minimal_test_png()
    assert len(calls) == 1


def test_wifi_dvt_capture_refuses_unverified_route_before_spawning(monkeypatch):
    monkeypatch.setattr(capture.config, "get", lambda key, default=None: "subprocess" if key == "SIDETAP_WIFI_CAPTURE_BACKEND" else default)
    monkeypatch.setattr(capture.config, "SIDETAP_UDID", "pinned-iphone")
    from phone_harness import wireless
    monkeypatch.setattr(capture.wireless, "require_wifi",
                        lambda: (_ for _ in ()).throw(wireless.WirelessError("network missing")))
    monkeypatch.setattr(capture.subprocess, "run",
                        lambda *a, **k: pytest.fail("should not start DVT"))
    with pytest.raises(capture.CaptureError, match="network missing"):
        capture._wifi_dvt_screenshot()


def test_wifi_dvt_capture_rejects_invalid_png(monkeypatch):
    monkeypatch.setattr(capture.config, "SIDETAP_UDID", "pinned-iphone")
    monkeypatch.setattr(capture.config, "get", lambda key, default=None: "subprocess" if key == "SIDETAP_WIFI_CAPTURE_BACKEND" else default)
    import subprocess
    monkeypatch.setattr(capture.wireless, "require_wifi", lambda: "pinned-iphone")
    def fake_run(args, **kwargs):
        Path(args[-2]).write_bytes(b"not a phone screenshot")
        return subprocess.CompletedProcess(args, 0, "", "")
    monkeypatch.setattr(capture.subprocess, "run", fake_run)
    with pytest.raises(capture.CaptureError, match="non-PNG"):
        capture._wifi_dvt_screenshot()


def test_wifi_dvt_capture_rejects_failed_subprocess(monkeypatch):
    monkeypatch.setattr(capture.config, "SIDETAP_UDID", "pinned-iphone")
    monkeypatch.setattr(capture.config, "get", lambda key, default=None: "subprocess" if key == "SIDETAP_WIFI_CAPTURE_BACKEND" else default)
    import subprocess
    monkeypatch.setattr(capture.wireless, "require_wifi", lambda: "pinned-iphone")
    monkeypatch.setattr(capture.subprocess, "run",
                        lambda args, **kw: subprocess.CompletedProcess(args, 1, "", "no service"))
    with pytest.raises(capture.CaptureError, match="no service"):
        capture._wifi_dvt_screenshot()


def test_wifi_mode_screenshot_never_uses_usb_only_go_ios(monkeypatch, fresh):
    monkeypatch.setattr(capture.wireless, "mode", lambda: "wifi")
    monkeypatch.setattr(capture.config, "get", lambda key, default=None: "1" if key == "SIDETAP_DIRECT_ENABLE" else default)
    monkeypatch.setattr(capture.config, "SIDETAP_UDID", "pinned-iphone")
    monkeypatch.setattr(capture, "_wifi_dvt_screenshot", lambda: b"wireless-screen")
    monkeypatch.setattr(capture, "_go_ios_screenshot", lambda: pytest.fail("used USB-only screenshot"))
    monkeypatch.setattr(capture, "_wda_screenshot", lambda: pytest.fail("used old WDA"))
    assert capture.screenshot_png() == b"wireless-screen"


def test_wifi_cache_cannot_cross_phone_UDID(monkeypatch, fresh):
    monkeypatch.setattr(capture.wireless, "mode", lambda: "wifi")
    monkeypatch.setattr(capture.config, "get", lambda key, default=None: "1" if key == "SIDETAP_DIRECT_ENABLE" else default)
    monkeypatch.setattr(capture.config, "SIDETAP_UDID", "phone-A")
    seen = []
    def shot():
        seen.append(capture.config.SIDETAP_UDID)
        return seen[-1].encode()
    monkeypatch.setattr(capture, "_wifi_dvt_screenshot", shot)
    assert capture.screenshot_png(max_age=5) == b"phone-A"
    assert capture.screenshot_png(max_age=5) == b"phone-A"
    monkeypatch.setattr(capture.config, "SIDETAP_UDID", "phone-B")
    assert capture.screenshot_png(max_age=5) == b"phone-B"
    assert seen == ["phone-A", "phone-B"]
