"""Release packaging invariants for the one-app LiveContainer/WDA integration."""
from __future__ import annotations

import importlib.util
import plistlib
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location("one_slot_wda_build", ROOT / "scripts/build_sidetap_wda_ipa.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
validator_spec = importlib.util.spec_from_file_location("one_slot_wda_validator", ROOT / "scripts/validate_sidetap_bundle.py")
validator = importlib.util.module_from_spec(validator_spec)
validator_spec.loader.exec_module(validator)


def archive(path, members):
    with zipfile.ZipFile(path, "w") as z:
        for name, contents in members.items():
            z.writestr(name, contents)


def host_members():
    return {
        "Payload/LiveContainer.app/Info.plist": plistlib.dumps({
            "CFBundleIdentifier": "com.kdt.livecontainer", "CFBundleExecutable": "LiveContainer"
        }),
        "Payload/LiveContainer.app/LiveContainer": b"existing-executable",
        "Payload/LiveContainer.app/Frameworks/SideStoreApp.framework/SideStore": b"existing-sidestore",
        "Payload/LiveContainer.app/PlugIns/LiveProcess.appex/LiveProcess": b"other-extension",
        "Payload/LiveContainer.app/PlugIns/LiveProcess.appex/Info.plist": plistlib.dumps({
            "CFBundleIdentifier": "com.kdt.livecontainer.LiveProcess",
            "CFBundleExecutable": "LiveProcess",
        }),
    }


def wda_members():
    p = "WebDriverAgentRunner-Runner.app/PlugIns/WebDriverAgentRunner.xctest/"
    return {
        "WebDriverAgentRunner-Runner.app/Info.plist": plistlib.dumps({
            "CFBundleIdentifier": "com.facebook.WebDriverAgentRunner.xctrunner",
            "CFBundlePackageType": "APPL",
        }),
        p + "Info.plist": plistlib.dumps({
            "CFBundleIdentifier": "com.facebook.WebDriverAgentRunner",
            "CFBundleExecutable": "WebDriverAgentRunner", "CFBundlePackageType": "BNDL",
        }),
        p + "WebDriverAgentRunner": b"test-runner",
        p + "Frameworks/WebDriverAgentLib.framework/WebDriverAgentLib": b"wda-library",
        p + "Frameworks/WebDriverAgentLib.framework/Info.plist": b"framework",
        p + "WebDriverAgentRunner.xctest.dSYM/Contents/Info.plist": b"debug-only",
    }


class ReleasePackaging(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.host = self.root / "host.ipa"
        self.wda = self.root / "wda.zip"
        self.out = self.root / "com.kdt.livecontainer.ipa"
        archive(self.host, host_members())
        archive(self.wda, wda_members())

    def build(self):
        return module.package(self.host, self.wda, self.out, check_hash=False)

    def test_single_identity_and_existing_components_preserved(self):
        report = self.build()
        self.assertEqual(report["principal_app_count"], 1)
        self.assertFalse(report["xctest_bootstrap_verified"])
        self.assertTrue(validator.inspect_ipa(self.out, require_wda=True)["valid_structure"])
        with zipfile.ZipFile(self.out) as ipa:
            self.assertEqual(ipa.read("Payload/LiveContainer.app/LiveContainer"), b"existing-executable")
            self.assertEqual(ipa.read("Payload/LiveContainer.app/Frameworks/SideStoreApp.framework/SideStore"), b"existing-sidestore")
            self.assertNotIn("Payload/WebDriverAgentRunner-Runner.app/Info.plist", ipa.namelist())
            self.assertNotIn(module.PLUGIN + "WebDriverAgentRunner.xctest.dSYM/Contents/Info.plist", ipa.namelist())
            info = plistlib.loads(ipa.read("Payload/LiveContainer.app/Info.plist"))
            self.assertEqual(info["LCEmbeddedWDARunner"]["TestBundle"], "WebDriverAgentRunner.xctest")

    def test_iloader_052_bundle_id_rewrite_regression(self):
        report = self.build()
        self.assertEqual(report["embedded_wda_bundle_id"], "com.kdt.livecontainer.WebDriverAgentRunner")
        with zipfile.ZipFile(self.out) as ipa, zipfile.ZipFile(self.wda) as source:
            host_id = plistlib.loads(ipa.read(module.HOST + "Info.plist"))["CFBundleIdentifier"]
            wda_info = plistlib.loads(ipa.read(module.PLUGIN + "Info.plist"))
            runner_id = wda_info["CFBundleIdentifier"]
            # Reproduce the exact isideload 0.5.2 application.rs:170-181
            # prefix predicate and the signed-host substitution.
            self.assertTrue(runner_id.startswith(host_id) and len(runner_id) > len(host_id))
            signed_host = host_id + ".TESTTEAM"
            self.assertEqual(signed_host + runner_id[len(host_id):],
                             "com.kdt.livecontainer.TESTTEAM.WebDriverAgentRunner")
            self.assertEqual(wda_info["CFBundleExecutable"], "WebDriverAgentRunner")
            self.assertEqual(ipa.read(module.PLUGIN + "WebDriverAgentRunner"),
                             source.read(module.WDA_PREFIXES[0] + "WebDriverAgentRunner"))
            self.assertEqual(plistlib.loads(source.read(module.WDA_PREFIXES[0] + "Info.plist"))["CFBundleIdentifier"],
                             "com.facebook.WebDriverAgentRunner")
            self.assertEqual(ipa.read(module.HOST + "PlugIns/LiveProcess.appex/Info.plist"),
                             host_members()[module.HOST + "PlugIns/LiveProcess.appex/Info.plist"])

    def test_unexpected_source_bundle_id_rejected(self):
        members = wda_members()
        name = module.WDA_PREFIXES[0] + "Info.plist"
        info = plistlib.loads(members[name])
        info["CFBundleIdentifier"] = "unrelated.runner"
        members[name] = plistlib.dumps(info)
        archive(self.wda, members)
        with self.assertRaisesRegex(module.PackagingError, "upstream WDA test bundle identifier"):
            self.build()
        self.assertFalse(self.out.exists())

    def test_source_checksum_protected(self):
        with self.assertRaisesRegex(module.PackagingError, "SHA-256"):
            module.package(self.host, self.wda, self.out)
        self.assertFalse(self.out.exists())

    def test_missing_runner_cannot_produce_ipa(self):
        incomplete = wda_members()
        del incomplete["WebDriverAgentRunner-Runner.app/PlugIns/WebDriverAgentRunner.xctest/WebDriverAgentRunner"]
        archive(self.wda, incomplete)
        with self.assertRaisesRegex(module.PackagingError, "runner executable"):
            self.build()
        self.assertFalse(self.out.exists())

    def test_no_overwriting_existing_archive(self):
        self.out.write_bytes(b"protected")
        with self.assertRaisesRegex(module.PackagingError, "Output"):
            self.build()
        self.assertEqual(self.out.read_bytes(), b"protected")

    def test_never_accepts_second_principal_application(self):
        bad = host_members()
        bad["Payload/Second.app/Info.plist"] = plistlib.dumps({"CFBundleIdentifier": "x.y"})
        archive(self.host, bad)
        with self.assertRaisesRegex(module.PackagingError, "one principal"):
            self.build()

    def test_host_identity_is_upgrade_stable(self):
        bad = host_members()
        bad["Payload/LiveContainer.app/Info.plist"] = plistlib.dumps({
            "CFBundleIdentifier": "com.new.bundle", "CFBundleExecutable": "LiveContainer",
        })
        archive(self.host, bad)
        with self.assertRaisesRegex(module.PackagingError, "bundle ID changed"):
            self.build()


if __name__ == "__main__":
    unittest.main()


class SideStoreAuthFixRegression(unittest.TestCase):
    """Runs in the existing Ubuntu structural audit and macOS IPA test step."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.config = self.root / "SideStore/Core/Anisette/AnisetteConfigManager.swift"
        self.auth = self.root / "Dependencies/SideSign/Sources/DeveloperPortal/Authentication.swift"
        self.config.parent.mkdir(parents=True)
        self.auth.parent.mkdir(parents=True)
        patch_spec = importlib.util.spec_from_file_location(
            "sidestore_authfix_patch", ROOT / "scripts/patch_sidestore_authfix.py"
        )
        self.patch = importlib.util.module_from_spec(patch_spec)
        patch_spec.loader.exec_module(self.patch)
        for relative, replacements in self.patch.EDIT_MAP.items():
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            fixture = "\n".join(old for old, new in replacements) + "\n"
            if relative == self.patch.CONFIG_PATH:
                fixture = "let useOnDeviceAnisette = true\n" + fixture + "let remoteAnisette = true\n"
            path.write_text(fixture, encoding="utf-8")

    def test_both_providers_and_both_apple_auth_paths_are_fixed(self):
        changes = self.patch.patch_sources(self.root, verify_git=False)
        self.assertEqual(changes[self.patch.CONFIG_PATH], 1)
        self.assertEqual(changes[self.patch.AUTH_PATH], 4)
        self.assertEqual(changes[self.patch.ERROR_PATH], 3)
        self.assertEqual(changes[self.patch.SIGN_IN_PATH], 4)
        self.assertEqual(changes[self.patch.PROTOCOL_PATH], 1)
        self.assertEqual(changes[self.patch.HANDLER_PATH], 1)
        config = self.config.read_text()
        auth = self.auth.read_text()
        self.assertIn("let useOnDeviceAnisette = true", config)
        self.assertIn("let remoteAnisette = true", config)
        self.assertEqual(config.count('replacingOccurrences(of: "<macOS;", with: "<Mac OS X;")'), 1)
        self.assertEqual(auth.count('replacingOccurrences(of: "<macOS;", with: "<Mac OS X;")'), 2)
        self.assertNotIn("new.ani.sidestore.io", config + auth)
        self.assertNotIn("resetToDefaults", config + auth)

    def test_rerunning_patch_or_partial_source_drift_is_rejected(self):
        self.patch.patch_sources(self.root, verify_git=False)
        with self.assertRaisesRegex(self.patch.PatchError, "source anchor"):
            self.patch.patch_sources(self.root, verify_git=False)

    def test_patch_is_atomic_before_writes(self):
        before = self.config.read_text()
        self.auth.write_text("unexpected upstream source", encoding="utf-8")
        with self.assertRaisesRegex(self.patch.PatchError, "source anchor"):
            self.patch.patch_sources(self.root, verify_git=False)
        self.assertEqual(self.config.read_text(), before)

    def test_pinned_provenance_and_marked_version(self):
        self.assertEqual(self.patch.SIDESTORE_COMMIT, "044bd72ad4eb270c3900bd04dc6f508d0ac474db")
        self.assertEqual(self.patch.SIDESIGN_COMMIT, "752d1ef602aa792a432ffa1e71646dc1ecf7363c")
        self.assertEqual(self.patch.ANISETTEKIT_COMMIT, "db8b41022697b6c19be8a5f01a1ce834145a2a26")
        self.assertIn("authfix", self.patch.MARKETING_VERSION)

    def test_recovery_requires_stage_consent_and_previous_blob(self):
        self.patch.patch_sources(self.root, verify_git=False)
        source = (self.root / self.patch.SIGN_IN_PATH).read_text()
        auth = (self.root / self.patch.AUTH_PATH).read_text()
        errors = (self.root / self.patch.ERROR_PATH).read_text()
        handler = (self.root / self.patch.HANDLER_PATH).read_text()
        proto = (self.root / self.patch.PROTOCOL_PATH).read_text()
        self.assertIn('authPhase = requestParameters["o"] as? String ?? "unknown"', auth)
        self.assertIn('if errorCode == -22410', auth)
        self.assertIn('case grandSlamRejection(code: Int, phase: String, message: String)', errors)
        self.assertIn('code == -22410, phase == "init"', source)
        self.assertIn('let previouslyStoredAdi = AnisetteConfigManager.shared.anisetteAdiBlob', source)
        self.assertIn('let oldBlob = previouslyStoredAdi, !oldBlob.isEmpty', source)
        self.assertIn('guard await self.signInHandler.confirmStaleAnisetteRecovery() else', source)
        self.assertIn('func confirmStaleAnisetteRecovery() async -> Bool', proto)
        self.assertIn('func confirmStaleAnisetteRecovery() async -> Bool', handler)
        self.assertIn('Keep Current Identity', handler)
        self.assertIn('Try Fresh Provisioning', handler)
        self.assertIn('let provider = useOnDevice ? "on-device"', source)
        self.assertNotIn('UserDefaults.standard.useOnDeviceAnisette = false', source)

    def test_failed_recovery_restores_blob_and_preserves_certificate(self):
        self.patch.patch_sources(self.root, verify_git=False)
        source = (self.root / self.patch.SIGN_IN_PATH).read_text()
        self.assertIn('await AuthManager.shared.signOut(keepCertificate: true)', source)
        self.assertNotIn('await AuthManager.shared.signOut()', source)
        self.assertEqual(source.count('AnisetteConfigManager.shared.anisetteAdiBlob = nil'), 1)
        self.assertEqual(source.count('AnisetteConfigManager.shared.anisetteAdiBlob = oldBlob'), 1)
        self.assertIn('AnisetteDataManager.shared.clearCache()', source)
        self.assertIn('if self.isCancelled { throw OperationError.cancelled }', source)
        self.assertEqual(source.count('result = try await self.performAppleSignIn('), 2)
        self.assertNotIn('Keychain.shared.clearAll()', source)

    def test_one_attempt_state_does_not_store_raw_adi(self):
        self.patch.patch_sources(self.root, verify_git=False)
        source = (self.root / self.patch.SIGN_IN_PATH).read_text()
        self.assertIn('private actor StaleAnisetteRecoveryGate', source)
        self.assertIn('Data(SHA256.hash(data: Data(context.utf8))).base64EncodedString()', source)
        self.assertIn('func canAttempt(_ fingerprint: String) -> Bool', source)
        self.assertIn('guard canAttempt(fingerprint) else { return false }', source)
        self.assertIn('UserDefaults.standard.set(fingerprint, forKey: attemptKey)', source)
        self.assertNotIn('UserDefaults.standard.set(blob,', source)

    def test_six_source_preflight_failure_is_atomic(self):
        before = {p: (self.root / p).read_bytes() for p in self.patch.EDIT_MAP}
        missing = self.root / self.patch.PROTOCOL_PATH
        missing.write_text("unexpected source", encoding="utf-8")
        with self.assertRaisesRegex(self.patch.PatchError, "source anchor"):
            self.patch.patch_sources(self.root, verify_git=False)
        for path, original in before.items():
            if path != self.patch.PROTOCOL_PATH:
                self.assertEqual((self.root / path).read_bytes(), original)
