#!/usr/bin/env python3
"""Fail CI if release IPA identity or SideStore source metadata drifts.

This validates the archive actually produced by build_github.sh, rather than
assuming the asset filename (which is not a bundle identifier) is authoritative.
"""
import argparse
import hashlib
import json
import plistlib
import re
import sys
import zipfile
from pathlib import Path
from urllib.parse import unquote, urlparse

EXPECTED_BUNDLE_ID = "com.kdt.livecontainer"
INFO_PATTERN = re.compile(r"^Payload/[^/]+\.app/Info\.plist$")


def inspect_ipa(ipa_path: Path, *, expect_embedded_sidestore: bool) -> tuple[str, str]:
    if not ipa_path.is_file():
        raise ValueError(f"IPA is missing: {ipa_path}")
    with zipfile.ZipFile(ipa_path) as archive:
        names = set(archive.namelist())
        root_infos = [name for name in names if INFO_PATTERN.fullmatch(name)]
        if len(root_infos) != 1:
            raise ValueError(f"{ipa_path}: expected one Payload/*.app/Info.plist, found {root_infos}")
        root_info = root_infos[0]
        plist = plistlib.loads(archive.read(root_info))
        bundle_id = plist.get("CFBundleIdentifier")
        version = plist.get("CFBundleShortVersionString")
        if bundle_id != EXPECTED_BUNDLE_ID:
            raise ValueError(f"{ipa_path}: expected bundle ID {EXPECTED_BUNDLE_ID!r}, got {bundle_id!r}")
        if not isinstance(version, str) or not version:
            raise ValueError(f"{ipa_path}: CFBundleShortVersionString is missing")
        app_prefix = root_info.removesuffix("Info.plist")
        embedded_prefix = app_prefix + "Frameworks/SideStoreApp.framework/"
        embedded = any(name.startswith(embedded_prefix) for name in names)
        if embedded != expect_embedded_sidestore:
            raise ValueError(
                f"{ipa_path}: embedded SideStore expected={expect_embedded_sidestore}, present={embedded}"
            )
        if embedded and embedded_prefix + "Info.plist" not in names:
            raise ValueError(f"{ipa_path}: embedded SideStore framework has no Info.plist")
        # Check direct app extensions' bundle ID prefix (required by iOS).
        for name in sorted(names):
            if not name.startswith(app_prefix + "PlugIns/") or not name.endswith(".appex/Info.plist"):
                continue
            if name.count("/") != app_prefix.count("/") + 2:
                continue
            extension = plistlib.loads(archive.read(name))
            extension_id = extension.get("CFBundleIdentifier")
            if not isinstance(extension_id, str) or not extension_id.startswith(bundle_id + "."):
                raise ValueError(f"{ipa_path}: invalid extension ID {extension_id!r} in {name}")
        bad_entry = archive.testzip()
        if bad_entry is not None:
            raise ValueError(f"{ipa_path}: corrupt zip member {bad_entry}")
    print(f"OK: {ipa_path.name}: CFBundleIdentifier={bundle_id}, version={version}, embeddedSideStore={embedded}")
    return bundle_id, version


def inspect_source(source_path: Path, expected_bundle_id: str, expected_version: str) -> None:
    source = json.loads(source_path.read_text(encoding="utf-8"))
    apps = source.get("apps")
    if not isinstance(apps, list) or len(apps) != 1:
        raise ValueError("test AltSource must contain exactly one app")
    app = apps[0]
    if app.get("bundleIdentifier") != expected_bundle_id:
        raise ValueError("AltSource bundleIdentifier does not match IPA CFBundleIdentifier")
    if app.get("version") != expected_version:
        raise ValueError("AltSource version does not match built IPA")
    versions = app.get("versions")
    if not isinstance(versions, list) or not versions or versions[0].get("version") != expected_version:
        raise ValueError("AltSource versions[0].version does not match built IPA")
    url = versions[0].get("downloadURL")
    if url != app.get("downloadURL"):
        raise ValueError("AltSource top-level and version download URLs differ")
    parsed = urlparse(url or "")
    if parsed.scheme != "https" or parsed.netloc != "github.com":
        raise ValueError("AltSource download URL must be a GitHub HTTPS release URL")
    if unquote(parsed.path.rsplit("/", 1)[-1]) != "LiveContainer+SideStore.ipa":
        raise ValueError("AltSource URL must link to the embedded-SideStore release asset")
    if not isinstance(app.get("size"), int) or app["size"] <= 0 or app["size"] != versions[0].get("size"):
        raise ValueError("AltSource published IPA sizes are inconsistent")
    print(f"OK: {source_path}: {expected_bundle_id} {expected_version}, published asset={url}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def inspect_alias(alias_path: Path, sidestore_path: Path) -> None:
    if alias_path.name != EXPECTED_BUNDLE_ID + ".ipa":
        raise ValueError("URL-safe alias basename must match CFBundleIdentifier")
    if not alias_path.is_file() or alias_path.stat().st_size != sidestore_path.stat().st_size:
        raise ValueError("URL-safe alias is missing or differs in size from embedded SideStore IPA")
    if sha256_file(alias_path) != sha256_file(sidestore_path):
        raise ValueError("URL-safe alias differs in bytes from embedded SideStore IPA")
    print(f"OK: {alias_path.name} is a byte-identical URL-safe alias")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--standard", type=Path, required=True)
    parser.add_argument("--sidestore", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--alias", type=Path, required=True)
    args = parser.parse_args()
    try:
        standard_id, standard_version = inspect_ipa(args.standard, expect_embedded_sidestore=False)
        sidestore_id, sidestore_version = inspect_ipa(args.sidestore, expect_embedded_sidestore=True)
        if (standard_id, standard_version) != (sidestore_id, sidestore_version):
            raise ValueError("Standard and embedded-SideStore IPA version/identifier differ")
        inspect_source(args.source, sidestore_id, sidestore_version)
        inspect_alias(args.alias, args.sidestore)
    except (OSError, ValueError, KeyError, zipfile.BadZipFile, plistlib.InvalidFileException) as exc:
        print(f"ERROR: release package validation failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
