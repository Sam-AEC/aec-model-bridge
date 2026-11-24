import json

from revit_mcp_server.security.audit import AuditRecorder, main as audit_main, verify_audit_log


def _write(path, n=3):
    rec = AuditRecorder(path)
    for i in range(n):
        rec.record("tool", f"r{i}", {"a": i}, {"ok": True})
    return path


def test_chain_verifies_and_survives_new_recorder(tmp_path):
    path = _write(tmp_path / "audit.log", 2)
    AuditRecorder(path).record("tool", "r9", {}, {})
    result = verify_audit_log(path)
    assert result["ok"] and result["entries"] == 3


def test_log_stays_readable_json_lines(tmp_path):
    path = _write(tmp_path / "audit.log", 1)
    entry = json.loads(path.read_text().splitlines()[0])
    assert entry["tool"] == "tool" and entry["request_id"] == "r0"


def test_edit_detected(tmp_path):
    path = _write(tmp_path / "audit.log")
    lines = path.read_text().splitlines()
    lines[1] = lines[1].replace('"a": 1', '"a": 99')
    path.write_text("\n".join(lines) + "\n")
    result = verify_audit_log(path)
    assert not result["ok"] and result["line"] == 2


def test_deleted_line_detected(tmp_path):
    path = _write(tmp_path / "audit.log")
    lines = path.read_text().splitlines()
    path.write_text("\n".join([lines[0], lines[2]]) + "\n")
    result = verify_audit_log(path)
    assert not result["ok"] and result["line"] == 2


def test_legacy_lines_accepted_only_at_start(tmp_path):
    path = tmp_path / "audit.log"
    legacy = json.dumps({"tool": "old", "payload": {}})
    path.write_text(legacy + "\n")
    AuditRecorder(path).record("tool", "r", {}, {})
    result = verify_audit_log(path)
    assert result["ok"] and result["legacy_entries"] == 1 and result["entries"] == 1
    with path.open("a") as fh:
        fh.write(legacy + "\n")
    assert not verify_audit_log(path)["ok"]


def test_missing_and_invalid(tmp_path):
    assert not verify_audit_log(tmp_path / "none.log")["ok"]
    path = tmp_path / "bad.log"
    path.write_text("not json\n")
    assert not verify_audit_log(path)["ok"]


def test_cli_exit_codes(tmp_path):
    path = _write(tmp_path / "audit.log")
    assert audit_main(["verify", str(path)]) == 0
    path.write_text(path.read_text().replace("r1", "rX"))
    assert audit_main(["verify", str(path)]) == 1
