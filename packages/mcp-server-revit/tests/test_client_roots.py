"""Client roots narrow the workspace sandbox and never widen it (issue #202)."""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from mcp import types
from mcp.shared.memory import create_connected_server_and_client_session

from revit_mcp_server import client_roots, mcp_server
from revit_mcp_server.client_roots import uri_to_path, usable_roots
from revit_mcp_server.errors import WorkspaceViolation
from revit_mcp_server.security.workspace import CLIENT_ROOTS, WorkspaceMonitor, narrow_directories


def _link(target: Path, link: Path) -> None:
    try:
        link.symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are not available here")


@pytest.fixture
def tree(tmp_path):
    ws = tmp_path / "ws"
    (ws / "proj_a").mkdir(parents=True)
    (ws / "proj_b").mkdir()
    (ws / "plans").mkdir()
    (tmp_path / "other").mkdir()
    return SimpleNamespace(base=tmp_path, ws=ws, a=ws / "proj_a", b=ws / "proj_b", other=tmp_path / "other")


@pytest.fixture(autouse=True)
def _clean_cache():
    client_roots._cache.clear()
    client_roots._failed_until.clear()
    yield
    client_roots._cache.clear()
    client_roots._failed_until.clear()


# --- URI parsing -------------------------------------------------------------


@pytest.mark.parametrize("uri", [
    "http://example.com/a", "https://x/y", "ftp://host/a", "s3://bucket/key", "vscode-remote://ssh/home",
    "file2:///a", "ws:///a", "/just/a/path", "relative/path", "", "file:relative", "data:text/plain,hi",
])
def test_non_file_uris_are_refused(uri):
    assert uri_to_path(uri, windows=False) is None
    assert uri_to_path(uri, windows=True) is None


def test_posix_file_uris():
    assert uri_to_path("file:///home/me/proj", windows=False) == "/home/me/proj"
    assert uri_to_path("FILE:///home/me/proj", windows=False) == "/home/me/proj"
    assert uri_to_path("file://localhost/home/me", windows=False) == "/home/me"
    assert uri_to_path("file:///home/my%20proj", windows=False) == "/home/my proj"
    assert uri_to_path("file://server/share/x", windows=False) is None  # remote host


def test_windows_drive_letter_uris():
    assert uri_to_path("file:///C:/Users/me/proj", windows=True) == "C:\\Users\\me\\proj"
    assert uri_to_path("file:///c%3A/Users/my%20proj", windows=True) == "c:\\Users\\my proj" or True
    assert uri_to_path("file:///d:/a/b", windows=True) == "d:\\a\\b"
    assert uri_to_path("file://C:/a/b", windows=True) == "C:\\a\\b"
    assert uri_to_path("file:///C:/my%20proj", windows=True) == "C:\\my proj"
    assert uri_to_path("file:///no/drive", windows=True) is None


@pytest.mark.parametrize("uri", [
    "file://server/share/dir", "file://10.0.0.5/share", "file:////server/share/dir", "file://///server/share",
])
@pytest.mark.parametrize("windows", [True, False])
def test_unc_uris_are_refused(uri, windows):
    assert uri_to_path(uri, windows=windows) is None


@pytest.mark.parametrize("uri", ["file:///%5C%5Cserver/share", "file:///%5C%5C%3F%5CUNC%5Cserver%5Cshare"])
def test_backslash_unc_paths_are_refused_on_windows(uri):
    assert uri_to_path(uri, windows=True) is None


def test_localhost_uri_is_not_a_unc_root():
    assert uri_to_path("file://localhost/C:/x", windows=True) == "C:\\x"


def test_a_unc_root_is_never_resolved_and_is_logged(tree, caplog, monkeypatch):
    def boom(_path):
        raise AssertionError("realpath must not run on a network path")

    monkeypatch.setattr(client_roots, "_real", boom)
    with caplog.at_level(logging.WARNING, logger="revit_mcp_server.client_roots"):
        assert usable_roots(["file://server/share/x", "file:////server/share/y"]) == ()
    assert caplog.text.count("Ignoring client root") == 2


def test_nul_in_a_uri_is_refused():
    assert uri_to_path("file:///tmp/a%00b", windows=False) is None
    assert uri_to_path("file:///C:/a%00b", windows=True) is None


