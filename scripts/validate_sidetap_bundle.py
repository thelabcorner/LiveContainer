#!/usr/bin/env python3
"""Read-only IPA structure audit for the one-slot SideTap experiment.

Structural validation is not proof of Apple signing, XCTest startup or slot count.
No IPA contents are installed or executed.
"""
from __future__ import annotations

import argparse
import json
import plistlib
import sys
import zipfile
from pathlib import Path, PurePosixPath


def inspect_ipa(path: Path, *, require_wda: bool = False) -> dict:
    errors: list[str] = []
    warnings: list[str] = []
    with zipfile.ZipFile(path) as archive:
        names = [entry.filename for entry in archive.infolist() if not entry.is_dir()]
        indexed = set(names)
        if len(names) != len(indexed):
            errors.append("Duplicate ZIP member paths: not safe to package")
        for name in names:
            parts = PurePosixPath(name).parts
            if name.startswith("/") or ".." in parts or "\\" in name:
                errors.append(f"Unsafe ZIP path: {name}")
        apps = sorted(
            {parts[1] for name in names if (parts := PurePosixPath(name).parts)
             and len(parts) > 2 and parts[0] == "Payload" and parts[1].endswith(".app")}
        )
        if apps != ["LiveContainer.app"]:
            errors.append(f"Expected one native Payload/LiveContainer.app; found {apps!r}")

        host = "Payload/LiveContainer.app/"
        def plist_at(name: str) -> dict | None:
            if name not in indexed:
                errors.append(f"Missing {name}")
                return None
            try:
                value = plistlib.loads(archive.read(name))
                if not isinstance(value, dict):
                    raise ValueError("not a plist dictionary")
                return value
            except (ValueError, plistlib.InvalidFileException) as exc:
                errors.append(f"Unreadable {name}: {exc}")
                return None

        info = plist_at(host + "Info.plist")
        host_id = info.get("CFBundleIdentifier") if info is not None else None
        if host_id != "com.kdt.livecontainer":
            errors.append(f"Original host bundle ID not preserved: {host_id!r}")
        if info is not None:
            exe = info.get("CFBundleExecutable")
            if not isinstance(exe, str) or (host + exe) not in indexed:
                errors.append("Missing declared LiveContainer host executable")

        sidestore = host + "Frameworks/SideStoreApp.framework/"
        if not any(name.startswith(sidestore) for name in names):
            errors.append("Embedded SideStore framework not present")

        test_paths = sorted({
            "/".join(name.split("/")[:i + 1]) + "/"
            for name in names
            for i, part in enumerate(name.split("/"))
            if part.endswith(".xctest")
        })
        for prefix in test_paths:
            if not prefix.startswith(host + "PlugIns/"):
                errors.append("XCTest bundle not embedded in the principal app: " + prefix)
                continue
            bundle = plist_at(prefix + "Info.plist")
            if bundle is not None:
                executable = bundle.get("CFBundleExecutable")
                if not isinstance(executable, str) or (prefix + executable) not in indexed:
                    errors.append("XCTest bundle missing declared executable: " + prefix)

        if require_wda and not any("WebDriverAgent" in name for name in test_paths):
            errors.append("WDA XCTest bundle required but not found in host app")
        if not test_paths:
            warnings.append("No XCTest bundle: baseline LC+SideStore or WDA-free transport only")
        warnings.append("Signatures, entitlements, provisioning, XCTest bootstrap and actual installed slot count require separate device/CI verification")

    return {
        "valid_structure": not errors,
        "host_bundle_id": host_id,
        "native_apps": apps,
        "xctest_bundles": test_paths,
        "errors": errors,
        "warnings": warnings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ipa", type=Path)
    parser.add_argument("--require-wda", action="store_true")
    args = parser.parse_args()
    try:
        result = inspect_ipa(args.ipa, require_wda=args.require_wda)
    except (OSError, zipfile.BadZipFile) as exc:
        print(json.dumps({"valid_structure": False, "errors": [str(exc)]}))
        return 2
    print(json.dumps(result, indent=2))
    return 0 if result["valid_structure"] else 1


if __name__ == "__main__":
    sys.exit(main())
