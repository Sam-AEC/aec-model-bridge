"""Bounded orchestration of existing dedicated Revit reads, never executable code."""
from __future__ import annotations

from typing import Any, Awaitable, Callable

MAX_ELEMENTS = 50
MAX_PARAMETERS = 20
MAX_SECTIONS = 200
MAX_ELEMENT_ID = 2**31 - 1  # get_parameter_value currently uses GetInt32.
MAX_NAME_LENGTH = 260

INSPECTION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "element_ids": {
            "type": "array", "minItems": 1, "maxItems": MAX_ELEMENTS, "uniqueItems": True,
            "items": {"type": "integer", "minimum": 1, "maximum": MAX_ELEMENT_ID},
            "description": "Explicit positive element IDs in the active document, up to 50 unique IDs.",
        },
        "parameter_names": {
            "type": "array", "maxItems": MAX_PARAMETERS, "uniqueItems": True,
            "items": {"type": "string", "minLength": 1, "maxLength": MAX_NAME_LENGTH, "pattern": r"\S"},
            "description": "Up to 20 exact parameter names; omitted or empty means geometry only. IDs times (1 + names) must be at most 200.",
        },
        "expected_document_title": {
            "type": "string", "minLength": 1, "maxLength": MAX_NAME_LENGTH, "pattern": r"\S",
            "description": "Optional exact active-document title guard; a mismatch skips all element reads.",
        },
    },
    "required": ["element_ids"],
}


def validate_inspection(arguments: dict[str, Any]) -> tuple[list[int], list[str], str | None]:
    """Validate independently of the MCP schema: panel and internal callers use this too."""
    if not isinstance(arguments, dict) or set(arguments) - set(INSPECTION_SCHEMA["properties"]):
        raise ValueError("revit_inspect_elements accepts only element_ids, parameter_names and expected_document_title")
    ids = arguments.get("element_ids")
    if not isinstance(ids, list) or not 1 <= len(ids) <= MAX_ELEMENTS:
        raise ValueError("element_ids must be a list of 1 to 50 unique positive integers")
    if any(type(value) is not int or not 1 <= value <= MAX_ELEMENT_ID for value in ids) or len(set(ids)) != len(ids):
        raise ValueError("element_ids must be unique positive integers no greater than 2147483647")
    names = arguments.get("parameter_names", [])
    if not isinstance(names, list) or len(names) > MAX_PARAMETERS:
        raise ValueError("parameter_names must be a list of at most 20 unique names")
    if any(not isinstance(name, str) or not name.strip() or len(name) > MAX_NAME_LENGTH for name in names):
        raise ValueError("parameter_names must contain nonblank strings of at most 260 characters")
    if len(set(names)) != len(names):
        raise ValueError("parameter_names must be unique")
    expected = arguments.get("expected_document_title")
    if "expected_document_title" in arguments and (
        not isinstance(expected, str) or not expected.strip() or len(expected) > MAX_NAME_LENGTH
    ):
        raise ValueError("expected_document_title must be a nonblank string of at most 260 characters")
    if len(ids) * (1 + len(names)) > MAX_SECTIONS:
        raise ValueError("At most 200 geometry/parameter sections may be requested; split this inspection into smaller batches")
    return list(ids), list(names), expected


def _error(message: str, code: str, **details: Any) -> dict[str, Any]:
    return {"success": False, "status": "error", "error": {"code": code, "message": message}, **details}


def _classify(result: Any, arguments: dict[str, Any]) -> dict[str, Any]:
    """Judge one read result (or the exception it raised) the same way for single and batched reads."""
    if isinstance(result, BaseException):
        return _error(str(result), "READ_FAILED", exception_type=type(result).__name__)
    if not isinstance(result, dict) or not result:
        return _error("Dedicated read returned no structured result", "INVALID_READ_RESULT")
    if result.get("success") is False or result.get("ok") is False or result.get("error") or result.get("status") == "error":
        return _error(str(result.get("error") or result.get("message") or "Dedicated read failed"),
                      str(result.get("error_code") or "READ_FAILED"), data=result)
    if "element_id" in arguments and result.get("element_id") != arguments["element_id"]:
        return _error("Dedicated read did not return the requested element ID", "ELEMENT_ID_MISMATCH", data=result)
    if "parameter_name" in arguments and (
        result.get("parameter_name") != arguments["parameter_name"] or "value" not in result
    ):
        return _error("Dedicated read did not return the requested parameter value", "INVALID_PARAMETER_RESULT", data=result)
    return {"success": True, "status": "success", "data": result}


async def _read(
    execute: Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]],
    tool: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    try:
        result = await execute(tool, arguments)
    except Exception as exc:
        result = exc
    return _classify(result, arguments)


def _document_section(result: dict[str, Any]) -> dict[str, Any]:
    if result["success"]:
        data = result["data"]
        if not isinstance(data.get("title"), str) or not data["title"].strip() or not isinstance(data.get("path"), str):
            return _error("Document read did not return a title and path", "DOCUMENT_UNVERIFIED")
        # Return only the identity needed for this inspection, rather than all project metadata.
        result["data"] = {key: data[key] for key in ("title", "path", "is_family", "is_workshared") if key in data}
    return result


