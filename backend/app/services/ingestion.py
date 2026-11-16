import hashlib

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import AuditEvent, Document
from app.services.ocr import optimize_pdf


class DocumentIngestionService:
    def __init__(self, settings: Settings):
        self.settings = settings

    def ingest(self, upload: UploadFile, content: bytes, db: Session) -> tuple[Document, bool]:
        if not content.startswith(b"%PDF"):
            raise ValueError("Il file caricato non è un PDF valido")
        if len(content) > self.settings.max_upload_mb * 1024 * 1024:
            raise ValueError(f"Il PDF supera il limite di {self.settings.max_upload_mb} MB")
        digest = hashlib.sha256(content).hexdigest()
        existing = db.scalar(select(Document).where(Document.sha256 == digest))
        if existing:
            return existing, False
        storage = self.settings.storage_dir / digest
        storage.mkdir(parents=True, exist_ok=True)
        path = storage / "source.pdf"
        path.write_bytes(content)
        optimized_path, page_count, optimization = optimize_pdf(str(path))
        document = Document(
            filename=upload.filename or "document.pdf",
            sha256=digest,
            storage_path=str(path),
            page_count=page_count,
        )
        db.add(document)
        db.flush()
        db.add(
            AuditEvent(
                document_id=document.id,
                stage="INGESTION",
                agent=self.__class__.__name__,
                action="PDF stored and fingerprinted",
                detail={"sha256": digest, "bytes": len(content)},
            )
        )
        db.add(
            AuditEvent(
                document_id=document.id,
                stage="OPTIMIZATION",
                agent="PDFPreprocessor",
                action="PDF optimized before analysis",
                detail={**optimization, "optimized_file": optimized_path},
            )
        )
        db.commit()
        return document, True
