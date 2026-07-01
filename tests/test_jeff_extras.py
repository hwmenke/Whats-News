"""Tests for the second Jeff-process pass: VARS, pocket pivots, screens,
management hints, excursion backfill, liquidity cap, Finviz parsing."""
import pytest
import numpy as np
import pandas as pd

import database as db


@pytest.fixture
def temp_db(monkeypatch, tmp_path):
    path = str(tmp_path / "test_finance.db")
    monkeypatch.setattr(db, "DB_PATH", path)
    db.init_db()
    return path


@pytest.fixture
def client(temp_db):
    import app as app_module
    return app_module.app.test_client()


# ── swing_core additions ───────────────────────────────────────────────────────

def test_swing_data_new_fields(monkeypatch, synth_ohlcv):
    import swing_core as sc
    monkeypatch.setattr(db, "get_ohlcv_df",
        lambda symbol, freq="daily", limit=260: synth_ohlcv)
    sd = sc.swing_data_for("AAPL")
    for key in ("pocket_pivot", "vol_dryup", "ma200_declining", "avg_dollar_vol"):
        assert key in sd, f"Missing key: {key}"
    assert isinstance(sd["pocket_pivot"], bool)
    assert isinstance(sd["vol_dryup"], bool)
    assert sd["avg_dollar_vol"] > 0


def test_pocket_pivot_detected():
    """Up day on volume above every down-day volume of the prior 10 sessions."""
    import swing_core as sc
    n = 60
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    close = pd.Series(np.linspace(100, 110, n), index=idx)
    # Make alternating small down days inside the window
    close.iloc[-11:-1:2] -= 0.5
    vol = pd.Series(np.full(n, 1_000_000.0), index=idx)
    vol.iloc[-1] = 5_000_000.0          # today: massive volume
    close.iloc[-1] = close.iloc[-2] + 2  # today: up day
    df = pd.DataFrame({"open": close, "high": close + 1,
                       "low": close - 1, "close": close, "volume": vol})
    sd = sc.swing_data_for("X", df=df)
    assert sd["pocket_pivot"] is True


def test_vars_score_positive_for_outperformer():
    import swing_core as sc
    idx   = pd.date_range("2024-01-01", periods=80, freq="B")
    sym   = pd.Series(np.linspace(100, 130, 80), index=idx)   # +30%
    bench = pd.Series(np.linspace(100, 105, 80), index=idx)   # +5%
    score = sc.vars_score(sym, bench, window=63)
    assert score > 0


def test_vars_score_insufficient_data():
    import swing_core as sc
    idx = pd.date_range("2024-01-01", periods=10, freq="B")
    s = pd.Series(np.linspace(100, 110, 10), index=idx)
    assert sc.vars_score(s, s, window=63) == 0.0


# ── Screens endpoint ───────────────────────────────────────────────────────────

def test_screens_unknown_name(client):
    resp = client.get("/api/screens/bogus")
    assert resp.status_code == 400


def test_screens_high_adr(client, monkeypatch, synth_ohlcv):
    db.add_symbol("AAPL", sector="Technology")
    monkeypatch.setattr(db, "get_ohlcv_df",
        lambda symbol, freq="daily", limit=260: synth_ohlcv)
    resp = client.get("/api/screens/high_adr")
    assert resp.status_code == 200
    d = resp.get_json()
    assert d["screen"] == "high_adr"
    assert len(d["rows"]) == 1
    assert d["rows"][0]["symbol"] == "AAPL"
    assert "adr_pct" in d["rows"][0]


def test_screens_recent_ipo_short_history(client, monkeypatch, synth_ohlcv):
    db.add_symbol("NEWCO")
    short_df = synth_ohlcv.tail(80)  # < 252 bars → counts as recent listing
    monkeypatch.setattr(db, "get_ohlcv_df",
        lambda symbol, freq="daily", limit=260: short_df)
    resp = client.get("/api/screens/recent_ipo")
    d = resp.get_json()
    assert len(d["rows"]) == 1
    assert d["rows"][0]["bars"] == 80


# ── Open-trade management hints ────────────────────────────────────────────────

def test_journal_manage_hints(client, monkeypatch, synth_ohlcv):
    from datetime import date, timedelta
    entry_date = (date.today() - timedelta(days=1)).isoformat()
    last_close = float(synth_ohlcv["close"].iloc[-1])
    # Stop placed so the trade is up > 2R at the synthetic last close
    entry = last_close - 4.0
    stop  = entry - 1.5
    db.add_journal_entry("AAPL", "long", entry_date, entry, stop_loss=stop)
    monkeypatch.setattr(db, "get_ohlcv_df",
        lambda symbol, freq="daily", limit=80: synth_ohlcv.tail(limit))

    resp = client.get("/api/journal/manage")
    assert resp.status_code == 200
    trades = resp.get_json()["open_trades"]
    assert len(trades) == 1
    t = trades[0]
    assert t["symbol"] == "AAPL"
    assert t["current_r"] is not None and t["current_r"] >= 2.0
    assert any("shave" in h["text"] for h in t["hints"])


def test_journal_manage_skips_closed(client):
    db.add_journal_entry("MSFT", "long", "2026-01-05", 100.0,
                         exit_date="2026-01-12", exit_price=105.0, stop_loss=97.0)
    resp = client.get("/api/journal/manage")
    assert resp.get_json()["open_trades"] == []


# ── MFE/MAE backfill ───────────────────────────────────────────────────────────

