# One-slot SideTap integration — implementation workspace

**Branch:** `thelabcorner/LiveContainer:feature/one-slot-sidetap-wda`
**Upstream SideTap source:** [ucsandman/SideTap](https://github.com/ucsandman/SideTap) at `05b05c1da96f7fe3e720f49e033be1455d52810a` (MIT).
**Status:** working, tested Windows/MCP code; **no confirmed iOS one-slot XCTest runner**.

## What has actually been implemented

- `SideTap/` is a pinned **source snapshot** of the real SideTap Python harness, MCP server, WDA client, safeguards and tests. This is not a reimplementation, nor is Python embedded in the iOS app.
- In that source, `phone_harness/coredevice.py` adds optional WDA-free HID controls using `pymobiledevice3`'s actual `core-device universal-hid-service` implementation. Source-level MCP registration exposes `direct_status`, `direct_tap`, `direct_drag`, `direct_type_ascii`.
- `openfork-mcp.cmd` launches **the vendored source**, using the existing `W:\Dev\SideTap\.venv` Python dependencies on this Windows PC. The installed OpenFork MCP is still **disabled by default**; importing the package does not activate it.
- `../scripts/stage_sidetap_wda_research.py` is a strictly offline **research-only** staging tool: it copies an official WDA XCTest bundle into one LiveContainer principal app structure. Its output is **unsigned, not installable**, and cannot establish whether `testmanagerd` will accept the runner. It is not included in any production build.
- Separate CI workflow checks Python regression tests, HTTPS companion security, full-screen iOS integration structure and offline package invariants without touching an iPhone.

## LiveContainer's SideTap icon now opens the actual application

The LiveContainer **Apps** header has two adjacent icons: the original built-in SideStore button, immediately followed by the original SideTap icon converted from `SideTap/assets/sidetap.ico` to an iOS asset catalog. Tapping SideTap opens `SideTapAppView` as a **full-screen application**, not a status sheet.

SideTap's existing interface is `SideTap/src/phone_harness/viewer.html` backed by the Windows `viewer.py`. There is no separate native iPhone SideTap executable to launch. The full-screen iOS `WKWebView` loads **that original viewer** through an explicit, encrypted workstation companion. The iPhone app never installs WDA or takes an additional free signing slot. Without pairing, the full-screen SideTap app shows its own secure connection onboarding UI.

### Start the workstation companion deliberately

The SideTap MCP stays disabled in OpenFork. This companion also **does not start automatically**.

1. Connect the workstation and phone to a network where they can reach one another. Identify a *specific private IPv4 address assigned to the workstation* (for example `192.168.1.50`); don't use `127.0.0.1` on the phone, don't expose the service to the public internet.
2. Start the companion from the vendored SideTap source with an existing Python environment containing its official dependencies (including `cryptography`):

   ```powershell
   cd W:\Dev\LiveContainer-SideTap\SideTapIntegration\SideTap
   $env:PYTHONPATH = "$PWD\src"
   W:\Dev\SideTap\.venv\Scripts\python.exe -m phone_harness companion --bind 192.168.1.50
   ```

3. The PC prints three values: `https://192.168.1.50:8781/`, a certificate SHA-256 fingerprint, and a pairing code. Tap the SideTap icon in the LiveContainer Apps header. Enter the HTTPS address and fingerprint, then **Open SideTap**. The embedded original SideTap viewer loads its login form; enter the workstation pairing code. From then on the remote SideTap application loads with the original controls, STOP button and approval workflow.
4. Windows Defender Firewall may require **user-authorized** inbound access to the selected private IP/port. No firewall rule is added by this repository or by starting the companion. Stop the Windows command to stop sharing the viewer.

The companion uses a persistent self-signed TLS certificate with an explicitly verified fingerprint, a separate secret pairing code, and an ephemeral `Secure; HttpOnly; SameSite=Strict` cookie. Only same-origin requests reach the existing **loopback-only** SideTap viewer. It removes MJPEG port references so the viewer uses same-origin screen polling rather than opening an unprotected second network port. The actual native WDA functionality is still dependent on successful WDA setup; CoreDevice remains the optional no-extra-slot input alternative.

### Security and limitations

- The iPhone host rejects non-HTTPS URLs, missing or malformed TLS fingerprints, unexpected TLS certificates, and redirects to different hosts or ports.
- The Windows server refuses wildcard and public IP bindings, denies unauthenticated or cross-origin commands and uses a fixed loopback backend (no arbitrary proxy destinations). It sends neither phone passcodes nor API cookies to other hosts.
- Neither the new SideTap icon nor opening its full-screen UI launches the MCP, changes any phone settings, or installs an IPA. Starting the workstation companion is explicitly opt-in.
- Existing SideTap `viewer.html` was designed for desktop; its responsive layout works on narrow viewports but does not yet constitute a pixel-perfect native iOS redesign. Cross-app XCTest automation still requires a valid WDA runner, and the separate one-slot WDA hypothesis remains unproven.
- The iPhone must be able to reach the workstation. If the PC is offline, SideTap's viewer cannot respond. This is a **companion UI**, not a background iOS automation daemon.

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
