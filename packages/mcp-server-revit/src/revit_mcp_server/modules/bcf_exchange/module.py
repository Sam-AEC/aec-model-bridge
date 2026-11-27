"""
bcf_exchange module - BCF 2.1 issue export / import.

Commands:
  export_bcf - write a list of issues (and optionally the QA/QC issue store) to a .bcfzip.
  import_bcf - read a .bcfzip back into a plain list of issues.
  list_server_topics / create_server_topic / update_server_topic - BCF 3.0 REST topics
  (see the "BCF 3.0 REST client" section; create and update need an approved plan).

UNVERIFIED: the BCF structure is written from general knowledge of BCF 2.1. It has
NOT been validated against buildingSMART's XSDs or opened in any other BCF tool.
The module never touches the Revit model; the only file it writes is the .bcfzip.

Safety: zip files are only ever read in memory (nothing is extracted to disk) and
are checked for path traversal, absolute paths, symlinks, too many entries and
decompression bombs. XML containing a DOCTYPE or ENTITY declaration is refused
before parsing, which blocks entity expansion and external entities.
"""
from __future__ import annotations
from revit_mcp_server.security.module_permissions import writable_path
from revit_mcp_server.errors import WorkspaceViolation
from revit_mcp_server.security.workspace import base_directory, confine_path

import json
import logging
import os
import re
import sqlite3
import stat
import tempfile
import urllib.error
import urllib.parse
import urllib.request
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

BCF_URL_ENV = "MCP_REVIT_BCF_URL"
BCF_PROJECT_ENV = "MCP_REVIT_BCF_PROJECT_ID"
BCF_TOKEN_ENV = "MCP_REVIT_BCF_TOKEN"
HTTP_TIMEOUT_SECONDS = 15
MAX_RESPONSE_BYTES = 5 * 1024 * 1024
MAX_LIST_TOPICS = 500
_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
_TOPIC_STRING_FIELDS = ("title", "description", "topic_type", "topic_status", "priority",
                        "assigned_to", "due_date", "stage")
_TOPIC_SUMMARY_FIELDS = ("guid", "title", "description", "topic_type", "topic_status", "priority",
                         "assigned_to", "creation_date", "creation_author", "modified_date",
                         "modified_author", "due_date", "stage", "labels")
_PROJECT_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")

logger = logging.getLogger(__name__)

_IFC_GUID_RE = re.compile(r"^[0-9A-Za-z_$]{22}$")
def _is_bad_xml_char(ch: str) -> bool:
    """True for characters that are not allowed in XML 1.0 text."""
    code = ord(ch)
    return (
        code < 0x20 and code not in (0x09, 0x0A, 0x0D)
        or 0xD800 <= code <= 0xDFFF
        or code in (0xFFFE, 0xFFFF)
    )
_GUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


class BcfError(ValueError):
    pass


# ---------------------------------------------------------------------------
# Path sandbox
# ---------------------------------------------------------------------------

def _resolve_in_workspace(path_str: str, workspace: Any) -> Path:
    base = base_directory(workspace)
    if base is None:
        raise BcfError("A workspace is required.")
    if not path_str or "\x00" in path_str:
        raise BcfError("A file path is required.")
    candidate = Path(path_str)
    if not candidate.is_absolute():
        candidate = base / candidate
    try:
        return confine_path(workspace, candidate)
    except WorkspaceViolation as exc:
        raise BcfError(str(exc)) from exc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clean(text: Any) -> str:
    return "".join(ch for ch in ("" if text is None else str(text)) if not _is_bad_xml_char(ch))


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


def _build_markup(issue: Dict[str, Any], viewpoint_guid: str) -> bytes:
    root = ET.Element("Markup")
    header = ET.SubElement(root, "Header")
    ET.SubElement(header, "File", {"isExternal": "false"})
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
        vp = ET.SubElement(root, "Viewpoints", {"Guid": viewpoint_guid})
        ET.SubElement(vp, "Viewpoint").text = "viewpoint.bcfv"
    return _xml_bytes(root)


