# HEVC iOS 18.7.7 physical findings — October 27, 2026

This section supersedes earlier tentative language elsewhere in this document.

## The device-side HEVC blocker has been identified

The phone's battery drained and it rebooted. Before remounting its
personalized DeveloperDiskImage (DDI), a correctly paired Wi-Fi RSD tunnel
advertised 59 services, including Instruments, but **zero**
com.apple.coredevice.* services. SideTap now reads the authenticated RSD
directory, checks the selected UDID, and reports the exact absent services
before requesting HEVC. Service presence must never be guessed from a
working tunnel.

The ordinary image-mounter path failed during
QueryPersonalizationManifest: the device terminated the connection. The
official userspace path succeeded without a cable or IPA changes:

    pymobiledevice3 mounter auto-mount --userspace --udid <pinned-UDID>

The command obtained Apple's signed personalization ticket and successfully
mounted the DDI. After mounting, the exact same Wi-Fi tunnel advertised
**80 services**, including **17 com.apple.coredevice.* services**. The
displayservice, screencaptureservice and universalhidservice entries were
present and the media support/status requests succeeded.

The live streaming test then reached DisplayService.start_video_stream
and the device rejected it with:

    Remote control requires iOS 27.0 or later on this device. (code 9021)

This is the authoritative blocker for native CoreDevice HEVC on the
current iPhone running iOS 18.7.7. It is no longer missing mDNS, missing
DDI, absent services, Python performance or protocol negotiation. Do not
keep retrying this gated RPC or claim CoreDevice HEVC playback works.
Presence of a coredevice HID service likewise does **not** authorize
touch injection; service availability and OS policy are independent.

The only previously certified wireless capture was the DVT screenshot
path, slower than hardware-streamed video. Keep that fail-closed fallback
for the existing one-slot SideTap stack. The newly added HEVC RTP
certification suite stays useful for a future device/OS that genuinely
supports the stream.

## Alternative independent video path: AirPlay screen mirroring

On the same date we downloaded the standalone native Windows receiver from

    https://github.com/moieric11/AirPlay-Windows/releases/tag/v0.4.1

The x64 portable ZIP hash was independently verified against the release
asset's published SHA-256:
5f1792a96efffe84b220edfa7286fa7670806226aa4d0b4b6c7e33ddd7747bf9

The portable receiver is **not** bundled into SideTap or its IPA. It
was started separately on Windows, with Direct3D 11 hardware decoding
initialized on the RTX 2060. Logs reported listening on TCP 7000 and
successfully publishing AirPlay-Windows._airplay._tcp.local over mDNS.

**Actual video transmission has NOT yet been observed.** The iPhone must
start Screen Mirroring from Control Center and choose AirPlay-Windows.
Windows Firewall currently has explicit enabled inbound *Block* rules
named airplay-windows for TCP and UDP on its Public network profile.
Those user/system rules were inspected but NOT overridden. Do not open
all ports, disable the firewall or override those block rules without
a deliberate authorization and a restricted local-subnet firewall plan.

The receiver advertises H.264 and HEVC decoder support. Whether the iPhone
chooses either codec is subject to real AirPlay negotiation. This is
read-only screen mirroring; it does not restore wired or wireless touch
control. The existing TLS-authenticated SideTap companion remains
unchanged; do not expose the receiver's control/administration endpoints
through the companion without a separate security review.

Apple's ScreenCaptureKit system-wide sharing API is only available on
iOS 27+, so it cannot be substituted as an on-device iOS 18 solution.
ReplayKit's system-wide broadcast-upload extension is another legitimate
alternative for iOS 18, but requires an additional signed app extension
and explicit on-device screen-broadcast consent. It is not part of the
existing one-slot IPA. See Apple's ReplayKit developer documentation.

References:
https://doronz88.github.io/pymobiledevice3/guides/troubleshooting/
https://doronz88.github.io/pymobiledevice3/guides/ios17-tunnels/
https://github.com/moieric11/AirPlay-Windows
https://developer.apple.com/documentation/replaykit
