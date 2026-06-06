"""
module_registry.py — Central registry of dashboard modules.

Every feature tab is declared here as a Module. The app registers a module's
Flask Blueprint only when the module is enabled, and the frontend builds its nav
from the manifest, so features can be toggled on/off from the "⚙ Modules" tab.

Enable/disable state is persisted in the `module_state` table; core modules are
always on. A module without a `blueprint` keeps its routes in app.py (the base
feature set) and is gated on the frontend only.
"""

from dataclasses import dataclass, field
from typing import List

import database as db


@dataclass
class Module:
    id: str
    label: str
    icon: str
    group: str
    default_enabled: bool = True
    blueprint: str = ""              # "import_path:attr" of a Flask Blueprint
    core: bool = False               # core modules can't be disabled
    requires: List[str] = field(default_factory=list)
    notes: str = ""


# Order here defines nav order. Grouped for the ⚙ Modules settings UI.
MODULES: List[Module] = [
    # ── Core (base FinDash) ──────────────────────────────────────────────────
    Module("charts",       "Charts",          "📈", "Core",     core=True),
    Module("stats",        "Statistics",      "📊", "Core"),
    Module("knn",          "KNN Lookalike",   "🤖", "Core"),
    Module("backtest",     "Backtest",        "⚙️", "Core"),
    Module("trend",        "Adaptive Trend",  "🎯", "Core"),
    Module("scanner",      "Scanner",         "📡", "Core"),
    Module("data-manager", "Data Manager",    "🗄️", "Core",     core=True),
    # ── Process (Qullamaggie/Stockbee) ───────────────────────────────────────
    Module("journal",      "Trade Journal",   "📒", "Process"),
    Module("momentum",     "Momentum Scan",   "🚀", "Process"),
    Module("regime",       "Regime & Breadth","🌐", "Process"),
    Module("performance",  "Performance",     "📈", "Process",
           blueprint="mod_cockpit:performance_bp",
           notes="Equity curve, expectancy by setup, R-distribution, drawdown"),
    Module("modelbook",    "Model Book",      "📚", "Process",
           notes="Screenshot gallery of past trades, filterable by setup/result"),
    # ── Jeff Sun swing framework ──────────────────────────────────────────────
    Module("swing",        "Swing Suite",     "🏄", "Swing",
           blueprint="mod_blueprints:swing_bp",
           notes="Opportunity Score, setup grade, watchlist scan, breadth, sizing"),
    # ── Analytics (ported from jeff, pure-Python) ─────────────────────────────
    Module("strategy",     "Strategy Tester", "🧪", "Analytics",
           blueprint="mod_blueprints:strategy_bp"),
    Module("knn-forecast", "KNN Forecast",    "🔮", "Analytics",
           blueprint="mod_blueprints:knnf_bp"),
    Module("momentum-rank","Momentum Ranker", "🏅", "Analytics",
           blueprint="mod_blueprints:momranker_bp"),
    Module("market-dash",  "Market Dashboard","🗺️", "Analytics",
           blueprint="mod_blueprints:market_bp"),
    Module("seasonality",  "Seasonality",     "📅", "Analytics",
           blueprint="mod_blueprints:seasonality_bp"),
    Module("factor-model", "Factor Model",    "🧮", "Analytics",
           blueprint="mod_blueprints:factor_bp"),
    Module("regression",   "Macro Regression","📐", "Analytics",
           blueprint="mod_blueprints:regression_bp"),
    Module("swirligram",   "Swirligram",      "🌀", "Analytics",
           blueprint="mod_blueprints:swirligram_bp"),
    Module("news",         "News",            "📰", "Analytics",
           blueprint="mod_blueprints:news_bp"),
    # ── Market rotation / discovery ───────────────────────────────────────────
    Module("rrg",          "RRG Rotation",    "🔄", "Market",
           blueprint="mod_blueprints:rrg_bp",
           notes="Relative-rotation graph vs SPY (needs weekly data)"),
    Module("sector",       "Sector Heatmap",  "🔥", "Market",
           blueprint="mod_blueprints:sector_bp"),
    Module("social",       "Social Trends",   "📡", "Market",
           blueprint="mod_blueprints:social_bp",
           requires=["pytrends (optional)"],
           notes="Theme radar + pure-play stock mapper"),
    Module("alerts",       "Alerts",          "🔔", "Market",
           blueprint="mod_blueprints:alerts_bp",
           notes="Browser notifications when a watchlist name triggers an A/A+ setup"),
    Module("earnings",     "Earnings",        "📆", "Market",
           blueprint="mod_blueprints:earnings_bp", default_enabled=False,
           requires=["network (yfinance)"],
           notes="Next earnings date lookup; off by default (network)"),
]


def _state_map():
    """id -> enabled(bool) from the DB (only rows that were explicitly set)."""
    state = {}
    try:
        conn = db.get_connection()
        for r in conn.execute("SELECT id, enabled FROM module_state").fetchall():
            state[r["id"]] = bool(r["enabled"])
        conn.close()
    except Exception:
        pass
    return state


def enabled_map():
    """id -> enabled(bool), merging declared defaults with stored overrides."""
    stored = _state_map()
    return {m.id: (True if m.core else stored.get(m.id, m.default_enabled))
            for m in MODULES}


def set_enabled(updates: dict):
    """Persist {id: bool} overrides. Core modules are ignored (always on)."""
    cores = {m.id for m in MODULES if m.core}
    conn = db.get_connection()
    for mid, en in (updates or {}).items():
        if mid in cores:
            continue
        conn.execute(
            "INSERT INTO module_state (id, enabled) VALUES (?, ?) "
            "ON CONFLICT(id) DO UPDATE SET enabled = excluded.enabled",
            (mid, 1 if en else 0),
        )
    conn.commit()
    conn.close()


def manifest():
    em = enabled_map()
    return [{
        "id": m.id, "label": m.label, "icon": m.icon, "group": m.group,
        "core": m.core, "enabled": em[m.id], "requires": m.requires,
        "notes": m.notes,
    } for m in MODULES]


def enabled_blueprints():
    """Modules that have a Blueprint and are currently enabled."""
    em = enabled_map()
    return [m for m in MODULES if m.blueprint and em.get(m.id)]
