from datetime import UTC, datetime
from pathlib import Path
import re
import shutil
from threading import Lock

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import get_settings
from app.db.models import (
    AuditEvent,
    CadastralPair,
    Conflict,
    Document,
    EntityCandidate,
    EntityCluster,
    EntityRelationship,
    DocumentCluster,
    FieldDefinition,
    FieldResult,
    Page,
    PageObservation,
    PageMicroMemory,
    PageSeparation,
    ProcessingRun,
    RecoveryRequest,
    ResolvedField,
)
from app.db.session import SessionLocal, get_db
from app.schemas import (
    DocumentDetail,
    DocumentOut,
    FieldDefinitionIn,
    FieldDefinitionOut,
    FieldValueUpdate,
    ProcessRequest,
)
from app.services.ingestion import DocumentIngestionService
from app.services.instruction_profiles import load_pipeline_rules
from app.services.micro_orchestrator import AgentOrchestrator
from app.services.recovery import recover_interrupted_processing

router = APIRouter(prefix="/api")
active_documents: set[str] = set()
cancel_requested_documents: set[str] = set()
active_documents_lock = Lock()
# MiniCPM-OCR and Qwen share the local machine's compute and memory. Keep
# complete document pipelines serial so the two model services are never used
# concurrently by separate background requests.
model_pipeline_lock = Lock()


def _process_document_serially(db: Session, document_id: str, mode: str):
    with model_pipeline_lock:
        AgentOrchestrator().process(
            db, document_id, mode, should_cancel=lambda: _cancel_requested(document_id)
        )


def _cancel_requested(document_id: str) -> bool:
    with active_documents_lock:
        return document_id in cancel_requested_documents


def process_background(document_id: str, mode: str):
    try:
        with SessionLocal() as db:
            _process_document_serially(db, document_id, mode)
    finally:
        with active_documents_lock:
            active_documents.discard(document_id)
            cancel_requested_documents.discard(document_id)


def process_batch_background(document_ids: list[str], mode: str):
    for document_id in document_ids:
        try:
            with SessionLocal() as db:
                _process_document_serially(db, document_id, mode)
        except Exception:
            # The orchestrator persists FAILED on the current document. Keep the
            # batch moving so one bad file cannot block the remaining queue.
            pass
        finally:
            with active_documents_lock:
                active_documents.discard(document_id)
                cancel_requested_documents.discard(document_id)


@router.get("/health")
def health():
    return {"status": "ok"}


