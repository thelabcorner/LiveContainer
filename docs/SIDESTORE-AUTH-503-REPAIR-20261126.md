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

## 2026-11-26 12:00 CST: authfix2 device result — GSA init -22410 and PTM/TK HTTP 401

Status: OPEN. Installed footer identifies LiveContainer 3.8.14-Release,
feature/one-slot-sidetap-wda/84274e8, embedded SideStore 0.7.0-20261126.2,
iOS 18.7.7 (22H340). Two user screenshots show:
* `This action could not be completed. Try again. (-22410; GrandSlam init)`
* `HTTP error (401): Apple PTM/TK endpoint returned HTTP 401`

The order of attempts, actual provider selected, whether the user consented
to the retry, effective custom headers, and runtime logs are not established.
Do not infer those from screenshot order. No successful sign-in or 2FA
has been demonstrated. The screenshots contain account-identifying data;
do not commit them or transcribe the account identifier.

### Source evidence

- Shipped overlay: https://github.com/thelabcorner/LiveContainer/blob/84274e83f15e1eccd0601691f246678de09b057a/scripts/patch_sidestore_authfix.py
  clears the persisted ADI only after consent for typed init -22410,
  retries once, restores the old blob on failure and preserves the
  signing certificate. A PTM/TK failure during initial anisette acquisition
  occurs before the sign-in retry catch. During reprovision it also prevents
  the retry from reaching GSA. The overlay does not modify AnisetteKit.
- Canonical SideStore and LiveContainer/SideStore at 044bd72ad4eb270c3900bd04dc6f508d0ac474db
  have identical blobs for AnisetteProvider.swift (bd628606d3808209159b29d5f3650118b9739401),
  OnDeviceAnisetteManager.swift (03cc650766360eb6512f2a4543c2f288b2399d11),
  AnisetteConfigManager.swift (161f608c43ec40b30f390a7e245c143796e5e2a0),
  SignInOperation.swift (1ff9135ea725cc45481d82a96af1de8418726ef8).
  See https://github.com/SideStore/SideStore/tree/044bd72ad4eb270c3900bd04dc6f508d0ac474db/SideStore/Core/Anisette
  and https://github.com/LiveContainer/SideStore/tree/044bd72ad4eb270c3900bd04dc6f508d0ac474db/SideStore/Core/Anisette.
  Canonical develop head returned 4f3d18d98c5fbee72c80f787ceb2e8e09ded60a6,
  no later canonical commit was returned. Upstream LiveContainer main and
  custom build have identical SideStoreHooks.m blob f9932ae758fddf6a398276d6afda6bf4d2ac1af8;
  this file does not hook the PTM/TK request. Other host runtime effects are
  not excluded by that comparison.
- SideSign 752d1ef602aa792a432ffa1e71646dc1ecf7363c:
  https://github.com/SideStore/SideSign/blob/752d1ef602aa792a432ffa1e71646dc1ecf7363c/Sources/DeveloperPortal/Authentication.swift#L18-L67
  sends init before computing/sending the password-derived SRP proof at complete.
  It obtains clientInfo from anisetteData but uses separate configured
  grandSlam.userAgent at lines 320-327. The default is an Xcode-flavored UA
  (Sources/Constants.swift:14-19), while the default provisioning UA is akd.
  SideStore's SideSignConfigManager applies its own persisted configuration.
  This difference is a source fact, not proof of rejection or proof that
  the user's effective values are defaults.
- AnisetteKit db8b41022697b6c19be8a5f01a1ce834145a2a26 (also latest main commit
  returned by GitHub):
  https://github.com/mahee96/AnisetteKit/blob/db8b41022697b6c19be8a5f01a1ce834145a2a26/Sources/AnisetteClient.swift#L231-L291
  performs lookup -> SPIM -> provider.startProvision -> PTM/TK -> provider.endProvision.
  fetchPtmTk at lines 371-389 invokes sendRequest, which throws the exact
  endpoint/status message on non-200 at lines 315-323. Thus a provider session
  has been started, but Apple rejected finish before endProvision. The
  provider may be remote or local: both modes share AnisetteClient.
