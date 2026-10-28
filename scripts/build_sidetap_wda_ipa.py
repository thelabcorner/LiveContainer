#!/usr/bin/env python3
"""Produce a single-app LiveContainer + SideStore + SideTap + embedded WDA IPA.

This stages Appium's real device XCTest bundle under the existing LiveContainer
host identity; it NEVER packages or installs a second principal .app. It does
not assert that Apple's testmanagerd will accept this host as an XCTest runner.
The resulting IPA must be re-signed by the normal LiveContainer installer.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import plistlib
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

HOST = "Payload/LiveContainer.app/"
PLUGIN = HOST + "PlugIns/WebDriverAgentRunner.xctest/"
WDA_VERSION = "v13.2.0"
WDA_SHA256 = "448ffe591cf64abf7ff0751897b6860cd45b8032b39677a5dd79f827c4d781cc"
WDA_PREFIXES = (
    "WebDriverAgentRunner-Runner.app/PlugIns/WebDriverAgentRunner.xctest/",
    "Payload/WebDriverAgentRunner-Runner.app/PlugIns/WebDriverAgentRunner.xctest/",
)
MAX_UNCOMPRESSED = 350 * 1024 * 1024


class PackagingError(ValueError):
    pass


def _index(archive: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
    result = {}
    total = 0
    for info in archive.infolist():
        name = info.filename
        parts = PurePosixPath(name).parts
        if name.startswith("/") or "\\" in name or ".." in parts or not parts:
            raise PackagingError("Unsafe ZIP path: " + name)
        if (info.external_attr >> 16) & 0o170000 == 0o120000:
            raise PackagingError("ZIP symlink not permitted: " + name)
        if info.flag_bits & 1:
            raise PackagingError("Encrypted archive member: " + name)
        if name in result:
            raise PackagingError("Duplicate ZIP member: " + name)
        result[name] = info
        total += info.file_size
        if total > MAX_UNCOMPRESSED:
            raise PackagingError("Expanded archive exceeds resource limit")
    return result


def _plist(archive: zipfile.ZipFile, name: str) -> dict:
    try:
        data = plistlib.loads(archive.read(name))
    except (KeyError, ValueError, plistlib.InvalidFileException) as exc:
        raise PackagingError("Missing or invalid plist: " + name) from exc
    if not isinstance(data, dict):
        raise PackagingError("Expected dictionary plist: " + name)
    return data


def package(host: Path, wda: Path, output: Path, *, check_hash: bool = True) -> dict:
    if not host.is_file() or not wda.is_file():
        raise PackagingError("Host IPA and WDA ZIP must exist")
    if output.exists() or output.resolve() in (host.resolve(), wda.resolve()):
        raise PackagingError("Output must be new and separate from both inputs")
    if output.suffix.lower() != ".ipa":
        raise PackagingError("Expected an .ipa output")
    actual_hash = hashlib.sha256(wda.read_bytes()).hexdigest()
    if check_hash and actual_hash != WDA_SHA256:
        raise PackagingError("Appium WDA archive SHA-256 differs from pinned official asset")
    with zipfile.ZipFile(host) as source, zipfile.ZipFile(wda) as driver:
        h, w = _index(source), _index(driver)
        apps = {n.split("/")[1] for n in h if n.startswith("Payload/")
                and len(n.split("/")) > 2 and n.split("/")[1].endswith(".app")}
        if apps != {"LiveContainer.app"}:
            raise PackagingError("Expected exactly one principal LiveContainer.app")
        metadata = _plist(source, HOST + "Info.plist")
        if metadata.get("CFBundleIdentifier") != "com.kdt.livecontainer":
            raise PackagingError("Host bundle ID changed; would break upgrade identity")
        exe = metadata.get("CFBundleExecutable")
        if not isinstance(exe, str) or HOST + exe not in h:
            raise PackagingError("Host executable missing")
        if not any(n.startswith(HOST + "Frameworks/SideStoreApp.framework/") for n in h):
            raise PackagingError("Built-in SideStore missing")
        if any(".xctest/" in n for n in h):
            raise PackagingError("Host already contains an XCTest bundle")

        prefix = next((p for p in WDA_PREFIXES if p + "Info.plist" in w), None)
        if prefix is None:
            raise PackagingError("Official WebDriverAgentRunner.xctest absent")
        wda_info = _plist(driver, prefix + "Info.plist")
        runner = wda_info.get("CFBundleExecutable")
        if (not isinstance(runner, str) or prefix + runner not in w
                or wda_info.get("CFBundlePackageType") != "BNDL"):
            raise PackagingError("Actual WDA XCTest runner executable absent")
        lib = prefix + "Frameworks/WebDriverAgentLib.framework/"
        if lib + "WebDriverAgentLib" not in w:
            raise PackagingError("WDA library framework absent")
        nested = sorted(n for n in w if n.startswith(prefix) and not n.endswith("/")
                        and ".dSYM/" not in n)
        written = {PLUGIN + name[len(prefix):] for name in nested}
        if any(n in h for n in written):
            raise PackagingError("Nested WDA collides with host")
        metadata["LCEmbeddedWDARunner"] = {
            "TestBundle": "WebDriverAgentRunner.xctest",
            "WDARelease": WDA_VERSION,
            "WDAArchiveSHA256": actual_hash,
            "XCTestBootstrapVerified": False,
        }
        output.parent.mkdir(parents=True, exist_ok=True)
        # Do not leave partially assembled IPAs after a failed write.
        tmp = None
        try:
            with tempfile.NamedTemporaryFile(prefix=".wda-", suffix=".ipa",
                                             dir=output.parent, delete=False) as handle:
                tmp = Path(handle.name)
            with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED,
                                 compresslevel=6, allowZip64=True) as target:
                for name, info in h.items():
                    if name == HOST + "Info.plist":
                        target.writestr(name, plistlib.dumps(metadata, fmt=plistlib.FMT_BINARY))
                    else:
                        target.writestr(info, source.read(name))
                for name in nested:
                    target.writestr(PLUGIN + name[len(prefix):], driver.read(name))
            with zipfile.ZipFile(tmp) as verify:
                members = _index(verify)
                if PLUGIN + runner not in members or PLUGIN + "Info.plist" not in members:
                    raise PackagingError("Output lost WDA executable")
            os.replace(tmp, output)
        finally:
            if tmp is not None:
                tmp.unlink(missing_ok=True)

    return {
        "artifact": str(output),
        "principal_app": "com.kdt.livecontainer",
        "principal_app_count": 1,
        "wda_release": WDA_VERSION,
        "wda_sha256": actual_hash,
        "embedded_wda_bundle": PLUGIN,
        "embedded_wda_files": len(nested),
        "requires_normal_install_resigning": True,
        "xctest_bootstrap_verified": False,
        "cross_app_control_verified": False,
        "additional_apple_app_slot": "not requested; device confirmation pending",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", type=Path, required=True)
    parser.add_argument("--wda", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(package(args.host, args.wda, args.out), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
