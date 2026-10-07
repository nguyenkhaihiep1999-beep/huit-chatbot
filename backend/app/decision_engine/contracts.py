"""
contracts.py
Pydantic models and type contracts for the Decision Engine.
Strictly mapped to canonical schemas:
- huit.decision.decision-request@2.0.0
- huit.decision.decision-result@1.0.0
"""
import math
from typing import Annotated, Any, Dict, List, Literal, Optional, Union
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, field_validator, model_validator


CriteriaDescription = Annotated[str, Field(strict=True, max_length=500)]
ScoreCriteria = Annotated[List[CriteriaDescription], Field(min_length=2, max_length=10)]


class QuestionDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["choice", "score", "noul"] = Field(
        description="Loại câu hỏi System One của Jev"
    )
    instructions: Optional[str] = Field(
        default=None, max_length=1000, description="Hướng dẫn đánh giá"
    )
    criteria: Optional[Union[Dict[str, CriteriaDescription], ScoreCriteria]] = Field(
        default=None, description="Mô tả tiêu chí cho từng lựa chọn (dict cho choice/noul, list cho score)"
    )

    @model_validator(mode="after")
    def validate_criteria_type(self) -> "QuestionDefinition":
        if self.type == "score":
            if not isinstance(self.criteria, list):
                raise ValueError("Score criteria must be an ordered list of 2 to 10 descriptions")
        elif self.criteria is not None and not isinstance(self.criteria, dict):
            raise ValueError("Choice/Noul criteria must be an object")
        return self


class DecisionRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "x-contract-id": "huit.decision.decision-request",
            "x-contract-version": "2.0.0",
        },
    )

    decision_type: Literal["intent", "evidence_sufficiency", "custom"] = Field(
        description="Mục đích ra quyết định"
    )
    state: str = Field(
        ...,
        min_length=1,
        max_length=8192,
        description="Trạng thái đã được làm sạch và khử dữ liệu nhạy cảm",
    )
    model: str = Field(
        default="jev-latest", max_length=64, description="Định danh mô hình Jev"
    )
    questions: Dict[str, QuestionDefinition] = Field(
        ...,
        min_length=1,
        max_length=20,
        description="Danh sách các câu hỏi quyết định",
    )
    context_metadata: Optional[Dict[str, Any]] = Field(
        default=None, description="Metadata phụ trợ cho telemetry ẩn danh"
    )


class DecisionItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["choice", "score", "noul"] = Field(description="Loại quyết định")
    choice: Optional[str] = Field(default=None, description="Lựa chọn được chọn")
    score: Optional[float] = Field(default=None, description="Điểm số đánh giá")
    noul: Optional[float] = Field(
        default=None, ge=0.0, le=1.0, description="Xác suất Có (0.0 đến 1.0)"
    )
    confidence: Optional[float] = Field(
        default=None, ge=0.0, le=1.0, description="Độ tin cậy của mô hình (0.0 đến 1.0, bắt buộc với choice/score)"
    )
    probabilities: Optional[Dict[str, float]] = Field(
        default=None, description="Phân phối xác suất giữa các lựa chọn"
    )

    @field_validator("confidence", "score", "noul", mode="before")
    @classmethod
    def validate_no_boolean(cls, v: Any) -> Any:
        if isinstance(v, bool):
            raise ValueError("Boolean không phải là giá trị số hợp lệ")
        return v

    @field_validator("confidence", mode="after")
    @classmethod
    def validate_confidence(cls, v: Optional[float]) -> Optional[float]:
        if v is not None:
            if math.isnan(v) or math.isinf(v):
                raise ValueError("confidence must be a finite number between 0.0 and 1.0")
            if not (0.0 <= v <= 1.0):
                raise ValueError(f"confidence out of bounds [0.0, 1.0]: {v}")
        return v

    @field_validator("score", mode="after")
    @classmethod
    def validate_score(cls, v: Optional[float]) -> Optional[float]:
        if v is not None:
            if math.isnan(v) or math.isinf(v):
                raise ValueError("score must be a finite number")
        return v

    @field_validator("noul", mode="after")
    @classmethod
    def validate_noul(cls, v: Optional[float]) -> Optional[float]:
        if v is not None:
            if math.isnan(v) or math.isinf(v):
                raise ValueError("noul must be a finite number between 0.0 and 1.0")
            if not (0.0 <= v <= 1.0):
                raise ValueError(f"noul out of bounds [0.0, 1.0]: {v}")
        return v

    @field_validator("probabilities", mode="before")
    @classmethod
    def validate_probabilities_before(cls, v: Any) -> Any:
        if v is not None:
            if not isinstance(v, dict):
                raise ValueError("probabilities phải là một object/dict")
            for k, val in v.items():
                if isinstance(val, bool):
                    raise ValueError(f"Giá trị xác suất cho '{k}' không được là boolean")
        return v

    @field_validator("probabilities", mode="after")
    @classmethod
    def validate_probabilities(cls, v: Optional[Dict[str, float]]) -> Optional[Dict[str, float]]:
        if v is not None:
            for k, val in v.items():
                if math.isnan(val) or math.isinf(val) or not (0.0 <= val <= 1.0):
                    raise ValueError(f"Probability for key '{k}' must be finite between 0.0 and 1.0: {val}")
        return v

    @model_validator(mode="after")
    def validate_item_type_consistency(self) -> "DecisionItem":
        if self.type == "choice":
            if self.choice is None or not str(self.choice).strip():
                raise ValueError("DecisionItem with type='choice' must have a non-empty 'choice'")
            if self.confidence is None:
                raise ValueError("DecisionItem with type='choice' must have 'confidence'")
            if self.score is not None:
                raise ValueError("DecisionItem with type='choice' cannot have 'score'")
            if self.noul is not None:
                raise ValueError("DecisionItem with type='choice' cannot have 'noul'")
        elif self.type == "score":
            if self.score is None:
                raise ValueError("DecisionItem with type='score' must have 'score'")
            if self.confidence is None:
                raise ValueError("DecisionItem with type='score' must have 'confidence'")
            if self.choice is not None:
                raise ValueError("DecisionItem with type='score' cannot have 'choice'")
            if self.noul is not None:
                raise ValueError("DecisionItem with type='score' cannot have 'noul'")
        elif self.type == "noul":
            if self.noul is None:
                raise ValueError("DecisionItem with type='noul' must have 'noul'")
            if self.choice is not None:
                raise ValueError("DecisionItem with type='noul' cannot have 'choice'")
            if self.score is not None:
                raise ValueError("DecisionItem with type='noul' cannot have 'score'")
        return self


class DecisionUsage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)


class DecisionResult(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "x-contract-id": "huit.decision.decision-result",
            "x-contract-version": "1.0.0",
        },
    )

    decision_type: Literal["intent", "evidence_sufficiency", "custom"] = Field(
        description="Mục đích ra quyết định"
    )
    status: Literal["success", "fallback", "error", "skipped"] = Field(
        description="Trạng thái thực thi của engine"
    )
    provider: str = Field(..., min_length=1, max_length=64)
    model: str = Field(..., min_length=1, max_length=64)
    decisions: Dict[str, DecisionItem] = Field(
        default_factory=dict, description="Kết quả quyết định theo từng câu hỏi"
    )
    usage: Optional[DecisionUsage] = Field(
        default=None, description="Thông tin token tiêu thụ"
    )
    latency_ms: float = Field(default=0.0, ge=0.0, description="Thời gian xử lý ms")
    error_message: Optional[str] = Field(
        default=None, max_length=1000, description="Thông báo lỗi an toàn (không chứa secret)"
    )

    _retry_count: int = PrivateAttr(default=0)
    _queue_wait_ms: float = PrivateAttr(default=0.0)
    _provider_latency_ms: float = PrivateAttr(default=0.0)
    _fallback_reason: Optional[str] = PrivateAttr(default=None)
    # Runtime-only evidence; not part of the canonical JSON contract.
    _api_called: bool = PrivateAttr(default=False)