- Confirmed source-level lifecycle defect: the Swift provider protocol
  has no cancellation method and runProvisioningFlow does not cancel
  a started session if PTM/TK or subsequent completion fails.
  https://github.com/mahee96/AnisetteKit/blob/db8b41022697b6c19be8a5f01a1ce834145a2a26/Sources/AnisetteDataProvider.swift#L13-L18
  Native cancel_provision_uc and cancel_provision_c are declared in
  Native/include/anisette_core.h; UC cancellation invokes the ADI session
  destruction symbol (Native/anisette_core_uc.cpp:389-413).
  https://github.com/mahee96/AnisetteKit/blob/db8b41022697b6c19be8a5f01a1ce834145a2a26/Native/anisette_core_uc.cpp#L389-L413
  SideSign's remote provider also retains an open WebSocket session until
  endProvision, and has no per-session cancellation exposed to this flow:
  https://github.com/SideStore/SideSign/blob/752d1ef602aa792a432ffa1e71646dc1ecf7363c/Sources/Anisette/RemoteAnisetteDataProvider.swift#L108-L201
  This can explain a cascading pending-session error (-45063) after finish
  fails; that code was not observed on this device. It cannot explain the
  initial HTTP 401 by itself.
- Secondary rollback/identity gaps: SideSign AnisetteDataManager.clearCache()
  clears only its remote cache, not the ODA manager's separate instance,
  native session or routing cache. The previous overlay's old-blob restore
  is not a transactional rollback of all provisioning state. Existing remote
  failover can rotate servers if rotation is enabled; the overlay does not
  lock the exact remote server for recovery despite its same-provider intent.

### Independent upstream observations

- https://github.com/SideStore/SideStore/issues/1772 : matching PTM/TK 401
  followed by pending session -45063; mixed community outcomes.
- https://github.com/SideStore/SideStore/issues/1777 : matching -22410.
- https://github.com/SideStore/SideStore/issues/1745#issuecomment-7065875033 :
  another LC+SS nightly user reports 503 -> -22410 -> PTM/TK 401, and a
  remote-provider workaround. This is user-reported, not a controlled
  comparison for the current device, and does not establish that a provider
  switch is the proper source fix.
- https://github.com/nab138/iloader/pull/1205#issuecomment-7188536325 :
  separate desktop isideload 0.5.2 tests report both older client identity
  and stale anisette state independently preventing GSA init. A wrong
  password test reached the password-proof stage only after those variables
  were changed. Desktop findings are not evidence of successful ODA
  provisioning or account authentication on iOS.

### Next discriminating tests; no new account attempts or state changes yet

| Hypothesis | Prediction / test | Falsifier or limitation |
| --- | --- | --- |
| Cached ADI alone causes init rejection | Existing recovery with fresh ADI and unchanged effective identity reaches GSA | PTM/TK 401 blocks this experiment; no fresh identity was obtained in that attempt |
| Provisioning HTTP request or ADI environment is rejected | Record redacted phase/status, effective header family/version and consistency, provider class and local library provenance; compare with pinned upstream and provider documentation | Same verified request contract/environment succeeds under matched conditions; private Apple rejection reason remains unavailable |
| Provisioning session leaked after finish error | Mock transport returns 401 after successful start; cancellation must run exactly once and next attempt must not inherit pending session | Successful completion needs no cancellation; a mocked 401 cannot prove Apple's actual account or environment policy |
| Header config / GrandSlam UA mismatch | Inspect both resolved configuration paths without modifying them; compare stage-specific header categories, not raw secrets | Matching identity still rejected, or the user already has consistent effective values |

Next code work: independently test the session cleanup contract (local and
remote, success, HTTP error, cancellation, and finish error) at the pinned
AnisetteKit/SideSign boundary, with original error preservation and no
certificate/ADI/provider migration. Review the native cancellation return
semantics before choosing an overlay/dependency pin. Separately investigate
the first PTM/TK rejection; do not sell a cleanup-only patch as a fix for it.
Obtain the current provider class and whether the consent dialog appeared
before the 401, without changing provider, resetting ADI, or repeating login.
Avoid collecting raw verbose logs: existing code can log account/identity
material. Use only deliberately redacted diagnostics.

No new Swift/runtime patch, build, Apple request, reset, or provider switch
was performed during this investigation. Source audit only. Device
authentication and renewal remain unverified. Existing package/WDA progress
is preserved.
