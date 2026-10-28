# One-slot LiveContainer + SideStore + SideTap + WebDriverAgent

The single installed principal application is LiveContainer. SideStore remains
embedded as a framework. SideTap remains a native full-screen view of the
Windows viewer. Appium WebDriverAgentRunner.xctest and its
WebDriverAgentLib.framework are now packaged inside the *same* LiveContainer.

There is no standalone WDA app and no Sideloadly step.

## Build and install the combined IPA

Open the GitHub Actions page for the feature/one-slot-sidetap-wda branch:
https://github.com/thelabcorner/LiveContainer/actions/workflows/build.yml

Open the successful Xcode - Build run; its additional combined artifact is
com.kdt.livecontainer.ipa. Install that new IPA using the existing LiveContainer
upgrade/signing workflow, NOT by uninstalling the previous app. Retain the
same signing identity, user data, SideStore, and app slot. Do not install any
WebDriverAgent IPA separately.

The Appium WDA v13.2.0 upstream asset is pinned and verified with SHA256:
448ffe591cf64abf7ff0751897b6860cd45b8032b39677a5dd79f827c4d781cc

## USB runtime

The bundled SideTap Python harness defaults to SIDETAP_WDA_MODE=embedded-livecontainer.
It detects the signed primary LiveContainer installed-app bundle ID, even
when an Apple signing suffix is appended, and passes that same ID to
go-ios runwda as the XCTest runner host. The expected loopback HTTP endpoint
is http://127.0.0.1:8100/status over USB forwarding.

A mounted personalized Developer Disk Image is required. On October 27,
pymobiledevice3 successfully mounted it over USB on iOS 18.7.7:
python -m pymobiledevice3 mounter auto-mount --userspace --udid YOUR_UDID

## Verification after installation

The GitHub packaging and archive tests certify a single principal app,
matching bundle identity, pinned WDA bytes and nested XCTest bundle, but
DO NOT prove Apple's testmanagerd accepts LiveContainer as the runner host.
After manual upgrade, the decisive checks are actual runwda launch logs,
an HTTP /status response, tap/drag/type actions, simultaneous SideTap UI,
shared session, extensions, 7-day refresh and saved-app data continuity.

If Apple's daemon refuses the executable/bootstrap, report that real error
without installing a second app. The design target remains ONE LiveContainer.
