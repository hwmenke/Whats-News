"""Tests for the Jeff-process API surface: market diary, trade plans,
watchlist tiers, risk pedal, and extended r-analytics."""
import pytest

import database as db


@pytest.fixture
def temp_db(monkeypatch, tmp_path):
    """Point database.py at a fresh throw-away SQLite file."""
    path = str(tmp_path / "test_finance.db")
    monkeypatch.setattr(db, "DB_PATH", path)
    db.init_db()
    return path


@pytest.fixture
def client(temp_db):
    import app as app_module
    return app_module.app.test_client()


# ── Watchlist tiers ────────────────────────────────────────────────────────────

def test_valid_tiers_include_back_watchlist():
    assert "back_watchlist" in db.VALID_TIERS


def test_set_tier_back_watchlist(temp_db):
    db.add_symbol("AAPL")
    assert db.set_symbol_tier("AAPL", "back_watchlist") is True
    assert db.get_symbol_tier("AAPL") == "back_watchlist"


def test_set_tier_rejects_invalid(temp_db):
    db.add_symbol("AAPL")
    assert db.set_symbol_tier("AAPL", "bogus") is False


def test_list_symbols_by_tier_has_all_buckets(temp_db):
    result = db.list_symbols_by_tier()
    for tier in ("back_watchlist", "watchlist", "stalk", "focus", "active"):
        assert tier in result


def test_tier_route_accepts_back_watchlist(client):
    db.add_symbol("MSFT")
    resp = client.put("/api/symbols/MSFT/tier", json={"tier": "back_watchlist"})
    assert resp.status_code == 200
    assert resp.get_json()["tier"] == "back_watchlist"


# ── Market diary ───────────────────────────────────────────────────────────────

def test_diary_upsert_and_list(temp_db):
    db.upsert_diary_entry("2026-06-01", regime_state="BULL", risk_pedal="green",
                          breadth_pct20=72.0, notes="strong tape")
    entries = db.list_diary()
    assert len(entries) == 1
    assert entries[0]["regime_state"] == "BULL"
    assert entries[0]["notes"] == "strong tape"


def test_diary_upsert_is_idempotent_per_date(temp_db):
    db.upsert_diary_entry("2026-06-01", notes="first")
    db.upsert_diary_entry("2026-06-01", notes="second")
    entries = db.list_diary()
    assert len(entries) == 1
    assert entries[0]["notes"] == "second"


def test_diary_delete(temp_db):
    db.upsert_diary_entry("2026-06-01", notes="x")
    db.delete_diary_entry("2026-06-01")
    assert db.list_diary() == []


def test_diary_get_route(client):
    db.upsert_diary_entry("2026-06-02", regime_state="CHOP", notes="mixed")
    resp = client.get("/api/diary")
    assert resp.status_code == 200
    data = resp.get_json()
    assert isinstance(data, list)
    assert data[0]["date"] == "2026-06-02"


def test_diary_limit_validation(client):
    resp = client.get("/api/diary?limit=0")
    assert resp.status_code == 400


# ── Trade plans ────────────────────────────────────────────────────────────────

def test_trade_plan_upsert_and_list(temp_db):
    db.upsert_trade_plan("NVDA", trigger_price=130.0, stop_price=124.0,
                         trigger_type="range breakout")
    plans = db.list_trade_plans()
    assert len(plans) == 1
    assert plans[0]["symbol"] == "NVDA"
    assert plans[0]["trigger_price"] == 130.0


def test_trade_plan_upsert_replaces(temp_db):
    db.upsert_trade_plan("NVDA", trigger_price=130.0, stop_price=124.0)
    db.upsert_trade_plan("NVDA", trigger_price=135.0, stop_price=128.0)
    plans = db.list_trade_plans()
    assert len(plans) == 1
    assert plans[0]["trigger_price"] == 135.0


def test_trade_plan_delete(temp_db):
    db.upsert_trade_plan("NVDA", trigger_price=130.0, stop_price=124.0)
    db.delete_trade_plan("NVDA")
    assert db.list_trade_plans() == []


