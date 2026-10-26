from __future__ import annotations

import subprocess
from unittest.mock import Mock

import pytest

from phone_harness import coredevice


@pytest.fixture(autouse=True)
def opt_in_test(monkeypatch):
    monkeypatch.setattr(coredevice.config, "get", lambda k, d=None: "1" if k == "SIDETAP_DIRECT_ENABLE" else d)
    monkeypatch.setattr(coredevice.config, "SIDETAP_UDID", "phone")
    monkeypatch.setattr(coredevice.device, "list_devices", lambda: ["phone"])
    monkeypatch.setattr(coredevice.wda_client, "stop_engaged", lambda: False)
    monkeypatch.setattr(coredevice.wda_client, "_append_activity", lambda _: None)


def test_disabled_by_default_fails_closed(monkeypatch):
    run = Mock()
    monkeypatch.setattr(coredevice.subprocess, "run", run)
    monkeypatch.setattr(coredevice.config, "get", lambda k, d=None: d)
    assert not coredevice.direct_status()["ready"]
    with pytest.raises(coredevice.CoreDeviceError, match="disabled"):
        coredevice.direct_tap(.5, .5)
    run.assert_not_called()


def test_stop_blocks_actions(monkeypatch):
    run = Mock()
    monkeypatch.setattr(coredevice.subprocess, "run", run)
    monkeypatch.setattr(coredevice.wda_client, "stop_engaged", lambda: True)
    for call in (lambda: coredevice.direct_tap(.5, .5),
                 lambda: coredevice.direct_drag(.1, .9, .1, .1),
                 lambda: coredevice.direct_type_ascii("hello")):
        with pytest.raises(coredevice.CoreDeviceError, match="STOP"):
            call()
    run.assert_not_called()


@pytest.mark.parametrize("devices", [[], ["other"], ["phone", "other"]])
def test_refuses_ambiguous_device(monkeypatch, devices):
    monkeypatch.setattr(coredevice.device, "list_devices", lambda: devices)
    run = Mock()
    monkeypatch.setattr(coredevice.subprocess, "run", run)
    with pytest.raises(coredevice.CoreDeviceError):
        coredevice.direct_tap(.5, .5)
    run.assert_not_called()


def test_duplicate_enumeration_safe(monkeypatch):
    monkeypatch.setattr(coredevice.device, "list_devices", lambda: ["phone", "phone"])
    assert coredevice.direct_status()["ready"]


@pytest.mark.parametrize("x", [-1, 2, float("nan"), float("inf"), True, "1"])
def test_rejects_invalid_coordinates(x):
    with pytest.raises(ValueError):
        coredevice.direct_tap(x, .5)


def test_tap_uses_normalized_coordinates_and_userspace(monkeypatch):
    run = Mock(return_value=subprocess.CompletedProcess([], 0, "", ""))
    monkeypatch.setattr(coredevice.subprocess, "run", run)
    coredevice.direct_tap(.5, 1.0)
    cmd = run.call_args.args[0]
    assert cmd[0] == coredevice.sys.executable
    assert cmd[2] == "pymobiledevice3"
    assert cmd[6:9] == ["tap", "32768", "65535"]
    assert cmd[-1] == "--userspace"


def test_drag_is_contact_drag_not_pointer_swipe(monkeypatch):
    run = Mock(return_value=subprocess.CompletedProcess([], 0, "", ""))
    monkeypatch.setattr(coredevice.subprocess, "run", run)
    coredevice.direct_drag(0.1, 0.2, 0.8, 0.9)
    assert run.call_args.args[0][6] == "drag"


def test_type_redacts_contents_from_activity(monkeypatch):
    run = Mock(return_value=subprocess.CompletedProcess([], 0, "", ""))
    activity = Mock()
    monkeypatch.setattr(coredevice.subprocess, "run", run)
    monkeypatch.setattr(coredevice.wda_client, "_append_activity", activity)
    coredevice.direct_type_ascii("secret!")
    assert run.call_args.args[0][7] == "secret!"
    assert "secret!" not in activity.call_args.args[0]


@pytest.mark.parametrize("text", ["", "café", "🙂", "a" * 1025, "\x00"])
def test_type_rejects_unsupported_characters(text):
    with pytest.raises(ValueError):
        coredevice.direct_type_ascii(text)


def test_timeout_never_auto_replays(monkeypatch):
    def timeout(*a, **kw):
        raise subprocess.TimeoutExpired("pymobiledevice3", 1)
    monkeypatch.setattr(coredevice.subprocess, "run", timeout)
    with pytest.raises(coredevice.CoreDeviceError, match="Delivery unknown"):
        coredevice.direct_tap(.5, .5)


def test_failed_delivery_not_logged_as_success(monkeypatch):
    activity = Mock()
    monkeypatch.setattr(coredevice.wda_client, "_append_activity", activity)
    monkeypatch.setattr(coredevice.subprocess, "run",
                        lambda *a, **kw: subprocess.CompletedProcess([], 1, "", "denied"))
    with pytest.raises(coredevice.CoreDeviceError, match="denied"):
        coredevice.direct_tap(.5, .5)
    activity.assert_not_called()