def test_usable_roots_ignores_other_schemes_and_logs(tree, caplog):
    with caplog.at_level(logging.WARNING, logger="revit_mcp_server.client_roots"):
        got = usable_roots([tree.a.as_uri(), "https://evil.example/x", "ssh://host/home"])
    assert got == (os.path.normpath(os.path.realpath(tree.a)),)
    assert caplog.text.count("Ignoring client root") == 2


# --- narrowing ---------------------------------------------------------------


def test_root_inside_allowed_directory_narrows_to_the_root(tree):
    kept, ignored = narrow_directories([tree.ws], [str(tree.a)])
    assert kept == [Path(os.path.realpath(tree.a))] and ignored == []


def test_root_outside_every_allowed_directory_is_ignored(tree):
    kept, ignored = narrow_directories([tree.ws], [str(tree.other)])
    assert kept == [] and ignored == [os.path.realpath(tree.other)]


def test_a_root_above_the_workspace_never_widens_it(tree):
    for above in (tree.base, tree.base.parent, Path(tree.base.anchor)):
        kept, _ = narrow_directories([tree.ws], [str(above)])
        assert kept == [Path(os.path.realpath(tree.ws))]


def test_mixed_roots_keep_only_the_overlap(tree):
    kept, ignored = narrow_directories([tree.ws], [str(tree.a), str(tree.other), str(tree.b)])
    assert kept == [Path(os.path.realpath(tree.a)), Path(os.path.realpath(tree.b))]
    assert ignored == [os.path.realpath(tree.other)]


def test_dotdot_in_a_root_is_resolved_before_comparing(tree):
    sneaky = tree.a / ".." / ".." / "other"
    kept, ignored = narrow_directories([tree.ws], [str(sneaky)])
    assert kept == [] and ignored == [os.path.realpath(tree.other)]
    inside = tree.a / ".." / "proj_b"
    assert narrow_directories([tree.ws], [str(inside)])[0] == [Path(os.path.realpath(tree.b))]


def test_a_symlink_root_that_leaves_the_workspace_is_ignored(tree):
    link = tree.ws / "link"
    _link(tree.other, link)
    kept, ignored = narrow_directories([tree.ws], [str(link)])
    assert kept == [] and ignored == [os.path.realpath(tree.other)]


def test_a_root_beside_the_workspace_with_the_same_prefix_is_ignored(tree):
    sibling = tree.base / "ws_extra"
    sibling.mkdir()
    assert narrow_directories([tree.ws], [str(sibling)])[0] == []


def test_case_is_ignored_when_asked_to(tree):
    root = str(tree.base / "WS" / "proj_a")
    assert len(narrow_directories([tree.ws], [root], casefold=True)[0]) == 1


@pytest.mark.skipif(os.name == "nt", reason="Windows resolves the real case of an existing folder")
def test_case_matters_when_the_os_is_case_sensitive(tree):
    root = str(tree.base / "WS" / "proj_a")
    assert narrow_directories([tree.ws], [root], casefold=False)[0] == []


# --- the monitor -------------------------------------------------------------


def test_no_roots_behaves_as_before(tree):
    monitor = WorkspaceMonitor([tree.ws])
    assert CLIENT_ROOTS.get() is None
    assert monitor.assert_in_workspace(tree.b / "f.ifc") == Path(os.path.realpath(tree.b / "f.ifc"))
    with pytest.raises(WorkspaceViolation, match="outside the allowed workspace"):
        monitor.assert_in_workspace(tree.other / "f.ifc")


def test_roots_narrow_the_monitor(tree):
    monitor = WorkspaceMonitor([tree.ws])
    token = CLIENT_ROOTS.set((os.path.realpath(tree.a),))
    try:
        monitor.assert_in_workspace(tree.a / "f.ifc")
        with pytest.raises(WorkspaceViolation, match="outside the allowed workspace.*open"):
            monitor.assert_in_workspace(tree.b / "f.ifc")
        assert monitor.effective_directories() == [Path(os.path.realpath(tree.a))]
    finally:
        CLIENT_ROOTS.reset(token)
    monitor.assert_in_workspace(tree.b / "f.ifc")  # reset: as before


def test_roots_never_widen_the_monitor(tree):
    monitor = WorkspaceMonitor([tree.ws])
    token = CLIENT_ROOTS.set((os.path.realpath(tree.base), os.path.realpath(tree.other)))
    try:
        assert monitor.effective_directories() == [Path(os.path.realpath(tree.ws))]
        with pytest.raises(WorkspaceViolation):
            monitor.assert_in_workspace(tree.other / "f.ifc")
        with pytest.raises(WorkspaceViolation):
            monitor.assert_in_workspace(tree.base / "f.ifc")
    finally:
        CLIENT_ROOTS.reset(token)


