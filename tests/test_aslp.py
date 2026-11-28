import pytest

from climbing_performance.aslp import (
    cp_remaining_fraction_at_altitude,
    cp_remaining_fraction_range_at_altitude,
    sea_level_equivalent_power,
    altitude_power_loss_percent,
    estimate_aslp_wkg,
    summarise_aslp,
)


def test_cp_fraction_is_1_at_low_altitude():
    assert cp_remaining_fraction_at_altitude(0.0) == pytest.approx(1.0)
    assert cp_remaining_fraction_at_altitude(250.0) == pytest.approx(1.0)


def test_cp_fraction_declines_with_altitude():
    low = cp_remaining_fraction_at_altitude(250.0)
    mid = cp_remaining_fraction_at_altitude(2250.0)
    high = cp_remaining_fraction_at_altitude(4250.0)

    assert low > mid > high
    assert mid == pytest.approx(0.8707, rel=1e-3)
    assert high == pytest.approx(0.7258, rel=1e-3)


def test_sea_level_equivalent_power_exceeds_estimated_power_at_altitude():
    estimated = 350.0
    corrected = sea_level_equivalent_power(estimated, 2250.0)

    assert corrected > estimated
    assert corrected == pytest.approx(350.0 / 0.8707, rel=1e-3)


def test_altitude_loss_percent_is_zero_at_low_altitude():
    assert altitude_power_loss_percent(0.0) == pytest.approx(0.0)
    assert altitude_power_loss_percent(250.0) == pytest.approx(0.0)


def test_aslp_wkg():
    result = estimate_aslp_wkg(
        estimated_power_w=350.0,
        rider_mass_kg=70.0,
        avg_altitude_m=2250.0,
    )
    expected = (350.0 / 0.8707) / 70.0
    assert result == pytest.approx(expected, rel=1e-3)


def test_summarise_aslp_contains_expected_keys():
    result = summarise_aslp(
        estimated_power_w=360.0,
        rider_mass_kg=72.0,
        avg_altitude_m=1800.0,
    )

    expected_keys = {
        "estimated_power_w",
        "avg_altitude_m",
        "cp_remaining_fraction",
        "cp_remaining_fraction_low",
        "cp_remaining_fraction_high",
        "altitude_power_loss_percent",
        "sea_level_equivalent_power_w",
        "sea_level_equivalent_power_low_w",
        "sea_level_equivalent_power_high_w",
        "aslp_w_per_kg",
        "aslp_w_per_kg_low",
        "aslp_w_per_kg_high",
        "uncertainty_method",
    }

    assert expected_keys.issubset(result.keys())
    assert result["sea_level_equivalent_power_low_w"] <= result["sea_level_equivalent_power_w"]
    assert result["sea_level_equivalent_power_w"] <= result["sea_level_equivalent_power_high_w"]


def test_cp_fraction_range_contains_central_estimate():
    for altitude_m in (250.0, 1250.0, 2250.0, 3250.0, 4250.0):
        low, high = cp_remaining_fraction_range_at_altitude(altitude_m)
        central = cp_remaining_fraction_at_altitude(altitude_m)
        assert low <= central <= high


def test_negative_altitude_raises():
    with pytest.raises(ValueError):
        cp_remaining_fraction_at_altitude(-1.0)


def test_non_positive_power_raises():
    with pytest.raises(ValueError):
        sea_level_equivalent_power(0.0, 1000.0)


def test_non_positive_mass_raises():
    with pytest.raises(ValueError):
        estimate_aslp_wkg(300.0, 0.0, 1000.0)
