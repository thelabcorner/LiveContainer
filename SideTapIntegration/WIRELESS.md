## Persistent screenshot optimization — October 27, 2026

Measured on the actual iPhone: first-time RSD establishment takes about
3.0 seconds, DVT channel establishment 0.4 seconds, and successive screenshot
response times on a reused tunnel were 1.0, 2.6, and 2.6 seconds.
The 10+ second UI delay predominantly comes from creating a new userspace
tunnel, DVT provider and screenshot channel per subprocess, compounded by
repeated device discovery.

The new SideTap persistent_dvt.py retains one authenticated, UDID-pinned
userspace RSD tunnel and DVT screenshot channel on a dedicated asyncio loop.
It serializes concurrent captures, tears down invalid connections, refuses
cross-device sessions, and rechecks the actual network-only transport on
each connection/reconnection (rather than every frame). The standard
Wi-Fi capture backend is now persistent; the old subprocess mode remains
an explicit compatibility fallback via SIDETAP_WIFI_CAPTURE_BACKEND.

The first persistent prototype captured three real full-size iPhone frames
in 11.3, 6.1 and 5.6 seconds, but still performed a full network preflight
on each image. Source changes removed that redundant per-frame preflight,
and the complete test suite passed 640 tests with one skipped. Before those
changes could be physically re-benchmarked, the phone ran out of power;
it is back on Wi-Fi, with genuine Bonjour and authenticated paired TCP,
but Apple's Windows usbmux currently does not enumerate its network entry.
The upstream UserspaceRsdTunnel factory requires usbmux. Therefore, do NOT
assert that final optimized per-frame performance is already proven.

Porting to Rust through PyO3/maturin is possible, but premature: Python
startup and tunnel re-establishment are separate from intrinsic Python
execution cost. Benchmark connection reuse, DVT roundtrip, phone image
encoding and the userspace TCP stack first.

# October 27, 2026: verified untethered screen capture (supersedes older notes below)

**The physical Wi-Fi connection works.** With USB device enumeration empty,
Windows Apple Mobile Device Service discovered the pinned iPhone as a Network
device. Independent Bonjour discovery resolved the same phone to
192.168.1.7, and a direct paired lockdown connection over TCP succeeded.
Developer Mode and the developer image were already enabled.

**Why removing USB appeared to disconnect everything:** A phone can be
advertised on both transports while connected by cable. A developer tunnel
established *through USB* stops working when that USB link disappears. The
go-ios userspace agent may remain listening but have no active per-device
tunnel; it does not seamlessly migrate its connection to Wi-Fi. We
reproduced that behavior with no cable and a directly reachable iPhone:
the go-ios agent stayed at "Tunnel server started" and showed no tunnel,
while pymobiledevice3 userspace CoreDevice display queries succeeded.
See the independently reported Windows case:
https://github.com/danielpaulus/go-ios/issues/779

A separate intermittent discovery problem can also occur: the phone may
advertise by Bonjour while Windows Apple Mobile Device Service has not yet
re-enumerated it, or it may stop advertising temporarily while sleeping.
The new read-only SideTap wireless-discover command independently checks
Bonjour, the Apple usbmux Network listing, and direct paired TCP to the
exact configured device identifier. These checks differentiate the daemon
missing an announcement from an unreachable iPhone. Do not reinstall
drivers or toggle pairing credentials when Bonjour and paired TCP work.

**Working workaround:** The DVT screenshot developer service, accessed by
pymobiledevice3 using userspace RSD over Wi-Fi, successfully returned a
genuine 1284 x 2778 PNG from the actual unplugged iPhone. SideTap's
capture.py now selects that service in explicit Wi-Fi mode instead of the
go-ios screenshot command. No WDA app, new IPA, signing slot, privileged
network adapter, or cable is necessary for this screenshot-only path.

**Important limitations:** One real capture took approximately 11 seconds
including process and tunnel startup. This is a slow but legitimate preview,
not a smooth high-fps video stream. The iPhone currently rejects the
CoreDevice Universal HID service, so tap, drag and keyboard control are
NOT yet working wirelessly. The viewer intentionally advertises capture
and input as independent capabilities; it never enables input solely
because a screenshot or display metadata is available.

A manual kernel Wi-Fi tunnel command was also attempted. It searches the
older RemotePairing service and returned no tunnel service; that does not
contradict the successful iOS 18 CoreDeviceProxy userspace connection.
These are distinct protocol routes. Preserve the existing signed WDA
semantics where a separate real WDA tunnel and runner are available.

On this Windows host the classic Apple Mobile Device Service is already
installed and working: do not replace drivers, disable the firewall or
create an extra app installation. A future persistent screenshot
connection should address frame latency separately.

References:
- https://doronz88.github.io/pymobiledevice3/guides/troubleshooting/
- https://doronz88.github.io/pymobiledevice3/guides/ios17-tunnels/
- https://doronz88.github.io/pymobiledevice3/api/dvt/
- https://github.com/danielpaulus/go-ios/issues/779

---
**Historical engineering notes below** include earlier pre-DVT
investigations and are superseded by the verified results above.

## Critical transport audit (2026-10-26)

