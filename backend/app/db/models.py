import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    filename: Mapped[str] = mapped_column(String(255))
    sha256: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    storage_path: Mapped[str] = mapped_column(Text)
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default="UPLOADED", index=True)
    pipeline_mode: Mapped[str] = mapped_column(String(24), default="AUTO")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    pages: Mapped[list["Page"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    results: Mapped[list["FieldResult"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    audits: Mapped[list["AuditEvent"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class Page(Base):
    __tablename__ = "pages"
    __table_args__ = (UniqueConstraint("document_id", "page_number"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    page_number: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text, default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    vision_features: Mapped[dict] = mapped_column(JSON, default=dict)
    anchors: Mapped[dict] = mapped_column(JSON, default=dict)
    blocks: Mapped[list] = mapped_column(JSON, default=list)
    embedding: Mapped[list] = mapped_column(JSON, default=list)
    cluster_label: Mapped[str] = mapped_column(String(64), default="Documento principale")
    render_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    document: Mapped[Document] = relationship(back_populates="pages")


class FieldDefinition(Base):
    __tablename__ = "field_definitions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    label: Mapped[str] = mapped_column(String(160))
    instructions: Mapped[str] = mapped_column(Text)
    positive_examples: Mapped[list] = mapped_column(JSON, default=list)
    negative_examples: Mapped[list] = mapped_column(JSON, default=list)
    validator: Mapped[dict] = mapped_column(JSON, default=dict)
    ranking_rules: Mapped[list] = mapped_column(JSON, default=list)
    strategy: Mapped[dict] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class FieldResult(Base):
    __tablename__ = "field_results"
    __table_args__ = (UniqueConstraint("document_id", "field_key"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    field_key: Mapped[str] = mapped_column(String(80))
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bbox: Mapped[list | None] = mapped_column(JSON, nullable=True)
    evidence: Mapped[str] = mapped_column(Text, default="")
    reasoning: Mapped[list] = mapped_column(JSON, default=list)
    validated_by: Mapped[str] = mapped_column(String(80), default="GlobalDocumentMemory")
    candidates: Mapped[list] = mapped_column(JSON, default=list)
    document: Mapped[Document] = relationship(back_populates="results")


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    stage: Mapped[str] = mapped_column(String(80))
    agent: Mapped[str] = mapped_column(String(80))
    action: Mapped[str] = mapped_column(String(160))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    document: Mapped[Document] = relationship(back_populates="audits")


class ProcessingRun(Base):
    __tablename__ = "processing_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(32), default="PROCESSING", index=True)
    pipeline_version: Mapped[str] = mapped_column(String(32), default="2.0")
    model_name: Mapped[str] = mapped_column(String(255))
    prompt_hash: Mapped[str] = mapped_column(String(64), index=True)
    render_config: Mapped[dict] = mapped_column(JSON, default=dict)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class PageObservation(Base):
    __tablename__ = "page_observations"
    __table_args__ = (UniqueConstraint("run_id", "page_number"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("processing_runs.id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    page_number: Mapped[int] = mapped_column(Integer)
    chunk_ids: Mapped[list] = mapped_column(JSON, default=list)
    rendered: Mapped[bool] = mapped_column(Boolean, default=False)
    ocr_completed: Mapped[bool] = mapped_column(Boolean, default=False)
    vision_completed: Mapped[bool] = mapped_column(Boolean, default=False)
    entities_saved: Mapped[bool] = mapped_column(Boolean, default=False)
    page_quality: Mapped[float] = mapped_column(Float, default=0)
    observations: Mapped[dict] = mapped_column(JSON, default=dict)


class EntityCandidate(Base):
    __tablename__ = "entity_candidates"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("processing_runs.id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    field_key: Mapped[str] = mapped_column(String(80), index=True)
    entity_type: Mapped[str] = mapped_column(String(80))
    raw_value: Mapped[str] = mapped_column(Text)
    normalized_value: Mapped[str] = mapped_column(Text, index=True)
    page_number: Mapped[int] = mapped_column(Integer, index=True)
    chunk_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    semantic_role: Mapped[str] = mapped_column(String(80), default="candidate")
    semantic_confidence: Mapped[float] = mapped_column(Float, default=0)
    ocr_confidence: Mapped[float] = mapped_column(Float, default=0)
    vision_confidence: Mapped[float] = mapped_column(Float, default=0)
    evidence_text: Mapped[str] = mapped_column(Text, default="")
    bounding_box: Mapped[list | None] = mapped_column(JSON, nullable=True)
    source_engine: Mapped[str] = mapped_column(String(80))
    requires_review: Mapped[bool] = mapped_column(Boolean, default=False)
    selected: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EntityRelationship(Base):
    __tablename__ = "entity_relationships"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("processing_runs.id", ondelete="CASCADE"), index=True
    )
    relation_type: Mapped[str] = mapped_column(String(80), index=True)
    source_candidate_id: Mapped[int] = mapped_column(
        ForeignKey("entity_candidates.id", ondelete="CASCADE")
    )
    target_candidate_id: Mapped[int] = mapped_column(
        ForeignKey("entity_candidates.id", ondelete="CASCADE")
    )
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0)
    evidence: Mapped[str] = mapped_column(Text, default="")


class PageSeparation(Base):
    __tablename__ = "page_separation"
    __table_args__ = (UniqueConstraint("run_id", "page_number"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("processing_runs.id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    page_number: Mapped[int] = mapped_column(Integer)
    assigned_role: Mapped[str] = mapped_column(String(64))
    document_type: Mapped[str] = mapped_column(String(80), default="unknown")
    role_confidence: Mapped[float] = mapped_column(Float, default=0)
    starts_new_document: Mapped[bool] = mapped_column(Boolean, default=False)
    boundary_confidence: Mapped[float] = mapped_column(Float, default=0)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    requires_review: Mapped[bool] = mapped_column(Boolean, default=False)


class DocumentCluster(Base):
    __tablename__ = "document_clusters"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("processing_runs.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(64))
    document_type: Mapped[str] = mapped_column(String(80), default="unknown")
    page_numbers: Mapped[list] = mapped_column(JSON, default=list)
    role_confidence: Mapped[float] = mapped_column(Float, default=0)
    boundary_confidence: Mapped[float] = mapped_column(Float, default=0)
    title: Mapped[str] = mapped_column(Text, default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    requires_review: Mapped[bool] = mapped_column(Boolean, default=False)


class ResolvedField(Base):
    __tablename__ = "resolved_fields"
    __table_args__ = (UniqueConstraint("run_id", "field_key"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("processing_runs.id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    field_key: Mapped[str] = mapped_column(String(80), index=True)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0)
    selected_candidate_id: Mapped[int | None] = mapped_column(
        ForeignKey("entity_candidates.id", ondelete="SET NULL"), nullable=True
    )
    source_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bounding_box: Mapped[list | None] = mapped_column(JSON, nullable=True)
    selection_reason: Mapped[list] = mapped_column(JSON, default=list)
    rejected_candidates: Mapped[list] = mapped_column(JSON, default=list)
    requires_review: Mapped[bool] = mapped_column(Boolean, default=False)


class Conflict(Base):
    __tablename__ = "conflicts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("processing_runs.id", ondelete="CASCADE"), index=True
    )
    field_key: Mapped[str] = mapped_column(String(80), index=True)
    candidate_ids: Mapped[list] = mapped_column(JSON, default=list)
    description: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(20), default="medium")
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)


class PageMicroMemory(Base):
    __tablename__ = "page_micro_memories"
    __table_args__ = (UniqueConstraint("run_id", "page_number"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("processing_runs.id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    page_number: Mapped[int] = mapped_column(Integer, index=True)
    checkpoint_hash: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(24), default="COMPLETED")
    document_assignment: Mapped[str] = mapped_column(String(80), default="da_revisionare")
    document_type: Mapped[str] = mapped_column(String(80), default="unknown")
    page_type: Mapped[str] = mapped_column(String(80), default="unknown")
    page_type_confidence: Mapped[float] = mapped_column(Float, default=0)
    role_confidence: Mapped[float] = mapped_column(Float, default=0)
    continuation_confidence: Mapped[float] = mapped_column(Float, default=0)
    new_document_confidence: Mapped[float] = mapped_column(Float, default=0)
    boundary_confidence: Mapped[float] = mapped_column(Float, default=0)
    starts_new_document: Mapped[bool] = mapped_column(Boolean, default=False)
    ocr: Mapped[dict] = mapped_column(JSON, default=dict)
    vision_analysis: Mapped[dict] = mapped_column(JSON, default=dict)
    field_states: Mapped[dict] = mapped_column(JSON, default=dict)
    entity_candidates: Mapped[list] = mapped_column(JSON, default=list)
    continuity_signals: Mapped[list] = mapped_column(JSON, default=list)
    separation_signals: Mapped[list] = mapped_column(JSON, default=list)
    page_summary: Mapped[str] = mapped_column(Text, default="")
    evidence: Mapped[list] = mapped_column(JSON, default=list)
    local_conflicts: Mapped[list] = mapped_column(JSON, default=list)
    requires_review: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EntityCluster(Base):
    __tablename__ = "entity_clusters"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("processing_runs.id", ondelete="CASCADE"), index=True
    )
    field_key: Mapped[str] = mapped_column(String(80), index=True)
    normalized_value: Mapped[str] = mapped_column(Text, index=True)
    representative_value: Mapped[str] = mapped_column(Text)
    semantic_role: Mapped[str] = mapped_column(String(80), default="candidate")
    candidate_ids: Mapped[list] = mapped_column(JSON, default=list)
    page_numbers: Mapped[list] = mapped_column(JSON, default=list)
    document_assignments: Mapped[list] = mapped_column(JSON, default=list)
    global_confidence: Mapped[float] = mapped_column(Float, default=0)
    evidence: Mapped[list] = mapped_column(JSON, default=list)
    has_conflict: Mapped[bool] = mapped_column(Boolean, default=False)


class RecoveryRequest(Base):
    __tablename__ = "recovery_requests"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("processing_runs.id", ondelete="CASCADE"), index=True
    )
    field_key: Mapped[str] = mapped_column(String(80), index=True)
    page_numbers: Mapped[list] = mapped_column(JSON, default=list)
    candidate_ids: Mapped[list] = mapped_column(JSON, default=list)
    bounding_boxes: Mapped[list] = mapped_column(JSON, default=list)
    reason: Mapped[str] = mapped_column(Text)
    available_evidence: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(24), default="PENDING")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CadastralPair(Base):
    __tablename__ = "cadastral_pairs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("processing_runs.id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    page_number: Mapped[int] = mapped_column(Integer)
    particella_candidate_id: Mapped[int | None] = mapped_column(
        ForeignKey("entity_candidates.id", ondelete="SET NULL"), nullable=True
    )
    subalterno_candidate_id: Mapped[int | None] = mapped_column(
        ForeignKey("entity_candidates.id", ondelete="SET NULL"), nullable=True
    )
    confidence: Mapped[float] = mapped_column(Float, default=0)
