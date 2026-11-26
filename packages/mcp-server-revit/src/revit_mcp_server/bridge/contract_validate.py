"""Checks an add-in command payload against its schema in the shared command contract.

The schemas come from contracts/bridge-commands.json through the generated module
contract_generated.py. This file is hand written and supports the JSON Schema subset that
contract uses: type, enum, minimum, maximum, minItems, pattern, items, properties, required,
anyOf and $ref to "#/$defs/<name>". The extension keyword "x-ignore-case" makes enum
matching case-insensitive, as the add-in is for category names.

Properties that a schema does not list are allowed: the server adds fields such as
request_id and action_id that the add-in reads outside the command handler.
"""
from __future__ import annotations

import math
import re
from typing import Any, Mapping

from ..errors import BridgeContractError

_MAX_PROBLEMS = 5
_TYPE_WORDS = {
    "string": "a string",
    "number": "a number",
    "integer": "a whole number",
    "boolean": "true or false",
    "array": "a list",
    "object": "an object",
    "null": "null",
}


def _resolve(schema: Mapping[str, Any], defs: Mapping[str, Any]) -> Mapping[str, Any]:
    seen = 0
    while "$ref" in schema:
        ref = schema["$ref"]
        if not isinstance(ref, str) or not ref.startswith("#/$defs/") or ref[8:] not in defs:
            raise BridgeContractError(f"The command contract has an unknown reference {ref!r}.")
        schema = defs[ref[8:]]
        seen += 1
        if seen > 20:
            raise BridgeContractError("The command contract has a reference loop.")
    return schema


def _is_type(value: Any, name: str) -> bool:
    if name == "null":
        return value is None
    if name == "boolean":
        return isinstance(value, bool)
    if name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if name == "string":
        return isinstance(value, str)
    if name == "array":
        return isinstance(value, (list, tuple))
    if name == "object":
        return isinstance(value, Mapping)
    return False


def _describe(schema: Mapping[str, Any], defs: Mapping[str, Any]) -> str:
    schema = _resolve(schema, defs)
    if "anyOf" in schema:
        return " or ".join(_describe(option, defs) for option in schema["anyOf"])
    types = schema.get("type")
    if types is None:
        return "any value"
    names = [types] if isinstance(types, str) else list(types)
    return " or ".join(_TYPE_WORDS.get(n, n) for n in names)


def _shown(value: Any) -> str:
    text = repr(value)
    return text if len(text) <= 60 else text[:57] + "..."


def _check(schema: Mapping[str, Any], value: Any, defs: Mapping[str, Any], where: str, out: list[str]) -> None:
    if len(out) >= _MAX_PROBLEMS:
        return
    schema = _resolve(schema, defs)

    if "anyOf" in schema:
        for option in schema["anyOf"]:
            trial: list[str] = []
            _check(option, value, defs, where, trial)
            if not trial:
                break
        else:
            out.append(f"{where} must be {_describe(schema, defs)}, got {_shown(value)}")
            return

    types = schema.get("type")
    if types is not None:
        names = [types] if isinstance(types, str) else list(types)
        if not any(_is_type(value, n) for n in names):
            out.append(f"{where} must be {_describe(schema, defs)}, got {_shown(value)}")
            return

    if isinstance(value, float) and not math.isfinite(value):
        out.append(f"{where} must be a finite number, got {_shown(value)}")
        return

    if "enum" in schema:
        allowed = schema["enum"]
        if schema.get("x-ignore-case") and isinstance(value, str):
            ok = value.lower() in {a.lower() for a in allowed if isinstance(a, str)}
        else:
            ok = value in allowed
        if not ok:
            words = ", ".join(str(a) for a in allowed if a is not None)
            out.append(f"{where} must be one of: {words}; got {_shown(value)}")
            return

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            out.append(f"{where} must be at least {schema['minimum']}, got {_shown(value)}")
            return
        if "maximum" in schema and value > schema["maximum"]:
            out.append(f"{where} must be at most {schema['maximum']}, got {_shown(value)}")
            return

    if isinstance(value, str) and "pattern" in schema and not re.search(schema["pattern"], value):
        out.append(f"{where} has the wrong format, got {_shown(value)}")
        return

    if isinstance(value, (list, tuple)):
        if "minItems" in schema and len(value) < schema["minItems"]:
            out.append(f"{where} needs at least {schema['minItems']} item(s), got {len(value)}")
            return
        if "items" in schema:
            for index, item in enumerate(value):
                _check(schema["items"], item, defs, f"{where}[{index}]", out)

    if isinstance(value, Mapping):
        for key in schema.get("required", ()):
            if key not in value:
                out.append(f"{_join(where, key)} is required and missing")
        for key, sub in schema.get("properties", {}).items():
            if key in value:
                _check(sub, value[key], defs, _join(where, key), out)


def _join(where: str, key: str) -> str:
    return key if not where else f"{where}.{key}"


def payload_problems(schema: Mapping[str, Any], payload: Any, defs: Mapping[str, Any]) -> list[str]:
    """Plain-language problems with the payload, at most a few; an empty list means it fits."""
    if not isinstance(payload, Mapping):
        return [f"the payload must be an object, got {_shown(payload)}"]
    out: list[str] = []
    _check(schema, payload, defs, "", out)
    return out[:_MAX_PROBLEMS]


def validate_payload(command: str, schema: Mapping[str, Any], payload: Any, defs: Mapping[str, Any]) -> None:
    """Raise BridgeContractError, naming every problem found, when the payload does not fit."""
    problems = payload_problems(schema, payload, defs)
    if problems:
        raise BridgeContractError(
            f"Not sent to Revit: the payload for add-in command '{command}' does not match the command "
            f"contract. {'; '.join(problems)}. Nothing was changed in the model. "
            "The parameters each command accepts are in contracts/bridge-commands.json."
        )
