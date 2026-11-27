"""Small live acceptance runner. Defaults to a plan; never edits model content."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from revit_mcp_server.security.audit import redact_data, register_secret_value
from revit_mcp_server.security.panel_token import TOKEN_HEADER, read_token

ROOT = Path(__file__).resolve().parents[3]
ARTIFACTS = ROOT / "artifacts" / "revit-acceptance"
KIT_DIR = ROOT / "artifacts" / "revit-kit"
REFUSAL = "Read mode refuses scripts that could change the model"
MAX_RESPONSE = 256 * 1024


class AcceptanceError(RuntimeError):
    pass


class PanelClient:
    """Use the real human-panel schema; never accept or create approval overrides."""

    def __init__(self, url: str, pid: int, token: str, timeout: float = 40):
        parsed = urlsplit(url)
        if (parsed.scheme != "http" or parsed.hostname != "127.0.0.1"
                or parsed.username or parsed.password or parsed.path not in ("", "/")
                or parsed.query or parsed.fragment or not parsed.port):
            raise AcceptanceError("Hub must be http://127.0.0.1:<port> without credentials or a path.")
        self.url, self.pid, self.token, self.timeout = url.rstrip("/"), pid, token, timeout
        register_secret_value(token)

    def call(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        # Each call opens a fresh HTTP client: result collection does not depend on a submit session.
        try:
            with httpx.Client(timeout=self.timeout, trust_env=False, follow_redirects=False) as client:
                with client.stream("POST", self.url + "/execute", headers={TOKEN_HEADER: self.token},
                                   json={"tool": tool, "arguments": arguments,
                                         "instance": {"pid": self.pid}}) as response:
                    chunks, size = [], 0
                    for chunk in response.iter_bytes():
                        size += len(chunk)
                        if size > MAX_RESPONSE:
                            raise AcceptanceError("Panel response exceeds the evidence budget.")
                        chunks.append(chunk)
                    body = json.loads(b"".join(chunks))
                    if not isinstance(body, dict):
                        raise AcceptanceError("Panel returned a malformed response.")
                    if response.status_code != 200 or body.get("ok") is not True:
                        raise AcceptanceError(str(redact_data(body.get("error", "Panel request failed."))))
                    result = body.get("result")
                    if not isinstance(result, dict):
                        raise AcceptanceError("Panel returned a non-object tool result.")
                    return result
        except (httpx.HTTPError, json.JSONDecodeError) as exc:
            # Do not expose transport internals, headers or credentials through exception reprs.
            raise AcceptanceError(f"Panel transport failed ({type(exc).__name__}).") from None


def bounded(value: Any, depth: int = 0) -> Any:
    if depth >= 8:
        return "<depth-limit>"
    if isinstance(value, dict):
        return {str(k): bounded(v, depth + 1) for k, v in list(value.items())[:32]}
    if isinstance(value, (list, tuple)):
        return [bounded(v, depth + 1) for v in value[:32]]
    if isinstance(value, str):
        return value[:1500] + ("<truncated>" if len(value) > 1500 else "")
    return value


def write_evidence(report: dict[str, Any], directory: Path = ARTIFACTS) -> Path:
    directory = directory.resolve()
    if not directory.is_relative_to((ROOT / "artifacts").resolve()):
        raise AcceptanceError("Evidence must stay inside the ignored artifacts directory.")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (report["run_id"] + ".json")
    safe = bounded(redact_data(report))
    payload = json.dumps(safe, indent=2, ensure_ascii=True)
    if len(payload.encode("utf-8")) > 100 * 1024:
        raise AcceptanceError("Evidence exceeds 100 KiB.")
    # Never overwrite evidence of an earlier run.
    with path.open("x", encoding="utf-8") as stream:
        stream.write(payload + "\n")
    return path


PRODUCTION_PATTERN_ENV = "AEC_ACCEPTANCE_PRODUCTION_PATTERN"


def production_pattern() -> re.Pattern[str] | None:
    """Optional extra regex (case-insensitive) that marks a document as production. Empty means unset."""
    raw = os.environ.get(PRODUCTION_PATTERN_ENV, "").strip()
    if not raw:
        return None
    try:
        return re.compile(raw, re.I)
    except re.error:
        # Fail closed: a pattern that cannot be read must not silently weaken the guard.
        raise AcceptanceError(f"{PRODUCTION_PATTERN_ENV} is not a valid regular expression.") from None


def identity(context: dict[str, Any], options: argparse.Namespace) -> dict[str, Any]:
    document = context.get("document")
    if (context.get("mock") or context.get("busy") or context.get("ok") is not True
            or context.get("addin_supports_context") is not True or not isinstance(document, dict)):
        raise AcceptanceError("Live document context is unavailable; refusing to run scripts.")
    if document.get("title") != options.expected_document or str(document.get("guid", "")).lower() != options.expected_guid.lower():
        raise AcceptanceError("Active document does not match the exact expected title and GUID.")
    if document.get("is_family"):
        raise AcceptanceError("Use a project document, not a family document.")
    labels = " ".join(str(document.get(k, "")) for k in ("title", "path", "central_path"))
    scratch = bool(re.search(r"\b(?:scratch|disposable|acceptance|test)\b", labels, re.I))
    production = (bool(re.search(r"\bproduction\b|\bprod\b", labels, re.I))
                  or document.get("is_workshared") is True)
    extra = production_pattern()
    if extra is not None and extra.search(labels):
        production = True
    if not options.allow_existing_test_document and (not scratch or production):
        raise AcceptanceError("Default scope requires a disposable scratch/test project; existing projects need explicit owner authorization and --allow-existing-test-document.")
    stamp = context.get("addin") or {}
    if not isinstance(stamp, dict):
        raise AcceptanceError("Loaded add-in build stamp is malformed.")
    if not stamp.get("module_id") or not stamp.get("assembly_file_time_utc"):
        raise AcceptanceError("Loaded add-in has no verifiable module/file-time build stamp.")
    if context.get("queue", {}).get("running") or context.get("queue", {}).get("depth", 0):
        raise AcceptanceError("Revit queue is busy; finish existing work before acceptance.")
    return document


def read_script(options: argparse.Namespace, *, marker: str = "", seconds: float = 0) -> str:
    # Source intentionally uses Python 2 syntax for the Revit 2024 IronPython runtime.
    # The process id is pinned by the panel `instance` routing; a read-mode script may not touch System.Diagnostics.
    expected = json.dumps([options.expected_document, options.expected_guid.lower()], ensure_ascii=True)
    delay = "time.sleep(%r)\n" % seconds if seconds else ""
    return ("import json, time, collections\n"
            "from Autodesk.Revit.DB import FilteredElementCollector\n"
            f"expected = json.loads({json.dumps(expected)})\n"
            "def session_identity():\n"
            "    return [doc.Title, str(doc.CreationGUID).lower()]\n"
            "assert session_identity() == expected, 'Acceptance document mismatch'\n"
            + delay +
            "assert session_identity() == expected, 'Acceptance identity changed while running'\n"
            "__output__ = json.dumps({'identity': session_identity(), "
            "'elements': FilteredElementCollector(doc).WhereElementIsNotElementType().GetElementCount(), "
            "'warnings': len(list(doc.GetWarnings())), 'modifiable': doc.IsModifiable, "
            f"'marker': {json.dumps(marker)}, 'stdlib': list(collections.deque([1, 2]))}})\n")


def decode_read(result: dict[str, Any], options: argparse.Namespace) -> dict[str, Any]:
    if result.get("success") is not True or result.get("model_changes_in_read_mode") != 0 or result.get("mode") != "read":
        raise AcceptanceError("Read runner did not confirm success, read mode and zero model changes.")
    try:
        output = json.loads(result.get("output", ""))
    except (TypeError, json.JSONDecodeError):
        raise AcceptanceError("Read runner did not return the expected JSON evidence.") from None
    if not isinstance(output, dict):
        raise AcceptanceError("Read evidence must be an object.")
    if output.get("identity") != [options.expected_document, options.expected_guid.lower()]:
        raise AcceptanceError("Script evidence does not match the expected document/PID.")
    if output.get("modifiable") is not False or output.get("stdlib") != [1, 2]:
        raise AcceptanceError("Runtime/preflight evidence is incomplete or the document is modifiable.")
    for key in ("elements", "warnings"):
        if type(output.get(key)) is not int or output[key] < 0:
            raise AcceptanceError("Read script returned invalid model counts.")
    return output


def read_call(client: Any, options: argparse.Namespace, **kwargs: Any) -> dict[str, Any]:
    return client.call("revit_execute_python", {"mode": "read", "script": read_script(options, **kwargs)})


def case(report: dict[str, Any], name: str, status: str, detail: Any) -> None:
    report["checks"][name] = {"status": status, "detail": detail}


def collect_pending(client: Any, options: argparse.Namespace, result: dict[str, Any],
                    *, clock: Any, sleep: Any) -> tuple[dict[str, Any], int]:
    request_id = result.get("request_id")
    deadline, polls = clock() + options.max_wait, 0
    while result.get("status") == "running" and clock() < deadline:
        if not isinstance(request_id, str) or not request_id:
            raise AcceptanceError("Running result has no request_id; do not resubmit.")
        result = client.call("revit_get_result", {"request_id": request_id, "wait_s": min(25, options.poll_wait)})
        polls += 1
        if result.get("status") == "running":
            sleep(min(1, max(0, deadline - clock())))
    return result, polls


def run_checks(client: Any, options: argparse.Namespace, *, clock=time.monotonic,
               sleep=time.sleep, checkpoint: Any = None) -> dict[str, Any]:
    report = {"run_id": "acceptance-" + uuid.uuid4().hex, "date": datetime.now(timezone.utc).isoformat(),
              "expected": {"pid": options.pid, "title": options.expected_document, "guid": options.expected_guid},
              "scope": "read-only; no model writes or cleanup", "checks": {}}
    for name in ["context", "runtime", "T11", "T1"]:
        case(report, name, "NOT_RUN", "No live call made yet.")
    for number in [2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 13]:
        case(report, f"T{number}", "UNSUPPORTED", "Fixture/acceptance case is not implemented by this narrow runner.")
    try:
        if options.resume_request_id:
            # Context is queued behind a sleeping script, so only collect its retained result.
            # This route is read-only and never submits a script or repeats a write.
            result, polls = collect_pending(client, options,
                                           {"status": "running", "request_id": options.resume_request_id},
                                           clock=clock, sleep=sleep)
            detail = {"request_id": options.resume_request_id, "marker": options.expected_marker, "polls": polls}
            if result.get("status") == "running":
                case(report, "T1", "RUNNING", detail)
            else:
                finished = decode_read(result, options)
                if finished.get("marker") != options.expected_marker:
                    raise AcceptanceError("Retained result has the wrong acceptance marker.")
                context = client.call("revit_get_context", {})
                identity(context, options)
                case(report, "context", "PASS", context)
                replay = decode_read(client.call("revit_get_result", {"request_id": options.resume_request_id, "wait_s": 0}), options)
                detail.update(retained_replay_matches=replay == finished,
                              limit="Resume proves result retrieval, not sleep duration, initial counts or MCP-client-kill acceptance.")
                case(report, "T1", "PARTIAL" if replay == finished else "FAIL", detail)
            return report
        context = client.call("revit_get_context", {})
        identity(context, options)
        case(report, "context", "PASS", context)
        baseline = decode_read(read_call(client, options), options)
        case(report, "runtime", "PASS", baseline)
        # This would only open and roll back an empty transaction if the guard failed.
        challenge = "from Autodesk.Revit.DB import Transaction\nt = Transaction(doc, 'Acceptance refusal probe')\nt.Start()\nt.RollBack()"
        refused = False
        try:
            result = client.call("revit_execute_python", {"mode": "read", "script": challenge})
            refused = result.get("success") is False and REFUSAL in str(result.get("error", ""))
        except AcceptanceError as exc:
            refused = REFUSAL in str(exc)
        after = decode_read(read_call(client, options), options)
        unchanged = all(after[k] == baseline[k] for k in ("elements", "warnings"))
        mode = context.get("server", {}).get("approval_mode")
        status = "FAIL" if not refused or not unchanged else "PASS" if mode == "ask_first" else "PARTIAL"
        case(report, "T11", status, {"transaction_refused": refused, "counts_unchanged": unchanged,
                                     "approval_mode": mode, "no_plan_supplied": True,
                                     "limit": "Dev/Auto cannot prove the no-approval exemption; counts are not a full model diff."})
        if options.t1_seconds is not None:
            identity(client.call("revit_get_context", {}), options)
            marker = report["run_id"]
            result = read_call(client, options, marker=marker, seconds=options.t1_seconds)
            request_id = result.get("request_id") if result.get("status") == "running" else None
            # Save enough in the final evidence to resume, without ever rerunning the sleep.
            detail = {"request_id": request_id, "marker": marker, "seconds": options.t1_seconds,
                      "mcp_client_kill": "NOT_RUN: panel transport cannot establish MCP process-kill recovery."}
            case(report, "T1", "RUNNING" if request_id else "PARTIAL", detail)
            if request_id and checkpoint:
                checkpoint({**report, "run_id": report["run_id"] + "-pending"})
            result, polls = collect_pending(client, options, result, clock=clock, sleep=sleep)
            detail["polls"] = polls
            if result.get("status") == "running":
                case(report, "T1", "RUNNING", detail)
            else:
                finished = decode_read(result, options)
                if finished.get("marker") != marker:
                    raise AcceptanceError("Durable result has the wrong acceptance marker.")
                replay_ok = False
                if request_id:
                    replay = decode_read(client.call("revit_get_result", {"request_id": request_id, "wait_s": 0}), options)
                    replay_ok = replay == finished
                unchanged = all(finished[k] == baseline[k] for k in ("elements", "warnings"))
                detail.update(retained_replay_matches=replay_ok, counts_unchanged=unchanged)
                full_duration = options.t1_seconds is not None and options.t1_seconds >= 90
                status = "FAIL" if not unchanged or (request_id and not replay_ok) else "PARTIAL"
                # Only this subcase is proved; the section-8 client-kill subcase remains NOT_RUN.
                if request_id and replay_ok and full_duration:
                    detail["ninety_second_result_subcase"] = "PASS"
                case(report, "T1", status, detail)
    except AcceptanceError as exc:
        report["error"] = str(redact_data(str(exc)))
        case(report, "preflight_or_transport", "FAIL", report["error"])
    return report


# ---- Kit mode: read-only evidence for the cards in docs/live-verification-kit.md ----
# The guard below is the safety property: only these tools can be called, and none changes the model.
# revit_extract_snapshot only writes a snapshot file into the workspace.
KIT_READ_TOOLS = frozenset({
    "revit_health", "revit_get_context", "revit_extract_snapshot", "sheet_view_audit_run_audit",
    "schedule_diff_compare", "model_health_score", "param_completeness_heatmap", "policy_show",
    "list_pending_plans",
})
KIT_CARDS: tuple[dict[str, Any], ...] = (
    {"issue": 142, "title": "Snapshot has view and sheet records", "writes": False, "auto": True,
     "manual": "Placed and unplaced view check; run on the real project."},
    {"issue": 367, "title": "Snapshot holds schedule rows", "writes": False, "auto": True,
     "manual": "Normal, key and multi-category schedules; truncation flag; snapshot size."},
    {"issue": 371, "title": "Modal dialog reported by health", "writes": False, "auto": False,
     "manual": "Open a modal dialog in Revit and read /health."},
    {"issue": 372, "title": "revit_reconnect after a Revit restart", "writes": False, "auto": False,
     "manual": "Restart Revit and call revit_reconnect."},
    {"issue": 397, "title": "Ribbon Dev group follows Dev mode", "writes": False, "auto": False,
     "manual": "Look at the ribbon with Dev mode on and off."},
    {"issue": 211, "title": "revit_export_image as MCP image content", "writes": False, "auto": False,
     "manual": "Needs a multimodal MCP client."},
    {"issue": 147, "title": "Workshared model with links", "writes": False, "auto": True,
     "manual": "One block per PR (60, 64, 76, 77, 78, 81, 84); linked files."},
    {"issue": 281, "title": "Named-pipe transport ACL", "writes": False, "auto": False,
     "manual": "Pipe ACL and HTTP fallback in a live Windows session."},
    {"issue": 280, "title": "Live model cache from DocumentChanged", "writes": False, "auto": False,
     "manual": "Edit one element by hand and time the refresh."},
    {"issue": 218, "title": "1.6 release checks", "writes": True, "auto": True,
     "manual": "Launchers, doctor, panel Reject Selected, IDS, policy denial, clients, enforce mode."},
    {"issue": 150, "title": "Core tool profile in two MCP clients", "writes": True, "auto": False,
     "manual": "Needs two MCP clients."},
    {"issue": 148, "title": "qa_handover on before and after snapshots", "writes": True, "auto": False,
     "manual": "Needs one approved door-Mark plan."},
    {"issue": 149, "title": "Plan expiry and document binding", "writes": True, "auto": False,
     "manual": "Two documents, expiry wait, unreachable context."},
    {"issue": 293, "title": "Rolled-back preview in the panel", "writes": True, "auto": False,
     "manual": "Draft a plan and read the preview in the panel."},
)
KIT_FORBIDDEN = ("plan_actions", "execute_plan", "approve_plan", "reject_plan", "rollback_plan",
                 "recover", "revit_execute_python")
SNAPSHOT_BUDGET_SECONDS = 20.0


class KitGuard:
    """Refuse any tool outside KIT_READ_TOOLS and remember every call made."""

    def __init__(self, client: Any):
        self.client, self.calls = client, []

    def call(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if tool not in KIT_READ_TOOLS or any(word in tool for word in KIT_FORBIDDEN):
            raise AcceptanceError(f"Kit mode is read-only; refused tool {tool}.")
        self.calls.append(tool)
        return self.client.call(tool, arguments)


def ascii_safe(text: str) -> str:
    return text.encode("ascii", "backslashreplace").decode("ascii")


def title_hash(title: Any) -> str:
    return hashlib.sha256(str(title or "").encode("utf-8")).hexdigest()[:16]


def dig(value: Any, key: str, depth: int = 0) -> Any:
    """First value under `key`, searching nested dicts; tool results are sometimes wrapped."""
    if depth > 4 or not isinstance(value, dict):
        return None
    if key in value:
        return value[key]
    for inner in value.values():
        found = dig(inner, key, depth + 1)
        if found is not None:
            return found
    return None


def kit_context_fields(context: dict[str, Any]) -> dict[str, Any]:
    def part(name: str) -> dict[str, Any]:
        return context[name] if isinstance(context.get(name), dict) else {}

    document = part("document")
    return {"revit_version": part("revit").get("version"), "addin_version": part("addin").get("version"),
            "server_version": part("server").get("version"), "approval_mode": part("server").get("approval_mode"),
            "document": {"title_sha256_16": title_hash(document.get("title")),
                         "is_workshared": document.get("is_workshared"),
                         "is_family": document.get("is_family")}}


def kit_card(issue: int, status: str, evidence: Any) -> dict[str, Any]:
    meta = next(c for c in KIT_CARDS if c["issue"] == issue)
    return {"issue": issue, "title": meta["title"], "status": status, "writes": meta["writes"],
            "evidence": evidence, "manual_remaining": meta["manual"]}


def _auto(issue: int, check: Any) -> dict[str, Any]:
    try:
        ok, evidence = check()
    except AcceptanceError as exc:
        return kit_card(issue, "AUTO-FAIL", {"error": str(redact_data(str(exc)))})
    return kit_card(issue, "AUTO-PASS" if ok else "AUTO-FAIL", evidence)


def run_kit(client: Any, options: argparse.Namespace, *, clock=time.monotonic) -> dict[str, Any]:
    guard = KitGuard(client)
    now = datetime.now(timezone.utc)
    report: dict[str, Any] = {
        "kit_version": 1, "run_id": "kit-" + now.strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6],
        "timestamp": now.isoformat(), "pid": options.pid,
        "scope": "read-only; calls only " + ", ".join(sorted(KIT_READ_TOOLS)), "cards": {}}
    state: dict[str, Any] = {}
    try:
        health = guard.call("revit_health", {})
        context = guard.call("revit_get_context", {})
        report.update(kit_context_fields(context))
        report["health_ok"] = bool(health) and health.get("ok", True) is not False
        if context.get("mock") or context.get("ok") is not True:
            raise AcceptanceError("Hub is in mock mode or the Revit context is unavailable.")
        state["context"] = context
    except AcceptanceError as exc:
        report["prerequisite_error"] = str(redact_data(str(exc)))
    if "context" in state:
        try:
            started = clock()
            extracted = guard.call("revit_extract_snapshot", {})
            state["snapshot_seconds"] = round(clock() - started, 2)
            state["snapshot_id"] = dig(extracted, "snapshot_id")
            if not isinstance(state["snapshot_id"], str) or not state["snapshot_id"]:
                state.pop("snapshot_id")
                raise AcceptanceError("Snapshot result has no snapshot_id.")
        except AcceptanceError as exc:
            report["snapshot_error"] = str(redact_data(str(exc)))

    def need_snapshot() -> str:
        if "prerequisite_error" in report:
            raise AcceptanceError("Prerequisite failed: " + report["prerequisite_error"])
        if "snapshot_id" not in state:
            raise AcceptanceError("Prerequisite failed: " + report.get("snapshot_error", "no snapshot"))
        return state["snapshot_id"]

    def card_142() -> tuple[bool, Any]:
        audit = guard.call("sheet_view_audit_run_audit", {"snapshot_id": need_snapshot()})
        headline, captured, status = dig(audit, "headline"), dig(audit, "views_captured"), dig(audit, "status")
        fast = state["snapshot_seconds"] <= SNAPSHOT_BUDGET_SECONDS
        ok = headline is None and captured is not False and status != "no_sheet_view_data" and fast
        return ok, {"audit_status": status, "headline": headline, "views_captured": captured,
                    "rated": dig(audit, "rated"), "snapshot_seconds": state["snapshot_seconds"],
                    "budget_seconds": SNAPSHOT_BUDGET_SECONDS}

    def card_367() -> tuple[bool, Any]:
        sid = need_snapshot()
        diff = guard.call("schedule_diff_compare", {"older_snapshot_id": sid, "newer_snapshot_id": sid,
                                                    "max_items": 5})
        schedules = dig(diff, "schedules")
        status = schedules.get("status") if isinstance(schedules, dict) else None
        return status in ("compared", "partial"), {"schedules_status": status, "diff_status": dig(diff, "status")}

    def card_147() -> tuple[bool, Any]:
        if "context" not in state:
            raise AcceptanceError("Prerequisite failed: " + report.get("prerequisite_error", "no context"))
        workshared = (state["context"].get("document") or {}).get("is_workshared")
        return workshared is True, {"is_workshared": workshared}

    def card_218() -> tuple[bool, Any]:
        sid = need_snapshot()
        score = dig(guard.call("model_health_score", {"snapshot_id": sid, "include_trend": False}), "score")
        rows = dig(guard.call("param_completeness_heatmap", {"snapshot_id": sid}), "rows")
        policy = guard.call("policy_show", {})
        pending = guard.call("list_pending_plans", {"include_expired": True})
        ok = (isinstance(score, (int, float)) and not isinstance(score, bool) and 0 <= score <= 100
              and isinstance(rows, list) and len(rows) > 0)
        return ok, {"health_score": score, "heatmap_rows": len(rows) if isinstance(rows, list) else None,
                    "policy_hash": dig(policy, "hash") or dig(policy, "policy_hash"),
                    "pending_plans_listed": isinstance(pending, dict)}

    checks = {142: card_142, 367: card_367, 147: card_147, 218: card_218}
    for meta in KIT_CARDS:
        issue = meta["issue"]
        report["cards"][str(issue)] = (_auto(issue, checks[issue]) if issue in checks
                                       else kit_card(issue, "MANUAL", "Not automated; follow the card."))
    report["calls"] = list(guard.calls)
    return report


def kit_markdown(report: dict[str, Any]) -> str:
    doc = report.get("document", {})
    lines = ["# Live verification kit report", "",
             f"- Run: {report['run_id']}", f"- Time (UTC): {report['timestamp']}",
             f"- Revit: {report.get('revit_version')}", f"- Add-in: {report.get('addin_version')}",
             f"- Server: {report.get('server_version')}",
             f"- Document title hash: {doc.get('title_sha256_16')} (workshared: {doc.get('is_workshared')})",
             f"- Scope: {report['scope']}", ""]
    if report.get("prerequisite_error"):
        lines += [f"Prerequisite failed: {report['prerequisite_error']}", ""]
    lines += ["| Card | Status | Access | Evidence | Still manual |", "|---|---|---|---|---|"]
    for key, card in report["cards"].items():
        evidence = json.dumps(bounded(card["evidence"]), ensure_ascii=True).replace("|", "/")
        lines.append(f"| #{key} {card['title']} | {card['status']} | {'WRITE' if card['writes'] else 'read'} "
                     f"| {evidence[:300]} | {card['manual_remaining']} |")
    lines += ["", "AUTO-PASS covers only the automated part. Do the manual steps in docs/live-verification-kit.md.", ""]
    return "\n".join(lines)


def write_kit_report(report: dict[str, Any], directory: Path | None = None) -> tuple[Path, Path]:
    directory = (directory or KIT_DIR).resolve()
    if not directory.is_relative_to((ROOT / "artifacts").resolve()):
        raise AcceptanceError("Kit reports must stay inside the ignored artifacts directory.")
    directory.mkdir(parents=True, exist_ok=True)
    safe = bounded(redact_data(report))
    payload = json.dumps(safe, indent=2, ensure_ascii=True)
    if len(payload.encode("utf-8")) > 200 * 1024:
        raise AcceptanceError("Kit report exceeds 200 KiB.")
    jpath, mpath = directory / (report["run_id"] + ".json"), directory / (report["run_id"] + ".md")
    with jpath.open("x", encoding="ascii") as stream:
        stream.write(payload + "\n")
    with mpath.open("x", encoding="ascii") as stream:
        stream.write(ascii_safe(kit_markdown(safe)))
    return jpath, mpath


def kit_summary(report: dict[str, Any], jpath: Path, mpath: Path) -> str:
    lines = [f"KIT report: {jpath.relative_to(ROOT).as_posix()}", f"KIT report: {mpath.relative_to(ROOT).as_posix()}"]
    lines += [f"card #{key} {card['status']}" for key, card in report["cards"].items()]
    return ascii_safe("\n".join(lines))


def main_kit(options: argparse.Namespace) -> int:
    if not options.run:
        print(ascii_safe(json.dumps({"status": "NOT_RUN", "mode": "kit", "pid": options.pid,
                                      "tools": sorted(KIT_READ_TOOLS), "cards": [c["issue"] for c in KIT_CARDS],
                                      "scope": "Read-only. No token read and no live calls without --run."}, indent=2)))
        return 0
    try:
        token = read_token()
        if not token:
            raise AcceptanceError("No panel token exists; start the authenticated panel first.")
        report = run_kit(PanelClient(options.hub, options.pid, token), options)
        jpath, mpath = write_kit_report(report)
        print(kit_summary(report, jpath, mpath))
        failed = "prerequisite_error" in report or any(c["status"] == "AUTO-FAIL" for c in report["cards"].values())
        return 1 if failed else 0
    except (AcceptanceError, OSError, ValueError) as exc:
        print(ascii_safe(json.dumps({"status": "FAIL", "error": redact_data(str(exc))})))
        return 1


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--pid", type=int, required=True)
    p.add_argument("--expected-document")
    p.add_argument("--expected-guid", help="Document CreationGUID, not its path.")
    p.add_argument("--hub", default="http://127.0.0.1:8787")
    p.add_argument("--run", action="store_true", help="Make live calls; otherwise emit only a plan.")
    p.add_argument("--allow-existing-test-document", action="store_true", help="Owner explicitly designated this exact existing document for tests. Does not permit model writes.")
    p.add_argument("--t1-seconds", nargs="?", const=90.0, type=float, help="Run durable-result sleep; default 90 seconds. UI is blocked during this read script.")
    p.add_argument("--max-wait", type=float, default=120)
    p.add_argument("--poll-wait", type=float, default=5, help="Per revit_get_result wait, 0 to 25 seconds.")
    p.add_argument("--resume-request-id", help="Collect an existing request; never resubmit the script.")
    p.add_argument("--expected-marker", help="Marker saved in the earlier T1 evidence; required to resume.")
    p.add_argument("--kit", action="store_true", help="Read-only kit mode for docs/live-verification-kit.md. Needs only --pid; with --run it writes a JSON and Markdown report under artifacts/revit-kit.")
    return p


def main(argv: list[str] | None = None) -> int:
    p = parser()
    options = p.parse_args(argv)
    if options.kit:
        if (options.t1_seconds is not None or options.resume_request_id or options.allow_existing_test_document
                or options.expected_document or options.expected_guid):
            p.error("--kit takes only --pid, --hub and --run; it is read-only and records no document title.")
        if options.pid <= 0:
            p.error("Require a positive PID.")
        return main_kit(options)
    if not options.expected_document or not options.expected_guid:
        p.error("--expected-document and --expected-guid are required unless --kit is used.")
    try:
        options.expected_guid = str(uuid.UUID(options.expected_guid))
    except ValueError:
        p.error("expected-guid must be a valid Document CreationGUID.")
    if options.pid <= 0 or not options.expected_document.strip():
        p.error("Require positive PID, an exact document title and CreationGUID.")
    if not all(math.isfinite(v) for v in [options.max_wait, options.poll_wait]):
        p.error("Wait values must be finite.")
    if not (0 <= options.poll_wait <= 25 and 0 < options.max_wait <= 600):
        p.error("poll-wait must be 0..25; max-wait must be >0 and <=600.")
    if options.t1_seconds is not None and (not math.isfinite(options.t1_seconds) or not 0 < options.t1_seconds <= 120):
        p.error("t1-seconds must be >0 and <=120; under 90 is a smoke probe only.")
    if options.resume_request_id and (options.t1_seconds is not None or not options.expected_marker):
        p.error("Resume needs expected-marker and cannot submit t1-seconds again.")
    if not options.run:
        print(json.dumps({"status": "NOT_RUN", "pid": options.pid,
                          "expected_document": options.expected_document, "expected_guid": options.expected_guid,
                          "checks": ["context", "runtime", "T11"] + (["T1"] if options.t1_seconds or options.resume_request_id else []),
                          "scope": "Read-only. T2-T10/T12/T13 unsupported. No token read and no live calls."}, indent=2))
        return 0
    try:
        token = read_token()
        if not token:
            raise AcceptanceError("No panel token exists; start the authenticated panel first.")
        client = PanelClient(options.hub, options.pid, token)
        def checkpoint(report: dict[str, Any]) -> None:
            path = write_evidence(report)
            print(json.dumps({"pending_evidence": str(path.relative_to(ROOT))}))

        report = run_checks(client, options, checkpoint=checkpoint)
        evidence = write_evidence(report)
        print(json.dumps({"evidence": str(evidence.relative_to(ROOT)),
                          "checks": {k: v["status"] for k, v in report["checks"].items()}}, indent=2))
        return 1 if any(c["status"] == "FAIL" for c in report["checks"].values()) else 0
    except (AcceptanceError, OSError, ValueError) as exc:
        print(json.dumps({"status": "FAIL", "error": redact_data(str(exc))}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
