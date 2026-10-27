# Updated physical-device verdict (October 27, 2026)

The missing developer image was restored successfully over the official
userspace tunnel. After that, the iPhone advertised 80 RSD services and
accepted DisplayService metadata requests, but rejected actual video
startup with code 9021: **"Remote control requires iOS 27.0 or later
on this device."** This handset is on iOS 18.7.7. Native CoreDevice
HEVC is therefore unavailable despite restored pairing, DDI and Wi-Fi.

The standalone Windows AirPlay receiver has been launched as an alternate
continuous-video route, with GPU decoding and mDNS advertisement verified.
No AirPlay video session has been confirmed; Windows Firewall contains
explicit inbound block rules for this receiver. They remain unchanged.

See [HEVC_FINDINGS_20261027.md](HEVC_FINDINGS_20261027.md) for measured
service-directory changes, commands, the device error and next steps.

---

# SideTap continuous HEVC video: engineering and release gates

Status: source-backed and protocol-tested; not yet device-certified.
The iPhone appears on Bonjour, but Windows Apple usbmux currently reports no
Network device. The available no-root RSD provider cannot open DisplayService.
Never claim a live HEVC stream or invent an FPS from successful DVT screenshots.

## Architecture

CoreDevice DisplayService.start_video_stream initiates a device-originated
hardware HEVC stream. The existing upstream implementation delivers UDP RTP
through RSD and performs RFC 7798 depacketization, keyframe repair,
VPS/SPS/PPS recovery, and browser WebCodecs decoding into a canvas.

This avoids repeated PNG screenshot RPCs, PNG encoding and file transfers,
but a real throughput improvement still depends on device RTP behavior and
the browser decoder.

Upstream references:
https://doronz88.github.io/pymobiledevice3/guides/cli-recipes/
https://doronz88.github.io/pymobiledevice3/guides/ios17-tunnels/
https://github.com/doronz88/pymobiledevice3/blob/master/pymobiledevice3/remote/core_device/display_service.py
https://github.com/doronz88/pymobiledevice3/blob/master/pymobiledevice3/remote/core_device/screen_stream.py

## Implemented certification command

- phone-harness wireless-media-status: separate, read-only DisplayService
  support-info and running-state probes.
- phone-harness hevc-probe --confirm: refuses to open streaming without a
  pinned SIDETAP_UDID, SIDETAP_TRANSPORT=wifi, paired network-only lockdown,
  an unplugged USB connection, and available media service.
- Captures up to 4 seconds of length-prefixed RTP through pymobiledevice3
  userspace RSD (configurable duration 2-10s in Python), then discards its
  temporary file and returns packet counts, timestamp count, marker count,
  aggregate payload bitrate and approximate distinct-timestamp rate.
- Explicit timeout and 64 MiB post-capture size check. Malformed/truncated RTP
  fails closed. Never promises HEVC browser decode or a video FPS based solely
  on the presence of RTP packets.
- No LAN HTTP listener, raw screenshot output, touch events, paired-device
  mutation, new IPA or signing slot is involved.

An actual video session can conflict with the device's camera/microphone;
the upstream capture command also calls stop_media_stream(stop_all=True)
on exit and may disrupt another active mirroring session. Use only with
explicit consent and no other active screen-mirroring session. Production
use must manage/stop only its own session instead.

## Physical certification matrix

Source API: confirmed.
USB-free DVT screenshot: previously physically confirmed.
HEVC media support from this iPhone: BLOCKED by usbmux network enumeration.
Received RTP packets: NOT VERIFIED.
HEVC VPS/SPS/PPS and keyframes: NOT VERIFIED.
Browser WebCodecs playback: NOT VERIFIED.
Sustainable video FPS/latency: NOT MEASURED.
Wi-Fi HID touch: NOT VERIFIED and previously rejected by service.
TLS-authenticated same-origin HEVC viewer relay: NOT IMPLEMENTED.

## Design for eventual SideTap viewer

The upstream serve-web surface includes watch and CONTROL paths (touch,
keyboard, buttons, clipboard). Do not expose it unchanged or bind it to
all LAN interfaces. Use SideTap's existing TLS-pinned HTTPS companion and
authenticated cookie, with a strictly read-only frame/codec proxy. Enforce
same-origin and endpoint allowlists; exclude every upstream action route;
apply backpressure, slow-client limits, cancellation on tab hide/unpair and
frame staleness indicators. Video availability is independent of HID input.

HEVC is only a candidate until it succeeds on this iOS 18.7.7 handset.
Rust/PyO3 acceleration is premature absent proof of Python-side CPU
bottlenecks rather than transport or device-side encoding latency.