@router.post("/documents", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
async def upload_document(file: UploadFile = File(...), db: Session = Depends(get_db)):
    try:
        document, created = DocumentIngestionService(get_settings()).ingest(
            file, await file.read(), db
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not created:
        return document
    return document


@router.get("/documents", response_model=list[DocumentOut])
def list_documents(db: Session = Depends(get_db)):
    return list(db.scalars(select(Document).order_by(Document.created_at.desc())))


@router.post("/documents/process-pending", status_code=status.HTTP_202_ACCEPTED)
def process_pending_documents(
    request: ProcessRequest, tasks: BackgroundTasks, db: Session = Depends(get_db)
):
    documents = list(
        db.scalars(
            select(Document)
            .where(Document.status.in_(("UPLOADED", "READY", "FAILED")))
            .order_by(func.lower(Document.filename), Document.filename, Document.id)
        )
    )
    queued: list[Document] = []
    with active_documents_lock:
        for document in documents:
            if document.id in active_documents:
                continue
            active_documents.add(document.id)
            queued.append(document)
    try:
        for document in queued:
            document.status, document.pipeline_mode = "QUEUED", request.mode
            document.error = None
        db.commit()
    except Exception:
        with active_documents_lock:
            active_documents.difference_update(document.id for document in queued)
        raise
    document_ids = [document.id for document in queued]
    if document_ids:
        tasks.add_task(process_batch_background, document_ids, request.mode)
    return {
        "status": "QUEUED" if document_ids else "EMPTY",
        "count": len(document_ids),
        "document_ids": document_ids,
    }


@router.get("/documents/{document_id}", response_model=DocumentDetail)
def document_detail(document_id: str, db: Session = Depends(get_db)):
    document = db.scalar(
        select(Document)
        .where(Document.id == document_id)
        .options(
            selectinload(Document.pages),
            selectinload(Document.results),
            selectinload(Document.audits),
        )
    )
    if not document:
        raise HTTPException(status_code=404, detail="Documento non trovato")
    document.pages.sort(key=lambda page: page.page_number)
    document.results.sort(key=lambda result: result.field_key)
    document.audits.sort(key=lambda event: event.id, reverse=True)
    for page in document.pages:
        page.render_url = f"/api/documents/{document.id}/pages/{page.page_number}/image"
    return document


@router.post("/documents/{document_id}/process", status_code=status.HTTP_202_ACCEPTED)
def process_document(
    document_id: str, request: ProcessRequest, tasks: BackgroundTasks, db: Session = Depends(get_db)
):
    document = db.get(Document, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Documento non trovato")
    with active_documents_lock:
        if document_id in active_documents:
            raise HTTPException(status_code=409, detail="Documento già in elaborazione")
        if document.status in {"PROCESSING", "QUEUED"}:
            recover_interrupted_processing(db, document_id)
            document = db.get(Document, document_id)
        active_documents.add(document_id)
    try:
        document.status, document.pipeline_mode = "QUEUED", request.mode
        document.error = None
        db.commit()
    except Exception:
        with active_documents_lock:
            active_documents.discard(document_id)
        raise
    tasks.add_task(process_background, document_id, request.mode)
    return {"id": document.id, "status": "QUEUED", "mode": request.mode}


@router.post("/documents/{document_id}/interrupt", status_code=status.HTTP_202_ACCEPTED)
def interrupt_document(document_id: str, db: Session = Depends(get_db)):
    document = db.get(Document, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Documento non trovato")
    if document.status not in {"PROCESSING", "QUEUED"}:
        raise HTTPException(status_code=409, detail="Nessuna elaborazione attiva da interrompere")
    with active_documents_lock:
        if document_id not in active_documents:
            raise HTTPException(status_code=409, detail="Elaborazione non attiva")
        cancel_requested_documents.add(document_id)
    return {"id": document.id, "status": "CANCEL_REQUESTED"}


@router.delete("/documents/{document_id}/results")
def reset_document_results(document_id: str, db: Session = Depends(get_db)):
    document = db.get(Document, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Documento non trovato")
    if document.status in {"PROCESSING", "QUEUED"}:
        raise HTTPException(status_code=409, detail="Attendi la fine dell'elaborazione")
    run_ids = select(ProcessingRun.id).where(ProcessingRun.document_id == document_id)
    deleted_results = db.execute(
        delete(FieldResult).where(FieldResult.document_id == document_id)
    ).rowcount or 0
    for model in (EntityRelationship, CadastralPair, ResolvedField):
        db.execute(delete(model).where(model.run_id.in_(run_ids)))
    for model in (
        RecoveryRequest,
        Conflict,
        EntityCluster,
        DocumentCluster,
        PageMicroMemory,
        PageSeparation,
        PageObservation,
    ):
        db.execute(delete(model).where(model.run_id.in_(run_ids)))
    db.execute(delete(EntityCandidate).where(EntityCandidate.run_id.in_(run_ids)))
    deleted_runs = db.execute(
        delete(ProcessingRun).where(ProcessingRun.document_id == document_id)
    ).rowcount or 0
    deleted_pages = db.execute(delete(Page).where(Page.document_id == document_id)).rowcount or 0
    db.execute(delete(AuditEvent).where(AuditEvent.document_id == document_id))

    source_path = Path(document.storage_path)
    optimized_path = source_path.with_name("optimized.pdf")
    pages_dir = source_path.parent / "pages"
    optimized_deleted = optimized_path.is_file()
    if optimized_deleted:
        optimized_path.unlink()
    pages_deleted = pages_dir.is_dir()
    if pages_deleted:
        shutil.rmtree(pages_dir)

    document.status = "UPLOADED"
    document.page_count = 0
    document.error = None
    document.pipeline_mode = "AUTO"
    db.add(
        AuditEvent(
            document_id=document.id,
            stage="RESET",
            agent="UserAction",
            action="Document processing reset completely",
            detail={
                "deleted_results": deleted_results,
                "deleted_memory_runs": deleted_runs,
                "deleted_pages": deleted_pages,
                "optimized_pdf_deleted": optimized_deleted,
                "page_images_deleted": pages_deleted,
                "source_pdf_preserved": True,
            },
        )
    )
    db.commit()
    return {
        "id": document.id,
        "status": document.status,
        "deleted_results": deleted_results,
        "deleted_memory_runs": deleted_runs,
        "deleted_pages": deleted_pages,
        "optimized_pdf_deleted": optimized_deleted,
        "page_images_deleted": pages_deleted,
        "source_pdf_preserved": True,
    }


@router.patch("/documents/{document_id}/results/{field_key}")
def update_document_result(
    document_id: str,
    field_key: str,
    request: FieldValueUpdate,
    db: Session = Depends(get_db),
):
    document = db.get(Document, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Documento non trovato")
    if document.status in {"PROCESSING", "QUEUED"}:
        raise HTTPException(status_code=409, detail="Attendi la fine dell'elaborazione")
    result = db.scalar(
        select(FieldResult).where(
            FieldResult.document_id == document_id, FieldResult.field_key == field_key
        )
    )
    if not result:
        raise HTTPException(status_code=404, detail="Campo estratto non trovato")

    run = db.scalar(
        select(ProcessingRun)
        .where(ProcessingRun.document_id == document_id)
        .order_by(ProcessingRun.started_at.desc())
    )
    candidate = None
    if request.selected_candidate_id is not None:
        if not run:
            raise HTTPException(status_code=404, detail="Run di elaborazione non trovata")
        candidate = db.scalar(
            select(EntityCandidate).where(
                EntityCandidate.id == request.selected_candidate_id,
                EntityCandidate.run_id == run.id,
                EntityCandidate.document_id == document_id,
                EntityCandidate.field_key == field_key,
            )
        )
        if not candidate:
            raise HTTPException(status_code=422, detail="Il candidato non appartiene a questo campo")

    previous_value = result.value
    value = (
        candidate.raw_value
        if candidate
        else request.value.strip() if request.value and request.value.strip() else None
    )
    result.value = value
    result.confidence = candidate.semantic_confidence if candidate else 1.0
    result.reasoning = ["candidato selezionato manualmente"] if candidate else ["valore modificato manualmente"]
    result.validated_by = "UserCandidateSelection" if candidate else "UserEdit"
    if candidate:
        result.page_number = candidate.page_number
        result.bbox = candidate.bounding_box
        result.evidence = candidate.evidence_text

    if run:
        resolved = db.scalar(
            select(ResolvedField).where(
                ResolvedField.run_id == run.id, ResolvedField.field_key == field_key
            )
        )
        if resolved:
            resolved.value = value
            resolved.confidence = candidate.semantic_confidence if candidate else 1.0
            resolved.selected_candidate_id = candidate.id if candidate else None
            resolved.selection_reason = (
                ["candidato selezionato manualmente"]
                if candidate
                else ["valore modificato manualmente"]
            )
            resolved.requires_review = candidate.requires_review if candidate else False
            if candidate:
                resolved.source_page = candidate.page_number
                resolved.bounding_box = candidate.bounding_box
        for item in db.scalars(
            select(EntityCandidate).where(
                EntityCandidate.run_id == run.id,
                EntityCandidate.field_key == field_key,
            )
        ):
            item.selected = bool(candidate and item.id == candidate.id)

    db.add(
        AuditEvent(
            document_id=document_id,
            stage="MANUAL_EDIT",
            agent="UserAction",
            action=f"Field {field_key} updated",
            detail={
                "field_key": field_key,
                "previous_value": previous_value,
                "value": value,
                "selected_candidate_id": candidate.id if candidate else None,
            },
        )
    )
    db.commit()
    db.refresh(result)
    return result


@router.get("/documents/{document_id}/memory")
def document_memory(document_id: str, db: Session = Depends(get_db)):
    if not db.get(Document, document_id):
        raise HTTPException(status_code=404, detail="Documento non trovato")
    pipeline_version = str(
        load_pipeline_rules(str(get_settings().pipeline_rules_path)).get("version", "unknown")
    )
    run = db.scalar(
        select(ProcessingRun)
        .where(ProcessingRun.document_id == document_id)
        .order_by(ProcessingRun.started_at.desc())
    )
    if not run:
        return {
            "pipeline_version": pipeline_version,
            "run": None,
            "candidates": [],
            "resolved_fields": [],
            "page_separation": [],
            "relationships": [],
            "conflicts": [],
            "micro_memories": [],
            "entity_clusters": [],
            "recovery_requests": [],
            "cadastral_pairs": [],
        }
    candidates = list(
        db.scalars(
            select(EntityCandidate)
            .where(EntityCandidate.run_id == run.id)
            .order_by(EntityCandidate.field_key, EntityCandidate.page_number, EntityCandidate.id)
        )
    )
    resolved = list(
        db.scalars(
            select(ResolvedField)
            .where(ResolvedField.run_id == run.id)
            .order_by(ResolvedField.field_key)
        )
    )
    separations = list(
        db.scalars(
            select(PageSeparation)
            .where(PageSeparation.run_id == run.id)
            .order_by(PageSeparation.page_number)
        )
    )
    relationships = list(
        db.scalars(select(EntityRelationship).where(EntityRelationship.run_id == run.id))
    )
    conflicts = list(db.scalars(select(Conflict).where(Conflict.run_id == run.id)))
    micro_memories = list(
        db.scalars(
            select(PageMicroMemory)
            .where(PageMicroMemory.run_id == run.id)
            .order_by(PageMicroMemory.page_number)
        )
    )
    entity_clusters = list(
        db.scalars(
            select(EntityCluster)
            .where(EntityCluster.run_id == run.id)
            .order_by(EntityCluster.field_key, EntityCluster.global_confidence.desc())
        )
    )
    relevance_by_candidate: dict[int, float] = {}
    for cluster in entity_clusters:
        for candidate_id in cluster.candidate_ids:
            relevance_by_candidate[candidate_id] = max(
                relevance_by_candidate.get(candidate_id, 0.0), cluster.global_confidence
            )
    recovery_requests = list(
        db.scalars(select(RecoveryRequest).where(RecoveryRequest.run_id == run.id))
    )
    cadastral_pairs = list(db.scalars(select(CadastralPair).where(CadastralPair.run_id == run.id)))
    return {
        "pipeline_version": pipeline_version,
        "run": {
            "id": run.id,
            "status": run.status,
            "pipeline_version": run.pipeline_version,
            "model_name": run.model_name,
            "prompt_hash": run.prompt_hash,
            "render_config": run.render_config,
            "started_at": run.started_at,
            "completed_at": run.completed_at,
            "error": run.error,
        },
        "candidates": [
            {
                "id": item.id,
                "field_key": item.field_key,
                "raw_value": item.raw_value,
                "normalized_value": item.normalized_value,
                "page_number": item.page_number,
                "chunk_id": item.chunk_id,
                "semantic_role": item.semantic_role,
                "semantic_confidence": item.semantic_confidence,
                "ocr_confidence": item.ocr_confidence,
                "vision_confidence": item.vision_confidence,
                "evidence_text": item.evidence_text,
                "bounding_box": item.bounding_box,
                "source_engine": item.source_engine,
                "requires_review": item.requires_review,
                "selected": item.selected,
                "rejection_reason": item.rejection_reason,
                "global_relevance": round(
                    relevance_by_candidate.get(
                        item.id,
                        item.semantic_confidence * 0.75 + item.ocr_confidence * 0.25,
                    ),
                    3,
                ),
                "relevance_source": (
                    "global_cluster" if item.id in relevance_by_candidate else "candidate_score"
                ),
            }
            for item in candidates
        ],
        "resolved_fields": [
            {
                "field_key": item.field_key,
                "value": item.value,
                "confidence": item.confidence,
                "selected_candidate_id": item.selected_candidate_id,
                "source_page": item.source_page,
                "bounding_box": item.bounding_box,
                "selection_reason": item.selection_reason,
                "rejected_candidates": item.rejected_candidates,
                "requires_review": item.requires_review,
            }
            for item in resolved
        ],
        "page_separation": [
            {
                "page_number": item.page_number,
                "assigned_role": item.assigned_role,
                "document_type": item.document_type,
                "role_confidence": item.role_confidence,
                "starts_new_document": item.starts_new_document,
                "boundary_confidence": item.boundary_confidence,
                "evidence": item.evidence,
                "requires_review": item.requires_review,
            }
            for item in separations
        ],
        "relationships": [
            {
                "id": item.id,
                "relation_type": item.relation_type,
                "source_candidate_id": item.source_candidate_id,
                "target_candidate_id": item.target_candidate_id,
                "page_number": item.page_number,
                "confidence": item.confidence,
                "evidence": item.evidence,
            }
            for item in relationships
        ],
        "conflicts": [
            {
                "id": item.id,
                "field_key": item.field_key,
                "candidate_ids": item.candidate_ids,
                "description": item.description,
                "severity": item.severity,
                "resolved": item.resolved,
            }
            for item in conflicts
        ],
        "micro_memories": [
            {
                "page_number": item.page_number,
                "checkpoint_hash": item.checkpoint_hash,
                "document_assignment": item.document_assignment,
                "document_type": item.document_type,
                "page_type": item.page_type,
                "page_type_confidence": item.page_type_confidence,
                "role_confidence": item.role_confidence,
                "continuation_confidence": item.continuation_confidence,
                "new_document_confidence": item.new_document_confidence,
                "boundary_confidence": item.boundary_confidence,
                "starts_new_document": item.starts_new_document,
                "page_summary": item.page_summary,
                "continuity_signals": item.continuity_signals,
                "separation_signals": item.separation_signals,
                "field_states": item.field_states,
                "entity_candidates": item.entity_candidates,
                "requires_review": item.requires_review,
            }
            for item in micro_memories
        ],
        "entity_clusters": [
            {
                "id": item.id,
                "field_key": item.field_key,
                "representative_value": item.representative_value,
                "semantic_role": item.semantic_role,
                "candidate_ids": item.candidate_ids,
                "page_numbers": item.page_numbers,
                "document_assignments": item.document_assignments,
                "global_confidence": item.global_confidence,
                "has_conflict": item.has_conflict,
            }
            for item in entity_clusters
        ],
        "recovery_requests": [
            {
                "id": item.id,
                "field_key": item.field_key,
                "page_numbers": item.page_numbers,
                "candidate_ids": item.candidate_ids,
                "reason": item.reason,
                "status": item.status,
            }
            for item in recovery_requests
        ],
        "cadastral_pairs": [
            {
                "id": item.id,
                "page_number": item.page_number,
                "particella_candidate_id": item.particella_candidate_id,
                "subalterno_candidate_id": item.subalterno_candidate_id,
                "confidence": item.confidence,
            }
            for item in cadastral_pairs
        ],
    }


@router.get("/documents/{document_id}/status")
def document_processing_status(document_id: str, db: Session = Depends(get_db)):
    document = db.get(Document, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Documento non trovato")
    run = db.scalar(
        select(ProcessingRun)
        .where(ProcessingRun.document_id == document_id)
        .order_by(ProcessingRun.started_at.desc())
    )
    completed_pages = 0
    if run:
        completed_pages = db.scalar(
            select(func.count(PageMicroMemory.id)).where(PageMicroMemory.run_id == run.id)
        ) or 0
    latest_audit = db.scalar(
        select(AuditEvent)
        .where(AuditEvent.document_id == document_id)
        .order_by(AuditEvent.id.desc())
        .limit(1)
    )
    return {
        "id": document.id,
        "status": document.status,
        "error": document.error,
        "page_count": document.page_count,
        "completed_pages": completed_pages,
        "run_id": run.id if run else None,
        "latest_audit_id": latest_audit.id if latest_audit else None,
    }


@router.get("/documents/{document_id}/runs/analytics")
def document_run_analytics(document_id: str, db: Session = Depends(get_db)):
    document = db.get(Document, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Documento non trovato")
    runs = list(
        db.scalars(
            select(ProcessingRun)
            .where(ProcessingRun.document_id == document_id)
            .order_by(ProcessingRun.started_at.desc())
        )
    )

    def metric(call: dict, key: str) -> int:
        value = call.get(key, 0)
        return int(value or 0) if isinstance(value, (int, float)) else 0

    output = []
    for run in runs:
        memories = list(
            db.scalars(
                select(PageMicroMemory)
                .where(PageMicroMemory.run_id == run.id)
                .order_by(PageMicroMemory.page_number)
            )
        )
        pages = []
        phase_totals: dict[str, dict[str, int]] = {}
        for memory in memories:
            calls = memory.vision_analysis.get("model_calls", []) if memory.vision_analysis else []
            duration = prompt_tokens = completion_tokens = 0
            used_vision = False
            for call in calls if isinstance(calls, list) else []:
                if not isinstance(call, dict):
                    continue
                phase = str(call.get("phase", "page_review"))
                duration += metric(call, "duration_ms")
                prompt_tokens += metric(call, "prompt_tokens")
                completion_tokens += metric(call, "completion_tokens")
                used_vision = used_vision or "vision" in phase
                totals = phase_totals.setdefault(
                    phase, {"duration_ms": 0, "prompt_tokens": 0, "completion_tokens": 0, "calls": 0}
                )
                totals["duration_ms"] += metric(call, "duration_ms")
                totals["prompt_tokens"] += metric(call, "prompt_tokens")
                totals["completion_tokens"] += metric(call, "completion_tokens")
                totals["calls"] += 1
            pages.append(
                {
                    "page_number": memory.page_number,
                    "duration_ms": duration,
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": prompt_tokens + completion_tokens,
                    "vision_used": used_vision,
                    "candidate_count": len(memory.entity_candidates or []),
                    "requires_review": memory.requires_review,
                }
            )

        global_audit = db.scalar(
            select(AuditEvent)
            .where(
                AuditEvent.document_id == document_id,
                AuditEvent.stage == "GLOBAL_PASS",
                AuditEvent.created_at >= run.started_at,
                AuditEvent.created_at <= (run.completed_at or datetime.now(UTC)),
            )
            .order_by(AuditEvent.id.desc())
            .limit(1)
        )
        global_metrics = (global_audit.detail or {}).get("global_review_model_call", {}) if global_audit else {}
        for call in global_metrics.get("agent_calls", []) if isinstance(global_metrics, dict) else []:
            if not isinstance(call, dict):
                continue
            phase = f"global_{call.get('agent', 'selector')}"
            phase_totals[phase] = {
                "duration_ms": metric(call, "duration_ms"),
                "prompt_tokens": metric(call, "prompt_tokens"),
                "completion_tokens": metric(call, "completion_tokens"),
                "calls": 1,
            }
        prompt_tokens = sum(item["prompt_tokens"] for item in pages) + metric(global_metrics, "prompt_tokens")
        completion_tokens = sum(item["completion_tokens"] for item in pages) + metric(global_metrics, "completion_tokens")
        duration_ms = (
            round((run.completed_at - run.started_at).total_seconds() * 1000)
            if run.completed_at else None
        )
        candidate_count = db.scalar(
            select(func.count(EntityCandidate.id)).where(EntityCandidate.run_id == run.id)
        ) or 0
        resolved_count = db.scalar(
            select(func.count(ResolvedField.id)).where(ResolvedField.run_id == run.id)
        ) or 0
        output.append(
            {
                "run_id": run.id,
                "status": run.status,
                "pipeline_version": run.pipeline_version,
                "model_name": run.model_name,
                "started_at": run.started_at,
                "completed_at": run.completed_at,
                "duration_ms": duration_ms,
                "page_count": len(memories),
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
                "estimated_cost_eur": 0,
                "candidate_count": candidate_count,
                "resolved_count": resolved_count,
                "vision_pages": sum(1 for page in pages if page["vision_used"]),
                "phases": [
                    {"phase": phase, **values} for phase, values in phase_totals.items()
                ],
                "pages": pages,
            }
        )
    return output


@router.get("/documents/{document_id}/pages/{page_number}/image")
def page_image(document_id: str, page_number: int, db: Session = Depends(get_db)):
    page = db.scalar(
        select(Page).where(Page.document_id == document_id, Page.page_number == page_number)
    )
    if not page or not page.render_path or not Path(page.render_path).is_file():
        raise HTTPException(status_code=404, detail="Immagine pagina non trovata")
    return FileResponse(page.render_path, media_type="image/png")


@router.get("/documents/{document_id}/file")
def document_file(document_id: str, db: Session = Depends(get_db)):
    document = db.get(Document, document_id)
    if not document or not Path(document.storage_path).is_file():
        raise HTTPException(status_code=404, detail="PDF non trovato")
    return FileResponse(
        document.storage_path,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{document.filename}"'},
    )


@router.get("/documents/{document_id}/optimized-file")
def optimized_document_file(document_id: str, db: Session = Depends(get_db)):
    document = db.get(Document, document_id)
    if not document or not Path(document.storage_path).is_file():
        raise HTTPException(status_code=404, detail="PDF non trovato")
    optimized_path = Path(document.storage_path).with_name("optimized.pdf")
    if not optimized_path.is_file():
        from app.services.ocr import optimize_pdf

        optimize_pdf(document.storage_path)
    return FileResponse(
        optimized_path,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{document.filename}"'},
    )


@router.get("/fields", response_model=list[FieldDefinitionOut])
def list_fields(db: Session = Depends(get_db)):
    return list(db.scalars(
        select(FieldDefinition)
        .where(FieldDefinition.key != "sintesi")
        .order_by(FieldDefinition.id)
    ))


@router.put("/fields", response_model=list[FieldDefinitionOut])
def save_field_configuration(
    payload: list[FieldDefinitionIn], db: Session = Depends(get_db)
):
    if not payload:
        raise HTTPException(status_code=422, detail="Configura almeno un campo")
    keys = [field.key for field in payload]
    if len(keys) != len(set(keys)):
        raise HTTPException(status_code=422, detail="Le chiavi dei campi devono essere uniche")
    for field in payload:
        patterns = [
            (field.strategy.get("pattern"), True),
            (field.validator.get("value_pattern"), False),
        ]
        for pattern, extraction_pattern in patterns:
            if not pattern:
                continue
            try:
                compiled = re.compile(str(pattern), re.IGNORECASE)
            except re.error as exc:
                raise HTTPException(
                    status_code=422,
                    detail=f"Pattern non valido per {field.label}: {exc}",
                ) from exc
            if extraction_pattern and "value" not in compiled.groupindex:
                raise HTTPException(
                    status_code=422,
                    detail=f"Il pattern di estrazione per {field.label} deve includere (?P<value>...).",
                )

    existing = {
        field.key: field
        for field in db.scalars(select(FieldDefinition)).all()
    }
    incoming = set(keys)
    for key, field in existing.items():
        if key not in incoming:
            db.delete(field)
    for payload_field in payload:
        values = payload_field.model_dump()
        field = existing.get(payload_field.key)
        if field is None:
            db.add(FieldDefinition(**values))
        else:
            for name, value in values.items():
                setattr(field, name, value)
    db.commit()
    return list(db.scalars(select(FieldDefinition).order_by(FieldDefinition.id)))


@router.post("/fields", response_model=FieldDefinitionOut, status_code=201)
def create_field(payload: FieldDefinitionIn, db: Session = Depends(get_db)):
    if db.scalar(select(FieldDefinition).where(FieldDefinition.key == payload.key)):
        raise HTTPException(status_code=409, detail="Chiave campo già esistente")
    field = FieldDefinition(**payload.model_dump())
    db.add(field)
    db.commit()
    db.refresh(field)
    return field


@router.put("/fields/{field_id}", response_model=FieldDefinitionOut)
def update_field(field_id: int, payload: FieldDefinitionIn, db: Session = Depends(get_db)):
    field = db.get(FieldDefinition, field_id)
    if not field:
        raise HTTPException(status_code=404, detail="Campo non trovato")
    for key, value in payload.model_dump().items():
        setattr(field, key, value)
    db.commit()
    return field


@router.delete("/fields/{field_id}", status_code=204)
def delete_field(field_id: int, db: Session = Depends(get_db)):
    field = db.get(FieldDefinition, field_id)
    if not field:
        raise HTTPException(status_code=404, detail="Campo non trovato")
    db.delete(field)
    db.commit()
    return Response(status_code=204)
