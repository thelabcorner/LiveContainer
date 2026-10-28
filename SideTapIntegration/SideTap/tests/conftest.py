"""Keep imported upstream standalone-WDA test contracts isolated from fork defaults.

The production one-slot build defaults to embedded-livecontainer. Existing
upstream fixture expectations intentionally exercise their legacy mode.
"""
import pytest
from phone_harness import config


@pytest.fixture(autouse=True)
def legacy_wda_mode_for_existing_upstream_tests(monkeypatch):
    monkeypatch.setattr(config, "SIDETAP_WDA_MODE", "separate")
