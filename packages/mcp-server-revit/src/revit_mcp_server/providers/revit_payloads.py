"""Payload builders for Revit tools whose MCP arguments differ from what the add-in handler reads.

contracts/bridge-commands.json is derived from the C# handlers in BridgeCommandFactory.cs and is the
source of truth for each payload. Every builder here returns exactly the keys its handler reads,
omits optional keys the caller did not give (the C# calls GetInt32 or GetBoolean on any key that is
present, so null fails), and raises ValueError with a plain message instead of guessing.
"""
from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

Args = Dict[str, Any]

CSV_MAX_BYTES = 1_000_000
CSV_MAX_ROWS = 1000
DWG_VERSIONS = ("AutoCAD2018", "AutoCAD2013", "AutoCAD2010")

_CSV_NUMBER_HEADERS = ("sheet_number", "number")
_CSV_NAME_HEADERS = ("sheet_name", "name")
_CSV_TITLEBLOCK_HEADERS = ("titleblock_name", "titleblock", "title_block")


def _optional(args: Args, *names: str) -> Args:
    return {name: args[name] for name in names if args.get(name) is not None}


def _pick(args: Args, primary: str, alias: str, tool: str) -> Any:
    """Return args[primary], falling back to the older name; refuse two different values."""
    value, old = args.get(primary), args.get(alias)
    if value is not None and old is not None and value != old:
        raise ValueError(f"{tool}: {primary} and {alias} name the same input; give one of them.")
    return value if value is not None else old


def _need(value: Any, message: str) -> Any:
    if value is None or value == "":
        raise ValueError(message)
    return value


