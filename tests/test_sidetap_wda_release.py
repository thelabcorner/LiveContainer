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
    }


def wda_members():
    p = "WebDriverAgentRunner-Runner.app/PlugIns/WebDriverAgentRunner.xctest/"
    return {
        "WebDriverAgentRunner-Runner.app/Info.plist": plistlib.dumps({
            "CFBundleIdentifier": "com.facebook.WebDriverAgentRunner.xctrunner",
            "CFBundlePackageType": "APPL",
        }),
        p + "Info.plist": plistlib.dumps({
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