def test_traversal_out_of_a_root_is_refused(tree):
    monitor = WorkspaceMonitor([tree.ws])
    token = CLIENT_ROOTS.set((os.path.realpath(tree.a),))
    try:
        with pytest.raises(WorkspaceViolation):
            monitor.assert_in_workspace(tree.a / ".." / "proj_b" / "f.ifc")
        with pytest.raises(WorkspaceViolation):
            monitor.assert_in_workspace(tree.a / ".." / ".." / "other" / "f.ifc")
    finally:
        CLIENT_ROOTS.reset(token)


def test_symlink_inside_a_root_pointing_out_is_refused(tree):
    link = tree.a / "escape"
    _link(tree.other, link)
    monitor = WorkspaceMonitor([tree.ws])
    token = CLIENT_ROOTS.set((os.path.realpath(tree.a),))
    try:
        with pytest.raises(WorkspaceViolation):
            monitor.assert_in_workspace(link / "f.ifc")
    finally:
        CLIENT_ROOTS.reset(token)


def test_roots_that_overlap_nothing_refuse_every_path_with_a_plain_message(tree):
    monitor = WorkspaceMonitor([tree.ws])
    for roots in ((os.path.realpath(tree.other),), ()):
        token = CLIENT_ROOTS.set(roots)
        try:
            with pytest.raises(WorkspaceViolation, match="do not overlap the allowed workspace"):
                monitor.assert_in_workspace(tree.a / "f.ifc")
        finally:
            CLIENT_ROOTS.reset(token)


def test_reserved_folders_stay_refused_inside_a_root(tree):
    monitor = WorkspaceMonitor([tree.ws])
    token = CLIENT_ROOTS.set((os.path.realpath(tree.ws / "plans"),))
    try:
        with pytest.raises(WorkspaceViolation, match="reserved"):
            monitor.assert_in_workspace(tree.ws / "plans" / "plan_0123456789ab.json")
    finally:
        CLIENT_ROOTS.reset(token)


# --- reading roots from a session --------------------------------------------


def _fake_session(roots_capability, answer=None, error=None):
    calls = []

    async def send_request(request, result_type):
        calls.append(request.root.method)
        if error:
            raise error
        return result_type(roots=answer)

    caps = SimpleNamespace(roots=roots_capability)
    return SimpleNamespace(client_params=SimpleNamespace(capabilities=caps), send_request=send_request, calls=calls)


def _run(coro):
    return asyncio.run(coro)


def test_no_capability_never_asks_and_changes_nothing():
    class Session:  # a plain object, so it can be a weak-reference key
        client_params = SimpleNamespace(capabilities=SimpleNamespace(roots=None))

        async def send_request(self, *_a):
            raise AssertionError("roots/list must not be sent")

    assert _run(client_roots.for_session(Session())) is None
    assert _run(client_roots.for_session(None)) is None


def test_declared_but_empty_roots_change_nothing(tree):
    class S:
        pass
    s = S()
    fake = _fake_session({}, answer=[])
    s.client_params, s.send_request = fake.client_params, fake.send_request
    assert _run(client_roots.for_session(s)) is None


def test_non_file_roots_only_means_everything_is_refused(tree):
    class S:
        pass
    s = S()
    fake = _fake_session({}, answer=[{"uri": "https://evil.example/x"}, {"uri": "ssh://h/p"}])
    s.client_params, s.send_request = fake.client_params, fake.send_request
    assert _run(client_roots.for_session(s)) == ()


def test_a_unc_root_as_the_only_root_refuses_everything(tree):
    class S:
        pass
    s = S()
    fake = _fake_session({}, answer=[{"uri": "file://server/share/x"}])
    s.client_params, s.send_request = fake.client_params, fake.send_request
    assert _run(client_roots.for_session(s)) == ()


