"""Local tool-usage counts (issue #273): counting, privacy, opt-out, atomic writes,
the `learned` profile with its daily fallback, context_report and search tie-break."""
from __future__ import annotations

import asyncio
import json
from datetime import date, timedelta

import pytest

from revit_mcp_server import mcp_server, usage_counts
from revit_mcp_server.errors import BridgeError
from revit_mcp_server.registry_factory import build_registry
from revit_mcp_server.security.approval import HUMAN_ONLY_TOOLS
from revit_mcp_server.security.workspace import WorkspaceMonitor
from revit_mcp_server.tool_profiles import (
    ALWAYS_LOADED_TOOLS, CORE_TOOLS, DAILY_EXCLUDE, LEARNED_MIN_CALLS, load_tool_profile,
)
from revit_mcp_server.usage_counts import UsageCounter, top_tools, usage_file

TODAY = date(2026, 11, 24)
APPROVAL_TOOLS = ("plan_actions", "execute_plan", "list_pending_plans")


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def counter(tmp_path, clock=None, interval=60.0, enabled=True):
    return UsageCounter(usage_file(tmp_path), enabled=enabled, flush_interval=interval,
                        clock=clock or Clock(), today=lambda: TODAY)


def data(**calls_by_tool):
    """{tool: calls} on TODAY, as a usage file dict."""
    return {"version": 1, "tools": {n: {"days": {TODAY.isoformat(): c}, "last_used": TODAY.isoformat()}
                                    for n, c in calls_by_tool.items()}}


# ---- counting ------------------------------------------------------------- #

def test_counts_per_tool_and_day_after_flush(tmp_path):
    c = counter(tmp_path)
    for _ in range(3):
        c.record("revit_list_walls")
    c.record("snapshot_take")
    assert not usage_file(tmp_path).exists()  # rate limited: nothing written yet
    c.flush()
    saved = json.loads(usage_file(tmp_path).read_text(encoding="utf-8"))
    assert saved["tools"]["revit_list_walls"] == {"days": {"2026-11-24": 3}, "last_used": "2026-11-24"}
    assert saved["tools"]["snapshot_take"]["days"] == {"2026-11-24": 1}
    assert [r["name"] for r in top_tools(saved, today=TODAY)] == ["revit_list_walls", "snapshot_take"]


def test_flush_is_rate_limited(tmp_path):
    clock = Clock()
    c = counter(tmp_path, clock=clock, interval=60)
    c.record("a_tool")
    clock.now = 59
    c.record("a_tool")
    assert not usage_file(tmp_path).exists()
    clock.now = 60
    c.record("a_tool")
    assert usage_file(tmp_path).exists()
    assert usage_counts.load(usage_file(tmp_path))["tools"]["a_tool"]["days"]["2026-11-24"] == 3


def test_flush_adds_to_existing_file_from_another_process(tmp_path):
    first, second = counter(tmp_path), counter(tmp_path)
    first.record("a_tool")
    second.record("a_tool")
    second.record("b_tool")
    first.flush()
    second.flush()
    tools = usage_counts.load(usage_file(tmp_path))["tools"]
    assert tools["a_tool"]["days"]["2026-11-24"] == 2 and tools["b_tool"]["days"]["2026-11-24"] == 1


def test_window_and_pruning(tmp_path):
    old = (TODAY - timedelta(days=40)).isoformat()
    ancient = (TODAY - timedelta(days=200)).isoformat()
    stored = {"tools": {"a_tool": {"days": {old: 100, TODAY.isoformat(): 1}},
                        "b_tool": {"days": {ancient: 5}}}}
    merged = usage_counts.merge(stored, {}, TODAY)
    assert "b_tool" not in merged["tools"]  # older than KEEP_DAYS is dropped
    assert top_tools(merged, today=TODAY) == [{"name": "a_tool", "calls": 1, "last_used": "2026-11-24"}]
    assert top_tools(merged, today=TODAY, days=60)[0]["calls"] == 101


