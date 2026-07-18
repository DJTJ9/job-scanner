import pytest
from jobscanner.scan_config import ScanPreset, SCAN_PRESETS


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