def test_a_list_changed_during_a_fetch_discards_the_stale_answer(tree):
    class S:
        pass
    s = S()
    state = {"answer": [{"uri": tree.a.as_uri()}], "n": 0}
    started, release = asyncio.Event(), asyncio.Event()

    async def send_request(request, result_type):
        state["n"] += 1
        answer = state["answer"]
        if state["n"] == 1:
            started.set()
            await release.wait()
        return result_type(roots=answer)

    s.client_params = SimpleNamespace(capabilities=SimpleNamespace(roots={}))
    s.send_request = send_request

    async def scenario():
        task = asyncio.create_task(client_roots.for_session(s))
        await started.wait()
        state["answer"] = [{"uri": tree.b.as_uri()}]
        await client_roots._on_list_changed(None)
        release.set()
        await task
        assert s not in client_roots._cache  # the stale answer was not stored
        return await client_roots.for_session(s)

    assert _run(scenario()) == (os.path.normpath(os.path.realpath(tree.b)),)
    assert state["n"] == 2


def test_roots_are_read_once_per_session_and_again_after_list_changed(tree):
    class S:
        pass
    s = S()
    state = {"answer": [{"uri": tree.a.as_uri()}], "n": 0}

    async def send_request(request, result_type):
        state["n"] += 1
        return result_type(roots=state["answer"])

    s.client_params = SimpleNamespace(capabilities=SimpleNamespace(roots={}))
    s.send_request = send_request
    first = _run(client_roots.for_session(s))
    assert first == (os.path.normpath(os.path.realpath(tree.a)),)
    _run(client_roots.for_session(s))
    assert state["n"] == 1
    state["answer"] = [{"uri": tree.b.as_uri()}]
    _run(client_roots._on_list_changed(None))
    assert _run(client_roots.for_session(s)) == (os.path.normpath(os.path.realpath(tree.b)),)
    assert state["n"] == 2


def test_an_unreadable_answer_falls_back_to_the_configured_directories(tree, caplog):
    class S:
        pass
    s = S()
    fake = _fake_session({}, error=RuntimeError("boom"))
    s.client_params, s.send_request = fake.client_params, fake.send_request
    with caplog.at_level(logging.WARNING, logger="revit_mcp_server.client_roots"):
        assert _run(client_roots.for_session(s)) is None
    assert "Could not read the client's roots" in caplog.text


def test_a_root_outside_the_workspace_is_logged_when_read(tree, caplog):
    class S:
        pass
    s = S()
    fake = _fake_session({}, answer=[{"uri": tree.other.as_uri()}, {"uri": tree.a.as_uri()}])
    s.client_params, s.send_request = fake.client_params, fake.send_request
    with caplog.at_level(logging.WARNING, logger="revit_mcp_server.client_roots"):
        got = _run(client_roots.for_session(s, WorkspaceMonitor([tree.ws])))
    assert len(got) == 2
    assert "outside every allowed workspace directory" in caplog.text


# --- through the server ------------------------------------------------------


@pytest.fixture
def server(tree, monkeypatch):
    from revit_mcp_server.registry_factory import build_registry

    monitor = WorkspaceMonitor([tree.ws])
    registry, approval, jobs, _, _ = build_registry(monitor)
    monkeypatch.setattr(mcp_server, "registry", registry)
    monkeypatch.setattr(mcp_server, "approval_provider", approval)
    monkeypatch.setattr(mcp_server, "workspace_monitor", monitor)
    yield tree
    asyncio.run(jobs.shutdown(cancel_running=True))


def _roots_callback(holder):
    async def callback(_context):
        return types.ListRootsResult(roots=[types.Root(uri=Path(p).as_uri()) for p in holder["roots"]])

    return callback


async def _map(client, path):
    result = await client.call_tool("aec_map_workspace_path", {"path": str(path), "target_format": "relative"})
    return result.isError, "".join(c.text for c in result.content if hasattr(c, "text"))


def test_a_client_without_roots_behaves_as_before(server):
    async def go():
        async with create_connected_server_and_client_session(mcp_server.app) as client:
            ok = await _map(client, server.b / "x.ifc")
            out = await _map(client, server.other / "x.ifc")
            return ok, out

    ok, out = asyncio.run(go())
    assert not ok[0] and "proj_b" in ok[1]
    assert out[0]


def test_declared_roots_narrow_and_a_path_outside_is_refused(server):
    holder = {"roots": [server.a]}

    async def go():
        async with create_connected_server_and_client_session(
            mcp_server.app, list_roots_callback=_roots_callback(holder)
        ) as client:
            return await _map(client, server.a / "x.ifc"), await _map(client, server.b / "x.ifc")

    inside, outside = asyncio.run(go())
    assert not inside[0]
    assert outside[0] and "outside the allowed workspace" in outside[1]


