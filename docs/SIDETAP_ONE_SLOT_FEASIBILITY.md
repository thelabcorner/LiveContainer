# One-slot SideTap integration feasibility (LiveContainer + SideStore)

**Status:** source-researched engineering plan, not an implemented device driver.
**Work branch:** `feature/one-slot-sidetap-wda` (thelabcorner/LiveContainer).
**Based on:** `feature/upstream-ready-sidestore-webclip` at `f5cd1193d783420e830f69fc27b3bdef688b65de`.
**Original feature remains intact:** built-in SideStore Home Screen Web Clip, `builtinSideStore` deep-link target and draft PR #2.

## The actual objective

Operate an iPhone running iOS 18.7.7 from Windows, via the SideTap MCP / viewer, with **no additional free Apple developer app slot beyond the currently installed LiveContainer + SideStore slot**, while preserving the current install, guest apps, signing / refresh, and Home Screen Web Clip. No remote phone installs, IPA swaps, changes to the user's Apple account, or upstream PRs without explicit authorization.

Important separation: SideTap's Python `phone_harness`, Windows UI, `go-ios`, and MCP **stay on Windows**. The part consuming a phone app slot is Appium WebDriverAgent's real-device XCTest runner. Shipping the Python application inside an iPhone IPA is not the intended runtime architecture.

## Grounded source architecture

1. The repo's `.github/build_github.sh` builds `LiveContainer.app`, downloads the **mutable** `LiveContainer/SideStore` nightly IPA, embeds `SideStore.app` as `Frameworks/SideStoreApp.framework`, rewrites its executable to a dylib with `dylibify`, and relocates the widget and intents. This explains the existing one-slot composition; it does **not** demonstrate that XCTest runners can use that mechanism.
2. `SideStoreSupport/SideStore.swift` delegates app refresh and starts SideStore; `SideStoreHooks.m` normalizes bundle identifiers. `LiveProcess` and `LaunchAppExtension` are extension targets, not XCTest runner targets.
3. The combined IPA contains a *single principal iOS app* (`Payload/LiveContainer.app`). Adding a separate `Payload/WDA.app`, installing WDA via embedded SideStore, or treating it as a standard LiveContainer guest does **not** satisfy a genuine one-slot native XCTest requirement.
4. SideTap's `src/phone_harness/device.py`, `wda_client.py`, `signing.py` use a separate Appium WebDriverAgent host app, nested `PlugIns/WebDriverAgentRunner.xctest`, go-ios XCTest launch, tunnel, and port forwards. The nested bundle must be preserved and correctly signed.
5. LiveContainer issue #1489 records an embedded SideStore signing path that removed nested `.xctest` bundles from imported apps (ERROR 104); the SideStore signing fix is necessary for separately installed WDA, but **does not** eliminate the extra app slot.
6. LiveContainer issue #1555 describes additional nested-framework signing faults after SideSign changes. Therefore recursively signing nested frameworks and signed test bundles, rather than assuming shallow signing, is a separate invariant.

### Source URLs

- LiveContainer fork: https://github.com/thelabcorner/LiveContainer
- Existing clean Web Clip PR: https://github.com/thelabcorner/LiveContainer/pull/2
- LC combined packaging: https://github.com/LiveContainer/LiveContainer/blob/main/.github/build_github.sh
- LC XCTest signing bug: https://github.com/LiveContainer/LiveContainer/issues/1489
- LC nested framework signing bug: https://github.com/LiveContainer/LiveContainer/issues/1555
- SideTap architecture: https://github.com/ucsandman/SideTap
- SideTap Windows setup: https://github.com/ucsandman/SideTap/blob/main/docs/setup-windows.md
- Appium preinstalled WDA details: https://github.com/appium/appium-xcuitest-driver/blob/master/docs/guides/run-preinstalled-wda.md
- CoreDevice video/HID independent alternative: https://github.com/doronz88/pymobiledevice3/blob/master/docs/guides/cli-recipes.md
- CoreDevice userspace tunnels: https://github.com/doronz88/pymobiledevice3/blob/master/docs/guides/ios17-tunnels.md

## Feasibility tracks — investigate, do not assume

### Track A: native XCTest runner inside the one registered LiveContainer app

**Hypothesis A1:** a signed `WebDriverAgentRunner.xctest` can be embedded under the principal LiveContainer app and launched through `testmanagerd` with **LiveContainer's existing registered bundle identifier** and an appropriate runner/test configuration.

**Key unknown:** whether `testmanagerd` accepts `com.kdt.livecontainer` as an XCTest runner host and can launch an embedded `.xctest` without the normal standalone `WebDriverAgentRunner-Runner.app` identity and runner executable. Merely copying the bundle into `PlugIns` or converting WDA to a dylib is **not proof**; the XCTest process/bootstrap and Apple's developer signature policies must all work.

Spikes, in order:
- Compare WDA test-runner plist keys, its executable's startup path, Info.plist, embedded provisioning profile, and nested signatures to LiveContainer's app + extension structure. Record any provisioning / TestFlight / free-account restrictions.
- Build a *separate CI-only artifact* with one `Payload/LiveContainer.app` and a preserved `PlugIns/*.xctest`. Do not install it. Verify nested signatures with `codesign --verify --deep --strict` and inspect with `codesign -d --entitlements :-`.
- With explicit authorization, test native `testmanagerd` bootstrap on an expendable test installation; record actual `ios runwda` / XCTest error messages. A runner that simply starts its own app UI is a **failure**.
- If the host identity or testing daemon requires an independently installed `WDA.app`, **stop this track**. Do not masquerade a separately installed runner as one slot.

