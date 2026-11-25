"""Fail-closed branches of panel_token, dev_mode, audit and dispatch (issue #237).

Permission and I/O failures are simulated with monkeypatch so the tests also run as root and on
Windows. Windows-only branches run on any OS through a stand-in for the ``os`` module whose
``name`` is ``nt``; icacls itself is UNVERIFIED here.
"""
from __future__ import annotations

import errno
import json
import logging
import os
import subprocess
from types import SimpleNamespace

import pytest

from revit_mcp_server.security import dev_mode as dev
from revit_mcp_server.security import panel_token
from revit_mcp_server.security.audit import (
    GENESIS_HASH, AuditRecorder, _last_hash, redact_data, register_secret_value, verify_audit_log,
)
from revit_mcp_server.security.dispatch import gate_after_result, settle_in_flight
from revit_mcp_server.security.panel_token import PanelTokenError, load_or_create_token, read_token

posix_only = pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
TOKEN = "B" * 43


class _NtOs:
    """The real ``os`` module, except that it reports Windows."""
    name = "nt"

    def __getattr__(self, item):
        return getattr(os, item)


@pytest.fixture
def token_file(tmp_path, monkeypatch):
    path = tmp_path / "keys" / "panel-hub.token"
    monkeypatch.setenv(panel_token.TOKEN_ENV_FILE, str(path))
    return path


def _write_token(path, content=TOKEN + "\n", mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content if isinstance(content, bytes) else content.encode())
    path.chmod(mode)


# ---------------------------------------------------------------- panel_token

def test_whoami_without_sid_is_refused(monkeypatch):
    monkeypatch.setattr(panel_token.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout="no sid here"))
    with pytest.raises(ValueError, match="no SID"):
        panel_token._current_user_sid()


@pytest.mark.parametrize("failure", [OSError("boom"), ValueError("no SID"), subprocess.TimeoutExpired("icacls", 15)])
def test_acl_failure_refuses_without_leaking_detail(monkeypatch, tmp_path, failure):
    def fail(*a, **k):
        raise failure
    monkeypatch.setattr(panel_token.subprocess, "run", fail)
    with pytest.raises(PanelTokenError, match=rf"Could not restrict access to the panel token file \({type(failure).__name__}\)\.$"):
        panel_token._restrict_windows_acl(tmp_path / "t")


@posix_only
def test_non_ascii_token_file_is_refused(token_file):
    _write_token(token_file, b"\xff\xfe" + b"A" * 41)
    with pytest.raises(PanelTokenError, match="cannot be read; delete it and restart the hub"):
        read_token()


@posix_only
def test_directory_instead_of_token_file_is_refused(token_file):
    token_file.mkdir(parents=True)
    with pytest.raises(PanelTokenError, match="is not a regular file; delete it and restart the hub"):
        read_token()


@posix_only
def test_token_file_owned_by_another_user_is_refused(token_file, monkeypatch):
    _write_token(token_file)
    monkeypatch.setattr(panel_token.os, "getuid", lambda: os.stat(token_file).st_uid + 1)
    with pytest.raises(PanelTokenError, match="is owned by another user; delete it and restart the hub"):
        read_token()


@posix_only
def test_read_error_is_refused(token_file, monkeypatch):
    _write_token(token_file)

    def fail(fd, n):
        raise OSError(errno.EIO, "input/output error")
    monkeypatch.setattr(panel_token.os, "read", fail)
    with pytest.raises(PanelTokenError, match="cannot be read; delete it and restart the hub"):
        read_token()


@posix_only
def test_no_hard_links_falls_back_to_exclusive_create(token_file, monkeypatch):
    def no_link(src, dst):
        raise OSError(errno.EPERM, "hard links not supported")
    monkeypatch.setattr(panel_token.os, "link", no_link)
    token = load_or_create_token()
    assert panel_token.is_valid_token(token)
    assert token_file.stat().st_mode & 0o077 == 0
    assert [p.name for p in token_file.parent.iterdir()] == [token_file.name]


@posix_only
def test_failed_temp_cleanup_does_not_break_creation(token_file, monkeypatch):
    real_unlink = os.unlink

    def unlink(path, *a, **k):
        if str(path).endswith(".tmp"):
            raise OSError(errno.EACCES, "denied")
        return real_unlink(path, *a, **k)
    monkeypatch.setattr(panel_token.os, "unlink", unlink)
    assert panel_token.is_valid_token(load_or_create_token())


def test_exclusive_copy_never_overwrites_existing_file(tmp_path):
    existing = tmp_path / "panel-hub.token"
    existing.write_text("keep me")
    panel_token._exclusive_copy(existing, TOKEN)
    assert existing.read_text() == "keep me"


@posix_only
def test_windows_create_restricts_the_acl(token_file, monkeypatch):
    seen = []
    monkeypatch.setattr(panel_token, "os", _NtOs())
    monkeypatch.setattr(panel_token, "_restrict_windows_acl", seen.append)
    assert panel_token.is_valid_token(load_or_create_token())
    assert len(seen) == 1 and seen[0].name.endswith(".tmp")


def _deny_acl(path):
    raise PanelTokenError("Could not restrict access to the panel token file (OSError).")


@posix_only
def test_windows_acl_failure_on_copy_deletes_the_file(tmp_path, monkeypatch):
    target = tmp_path / "panel-hub.token"
    monkeypatch.setattr(panel_token, "os", _NtOs())
    monkeypatch.setattr(panel_token, "_restrict_windows_acl", _deny_acl)
    with pytest.raises(PanelTokenError, match="Could not restrict access to the panel token file"):
        panel_token._exclusive_copy(target, TOKEN)
    assert not target.exists()


