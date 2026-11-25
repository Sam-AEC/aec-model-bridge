"""Advisory lint for `revit_execute_python` scripts: known Revit API and IronPython traps.

Each rule is a regular expression over the script text with a message and an example. The lint only
returns warnings. It never refuses, edits or delays a script, it is not part of the approval gate, and
read mode (security/read_mode.py) is unchanged. Rules are text matches, so they can warn about code
that is fine; read the warning, then decide. The traps come from the live-use list in
.claude/skills/revit-bim-builder/SKILL.md. UNVERIFIED against live Revit: the rules were written from
that list and tested only on fixture scripts.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

MAX_WARNINGS = 20


@dataclass(frozen=True)
class LintRule:
    id: str
    pattern: re.Pattern[str]
    message: str
    example: str
    # When this pattern matches anywhere in the script, the rule stays quiet.
    unless: re.Pattern[str] | None = None


def _rx(text: str) -> re.Pattern[str]:
    return re.compile(text)


RULES: tuple[LintRule, ...] = (
    LintRule(
        "collections_import",
        _rx(r"^[ \t]*(?:import|from)[ \t]+collections\b"),
        "IronPython 2.7 in Revit has no `collections` module. Use a plain dict or list.",
        "d = {}; d.setdefault(key, []).append(value)",
    ),
    LintRule(
        "fstring",
        _rx(r"""(?<![\w.])(?:[fF][rR]?|[rR][fF])["']"""),
        "IronPython 2.7 does not support f-strings. Use '%s' % value or '{}'.format(value).",
        "print('walls: %d' % count)",
    ),
    LintRule(
        "out_parameter_roof",
        _rx(r"\bNewFootPrintRoof\b"),
        "NewFootPrintRoof has an out parameter that IronPython cannot call. "
        "Use the add-in command revit.create_roof, or call it by reflection.",
        "revit_raw_command: command 'revit.create_roof'",
    ),
    LintRule(
        "wall_flip",
        _rx(r"\.\s*Flip\s*\("),
        "Wall.Flip() after creation breaks corner joins. Reverse the curve before creating the wall "
        "(Revit puts the exterior face on the left of the drawing direction).",
        "Wall.Create(doc, curve.CreateReversed(), level_id, False)",
    ),
    LintRule(
        "phase_indexer",
        _rx(r"\.\s*(?:FromRoom|ToRoom)\b"),
        "FromRoom and ToRoom depend on the phase and show as `indexer#` in IronPython. "
        "Call get_FromRoom(phase) or get_ToRoom(phase).",
        "room = door.get_FromRoom(doc.Phases[doc.Phases.Size - 1])",
    ),
    LintRule(
        "transaction_unclosed",
        _rx(r"\bTransaction\s*\("),
        "A Transaction is created but the script never calls Commit() or RollBack(). Each call has its own "
        "scope, so an open transaction is lost or blocks later calls. Commit or roll back in the same script.",
        "t = Transaction(doc, 'name'); t.Start(); ...; t.Commit()",
        unless=_rx(r"\.\s*(?:Commit|RollBack)\s*\("),
    ),
    LintRule(
        "family_doc_not_closed_in_finally",
        _rx(r"\.\s*EditFamily\s*\("),
        "A document from EditFamily must be closed in a finally block, or an error leaves it open and later "
        "calls fail.",
        "fdoc = doc.EditFamily(fam)\ntry:\n    ...\nfinally:\n    fdoc.Close(False)",
        unless=_rx(r"\bfinally[ \t]*:[\s\S]*\.\s*Close\s*\("),
    ),
    LintRule(
        "dialog_blocks_bridge",
        _rx(r"\bTaskDialog\s*\.\s*Show\b|\bMessageBox\s*\.\s*Show\b|\bForms\s*\.\s*Form\b"),
        "A dialog freezes Revit and the bridge until someone closes it. Print the text and return it in "
        "the result instead.",
        "print('Done')",
    ),
    LintRule(
        "long_sleep",
        _rx(r"\btime\s*\.\s*sleep\s*\(\s*(?:[2-9]\d|\d{3,})\b"),
        "A sleep of 20 seconds or more can hit the 30 second bridge timeout, and the script keeps running "
        "after the timeout. Split the work into shorter calls.",
        "time.sleep(2)",
    ),
)


def _without_comment_lines(script: str) -> str:
    # Blank (not drop) full-line comments so line numbers stay right.
    return "\n".join("" if line.lstrip().startswith("#") else line for line in script.splitlines())


def lint_script(script: Any) -> list[dict[str, Any]]:
    """Warnings for one script: a list of {rule, line, message, example}. Never raises, never blocks.

    A value that is not a non-empty string gives no warnings. At most MAX_WARNINGS are returned."""
    if not isinstance(script, str) or not script.strip():
        return []
    try:
        text = _without_comment_lines(script)
        warnings: list[dict[str, Any]] = []
        for rule in RULES:
            match = rule.pattern.search(text)
            if match is None or (rule.unless is not None and rule.unless.search(text)):
                continue
            warnings.append({
                "rule": rule.id,
                "line": text.count("\n", 0, match.start()) + 1,
                "message": rule.message,
                "example": rule.example,
            })
        return warnings[:MAX_WARNINGS]
    except Exception:  # noqa: BLE001 - advisory only: a lint fault must never stop a script
        return []