def test_corrupt_or_odd_file_reads_as_empty_entries(tmp_path):
    path = usage_file(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")
    assert usage_counts.load(path)["tools"] == {}
    path.write_text(json.dumps({"tools": {"bad name/..": {"days": {"2026-11-24": 3}},
                                          "ok_tool": {"days": {"nope": 2, "2026-11-24": -1, "2026-11-23": 2}}}}),
                    encoding="utf-8")
    assert usage_counts.load(path)["tools"] == {"ok_tool": {"days": {"2026-11-23": 2}, "last_used": "2026-11-23"}}


# ---- privacy -------------------------------------------------------------- #

def test_only_names_counts_and_days_are_stored(tmp_path, monkeypatch):
    registry, approval, jobs, *_ = build_registry(WorkspaceMonitor([tmp_path]))
    registry.freeze_tool_profile(load_tool_profile({"MCP_REVIT_TOOL_PROFILE": "full"}))
    registry.usage_counter = counter(tmp_path)
    monkeypatch.setattr(mcp_server, "registry", registry)
    monkeypatch.setattr(mcp_server, "approval_provider", approval)
    monkeypatch.setattr(mcp_server, "job_manager", jobs)
    secret = "SECRET-PROJECT-Wall-Level-3-jdoe"
    asyncio.run(mcp_server.call_tool("search_tools", {"query": secret}))
    asyncio.run(mcp_server.call_tool("not_a_tool_" + "x", {"query": secret}))
    asyncio.run(mcp_server.call_tool("approve_plan", {"plan_id": secret}))  # human-only: refused, not counted
    registry.usage_counter.flush()
    text = usage_file(tmp_path).read_text(encoding="utf-8")
    assert secret not in text and "jdoe" not in text
    saved = json.loads(text)
    assert set(saved) == {"version", "tools"}
    assert list(saved["tools"]) == ["search_tools"]  # unknown and human-only names are not counted
    assert set(saved["tools"]["search_tools"]) == {"days", "last_used"}


def test_malformed_names_are_ignored(tmp_path):
    c = counter(tmp_path)
    for name in ("../etc/passwd", "a b", "", "x" * 200, None, 5):
        c.record(name)
    c.flush()
    assert not usage_file(tmp_path).exists()


def test_usage_file_stays_in_workspace(tmp_path):
    path = usage_file(tmp_path)
    assert path.parent.name == "usage" and path.name == "tool-usage.json"
    assert path.is_relative_to(tmp_path.resolve())


# ---- opt-out -------------------------------------------------------------- #

@pytest.mark.parametrize("value", ["off", "0", "false", "OFF", "no"])
def test_opt_out_writes_nothing(tmp_path, value):
    env = {usage_counts.ENV_VAR: value}
    assert usage_counts.counts_enabled(env) is False
    c = usage_counts.start_counter(tmp_path, env)
    c.record("a_tool")
    c.flush()
    assert not c.enabled
    assert not (tmp_path / "usage").exists()


def test_counting_is_off_by_default_and_unknown_values_are_refused():
    assert usage_counts.counts_enabled({}) is False
    assert usage_counts.counts_enabled({usage_counts.ENV_VAR: "on"}) is True
    with pytest.raises(ValueError, match="on or off"):
        usage_counts.counts_enabled({usage_counts.ENV_VAR: "maybe"})


# ---- atomic write --------------------------------------------------------- #

def test_failed_replace_keeps_old_file_and_leaves_no_temp(tmp_path, monkeypatch):
    c = counter(tmp_path)
    c.record("a_tool")
    c.flush()
    path = usage_file(tmp_path)
    before = path.read_text(encoding="utf-8")

    def boom(src, dst):
        raise BridgeError("locked")

    monkeypatch.setattr("revit_mcp_server.security.approval.replace_with_retry", boom)
    c.record("b_tool")
    c.flush()  # logged, not raised
    assert path.read_text(encoding="utf-8") == before
    assert [p.name for p in path.parent.iterdir()] == ["tool-usage.json"]


def test_failed_flush_keeps_counts_for_the_next_flush(tmp_path, monkeypatch):
    c = counter(tmp_path)
    c.record("a_tool")
    c.record("a_tool")
    real = usage_counts.write_atomic
    monkeypatch.setattr(usage_counts, "write_atomic", lambda path, data: (_ for _ in ()).throw(OSError("locked")))
    c.flush()  # logged, not raised
    assert not usage_file(tmp_path).exists()
    c.record("a_tool")
    monkeypatch.setattr(usage_counts, "write_atomic", real)
    c.flush()
    assert usage_counts.load(usage_file(tmp_path))["tools"]["a_tool"]["days"]["2026-11-24"] == 3
    assert not (usage_file(tmp_path).parent / ".tool-usage.json.lock").exists()


def test_flush_waits_for_lock_and_keeps_counts_on_timeout(tmp_path):
    c = UsageCounter(usage_file(tmp_path), flush_interval=60, clock=Clock(), today=lambda: TODAY,
                     lock_timeout=0.05)
    lock = usage_file(tmp_path).parent / ".tool-usage.json.lock"
    lock.parent.mkdir(parents=True)
    lock.write_text("1", encoding="utf-8")  # another process is flushing
    c.record("a_tool")
    c.flush()
    assert not usage_file(tmp_path).exists() and lock.exists()  # not written, lock left alone
    lock.unlink()
    c.flush()
    assert usage_counts.load(usage_file(tmp_path))["tools"]["a_tool"]["days"]["2026-11-24"] == 1
    assert not lock.exists()


def test_stale_lock_is_removed(tmp_path):
    import os
    import time as _time
    lock = usage_file(tmp_path).parent / ".tool-usage.json.lock"
    lock.parent.mkdir(parents=True)
    lock.write_text("1", encoding="utf-8")
    old = _time.time() - usage_counts.STALE_LOCK_SECONDS - 5
    os.utime(lock, (old, old))
    c = counter(tmp_path)
    c.record("a_tool")
    c.flush()
    assert usage_counts.load(usage_file(tmp_path))["tools"]["a_tool"]["days"]["2026-11-24"] == 1
    assert not lock.exists()


def test_concurrent_flushes_keep_all_counts(tmp_path):
    import threading
    counters = [counter(tmp_path) for _ in range(6)]
    for c in counters:
        for _ in range(5):
            c.record("a_tool")
    barrier = threading.Barrier(len(counters))

    def run(c):
        barrier.wait()
        c.flush()

    threads = [threading.Thread(target=run, args=(c,)) for c in counters]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert usage_counts.load(usage_file(tmp_path))["tools"]["a_tool"]["days"]["2026-11-24"] == 30


def test_lock_contention_reported_as_permission_error_is_waited_out(tmp_path, monkeypatch):
    """Windows raises PermissionError (not FileExistsError) on O_EXCL while the holder deletes
    the lock file; that is contention, not a failed flush, so no count may be dropped."""
    real_open = usage_counts.os.open
    calls = {"n": 0}

    def flaky_open(path, flags, *args, **kwargs):
        if str(path).endswith(".lock") and calls["n"] < 3:
            calls["n"] += 1
            raise PermissionError(13, "Permission denied", str(path))
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(usage_counts.os, "open", flaky_open)
    c = counter(tmp_path)
    c.record("a_tool")
    c.flush()
    assert calls["n"] == 3
    assert c._pending == {}
    assert usage_counts.load(usage_file(tmp_path))["tools"]["a_tool"]["days"]["2026-11-24"] == 1


def test_many_concurrent_flush_rounds_lose_nothing(tmp_path):
    import threading
    rounds, workers, per = 8, 8, 3
    counters = [counter(tmp_path) for _ in range(workers)]
    for _ in range(rounds):
        for c in counters:
            for _ in range(per):
                c.record("a_tool")
        barrier = threading.Barrier(workers)

        def run(c):
            barrier.wait()
            c.flush()

        threads = [threading.Thread(target=run, args=(c,)) for c in counters]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    assert all(not c._pending for c in counters)
    got = usage_counts.load(usage_file(tmp_path))["tools"]["a_tool"]["days"]["2026-11-24"]
    assert got == rounds * workers * per


# ---- learned profile ------------------------------------------------------ #

def test_learned_profile_lists_core_always_loaded_and_top_tools():
    usage = data(rhino_list_layers=40, speckle_send=20, revit_create_wall=10)
    profile = load_tool_profile({"MCP_REVIT_TOOL_PROFILE": "learned", "MCP_REVIT_LEARNED_TOP_N": "2"},
                                usage_data=usage, today=TODAY)
    assert profile.name == "learned"
    assert set(CORE_TOOLS) | set(ALWAYS_LOADED_TOOLS) <= set(profile.tools)
    assert "rhino_list_layers" in profile.tools and "speckle_send" in profile.tools
    assert "revit_create_wall" not in profile.tools  # outside the top 2
    assert profile.exclude == ()  # learned does not apply daily's exclusions to used tools
    assert "70 calls" in profile.detail
    for name in APPROVAL_TOOLS + ("search_tools", "context_report"):
        provider = "approval" if name in APPROVAL_TOOLS else "tool_search"
        assert profile.allows(provider, None, name)


def test_learned_falls_back_to_daily_with_too_little_data():
    usage = data(revit_list_walls=LEARNED_MIN_CALLS - 1)
    profile = load_tool_profile({"MCP_REVIT_TOOL_PROFILE": "learned"}, usage_data=usage, today=TODAY)
    assert profile.name == "daily" and profile.tools is None and profile.exclude == DAILY_EXCLUDE
    assert "fell back to daily" in profile.detail and str(LEARNED_MIN_CALLS - 1) in profile.detail


def test_learned_ignores_calls_older_than_window():
    old = (TODAY - timedelta(days=31)).isoformat()
    usage = {"tools": {"revit_list_walls": {"days": {old: 500}}}}
    assert load_tool_profile({"MCP_REVIT_TOOL_PROFILE": "learned"}, usage_data=usage, today=TODAY).name == "daily"


def test_learned_reads_workspace_file_and_respects_opt_out(tmp_path):
    path = usage_file(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(data(revit_list_walls=80)), encoding="utf-8")
    env = {"MCP_REVIT_TOOL_PROFILE": "learned", "MCP_REVIT_WORKSPACE_DIR": str(tmp_path), usage_counts.ENV_VAR: "on"}
    assert load_tool_profile(env, today=TODAY).name == "learned"
    off = load_tool_profile({**env, usage_counts.ENV_VAR: "off"}, today=TODAY)
    assert off.name == "daily" and "usage counts are off" in off.detail


@pytest.mark.parametrize("value", ["0", "201", "ten", "-1"])
def test_learned_top_n_is_validated(value):
    with pytest.raises(ValueError, match="MCP_REVIT_LEARNED_TOP_N"):
        load_tool_profile({"MCP_REVIT_TOOL_PROFILE": "learned", "MCP_REVIT_LEARNED_TOP_N": value},
                          usage_data=data(a_tool=100), today=TODAY)


def test_learned_profile_file_cannot_exclude_approval(tmp_path):
    f = tmp_path / "p.json"
    f.write_text(json.dumps({"exclude": ["approval"]}), encoding="utf-8")
    with pytest.raises(ValueError, match="approval tools cannot be excluded"):
        load_tool_profile({"MCP_REVIT_TOOL_PROFILE": "learned", "MCP_REVIT_TOOL_PROFILE_FILE": str(f)},
                          usage_data=data(a_tool=100), today=TODAY)


def test_learned_list_is_frozen_for_the_session(tmp_path):
    registry, *_ = build_registry(WorkspaceMonitor([tmp_path]))
    profile = load_tool_profile({"MCP_REVIT_TOOL_PROFILE": "learned"},
                                usage_data=data(revit_list_walls=60), today=TODAY)
    registry.freeze_tool_profile(profile)
    registry.usage_counter = counter(tmp_path)
    before = [t.name for _, t in registry.get_tools_with_providers()]
    hidden = next(t.name for p in registry.get_all_providers() for t in p.get_capabilities()
                  if t.name not in before and t.name not in HUMAN_ONLY_TOOLS)
    for _ in range(200):
        registry.usage_counter.record(hidden)
    registry.usage_counter.flush()
    assert [t.name for _, t in registry.get_tools_with_providers()] == before
    assert not registry.is_tool_visible(hidden)
    with pytest.raises(RuntimeError, match="static"):
        registry.freeze_tool_profile(load_tool_profile({"MCP_REVIT_TOOL_PROFILE": "full"}))
    for name in APPROVAL_TOOLS + ALWAYS_LOADED_TOOLS:
        assert name in before


# ---- context_report and search_tools -------------------------------------- #

def _registry(tmp_path, profile="full", usage=None):
    registry, *_ = build_registry(WorkspaceMonitor([tmp_path]))
    registry.freeze_tool_profile(load_tool_profile({"MCP_REVIT_TOOL_PROFILE": profile}))
    c = UsageCounter(usage_file(tmp_path), flush_interval=1e9)  # real today: data relative to it
    if usage:
        for name, calls in usage.items():
            for _ in range(calls):
                c.record(name)
    registry.usage_counter = c
    return registry


def _run(registry, name, args):
    provider = registry.lookup_tool_provider(name)
    return asyncio.run(provider.execute_tool(name, args))


def test_context_report_shows_top_tools_and_suggests_learned(tmp_path):
    registry = _registry(tmp_path, "full", {"revit_list_walls": 40, "snapshot_take": 15})
    out = _run(registry, "context_report", {})
    usage = out["usage"]
    assert usage["counting"] is True and usage["calls"] == 55
    assert [r["name"] for r in usage["top_tools"]] == ["revit_list_walls", "snapshot_take"]
    assert usage["learned_listed_tools"] < out["listed_tools"] * 0.75
    assert "MCP_REVIT_TOOL_PROFILE=learned" in out["tips"][0]
    json.dumps(out)


def test_context_report_does_not_suggest_learned_without_enough_data(tmp_path):
    out = _run(_registry(tmp_path, "full", {"revit_list_walls": 3}), "context_report", {})
    assert out["usage"]["learned_listed_tools"] is None and "needs" in out["usage"]["note"]
    assert not any("learned" in tip for tip in out["tips"])


def test_context_report_when_counting_is_off(tmp_path):
    registry = _registry(tmp_path)
    registry.usage_counter = UsageCounter(None, enabled=False)
    out = _run(registry, "context_report", {})
    assert out["usage"]["counting"] is False and usage_counts.ENV_VAR in out["usage"]["note"]


def test_search_ties_are_broken_by_usage(tmp_path):
    from revit_mcp_server.providers.tool_search import _score
    from revit_mcp_server.tool_metadata import enrich_tool

    registry = _registry(tmp_path / "plain")
    by_score = {}
    for provider in registry.get_all_providers():
        for t in provider.get_capabilities():
            score = _score(["snapshot"], enrich_tool(provider.get_identity(), t))
            if score > 0 and t.name not in HUMAN_ONLY_TOOLS:
                by_score.setdefault(score, []).append(t.name)
    tied = sorted(next(names for names in by_score.values() if len(names) >= 2))
    first, last = tied[0], tied[-1]
    args = {"query": "snapshot", "limit": 25, "include_schema": False}

    plain = [t["name"] for t in _run(registry, "search_tools", args)["tools"]]
    assert plain.index(first) < plain.index(last)  # no usage: name order
    used = _registry(tmp_path / "used", usage={last: 3})
    ranked = [t["name"] for t in _run(used, "search_tools", args)["tools"]]
    assert ranked.index(last) < ranked.index(first)


# ---- CLI ------------------------------------------------------------------ #

def test_cli_show_and_reset(tmp_path, capsys):
    c = counter(tmp_path)
    c.record("revit_list_walls")
    c.flush()
    # The CLI uses the real date; give it data dated today.
    path = usage_file(tmp_path)
    path.write_text(json.dumps(data(revit_list_walls=2)).replace(TODAY.isoformat(),
                    usage_counts._today().isoformat()), encoding="utf-8")
    assert usage_counts.main(["show", "--json"], workspace=tmp_path) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["tools"][0]["name"] == "revit_list_walls" and shown["tools"][0]["calls"] == 2
    assert usage_counts.main(["show"], workspace=tmp_path) == 0
    assert "revit_list_walls" in capsys.readouterr().out
    assert usage_counts.main(["reset"], workspace=tmp_path) == 0
    assert not path.exists()
    assert usage_counts.main(["show"], workspace=tmp_path) == 0
    assert "No tool calls counted" in capsys.readouterr().out
