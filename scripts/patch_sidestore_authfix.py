#!/usr/bin/env python3
"""Small, fail-closed source patch for the pinned LiveContainer-compatible SideStore.

The real fix is on the outgoing Apple auth header, not a change to the
on-device/remote Anisette setting. Preserve the saved custom configuration
and normalize it just before Anisette preparation and Apple auth requests.
CPU validation and Swift compilation run only in GitHub Actions.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

SIDESTORE_COMMIT = "044bd72ad4eb270c3900bd04dc6f508d0ac474db"
SIDESIGN_COMMIT = "752d1ef602aa792a432ffa1e71646dc1ecf7363c"
ANISETTEKIT_COMMIT = "db8b41022697b6c19be8a5f01a1ce834145a2a26"
MARKETING_VERSION = "0.7.0-20261126.1+044bd72a-authfix"

CONFIG_PATH = "SideStore/Core/Anisette/AnisetteConfigManager.swift"
AUTH_PATH = "Dependencies/SideSign/Sources/DeveloperPortal/Authentication.swift"

# Exact once-only changes, against the pinned upstream source.
EDIT_MAP = {
    CONFIG_PATH: (
        (
            "$0.clientInfo = config.clientInfo.isEmpty ? AppConstants.Anisette.defaultClientInfo : config.clientInfo",
            '$0.clientInfo = (config.clientInfo.isEmpty ? AppConstants.Anisette.defaultClientInfo : config.clientInfo).replacingOccurrences(of: "<macOS;", with: "<Mac OS X;")',
        ),
    ),
    AUTH_PATH: (
        (
            '"X-MMe-Client-Info": anisetteData.clientInfo,',
            '"X-MMe-Client-Info": anisetteData.clientInfo.replacingOccurrences(of: "<macOS;", with: "<Mac OS X;"),',
        ),
        (
            '"X-MMe-Client-Info": a.clientInfo,',
            '"X-MMe-Client-Info": a.clientInfo.replacingOccurrences(of: "<macOS;", with: "<Mac OS X;"),',
        ),
    ),
}


class PatchError(RuntimeError):
    pass


def _check_source(root: Path) -> None:
    def git_sha(directory: Path) -> str:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=directory, text=True
        ).strip()

    if git_sha(root) != SIDESTORE_COMMIT:
        raise PatchError("SideStore source revision changed: refuse unreviewed build")
    if git_sha(root / "Dependencies" / "SideSign") != SIDESIGN_COMMIT:
        raise PatchError("SideSign source revision changed: refuse unreviewed build")
    resolved = json.loads(
        (root / "AltStore.xcodeproj/project.xcworkspace/xcshareddata/swiftpm/Package.resolved").read_text()
    )
    matches = [
        pin for pin in resolved.get("pins", [])
        if pin.get("identity") == "anisettekit"
    ]
    if len(matches) != 1 or matches[0].get("state", {}).get("revision") != ANISETTEKIT_COMMIT:
        raise PatchError("AnisetteKit dependency revision changed: refuse unreviewed build")


def patch_sources(root: Path, *, verify_git: bool = True) -> dict[str, int]:
    """Modify the two source files only. Fail before writing if any anchor drifts."""
    root = Path(root)
    if verify_git:
        _check_source(root)
    updates = {}
    counts = {}
    for relative, edits in EDIT_MAP.items():
        path = root / relative
        original = path.read_text(encoding="utf-8")
        patched = original
        for old, new in edits:
            count = patched.count(old)
            if count != 1:
                raise PatchError(f"{relative}: expected one exact source anchor, found {count}")
            patched = patched.replace(old, new, 1)
        if patched == original:
            raise PatchError(f"{relative}: unexpectedly unchanged")
        updates[path] = patched
        counts[relative] = len(edits)

    # One-shot commit only after every file has passed the preconditions.
    for path, patched in updates.items():
        path.write_text(patched, encoding="utf-8")
    return counts
