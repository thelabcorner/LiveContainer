"""Static iOS integration invariants; Xcode compilation still required separately."""
from __future__ import annotations

import json
import plistlib
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_sidetap_button_opens_full_app_not_status_panel():
    source = (ROOT / "LiveContainerSwiftUI/Views/AppList/LCAppListView.swift").read_text()
    assert "LCUtils.openSideStore(delegate: self)" in source
    sidestore = source.index("LCUtils.openSideStore(delegate: self)")
    sidetap = source.index("sideTapAppPresent = true")
    assert sidestore < sidetap
    assert ".fullScreenCover(isPresented: $sideTapAppPresent)" in source
    assert "SideTapAppView(isPresented: $sideTapAppPresent)" in source
    assert "sideTapPanelPresent" not in source
    assert "Image(\"SideTap\")" in source


def test_real_sidetap_icon_packaged_for_ios():
    root = ROOT / "Resources/Assets.xcassets/SideTap.imageset"
    info = json.loads((root / "Contents.json").read_text())
    by_scale = {x["scale"]: x["filename"] for x in info["images"]}
    assert set(by_scale) == {"1x", "2x", "3x"}
    for scale, expected in [(1, 64), (2, 128), (3, 256)]:
        png = (root / by_scale[f"{scale}x"]).read_bytes()
        assert png.startswith(b"\x89PNG\r\n\x1a\n")
        assert struct.unpack(">II", png[16:24]) == (expected, expected)
    assert (ROOT / "SideTapIntegration/SideTap/assets/sidetap.ico").is_file()


def test_pinned_tls_and_no_external_web_navigation():
    swift = (ROOT / "LiveContainerSwiftUI/Views/AppList/SideTapAppView.swift").read_text()
    assert 'components.scheme?.lowercased() == "https"' in swift
    assert "SecCertificateCopyData(certificate)" in swift
    assert "SHA256.hash(data: bytes)" in swift
    assert "actual == fingerprint" in swift
    assert "target.scheme == \"https\"" in swift
    assert "target.host?.lowercased() == url.host?.lowercased()" in swift
    assert "decisionHandler(.cancel)" in swift
    assert "SideTapVerifiedWebView(url: url, fingerprint: fingerprint)" in swift
    assert "WKWebView" in swift
    assert "iPhone control companion" not in swift  # reject the old placeholder status sheet


def test_existing_app_identity_and_network_permission_preserved():
    plist = plistlib.loads((ROOT / "LiveContainer/Info.plist").read_bytes())
    assert plist["CFBundleIdentifier"] == "$(PRODUCT_BUNDLE_IDENTIFIER)"
    assert "SideTap" in plist["NSLocalNetworkUsageDescription"]
    script = (ROOT / ".github/build_github.sh").read_text()
    assert "SideStoreApp.framework" in script
    assert "SideStore.ipa" in script


def test_windows_companion_does_not_auto_start_or_open_phone():
    source = (ROOT / "SideTapIntegration/SideTap/src/phone_harness/run.py").read_text()
    assert 'if cmd == "companion":' in source
    assert "return companion.main(args[1:])" in source
    config = (ROOT / "SideTapIntegration/SideTap/src/phone_harness/companion.py").read_text()
    assert "secrets.token_urlsafe" in config
    assert "SSLContext" in config
    assert '"127.0.0.1", config.VIEWER_PORT' in config
    assert 'data["mjpeg"] = None' in config
    assert "SameSite=Strict" in config
    assert "serve_forever()" in config
