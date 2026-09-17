"""LTX domain adapter for admission visual reads and commands (v2.0.0)."""
from typing import Any, Dict, Optional

from backend.app.data_access.operation_gateway import execute_registered_operation
from backend.app.data_access.registered_operations.admission_visuals_v2 import (
    GET_ADMISSION_VISUAL,
    LIST_ADMISSION_VISUALS,
    SAVE_ADMISSION_VISUAL,
    AdmissionVisualDocument,
)

GET_CHECKSUM = "52a66bccf078ac9ba1cd486da78b86d37880650ab3c5ee5ee94c66bc1bd11a0b"
LIST_CHECKSUM = "47b159b328c0fbba3246cd611b73adc5becec0252f8474bbaa96688546e6cb3a"
SAVE_CHECKSUM = "12f3073779da2b6778e713fc669ca41c13accefe03cdee2acab361fb04aac87c"


def read_admission_visual(visual_id: str, *, principal_id: str = "system", request_id: str = "internal"):
    return execute_registered_operation(
        key=GET_ADMISSION_VISUAL.key,
        version=GET_ADMISSION_VISUAL.version,
        checksum=GET_CHECKSUM,
        parameters={"visual_id": visual_id},
        principal_id=principal_id,
        request_id=request_id,
    )


def search_admission_visuals(category: str = "all", search: str = "", limit: int = 100,
                             *, principal_id: str = "system", request_id: str = "internal"):
    return execute_registered_operation(
        key=LIST_ADMISSION_VISUALS.key,
        version=LIST_ADMISSION_VISUALS.version,
        checksum=LIST_CHECKSUM,
        parameters={"category": category, "search": search, "limit": limit},
        principal_id=principal_id,
        request_id=request_id,
    )


def persist_admission_visual(document: Dict[str, Any], *, principal_id: str = "system",
                             request_id: str = "internal") -> bool:
    visual_id = str(document.get("visual_id") or document.get("_id") or "")
    doc_copy = dict(document)
    doc_copy.pop("_id", None)
    doc_copy.pop("image_base64", None)
    doc_copy.pop("image_data", None)
    doc_copy.pop("binary", None)
    doc_copy.pop("blob", None)
    doc_copy["visual_id"] = visual_id
    allowed_fields = AdmissionVisualDocument.model_fields.keys()
    cleaned = {k: v for k, v in doc_copy.items() if k in allowed_fields}
    result = execute_registered_operation(
        key=SAVE_ADMISSION_VISUAL.key,
        version=SAVE_ADMISSION_VISUAL.version,
        checksum=SAVE_CHECKSUM,
        parameters={"visual_id": visual_id, "document": cleaned},
        principal_id=principal_id,
        request_id=request_id,
    )
    return bool(result and result.get("saved"))