def _build_viewpoint(issue: Dict[str, Any], viewpoint_guid: str) -> bytes:
    root = ET.Element("VisualizationInfo", {"Guid": viewpoint_guid})
    comps = ET.SubElement(root, "Components")
    sel = ET.SubElement(comps, "Selection")
    for guid in issue["ifc_guids"]:
        ET.SubElement(sel, "Component", {"IfcGuid": guid})
    for uid in issue["element_uids"]:
        if _IFC_GUID_RE.match(uid):
            ET.SubElement(sel, "Component", {"IfcGuid": uid})
        else:
            # Revit UniqueIds are not IFC GUIDs; keep them as the authoring-tool id.
            comp = ET.SubElement(sel, "Component")
            ET.SubElement(comp, "OriginatingSystem").text = "Revit"
            ET.SubElement(comp, "AuthoringToolId").text = uid
    # BCF 2.1 requires Visibility after Selection.
    ET.SubElement(comps, "Visibility", {"DefaultVisibility": "true"})
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
                ET.SubElement(proj, "ExtensionSchema")
                zf.writestr("project.bcfp", _xml_bytes(proj))
            for issue in issues:
                # BCF 2.1 expects an explicit directory entry per topic.
                zf.writestr(zipfile.ZipInfo(f"{issue['id']}/"), b"")
                vp_guid = str(uuid.uuid4())
                zf.writestr(f"{issue['id']}/markup.bcf", _build_markup(issue, vp_guid))
                if issue["element_uids"] or issue["ifc_guids"]:
                    zf.writestr(f"{issue['id']}/viewpoint.bcfv", _build_viewpoint(issue, vp_guid))
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
# BCF 3.0 REST client (topics)
# UNVERIFIED against real BIMcollab or Revizto servers; tested against a local mock only.
# The server URL and the bearer token come ONLY from the environment, never from tool
# arguments, so a model cannot point the token at a server of its choosing. The token is
# never logged, returned or placed in an error message.
# ---------------------------------------------------------------------------

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # a redirect would forward the token to another host
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def _redact(text: str, token: str) -> str:
    return text.replace(token, "[redacted]") if token else text


def _server_base_url() -> str:
    raw = (os.environ.get(BCF_URL_ENV) or "").strip()
    if not raw:
        raise BcfError(f"No BCF server is configured. Set {BCF_URL_ENV} to the server address (for example https://example.test).")
    try:
        parts = urllib.parse.urlsplit(raw)
        host = (parts.hostname or "").lower()
        parts.port  # raises ValueError on a bad port
    except ValueError as exc:
        raise BcfError(f"{BCF_URL_ENV} is not a valid URL.") from exc
    if parts.username is not None or parts.password is not None:
        raise BcfError(f"{BCF_URL_ENV} must not contain a user name or password.")
    if parts.query or parts.fragment:
        raise BcfError(f"{BCF_URL_ENV} must not contain a query or fragment.")
    if not (parts.scheme == "https" or (parts.scheme == "http" and host in _LOCAL_HOSTS)):
        raise BcfError(f"{BCF_URL_ENV} must use https. Plain http is only allowed for 127.0.0.1 and localhost.")
    if not host:
        raise BcfError(f"{BCF_URL_ENV} is not a valid URL.")
    return raw.rstrip("/")


def _server_token() -> str:
    token = (os.environ.get(BCF_TOKEN_ENV) or "").strip()
    if not token:
        raise BcfError(
            f"No BCF credentials. Set {BCF_TOKEN_ENV} in the environment of the server. "
            "The token is never accepted as a tool argument."
        )
    if any(ord(c) < 33 or ord(c) > 126 for c in token):
        raise BcfError(f"{BCF_TOKEN_ENV} is not a valid bearer token.")
    return token


def _project_id(value: Any) -> str:
    pid = str(value if value else os.environ.get(BCF_PROJECT_ENV, "")).strip()
    if not pid:
        raise BcfError(f"A project_id is required (argument, or set {BCF_PROJECT_ENV}).")
    if not _PROJECT_ID_RE.match(pid) or pid in (".", ".."):
        raise BcfError("project_id may only contain letters, digits, '.', '_' and '-'.")
    return pid


