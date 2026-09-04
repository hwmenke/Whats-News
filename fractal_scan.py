"""Fractal scan probe — Caspar's odds-edge / SPEC 25/27 only.

Looks for local `odds-edge/fractal.py` (and a few sibling / env paths).
Walks this repo (and git submodules) for any file named fractal.py.

Does NOT compute Hurst or D. Rows stay empty until that module is on disk
and its own scan API is wired — this file never estimates fractal dimension.
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# Paths we will wire the moment the file appears. Do not invent estimators.
CANDIDATE_PATHS = (
    ROOT / "odds-edge" / "fractal.py",
    ROOT / "odds_edge" / "fractal.py",
    ROOT / "vendor" / "odds-edge" / "fractal.py",
    ROOT / "third_party" / "odds-edge" / "fractal.py",
    ROOT / "bca" / "fractal.py",
    ROOT / "bca" / "odds-edge" / "fractal.py",
)

EXPECTED = "odds-edge/fractal.py (SPEC 25/27) from Caspar’s BCA / odds-edge pipeline"
PLACEHOLDER = (
    "Fractal: needs local odds-edge. "
    "Will not invent D / Hurst. Drop fractal.py on a probed path or set FRACTAL_PY."
)
COLUMNS = ["symbol", "d_65d", "d_130d", "move_65d", "move_130d", "read"]
_SKIP_DIRS = {
    ".git",
    "__pycache__",
    ".venv",
    "venv",
    "node_modules",
    ".dart_tool",
    "build",
    ".pytest_cache",
}


def _probed() -> list[str]:
    out = []
    env = _env_path()
    if env is not None:
        out.append(f"env:{env}")
    for path in CANDIDATE_PATHS:
        try:
            out.append(str(path.relative_to(ROOT)))
        except ValueError:
            out.append(str(path))
    out.append("walk:**/fractal.py")
    return out


def _env_path() -> Path | None:
    raw = (os.environ.get("FRACTAL_PY") or os.environ.get("ODDS_EDGE_FRACTAL") or "").strip()
    if not raw:
        return None
    return Path(raw).expanduser()


def _is_real_module(path: Path) -> bool:
    try:
        return path.is_file() and path.stat().st_size > 0 and path.name == "fractal.py"
    except OSError:
        return False


def _rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path.resolve())


def _walk_tree() -> list[Path]:
    found: list[Path] = []
    try:
        entries = os.walk(ROOT, followlinks=True)
    except OSError:
        return found
    for dirpath, dirnames, filenames in entries:
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        if "fractal.py" in filenames:
            cand = Path(dirpath) / "fractal.py"
            if _is_real_module(cand):
                found.append(cand)
    return found


def find_source() -> str | None:
    """Return repo-relative (or absolute) path if Caspar's fractal.py is on disk."""
    env = _env_path()
    if env is not None and _is_real_module(env):
        return _rel(env)
    for path in CANDIDATE_PATHS:
        if _is_real_module(path):
            return _rel(path)
    walked = _walk_tree()
    if walked:
        return _rel(walked[0])
    return None


def status() -> dict:
    source = find_source()
    if source:
        return {
            "available": True,
            "source": source,
            "expected": EXPECTED,
            "reason": (
                f"Found {source}. Adapter pending — still no invented D. "
                "Will call that module's scan API once Caspar confirms the entry point."
            ),
            "probed": _probed(),
        }
    return {
        "available": False,
        "source": None,
        "expected": EXPECTED,
        "reason": PLACEHOLDER,
        "probed": _probed(),
    }


def scan() -> dict:
    """GET /api/fractal/scan — rows only from odds-edge, never estimated here."""
    meta = status()
    return {
        **meta,
        "columns": COLUMNS,
        "rows": [],
        "message": meta.get("reason") or PLACEHOLDER,
    }
