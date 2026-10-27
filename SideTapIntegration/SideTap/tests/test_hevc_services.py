"""No-device RSD service inventory verification."""
import pytest
from phone_harness import hevc_services


def test_realistic_ios_18_catalog_does_not_claim_hevc():
    raw = {"com.apple.mobile.lockdown.remote.trusted": {"Port": 13},
           "com.apple.instruments.dtservicehub": {"Port": 47}}
    raw.update({"com.example.service" + str(i): {"Port": i} for i in range(57)})
    report = hevc_services.summarize_services(raw)
    assert report["service_count"] == 59
    assert report["instruments_dvt_present"] is True
    assert report["coredevice_service_count"] == 0
    assert report["hevc_display_advertised"] is False
    assert report["services"][hevc_services.TARGETS[1]] is False
    assert report["services"][hevc_services.TARGETS[2]] is False


def test_display_advertisement_independent_of_hid():
    raw = {"com.apple.coredevice.displayservice": {"Port": 9000},
           "com.apple.instruments.dtservicehub": {}}
    result = hevc_services.summarize_services(raw)
    assert result["hevc_display_advertised"] is True
    assert result["coredevice_service_count"] == 1
    assert result["services"][hevc_services.TARGETS[2]] is False


@pytest.mark.parametrize("not_directory", [None, [], "invalid", 42])
def test_missing_directory_fails_closed(not_directory):
    with pytest.raises(hevc_services.RSDInventoryError, match="directory"):
        hevc_services.summarize_services(not_directory)


@pytest.mark.parametrize("udid", [None, "", "bad device", 15])
def test_invalid_target_refused_without_connecting(udid):
    with pytest.raises(hevc_services.RSDInventoryError, match="pinned"):
        hevc_services.probe(udid)
