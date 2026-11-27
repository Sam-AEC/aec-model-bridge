"""Harness safety and honest evidence, using fake transports; no Revit or sleeps."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location("live_acceptance_harness", ROOT / "scripts/revit/acceptance/run.py")
assert SPEC and SPEC.loader
harness = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(harness)
GUID = "b3e63473-1641-4c71-9425-510915cddc65"


def options(*extra):
    return harness.parser().parse_args(["--pid", "123", "--expected-document", "Acceptance scratch",
                                       "--expected-guid", GUID, *extra])


def context(title="Acceptance scratch", guid=GUID, mode="ask_first"):
    return {"ok": True, "addin_supports_context": True, "busy": False,
            "document": {"title": title, "guid": guid, "path": "unsaved", "is_family": False},
            "addin": {"module_id": "module-1", "assembly_file_time_utc": "2026-10-14T08:00:00Z"},
            "queue": {"depth": 0, "running": None}, "server": {"approval_mode": mode}}


def read_result(opts=None, marker="", elements=4):
    opts = opts or options()
    return {"success": True, "mode": "read", "model_changes_in_read_mode": 0,
            "output": json.dumps({"identity": [opts.expected_document, opts.expected_guid],
                                  "elements": elements, "warnings": 0, "modifiable": False,
                                  "stdlib": [1, 2], "marker": marker})}


class FakeClient:
    def __init__(self, ctx=None, refusal=None, changed=False, duration=False):
        self.context = ctx or context()
        self.refusal = refusal or harness.REFUSAL + " (found: Transaction)"
        self.changed, self.duration = changed, duration
        self.calls, self.reads, self.marker, self.polls = [], 0, "", 0

    def call(self, tool, args):
        self.calls.append((tool, args))
        if tool == "revit_get_context":
            return self.context
        if tool == "revit_get_result":
            self.polls += 1
            return read_result(marker=self.marker)
        assert tool == "revit_execute_python" and args["mode"] == "read"
        assert "plan_id" not in args
        if "Transaction" in args["script"]:
            raise harness.AcceptanceError(self.refusal)
        self.reads += 1
        if "time.sleep(" in args["script"]:
            # Execute the fixed read script in a synthetic scope is not needed: the marker
            # supplied to the fake output is independent of its receipt/replay assertions.
            import re
            self.marker = re.search(r"'marker': (\"[^\"]+\")", args["script"])[1].strip('"')
            return {"status": "running", "request_id": "durable-r1"}
        return read_result(elements=5 if self.changed and self.reads > 1 else 4)


def test_default_cli_is_offline_and_does_not_read_token(monkeypatch, capsys):
    monkeypatch.setattr(harness, "read_token", lambda: pytest.fail("Plan read a secret"))
    assert harness.main(["--pid", "123", "--expected-document", "Acceptance scratch", "--expected-guid", GUID]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "NOT_RUN"


@pytest.mark.parametrize("ctx", [context(guid="another-guid"), context(title="Another document"),
                                {**context(), "mock": True}, {**context(), "busy": True},
                                {**context(), "addin_supports_context": False},
                                {**context(), "queue": {"depth": 1}}])
def test_bad_preflight_never_submits_script(ctx):
    client = FakeClient(ctx=ctx)
    report = harness.run_checks(client, options())
    assert report["checks"]["preflight_or_transport"]["status"] == "FAIL"
    assert [name for name, _ in client.calls] == ["revit_get_context"]


def test_existing_document_requires_explicit_exact_owner_scope():
    opts = options()
    opts.expected_document = "Example project"
    ctx = context(title=opts.expected_document)
    with pytest.raises(harness.AcceptanceError, match="Default scope"):
        harness.identity(ctx, opts)
    opts.allow_existing_test_document = True
    assert harness.identity(ctx, opts)["title"] == opts.expected_document
    ctx["document"]["guid"] = "different"
    with pytest.raises(harness.AcceptanceError, match="exact expected"):
        harness.identity(ctx, opts)


def _scratch_context(title):
    ctx = context(title=title)
    return ctx


def test_production_pattern_env_rejects_matching_names(monkeypatch):
    opts = options()
    opts.expected_document = "Acme scratch"
    ctx = _scratch_context(opts.expected_document)
    monkeypatch.delenv("AEC_ACCEPTANCE_PRODUCTION_PATTERN", raising=False)
    assert harness.identity(ctx, opts)["title"] == "Acme scratch"
    monkeypatch.setenv("AEC_ACCEPTANCE_PRODUCTION_PATTERN", "ACME|contoso")
    with pytest.raises(harness.AcceptanceError, match="Default scope"):
        harness.identity(ctx, opts)
    monkeypatch.setenv("AEC_ACCEPTANCE_PRODUCTION_PATTERN", "")
    assert harness.identity(ctx, opts)["title"] == "Acme scratch"


def test_production_pattern_env_invalid_regex_fails_closed(monkeypatch):
    monkeypatch.setenv("AEC_ACCEPTANCE_PRODUCTION_PATTERN", "(unclosed")
    with pytest.raises(harness.AcceptanceError, match="AEC_ACCEPTANCE_PRODUCTION_PATTERN"):
        harness.identity(context(), options())


def test_builtin_production_words_still_rejected(monkeypatch):
    monkeypatch.delenv("AEC_ACCEPTANCE_PRODUCTION_PATTERN", raising=False)
    opts = options()
    opts.expected_document = "prod scratch"
    with pytest.raises(harness.AcceptanceError, match="Default scope"):
        harness.identity(_scratch_context(opts.expected_document), opts)


@pytest.mark.parametrize(("mode", "expected"), [("ask_first", "PASS"), ("auto", "PARTIAL"), ("look_only", "PARTIAL")])
def test_t11_only_proves_no_plan_exemption_in_ask_first(mode, expected):
    report = harness.run_checks(FakeClient(ctx=context(mode=mode)), options())
    assert report["checks"]["runtime"]["status"] == "PASS"
    assert report["checks"]["T11"]["status"] == expected
    assert report["checks"]["T2"]["status"] == "UNSUPPORTED"


@pytest.mark.parametrize("client", [FakeClient(refusal="unrelated network error"), FakeClient(changed=True)])
def test_arbitrary_error_or_changed_counts_cannot_pass_t11(client):
    report = harness.run_checks(client, options())
    assert report["checks"]["T11"]["status"] == "FAIL"


@pytest.mark.parametrize("alter", [{"model_changes_in_read_mode": 1}, {"mode": "write"},
                                 {"success": False}, {"output": "[]"}])
def test_read_runner_requires_real_zero_change_metadata(alter):
    with pytest.raises(harness.AcceptanceError):
        harness.decode_read({**read_result(), **alter}, options())


def test_t1_uses_result_interface_and_does_not_claim_full_acceptance():
    client = FakeClient(duration=True)
    checkpoints = []
    report = harness.run_checks(client, options("--t1-seconds"), checkpoint=checkpoints.append,
                                sleep=lambda _: pytest.fail("Unexpected test sleep"))
    detail = report["checks"]["T1"]["detail"]
    assert detail["ninety_second_result_subcase"] == "PASS"
    assert detail["retained_replay_matches"] is True
    assert report["checks"]["T1"]["status"] == "PARTIAL"
    assert detail["mcp_client_kill"].startswith("NOT_RUN")
    assert checkpoints[0]["run_id"].endswith("-pending")
    fetches = [args for name, args in client.calls if name == "revit_get_result"]
    assert fetches == [{"request_id": "durable-r1", "wait_s": 5}, {"request_id": "durable-r1", "wait_s": 0}]


def test_resume_collects_without_resubmitting_or_queueing_preflight():
    client = FakeClient()
    client.marker = "earlier-marker"
    report = harness.run_checks(client, options("--resume-request-id", "durable-r1", "--expected-marker", client.marker))
    assert [name for name, _ in client.calls] == ["revit_get_result", "revit_get_context", "revit_get_result"]
    assert report["checks"]["T1"]["status"] == "PARTIAL"
    assert report["checks"]["T11"]["status"] == "NOT_RUN"


def test_read_script_pins_document_before_and_after_delay():
    script = harness.read_script(options(), seconds=90, marker="receipt-marker")
    assert script.count("assert session_identity() == expected") == 2
    assert "time.sleep(90)" in script and GUID in script
    from revit_mcp_server.security.read_mode import validate_read_script
    validate_read_script(script)
    compile(script, "acceptance-read-script", "exec")


@pytest.mark.parametrize("url", ["https://127.0.0.1:8787", "http://evil.example:8787", "http://127.0.0.1:8787/path",
                               "http://token@127.0.0.1:8787", "http://127.0.0.1:8787?token=x"])
def test_transport_refuses_secret_exfiltration_targets(url):
    with pytest.raises(harness.AcceptanceError):
        harness.PanelClient(url, 123, "s" * 43)


def test_transport_uses_authenticated_panel_instance_schema(monkeypatch):
    captured = []

    def handler(request):
        captured.append(json.loads(request.content))
        assert request.headers["X-AMB-Token"] == "s" * 43
        return httpx.Response(200, json={"ok": True, "result": {"answer": 1}})

    factory = httpx.Client
    monkeypatch.setattr(harness.httpx, "Client", lambda **kw: factory(transport=httpx.MockTransport(handler), **kw))
    assert harness.PanelClient("http://127.0.0.1:8787", 123, "s" * 43).call("revit_get_context", {}) == {"answer": 1}
    assert captured == [{"tool": "revit_get_context", "arguments": {}, "instance": {"pid": 123}}]


def test_evidence_is_bounded_redacted_exclusive_and_inside_ignored_artifacts(tmp_path, monkeypatch):
    monkeypatch.setattr(harness, "ROOT", tmp_path)
    harness.PanelClient("http://127.0.0.1:8787", 123, "s" * 43)
    report = {"run_id": "case-1", "token": "s" * 43, "message": "secret echo " + "s" * 43,
              "path": "C:/secret/project.rvt", "large": "x" * 10000}
    evidence = harness.write_evidence(report, tmp_path / "artifacts" / "acceptance")
    content = evidence.read_text()
    assert "s" * 43 not in content and "C:/secret" not in content and len(content) < 3000
    with pytest.raises(FileExistsError):
        harness.write_evidence(report, evidence.parent)
    with pytest.raises(harness.AcceptanceError):
        harness.write_evidence(report, tmp_path / "tracked")


# ---- kit mode ----
KIT_TITLE = "Scratch café model"


class FakeKitClient:
    def __init__(self, *, mock=False, headline=None, title=KIT_TITLE):
        self.mock, self.headline, self.title = mock, headline, title
        self.calls = []

    def call(self, tool, args):
        self.calls.append((tool, args))
        if tool == "revit_health":
            return {"ok": True}
        if tool == "revit_get_context":
            return {"ok": True, "mock": self.mock,
                    "document": {"title": self.title, "is_workshared": True, "is_family": False},
                    "revit": {"version": "2024"}, "addin": {"version": "1.6.0"},
                    "server": {"version": "1.6.0", "approval_mode": "ask_first"}}
        if tool == "revit_extract_snapshot":
            return {"snapshot_id": "01JSNAP"}
        if tool == "sheet_view_audit_run_audit":
            return {"status": "ok", "views_captured": True, "rated": True,
                    **({"headline": self.headline} if self.headline else {})}
        if tool == "schedule_diff_compare":
            return {"status": "ok", "schedules": {"status": "compared"}}
        if tool == "model_health_score":
            return {"score": 81.5}
        if tool == "param_completeness_heatmap":
            return {"rows": [{"category": "OST_Doors"}]}
        if tool == "policy_show":
            return {"hash": "abc"}
        if tool == "list_pending_plans":
            return {"plans": []}
        raise AssertionError(f"unexpected tool {tool}")


def kit_options(*extra):
    return harness.parser().parse_args(["--kit", "--pid", "123", *extra])


def test_kit_calls_only_read_tools_and_never_a_mutating_one():
    client = FakeKitClient()
    harness.run_kit(client, kit_options())
    names = {name for name, _ in client.calls}
    assert names <= harness.KIT_READ_TOOLS
    for word in ("plan_actions", "execute_plan", "approve", "revit_execute_python", "reject", "rollback"):
        assert not any(word in name for name in names)
    assert all("plan_id" not in args for _, args in client.calls)


def test_kit_guard_refuses_unlisted_tools_before_sending():
    inner = FakeKitClient()
    guard = harness.KitGuard(inner)
    for tool in ("execute_plan", "plan_actions", "approve_plan", "revit_execute_python", "revit_set_parameter_value"):
        with pytest.raises(harness.AcceptanceError, match="read-only"):
            guard.call(tool, {})
    assert inner.calls == [] and guard.calls == []


def test_kit_report_shape_and_title_is_hashed_not_stored():
    report = harness.run_kit(FakeKitClient(), kit_options())
    assert report["revit_version"] == "2024" and report["addin_version"] == "1.6.0"
    assert report["timestamp"] and report["run_id"].startswith("kit-")
    assert list(report["cards"]) == [str(c["issue"]) for c in harness.KIT_CARDS]
    assert [report["cards"][k]["status"] for k in ("142", "367", "147", "218")] == ["AUTO-PASS"] * 4
    assert report["cards"]["142"]["evidence"]["snapshot_seconds"] >= 0
    assert report["document"]["title_sha256_16"] == harness.title_hash(KIT_TITLE)
    assert "caf" not in json.dumps(report) and "Scratch" not in json.dumps(report)
    assert report["calls"][:2] == ["revit_health", "revit_get_context"]


def test_kit_manual_cards_are_listed_and_write_cards_marked():
    report = harness.run_kit(FakeKitClient(), kit_options())
    manual = {k for k, c in report["cards"].items() if c["status"] == "MANUAL"}
    assert manual == {"371", "372", "397", "211", "281", "280", "150", "148", "149", "293"}
    assert {k for k, c in report["cards"].items() if c["writes"]} == {"218", "150", "148", "149", "293"}
    assert "MANUAL" in harness.kit_markdown(report) and "WRITE" in harness.kit_markdown(report)


def test_kit_autofail_when_audit_says_views_not_captured():
    report = harness.run_kit(FakeKitClient(headline="views not captured: result not rated"), kit_options())
    assert report["cards"]["142"]["status"] == "AUTO-FAIL"
    assert report["cards"]["367"]["status"] == "AUTO-PASS"


def test_kit_mock_hub_fails_auto_cards_and_stops_after_context():
    client = FakeKitClient(mock=True)
    report = harness.run_kit(client, kit_options())
    assert [n for n, _ in client.calls] == ["revit_health", "revit_get_context"]
    assert "prerequisite_error" in report
    assert all(report["cards"][k]["status"] == "AUTO-FAIL" for k in ("142", "367", "147", "218"))


def test_kit_slow_snapshot_fails_142():
    ticks = iter([0.0, 25.0])
    report = harness.run_kit(FakeKitClient(), kit_options(), clock=lambda: next(ticks))
    assert report["cards"]["142"]["status"] == "AUTO-FAIL"


def test_kit_cli_default_is_offline_and_rejects_document_scope(monkeypatch, capsys):
    monkeypatch.setattr(harness, "read_token", lambda: pytest.fail("Plan read a secret"))
    assert harness.main(["--kit", "--pid", "123"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "NOT_RUN"
    with pytest.raises(SystemExit):
        harness.main(["--kit", "--pid", "123", "--expected-document", "x"])


def test_kit_run_writes_ascii_json_and_markdown_under_artifacts(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(harness, "ROOT", tmp_path)
    monkeypatch.setattr(harness, "KIT_DIR", tmp_path / "artifacts" / "revit-kit")
    monkeypatch.setattr(harness, "read_token", lambda: "s" * 43)
    client = FakeKitClient()
    monkeypatch.setattr(harness, "PanelClient", lambda *a, **k: client)
    assert harness.main(["--kit", "--pid", "123", "--run"]) == 0
    out = capsys.readouterr().out
    out.encode("ascii")
    files = sorted((tmp_path / "artifacts" / "revit-kit").iterdir())
    assert [f.suffix for f in files] == [".json", ".md"]
    for f in files:
        f.read_bytes().decode("ascii")
    saved = json.loads(files[0].read_text())
    assert saved["cards"]["142"]["status"] == "AUTO-PASS" and "caf" not in files[0].read_text()
    assert "card #371 MANUAL" in out


def test_kit_report_refuses_paths_outside_artifacts(tmp_path, monkeypatch):
    monkeypatch.setattr(harness, "ROOT", tmp_path)
    with pytest.raises(harness.AcceptanceError):
        harness.write_kit_report({"run_id": "kit-x"}, tmp_path / "tracked")


def test_kit_doc_has_one_card_per_issue_in_order_and_marks_writes():
    text = (ROOT / "docs/live-verification-kit.md").read_text(encoding="utf-8")
    import re
    cards = re.findall(r"^### Card (\d+): #(\d+) ", text, re.M)
    assert [int(issue) for _, issue in cards] == [c["issue"] for c in harness.KIT_CARDS]
    assert [int(n) for n, _ in cards] == list(range(1, len(cards) + 1))
    sections = re.split(r"^### Card ", text, flags=re.M)[1:]
    for body, meta in zip(sections, harness.KIT_CARDS):
        assert ("WRITE: owner approves in the panel" in body.split("- Preconditions")[0]) == meta["writes"]


def test_kit_non_ascii_error_text_is_escaped_in_output_and_files(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(harness, "ROOT", tmp_path)
    monkeypatch.setattr(harness, "KIT_DIR", tmp_path / "artifacts" / "revit-kit")
    monkeypatch.setattr(harness, "read_token", lambda: "s" * 43)

    class Failing(FakeKitClient):
        def call(self, tool, args):
            if tool == "schedule_diff_compare":
                raise harness.AcceptanceError("café ✓ failed")
            return super().call(tool, args)

    monkeypatch.setattr(harness, "PanelClient", lambda *a, **k: Failing())
    assert harness.main(["--kit", "--pid", "123", "--run"]) == 1
    capsys.readouterr().out.encode("ascii")
    for f in (tmp_path / "artifacts" / "revit-kit").iterdir():
        text = f.read_bytes().decode("ascii")
        assert "367" in text
