import pytest

from backend.yahoo import YahooError, parse_index_chart


def test_parse_index_chart_returns_price_and_previous_close_change():
    result = parse_index_chart(
        {
            "chart": {
                "error": None,
                "result": [
                    {
                        "meta": {
                            "currency": "KRW",
                            "regularMarketPrice": 1_020,
                            "chartPreviousClose": 1_000,
                            "regularMarketTime": 1_785_834_330,
                            "exchangeTimezoneName": "Asia/Seoul",
                            "currentTradingPeriod": {
                                "regular": {
                                    "start": 1_785_888_000,
                                    "end": 1_785_909_600,
                                }
                            },
                        },
                        "timestamp": [1_785_834_330],
                        "indicators": {"quote": [{"close": [1_020]}]},
                    }
                ],
            }
        }
    )

    assert result["mark"] == 1_020
    assert result["change_pct"] == pytest.approx(2.0)
    assert result["ts"] == 1_785_834_330_000
    assert result["currency"] == "KRW"
    assert result["session"] == {
        "regular_start": 1_785_888_000_000,
        "regular_end": 1_785_909_600_000,
        "next_regular_start": 1_785_974_400_000,
        "timezone": "Asia/Seoul",
    }


def test_parse_index_chart_rejects_empty_payload():
    with pytest.raises(YahooError):
        parse_index_chart({"chart": {"result": None, "error": None}})
