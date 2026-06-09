"""api package — feature routes split into domain blueprints.

Route URLs are unchanged from the old monolithic features_api.py; only the
file layout and error responses (now ApiError taxonomy) differ.
"""
from api.symbols_meta import symbols_bp
from api.alerts import alerts_bp
from api.market import market_bp
from api.trade import trade_bp
from api.news_routes import news_bp
from api.swing import swing_bp

ALL_BLUEPRINTS = [symbols_bp, alerts_bp, market_bp, trade_bp, news_bp, swing_bp]