def test_backfill_excursions(client, monkeypatch):
    idx = pd.date_range("2026-01-05", periods=10, freq="B")
    close = pd.Series(np.full(10, 100.0), index=idx)
    high  = close.copy(); high.iloc[4] = 106.0   # peak +6 → MFE 3R with risk 2
    low   = close.copy(); low.iloc[2]  = 99.0    # dip  −1 → MAE −0.5R
    df = pd.DataFrame({"open": close, "high": high, "low": low,
                       "close": close, "volume": np.full(10, 1e6)})
    monkeypatch.setattr(db, "get_ohlcv_df",
        lambda symbol, freq="daily", limit=800: df)

    db.add_journal_entry("AAPL", "long", "2026-01-05", 100.0,
                         exit_date="2026-01-16", exit_price=104.0, stop_loss=98.0)

    resp = client.post("/api/journal/backfill-excursions")
    assert resp.status_code == 200
    assert resp.get_json()["updated"] == 1

    e = db.list_journal("AAPL")[0]
    assert e["mfe_r"] == pytest.approx(3.0, abs=0.01)
    assert e["mae_r"] == pytest.approx(-0.5, abs=0.01)

    # Second run is a no-op
    assert client.post("/api/journal/backfill-excursions").get_json()["updated"] == 0


# ── Overtrading guard ──────────────────────────────────────────────────────────

def test_journal_post_returns_today_count(client, monkeypatch):
    import market_regime as mr
    monkeypatch.setattr(mr, "compute_market_regime",
                        lambda sym="SPY": {"error": "no data"})
    import swing_core as sc
    monkeypatch.setattr(sc, "swing_data_for",
                        lambda sym: (_ for _ in ()).throw(ValueError("no data")))
    from datetime import date
    today = date.today().isoformat()
    for i in range(2):
        resp = client.post("/api/journal", json={
            "symbol": f"SYM{i}", "entry_price": 100, "entry_date": today})
    assert resp.get_json()["today_count"] == 2


# ── Liquidity cap ──────────────────────────────────────────────────────────────

def test_position_size_liquidity_fields(client, monkeypatch):
    import swing_core as sc
    monkeypatch.setattr(sc, "swing_data_for",
        lambda sym: {"avg_dollar_vol": 1_000_000.0})
    resp = client.post("/api/position-size", json={
        "account": 1_000_000, "risk_pct": 1.0,
        "entry": 100, "stop": 95, "symbol": "TINY",
    })
    d = resp.get_json()
    # 2000 shares × $100 = $200k = 20% of $1M ADV → warning
    assert d["adv_dollar"] == 1_000_000.0
    assert d["liq_pct_of_adv"] == pytest.approx(20.0, abs=0.1)
    assert d["liq_warning"] is True


def test_position_size_no_symbol_no_liq(client):
    resp = client.post("/api/position-size",
                       json={"entry": 100, "stop": 95})
    d = resp.get_json()
    assert d["adv_dollar"] is None
    assert d["liq_warning"] is False


# ── Finviz parsing (offline) ───────────────────────────────────────────────────

def test_finviz_filters_from_url():
    import finviz_import as fv
    f = fv.filters_from_url(
        "https://finviz.com/screener.ashx?v=111&f=cap_midover,ta_perf_4w30o&o=-volume")
    assert f["f"] == "cap_midover,ta_perf_4w30o"
    assert f["v"] == "111"
    assert f["o"] == "-volume"


def test_finviz_rejects_foreign_url():
    import finviz_import as fv
    with pytest.raises(ValueError):
        fv.filters_from_url("https://evil.example.com/screener.ashx?f=x")


def test_finviz_parse_export_csv():
    import finviz_import as fv
    csv_text = (
        '"No.","Ticker","Company","Sector","Industry","Country","Market Cap"\n'
        '1,"NVDA","NVIDIA Corp","Technology","Semiconductors","USA","3000B"\n'
        '2,"PLTR","Palantir","Technology","Software","USA","250B"\n'
        '3,"","bad row","","","",""\n'
    )
    rows = fv.parse_export_csv(csv_text)
    assert [r["symbol"] for r in rows] == ["NVDA", "PLTR"]
    assert rows[0]["sector"] == "Technology"


def test_finviz_parse_screener_html():
    import finviz_import as fv
    html = '''
      <table>
        <tr><td><a href="quote.ashx?t=NVDA&ty=c" class="tab-link">NVDA</a></td></tr>
        <tr><td><a href="/quote.ashx?t=BRK.B&p=d">BRK.B</a></td></tr>
        <tr><td><a href="quote.ashx?t=NVDA">NVDA dup</a></td></tr>
      </table>'''
    rows = fv.parse_screener_html(html)
    assert [r["symbol"] for r in rows] == ["NVDA", "BRK.B"]


def test_finviz_route_requires_input(client):
    resp = client.post("/api/finviz-import", json={})
    assert resp.status_code == 400


def test_finviz_route_rejects_bad_url(client):
    resp = client.post("/api/finviz-import",
                       json={"url": "https://example.com/x?f=y"})
    assert resp.status_code == 400


def test_finviz_fetch_with_fake_session(temp_db):
    """fetch_finviz against a stub session — no network."""
    import finviz_import as fv

    class FakeResp:
        status_code = 200
        text = ('"No.","Ticker","Company","Sector","Industry"\n'
                '1,"AAPL","Apple","Technology","Consumer Electronics"\n')
        def raise_for_status(self): pass

    class FakeSession:
        def __init__(self): self.calls = []
        def get(self, url, **kw):
            self.calls.append((url, kw.get("params", {})))
            return FakeResp()

    s = FakeSession()
    rows = fv.fetch_finviz(url="https://finviz.com/screener.ashx?v=111&f=cap_large",
                           auth="token123", _session=s)
    assert rows[0]["symbol"] == "AAPL"
    assert "elite.finviz.com" in s.calls[0][0]
    assert s.calls[0][1]["auth"] == "token123"
