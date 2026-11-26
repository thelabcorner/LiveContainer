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


## 2026-11-26: Second-stage GSA init -22410 (after 503 repair)

Installed evidence: 73f2d74 compiles and runs on iOS 18.7.7, but after
removing Apple's HTTP 503 response, sign-in surfaces -22410.
A new error is not proof of successful account authentication.

### Canonical source and evidence
* SideStore/SideStore:develop 4f3d18d98c5fbee72c80f787ceb2e8e09ded60a6:
  SideStore/Core/Operations/StandaloneOperations/SignInOperation.swift,
  SideStore/Core/Anisette/{AnisetteConfigManager,AnisetteProvider,OnDeviceAnisetteManager}.swift,
  SideStore/Views/Settings/Advanced/UserCustomizations/UserCustomizationsView.swift,
  SideStore/Core/Auth/AuthManager.swift, SideStore/Handlers/SignInFlowHandler.swift.
* Git blob comparisons for the seven relevant SideStore files matched the
  LiveContainer/SideStore pinned 044bd72ad4eb270c3900bd04dc6f508d0ac474db.
* SideSign pinned 752d1ef602aa792a432ffa1e71646dc1ecf7363c:
  Sources/DeveloperPortal/Authentication.swift and Sources/Models/Errors.swift.
* AnisetteKit pinned db8b41022697b6c19be8a5f01a1ce834145a2a26:
  Sources/AnisetteClient.swift resolveProvisioningBlob returns a supplied nonempty
  cached adi.pb without re-provisioning.
* Canonical user reports: SideStore/SideStore issues #1745, #1749, #1777.
  These show both successful reset recovery AND fresh ODA provisioning 401/-45063.
  Neither outcome is guaranteed for this device.
* SideStore PR #1728 is closed/unmerged, broadly forces remote Anisette and
  alters auth flow. It has NOT been blindly imported.

### Hypotheses and discriminators
H1: an ADI provisioned before header normalization is being reused at SRP
init, leading to -22410. One consented fresh provision with identical provider,
identity and client header should succeed; fresh-provision failures and a second
-22410 falsify/qualify this.
H0: Apple rejects the current client or account identity even with a fresh ADI;
fresh provisioning may succeed but GSA init still returns -22410.
H2: provisioning itself fails independently (PTM/TK 401, ADI -45063, lookup
404); report the NEW stage rather than treating it as success.

### Exact source-layer repair and protections
The GitHub credential cannot push directly to official SideStore/SideStore.
The writable LiveContainer fork carries a fail-closed source overlay, applied
to the exact pinned SideStore and SideSign Swift files prior to Xcode compilation.
The build retains the same SideStore 044bd72a, SideSign 752d1ef and AnisetteKit
db8b410 dependency pins; no stale prebuilt IPA fallback.

1. SideSign sends a typed GrandSlam rejection with its phase and Apple status.
2. Only -22410 in SRP init, with a previously stored nonempty adi.pb, offers
   an on-device confirmation. Declining makes NO state changes.
3. After explicit consent, one actor-serialized and persistently keyed retry
   clears only adi.pb, re-fetches using the SAME provider/server and identifier,
   and attempts auth once. Failed reprovision or auth restores the original blob
   and reports the actual error. No automatic server or identity switching.
4. The original certificate is preserved when the sign-in pipeline fails.
5. ADI/account/password/header values are never recorded in CI or new logs.
   Only a SHA-256 retry marker is persisted.

### Gates
Source and offline tests must pass on GitHub Actions. Xcode must compile
the mutated Swift files and the IPA must preserve the single-host identity,
embedded SideStore, SideTap and WDA layout. No green CI run proves Apple
account sign-in/2FA, 7-day refresh, provisioned ADI, or WDA XCTest bootstrap.
A device trial (including confirmation, the precise next error, and sign-in)
remains mandatory.

Rollback: the known-installable commit 73f2d74049d1d00f9851242c14ff0187e8d95544
is preserved; never force-push the custom branch.
