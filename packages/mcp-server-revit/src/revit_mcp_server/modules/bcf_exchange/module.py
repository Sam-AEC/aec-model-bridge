"""
bcf_exchange module - BCF 2.1 issue export / import.

Commands:
  export_bcf - write a list of issues (and optionally the QA/QC issue store) to a .bcfzip.
  import_bcf - read a .bcfzip back into a plain list of issues.

UNVERIFIED: the BCF structure is written from general knowledge of BCF 2.1. It has
NOT been validated against buildingSMART's XSDs or opened in any other BCF tool.
The module never touches the Revit model; the only file it writes is the .bcfzip.

Safety: zip files are only ever read in memory (nothing is extracted to disk) and
are checked for path traversal, absolute paths, symlinks, too many entries and
decompression bombs. XML containing a DOCTYPE or ENTITY declaration is refused
before parsing, which blocks entity expansion and external entities.
"""
from __future__ import annotations

import os
import re
import sqlite3
import stat
import tempfile
import uuid
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Optional

BCF_EXTENSION = ".bcfzip"
MAX_ENTRIES = 5000
MAX_ENTRY_BYTES = 10 * 1024 * 1024
MAX_TOTAL_BYTES = 100 * 1024 * 1024
MAX_RATIO = 200  # uncompressed / compressed, for entries over 1 MiB
MAX_TOPICS = 2000
MAX_COMPONENTS_PER_TOPIC = 10000
QAQC_DB = "qaqc_issues.db"

_IFC_GUID_RE = re.compile(r"^[0-9A-Za-z_$]{22}$")
_BAD_XML_CHARS = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff￾￿]")
_GUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


class BcfError(ValueError):
    pass


# ---------------------------------------------------------------------------
# Path sandbox
# ---------------------------------------------------------------------------

def _resolve_in_workspace(path_str: str, workspace: Any) -> Path:
    roots = [Path(r).resolve() for r in getattr(workspace, "allowed_directories", []) or []]
    if not roots:
        raise BcfError("A workspace is required.")
    if not path_str or "\x00" in path_str:
        raise BcfError("A file path is required.")
    candidate = Path(path_str)
    if not candidate.is_absolute():
        candidate = roots[0] / candidate
    resolved = candidate.resolve()
    if not any(resolved.is_relative_to(r) for r in roots):
        raise BcfError(f"'{resolved}' is outside the allowed workspace directories.")
    return resolved


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clean(text: Any) -> str:
    return _BAD_XML_CHARS.sub("", "" if text is None else str(text))


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _as_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    return [str(v) for v in value if v not in (None, "")]


def _qaqc_issues(workspace: Any) -> List[Dict[str, Any]]:
    db = Path(workspace.allowed_directories[0]) / QAQC_DB
    if not db.exists():
        return []
    conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("SELECT * FROM issues").fetchall()
    finally:
        conn.close()
    sev_to_prio = {"error": "High", "warning": "Normal", "info": "Low"}
    out = []
    for row in rows:
        r = dict(row)
        out.append({
            "id": r.get("id"),
            "title": f"{r.get('rule_id')}: {r.get('label') or ''}".strip(": "),
            "description": r.get("message") or "",
            "status": "Closed" if r.get("status") == "resolved" else "Open",
            "priority": sev_to_prio.get(r.get("severity"), "Normal"),
            "element_uids": _as_list(r.get("element_uid")),
            "created": r.get("created_at"),
        })
    return out


def _normalise_issue(raw: Any, index: int) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        raise BcfError(f"Issue {index + 1} must be an object with a title and description.")
    guid = str(raw.get("id") or raw.get("guid") or "")
    if not _GUID_RE.match(guid):
        guid = str(uuid.uuid4())
    title = _clean(raw.get("title")).strip() or f"Issue {index + 1}"
    return {
        "id": guid.lower(),
        "title": title,
        "description": _clean(raw.get("description") or raw.get("message")),
        "status": _clean(raw.get("status")) or "Open",
        "priority": _clean(raw.get("priority")),
        "author": _clean(raw.get("author")) or "aec-model-bridge",
        "assigned_to": _clean(raw.get("assigned_to")),
        "created": _clean(raw.get("created")) or _now(),
        "element_uids": [_clean(x) for x in _as_list(raw.get("element_uids"))],
        "ifc_guids": [_clean(x) for x in _as_list(raw.get("ifc_guids"))],
    }


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------

