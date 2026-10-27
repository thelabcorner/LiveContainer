from __future__ import annotations
import subprocess
import pytest

from phone_harness import config, ddi_recovery, wireless


def test_ddi_never_runs_without_explicit_approval(monkeypatch):
    monkeypatch.setattr(ddi_recovery.subprocess, "run",
                        lambda *a, **k: pytest.fail("not authorized"))
    with pytest.raises(ddi_recovery.DDIMountError, match="--confirm"):
        ddi_recovery.mount()


def test_ddi_refuses_unverified_wifi(monkeypatch):
    monkeypatch.setattr(config, "SIDETAP_UDID", "selected")
    monkeypatch.setattr(wireless, "require_wifi",
                        lambda: (_ for _ in ()).throw(wireless.WirelessError("not paired")))
    monkeypatch.setattr(ddi_recovery.subprocess, "run",
                        lambda *a, **k: pytest.fail("must not start"))
    with pytest.raises(ddi_recovery.DDIMountError, match="not paired"):
        ddi_recovery.mount(confirm=True)


def test_ddi_explicitly_pins_wifi_target_and_official_transport(monkeypatch):
    monkeypatch.setattr(config, "SIDETAP_UDID", "selected")
    monkeypatch.setattr(wireless, "require_wifi", lambda: "selected")
    commands = []
    def run(args, **kwargs):
        commands.append(args)
        assert args[1:] == ["-m", "pymobiledevice3", "mounter", "auto-mount",
                            "--userspace", "--udid", "selected"]
        assert kwargs["timeout"] == 150
        return subprocess.CompletedProcess(args, 0, "", "")
    monkeypatch.setattr(ddi_recovery.subprocess, "run", run)
    result = ddi_recovery.mount(confirm=True)
    assert result == {"mounted": True, "transport": "paired-wifi-userspace",
                      "device_identity_verified": True}
    assert len(commands) == 1


def test_ddi_fail_closed_without_exposing_internal_device_output(monkeypatch):
    monkeypatch.setattr(config, "SIDETAP_UDID", "selected")
    monkeypatch.setattr(wireless, "require_wifi", lambda: "selected")
    monkeypatch.setattr(ddi_recovery.subprocess, "run",
                        lambda args, **kw: subprocess.CompletedProcess(
                            args, 1, "", "Private pairing record content"))
    with pytest.raises(ddi_recovery.DDIMountError) as exc:
        ddi_recovery.mount(confirm=True)
    assert "Private" not in str(exc.value)
