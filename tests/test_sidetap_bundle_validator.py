import importlib.util
import io
import plistlib
import tempfile
import unittest
import zipfile
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "scripts" / "validate_sidetap_bundle.py"
spec = importlib.util.spec_from_file_location("validator", MODULE_PATH)
validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)


def make_ipa(path, *, extra_app=False, xctest=False, in_wrong_parent=False, missing_runner=False):
    host = "Payload/LiveContainer.app/"
    manifest = {
        host + "Info.plist": plistlib.dumps({"CFBundleIdentifier": "com.kdt.livecontainer", "CFBundleExecutable": "LiveContainer"}),
        host + "LiveContainer": b"mock Mach-O",
        host + "Frameworks/SideStoreApp.framework/SideStore": b"mock SideStore",
    }
    if extra_app:
        manifest["Payload/WebDriverAgent.app/Info.plist"] = b"app"
    if xctest:
        prefix = (host + "Frameworks/SideStoreApp.framework/" if in_wrong_parent else host) + "PlugIns/WebDriverAgentRunner.xctest/"
        manifest[prefix + "Info.plist"] = plistlib.dumps({"CFBundleExecutable": "WebDriverAgentRunner"})
        if not missing_runner:
            manifest[prefix + "WebDriverAgentRunner"] = b"mock XCTest"
    with zipfile.ZipFile(path, "w") as z:
        for name, data in manifest.items():
            z.writestr(name, data)


class TestOneSlotIPAStructure(unittest.TestCase):
    def test_baseline_single_app_preserved(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "baseline.ipa"
            make_ipa(path)
            result = validator.inspect_ipa(path)
            self.assertTrue(result["valid_structure"], result["errors"])
            self.assertEqual(result["native_apps"], ["LiveContainer.app"])
            self.assertEqual(result["xctest_bundles"], [])

    def test_require_wda_fails_when_absent(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "baseline.ipa"
            make_ipa(path)
            self.assertFalse(validator.inspect_ipa(path, require_wda=True)["valid_structure"])

    def test_second_registered_app_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "two-apps.ipa"
            make_ipa(path, extra_app=True)
            self.assertFalse(validator.inspect_ipa(path)["valid_structure"])

    def test_nested_xctest_structurally_accepted_but_not_claimed_functional(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "bundle.ipa"
            make_ipa(path, xctest=True)
            result = validator.inspect_ipa(path, require_wda=True)
            self.assertTrue(result["valid_structure"], result["errors"])
            self.assertTrue(any("XCTest bootstrap" in x for x in result["warnings"]))

    def test_wrong_parent_for_xctest_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "guest.ipa"
            make_ipa(path, xctest=True, in_wrong_parent=True)
            self.assertFalse(validator.inspect_ipa(path)["valid_structure"])

    def test_missing_xctest_executable_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "broken.ipa"
            make_ipa(path, xctest=True, missing_runner=True)
            self.assertFalse(validator.inspect_ipa(path)["valid_structure"])

    def test_duplicate_paths_are_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "dup.ipa"
            make_ipa(path)
            with zipfile.ZipFile(path, "a") as z:
                z.writestr("Payload/LiveContainer.app/Info.plist", b"duplicate")
            self.assertFalse(validator.inspect_ipa(path)["valid_structure"])


if __name__ == "__main__":
    unittest.main()