def _xml_bytes(root: ET.Element) -> bytes:
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _build_markup(issue: Dict[str, Any]) -> bytes:
    root = ET.Element("Markup")
    header = ET.SubElement(root, "Header")
    ET.SubElement(header, "File", {"IsExternal": "false"})
    topic = ET.SubElement(root, "Topic", {"Guid": issue["id"], "TopicType": "Issue", "TopicStatus": issue["status"]})
    ET.SubElement(topic, "Title").text = issue["title"]
    if issue["priority"]:
        ET.SubElement(topic, "Priority").text = issue["priority"]
    ET.SubElement(topic, "CreationDate").text = issue["created"]
    ET.SubElement(topic, "CreationAuthor").text = issue["author"]
    if issue["assigned_to"]:
        ET.SubElement(topic, "AssignedTo").text = issue["assigned_to"]
    if issue["description"]:
        ET.SubElement(topic, "Description").text = issue["description"]
    if issue["element_uids"] or issue["ifc_guids"]:
        vp = ET.SubElement(root, "Viewpoints", {"Guid": str(uuid.uuid4())})
        ET.SubElement(vp, "Viewpoint").text = "viewpoint.bcfv"
    return _xml_bytes(root)


def _build_viewpoint(issue: Dict[str, Any]) -> bytes:
    root = ET.Element("VisualizationInfo", {"Guid": str(uuid.uuid4())})
    comps = ET.SubElement(root, "Components")
    sel = ET.SubElement(comps, "Selection")
    for guid in issue["ifc_guids"]:
        ET.SubElement(sel, "Component", {"IfcGuid": guid})
    for uid in issue["element_uids"]:
        if _IFC_GUID_RE.match(uid):
            ET.SubElement(sel, "Component", {"IfcGuid": uid})
        else:
            # Revit UniqueIds are not IFC GUIDs; keep them as the authoring-tool id.
            comp = ET.SubElement(sel, "Component", {"OriginatingSystem": "Revit"})
            ET.SubElement(comp, "AuthoringToolId").text = uid
    return _xml_bytes(root)


def _write_bcf(path: Path, issues: List[Dict[str, Any]], project_name: str) -> None:
    version = ET.Element("Version", {"VersionId": "2.1"})
    ET.SubElement(version, "DetailedVersion").text = "2.1"
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    os.close(fd)
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("bcf.version", _xml_bytes(version))
            if project_name:
                proj = ET.Element("ProjectExtension")
                p = ET.SubElement(proj, "Project", {"ProjectId": str(uuid.uuid4())})
                ET.SubElement(p, "Name").text = project_name
                zf.writestr("project.bcfp", _xml_bytes(proj))
            for issue in issues:
                zf.writestr(f"{issue['id']}/markup.bcf", _build_markup(issue))
                if issue["element_uids"] or issue["ifc_guids"]:
                    zf.writestr(f"{issue['id']}/viewpoint.bcfv", _build_viewpoint(issue))
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


# ---------------------------------------------------------------------------
# Reading (hardened)
# ---------------------------------------------------------------------------

def _check_member_name(name: str) -> None:
    if not name or "\x00" in name or "\\" in name:
        raise BcfError(f"Unsafe entry name in zip: {name!r}")
    if name.startswith("/") or re.match(r"^[A-Za-z]:", name):
        raise BcfError(f"Absolute path in zip: {name!r}")
    if ".." in PurePosixPath(name).parts:
        raise BcfError(f"Path traversal in zip: {name!r}")


def _read_member(zf: zipfile.ZipFile, info: zipfile.ZipInfo) -> bytes:
    # Do not trust the declared size: read with a hard cap.
    with zf.open(info) as fh:
        data = fh.read(MAX_ENTRY_BYTES + 1)
    if len(data) > MAX_ENTRY_BYTES:
        raise BcfError(f"Zip entry '{info.filename}' is too large (limit {MAX_ENTRY_BYTES} bytes).")
    return data


def _safe_xml(data: bytes, name: str) -> ET.Element:
    # UTF-16/32 would hide the markers below; BCF is UTF-8.
    if data[:2] in (b"\xff\xfe", b"\xfe\xff") or b"\x00" in data[:4]:
        raise BcfError(f"'{name}' must be UTF-8 XML.")
    upper = data.upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise BcfError(f"'{name}' contains a DOCTYPE/ENTITY declaration, which is not allowed.")
    try:
        return ET.fromstring(data)
    except ET.ParseError as exc:
        raise BcfError(f"'{name}' is not valid XML: {exc}") from exc


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child_text(parent: ET.Element, name: str) -> str:
    for ch in parent:
        if _local(ch.tag) == name:
            return (ch.text or "").strip()
    return ""


def _parse_topic(markup: ET.Element, viewpoints: List[ET.Element]) -> Dict[str, Any]:
    topic = next((c for c in markup if _local(c.tag) == "Topic"), None)
    if topic is None:
        raise BcfError("markup.bcf has no Topic element.")
    ifc_guids: List[str] = []
    element_uids: List[str] = []
    for vp in viewpoints:
        count = 0
        for comp in vp.iter():
            if _local(comp.tag) != "Component":
                continue
            count += 1
            if count > MAX_COMPONENTS_PER_TOPIC:
                raise BcfError("Too many components in one viewpoint.")
            guid = comp.attrib.get("IfcGuid")
            if guid and guid not in ifc_guids:
                ifc_guids.append(guid)
            for ch in comp:
                if _local(ch.tag) == "AuthoringToolId" and ch.text and ch.text.strip() not in element_uids:
                    element_uids.append(ch.text.strip())
    return {
        "id": topic.attrib.get("Guid", ""),
        "title": _child_text(topic, "Title"),
        "description": _child_text(topic, "Description"),
        "status": topic.attrib.get("TopicStatus", ""),
        "priority": _child_text(topic, "Priority"),
        "author": _child_text(topic, "CreationAuthor"),
        "assigned_to": _child_text(topic, "AssignedTo"),
        "created": _child_text(topic, "CreationDate"),
        "element_uids": element_uids,
        "ifc_guids": ifc_guids,
    }


