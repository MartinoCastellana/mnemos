import json

from app.core.config import Settings
from app.services.extraction import ModelGateway
from app.services.instruction_profiles import InstructionProfileCompiler, load_pipeline_rules
from app.services.instruction_sections import InstructionSections
from app.services.memory import GlobalDocumentMemory


def test_gateway_passes_instructions_as_only_text_prompt(monkeypatch):
    captured = {}

    class Response:
        is_error = False
        status_code = 200
        text = ""

        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": json.dumps({"protocollo": "42"})}}]}

    def fake_post(url, json, timeout):
        captured.update(json)
        return Response()

    monkeypatch.setattr("app.services.extraction.httpx.post", fake_post)
    gateway = ModelGateway(Settings(model_backend="mlx"))
    prompt = "testo esatto delle istruzioni"
    result = gateway.complete(prompt, {"model_size": "3B"}, GlobalDocumentMemory("doc"))

    assert result == {"protocollo": "42"}
    text_parts = [
        part["text"] for part in captured["messages"][0]["content"] if part["type"] == "text"
    ]
    assert text_parts == [prompt]
    assert captured["max_tokens"] == ModelGateway.MAX_GENERATION_TOKENS
    assert captured["max_tokens"] <= 8192


def test_instruction_sections_keep_source_text_verbatim_and_split_phases():
    source = """ISTRUZIONI GLOBALI
1. ISOLAMENTO
regola comune
8. ENTITY CANDIDATES
conserva candidati
19.1 PROTOCOLLO
regola protocollo
20. RECUPERO MIRATO
recupera
23. OUTPUT FINALE
output pubblico"""
    sections = InstructionSections.parse(source)

    assert "regola comune" in sections.page_analysis()
    assert "conserva candidati" in sections.page_analysis()
    assert "regola protocollo" in sections.protocol_page()
    assert "output pubblico" not in sections.page_analysis()
    assert "output pubblico" not in sections.protocol_global()


def test_gateway_repairs_truncated_json_once(monkeypatch, tmp_path):
    requests = []
    responses = iter(
        [
            {"choices": [{"finish_reason": "length", "message": {"content": '{"page_summary":"non finita'}}]},
            {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": '{"page_summary":"riparata","entity_candidates":[]}'},
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 8},
            },
        ]
    )

    class Response:
        is_error = False
        status_code = 200
        text = ""

        def __init__(self, payload):
            self.payload = payload

        def json(self):
            return self.payload

    def fake_post(url, json, timeout):
        requests.append(json)
        return Response(next(responses))

    monkeypatch.setattr("app.services.extraction.httpx.post", fake_post)
    gateway = ModelGateway(Settings(model_backend="mlx", storage_dir=tmp_path))
    result = gateway.complete("istruzioni", {}, GlobalDocumentMemory("doc"))

    assert result["page_summary"] == "riparata"
    assert gateway.last_metrics["json_repaired"] is True
    assert gateway.last_metrics["finish_reason"] == "stop"
    assert all(message["role"] != "assistant" for message in requests[1]["messages"])
    assert list((tmp_path / "_diagnostics" / "model-json").glob("*-initial.txt"))


def test_json_normalizer_extracts_first_balanced_object():
    raw = 'testo prima ```json\n{"entity_candidates":[],"requires_review":false}\n``` dopo'
    normalized = ModelGateway._normalize_json_text(raw)

    assert normalized == '{"entity_candidates":[],"requires_review":false}'




def test_structured_rules_compile_specialized_address_profile():
    source = """ISTRUZIONI GLOBALI
1. COMUNE
base
6. OCR
ocr
7. VISION
vision
8. CANDIDATI
candidati
9. STRUTTURA
struttura
10. NON SELEZIONE
non selezione
14. MICRO
micro
15. CHECKPOINT
checkpoint
19.4 COMUNE
regola comune
19.5 ODONIMO
regola odonimo
19.6 CIVICO
regola civico
19.7 FOGLIO
regola foglio"""
    compiler = InstructionProfileCompiler(load_pipeline_rules())
    prompt = compiler.compile_vision(source, ["odonimo", "civico"])

    assert '"agent":"ADDRESS"' in prompt
    assert '"odonimo"' in prompt
    assert '"civico"' in prompt
    assert '"foglio"' not in prompt
    assert "regola comune" not in prompt
    assert compiler.focus_fields(["competing civico values"], [])[0:3] == [
        "comune",
        "odonimo",
        "civico",
    ]
