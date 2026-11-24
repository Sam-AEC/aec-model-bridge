"""Opt-in personal-data redaction of tool responses (issue #179)."""
from __future__ import annotations

import pytest

from revit_mcp_server import mcp_server
from revit_mcp_server.security.response_redaction import redact_response, redaction_level

ENV = "MCP_REVIT_REDACT_RESPONSES"
DATA = {
    "author": "Jane Doe",
    "note": "mail jane.doe@example.com, edited by alice01",
    "items": [{"owner": "Bob"}],
    "count": 3,
}


@pytest.fixture(autouse=True)
def _user(monkeypatch):
    monkeypatch.setenv("USER", "alice01")
    monkeypatch.delenv(ENV, raising=False)


def test_default_is_off_and_changes_nothing():
    assert redaction_level() == "off"
    assert redact_response(DATA) == DATA


def test_basic_masks_email_and_local_user_only(monkeypatch):
    monkeypatch.setenv(ENV, "basic")
    out = redact_response(DATA)
    assert "example.com" not in out["note"] and "alice01" not in out["note"]
    assert out["author"] == "Jane Doe" and out["items"][0]["owner"] == "Bob"
    assert out["count"] == 3


def test_strict_masks_person_fields(monkeypatch):
    monkeypatch.setenv(ENV, " STRICT ")
    out = redact_response(DATA)
    assert out["author"] == "<redacted-user>"
    assert out["items"][0]["owner"] == "<redacted-user>"
    assert out["count"] == 3


def test_invalid_value_fails_closed_to_strict(monkeypatch):
    monkeypatch.setenv(ENV, "banana")
    assert redaction_level() == "strict"
    assert redact_response(DATA)["author"] == "<redacted-user>"


def test_mcp_responses_use_it(monkeypatch):
    monkeypatch.setenv(ENV, "basic")
    assert "example.com" not in str(mcp_server.redact_data(DATA))
    err = mcp_server._tool_error("bridge_error", "failed for jane@example.com", result=DATA)
    assert "example.com" not in str(err.structuredContent)
    assert "example.com" not in err.content[0].text
