from datetime import datetime, timezone
from unittest.mock import Mock

import pytest
import gammaflip_client as client


def test_daily_budget_reserves_and_resets_by_utc_day(monkeypatch):
    monkeypatch.setattr(client, "_budget_day", None)
    monkeypatch.setattr(client, "_budget_used", 0)
    day = datetime(2026, 10, 31, tzinfo=timezone.utc)
    assert client.reserve_daily_requests(5, budget=10, now=day)
    assert client.reserve_daily_requests(5, budget=10, now=day)
    assert not client.reserve_daily_requests(1, budget=10, now=day)
    next_day = datetime(2026, 11, 1, tzinfo=timezone.utc)
    assert client.reserve_daily_requests(5, budget=10, now=next_day)


def test_fetch_levels_normalizes_real_gex(monkeypatch):
    future = datetime.now(timezone.utc).isoformat()
    response = Mock()
    response.json.return_value = {
        "data": {"spot": 100000, "flip": 98000, "regime": "positive",
                 "net_gex": 123456, "abs_gex": 234567, "p1_strike": 105000},
        "meta": {"market": "crypto", "as_of": future, "exchange_resolved": "combined"},
    }
    response.raise_for_status.return_value = None
    monkeypatch.setattr(client.requests, "get", lambda *args, **kwargs: response)
    result = client.fetch_levels("BTC", "gex_sk_test")
    assert result["symbol"] == "BTC"
    assert result["net_gex"] == 123456.0
    assert result["regime"] == "positive"
    assert result["exchange"] == "combined"


def test_fetch_levels_rejects_unsupported_coin():
    with pytest.raises(ValueError, match="unsupported_coin"):
        client.fetch_levels("DOGE", "gex_sk_test")


def test_fetch_levels_rejects_stale_data(monkeypatch):
    response = Mock()
    response.json.return_value = {
        "data": {"spot": 1}, "meta": {"market": "crypto", "as_of": "2020-01-01T00:00:00Z"}
    }
    response.raise_for_status.return_value = None
    monkeypatch.setattr(client.requests, "get", lambda *args, **kwargs: response)
    with pytest.raises(ValueError, match="stale_gamma_data"):
        client.fetch_levels("BTC", "gex_sk_test")
