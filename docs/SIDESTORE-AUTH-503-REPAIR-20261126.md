# Embedded SideStore: Apple GSA 503 compatibility repair

Date: 2026-11-26. Target branch: feature/one-slot-sidetap-wda.

## Verified failure mechanism

The installed combined IPA at 98f2ad2 bundles SideStore commit
044bd72ad4eb270c3900bd04dc6f508d0ac474db. SideStore's source locks
SideSign 752d1ef602aa792a432ffa1e71646dc1ecf7363c and AnisetteKit
db8b41022697b6c19be8a5f01a1ce834145a2a26. AnisetteKit's
defaultClientInfo contains <macOS;26.6;25F84>. SideSign passes the
anisetteData.clientInfo through as X-MMe-Client-Info on GsService2
authentication and two-factor requests.

Upstream controlled evidence:
* https://github.com/SideStore/SideStore/issues/1745
* https://github.com/JosssphZhou/poki/pull/549
The observed 503 is an Apple HTML response, not proof of an ODA failure.
A 503->401 result for an unauthenticated probe validates the endpoint
classification, NOT successful account sign-in.

## Code change

Instead of switching Anisette providers or resetting ADI:
1. Normalize the Client Info header in SideStore's
   AnisetteConfigManager.makeRequestHeaders, including persisted overrides.
2. Normalize the outgoing X-MMe-Client-Info in SideSign authentication init
   and two-factor requests (final defensive boundary).
3. Preserve the on-device/remote selection and ADI keychain data unchanged.
4. Build SideStore FROM SOURCE in GitHub Actions using the exact locked
   upstream, SideSign submodule, and AnisetteKit SwiftPM dependency; do not
   fall back to the old prebuilt nightly when building fails.
5. Give the new compiled SideStore a distinct authfix marketing version.

The builder only runs with GITHUB_ACTIONS=true. The normal existing
LiveContainer build workflow now invokes it and embeds the resulting IPA.

## Verification levels

A passing structural Python test proves exact source edit contracts,
negative cases, and source fallback discipline. Successful macOS Xcode
CI builds prove that SideStore source compiles, the package has the expected
bundle identity/version, and the final one-slot IPA is structurally valid.

Neither proves device provisioning, on-device Anisette operation after
install, Apple account + 2FA sign-in, 7-day renewal, or WDA XCTest launch.
The first decisive device check is the Apple sign-in flow from the upgraded
in-place combined IPA; inspect the actual failure response and header
if it continues to fail. Avoid account/password/ADI logs in CI.
