"""
odds_math.py - Odds conversions, de-vigging, EV and Kelly staking.

All probabilities are floats in (0, 1). American odds are ints like -110 / +145.
"""

import math


# -- Conversions ------------------------------------------------------------------

def american_to_decimal(odds):
    """-110 -> 1.909..., +145 -> 2.45"""
    odds = float(odds)
    if odds > 0:
        return 1.0 + odds / 100.0
    return 1.0 + 100.0 / abs(odds)


def decimal_to_american(dec):
    dec = float(dec)
    if dec >= 2.0:
        return int(round((dec - 1.0) * 100))
    return int(round(-100.0 / (dec - 1.0)))


def american_to_prob(odds):
    """Implied probability INCLUDING the book's vig."""
    odds = float(odds)
    if odds > 0:
        return 100.0 / (odds + 100.0)
    return abs(odds) / (abs(odds) + 100.0)


def prob_to_american(p):
    p = min(max(float(p), 1e-6), 1 - 1e-6)
    if p >= 0.5:
        return int(round(-100.0 * p / (1.0 - p)))
    return int(round(100.0 * (1.0 - p) / p))


# -- De-vigging --------------------------------------------------------------------

def devig_multiplicative(p1, p2):
    """Strip vig from a two-way market by normalising. Returns (q1, q2)."""
    total = p1 + p2
    if total <= 0:
        return 0.5, 0.5
    return p1 / total, p2 / total


def devig_power(p1, p2, tol=1e-9, max_iter=100):
    """
    Power-method de-vig: find k such that p1^k + p2^k = 1.
    Assigns more of the vig to the longshot, correcting the
    favourite-longshot bias books price into their lines. Returns (q1, q2).
    """
    p1 = min(max(p1, 1e-9), 1 - 1e-9)
    p2 = min(max(p2, 1e-9), 1 - 1e-9)
    lo, hi = 0.5, 10.0
    for _ in range(max_iter):
        k = (lo + hi) / 2.0
        s = p1 ** k + p2 ** k
        if abs(s - 1.0) < tol:
            break
        if s > 1.0:
            lo = k
        else:
            hi = k
    q1, q2 = p1 ** k, p2 ** k
    total = q1 + q2
    return q1 / total, q2 / total


def vig_pct(p1, p2):
    """Overround as a percentage, e.g. -110/-110 -> ~4.76%."""
    return (p1 + p2 - 1.0) * 100.0


# -- Value ------------------------------------------------------------------------

def expected_value(p_win, odds):
    """EV per $1 staked at American odds, given true win probability."""
    dec = american_to_decimal(odds)
    return p_win * (dec - 1.0) - (1.0 - p_win)


def kelly_fraction(p_win, odds):
    """
    Full-Kelly fraction of bankroll for a bet at American odds with true
    win probability p_win. Negative edge returns 0.
    """
    b = american_to_decimal(odds) - 1.0
    if b <= 0:
        return 0.0
    f = (p_win * b - (1.0 - p_win)) / b
    return max(0.0, f)


def kelly_stake(bankroll, p_win, odds, fraction=0.25, cap=0.03):
    """
    Fractional-Kelly stake. Walters never bet more than a low single-digit
    percentage of bankroll on one game, so the stake is hard-capped at
    `cap` (default 3%) of bankroll regardless of how juicy the edge looks.
    """
    f = kelly_fraction(p_win, odds) * fraction
    f = min(f, cap)
    return round(bankroll * f, 2)
