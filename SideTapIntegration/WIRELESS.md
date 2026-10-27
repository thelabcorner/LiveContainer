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