**Do not treat Wi-Fi lockdown discovery as proof that the HID command uses Wi-Fi.** After reviewing the actual `pymobiledevice3` implementation, the current `coredevice.py` calls `universal-hid-service ... --userspace` with `PYMOBILEDEVICE3_UDID`. In pymobiledevice3 11.45, the no-root userspace factory starts with `create_using_usbmux(serial=...)` and does not explicitly force the network connection type. A UDID chooses a device identity; it does *not* establish the route. This is an outstanding correctness gap in the wireless branch until the cable is unplugged and a real CoreDevice request succeeds.

An explicitly paired RemotePairing Wi-Fi tunnel is a different transport from discovering `_apple-mobdev2._tcp` or connecting to lockdown TCP 62078. The upstream source supports `get_remote_pairing_tunnel_services(udid=...)` and tunnels from `remote start-tunnel -t wifi`, with identity verification through the stored pair record. The CLI also supports `--tunnel <UDID>` to use a verified `tunneld` connection, in contrast to `--userspace`; these switches are mutually exclusive. Before changing input routing, implement a **single, verified Wi-Fi RSD backend** with a pinned target ID, route evidence, loss/reconnect handling, and an explicit no-USB gate. Do not claim that `--userspace` plus `PYMOBILEDEVICE3_UDID` alone accomplishes this. The current unit tests mock subprocesses and cannot prove the route.

**Other cautions:** the CoreDevice transport currently calls the CLI afresh for every HID gesture, which rebuilds an in-process tunnel and adds avoidable startup cost; a persistent controlled RSD session is preferable. The screenshot fallback currently uses go-ios, and therefore needs its *own* verified Wi-Fi service path rather than borrowing CoreDevice readiness. WDA and CoreDevice input modes must keep source/device identity, STOP, replay prevention and user authorization consistent.

References:
- https://github.com/doronz88/pymobiledevice3/blob/master/pymobiledevice3/remote/userspace_tunnel.py
- https://github.com/doronz88/pymobiledevice3/blob/master/pymobiledevice3/remote/tunnel_service.py
- https://github.com/doronz88/pymobiledevice3/blob/master/misc/RemoteXPC.md
- https://doronz88.github.io/pymobiledevice3/guides/ios17-tunnels/

# SideTap Wi-Fi implementation

## Physical-device results — iOS 18.7.7 (October 26, 2026)

Reproduced on the actual paired iPhone with USB absent, not simulated.

| Probe | Result |
|---|---|
| pymobiledevice3 usbmux list --usb --simple | Empty (no wired device) |
| pymobiledevice3 usbmux list --network --simple | Pinned iPhone is discovered over Wi-Fi |
| Paired network lockdown | Responded; Developer Mode enabled |
| CoreDevice get-display-info --userspace | SUCCESS: 1284 x 2778, 120 Hz display |
| CoreDevice universal-hid-service list-connected --userspace | FAIL at service startup |
| CoreDevice screen-capture screenshot --userspace | FAIL at service startup |
| developer screenshot --userspace (legacy) | FAIL at service startup |
| go-ios screenshot without active tunnel | FAIL: DVTSecureSocketProxy needs an RSD tunnel |
| go-ios userspace agent | Agent started, but no device tunnel was established |

This exact Windows go-ios behavior, stalling after "Tunnel server started" without an established Wi-Fi tunnel, is independently reported in https://github.com/danielpaulus/go-ios/issues/779. The upstream issue is open. A successful go-ios network-device listing is therefore insufficient to claim its XCTest/screenshot services will work.


This is real, unplugged lockdown and CoreDevice RSD communication. It is NOT yet wireless screen capture or HID input. Missing features may be iOS-version limitations, entitlement requirements, or tooling incompatibilities.

Source-level correction: RSD developer commands do not accept --udid. They use the real PYMOBILEDEVICE3_UDID environment variable with --userspace. The former --udid flag made the diagnostic fail even on a working network. The wireless readiness gate now tests the actual HID service before allowing gestures and reports ready=false when it is missing. The viewer does not send a fake placeholder frame as a successful wireless screenshot.

Full automation still needs a working screenshot service, a verified HID service, or the existing WDA path with an active go-ios developer tunnel and signed runner. No installed IPA or bundle ID was changed; no blind touches were issued.

## Status and scope

Wireless transport, selected-device validation, MCP diagnostics, and an opt-in CoreDevice HID adapter are now implemented inside the REAL SideTap source snapshot. The original SideTap viewer can route taps, swipes, and ASCII keyboard input to CoreDevice over a verified Wi-Fi connection, while preserving the WebDriverAgent route if an actual WDA runner is installed.

**Live unplugged operation on iOS 18.7.7 remains unverified.** The PC currently cannot establish a trusted connection to the iPhone via usbmux, so the one-time Wi-Fi toggle could not be enabled. This does NOT change the app bundle ID or install another app.

## Research conclusions

Original ucsandman/SideTap explicitly targets USB and assumes go-ios tunnels, forwards, and a signed WDA runner. Apple iOS 17.4+ provides CoreDeviceProxy via lockdown, and pymobiledevice3 implements in-process userspace RSD tunnels and HID/video services. Wi-Fi lockdown uses a paired Bonjour mobdev2 device and TCP 62078, rather than an ordinary open HTTP service.

