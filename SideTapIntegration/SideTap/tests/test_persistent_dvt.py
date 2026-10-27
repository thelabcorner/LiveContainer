"""Persistent SideTap DVT screenshot transport tests; no physical phone needed."""
from __future__ import annotations

import asyncio
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from phone_harness import persistent_dvt


def test_connection_reused_for_many_frames(monkeypatch):
    opened = []
    samples = []
    async def fake_open(self, udid):
        opened.append(udid)
        async def shot():
            samples.append(time.perf_counter())
            return b"frame"
        self._selected = udid
        self._service = SimpleNamespace(get_screenshot=shot)
    monkeypatch.setattr(persistent_dvt.PersistentDvtCapture, "_open", fake_open)
    worker = persistent_dvt.PersistentDvtCapture()
    try:
        assert worker.get_screenshot("phone-A") == b"frame"
        assert worker.get_screenshot("phone-A") == b"frame"
        assert worker.get_screenshot("phone-A") == b"frame"
        assert opened == ["phone-A"]
        assert len(samples) == 3
    finally:
        worker.close()


def test_selected_device_change_forces_new_connection(monkeypatch):
    opened = []
    async def fake_open(self, udid):
        opened.append(udid)
        async def shot():
            return udid.encode()
        self._selected = udid
        self._service = SimpleNamespace(get_screenshot=shot)
    monkeypatch.setattr(persistent_dvt.PersistentDvtCapture, "_open", fake_open)
    worker = persistent_dvt.PersistentDvtCapture()
    try:
        assert worker.get_screenshot("phone-A") == b"phone-A"
        assert worker.get_screenshot("phone-B") == b"phone-B"
        assert opened == ["phone-A", "phone-B"]
    finally:
        worker.close()


def test_failed_read_invalidates_session_and_requires_reconnect(monkeypatch):
    opened = []
    async def fake_open(self, udid):
        opened.append(udid)
        async def shot():
            if len(opened) == 1:
                raise ConnectionError("link dropped")
            return b"recovered"
        self._selected = udid
        self._service = SimpleNamespace(get_screenshot=shot)
    monkeypatch.setattr(persistent_dvt.PersistentDvtCapture, "_open", fake_open)
    worker = persistent_dvt.PersistentDvtCapture()
    try:
        with pytest.raises(persistent_dvt.PersistentCaptureError, match="ConnectionError"):
            worker.get_screenshot("phone-A")
        assert worker.get_screenshot("phone-A") == b"recovered"
        assert opened == ["phone-A", "phone-A"]
    finally:
        worker.close()


def test_concurrent_http_requests_share_one_connection_and_serialize_screenshots(monkeypatch):
    opened = []
    in_flight = 0
    peak = 0
    async def fake_open(self, udid):
        opened.append(udid)
        async def shot():
            nonlocal in_flight, peak
            in_flight += 1
            peak = max(peak, in_flight)
            await asyncio.sleep(.02)
            in_flight -= 1
            return b"frame"
        self._selected = udid
        self._service = SimpleNamespace(get_screenshot=shot)
    monkeypatch.setattr(persistent_dvt.PersistentDvtCapture, "_open", fake_open)
    worker = persistent_dvt.PersistentDvtCapture()
    results = []
    try:
        threads = [threading.Thread(target=lambda: results.append(worker.get_screenshot("phone-A")))
                   for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)
            assert not thread.is_alive()
        assert len(results) == 4
        assert all(x == b"frame" for x in results)
        assert opened == ["phone-A"]
        assert peak == 1
    finally:
        worker.close()


def test_worker_rejects_bad_identity_and_use_after_close():
    worker = persistent_dvt.PersistentDvtCapture()
    for value in ("", "phone A", None, 7):
        with pytest.raises(persistent_dvt.PersistentCaptureError):
            worker.get_screenshot(value)
    worker.close()
    with pytest.raises(persistent_dvt.PersistentCaptureError, match="closed"):
        worker.get_screenshot("phone-A")


def test_open_requires_pinned_network_only_preflight(monkeypatch):
    from phone_harness import wireless
    worker = persistent_dvt.PersistentDvtCapture()
    calls = []
    def verify():
        calls.append("preflight")
        raise wireless.WirelessError("Wi-Fi not verified")
    monkeypatch.setattr(wireless, "require_wifi", verify)
    try:
        with pytest.raises(persistent_dvt.PersistentCaptureError):
            worker.get_screenshot("phone-A", timeout=5)
        assert calls == ["preflight"]
    finally:
        worker.close()