def _topic_payload(fields: Dict[str, Any], require_title: bool) -> Dict[str, Any]:
    body: Dict[str, Any] = {}
    for key in _TOPIC_STRING_FIELDS:
        value = fields.get(key)
        if value is None:
            continue
        if not isinstance(value, str) or "\x00" in value:
            raise BcfError(f"'{key}' must be text.")
        body[key] = value
    labels = fields.get("labels")
    if labels is not None:
        if not isinstance(labels, list) or not all(isinstance(x, str) for x in labels):
            raise BcfError("'labels' must be a list of text values.")
        body["labels"] = list(labels)
    if require_title and not str(body.get("title", "")).strip():
        raise BcfError("A topic title is required.")
    if not require_title and not body:
        raise BcfError("Give at least one field to update.")
    return body


def _bcf_request(method: str, path: str, token: str, body: Optional[Dict[str, Any]] = None,
                 query: Optional[Dict[str, Any]] = None) -> Any:
    url = _server_base_url() + path
    if query:
        url += "?" + urllib.parse.urlencode(query)
    data = None
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    logger.info("BCF server request: %s %s", method, path)
    try:
        with _OPENER.open(request, timeout=HTTP_TIMEOUT_SECONDS) as resp:
            raw = resp.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        status = exc.code
        exc.close()
        if status in (401, 403):
            raise BcfError(
                f"The BCF server refused the credentials (HTTP {status}). "
                f"Check {BCF_TOKEN_ENV} and that the token may access this project."
            ) from None
        if status == 404:
            raise BcfError("The BCF server did not find that project or topic (HTTP 404).") from None
        if 300 <= status < 400:
            raise BcfError(f"The BCF server tried to redirect (HTTP {status}). Redirects are not followed; check {BCF_URL_ENV}.") from None
        raise BcfError(f"The BCF server returned an error (HTTP {status}).") from None
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        reason = getattr(exc, "reason", exc)
        raise BcfError(_redact(f"Could not reach the BCF server: {type(reason).__name__}.", token)) from None
    if len(raw) > MAX_RESPONSE_BYTES:
        raise BcfError("The BCF server response is too large.")
    try:
        return json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise BcfError("The BCF server did not return JSON.") from None


def _summarise_topic(topic: Any) -> Dict[str, Any]:
    if not isinstance(topic, dict):
        raise BcfError("The BCF server returned an unexpected topic shape.")
    return {k: topic[k] for k in _TOPIC_SUMMARY_FIELDS if k in topic}


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
        path = writable_path(workspace, _resolve_in_workspace(output_path, workspace))
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

    def list_server_topics(self, project_id: str = "", limit: int = 100, **_) -> Dict[str, Any]:
        pid = _project_id(project_id)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_LIST_TOPICS:
            raise BcfError(f"limit must be a whole number from 1 to {MAX_LIST_TOPICS}.")
        token = _server_token()
        data = _bcf_request("GET", f"/bcf/3.0/projects/{pid}/topics", token, query={"$top": limit})
        if not isinstance(data, list):
            raise BcfError("The BCF server returned an unexpected answer (a list of topics was expected).")
        topics = [_summarise_topic(t) for t in data[:limit]]
        return {
            "status": "read", "project_id": pid, "topic_count": len(topics), "topics": topics,
            "warning": "UNVERIFIED against real BIMcollab or Revizto servers.",
        }

    def create_server_topic(self, project_id: str = "", **fields) -> Dict[str, Any]:
        pid = _project_id(project_id)
        body = _topic_payload(fields, require_title=True)
        token = _server_token()
        data = _bcf_request("POST", f"/bcf/3.0/projects/{pid}/topics", token, body=body)
        return {
            "status": "created", "project_id": pid, "topic": _summarise_topic(data),
            "warning": "UNVERIFIED against real BIMcollab or Revizto servers.",
        }

    def update_server_topic(self, topic_guid: str = "", project_id: str = "", **fields) -> Dict[str, Any]:
        pid = _project_id(project_id)
        if not isinstance(topic_guid, str) or not _GUID_RE.match(topic_guid):
            raise BcfError("topic_guid must be the topic's GUID, for example 3f2b8c1e-0a4d-4c55-9d0e-2b7f5a6c1d10.")
        body = _topic_payload(fields, require_title=False)
        token = _server_token()
        data = _bcf_request("PUT", f"/bcf/3.0/projects/{pid}/topics/{topic_guid}", token, body=body)
        return {
            "status": "updated", "project_id": pid, "topic": _summarise_topic(data),
            "warning": "UNVERIFIED against real BIMcollab or Revizto servers.",
        }
