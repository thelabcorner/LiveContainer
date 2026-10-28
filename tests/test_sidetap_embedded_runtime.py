"""One-slot LiveContainer WDA runtime selection and no-sideload invariants."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "SideTapIntegration" / "SideTap" / "src"))
from phone_harness import config, device, signing  # noqa: E402


PRIMARY = "com.kdt.livecontainer.42CD8995T6"
SECONDARY = "com.kdt.LiveContainer2.42CD8995T6"


class EmbeddedRunnerDetection(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.state = Path(temp.name)
        for name, value in (
            ("STATE_DIR", self.state),
            ("WDA_BUNDLE_ID", None),
            ("SIDETAP_WDA_MODE", "embedded-livecontainer"),
        ):
            p = patch.object(config, name, value)
            p.start()
            self.addCleanup(p.stop)

    def _apps(self, entries):
        p = patch.object(device, "list_apps", return_value=entries)
        p.start()
        self.addCleanup(p.stop)

    def test_selects_only_signed_primary_livecontainer(self):
        self._apps([
            {"bundle_id": SECONDARY, "name": "LiveContainer2 3.8.10"},
            {"bundle_id": PRIMARY, "name": "LiveContainer 3.8.11"},
        ])
        self.assertEqual(device.detect_wda_bundle(), PRIMARY)
        self.assertEqual((self.state / "wda_bundle").read_text(), PRIMARY)

    def test_never_falls_back_to_standalone_wda(self):
        self._apps([{"bundle_id": "com.facebook.WebDriverAgentRunner.xctrunner",
                     "name": "WebDriverAgent"}])
        self.assertIsNone(device.detect_wda_bundle())

    def test_does_not_consider_livecontainer2_primary(self):
        self._apps([{"bundle_id": SECONDARY, "name": "LiveContainer2 3.8.10"}])
        self.assertIsNone(device.detect_wda_bundle())

    def test_cached_primary_used_during_sleep(self):
        (self.state / "wda_bundle").write_text(PRIMARY)
        self._apps([])
        self.assertEqual(device.detect_wda_bundle(), PRIMARY)

    def test_stale_standalone_cache_does_not_leak_into_embed_mode(self):
        (self.state / "wda_bundle").write_text("com.facebook.WebDriverAgentRunner.xctrunner")
        self._apps([])
        self.assertIsNone(device.detect_wda_bundle())

    def test_never_invokes_standalone_signing_tool(self):
        with patch.object(signing, "build_p12", side_effect=AssertionError("separate signer called")):
            response = signing.fix_input()
        self.assertFalse(response["ok"])
        self.assertEqual(response["step"], "integrated")
        self.assertIn("single LiveContainer IPA", response["message"])


if __name__ == "__main__":
    unittest.main()