Research references:
- https://github.com/ucsandman/SideTap
- https://doronz88.github.io/pymobiledevice3/guides/ios17-tunnels/
- https://doronz88.github.io/pymobiledevice3/guides/network-stacks/

On this actual Windows PC, pymobiledevice3 doctor finds classic iTunes Apple Mobile Device Service (C:/Program Files/Common Files/Apple/Mobile Device Support/AppleMobileDeviceService.exe). It supports Wi-Fi discovery. **No driver replacement is required**, though the currently visible USB and Wi-Fi device counts are zero.

## Source changes

- phone_harness/wireless.py: opt-in mode, bounded read-only network-only usbmux queries, live paired lockdown verification, device-identity pinning, Bonjour comparisons, and explicit USB-verified settings toggle.
- phone_harness/coredevice.py: when wireless mode is selected and the user has opted into HID, validate the pinned Wi-Fi device and set PYMOBILEDEVICE3_UDID for the real pymobiledevice3 userspace CoreDevice command. STOP is checked before every gesture.
- phone_harness/viewer.py: the ORIGINAL SideTap viewer accepts tap, swipe, and ASCII type via CoreDevice if wired WDA is not selected. It normalizes screenshot pixel coordinates into HID fractions. It does not pretend to supply WDA's accessibility tree or unsupported actions.
- phone_harness/admin.py: validates wireless lockdown and go-ios enumeration before launching WDA over Wi-Fi. If only pymobiledevice3 sees the phone, it reports this instead of silently reporting USB success.
- phone_harness/run.py: wireless-discover, wireless-status, wireless-enable --confirm.
- phone_harness/mcp_server.py: read-only wireless_status tool; Wi-Fi setting change is deliberately NOT callable through MCP.

## One-time enablement steps

1. Reconnect the iPhone by USB, unlock, accept Trust, and verify that it shows up in a real USB lockdown connection. No app install is required.
2. Run from SideTapIntegration/SideTap with the existing Python environment and PYTHONPATH pointing to src:

    python -m phone_harness wireless-discover

3. Set SIDETAP_UDID to the EXACT USB-verified iPhone identifier, then explicitly run:

    python -m phone_harness wireless-enable --confirm

   This is the only action that changes a phone setting; if the trusted USB connection cannot be verified, it fails without changing the phone.

4. Set SIDETAP_TRANSPORT=wifi and keep SIDETAP_UDID pinned. Physically unplug USB; both PC and phone need reachable Wi-Fi/LAN. Run:

    python -m phone_harness wireless-discover
    python -m phone_harness wireless-status

   Status must report ready=true and verified_network_device=true, while USB discovery is empty. A cached "Network" label is NOT sufficient.

5. To try WDA-free native gestures through the original SideTap viewer, opt in with SIDETAP_DIRECT_ENABLE=1 and run:

    python -m phone_harness direct-status

   Launch SideTap's original viewer (or its existing TLS-paired LiveContainer companion) and confirm the screen updates and controlled gestures land. This does not need an additional signed WDA app slot, but semantic AX/XCTest operations will not become available.

6. When using WDA instead, do not opt into direct HID. The existing go-ios WDA code continues through the paired Wi-Fi route if both network enumeration and the signed runner are available.

## Failure classifications

- No USB or Wi-Fi devices: physical or trust/discovery connection absent; do not claim wireless readiness.
- USB present but Wi-Fi disabled: run the explicit opt-in enablement command.
- Bonjour present but Apple usbmux Wi-Fi enumeration absent: paired Wi-Fi advertising is not enough for go-ios; check Apple Mobile Device Service and pair records.
- Network device present but cannot open lockdown: cached/stale entry; refuse input.
- Paired Wi-Fi lockdown succeeds but go-ios cannot enumerate: WDA-based functions cannot be claimed operational.
- WDA runner absent: no UI accessibility tree; CoreDevice still supports primitive HID if network and developer services work.
- Phone is on mobile data or outside the local route: the encrypted SideTap web companion on the PC may be reachable, but that alone does not extend Apple's paired developer connection to the device. A secure relay/VPN would need a separate, tested transport design.

## Safety & regression requirements

Original USB behavior is the default. Missing or ambiguous device identity refuses all wireless input. No changes to firewall rules, Apple ID, app IDs, certificates, or iPhone installations are performed. New actions honor SideTap STOP and do not auto-replay uncertain input after a timeout. Cross-platform unit/HTTP tests simulate discovery and touch routing; only a true unplugged-device test can establish full operation.

## Open verification gates

- Enable Wi-Fi debugging with the device physically reconnected and USB-trusted.
- Network-only lockdown handshake after removing the cable.
- Native screenshot availability over go-ios Wi-Fi; verified touch, drag, and typing on iOS 18.7.7.
- Recovery after lock, sleep, rotation and Wi-Fi drops; latency and battery measurements.
- SideTap companion UI remains authenticated and the user's STOP switch remains effective.