async def _document(execute: Callable[..., Awaitable[dict[str, Any]]]) -> dict[str, Any]:
    return _document_section(await _read(execute, "revit_get_document_info", {}))


ReadBatch = Callable[[list[tuple[str, dict[str, Any]]]], Awaitable[list[Any]]]


async def _batched_reads(
    execute_batch: ReadBatch, ids: list[int], names: list[str]
) -> tuple[dict[int, tuple[dict[str, Any], list[dict[str, Any]]]], dict[str, Any]] | None:
    """Element reads plus the closing document read through the read batch (#277), in the same
    order as the one-by-one path. None when the batch cannot be used; the caller then reads one by one."""
    calls: list[tuple[str, dict[str, Any]]] = []
    for element_id in ids:
        calls.append(("revit_get_element_geometry", {"element_id": element_id}))
        calls.extend(("revit_get_parameter_value", {"element_id": element_id, "parameter_name": name}) for name in names)
    calls.append(("revit_get_document_info", {}))
    try:
        answers = await execute_batch(calls)
    except Exception:
        return None
    if not isinstance(answers, list) or len(answers) != len(calls):
        return None
    sections = iter(zip(calls, answers))
    per_element: dict[int, tuple[dict[str, Any], list[dict[str, Any]]]] = {}
    for element_id in ids:
        (_, geometry_args), geometry_answer = next(sections)
        geometry = _classify(geometry_answer, geometry_args)
        parameters = []
        for name in names:
            (_, parameter_args), parameter_answer = next(sections)
            parameters.append({"parameter_name": name, **_classify(parameter_answer, parameter_args)})
        per_element[element_id] = (geometry, parameters)
    (_, document_args), document_answer = next(sections)
    return per_element, _document_section(_classify(document_answer, document_args))


async def inspect_elements(
    execute: Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]],
    arguments: dict[str, Any],
    execute_batch: ReadBatch | None = None,
) -> dict[str, Any]:
    """execute_batch, when given, runs the element reads and the closing document read in groups
    (RevitProvider.execute_read_batch): fewer Revit turns, same reads, same order, same result shape."""
    ids, names, expected = validate_inspection(arguments)
    before = await _document(execute)
    guard_error = None
    if not before["success"]:
        guard_error = "DOCUMENT_UNVERIFIED"
    elif expected is not None and before["data"]["title"] != expected:
        guard_error = "DOCUMENT_TITLE_MISMATCH"

    batched = None
    if execute_batch is not None and not guard_error:
        batched = await _batched_reads(execute_batch, ids, names)

    elements = []
    for element_id in ids:
        if guard_error:
            skipped = {"success": False, "status": "skipped", "error": {
                "code": guard_error, "message": "Element read skipped because the initial document guard failed",
            }}
            geometry = dict(skipped)
            parameters = [{"parameter_name": name, **skipped} for name in names]
        elif batched is not None:
            geometry, parameters = batched[0][element_id]
        else:
            # Await every read in order. No concurrent Revit user-interface requests.
            geometry = await _read(execute, "revit_get_element_geometry", {"element_id": element_id})
            parameters = []
            for name in names:
                value = await _read(execute, "revit_get_parameter_value", {
                    "element_id": element_id, "parameter_name": name,
                })
                parameters.append({"parameter_name": name, **value})
        sections = [geometry, *parameters]
        elements.append({
            "element_id": element_id,
            "success": all(section["success"] for section in sections),
            "geometry": geometry,
            "parameters": parameters,
        })

    if guard_error:
        after = {"success": False, "status": "skipped", "reason": "Initial document guard failed"}
    elif batched is not None:
        after = batched[1]
    else:
        after = await _document(execute)
    unchanged = bool(before["success"] and after["success"] and before["data"] == after["data"])
    sections = [section for element in elements for section in [element["geometry"], *element["parameters"]]]
    succeeded = sum(section["success"] for section in sections)
    failed = sum(section["status"] == "error" for section in sections)
    skipped_count = sum(section["status"] == "skipped" for section in sections)
    complete = unchanged and succeeded == len(sections)
    return {
        "success": complete,
        "document": {"before": before, "after": after, "unchanged_at_endpoints": unchanged,
                     "expected_title": expected, "guard_error": guard_error},
        "elements": elements,
        "completeness": {
            "complete": complete, "requested_elements": len(ids),
            "successful_elements": sum(element["success"] for element in elements),
            "requested_sections": len(sections), "successful_sections": succeeded,
            "failed_sections": failed, "skipped_sections": skipped_count,
            "document_verified_at_endpoints": unchanged,
        },
        "units": {"geometry_length": "ft", "geometry_area": "ft^2", "geometry_volume": "ft^3",
                  "parameters": "Values are returned unchanged by get_parameter_value; formatted strings may use document display units."},
        "limitations": [
            "Sequential dedicated reads are not an atomic snapshot; endpoint document checks cannot detect a switch away and back or edits between reads.",
            "Completeness covers requested reads only. Null geometry fields remain null; omitted parameters are not inspected.",
        ],
    }
