"""Fail-closed branches of the approval override, gating, binding and redaction helpers."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from revit_mcp_server.security import approval_override as ov
from revit_mcp_server.security.binding import _path_hash, live_binding
from revit_mcp_server.security.gating import requires_approval
from revit_mcp_server.security.response_redaction import redact_response

TOKEN = "A" * 43
NOW = 10_000


def _write(tmp_path, record):
    (tmp_path / ov.OVERRIDE_FILENAME).write_text(
        record if isinstance(record, str) else json.dumps(record), encoding="utf-8")


def _valid(**changes):
    record = {"mode": "auto", "set_at": NOW, "expires_at": NOW + 600,
              "sig": ov._sign(TOKEN, NOW, NOW + 600)}
    record.update(changes)
    return record


def test_valid_record_is_accepted_baseline(tmp_path):
    _write(tmp_path, _valid())
    assert ov.active_override(tmp_path, token=TOKEN, now=NOW + 1) is not None


@pytest.mark.parametrize("record", [
    "not json",
    "[]",
    {"mode": "look_only"},
    {"mode": "auto", "set_at": NOW},
    _valid(set_at=True),
    _valid(expires_at=float(NOW + 600)),
    _valid(sig=123),
    _valid(expires_at=NOW + ov.MAX_AUTO_MINUTES * 60 + 1),
    _valid(set_at=NOW + 10_000, expires_at=NOW + 10_600),
    _valid(sig="0" * 64),
])
def test_malformed_or_tampered_record_is_ignored(tmp_path, record):
    _write(tmp_path, record)
    assert ov.active_override(tmp_path, token=TOKEN, now=NOW + 1) is None


def test_empty_token_never_validates(tmp_path):
    _write(tmp_path, _valid())
    assert ov.active_override(tmp_path, token="", now=NOW + 1) is None


def _tool(mutating=True):
    return SimpleNamespace(is_mutating=mutating)


def _registry(hook=None):
    provider = SimpleNamespace() if hook is None else SimpleNamespace(call_is_read_only=hook)
    return SimpleNamespace(lookup_tool_provider=lambda name: provider)


def test_gating_fails_closed():
    assert requires_approval(_registry(), "t", None, {}) is False
    assert requires_approval(_registry(), "t", _tool(False), {}) is False
    assert requires_approval(_registry(), "t", _tool(), "not a dict") is True
    assert requires_approval(_registry(), "t", _tool(), {}) is True
    assert requires_approval(_registry(lambda n, a: False), "t", _tool(), {}) is True
    assert requires_approval(_registry(lambda n, a: "yes"), "t", _tool(), {}) is True
    assert requires_approval(_registry(lambda n, a: True), "t", _tool(), {}) is False


@pytest.mark.parametrize("value", [None, "", "   ", 5, ["x"]])
def test_path_hash_rejects_non_paths(value):
    assert _path_hash(value) is None


def test_path_hash_ignores_case_and_separators():
    assert _path_hash("C:\\Models\\A.rvt") == _path_hash(" c:/models/a.rvt ")


@pytest.mark.parametrize("context", [None, "x", {"mock": True, "document": {"guid": "g"}},
                                     {"document": "x"}, {"document": {"title": "t"}},
                                     {"document": {"is_workshared": True, "central_path": ""}}])
def test_live_binding_without_identity_is_none(context):
    assert live_binding(context) is None


def test_redaction_walks_tuples_and_masks_emails():
    out = redact_response({"items": ("mail a@example.com", 3)}, "strict")
    assert isinstance(out["items"], tuple)
    assert "a@example.com" not in out["items"][0] and out["items"][1] == 3