@posix_only
def test_windows_acl_failure_still_refuses_when_delete_fails(tmp_path, monkeypatch):
    def unlink_fails(path, *a, **k):
        raise OSError(errno.EACCES, "denied")
    nt = _NtOs()
    nt.unlink = unlink_fails
    monkeypatch.setattr(panel_token, "os", nt)
    monkeypatch.setattr(panel_token, "_restrict_windows_acl", _deny_acl)
    with pytest.raises(PanelTokenError, match="Could not restrict access to the panel token file"):
        panel_token._exclusive_copy(tmp_path / "panel-hub.token", TOKEN)


# ------------------------------------------------------------------- dev_mode

def test_enable_dev_refuses_an_invalid_token(tmp_path):
    with pytest.raises(PanelTokenError, match="A valid panel token is required to enable Dev mode"):
        dev.enable_dev(tmp_path, token="short")
    assert not dev.dev_path(tmp_path).exists()


def test_unknown_panel_mode_is_refused(tmp_path):
    with pytest.raises(ValueError, match="Unknown panel approval mode"):
        dev.set_panel_mode(tmp_path, "root", token=TOKEN)


@pytest.fixture
def dev_ws(tmp_path, token_file):
    ws = tmp_path / "ws"
    ws.mkdir()
    dev.enable_dev(ws, token=TOKEN)
    return ws


def _rewrite(ws, **changes):
    record = json.loads(dev.dev_path(ws).read_text())
    record.update(changes)
    dev.dev_path(ws).write_text(json.dumps(record))


MALFORMED = "the Dev record in this workspace is malformed"


def test_dev_record_with_wrong_fields_reads_off(dev_ws):
    _rewrite(dev_ws, extra="x")
    assert dev.dev_off_reason(dev_ws, token=TOKEN) == MALFORMED
    assert dev.active_dev(dev_ws, token=TOKEN) is False


@pytest.mark.parametrize("changes", [
    {"mode": "auto"}, {"set_at": -1}, {"set_at": True}, {"sig": 5}, {"nonce": "z" * 64}, {"nonce": "ab"},
])
def test_dev_record_with_bad_values_reads_off(dev_ws, changes):
    _rewrite(dev_ws, **changes)
    assert dev.dev_off_reason(dev_ws, token=TOKEN) == MALFORMED


def test_dev_without_a_valid_token_reads_off(dev_ws):
    assert dev.dev_off_reason(dev_ws, token="bad") == "key mismatch: no valid panel token to verify the Dev record"


def test_dev_with_unreadable_token_file_reads_off(dev_ws, monkeypatch):
    def unreadable(*a, **k):
        raise PanelTokenError("unreadable")
    monkeypatch.setattr(dev, "read_token", unreadable)
    assert dev.dev_off_reason(dev_ws) == "key mismatch: the panel token or authority record could not be read"


@posix_only
def test_windows_private_record_restricts_the_acl(tmp_path, token_file, monkeypatch):
    seen = []
    monkeypatch.setattr(dev, "os", _NtOs())
    monkeypatch.setattr(dev, "_restrict_windows_acl", seen.append)
    dev.enable_dev(tmp_path, token=TOKEN)
    assert len(seen) == 1 and dev.active_dev(tmp_path, token=TOKEN)


# ---------------------------------------------------------------------- audit

def test_redact_data_masks_tuple_items():
    register_secret_value("tuple-secret-value")
    out = redact_data(("keep", "has tuple-secret-value inside"))
    assert isinstance(out, tuple) and out[0] == "keep"
    assert "tuple-secret-value" not in out[1]


def test_last_hash_of_a_corrupt_last_line_is_genesis(tmp_path):
    path = tmp_path / "audit.log"
    AuditRecorder(path).record("tool", "r0", {}, {})
    with path.open("a") as fh:
        fh.write("not json\n")
    assert _last_hash(path) == GENESIS_HASH


def test_verify_skips_blank_lines(tmp_path):
    path = tmp_path / "audit.log"
    rec = AuditRecorder(path)
    rec.record("tool", "r0", {}, {})
    rec.record("tool", "r1", {}, {})
    lines = path.read_text().splitlines()
    path.write_text(lines[0] + "\n\n" + lines[1] + "\n")
    assert verify_audit_log(path)["ok"] is True


def test_verify_refuses_a_non_object_line(tmp_path):
    path = tmp_path / "audit.log"
    path.write_text("[1, 2]\n")
    result = verify_audit_log(path)
    assert result["ok"] is False and result["error"] == "line is not a JSON object" and result["line"] == 1


# ------------------------------------------------------------------- dispatch

class _BrokenGate:
    def mark_in_flight(self, *a, **k):
        raise RuntimeError("disk full")

    def in_flight(self, key):
        raise RuntimeError("disk full")


def test_failed_in_flight_record_is_logged_and_the_call_stays_running(caplog):
    result = {"status": "running", "request_id": "req-1"}
    with caplog.at_level(logging.ERROR):
        outcome = gate_after_result(_BrokenGate(), {"plan_id": "p", "key": "k"}, "revit_set_parameter_value", result)
    assert outcome.state == "running"
    assert "Could not record a plan action as in flight" in caplog.text


def test_failed_settle_is_logged_and_does_not_raise(caplog):
    with caplog.at_level(logging.ERROR):
        settle_in_flight(_BrokenGate(), "revit_get_result", {"request_id": "req-1"}, result={"success": True})
    assert "Could not settle the in-flight action for revit_get_result" in caplog.text