def test_trade_plan_route_rejects_stop_above_trigger(client):
    resp = client.post("/api/trade-plans",
                       json={"symbol": "NVDA", "trigger_price": 100, "stop_price": 105})
    assert resp.status_code == 400


def test_trade_plan_route_requires_symbol(client):
    resp = client.post("/api/trade-plans", json={"trigger_price": 100})
    assert resp.status_code == 400


def test_trade_plan_route_saves(client):
    resp = client.post("/api/trade-plans",
                       json={"symbol": "nvda", "trigger_price": 130, "stop_price": 124})
    assert resp.status_code == 201
    assert resp.get_json()["symbol"] == "NVDA"


# ── Journal context + r-analytics extensions ──────────────────────────────────

def test_journal_stores_context_and_excursion(temp_db):
    jid = db.add_journal_entry(
        "AAPL", "long", "2026-05-01", 100.0, qty=10,
        exit_date="2026-05-08", exit_price=109.0, stop_loss=97.0,
        setup="breakout", market_regime="BULL",
        entry_rvol=1.8, lod_dist_atr=0.4, mae_r=-0.3, mfe_r=3.2,
    )
    rows = db.list_journal("AAPL")
    assert rows[0]["id"] == jid
    assert rows[0]["market_regime"] == "BULL"
    assert rows[0]["entry_rvol"] == 1.8
    assert rows[0]["mfe_r"] == 3.2


def test_r_analytics_has_new_blocks(client, monkeypatch):
    # Two closed trades: one rule-compliant winner, one violating loser
    db.add_journal_entry("AAPL", "long", "2026-05-01", 100.0,
                         exit_date="2026-05-08", exit_price=109.0, stop_loss=97.0,
                         setup="breakout", market_regime="BULL",
                         entry_rvol=1.8, lod_dist_atr=0.4)
    db.add_journal_entry("TSLA", "long", "2026-05-02", 50.0,
                         exit_date="2026-05-03", exit_price=48.0, stop_loss=48.5,
                         setup="chase", market_regime="CHOP",
                         entry_rvol=0.7, lod_dist_atr=0.9)

    resp = client.get("/api/r-analytics")
    assert resp.status_code == 200
    d = resp.get_json()
    assert d["count"] == 2
    for key in ("setup_stats", "compliance", "last100", "excursion"):
        assert key in d, f"Missing key: {key}"

    assert d["last100"]["count"] == 2
    assert "breakout" in d["setup_stats"]
    lod = d["compliance"]["lod"]
    assert lod["pass"]["count"] == 1
    assert lod["fail"]["count"] == 1
    # The compliant trade won (+3R), the violation lost
    assert lod["pass"]["avg_r"] > 0 > lod["fail"]["avg_r"]


def test_journal_post_route_persists_review_fields(client, monkeypatch):
    # Avoid slow regime/swing-data auto-capture in this test
    import market_regime as mr
    monkeypatch.setattr(mr, "compute_market_regime",
                        lambda sym="SPY": {"error": "no data"})
    import swing_core as sc
    monkeypatch.setattr(sc, "swing_data_for",
                        lambda sym: (_ for _ in ()).throw(ValueError("no data")))

    resp = client.post("/api/journal", json={
        "symbol": "AAPL", "entry_price": 100, "stop_loss": 97,
        "exit_price": 103, "review_grade": "A",
        "review_mistakes": "none", "review_lesson": "wait for RVOL",
    })
    assert resp.status_code == 201
    rows = db.list_journal("AAPL")
    assert rows[0]["review_grade"] == "A"
    assert rows[0]["review_lesson"] == "wait for RVOL"


# ── Quick-stats sparkline ──────────────────────────────────────────────────────

def test_quick_stats_includes_spark(client, monkeypatch, synth_ohlcv):
    db.add_symbol("AAPL")
    monkeypatch.setattr(db, "get_ohlcv_df",
        lambda symbol, freq="daily", limit=60: synth_ohlcv.tail(limit))

    resp = client.get("/api/symbols/quick-stats")
    assert resp.status_code == 200
    row = resp.get_json()[0]
    assert row["symbol"] == "AAPL"
    assert len(row["spark"]) == 20
    assert row["spark"][-1] == pytest.approx(row["price"], abs=0.01)
