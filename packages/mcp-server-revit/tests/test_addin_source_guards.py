"""Static guards on the C# add-in source.

There is no C# test project yet and CI only compiles the add-in, so a method that calls
itself still builds. These checks read the source text and fail on known-fatal patterns.
"""
import re
from pathlib import Path

ADDIN_SRC = Path(__file__).resolve().parents[3] / "packages" / "revit-bridge-addin" / "src"
FACTORY = ADDIN_SRC / "Bridge" / "BridgeCommandFactory.cs"


def _method_body(source: str, signature_re: str) -> str:
    match = re.search(signature_re, source)
    assert match, f"method not found: {signature_re}"
    start = source.index("{", match.end())
    depth = 0
    for i in range(start, len(source)):
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                return source[start : i + 1]
    raise AssertionError("unbalanced braces")


def test_create_transaction_builds_a_real_transaction_and_does_not_call_itself():
    body = _method_body(
        FACTORY.read_text(encoding="utf-8"),
        r"public static BridgeTransaction CreateTransaction\(Document doc, string name\)",
    )
    assert "BridgeCommandFactory.CreateTransaction(" not in body, "CreateTransaction calls itself"
    assert "CreateTransaction(" not in body, "CreateTransaction calls itself"
    assert "new BridgeTransaction(" in body, "CreateTransaction must construct the checked BridgeTransaction"
    wrapper = (ADDIN_SRC / "Bridge" / "BridgeTransaction.cs").read_text(encoding="utf-8")
    assert "new Transaction(" in wrapper, "BridgeTransaction must construct the Revit Transaction"


def test_add_in_constructs_transactions_somewhere():
    hits = [p for p in ADDIN_SRC.rglob("*.cs") if "new Transaction(" in p.read_text(encoding="utf-8")]
    assert hits, "no 'new Transaction(' in the add-in: every model write would fail"


# --- Revit must never be held by one long request (the 2026-10-13 freeze) -------------------------

def test_executor_runs_one_request_per_revit_turn_and_skips_abandoned_ones():
    source = (ADDIN_SRC / "Bridge" / "ExternalEventHandler.cs").read_text(encoding="utf-8")
    execute = _method_body(source, r"public void Execute\(UIApplication app\)")
    assert "IsWanted(" in execute, "abandoned requests must be dropped before they start"
    assert re.search(r"RunOne\(app, request\);\s*break;", execute), "only one request may run per Execute"
    assert "Event?.Raise()" in execute, "remaining requests need another Revit turn, not the same one"


def test_queue_does_not_enqueue_a_retried_request_id_twice():
    source = (ADDIN_SRC / "Bridge" / "CommandQueue.cs").read_text(encoding="utf-8")
    enqueue = _method_body(source, r"public void Enqueue\(CommandRequest request\)")
    assert "_inflight.TryAdd" in enqueue and "return;" in enqueue


def test_snapshot_is_bounded_by_count_and_time_and_skips_geometry_computed_values():
    body = _method_body(FACTORY.read_text(encoding="utf-8"), r"private static object ExecuteExtractSnapshot\(")
    assert "ElapsedMilliseconds > budgetMs" in body and "maxElements" in body
    assert "truncated" in body
    assert "IsHeavySnapshotParameter" in body
    assert "ToElementIds()" in body, "collect ids first; do not materialise every element up front"


def test_snapshot_records_carry_host_uid_for_the_hosting_rules():
    """door_no_host / window_no_host test host_uid; leaving it out flagged every hosted door."""
    body = _method_body(FACTORY.read_text(encoding="utf-8"), r"private static object ExecuteExtractSnapshot\(")
    assert re.search(r"host_uid\s*=\s*\(elem as FamilyInstance\)\?\.Host\?\.UniqueId", body)


def test_hub_is_never_launched_from_the_bundled_python_folder():
    """From that folder the panel chat's MCP server failed to start (python311.dll conflict) and the chat had no tools."""
    source = (ADDIN_SRC / "Bridge" / "PanelHubLauncher.cs").read_text(encoding="utf-8")
    assert "GetDirectoryName(interpreter)" not in source
    assert "startInfo.WorkingDirectory = workspace" in source


