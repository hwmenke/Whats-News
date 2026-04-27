"""
errors.py — Structured API error taxonomy for the Financial Dashboard.

Usage in app.py:
    import errors
    errors.register(app)
    ...
    raise errors.ApiError("NO_DATA", "No data for AAPL", hint="Fetch the symbol first", http=404)
"""

import logging
from typing import Optional
from flask import jsonify

log = logging.getLogger(__name__)


class ApiError(Exception):
    def __init__(self, code: str, message: str,
                 hint: Optional[str] = None, http: int = 400):
        self.code    = code
        self.message = message
        self.hint    = hint
        self.http    = http
        super().__init__(message)

    def to_response(self):
        body = {"code": self.code, "message": self.message}
        if self.hint:
            body["hint"] = self.hint
        return jsonify(body), self.http


def register(app):
    """Attach global error handlers to the Flask app."""

    @app.errorhandler(ApiError)
    def _handle_api_error(err):
        return err.to_response()

    @app.errorhandler(Exception)
    def _handle_unexpected(err):
        log.exception("Unhandled exception")
        return jsonify({
            "code":    "INTERNAL",
            "message": "An internal error occurred.",
        }), 500


# ── Convenience raisers ─────────────────────────────────────────────────────────

def no_data(symbol: str) -> "ApiError":
    return ApiError(
        "NO_DATA",
        f"No data for {symbol}.",
        hint="Fetch the symbol first via POST /api/fetch/<symbol>.",
        http=404,
    )

def validation(message: str) -> "ApiError":
    return ApiError("VALIDATION", message, http=400)

def symbol_required() -> "ApiError":
    return ApiError("SYMBOL_REQUIRED", "symbol is required.", http=400)

def invalid_symbol(symbol: str) -> "ApiError":
    return ApiError("INVALID_SYMBOL", f"Invalid symbol format: {symbol}.", http=400)

def fetch_failed(symbol: str, detail: str = "") -> "ApiError":
    msg = f"No data returned for {symbol}."
    return ApiError("FETCH_FAILED", msg, hint=detail or None, http=502)

def upstream_error(symbol: str, detail: str = "") -> "ApiError":
    return ApiError("UPSTREAM_ERROR", f"Data source error for {symbol}.",
                    hint=detail[:200] if detail else None, http=502)

def computation_failed(detail: str = "") -> "ApiError":
    return ApiError("COMPUTATION_FAILED", "Computation failed.",
                    hint=detail[:200] if detail else None, http=500)
