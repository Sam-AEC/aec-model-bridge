from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

class ParamVal(BaseModel):
    v: Any
    storage: str
    instance: bool = True
    readonly: bool = False
    spec: Optional[str] = None

class LocationPoint(BaseModel):
    kind: str = "point"
    xyz: List[float]
    rotation: float = 0.0

class BBox(BaseModel):
    min: List[float]
    max: List[float]

class ElementRecord(BaseModel):
    uid: str
    amb_uid: Optional[str] = None
    element_id: int
    category: str
    cls: str = Field(..., alias="class")
    type_uid: Optional[str] = None
    family: Optional[str] = None
    type_name: Optional[str] = None
    level_uid: Optional[str] = None
    phase_created: Optional[int] = None
    phase_demolished: Optional[int] = None
    design_option: Optional[str] = None
    workset: Optional[str] = None
    group_uid: Optional[str] = None
    host_uid: Optional[str] = None
    room_uids: Dict[str, str] = Field(default_factory=dict)
    location: Optional[LocationPoint] = None
    bbox: Optional[BBox] = None
    params: Dict[str, ParamVal] = Field(default_factory=dict)
    geometry_ref: Optional[Dict[str, Any]] = None
    materials: List[str] = Field(default_factory=list)

    class Config:
        populate_by_name = True

class RelationRecord(BaseModel):
    kind: str
    from_id: str = Field(..., alias="from")
    to_id: str = Field(..., alias="to")

    class Config:
        populate_by_name = True

class TypeRecord(BaseModel):
    uid: str
    category: str
    family: str
    type_name: str
    params: Dict[str, ParamVal] = Field(default_factory=dict)
    family_source: str = "loadable"  # system | loadable | inplace

class SourceMetadata(BaseModel):
    app: str = "revit"
    app_version: str = "2025.2"
    doc_guid: str = ""
    central_guid: str = ""
    doc_title: str = ""
    units: str = "SI"
    phase_map: Dict[str, str] = Field(default_factory=dict)

class Snapshot(BaseModel):
    schema_ver: str = Field("amb.snapshot/1", alias="schema")
    snapshot_id: str
    taken_at: datetime = Field(default_factory=datetime.utcnow)
    source: SourceMetadata = Field(default_factory=SourceMetadata)
    elements: List[ElementRecord] = Field(default_factory=list)
    relations: List[RelationRecord] = Field(default_factory=list)
    types: List[TypeRecord] = Field(default_factory=list)
    counts: Dict[str, Any] = Field(default_factory=dict)

    class Config:
        populate_by_name = True

class SnapshotDelta(BaseModel):
    snapshot_id: str
    base_snapshot_id: str
    added: List[ElementRecord] = Field(default_factory=list)
    deleted: List[str] = Field(default_factory=list)  # list of UIDs
    modified: List[ElementRecord] = Field(default_factory=list)

class FacadePanel(BaseModel):
    pid: str
    panel_type: str
    corners_m: List[List[float]]
    target_family: str = "AMB_GlassPanel_Adaptive"
    type_map: str = "glass-clear"
    params: Dict[str, Any] = Field(default_factory=dict)
    amb_uid: Optional[str] = None

class FacadeZone(BaseModel):
    schema_ver: str = Field("amb.facade_zone/1", alias="schema")
    zone_id: str
    host: Dict[str, Any]
    grid: Dict[str, Any] = Field(default_factory=dict)
    panels: List[FacadePanel] = Field(default_factory=list)
    counts_expected: Dict[str, int] = Field(default_factory=dict)

    class Config:
        populate_by_name = True
