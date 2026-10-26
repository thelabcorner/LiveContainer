#!/usr/bin/env python3
"""Offline one-app XCTest staging experiment. NEVER produces a signed/usable IPA.

A single Payload/*.app is only a packaging invariant. It DOES NOT demonstrate
that iOS testmanagerd can launch WDA under LiveContainer's app identity.
This laboratory utility never modifies the original archive or the phone.
"""
from __future__ import annotations

import argparse
import json
import plistlib
import zipfile
from pathlib import Path, PurePosixPath

HOST = "Payload/LiveContainer.app/"
WDA_NAME = "WebDriverAgentRunner.xctest"
DEST = HOST + "PlugIns/" + WDA_NAME + "/"


class StagingError(ValueError):
    pass


def _members(archive: zipfile.ZipFile) -> set[str]:
    files = [e.filename for e in archive.infolist() if not e.is_dir()]
    if len(files) != len(set(files)):
        raise StagingError("Duplicate members in archive")
    for name in files:
        if name.startswith("/") or ".." in PurePosixPath(name).parts or "\\" in name:
            raise StagingError("Unsafe archive member " + name)
    return set(files)


def stage(host: Path, wda_archive: Path, output: Path) -> dict:
    for source in (host, wda_archive):
        if not source.is_file():
            raise StagingError("Missing input: " + str(source))
    if output.resolve() in (host.resolve(), wda_archive.resolve()):
        raise StagingError("Refusing to overwrite source")
    if output.suffix.lower() != ".ipa" or ".research." not in output.name:
        raise StagingError("Output must be named *.research.ipa to prevent accidental deployment")
    with zipfile.ZipFile(host) as h, zipfile.ZipFile(wda_archive) as w:
        hfiles, wfiles = _members(h), _members(w)
        hostinfo = HOST + "Info.plist"
        if hostinfo not in hfiles:
            raise StagingError("Not a LiveContainer IPA")
        info = plistlib.loads(h.read(hostinfo))
        if info.get("CFBundleIdentifier") != "com.kdt.livecontainer":
            raise StagingError("Unexpected LiveContainer bundle identifier")
        native_apps = {n.split("/")[1] for n in hfiles if n.startswith("Payload/") and
                       len(n.split("/")) > 2 and n.split("/")[1].endswith(".app")}
        if native_apps != {"LiveContainer.app"}:
            raise StagingError("Host must have one principal LiveContainer app")
        if not any(n.startswith(HOST + "Frameworks/SideStoreApp.framework/") for n in hfiles):
            raise StagingError("Built-in SideStore missing")
        if any(n.startswith(DEST) for n in hfiles):
            raise StagingError("XCTest already embedded")
        prefixes = [
            "WebDriverAgentRunner-Runner.app/PlugIns/" + WDA_NAME + "/",
            "Payload/WebDriverAgentRunner-Runner.app/PlugIns/" + WDA_NAME + "/",
        ]
        prefix = next((p for p in prefixes if p + "Info.plist" in wfiles), None)
        if prefix is None:
            raise StagingError("Real WDA nested XCTest bundle not found")
        plist = plistlib.loads(w.read(prefix + "Info.plist"))
        executable = plist.get("CFBundleExecutable")
        if not isinstance(executable, str) or prefix + executable not in wfiles:
            raise StagingError("WDA XCTest executable missing")
        nested = [n for n in sorted(wfiles) if n.startswith(prefix) and ".dSYM/" not in n]
        if not any(n.startswith(prefix + "Frameworks/WebDriverAgentLib.framework/") for n in nested):
            raise StagingError("WebDriverAgentLib.framework missing")
        existing = hfiles
        staged = {DEST + n[len(prefix):] for n in nested}
        if staged & existing:
            raise StagingError("WDA staging path collides with existing host files")
        if output.exists():
            raise StagingError("Output already exists; no implicit overwrite")
        output.parent.mkdir(parents=True, exist_ok=True)
        try:
            with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as target:
                for item in h.infolist():
                    if not item.is_dir():
                        target.writestr(item, h.read(item))
                for name in nested:
                    target.writestr(DEST + name[len(prefix):], w.read(name))
        except Exception:
            output.unlink(missing_ok=True)
            raise
    return {
        "status": "RESEARCH_ONLY_UNSIGNED_NOT_INSTALLABLE",
        "output": str(output),
        "principal_app_count": 1,
        "nested_test_bundle": DEST,
        "nested_files": len(nested),
        "bootstrap_verified": False,
        "slot_verified": False,
        "signing_verified": False,
        "warning": "Modified iOS app invalidates signatures. No XCTest runner launch has been demonstrated.",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--host", type=Path, required=True)
    ap.add_argument("--wda", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--research-only", action="store_true", required=True,
                    help="Acknowledge that no installable IPA is generated")
    args = ap.parse_args()
    print(json.dumps(stage(args.host, args.wda, args.out), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