**Hypothesis A2:** extract and embed WDA functionality into the LiveContainer host process. Must independently demonstrate that the XCTest UI-testing APIs will initialize and drive *other system apps* without an XCTest test runner; no assumption that linking `WebDriverAgentLib.framework` is enough. Investigate only after A1 fails. Do not build an invasive injection system as a default fallback.

### Track B: WDA-free SideTap transport using CoreDevice

`pymobiledevice3` (already present in the SideTap Python venv on the user's Windows machine) documents `developer core-device display serve-web` with HEVC screen streaming, remote mouse/touch/keyboard and `universal-hid-service` input, on iOS 17.4+ using a no-root userspace RSD tunnel. This potentially offers **zero additional app slots, zero IPA changes, and zero WDA signing/expiry**. It is not identical to XCTest's semantic accessibility tree.

- Establish a physical USB connection / valid CoreDevice tunnel and inspect media capability without installing an app.
- Passively verify screenshot and live display. Separately test a harmless, explicitly approved HID input; check visible result. No automatic taps/sends during setup.
- Measure capture latency, FPS, pixel geometry, rotation, touch and scroll mapping; compare against WDA / SideTap when available.
- Define an adapter behind existing SideTap APIs, e.g. `transport = coredevice | wda`. Preserve WDA semantic tree only on the WDA transport; do not fake it on HID transport.
- Keep STOP kill switch, network loopback binding and human approval gates for message sends.
- Prefer Track B if it provides the desired features. The iOS LiveContainer fork does not need changes to make this work.

**Observed on 2026-10-26:** `pymobiledevice3 11.45.0` reports the device over *Network*, not a verified current physical USB path; mounted personalized DDI is present. The passive `display get-media-support-info` probe failed to start the service. This is an unresolved transport/device connection condition, **not** proof of iOS 18.7.7 incompatibility or CoreDevice functionality.

### Track C: app-extension runner / SideStore guest

Only reconsider if a source-backed, reproducible demonstration shows Apple's XCTest test runner can be hosted from an installed `appex`/LiveProcess without introducing another registered app. iOS app extensions and LiveContainer guest execution are not substitutes for independent XCTest registration by definition. Low priority; do not invest in open-ended reverse engineering.

## Build and testing invariants

- **Slot:** exactly one top-level `Payload/*.app`; inspect actual registered app identities and provisioning profile with real-device tooling. One IPA file alone does *not* establish one slot.
- **Data:** same `com.kdt.livecontainer` bundle ID, Team ID, existing app groups, URL schemes, extensions, documents, SideStore refresh settings and guest containers. No delete/reinstall on the primary phone.
- **Web Clip:** `livecontainer://livecontainer-launch?bundle-name=builtinSideStore` still works, including repeated opens, app switching and confirmation callback.
- **Signatures:** every embedded executable, nested `.framework`, extension and test bundle is signed in the correct order. Test on-device signing, not just macOS local `codesign`.
- **Test runner:** demonstrate remote XCTest UI tree, focus/tap, text, cross-app launch and navigation (not merely screenshots), with zero additional installed native apps.
- **Security:** bind any unauthenticated phone-control endpoint to loopback; no persistent phone passcode; STOP must immediately block any new action; prompt injection from screen and messages must not bypass approvals.
- **Reliability:** plug/unplug, lock/unlock, SideStore refresh, 7-day free-signing renewal, firmware update, tunnel reconnection, and orientation changes.
- **CI:** macOS Xcode archive and on-disk IPA structure/signature audit, plus Python/unit tests that can run from Windows. Never install in CI without a test phone and explicit test scope.
- **Performance:** record cold startup, tunnel setup, input p50/p95, capture latency/FPS, artifact compressed bytes, peak RSS, battery/CPU where measurable. Claim improvement only with measured evidence.
- **Release:** do not create or publish a test IPA without validation. Pin the SideStore source/asset and checksum; avoid mutable nightly. Preserve the established fork's release aliases and manifest invariants if a release track is added later.

## Immediate stage gates

| Gate | Required proof | Current status |
|---|---|---|
| F0 | Separate work branch from user's Web Clip fork; no mutation to main/PR | PASS |
| F1 | Source audit: hosted SideStore and WDA signing/launch paths | IN PROGRESS |
| F2 | CoreDevice media/HID transport verified on physically attached iOS 18.7.7 phone | BLOCKED: no verified USB media service yet |
| F3 | One-slot XCTest native app identity demonstrated | UNKNOWN |
| F4 | macOS Xcode CI archive and nested signature audit | NOT RUN |
| F5 | On-device interaction parity, no second installed app | NOT RUN |
| F6 | Existing LiveContainer / SideStore / Web Clip regression tests | NOT RUN |

Do not turn an assumption about a bundle into an IPA deployment. Prefer the simplest verified capability path that actually gives the user remote control with one or fewer occupied slots.
