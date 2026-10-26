# One-slot SideTap integration — implementation workspace

**Branch:** `thelabcorner/LiveContainer:feature/one-slot-sidetap-wda`
**Upstream SideTap source:** [ucsandman/SideTap](https://github.com/ucsandman/SideTap) at `05b05c1da96f7fe3e720f49e033be1455d52810a` (MIT).
**Status:** working, tested Windows/MCP code; **no confirmed iOS one-slot XCTest runner**.

## What has actually been implemented

- `SideTap/` is a pinned **source snapshot** of the real SideTap Python harness, MCP server, WDA client, safeguards and tests. This is not a reimplementation, nor is Python embedded in the iOS app.
- In that source, `phone_harness/coredevice.py` adds optional WDA-free HID controls using `pymobiledevice3`'s actual `core-device universal-hid-service` implementation. Source-level MCP registration exposes `direct_status`, `direct_tap`, `direct_drag`, `direct_type_ascii`.
- `openfork-mcp.cmd` launches **the vendored source**, using the existing `W:\Dev\SideTap\.venv` Python dependencies on this Windows PC. The installed OpenFork MCP is still **disabled by default**; importing the package does not activate it.
- `../scripts/stage_sidetap_wda_research.py` is a strictly offline **research-only** staging tool: it copies an official WDA XCTest bundle into one LiveContainer principal app structure. Its output is **unsigned, not installable**, and cannot establish whether `testmanagerd` will accept the runner. It is not included in any production build.
- Separate CI workflow checks Python regression tests and offline package invariants without requiring or touching an iPhone.

## Actual runtime boundaries

| Requirement | Status |
|---|---|
| Original built-in SideStore, Home Screen Web Clip, same bundle ID | Preserved (feature branch is based on existing fork feature) |
| OpenFork MCP starts from real SideTap source | Verified: 35 tools / MCP handshake |
| Existing WDA-based tools preserved | Yes: 31 existing tools |
| New CoreDevice HID controls, opt-in and STOP gated | Implemented and unit-tested |
| CoreDevice HID works on user's iOS 18.7.7 | **Not proven**; needs live authorized USB service test |
| Full WDA semantic accessibility tree without WDA app | **Not available** through CoreDevice HID |
| Native WDA launches inside installed LiveContainer identity | **Not proven**; Apple XCTest bootstrap is the blocker |
| Combined, signed, working one-slot IPA | **Not built, not claimed, not installed** |

The CoreDevice path may provide the desired screen/touch interaction *without any extra iPhone installation*. It does **not** automatically provide WDA's semantic element tree, native test runner, or image stream inside SideTap's existing viewer. `pymobiledevice3 developer core-device display serve-web --userspace --bind 127.0.0.1` provides a separate browser viewer, but its built-in interactions are outside SideTap's kill-switch gating. Treat it as a separate human-operated tool, not a STOP-protected MCP controller. Do not expose its control port on the LAN.

## Safeguards

Direct HID tools are *disabled unless explicitly opted in* through `SIDETAP_DIRECT_ENABLE=1`, and the entire MCP remains disabled in OpenFork by default. Before every direct gesture or text action, code checks SideTap's STOP file, exactly one unambiguous connected iPhone, and any pinned `SIDETAP_UDID`. All coordinates use normalized fractions 0..1, mapped to CoreDevice's 0..65535 HID coordinates. **Use `drag` for actual touch contact**; CoreDevice `swipe` is only pointer movement.

Text input accepts printable ASCII, tab and newline only. The activity log stores character counts, not typed contents. Failed or timed-out HID commands never auto-repeat; a timeout might occur *after* iOS receives the action. These controls don't know what button is being tapped: approvals for sending messages are **not enforced for arbitrary `direct_tap` interactions**; a human should supervise the phone. Use WDA-backed higher-level tools where semantic verification and send-approval are needed.

## Running code without installing an IPA

From `SideTapIntegration/SideTap`, use Python 3.12 with its declared dependencies and `PYTHONPATH=src`:

```powershell
$env:PYTHONPATH = (Resolve-Path .\src).Path
python -m phone_harness direct-status
python -m phone_harness mcp
```

Use `SideTapIntegration/openfork-mcp.cmd` on this workstation for the MCP entry. With `SIDETAP_DIRECT_ENABLE=0`, direct-status is safe and mutation tools refuse input. Do **not** enable direct HID, start a display stream, install WDA, or deploy an IPA as part of automated setup.

Offline WDA experiment only (never deploy output):

```powershell
python scripts/stage_sidetap_wda_research.py --host built-LiveContainer+SideStore.ipa --wda official-Appium-WDA-Runner.zip --out combined.research.ipa --research-only
python scripts/validate_sidetap_bundle.py combined.research.ipa --require-wda
```

**Crucial:** the research IPA's signatures are invalid after modification. Validation proves only structure, *not* signing, runnability, or one-slot operation. Do not install it on the primary phone. Research next: build/sign with Xcode on macOS, test host identity under `testmanagerd` with an expendable test installation, and abandon nested-WDA packaging if XCTest requires a separately registered runner app.

## Tests

```powershell
cd W:\Dev\LiveContainer-SideTap\SideTapIntegration\SideTap
$env:PYTHONPATH = "$PWD\src"
py -3.12 -m pytest tests -q

cd W:\Dev\LiveContainer-SideTap
py -3.12 -m pytest tests\test_sidetap_bundle_validator.py tests\test_sidetap_wda_staging.py -q
```

Both test suites use mocks or synthetic archives and **do not interact with the phone**. Baseline on the workstation: 545 passed, 1 skipped (SideTap suite); 15 passed (archive suite). GitHub Actions runs the suites independently on Ubuntu.

## Exit criteria for a genuine one-slot release

1. Keep the existing LiveContainer/SideStore app identity, saved data, signing renewal and Home Screen Web Clip functioning.
2. Prove either (a) WDA starts under the same registered app identity without a second slot *and* exposes cross-app automation, or (b) WDA-free CoreDevice allows the required user interactions with no new app install.
3. On a test device, verify screen availability, tap, drag, keyboard, safe sending, reconnection, orientation, lock, STOP and multi-device fencing.
4. Measure latency, CPU/battery costs, installation/signing impact, IPA size, and user-visible regressions.
5. Never merge a speculative XCTest package into the regular LiveContainer release or modify the primary device without deliberate authorization.