def test_preview_replaces_stale_state_and_accepts_64_bit_element_ids():
    source = FACTORY.read_text(encoding="utf-8")
    body = _method_body(source, r"private static object ExecutePreviewElements\(")
    assert "x.GetInt64()" in body and "x.GetInt32()" not in body
    assert body.index("ExecuteClearPreview(app)") < body.index("if (ids.Count == 0)")
    assert body.index("view = uidoc.ActiveView", body.index("uidoc.ShowElements(ids)")) > body.index("uidoc.ShowElements(ids)")


# --- door/window fit checks and the clash budget (B-13, B-04) ------------------------------------

def _factory_text() -> str:
    return FACTORY.read_text(encoding="utf-8")


def test_place_door_and_window_share_the_checked_opening_helper():
    source = _factory_text()
    for command, category in (("revit.place_door", "OST_Doors"), ("revit.place_window", "OST_Windows")):
        match = re.search(r'\[BridgeCommand\("' + re.escape(command) + r'"[^\]]*\]\s*private static object \w+\([^)]*\)\s*=>([^;]*);', source)
        assert match, f"{command} must delegate to the shared helper"
        assert "PlaceHostedOpening(" in match.group(1) and category in match.group(1)


def test_opening_placement_refuses_before_the_transaction_and_verifies_the_host():
    source = _factory_text()
    body = _method_body(source, r"private static object PlaceHostedOpening\(")
    assert body.index("CheckOpeningFit(") < body.index("CreateTransaction("), "fit check must run before any transaction"
    assert body.index("ResolveOpeningSymbol(") < body.index("CreateTransaction(")
    assert body.count("CreateTransaction(") == 1, "one transaction per call"
    assert "CommitChecked()" in body
    assert body.count("VerifyOpeningHost(") == 2, "host verified before and after commit"
    assert "host_wall_id" in body and "volume_delta_m3" in body
    assert "hand_flipped" in body and "facing_flipped" in body
    assert "flipHand()" in body and "flipFacing()" in body


def test_opening_fit_check_names_the_wall_and_reads_width_height_parameters():
    source = _factory_text()
    body = _method_body(source, r"private static object CheckOpeningFit\(")
    assert "wallId" in body and "does not fit" in body
    for builtin in ("DOOR_WIDTH", "DOOR_HEIGHT", "WINDOW_WIDTH", "WINDOW_HEIGHT"):
        assert builtin in body
    assert "throw new ArgumentException" in body


def test_opening_symbol_defaults_are_not_hard_coded_names():
    source = _factory_text()
    for stale in ('"Single-Flush"', '"0915 x 2134mm"', '"1200 x 1500mm"'):
        assert stale not in source, f"{stale} does not exist in most projects; pick the first loaded symbol"
    body = _method_body(source, r"private static FamilySymbol ResolveOpeningSymbol\(")
    assert "first_available" in body
    assert "throw new InvalidOperationException" in body, "must fail loudly when no symbol is loaded"


def test_check_clashes_has_a_budget_and_does_not_look_names_up_in_the_pair_loop():
    source = _factory_text()
    body = _method_body(source, r"private static object ExecuteCheckClashes\(")
    for token in ("max_pairs", "time_budget_s", "truncated", "pairs_examined", "Stopwatch"):
        assert token in body, token
    loop_start = body.index("foreach (var a in list1)")
    loop = body[loop_start:]
    assert "get_BoundingBox" not in loop, "bounding boxes must be cached outside the pair loop"
    assert ".Name" not in loop.replace("d1.Name", "").replace("d2.Name", ""), "Name lookups must go through the cache"
    assert "WhereElementIsNotElementType" in source[source.index("CollectClashCandidates(Document"):]


# --- Batch reads, dispatch table, UniqueId cache, gzip (#277, #291, #292) ----------------------------
# UNVERIFIED in live Revit. The Revit-free parts have C# unit tests in packages/revit-bridge-addin-tests.

