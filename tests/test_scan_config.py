import pytest
from jobscanner.scan_config import ScanPreset, SCAN_PRESETS, BROWSER_CAPS, browser_caps_for


def test_presets_have_expected_values():
    assert SCAN_PRESETS["klein"] == ScanPreset(5, 20, 3, 50)
    assert SCAN_PRESETS["mittel"] == ScanPreset(10, 60, 6, 150)
    assert SCAN_PRESETS["gross"] == ScanPreset(15, None, None, None)


def test_preset_is_frozen():
    import dataclasses
    with pytest.raises(dataclasses.FrozenInstanceError):
        SCAN_PRESETS["klein"].limit_per_query = 99


def test_gross_is_unbounded():
    p = SCAN_PRESETS["gross"]
    assert p.max_scrapes_per_portal is None
    assert p.max_search_terms is None
    assert p.member_max_jobs is None


def test_browser_caps_mapping_from_spar_max_jobs():
    assert browser_caps_for(10) is BROWSER_CAPS["klein"]
    assert browser_caps_for(50) is BROWSER_CAPS["klein"]
    assert browser_caps_for(100) is BROWSER_CAPS["mittel"]
    assert browser_caps_for(150) is BROWSER_CAPS["mittel"]
    assert browser_caps_for(151) is BROWSER_CAPS["gross"]
    assert browser_caps_for(None) is BROWSER_CAPS["gross"]


def test_browser_caps_all_sizes_hard_bounded():
    # Heim-IP-Bann-Schutz: auch "gross" nie unlimitiert, Throttle nie unter 1s.
    for caps in BROWSER_CAPS.values():
        assert caps.max_queries > 0
        assert caps.max_detail > 0
        assert caps.throttle_ms >= 1000
