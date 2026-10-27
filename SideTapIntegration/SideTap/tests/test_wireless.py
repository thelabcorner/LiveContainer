"""No-device regression suite for Wi-Fi lockdown and WDA-free HID routing."""
from __future__ import annotations

import subprocess
from unittest.mock import Mock

import pytest

from phone_harness import config, coredevice, wireless


@pytest.fixture(autouse=True)
def usb_default(monkeypatch):
    monkeypatch.setattr(config, "SIDETAP_UDID", "selected-phone")
    monkeypatch.setattr(config, "get", lambda key, default=None: default)


def wifi_mode(monkeypatch):
    monkeypatch.setattr(config, "get", lambda key, default=None:
                        "wifi" if key == "SIDETAP_TRANSPORT" else
                        "1" if key == "SIDETAP_DIRECT_ENABLE" else default)


def test_wifi_requires_explicit_opt_in(monkeypatch):
    assert wireless.mode() == "usb"
    assert wireless.status()["ready"] is False


def test_invalid_mode_fails_closed(monkeypatch):
    monkeypatch.setattr(config, "get", lambda key, default=None: "surprise")
    with pytest.raises(wireless.WirelessError, match="usb or wifi"):
        wireless.mode()


def test_wifi_needs_pinned_iphone(monkeypatch):
    wifi_mode(monkeypatch)
    monkeypatch.setattr(config, "SIDETAP_UDID", None)
    run = Mock()
    monkeypatch.setattr(wireless, "_run", run)
    state = wireless.status()
    assert not state["ready"]
    assert "SIDETAP_UDID" in state["reason"]
    run.assert_not_called()


def test_network_only_not_usb_and_never_accepts_stale_record(monkeypatch):
    wifi_mode(monkeypatch)
    commands = []
    def runner(args, timeout=10):
        commands.append(args)
        if "--simple" in args:
            return ["selected-phone"]
        return []
    monkeypatch.setattr(wireless, "_run", runner)
    state = wireless.status()
    assert not state["ready"]
    assert not state["verified_network_device"]
    assert commands == [["usbmux", "list", "--network", "--simple"],
                        ["usbmux", "list", "--network"]]


def test_wifi_must_match_pinned_udid(monkeypatch):
    wifi_mode(monkeypatch)
    monkeypatch.setattr(wireless, "_run", lambda *a, **kw: ["different-phone"])
    assert not wireless.status()["ready"]
    with pytest.raises(wireless.WirelessError):
        wireless.require_wifi()


def test_wifi_ready_only_after_real_lockdown_network_proof(monkeypatch):
    wifi_mode(monkeypatch)
    def runner(args, timeout=10):
        if "--simple" in args:
            return ["unrelated-phone", "selected-phone"]
        return [{"UniqueDeviceID": "selected-phone"}, {"UniqueDeviceID": "unrelated-phone"}]
    monkeypatch.setattr(wireless, "_run", runner)
    state = wireless.status()
    assert state["ready"] and state["verified_network_device"]
    assert state["wda_ui_tree"] is False
    assert wireless.require_wifi() == "selected-phone"


def test_fail_closed_when_network_probe_times_out(monkeypatch):
    wifi_mode(monkeypatch)
    def timeout(*a, **kw):
        raise wireless.WirelessError("time out")
    monkeypatch.setattr(wireless, "_run", timeout)
    assert not wireless.status()["ready"]


@pytest.mark.parametrize("data", [None, {}, [7], [{"no_identifier": "x"}], ["other bad"], [{"udid": "x"}]])
def test_no_untrusted_discovery_shapes_or_identity(data):
    with pytest.raises(wireless.WirelessError):
        wireless._udids(data)


def test_wifi_enable_requires_confirmation_without_side_effects(monkeypatch):
    call = Mock()
    monkeypatch.setattr(wireless, "_run", call)
    with pytest.raises(wireless.WirelessError, match="confirm"):
        wireless.enable_wifi_connections()
    call.assert_not_called()


def test_wifi_enable_requires_pin_and_usb(monkeypatch):
    call = Mock(return_value=[])
    monkeypatch.setattr(wireless, "_run", call)
    monkeypatch.setattr(config, "SIDETAP_UDID", None)
    with pytest.raises(wireless.WirelessError, match="SIDETAP_UDID"):
        wireless.enable_wifi_connections(confirm=True)
    call.assert_not_called()
    monkeypatch.setattr(config, "SIDETAP_UDID", "selected-phone")
    with pytest.raises(wireless.WirelessError, match="USB"):
        wireless.enable_wifi_connections(confirm=True)
    call.assert_called_once_with(["usbmux", "list", "--usb", "--simple"])


def test_explicit_wifi_enable_uses_only_selected_existing_usb(monkeypatch):
    commands = []
    def runner(args, timeout=10):
        commands.append(args)
        return ["other-phone", "selected-phone"] if "--simple" in args else {"ok": True}
    monkeypatch.setattr(wireless, "_run", runner)
    assert "enabled" in wireless.enable_wifi_connections(confirm=True)
    assert commands == [["usbmux", "list", "--usb", "--simple"],
                        ["lockdown", "wifi-connections", "on", "--udid=selected-phone"]]


