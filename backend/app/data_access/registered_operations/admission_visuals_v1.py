"""Registered MongoDB operations for compact admission visual metadata."""
import re
from datetime import datetime, timezone
from typing import Any, Dict

from pydantic import BaseModel, Field

from backend.app.data_access.operation_gateway import OperationSpec, register_operation

HEAVY_PROJECTION = {"image_base64": 0, "image_data": 0, "binary": 0, "blob": 0}


class GetAdmissionVisualParams(BaseModel):
    visual_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")


class ListAdmissionVisualsParams(BaseModel):
    category: str = Field(default="all", max_length=64)
    search: str = Field(default="", max_length=100)
    limit: int = Field(default=100, ge=1, le=100)


class SaveAdmissionVisualParams(BaseModel):
    visual_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")
    document: Dict[str, Any]


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
    document = dict(params.document)
    for field in HEAVY_PROJECTION:
        document.pop(field, None)
    document["visual_id"] = params.visual_id
    document["updated_at"] = datetime.now(timezone.utc)
    ctx.collection("admission_visuals").update_one(
        {"_id": params.visual_id}, {"$set": document}, upsert=True
    )
    return {"visual_id": params.visual_id, "saved": True}


GET_ADMISSION_VISUAL = register_operation(OperationSpec(
    key="admission_visual.get",
    version="1.0.0",
    operation_type="read",
    parameter_model=GetAdmissionVisualParams,
    allowed_collections=("admission_visuals",),
    handler=_get,
    max_results=1,
    max_output_bytes=64_000,
    max_time_ms=1_500,
    declared_checksum="da1f411d322c913cf83a13f281fe84a2045f8b26e901d99a77bda957f7f18f4b",
))

LIST_ADMISSION_VISUALS = register_operation(OperationSpec(
    key="admission_visual.list",
    version="1.0.0",
    operation_type="read",
    parameter_model=ListAdmissionVisualsParams,
    allowed_collections=("admission_visuals",),
    handler=_list,
    max_results=100,
    max_output_bytes=512_000,
    max_time_ms=2_000,
    declared_checksum="b94969feea21f02351647d4d18dc407027fd8dc2fc0f336d185962c08836aa69",
))

SAVE_ADMISSION_VISUAL = register_operation(OperationSpec(
    key="admission_visual.save",
    version="1.0.0",
    operation_type="command",
    parameter_model=SaveAdmissionVisualParams,
    allowed_collections=("admission_visuals",),
    handler=_save,
    max_results=1,
    max_output_bytes=2_000,
    max_time_ms=2_000,
    declared_checksum="96b4c8c2f7e914f174cb7f8bdf62958b25c256dd1ef7027de5ed5513a9453460",
))