def _int(value: Any, name: str, tool: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{tool}: {name} must be a whole number, got {value!r}.")
    return value


def _int_list(value: Any, name: str, tool: str) -> List[int]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{tool}: {name} must be a non-empty list of ElementIds.")
    return [_int(v, f"{name} item", tool) for v in value]


# ---------------------------------------------------------------- placement and annotation


def placement_location(args: Args, tool: str) -> Dict[str, Any]:
    """location {x, y, z} from a location object or flat x/y/z; refuse when x or y is missing."""
    location = args.get("location")
    if location is not None:
        if not isinstance(location, dict):
            raise ValueError("location must be an object with x, y, and optional z coordinates")
        source = location
    else:
        source = args
    x, y, z = source.get("x"), source.get("y"), source.get("z", 0)
    if x is None or y is None:
        raise ValueError(f"{tool} needs a position: give x and y, or location {{x, y}}. Nothing was sent to Revit.")
    return {"x": x, "y": y, "z": 0 if z is None else z}


def hosted_opening(tool: str) -> Callable[[Args], Args]:
    def build(args: Args) -> Args:
        return {
            "wall_id": args.get("wall_id"),
            "location": placement_location(args, tool),
            **_optional(args, "family_name", "type_name", "hand_flipped", "facing_flipped"),
        }

    return build


def text_note(args: Args) -> Args:
    return {
        "text": args.get("text"),
        "location": {"x": args.get("x"), "y": args.get("y"), "z": 0},
        **_optional(args, "view_id"),
    }


def tag(args: Args) -> Args:
    return {
        "element_id": args.get("element_id"),
        "location": {"x": args.get("x"), "y": args.get("y"), "z": 0},
        **_optional(args, "view_id"),
    }


def element_material(args: Args) -> Args:
    return {
        "element_id": args.get("element_id"),
        "material_name": args.get("material_name"),
        **_optional(args, "face_index"),
    }


def edit_family(args: Args) -> Args:
    payload = _optional(args, "family_name", "family_symbol_id", "family_instance_id")
    if not payload:
        raise ValueError(
            "revit_edit_family needs family_name, family_symbol_id or family_instance_id. Nothing was sent to Revit."
        )
    return payload


# ---------------------------------------------------------------- views and export


def floor_plan_view(args: Args) -> Args:
    level = _need(_pick(args, "level_name", "level", "revit_create_floor_plan_view"),
                  "revit_create_floor_plan_view needs level_name.")
    payload: Args = {"level": level}
    name = _pick(args, "view_name", "name", "revit_create_floor_plan_view")
    if name is not None:
        payload["name"] = name
    return payload


def export_dwg(args: Args, resolve: Optional[Callable[[Path], Path]] = None) -> Args:
    """``resolve`` is the provider's workspace check; its absolute result is what the add-in gets,
    so a relative folder never reaches Revit (whose working folder differs from the server's)."""
    tool = "revit_export_dwg"
    view_id = _int(_need(args.get("view_id"), f"{tool} needs view_id."), "view_id", tool)
    directory = args.get("output_directory")
    old = args.get("output_path")
    if old is not None:
        if Path(str(old)).suffix:
            raise ValueError(
                f"{tool}: the add-in names each DWG after its view, so it needs a folder, not a file name. "
                f"Pass output_directory (a folder inside the workspace) instead of output_path '{old}'."
            )
        if directory is not None and directory != old:
            raise ValueError(f"{tool}: output_directory and output_path name the same input; give one of them.")
        directory = directory if directory is not None else old
    directory = _need(directory, f"{tool} needs output_directory, a folder inside the workspace.")
    if not isinstance(directory, str):
        raise ValueError(f"{tool}: output_directory must be a folder path (text).")
    if resolve is not None:
        directory = str(resolve(Path(directory)))
    payload: Args = {"view_ids": [view_id], "output_directory": directory}
    version = args.get("dwg_version")
    if version is not None:
        if version not in DWG_VERSIONS:
            raise ValueError(f"{tool}: dwg_version must be one of {', '.join(DWG_VERSIONS)}.")
        payload["dwg_version"] = version
    return payload


# ---------------------------------------------------------------- parameters


def batch_set_parameters(args: Args) -> Args:
    tool = "revit_batch_set_parameters"
    ids = _int_list(args.get("element_ids"), "element_ids", tool)
    name = _need(args.get("parameter_name"), f"{tool} needs parameter_name.")
    if args.get("value") is None:
        raise ValueError(f"{tool} needs value.")
    return {"updates": [{"element_id": i, "parameter_name": name, "value": args["value"]} for i in ids]}


def set_type_parameter(args: Args) -> Args:
    tool = "revit_set_type_parameter"
    type_id = _need(_pick(args, "type_id", "element_id", tool), f"{tool} needs type_id.")
    if args.get("value") is None:
        raise ValueError(f"{tool} needs value.")
    return {
        "type_id": _int(type_id, "type_id", tool),
        "parameter_name": _need(args.get("parameter_name"), f"{tool} needs parameter_name."),
        "value": args["value"],
    }


def shared_parameter(args: Args) -> Args:
    categories = args.get("categories")
    if categories is None:
        categories = []
    if not isinstance(categories, list) or not all(isinstance(c, str) for c in categories):
        raise ValueError("revit_create_shared_parameter: categories must be a list of category names.")
    return {
        "name": args.get("name"),
        "parameter_type": args.get("type") or "Text",
        "group_name": args.get("group") or "General",
        "categories": categories,
    }


def project_parameter(args: Args) -> Args:
    is_instance = args.get("is_instance", True)
    if not isinstance(is_instance, bool):
        raise ValueError("revit_create_project_parameter: is_instance must be true or false.")
    return {
        "name": args.get("name"),
        "parameter_type": args.get("type") or "Text",
        "group": args.get("group") or "General",
        "is_instance": is_instance,
    }


# ---------------------------------------------------------------- sheets


def create_sheet(args: Args) -> Args:
    tool = "revit_create_sheet"
    if args.get("titleblock_id") is not None:
        raise ValueError(
            f"{tool}: the add-in finds the title block by family name, not by ElementId. "
            "Pass titleblock_name (revit_list_titleblocks lists them). Nothing was sent to Revit."
        )
    return {
        "sheet_number": _need(_pick(args, "number", "sheet_number", tool), f"{tool} needs number."),
        "sheet_name": _need(_pick(args, "name", "sheet_name", tool), f"{tool} needs name."),
        **_optional(args, "titleblock_name"),
    }


def duplicate_sheet(args: Args) -> Args:
    tool = "revit_duplicate_sheet"
    option = args.get("duplicate_option")
    if option is not None and option != "Duplicate":
        raise ValueError(
            f"{tool}: the add-in makes a plain duplicate only (duplicate_option 'Duplicate'); "
            "use with_views to copy the viewports. Nothing was sent to Revit."
        )
    payload: Args = {
        "source_sheet_id": _need(_pick(args, "sheet_id", "source_sheet_id", tool), f"{tool} needs sheet_id."),
        "new_sheet_number": _need(args.get("new_sheet_number"), f"{tool} needs new_sheet_number."),
        "new_sheet_name": _need(args.get("new_sheet_name"), f"{tool} needs new_sheet_name."),
    }
    with_views = _pick(args, "with_views", "duplicate_viewports", tool)
    if with_views is not None:
        payload["duplicate_viewports"] = bool(with_views)
    return payload


def renumber_sheets(args: Args) -> Args:
    tool = "revit_renumber_sheets"
    sheets = args.get("sheets")
    if sheets is not None:
        if any(args.get(k) is not None for k in ("sheet_ids", "start_number", "prefix")):
            raise ValueError(f"{tool}: give sheets, or sheet_ids with start_number and prefix, not both.")
        if not isinstance(sheets, list) or not sheets:
            raise ValueError(f"{tool}: sheets must be a non-empty list of {{sheet_id, new_sheet_number}}.")
        items = []
        for i, item in enumerate(sheets):
            if not isinstance(item, dict):
                raise ValueError(f"{tool}: sheets[{i}] must be an object with sheet_id and new_sheet_number.")
            number = item.get("new_sheet_number")
            if not isinstance(number, str) or not number:
                raise ValueError(f"{tool}: sheets[{i}].new_sheet_number must be a non-empty string.")
            items.append({"sheet_id": _int(item.get("sheet_id"), f"sheets[{i}].sheet_id", tool),
                          "new_sheet_number": number})
    else:
        if args.get("sheet_ids") is None:
            raise ValueError(
                f"{tool} needs the sheets to renumber: pass sheet_ids in the new order (revit_list_sheets lists "
                "them) with start_number and an optional prefix, or pass sheets [{sheet_id, new_sheet_number}]. "
                "Nothing was sent to Revit."
            )
        ids = _int_list(args.get("sheet_ids"), "sheet_ids", tool)
        start = _int(_need(args.get("start_number"), f"{tool} needs start_number with sheet_ids."),
                     "start_number", tool)
        prefix = args.get("prefix") or ""
        items = [{"sheet_id": sid, "new_sheet_number": f"{prefix}{start + i}"} for i, sid in enumerate(ids)]
    seen_ids = [it["sheet_id"] for it in items]
    seen_numbers = [it["new_sheet_number"] for it in items]
    if len(set(seen_ids)) != len(seen_ids):
        raise ValueError(f"{tool}: a sheet is listed twice. List each sheet once.")
    if len(set(seen_numbers)) != len(seen_numbers):
        raise ValueError(f"{tool}: two sheets would get the same number. Give each sheet its own number.")
    return {"sheets": items}


def _csv_column(headers: Dict[str, str], names: tuple, tool: str, required: bool) -> str | None:
    for name in names:
        if name in headers:
            return headers[name]
    if required:
        raise ValueError(f"{tool}: the CSV needs a column named {names[0]} (or {names[1]}).")
    return None


def sheets_from_csv(path: Path, titleblock_name: Any = None) -> Args:
    """Read sheet_number, sheet_name and optional titleblock_name rows from a CSV inside the workspace."""
    tool = "revit_batch_create_sheets_from_csv"
    if not path.is_file():
        raise ValueError(f"{tool}: no CSV file at {path}.")
    if path.stat().st_size > CSV_MAX_BYTES:
        raise ValueError(f"{tool}: the CSV is larger than {CSV_MAX_BYTES} bytes.")
    return sheets_from_csv_bytes(path.read_bytes(), titleblock_name)


def sheets_from_csv_bytes(data: bytes, titleblock_name: Any = None) -> Args:
    """Parse CSV content already read (and, for a planned call, checked against its approved digest)."""
    tool = "revit_batch_create_sheets_from_csv"
    if len(data) > CSV_MAX_BYTES:
        raise ValueError(f"{tool}: the CSV is larger than {CSV_MAX_BYTES} bytes.")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ValueError(f"{tool}: the CSV is not UTF-8 text.") from None
    reader = csv.DictReader(io.StringIO(text))
    headers = {(h or "").strip().lower().replace(" ", "_"): h for h in (reader.fieldnames or [])}
    number_col = _csv_column(headers, _CSV_NUMBER_HEADERS, tool, True)
    name_col = _csv_column(headers, _CSV_NAME_HEADERS, tool, True)
    tb_col = _csv_column(headers, _CSV_TITLEBLOCK_HEADERS, tool, False)
    sheets: List[Args] = []
    numbers: set = set()
    for line, row in enumerate(reader, start=2):
        values = [str(v or "").strip() for v in row.values() if not isinstance(v, list)]
        if not any(values):
            continue
        number = str(row.get(number_col) or "").strip()
        name = str(row.get(name_col) or "").strip()
        if not number or not name:
            raise ValueError(f"{tool}: CSV line {line} needs both a sheet number and a sheet name.")
        if number in numbers:
            raise ValueError(f"{tool}: sheet number {number} appears twice in the CSV (line {line}).")
        numbers.add(number)
        item: Args = {"sheet_number": number, "sheet_name": name}
        block = (str(row.get(tb_col) or "").strip() if tb_col else "") or titleblock_name
        if block:
            item["titleblock_name"] = block
        sheets.append(item)
        if len(sheets) > CSV_MAX_ROWS:
            raise ValueError(f"{tool}: the CSV has more than {CSV_MAX_ROWS} sheets. Split it into smaller files.")
    if not sheets:
        raise ValueError(f"{tool}: the CSV has no sheet rows.")
    return {"sheets": sheets}
