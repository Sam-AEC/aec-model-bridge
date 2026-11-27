"""Opt-in localized tool descriptions (MCP_REVIT_LOCALE, issue #205)."""
import json
import logging
import os
from pathlib import Path

import pytest

from revit_mcp_server import locale_descriptions as loc
from revit_mcp_server.registry_factory import build_registry
from revit_mcp_server.security.workspace import WorkspaceMonitor
from revit_mcp_server.tool_metadata import enrich_tool


@pytest.fixture(scope="module")
def tools(tmp_path_factory):
    saved = os.environ.get("APS_CLIENT_ID")
    os.environ["APS_CLIENT_ID"] = "locale-test-placeholder"
    try:
        reg, *_ = build_registry(WorkspaceMonitor([tmp_path_factory.mktemp("ws")]))
    finally:
        if saved is None:
            os.environ.pop("APS_CLIENT_ID", None)
        else:
            os.environ["APS_CLIENT_ID"] = saved
    return [(p.get_identity(), t) for p, t in reg.get_tools_with_providers()]


@pytest.fixture(autouse=True)
def _fresh_cache(monkeypatch):
    monkeypatch.delenv("MCP_REVIT_LOCALE", raising=False)
    loc.reset_cache()
    yield
    loc.reset_cache()


def _use_locales_dir(monkeypatch, tmp_path, **files):
    for code, data in files.items():
        (tmp_path / f"{code}.json").write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(loc, "LOCALES_DIR", tmp_path)
    loc.reset_cache()


def test_unset_and_english_return_the_english_text(monkeypatch):
    assert loc.localized_description("revit_health", "English text") == "English text"
    monkeypatch.setenv("MCP_REVIT_LOCALE", "en")
    assert loc.localized_description("revit_health", "English text") == "English text"
    monkeypatch.setenv("MCP_REVIT_LOCALE", "")
    assert loc.localized_description("revit_health", "English text") == "English text"


def test_default_descriptions_are_unchanged_for_every_tool(tools, monkeypatch):
    before = {t.name: enrich_tool(pid, t).model_dump_json() for pid, t in tools}
    monkeypatch.setenv("MCP_REVIT_LOCALE", "en")
    loc.reset_cache()
    assert {t.name: enrich_tool(pid, t).model_dump_json() for pid, t in tools} == before


def test_translated_text_used_and_missing_key_falls_back(monkeypatch, tmp_path):
    _use_locales_dir(monkeypatch, tmp_path, xx={"revit_health": "Gezondheid"})
    monkeypatch.setenv("MCP_REVIT_LOCALE", "xx")
    assert loc.localized_description("revit_health", "Health") == "Gezondheid"
    assert loc.localized_description("revit_other", "Other") == "Other"


def test_locale_code_is_case_and_region_tolerant(monkeypatch, tmp_path):
    _use_locales_dir(monkeypatch, tmp_path, xx={"revit_health": "Gezondheid"})
    for value in ("XX", " xx ", "xx-BE", "xx_BE"):
        monkeypatch.setenv("MCP_REVIT_LOCALE", value)
        loc.reset_cache()
        assert loc.localized_description("revit_health", "Health") == "Gezondheid"


def test_unknown_locale_falls_back_and_warns_once(monkeypatch, caplog):
    monkeypatch.setenv("MCP_REVIT_LOCALE", "zz")
    with caplog.at_level(logging.WARNING):
        assert loc.localized_description("revit_health", "Health") == "Health"
        assert loc.localized_description("revit_health", "Health") == "Health"
    warnings = [r for r in caplog.records if "MCP_REVIT_LOCALE" in r.getMessage()]
    assert len(warnings) == 1


@pytest.mark.parametrize("value", ["../x", "a/b", r"..\x", "x.json"])
def test_unsafe_locale_value_is_rejected(monkeypatch, value):
    monkeypatch.setenv("MCP_REVIT_LOCALE", value)
    assert loc.localized_description("revit_health", "Health") == "Health"


def test_malformed_catalog_falls_back(monkeypatch, tmp_path):
    (tmp_path / "xx.json").write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(loc, "LOCALES_DIR", tmp_path)
    monkeypatch.setenv("MCP_REVIT_LOCALE", "xx")
    assert loc.localized_description("revit_health", "Health") == "Health"


def test_sample_nl_locale_changes_only_descriptions(tools, monkeypatch):
    english = {t.name: enrich_tool(pid, t) for pid, t in tools}
    monkeypatch.setenv("MCP_REVIT_LOCALE", "nl")
    loc.reset_cache()
    dutch = {t.name: enrich_tool(pid, t) for pid, t in tools}
    assert english.keys() == dutch.keys()
    changed = 0
    for name, en in english.items():
        nl = dutch[name]
        assert nl.inputSchema == en.inputSchema, name
        assert nl.outputSchema == en.outputSchema, name
        assert nl.annotations == en.annotations, name
        assert nl.title == en.title, name
        if nl.description != en.description:
            changed += 1
    assert changed >= 5


def test_every_locale_key_names_an_existing_tool(tools):
    names = {t.name for _, t in tools}
    files = sorted(Path(loc.LOCALES_DIR).glob("*.json"))
    assert files, "expected at least the sample locale"
    for path in files:
        data = json.loads(path.read_text(encoding="utf-8"))
        assert isinstance(data, dict) and data, path.name
        meta = data.get("_meta")
        assert isinstance(meta, dict) and meta.get("sample") is True, f"{path.name}: mark sample locales in _meta"
        keys = {k for k in data if k != "_meta"}
        assert keys - names == set(), f"{path.name} names unknown tools"
        assert all(isinstance(data[k], str) and data[k].strip() for k in keys), path.name


def test_config_accepts_locale_setting(monkeypatch):
    from revit_mcp_server.config import Config
    assert Config().locale == "en"
    monkeypatch.setenv("MCP_REVIT_LOCALE", "nl")
    assert Config().locale == "nl"
