"""Persistent, bounded DVT screenshot connection for a single paired iPhone.

Runs the pymobiledevice3 userspace TCP/IP stack on one dedicated asyncio
thread. The Apple tunnel, DTX provider and screenshot channel stay connected
across read-only captures, avoiding full setup for every browser refresh.

No HTTP listener, exposed TCP port, Apple pairing mutation, additional app
slot or input capability. Only the configured UDID may be captured.
"""
from __future__ import annotations

import asyncio
import atexit
from contextlib import AsyncExitStack
from concurrent.futures import Future, TimeoutError as FutureTimeout
import threading
from typing import Any


class PersistentCaptureError(RuntimeError):
    pass


class PersistentDvtCapture:
    def __init__(self) -> None:
        self._boot_guard = threading.Lock()
        self._boot = threading.Event()
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._async_guard: asyncio.Lock | None = None
        self._stack: AsyncExitStack | None = None
        self._service: Any = None
        self._selected: str | None = None
        self._closed = False
        # Multiple viewer pages/MCP clients asking for the same moment must
        # share one DVT response, not queue redundant full-resolution captures.
        self._pending_guard = threading.Lock()
        self._pending: dict[str, Future[bytes]] = {}

    def _run_loop(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._async_guard = asyncio.Lock()
        self._loop = loop
        self._boot.set()
        try:
            loop.run_forever()
        finally:
            try:
                loop.run_until_complete(self._reset())
                loop.run_until_complete(loop.shutdown_asyncgens())
            finally:
                loop.close()

    def _ensure_running(self) -> asyncio.AbstractEventLoop:
        with self._boot_guard:
            if self._closed:
                raise PersistentCaptureError("Persistent screenshot capture is closed")
            if self._thread is None:
                thread = threading.Thread(
                    target=self._run_loop, name="SideTap-WiFi-DVT",
                    daemon=True,
                )
                self._thread = thread
                thread.start()
        if not self._boot.wait(timeout=3):
            raise PersistentCaptureError("Wireless screenshot event loop did not start")
        if self._loop is None or self._thread is None or not self._thread.is_alive():
            raise PersistentCaptureError("Wireless screenshot event loop terminated")
        return self._loop

    async def _reset(self) -> None:
        stack, self._stack = self._stack, None
        self._service = None
        self._selected = None
        if stack is not None:
            await stack.aclose()

    async def _open(self, udid: str) -> None:
        # A full paired, network-only lockdown proof is required on each
        # tunnel creation, NOT on each frame. This avoids repeated subprocess
        # discovery and guarantees that the new tunnel cannot start over USB.
        from . import wireless
        verified = await asyncio.wait_for(asyncio.to_thread(wireless.require_wifi), timeout=15)
        if verified != udid:
            raise PersistentCaptureError("Wireless preflight selected a different iPhone")
        # Import lazily to keep regular USB SideTap and tests independent of
        # optional pymobiledevice3 developer dependencies.
        from pymobiledevice3.remote.userspace_tunnel import UserspaceRsdTunnel
        from pymobiledevice3.services.dvt.instruments.dvt_provider import DvtProvider
        from pymobiledevice3.services.dvt.instruments.screenshot import Screenshot

        stack = AsyncExitStack()
        try:
            rsd = await asyncio.wait_for(
                stack.enter_async_context(UserspaceRsdTunnel(serial=udid, autopair=False)),
                timeout=12,
            )
            dvt = await asyncio.wait_for(stack.enter_async_context(DvtProvider(rsd)), timeout=8)
            shot = await asyncio.wait_for(stack.enter_async_context(Screenshot(dvt)), timeout=8)
        except BaseException:
            await stack.aclose()
            raise
        self._stack = stack
        self._service = shot
        self._selected = udid

    async def _capture(self, udid: str) -> bytes:
        assert self._async_guard is not None
        async with self._async_guard:
            if self._selected != udid:
                await self._reset()
            if self._service is None:
                await self._open(udid)
            try:
                # Each screenshot is read-only. A failed or cancelled request
                # invalidates its DTX channel so the next capture reconnects.
                return await asyncio.wait_for(self._service.get_screenshot(), timeout=10)
            except BaseException:
                await self._reset()
                raise

    def get_screenshot(self, udid: str, *, timeout: float = 34.0) -> bytes:
        if not isinstance(udid, str) or not udid or any(c.isspace() for c in udid):
            raise PersistentCaptureError("A pinned iPhone UDID is required")
        loop = self._ensure_running()
        coro = self._capture(udid)
        with self._pending_guard:
            if self._closed:
                coro.close()
                raise PersistentCaptureError("Persistent screenshot capture is closed")
            submitted = self._pending.get(udid)
            if submitted is None or submitted.done():
                try:
                    submitted = asyncio.run_coroutine_threadsafe(coro, loop)
                except BaseException:
                    coro.close()
                    raise
                self._pending[udid] = submitted
            else:
                # The first caller's request is already in flight; it owns
                # the result. Close this unused coroutine to avoid warnings.
                coro.close()
        try:
            data = submitted.result(timeout=timeout)
        except FutureTimeout as exc:
            submitted.cancel()
            raise PersistentCaptureError("Wireless DVT capture exceeded its deadline") from exc
        except Exception as exc:
            raise PersistentCaptureError(
                "Persistent wireless DVT capture failed: " + type(exc).__name__
            ) from exc
        finally:
            with self._pending_guard:
                if submitted.done() and self._pending.get(udid) is submitted:
                    self._pending.pop(udid, None)
        if not isinstance(data, bytes):
            raise PersistentCaptureError("DVT returned a non-bytes image")
        return data

    def close(self) -> None:
        with self._boot_guard:
            self._closed = True
            loop = self._loop
            thread = self._thread
        if loop is not None and loop.is_running():
            try:
                future = asyncio.run_coroutine_threadsafe(self._reset(), loop)
                future.result(timeout=3)
            except Exception:
                pass
            loop.call_soon_threadsafe(loop.stop)
            if thread is not None and threading.current_thread() != thread:
                thread.join(timeout=3)


_instance = PersistentDvtCapture()
atexit.register(_instance.close)


def screenshot(udid: str) -> bytes:
    return _instance.get_screenshot(udid)
