"""Optional localized tool descriptions (MCP_REVIT_LOCALE).

English is the default and the fallback. A catalog is ``locales/<code>.json``: tool name to
description. Only the description text is replaced; tool names, titles, schemas and safety
annotations never change. A tool missing from the catalog keeps its English text, and so does
every tool when the locale is unset, ``en`` or unknown (the unknown case logs one warning).
"""
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path

LOCALES_DIR = Path(__file__).parent / "locales"
_CODE = re.compile(r"^[a-z]{2,3}$")
_log = logging.getLogger(__name__)
_cache: dict[str, dict[str, str]] = {}
_warned: set[str] = set()


def reset_cache() -> None:
    _cache.clear()
    _warned.clear()


def _warn_once(code: str, why: str) -> None:
    if code not in _warned:
        _warned.add(code)
        _log.warning("MCP_REVIT_LOCALE=%r %s; using English tool descriptions.", code, why)


def _normalize(value: str | None) -> str:
    text = (value or "").strip().lower().replace("_", "-")
    return text.split("-", 1)[0]


def _catalog(code: str) -> dict[str, str]:
    if code in _cache:
        return _cache[code]
    catalog: dict[str, str] = {}
    if not _CODE.match(code):
        _warn_once(code, "is not a language code")
    else:
        path = LOCALES_DIR / f"{code}.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            _warn_once(code, "has no description catalog")
        except (OSError, ValueError):
            _warn_once(code, "has an unreadable description catalog")
        else:
            if isinstance(data, dict):
                catalog = {k: v for k, v in data.items() if k != "_meta" and isinstance(v, str) and v.strip()}
    _cache[code] = catalog
    return catalog


def localized_description(tool_name: str, english: str) -> str:
    code = _normalize(os.environ.get("MCP_REVIT_LOCALE"))
    if code in ("", "en"):
        return english
    return _catalog(code).get(tool_name, english)