def _read_bcf(path: Path) -> Dict[str, Any]:
    try:
        zf = zipfile.ZipFile(path)
    except zipfile.BadZipFile as exc:
        raise BcfError("The file is not a valid zip/.bcfzip archive.") from exc
    with zf:
        infos = zf.infolist()
        if len(infos) > MAX_ENTRIES:
            raise BcfError(f"Too many entries in zip ({len(infos)}; limit {MAX_ENTRIES}).")
        total = 0
        for info in infos:
            _check_member_name(info.filename)
            if stat.S_ISLNK(info.external_attr >> 16):
                raise BcfError(f"Symbolic link in zip: {info.filename!r}")
            total += info.file_size
            if info.file_size > MAX_ENTRY_BYTES:
                raise BcfError(f"Zip entry '{info.filename}' is too large.")
            if info.file_size > 1024 * 1024 and info.compress_size and info.file_size / info.compress_size > MAX_RATIO:
                raise BcfError(f"Zip entry '{info.filename}' has a suspicious compression ratio.")
        if total > MAX_TOTAL_BYTES:
            raise BcfError("Zip is too large when uncompressed.")

        by_name = {i.filename: i for i in infos if not i.is_dir()}
        version = ""
        if "bcf.version" in by_name:
            vroot = _safe_xml(_read_member(zf, by_name["bcf.version"]), "bcf.version")
            version = vroot.attrib.get("VersionId", "")

        folders = sorted({n.split("/", 1)[0] for n in by_name if n.count("/") == 1 and n.endswith("/markup.bcf")})
        if len(folders) > MAX_TOPICS:
            raise BcfError(f"Too many topics ({len(folders)}; limit {MAX_TOPICS}).")
        issues = []
        for folder in folders:
            markup = _safe_xml(_read_member(zf, by_name[f"{folder}/markup.bcf"]), f"{folder}/markup.bcf")
            vps = [
                _safe_xml(_read_member(zf, by_name[n]), n)
                for n in sorted(by_name)
                if n.startswith(folder + "/") and n.endswith(".bcfv")
            ]
            issue = _parse_topic(markup, vps)
            if not issue["id"]:
                issue["id"] = folder
            issues.append(issue)
    return {"bcf_version": version, "issues": issues}


# ---------------------------------------------------------------------------
# Module class
# ---------------------------------------------------------------------------

class BcfExchangeModule:

    def export_bcf(
        self,
        output_path: str,
        issues: Optional[List[Dict[str, Any]]] = None,
        use_qaqc_issues: bool = False,
        project_name: str = "",
        overwrite: bool = False,
        workspace: Any = None,
        **_,
    ) -> Dict[str, Any]:
        if not output_path.lower().endswith(BCF_EXTENSION):
            raise BcfError(f"The output file name must end in {BCF_EXTENSION}.")
        path = _resolve_in_workspace(output_path, workspace)
        if path.exists() and not overwrite:
            raise BcfError(f"'{path}' already exists. Set overwrite to replace it.")
        raw = list(issues or [])
        if use_qaqc_issues:
            raw.extend(_qaqc_issues(workspace))
        normalised = [_normalise_issue(r, i) for i, r in enumerate(raw)]
        seen = set()
        for issue in normalised:
            if issue["id"] in seen:
                issue["id"] = str(uuid.uuid4())
            seen.add(issue["id"])
        path.parent.mkdir(parents=True, exist_ok=True)
        _write_bcf(path, normalised, _clean(project_name))
        return {
            "status": "written",
            "path": str(path),
            "issue_count": len(normalised),
            "bcf_version": "2.1",
            "warning": "UNVERIFIED: not validated against buildingSMART XSDs or other BCF tools.",
        }

    def import_bcf(self, bcf_path: str, workspace: Any = None, **_) -> Dict[str, Any]:
        path = _resolve_in_workspace(bcf_path, workspace)
        if not path.is_file():
            raise BcfError(f"File '{path}' not found.")
        result = _read_bcf(path)
        return {
            "status": "read",
            "path": str(path),
            "bcf_version": result["bcf_version"],
            "issue_count": len(result["issues"]),
            "issues": result["issues"],
            "warning": "UNVERIFIED: parsing is not validated against buildingSMART XSDs or other BCF tools.",
        }
