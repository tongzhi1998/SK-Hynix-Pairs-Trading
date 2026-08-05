import pytest

from backend.analytics import funding_carry, pair_metrics, rolling_zscores


def test_pair_metrics_apply_ten_to_one_ratio():
    result = pair_metrics(korean_mark=1_500, adr_mark=160)
    assert result["adr_equivalent"] == 1_600
    assert result["spread"] == 100
    assert result["premium_pct"] == pytest.approx(6.6666667)


def test_funding_carry_respects_position_direction():
    result = funding_carry(korean_rate=0.0001, adr_rate=0.0003)
    assert result["long_korean_short_adr"] == pytest.approx(0.0002)
    assert result["short_korean_long_adr"] == pytest.approx(-0.0002)


def test_rolling_zscore_waits_for_full_window():
    values = [1.0, 2.0, 3.0, 4.0]
    result = rolling_zscores(values, window=3)
    assert result[:2] == [None, None]
    assert result[2] == pytest.approx(1.224744871)
    assert result[3] == pytest.approx(1.224744871)


def test_pair_metrics_reject_non_positive_prices():
    with pytest.raises(ValueError):
        pair_metrics(0, 100)
