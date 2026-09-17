"""Registered MongoDB operations for compact admission visual metadata (v2.0.0)."""
from datetime import datetime, timezone
import re
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.app.data_access.operation_gateway import OperationSpec, register_operation
from backend.app.models.mongo_models import CutoffBoxItem

HEAVY_PROJECTION = {"image_base64": 0, "image_data": 0, "binary": 0, "blob": 0}


class AdmissionVisualDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")
    visual_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")
    major_code: str = Field(default="", max_length=32)
    category: str = Field(default="all", max_length=64)
    title: str = Field(default="", max_length=256)
    faculty: Optional[str] = Field(default="", max_length=128)
    duration: Optional[str] = Field(default="", max_length=64)
    tuition: Optional[str] = Field(default="", max_length=128)
    subject_combinations: List[str] = Field(default_factory=list)
    career_highlights: List[str] = Field(default_factory=list)
    cutoff_boxes: List[CutoffBoxItem] = Field(default_factory=list)
    scholarship_highlight: Optional[str] = Field(default=None, max_length=500)
    source_url: Optional[str] = Field(default=None, max_length=500)
    type: str = Field(default="admission_visual", max_length=64)
    storage_key: Optional[str] = Field(default=None, max_length=255)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @field_validator("created_at", "updated_at", mode="before")
    @classmethod
    def forbid_string_datetime(cls, v: Any, info) -> Optional[datetime]:
        if v is None:
            return None
        if isinstance(v, str):
            raise ValueError(f"{info.field_name} phải là datetime (BSON Date), không chấp nhận chuỗi (string) trong write operation")
        if isinstance(v, datetime):
            return v
        raise ValueError(f"{info.field_name} không đúng định dạng datetime")


# Parameter Models
class GetAdmissionVisualParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    visual_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")


class ListAdmissionVisualsParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category: str = Field(default="all", max_length=64)
    search: str = Field(default="", max_length=100)
    limit: int = Field(default=100, ge=1, le=100)


class SaveAdmissionVisualParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    visual_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")
    document: AdmissionVisualDocument


# Output Models
class AdmissionVisualOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    __nullable__ = True
    visual_id: Optional[str] = None
    major_code: Optional[str] = ""
    category: Optional[str] = "all"
    title: Optional[str] = ""
    faculty: Optional[str] = ""
    duration: Optional[str] = ""
    tuition: Optional[str] = ""
    subject_combinations: List[str] = Field(default_factory=list)
    career_highlights: List[str] = Field(default_factory=list)
    cutoff_boxes: List[CutoffBoxItem] = Field(default_factory=list)
    scholarship_highlight: Optional[str] = None
    source_url: Optional[str] = None
    type: Optional[str] = "admission_visual"
    storage_key: Optional[str] = None
    created_at: Optional[Union[datetime, str]] = None
    updated_at: Optional[Union[datetime, str]] = None


class SaveAdmissionVisualOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    visual_id: str
    saved: bool


def _get(ctx, params: GetAdmissionVisualParams):
    projection = {"_id": 0, **HEAVY_PROJECTION}
    return ctx.collection("admission_visuals").find_one(
        {"_id": params.visual_id}, projection
    )


def _list(ctx, params: ListAdmissionVisualsParams):
    query: Dict[str, Any] = {}
    if params.category and params.category != "all":
        query["category"] = params.category
    if params.search.strip():
        escaped = re.escape(params.search.strip())
        query["$or"] = [
            {"title": {"$regex": escaped, "$options": "i"}},
            {"major_code": {"$regex": escaped, "$options": "i"}},
            {"visual_id": {"$regex": escaped, "$options": "i"}},
        ]
    projection = {"_id": 0, **HEAVY_PROJECTION}
    return list(
        ctx.collection("admission_visuals")
        .find(query, projection)
        .sort("major_code", 1)
        .limit(params.limit)
    )


def _save(ctx, params: SaveAdmissionVisualParams):
    doc_dict = params.document.model_dump(mode="json")
    for field in HEAVY_PROJECTION:
        doc_dict.pop(field, None)
    doc_dict["visual_id"] = params.visual_id
    doc_dict["updated_at"] = datetime.now(timezone.utc)
    ctx.collection("admission_visuals").update_one(
        {"_id": params.visual_id}, {"$set": doc_dict}, upsert=True
    )
    return {"visual_id": params.visual_id, "saved": True}


GET_ADMISSION_VISUAL = register_operation(OperationSpec(
    key="admission_visual.get",
    version="2.0.0",
    operation_type="read",
    parameter_model=GetAdmissionVisualParams,
    output_model=AdmissionVisualOutput,
    allowed_collections=("admission_visuals",),
    mutation_policy="none",
    handler=_get,
    max_results=1,
    max_output_bytes=64_000,
    max_time_ms=1_500,
    audit_policy="always",
    audit_fail_policy="fail_open",
    declared_checksum="2e8096d5161453f91eebd15232c4f23e91109ad7d3e18efc96bb60b197c75083",
))

LIST_ADMISSION_VISUALS = register_operation(OperationSpec(
    key="admission_visual.list",
    version="2.0.0",
    operation_type="read",
    parameter_model=ListAdmissionVisualsParams,
    output_model=AdmissionVisualOutput,
    allowed_collections=("admission_visuals",),
    mutation_policy="none",
    handler=_list,
    max_results=100,
    max_output_bytes=512_000,
    max_time_ms=2_000,
    audit_policy="always",
    audit_fail_policy="fail_open",
    declared_checksum="c14c09b9cc8265edeaa96bea57fb3b77ef0e9861110bdcd0b8539f02c6b05f40",
))

SAVE_ADMISSION_VISUAL = register_operation(OperationSpec(
    key="admission_visual.save",
    version="2.0.0",
    operation_type="command",
    parameter_model=SaveAdmissionVisualParams,
    output_model=SaveAdmissionVisualOutput,
    allowed_collections=("admission_visuals",),
    mutation_policy="upsert",
    handler=_save,
    max_results=1,
    max_output_bytes=16_000,
    max_time_ms=2_500,
    audit_policy="always",
    audit_fail_policy="fail_open",
    declared_checksum="11914e6128082e75e0a64ea5370a43b4717ca8133c90c41b0d7b8c821507e736",
))
