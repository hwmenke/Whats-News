"""
settings_store.py — Persist account-level settings (equity, default risk %).

Single-row table `journal_settings` (id = 1). Used by the journal sizing form
so equity and default risk survive restarts.
"""

from datetime import datetime, timezone

import database as db

DEFAULTS = {"equity": 100000.0, "risk_pct": 1.0}


def get_settings():
    conn = db.get_connection()
    row = conn.execute(
        "SELECT equity, risk_pct FROM journal_settings WHERE id = 1"
    ).fetchone()
    conn.close()
    if not row:
        return dict(DEFAULTS)
    return {"equity": float(row["equity"]), "risk_pct": float(row["risk_pct"])}


def set_settings(equity=None, risk_pct=None):
    cur = get_settings()
    equity   = float(equity)   if equity   is not None else cur["equity"]
    risk_pct = float(risk_pct) if risk_pct is not None else cur["risk_pct"]
    if equity <= 0:
        raise ValueError("equity must be positive")
    if risk_pct <= 0:
        raise ValueError("risk_pct must be positive")

    now  = datetime.now(timezone.utc).isoformat()
    conn = db.get_connection()
    conn.execute(
        """
        INSERT INTO journal_settings (id, equity, risk_pct, updated_at)
        VALUES (1, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            equity     = excluded.equity,
            risk_pct   = excluded.risk_pct,
            updated_at = excluded.updated_at
        """,
        (equity, risk_pct, now),
    )
    conn.commit()
    conn.close()
    return {"equity": equity, "risk_pct": risk_pct}
