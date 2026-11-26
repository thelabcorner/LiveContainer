#!/usr/bin/env python3
"""Compile pinned patched SideStore in GitHub Actions; emit a verified .ipa.

Never ship the stale upstream nightly, never rewrite provisioning state, and
never use a local CPU. The resulting IPA remains subject to real device auth.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from patch_sidestore_authfix import (
    ANISETTEKIT_COMMIT, MARKETING_VERSION, SIDESIGN_COMMIT,
    SIDESTORE_COMMIT, patch_sources,
)

SOURCE_URL = "https://github.com/LiveContainer/SideStore.git"
PREBUILT_ARTIFACTS = (
    ("https___github_com_krzyzanowskim_OpenSSL_releases_download_3_6_2000_OpenSSL_xcframework_zip",
     "https://github.com/krzyzanowskim/OpenSSL/releases/download/3.6.2000/OpenSSL.xcframework.zip"),
    ("https___github_com_mahee96_unicorn_releases_download_2_1_4_multiarch_Unicorn_xcframework_zip",
     "https://github.com/mahee96/unicorn/releases/download/2.1.4-multiarch/Unicorn.xcframework.zip"),
)


def run(*cmd: str, cwd: Path | None = None) -> None:
    print("+ " + " ".join(cmd), flush=True)
    subprocess.run(list(cmd), cwd=cwd, check=True)


def prepare_binary_artifacts() -> None:
    cache_dir = Path.home() / "Library/Caches/org.swift.swiftpm/artifacts"
    cache_dir.mkdir(parents=True, exist_ok=True)
    for name, url in PREBUILT_ARTIFACTS:
        target = cache_dir / name
        if target.is_file() and target.stat().st_size > 0:
            continue
        temp = target.with_name(target.name + ".download")
        try:
            run("curl", "--fail", "--location", "--retry", "3", "--silent",
                "--show-error", url, "--output", str(temp))
            if not temp.is_file() or temp.stat().st_size == 0:
                raise RuntimeError("Missing binary artifact downloaded from " + url)
            os.replace(temp, target)
        finally:
            temp.unlink(missing_ok=True)


def build(output: Path) -> dict:
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise RuntimeError("All builds must run on GitHub Actions")
    output = output.resolve()
    if output.suffix != ".ipa" or output.exists():
        raise RuntimeError("Refusing to overwrite an existing output IPA")
    output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="side-authfix-", dir=output.parent) as temp:
        root = Path(temp) / "SideStore"
        run("git", "clone", "--single-branch", "--branch", "LiveContainerSupport",
            "--filter=blob:none", "--no-checkout", SOURCE_URL, str(root))
        run("git", "checkout", "--detach", SIDESTORE_COMMIT, cwd=root)
        run("git", "submodule", "update", "--init", "--recursive", cwd=root)
        changes = patch_sources(root, verify_git=True)
        print("PINNED_AUTH_PATCH " + json.dumps({
            "sidestore": SIDESTORE_COMMIT,
            "sidesign": SIDESIGN_COMMIT,
            "anisettekit": ANISETTEKIT_COMMIT,
            "changes": changes,
            "marketing_version": MARKETING_VERSION,
            "on_device_anisette_modified": False,
        }), flush=True)

        prepare_binary_artifacts()
        # Same macOS Xcode 27 runner and build recipe as upstream SideStore's CI.
        # Explicit version marker proves the installed binary is not the old nightly.
        run("make", "-B", "build", "MARKETING_VERSION=" + MARKETING_VERSION, cwd=root)
        run("make", "fakesign", "ipa", cwd=root)
        source_ipa = root / "SideStore.ipa"
        if not source_ipa.is_file():
            raise RuntimeError("Upstream build did not produce SideStore.ipa")
        with zipfile.ZipFile(source_ipa) as archive:
            members = set(archive.namelist())
            prefix = "Payload/SideStore.app/"
            if prefix + "SideStore" not in members or prefix + "Info.plist" not in members:
                raise RuntimeError("Patched SideStore missing executable or manifest")
            info = plistlib.loads(archive.read(prefix + "Info.plist"))
            if info.get("CFBundleIdentifier") != "com.SideStore.SideStore":
                raise RuntimeError("SideStore bundle identity changed")
            if info.get("CFBundleShortVersionString") != MARKETING_VERSION:
                raise RuntimeError(
                    "Compiled SideStore version marker missing: " +
                    str(info.get("CFBundleShortVersionString"))
                )
            if prefix + "PlugIns/AltWidgetExtension.appex/Info.plist" not in members:
                raise RuntimeError("Built-in SideStore widget unexpectedly missing")
        shutil.copyfile(source_ipa, output)
        digest = hashlib.sha256(output.read_bytes()).hexdigest()
        report = {
            "output": str(output),
            "sha256": digest,
            "size": output.stat().st_size,
            "sideStoreSource": SIDESTORE_COMMIT,
            "sideSignSource": SIDESIGN_COMMIT,
            "anisetteKitSource": ANISETTEKIT_COMMIT,
            "marketingVersion": MARKETING_VERSION,
            "authHeaderNormalization": "macOS -> Mac OS X (preserves Anisette provider)",
            "authRecovery": "Consented, single GSA init -22410 retry on cached ADI; rollback on failure",
            "certificatePreservation": True,
        }
        print("SIDESTORE_AUTHFIX_BUILD " + json.dumps(report), flush=True)
        return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        build(arguments.output)
    except (RuntimeError, subprocess.CalledProcessError, OSError, ValueError,
            zipfile.BadZipFile, KeyError) as exc:
        print("SIDESTORE_AUTHFIX_FAILED: " + str(exc), file=sys.stderr)
        raise SystemExit(1)
