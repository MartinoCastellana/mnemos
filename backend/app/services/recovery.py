from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AuditEvent, Document, ProcessingRun

INTERRUPTED_MESSAGE = "Elaborazione interrotta: il processo backend non è più attivo"


def recover_interrupted_processing(db: Session, document_id: str | None = None) -> int:
    query = select(Document).where(Document.status.in_(("PROCESSING", "QUEUED")))
    if document_id:
        query = query.where(Document.id == document_id)
    documents = list(db.scalars(query))
    now = datetime.now(UTC)
    for document in documents:
        runs = db.scalars(
            select(ProcessingRun).where(
                ProcessingRun.document_id == document.id,
                ProcessingRun.status == "PROCESSING",
            )
        )
        for run in runs:
            run.status = "FAILED"
            run.error = INTERRUPTED_MESSAGE
            run.completed_at = now
        document.status = "READY" if document.page_count else "UPLOADED"
        document.error = None
        db.add(
            AuditEvent(
                document_id=document.id,
                stage="RECOVERY",
                agent="PipelineRecovery",
                action="Interrupted processing released",
                detail={"previous_status": "PROCESSING", "can_retry": True},
            )
        )
    if documents:
        db.commit()
    return len(documents)
