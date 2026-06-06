import pytest
import pandas as pd

import app as app_module


@pytest.fixture
def client():
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client()


# ── Shape assertions ───────────────────────────────────────────────────────────

def _assert_error(resp, code, http_status):
    assert resp.status_code == http_status
    body = resp.get_json()
    assert body["code"] == code
    assert "message" in body


# ── NO_DATA ────────────────────────────────────────────────────────────────────

def test_ohlcv_nonexistent_symbol_returns_no_data(client, monkeypatch):
    import database as db
    monkeypatch.setattr(db, "get_ohlcv", lambda *a, **kw: [])
    resp = client.get("/api/ohlcv/NONEXISTENT")
    _assert_error(resp, "NO_DATA", 404)
    body = resp.get_json()
    assert "hint" in body


def test_stats_nonexistent_symbol_returns_no_data(client, monkeypatch):
    import database as db
    monkeypatch.setattr(db, "get_ohlcv_df", lambda *a, **kw: pd.DataFrame())
    resp = client.get("/api/stats/NONEXISTENT")
    _assert_error(resp, "NO_DATA", 404)


# ── VALIDATION ─────────────────────────────────────────────────────────────────

def test_ohlcv_invalid_limit_returns_validation(client):
    resp = client.get("/api/ohlcv/AAPL?limit=abc")
    _assert_error(resp, "VALIDATION", 400)


def test_ohlcv_zero_limit_returns_validation(client):
    resp = client.get("/api/ohlcv/AAPL?limit=0")
    _assert_error(resp, "VALIDATION", 400)


def test_ohlcv_invalid_freq_returns_validation(client):
    resp = client.get("/api/ohlcv/AAPL?freq=monthly")
    _assert_error(resp, "VALIDATION", 400)


def test_indicators_invalid_kama_returns_validation(client):
    resp = client.get("/api/indicators/AAPL?kama=abc")
    _assert_error(resp, "VALIDATION", 400)


# ── SYMBOL_REQUIRED ────────────────────────────────────────────────────────────

def test_add_symbol_empty_returns_symbol_required(client):
    resp = client.post("/api/symbols",
                       json={"symbol": ""},
                       content_type="application/json")
    _assert_error(resp, "SYMBOL_REQUIRED", 400)


# ── Internal errors do not leak stack traces ───────────────────────────────────

def test_fetch_internal_error_does_not_leak(client, monkeypatch):
    import data_fetcher as fetcher
    monkeypatch.setattr(fetcher, "fetch_and_store",
                        lambda sym: (_ for _ in ()).throw(KeyError("secret_key")))
    resp = client.post("/api/fetch/AAPL")
    body = resp.get_json()
    assert "secret_key" not in str(body)
    assert resp.status_code == 500
    assert body["code"] == "INTERNAL"
