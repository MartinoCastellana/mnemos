import fitz
from fastapi.testclient import TestClient
from sqlalchemy import create_engine


def make_pdf() -> bytes:
    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text((72, 72), "Protocollo: 123 Richiedente: Mario Rossi Via Roma civico 7")
    content = pdf.tobytes()
    pdf.close()
    return content


def test_upload_process_and_audit(tmp_path, monkeypatch):
    monkeypatch.setenv("DOC_AI_DATABASE_URL", f"sqlite:///{tmp_path}/test.db")
    monkeypatch.setenv("DOC_AI_STORAGE_DIR", str(tmp_path / "storage"))
    from app.core.config import get_settings

    get_settings.cache_clear()
    from app.db import session as db_session

    test_engine = create_engine(
        f"sqlite:///{tmp_path}/test.db", connect_args={"check_same_thread": False}
    )
    db_session.engine.dispose()
    db_session.engine = test_engine
    db_session.SessionLocal.configure(bind=test_engine)
    from app.main import app

    monkeypatch.setattr(
        "app.services.extraction.ModelGateway.complete",
        lambda self, prompt, role, memory, **kwargs: {
            "fields": {
                "protocollo": {"value": "123"},
                "data_protocollo": {"value": ""},
                "richiedente": {"value": "Mario Rossi"},
                "comune": {"value": "Copertino"},
                "odonimo": {"value": "Via Roma"},
                "civico": {"value": "7"},
                "foglio": {"value": ""},
                "particella": {"value": ""},
                "subalterno": {"value": ""},
                "categoria_catastale": {"value": ""},
                "data_valutazione": {"value": ""},
                "esito_valutazione": {"value": ""},
                "testo_valutazione": {"value": ""},
                "sintesi": {
                    "value": "Richiedente Mario Rossi, Comune Copertino.",
                },
            },
            "needs_review": False,
        },
    )
    monkeypatch.setattr(
        "app.services.extraction.ModelGateway.check_health",
        lambda self: {"available": True, "latency_ms": 1, "models": 1},
    )

    with TestClient(app) as client:
        uploaded = client.post(
            "/api/documents", files={"file": ("sample.pdf", make_pdf(), "application/pdf")}
        )
        assert uploaded.status_code == 201
        document_id = uploaded.json()["id"]
        response = client.post(f"/api/documents/{document_id}/process", json={"mode": "AUTO"})
        assert response.status_code == 202
        detail = client.get(f"/api/documents/{document_id}").json()
        assert detail["status"] == "COMPLETED"
        assert detail["page_count"] == 1
        processing_status = client.get(f"/api/documents/{document_id}/status")
        assert processing_status.status_code == 200
        assert processing_status.json()["completed_pages"] == 1
        assert any(
            item["field_key"] == "protocollo" and item["value"] == "123"
            for item in detail["results"]
        )
        assert any(event["stage"] == "OCR" for event in detail["audits"])
        memory = client.get(f"/api/documents/{document_id}/memory")
        assert memory.status_code == 200
        assert memory.json()["run"]["status"] == "COMPLETED"
        assert any(item["field_key"] == "protocollo" for item in memory.json()["candidates"])
        assert any(
            item["field_key"] == "protocollo" and item["selected_candidate_id"]
            for item in memory.json()["resolved_fields"]
        )
        edited = client.patch(
            f"/api/documents/{document_id}/results/protocollo", json={"value": "456"}
        )
        assert edited.status_code == 200
        assert edited.json()["value"] == "456"
        assert edited.json()["validated_by"] == "UserEdit"
        detail_after_edit = client.get(f"/api/documents/{document_id}").json()
        assert next(
            item for item in detail_after_edit["results"] if item["field_key"] == "protocollo"
        )["value"] == "456"
        memory_after_edit = client.get(f"/api/documents/{document_id}/memory").json()
        assert next(
            item
            for item in memory_after_edit["resolved_fields"]
            if item["field_key"] == "protocollo"
        )["value"] == "456"
        reset = client.delete(f"/api/documents/{document_id}/results")
        assert reset.status_code == 200
        assert reset.json()["ocr_preserved"] is True
        cleared = client.get(f"/api/documents/{document_id}").json()
        assert cleared["results"] == []
        assert cleared["page_count"] == 1
