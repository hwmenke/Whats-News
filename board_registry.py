"""Board column + measure registry for Market Moves and ENGINE.

JSON is the machine source (`boards/registry.json`). YAML is the human twin
(`boards/registry.yaml`) emitted from the same dict. Neither file changes
locked formulas — it only names keys, formats, visibility, and heat scales.

Prefs (web Customize / future Flutter) store order + hidden ids only.
Locked identity columns stay visible.
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent
JSON_PATH = ROOT / "boards" / "registry.json"
YAML_PATH = ROOT / "boards" / "registry.yaml"

_CACHE: Optional[dict] = None


def load_registry(*, reload: bool = False) -> dict:
    global _CACHE
    if _CACHE is not None and not reload:
        return deepcopy(_CACHE)
    with JSON_PATH.open(encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict) or "boards" not in data or "measures" not in data:
        raise ValueError("board registry must have boards + measures")
    _CACHE = data
    return deepcopy(data)


def measure(measure_id: str) -> dict:
    reg = load_registry()
    found = (reg.get("measures") or {}).get(measure_id)
    if not found:
        raise KeyError(f"unknown measure: {measure_id}")
    return {"id": measure_id, **found}


def resolve_board_id(board_id: str) -> str:
    aliases = load_registry().get("aliases") or {}
    return aliases.get(board_id, board_id)


def board_def(board_id: str) -> dict:
    reg = load_registry()
    resolved = resolve_board_id(board_id)
    found = (reg.get("boards") or {}).get(resolved)
    if not found:
        raise KeyError(f"unknown board: {board_id}")
    return found


def board_ids() -> list[str]:
    reg = load_registry()
    ids = list((reg.get("boards") or {}).keys())
    for alias in (reg.get("aliases") or {}):
        if alias not in ids:
            ids.append(alias)
    return ids


def default_columns(board_id: str) -> list[dict]:
    """Ordered default columns with resolved measure metadata."""
    spec = board_def(board_id)
    measures = load_registry().get("measures") or {}
    out = []
    for col in spec.get("columns") or []:
        mid = col.get("measure")
        meas = measures.get(mid) or {}
        out.append({
            "id": col["id"],
            "label": col.get("label") or col["id"],
            "measure": mid,
            "visible": bool(col.get("visible", True)),
            "locked": bool(col.get("locked", False)),
            "title": col.get("title") or meas.get("formula"),
            "key": meas.get("key") or col["id"],
            "fallback_key": meas.get("fallback_key"),
            "formula": meas.get("formula"),
            "format": meas.get("format") or "text",
            "heat": meas.get("heat") or "none",
            "heat_scale": meas.get("heat_scale"),
            "bullet_from": meas.get("bullet_from"),
        })
    return out


def apply_layout(board_id: str, layout: Optional[dict] = None) -> list[dict]:
    """Apply user order + hidden set. Locked columns cannot be hidden."""
    cols = default_columns(board_id)
    by_id = {c["id"]: c for c in cols}
    layout = layout or {}
    order = [cid for cid in (layout.get("order") or []) if cid in by_id]
    hidden = set(layout.get("hidden") or [])
    seen = set(order)
    for col in cols:
        if col["id"] not in seen:
            order.append(col["id"])
    resolved = []
    for cid in order:
        col = dict(by_id[cid])
        shown = True if col["locked"] else (col["visible"] and cid not in hidden)
        col["visible"] = shown
        if shown:
            resolved.append(col)
    return resolved


def catalog() -> dict:
    """Public GET /api/boards/registry payload."""
    reg = load_registry()
    boards = {}
    aliases = reg.get("aliases") or {}
    for bid in board_ids():
        spec = board_def(bid)
        boards[bid] = {
            "id": bid,
            "label": spec.get("label") if bid not in aliases else (
                "ENGINE" if bid == "engine" else "MACRO" if bid == "macro" else spec.get("label")
            ),
            "api": spec.get("api"),
            "density": spec.get("density"),
            "alias_of": aliases.get(bid),
            "columns": default_columns(bid),
        }
    return {
        "version": reg.get("version"),
        "theme": reg.get("theme"),
        "note": reg.get("note"),
        "measures": reg.get("measures"),
        "aliases": aliases,
        "canonical_boards": ["market_moves", "engine", "setup", "macro"],
        "boards": boards,
        "yaml": str(YAML_PATH.relative_to(ROOT)),
        "json": str(JSON_PATH.relative_to(ROOT)),
        "flutter_path": (
            "GET /api/boards/registry (or columns[] on MM/ENGINE payloads). "
            "Persist order+hidden under SharedPreferences key whats-news-desk-prefs "
            "field boardColumns — same shape as web localStorage. "
            "Apply in ScansPage._movesSlivers / _setupEngineSlivers. "
            "Do not invent cells when a measure is hidden."
        ),
    }


def attach(payload: dict, board_id: str, layout: Optional[dict] = None) -> dict:
    """Stamp resolved columns onto an existing board payload. No math changes."""
    out = dict(payload or {})
    out["board_id"] = board_id
    out["columns"] = apply_layout(board_id, layout)
    return out


def _yaml_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    text = str(value)
    if text == "" or any(ch in text for ch in ":#{}[]&*!|>'\"%@`\n") or text[:1] in "-?":
        return json.dumps(text, ensure_ascii=False)
    return text


def _dump_yaml(value: Any, indent: int = 0) -> list[str]:
    pad = "  " * indent
    lines: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(item, (dict, list)):
                lines.append(f"{pad}{key}:")
                lines.extend(_dump_yaml(item, indent + 1))
            else:
                lines.append(f"{pad}{key}: {_yaml_scalar(item)}")
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                first = True
                for key, val in item.items():
                    prefix = "- " if first else "  "
                    first = False
                    if isinstance(val, (dict, list)):
                        lines.append(f"{pad}{prefix}{key}:")
                        lines.extend(_dump_yaml(val, indent + 1))
                    else:
                        lines.append(f"{pad}{prefix}{key}: {_yaml_scalar(val)}")
            elif isinstance(item, list):
                lines.append(f"{pad}-")
                lines.extend(_dump_yaml(item, indent + 1))
            else:
                lines.append(f"{pad}- {_yaml_scalar(item)}")
    else:
        lines.append(f"{pad}{_yaml_scalar(value)}")
    return lines


def render_yaml(reg: Optional[dict] = None) -> str:
    data = reg if reg is not None else load_registry()
    header = (
        "# Board column + measure registry (human twin of registry.json).\n"
        "# Ordered columns, visibility, measure id → formula/key, format, heat.\n"
        "# Generated from boards/registry.json — edit JSON, then rewrite YAML.\n"
    )
    return header + "\n".join(_dump_yaml(data)) + "\n"


def write_yaml() -> Path:
    YAML_PATH.parent.mkdir(parents=True, exist_ok=True)
    YAML_PATH.write_text(render_yaml(), encoding="utf-8")
    return YAML_PATH


if __name__ == "__main__":
    write_yaml()
    print(f"wrote {YAML_PATH}")
