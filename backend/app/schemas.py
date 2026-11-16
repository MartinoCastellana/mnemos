from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

PipelineMode = Literal["STANDARD", "MULTI_AGENT", "AUTO"]


class FieldDefinitionIn(BaseModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,79}$")
    label: str
    instructions: str
    positive_examples: list[str] = []
    negative_examples: list[str] = []
    validator: dict[str, Any] = {}
    ranking_rules: list[dict[str, Any]] = []
    strategy: dict[str, Any] = {}
    enabled: bool = True


class FieldDefinitionOut(FieldDefinitionIn):
    id: int
    model_config = ConfigDict(from_attributes=True)


class FieldResultOut(BaseModel):
    field_key: str
    value: str | None
    confidence: float
    page_number: int | None
    bbox: list[float] | None
    evidence: str
    reasoning: list[str]
    validated_by: str
    candidates: list[dict[str, Any]]
    model_config = ConfigDict(from_attributes=True)


class PageOut(BaseModel):
    page_number: int
    summary: str
    anchors: dict[str, Any]
    cluster_label: str
    render_url: str | None = None
    model_config = ConfigDict(from_attributes=True)


class AuditOut(BaseModel):
    id: int
    stage: str
    agent: str
    action: str
    detail: dict[str, Any]
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class DocumentOut(BaseModel):
    id: str
    filename: str
    page_count: int
    status: str
    pipeline_mode: str
    error: str | None
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class DocumentDetail(DocumentOut):
    pages: list[PageOut]
    results: list[FieldResultOut]
    audits: list[AuditOut]


class ProcessRequest(BaseModel):
    mode: PipelineMode = "AUTO"


class FieldValueUpdate(BaseModel):
    value: str | None = Field(default=None, max_length=10000)
    selected_candidate_id: int | None = None
