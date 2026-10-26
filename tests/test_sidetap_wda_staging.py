"""Tests for strictly offline staging of official Appium WDA source."""
from __future__ import annotations

import importlib.util
import plistlib
import zipfile
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "scripts/stage_sidetap_wda_research.py"
spec = importlib.util.spec_from_file_location("wda_stage", SRC)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def _write_zip(path: Path, items: dict[str, bytes]):
    with zipfile.ZipFile(path, "w") as z:
        for name, content in items.items():
            z.writestr(name, content)


def _host(path):
    _write_zip(path, {
        "Payload/LiveContainer.app/Info.plist": plistlib.dumps({"CFBundleIdentifier": "com.kdt.livecontainer"}),
        "Payload/LiveContainer.app/LiveContainer": b"binary",
        "Payload/LiveContainer.app/Frameworks/SideStoreApp.framework/SideStore": b"embedded",
    })


def _wda(path, *, nested: bool = True):
    prefix = "WebDriverAgentRunner-Runner.app/PlugIns/WebDriverAgentRunner.xctest/"
    files = {prefix + "Info.plist": plistlib.dumps({"CFBundleExecutable": "WebDriverAgentRunner"}),
             prefix + "WebDriverAgentRunner": b"binary",
             prefix + "Frameworks/WebDriverAgentLib.framework/WebDriverAgentLib": b"lib"} if nested else {}
    _write_zip(path, files)


def test_stages_only_nested_xctest_not_standalone_app(tmp_path):
    h, w, out = (tmp_path / x for x in ("host.ipa", "wda.zip", "combined.research.ipa"))
    _host(h)
    _wda(w)
    report = module.stage(h, w, out)
    assert report["principal_app_count"] == 1
    assert report["bootstrap_verified"] is False
    assert report["status"] == "RESEARCH_ONLY_UNSIGNED_NOT_INSTALLABLE"
    with zipfile.ZipFile(out) as z:
        names = z.namelist()
        assert any(x.startswith(module.DEST) for x in names)
        assert not any(x.startswith("Payload/WebDriverAgentRunner-Runner.app") for x in names)
        assert "Payload/LiveContainer.app/Frameworks/SideStoreApp.framework/SideStore" in names


@pytest.mark.parametrize("outname", ["wrong.ipa", "combined.zip", "wda.ipa"])
def test_research_only_output_suffix_required(tmp_path, outname):
    h, w = tmp_path / "host.ipa", tmp_path / "wda.zip"
    _host(h); _wda(w)
    with pytest.raises(module.StagingError, match="research"):
        module.stage(h, w, tmp_path / outname)


def test_missing_wda_test_bundle_rejected(tmp_path):
    h, w, out = (tmp_path / x for x in ("host.ipa", "wda.zip", "out.research.ipa"))
    _host(h); _wda(w, nested=False)
    with pytest.raises(module.StagingError, match="XCTest"):
        module.stage(h, w, out)
    assert not out.exists()


def test_rejects_duplicate_archive_entries(tmp_path):
    h, w, out = (tmp_path / x for x in ("host.ipa", "wda.zip", "out.research.ipa"))
    _host(h); _wda(w)
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(h, "a") as z:
            z.writestr("Payload/LiveContainer.app/Info.plist", b"not-a-plist")
    with pytest.raises(module.StagingError, match="Duplicate"):
        module.stage(h, w, out)


def test_refuses_overwrite(tmp_path):
    h, w, out = (tmp_path / x for x in ("host.ipa", "wda.zip", "out.research.ipa"))
    _host(h); _wda(w)
    out.write_bytes(b"protected")
    with pytest.raises(module.StagingError, match="exists"):
        module.stage(h, w, out)
    assert out.read_bytes() == b"protected"


def test_rejects_second_principal_app(tmp_path):
    h, w, out = (tmp_path / x for x in ("host.ipa", "wda.zip", "out.research.ipa"))
    _host(h); _wda(w)
    with zipfile.ZipFile(h, "a") as z:
        z.writestr("Payload/Other.app/Info.plist", plistlib.dumps({"CFBundleIdentifier": "other"}))
    with pytest.raises(module.StagingError, match="one principal"):
        module.stage(h, w, out)