def test_wifi_direct_hid_pins_device_and_uses_real_coredevice_cli(monkeypatch):
    wifi_mode(monkeypatch)
    monkeypatch.setattr(coredevice.wireless, "require_wifi", lambda: "selected-phone")
    monkeypatch.setattr(coredevice.wda_client, "stop_engaged", lambda: False)
    monkeypatch.setattr(coredevice.wda_client, "_append_activity", lambda _: None)
    run = Mock(return_value=subprocess.CompletedProcess([], 0, "", ""))
    monkeypatch.setattr(coredevice.subprocess, "run", run)
    coredevice.direct_tap(.5, .5)
    assert run.call_args.kwargs["env"]["PYMOBILEDEVICE3_UDID"] == "selected-phone"
    assert run.call_args.args[0][-1] == "--userspace"
    assert "universal-hid-service" in run.call_args.args[0]


def test_wifi_direct_hid_never_runs_without_wifi_proof(monkeypatch):
    wifi_mode(monkeypatch)
    monkeypatch.setattr(coredevice.wireless, "require_wifi",
                        lambda: (_ for _ in ()).throw(wireless.WirelessError("not verified")))
    monkeypatch.setattr(coredevice.wda_client, "stop_engaged", lambda: False)
    run = Mock()
    monkeypatch.setattr(coredevice.subprocess, "run", run)
    with pytest.raises(coredevice.CoreDeviceError, match="not verified"):
        coredevice.direct_tap(.5, .5)
    run.assert_not_called()


def test_stop_blocks_wifi_before_network_discovery(monkeypatch):
    wifi_mode(monkeypatch)
    monkeypatch.setattr(coredevice.wda_client, "stop_engaged", lambda: True)
    probe = Mock()
    monkeypatch.setattr(coredevice.wireless, "require_wifi", probe)
    with pytest.raises(coredevice.CoreDeviceError, match="STOP"):
        coredevice.direct_tap(.5, .5)
    probe.assert_not_called()


def test_wireless_diagnostics_readonly_and_separates_discovery(monkeypatch):
    wifi_mode(monkeypatch)
    calls = []
    def runner(args, timeout=10):
        calls.append(args)
        return ["selected-phone"] if "usbmux" in args else [
            {"udid": "selected-phone"}]
    monkeypatch.setattr(wireless, "_run", runner)
    result = wireless.discovery()
    assert result["pin_matches_wifi"] is True
    assert result["bonjour"] == ["selected-phone"]
    assert all("wifi-connections" not in q for q in calls)

def test_wifi_capture_never_reads_other_wda_session(monkeypatch):
    from phone_harness import capture
    wifi_mode(monkeypatch)
    monkeypatch.setattr(capture, "_last_png", b"stale-WDA-pixels")
    monkeypatch.setattr(capture, "_last_transport", ("usb", False))
    monkeypatch.setattr(capture, "_last_at", capture.time.time())
    trusted = Mock(return_value="selected-phone")
    wifi_frame = Mock(return_value=b"verified-wifi-pixels")
    old_wda = Mock(side_effect=AssertionError("WDA must not be used in Wi-Fi direct mode"))
    monkeypatch.setattr(capture.wireless, "require_wifi", trusted)
    monkeypatch.setattr(capture, "_go_ios_screenshot", wifi_frame)
    monkeypatch.setattr(capture, "_wda_screenshot", old_wda)
    frame = capture.screenshot_png(max_age=20)
    assert frame == b"verified-wifi-pixels"
    old_wda.assert_not_called()
    wifi_frame.assert_called_once()
    trusted.assert_called_once()

def test_wireless_enable_accepts_empty_successful_cli_output(monkeypatch):
    proc = subprocess.CompletedProcess([], 0, "", "")
    monkeypatch.setattr(wireless.subprocess, "run", lambda *a, **kw: proc)
    assert wireless._run(["lockdown", "wifi-connections", "on"]) is None


def test_admin_wifi_mode_refuses_stale_go_ios_enumeration(monkeypatch):
    from phone_harness import admin
    wifi_mode(monkeypatch)
    monkeypatch.setattr(wireless, "status", lambda: {"ready": True, "reason": "Wi-Fi paired"})
    monkeypatch.setattr(admin.device, "list_devices", lambda: [])
    ok, detail, action = admin._check_device()
    assert not ok
    assert "go-ios" in detail
    assert "CoreDevice" in action


def test_admin_wifi_mode_accepts_selected_device_in_go_ios(monkeypatch):
    from phone_harness import admin
    wifi_mode(monkeypatch)
    monkeypatch.setattr(wireless, "status", lambda: {"ready": True, "reason": "Wi-Fi paired"})
    monkeypatch.setattr(admin.device, "list_devices", lambda: ["selected-phone"])
    ok, detail, fix = admin._check_device()
    assert ok and "verified paired Wi-Fi" in detail and fix == ""


def test_admin_wifi_mode_rejects_unverified_lockdown(monkeypatch):
    from phone_harness import admin
    wifi_mode(monkeypatch)
    monkeypatch.setattr(wireless, "status", lambda: {"ready": False, "reason": "Wi-Fi missing"})
    enumerated = Mock()
    monkeypatch.setattr(admin.device, "list_devices", enumerated)
    ok, detail, fix = admin._check_device()
    assert not ok and "Wi-Fi" in detail and "Wi-Fi missing" in fix
    enumerated.assert_not_called()