def test_batch_command_is_read_only_and_checks_every_member_before_running():
    source = _factory_text()
    assert re.search(r'\[BridgeCommand\("revit\.batch", IsMutating = false\)\]', source)
    body = _method_body(source, r"private static object ExecuteBatch\(UIApplication app, JsonElement payload\)")
    assert body.index("BridgeBatch.Parse(payload, IsReadOnlyCommand)") < body.index("Execute(app, member.Tool")
    assert "TimeBudgetMs" in body, "a batch must not hold Revit without a bound"
    batch = (ADDIN_SRC / "Bridge" / "BridgeBatch.cs").read_text(encoding="utf-8")
    assert "MaxCommands = 25" in batch
    assert "cannot be nested" in batch and "not a read-only command" in batch
    ctor = _method_body(source, r"static BridgeCommandFactory\(\)")
    assert "if (!attr.IsMutating && !attr.ConfirmationRequired)" in ctor


def test_batch_members_cannot_open_a_transaction_or_run_side_effect_commands():
    source = _factory_text()
    create = _method_body(source, r"public static BridgeTransaction CreateTransaction\(Document doc, string name\)")
    assert create.index("if (InReadBatch)") < create.index("new BridgeTransaction(")
    body = _method_body(source, r"private static object ExecuteBatch\(UIApplication app, JsonElement payload\)")
    assert body.index("_readBatchDepth++;") < body.index("Execute(app, member.Tool")
    assert "finally" in body and "_readBatchDepth--;" in body
    batch = (ADDIN_SRC / "Bridge" / "BridgeBatch.cs").read_text(encoding="utf-8")
    parse = batch[batch.index("public static List<BridgeBatchMember> Parse("):]
    assert parse.index("HasSideEffects(tool)") < parse.index("members.Add(")


def test_execute_restores_outer_state_so_batch_members_do_not_clear_it():
    body = _method_body(_factory_text(), r"public static object Execute\(UIApplication app, string tool, JsonElement payload\)")
    assert "CurrentActionId = outerActionId;" in body
    assert "_currentTransactionMessages = outerMessages;" in body


def test_dispatch_table_is_built_once_and_refuses_duplicate_names():
    source = _factory_text()
    ctor = _method_body(source, r"static BridgeCommandFactory\(\)")
    assert "_handlers = BridgeDispatchTable.Build(entries);" in ctor
    assert "_handlers[" not in source, "handlers must not be added one by one (a duplicate would overwrite)"
    table = (ADDIN_SRC / "Bridge" / "BridgeDispatchTable.cs").read_text(encoding="utf-8")
    assert "#if NET8_0_OR_GREATER" in table and "ToFrozenDictionary" in table
    assert "declared more than once" in table
    app = (ADDIN_SRC / "Bridge" / "App.cs").read_text(encoding="utf-8")
    assert "BridgeCommandFactory.GetToolCatalog()" in app, "the table must be built at startup"


def test_unique_id_lookups_go_through_the_checked_cache():
    source = _factory_text()
    for name in ("ExecuteSelectByUniqueIds", "ExecutePreviewElements"):
        assert "ElementLookup.ByUniqueId(doc," in _method_body(source, rf"private static object {name}\(")
    lookup = (ADDIN_SRC / "Bridge" / "ElementLookup.cs").read_text(encoding="utf-8")
    body = _method_body(lookup, r"internal static Element\? ByUniqueId\(Document doc, string\? uniqueId\)")
    assert "hit.UniqueId" in body, "a cached id must be checked against the UniqueId before use"
    app = (ADDIN_SRC / "Bridge" / "App.cs").read_text(encoding="utf-8")
    for hook in ("ElementLookup.OnDocumentChanged(args)", "ElementLookup.OnDocumentClosing(args)", "ElementLookup.OnViewActivated(args)"):
        assert hook in app, hook


def test_large_responses_are_gzipped_only_when_the_client_asks():
    server = (ADDIN_SRC / "Bridge" / "BridgeServer.cs").read_text(encoding="utf-8")
    body = _method_body(server, r"private void RespondRaw\(HttpListenerContext context, int statusCode, string json\)")
    assert 'ResponseCompression.ShouldGzip(context.Request.Headers["Accept-Encoding"], buffer.Length)' in body
    assert '"Content-Encoding", "gzip"' in body
    compression = (ADDIN_SRC / "Bridge" / "ResponseCompression.cs").read_text(encoding="utf-8")
    assert "MinBytes = 64 * 1024" in compression
