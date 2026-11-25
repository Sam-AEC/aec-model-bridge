"""Every add-in command name the Python side uses exists in the Revit add-in, and unused add-in commands are listed.

tests/test_addin_hub_contract.py checks the provider tool mappings (``RevitProvider._tool_mapping``). Command names
also appear elsewhere: modules that call ``revit_raw_command``, the job provider, metadata tables and module.json
files. This test reads every ``"revit.<name>"`` string literal in the server source and compares it with the
``[BridgeCommand("...")]`` names in the add-in source (no .NET needed). It is the first step of the single command
contract in docs/adr/0020-single-command-contract.md.

Both directions use recorded lists. A new dangling name or a new unused command fails; an entry that stops being
true also fails, so the lists cannot rot. Do not add to a list to make a failure go away without a reason.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

PACKAGES = Path(__file__).resolve().parents[2]
SERVER_SRC = PACKAGES / "mcp-server-revit" / "src" / "revit_mcp_server"
ADDIN_SRC = PACKAGES / "revit-bridge-addin" / "src"

_ATTR = re.compile(r'\[BridgeCommand\(\s*"([^"]+)"')
_LITERAL = re.compile(r"""["'](revit\.[a-z0-9_]+)["']""")

# The legacy handler table (legacy/tools/handlers.py) is keyed by command name and runs only for a tool whose
# mapping already points at that name, so its keys are not callers. test_legacy_keys_are_never_forwarded checks that.
LEGACY_DIR = SERVER_SRC / "legacy"

# Names the Python side uses that the add-in does not declare, with the reason.
KNOWN_DANGLING = {
    # pyrevit_bridge refuses to run until an add-in runner exists (docs/pyrevit-bridge.md).
    "revit.run_pyrevit_script",
    # Not command names: a docstring example and a prefix test for export commands.
    "revit.x",
    "revit.export_",
}

# Generated catalogue of every add-in command (scripts/gen_bridge_contract.py); naming a command
# there does not make the server call it.
GENERATED = {"bridge/contract_generated.py"}

# Add-in commands that no Python source names. They stay reachable through revit_raw_command.
KNOWN_UNUSED = {
    "revit.create_cable_tray",
    "revit.create_revision_cloud",
    "revit.create_text_type",
    # Named only as keys of the legacy handler table; no hub tool forwards to them.
    "revit.export_pdf_by_sheet_set",
    "revit.export_schedules",
    "revit.get_mep_systems",
    "revit.get_project_location",
    "revit.get_render_settings",
    "revit.get_room_boundary",
    "revit.open_document",
}


def addin_commands() -> set[str]:
    names: set[str] = set()
    for path in ADDIN_SRC.rglob("*.cs"):
        names.update(_ATTR.findall(path.read_text(encoding="utf-8")))
    return names


def python_references(include_legacy: bool = False) -> dict[str, set[str]]:
    """command name -> files (relative to the server package) that contain it as a string literal."""
    found: dict[str, set[str]] = {}
    for path in sorted(SERVER_SRC.rglob("*")):
        if path.suffix not in (".py", ".json") or not path.is_file():
            continue
        if not include_legacy and LEGACY_DIR in path.parents:
            continue
        if path.relative_to(SERVER_SRC).as_posix() in GENERATED:
            continue
        for name in _LITERAL.findall(path.read_text(encoding="utf-8")):
            found.setdefault(name, set()).add(path.relative_to(SERVER_SRC).as_posix())
    return found


@pytest.fixture(scope="module")
def catalog() -> set[str]:
    names = addin_commands()
    assert len(names) > 100, "the add-in parser found too few commands"
    return names


@pytest.fixture(scope="module")
def references() -> dict[str, set[str]]:
    refs = python_references()
    assert len(refs) > 50, "the source scan found too few command names"
    return refs


def test_every_command_name_used_in_python_exists_in_the_addin(catalog, references):
    dangling = {name: sorted(files) for name, files in references.items() if name not in catalog}
    new = {name: files for name, files in dangling.items() if name not in KNOWN_DANGLING}
    assert not new, f"Python source names add-in commands that do not exist: {new}"
    stale = sorted(KNOWN_DANGLING - set(dangling))
    assert not stale, f"KNOWN_DANGLING entries that now exist or are no longer used, remove them: {stale}"


def test_unused_addin_commands_are_recorded(catalog, references):
    unused = catalog - set(references)
    new = sorted(unused - KNOWN_UNUSED)
    assert not new, (
        f"Add-in commands that no Python source uses: {new}. Add a hub tool for each, or record it in KNOWN_UNUSED "
        "with the reason it is reachable only through revit_raw_command."
    )
    stale = sorted(KNOWN_UNUSED - unused)
    assert not stale, f"KNOWN_UNUSED entries that are now used or gone, remove them: {stale}"


def test_legacy_keys_are_never_forwarded(catalog):
    from revit_mcp_server.providers import RevitProvider
    from revit_mcp_server.security.workspace import WorkspaceMonitor

    legacy = set(python_references(include_legacy=True)) - set(python_references())
    dead = legacy - catalog
    forwarded = {cmd for cmd, _ in RevitProvider(workspace=WorkspaceMonitor([PACKAGES]))._tool_mapping.values()}
    assert len(forwarded) > 50 and dead
    assert not (dead & forwarded), f"tools forward to legacy-only command names: {sorted(dead & forwarded)}"


def test_scanner_reads_both_quote_styles():
    assert _LITERAL.findall("a = \"revit.one\"; b = 'revit.two'; c = revit.three") == ["revit.one", "revit.two"]
    assert _ATTR.findall('[BridgeCommand("revit.x", IsMutating = false)]') == ["revit.x"]