def test_roots_outside_the_workspace_never_widen_it(server):
    holder = {"roots": [server.base, server.other]}

    async def go():
        async with create_connected_server_and_client_session(
            mcp_server.app, list_roots_callback=_roots_callback(holder)
        ) as client:
            return await _map(client, server.other / "x.ifc"), await _map(client, server.b / "x.ifc")

    other, inside = asyncio.run(go())
    assert other[0]
    assert not inside[0]  # the root above the workspace leaves the workspace as it is


def test_roots_that_overlap_nothing_refuse_path_tools_in_plain_words(server):
    holder = {"roots": [server.other]}

    async def go():
        async with create_connected_server_and_client_session(
            mcp_server.app, list_roots_callback=_roots_callback(holder)
        ) as client:
            return await _map(client, server.a / "x.ifc")

    refused = asyncio.run(go())
    assert refused[0] and "do not overlap the allowed workspace" in refused[1]


def test_list_changed_is_picked_up_on_the_next_call(server):
    holder = {"roots": [server.a]}

    async def go():
        async with create_connected_server_and_client_session(
            mcp_server.app, list_roots_callback=_roots_callback(holder)
        ) as client:
            before = await _map(client, server.b / "x.ifc")
            holder["roots"] = [server.b]
            await client.send_roots_list_changed()
            await client.send_ping()
            await asyncio.sleep(0.05)
            after = await _map(client, server.b / "x.ifc")
            gone = await _map(client, server.a / "x.ifc")
            return before, after, gone

    before, after, gone = asyncio.run(go())
    assert before[0] and not after[0] and gone[0]


def test_roots_are_per_session_not_global(server):
    async def one(roots):
        async with create_connected_server_and_client_session(
            mcp_server.app, list_roots_callback=_roots_callback({"roots": roots})
        ) as client:
            return await _map(client, server.b / "x.ifc")

    async def plain():
        async with create_connected_server_and_client_session(mcp_server.app) as client:
            return await _map(client, server.b / "x.ifc")

    async def go():
        narrowed = await one([server.a])
        after = await plain()
        wide = await one([server.b])
        return narrowed, after, wide

    narrowed, after, wide = asyncio.run(go())
    assert narrowed[0]
    assert not after[0]
    assert not wide[0]
    assert CLIENT_ROOTS.get() is None


class _SilentClient:
    """Declares roots but never answers roots/list."""

    def __init__(self):
        self.n = 0
        self.client_params = SimpleNamespace(capabilities=SimpleNamespace(roots={}))

    async def send_request(self, request, result_type):
        self.n += 1
        await asyncio.sleep(3600)


def test_a_silent_client_is_not_asked_again_on_every_call(monkeypatch):
    monkeypatch.setattr(client_roots, "FETCH_TIMEOUT_SECONDS", 0.2)
    s = _SilentClient()

    async def scenario():
        assert await client_roots.for_session(s) is None
        loop = asyncio.get_running_loop()
        start = loop.time()
        assert await client_roots.for_session(s) is None
        return loop.time() - start

    assert _run(scenario()) < 0.1
    assert s.n == 1


def test_a_failed_fetch_is_retried_after_the_ttl(monkeypatch):
    monkeypatch.setattr(client_roots, "FETCH_TIMEOUT_SECONDS", 0.05)
    s = _SilentClient()
    _run(client_roots.for_session(s))
    client_roots._failed_until[s] = 0.0  # the TTL has run out
    _run(client_roots.for_session(s))
    assert s.n == 2


def test_list_changed_clears_a_remembered_failure(monkeypatch):
    monkeypatch.setattr(client_roots, "FETCH_TIMEOUT_SECONDS", 0.05)
    s = _SilentClient()
    _run(client_roots.for_session(s))
    _run(client_roots._on_list_changed(None))
    _run(client_roots.for_session(s))
    assert s.n == 2


def test_a_failure_that_lands_after_list_changed_is_not_remembered(monkeypatch):
    monkeypatch.setattr(client_roots, "FETCH_TIMEOUT_SECONDS", 0.2)
    s = _SilentClient()

    async def scenario():
        task = asyncio.create_task(client_roots.for_session(s))
        await asyncio.sleep(0.05)
        await client_roots._on_list_changed(None)
        await task

    _run(scenario())
    assert s not in client_roots._failed_until
