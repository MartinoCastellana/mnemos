from types import SimpleNamespace

from app.db.models import EntityCandidate, FieldDefinition
from app.services.default_fields import DEFAULT_FIELDS
from app.services.deterministic_memory import DeterministicMicroMemoryEngine
from app.services.extraction import (
    Candidate,
    EvidenceConsensusEngine,
    LocalizationEngine,
    ModelGateway,
)
from app.services.memory import GlobalDocumentMemory, OCRBlock, PageMemory
from app.services.micro_orchestrator import AgentOrchestrator
from app.services.structure import enrich_memory


def page(number: int, text: str):
    return PageMemory(
        number=number,
        text=text,
        blocks=[OCRBlock(text=word, bbox=[0.1, 0.1, 0.2, 0.2]) for word in text.split()],
        vision_features={"orientation": "portrait"},
    )


def test_non_consecutive_pages_cluster_by_anchor():
    memory = GlobalDocumentMemory(
        "x",
        pages=[
            page(1, "Protocollo AB/123 Impresa Alfa"),
            page(2, "Allegato estraneo ZX/999"),
            page(3, "Segue protocollo AB/123 Impresa Alfa"),
        ],
    )
    enrich_memory(memory)
    label_one = memory.page(1).cluster
    assert memory.page(3).cluster == label_one
    assert any(edge["source"] == 1 and edge["target"] == 3 for edge in memory.relationships)


def test_localization_returns_normalized_union():
    blocks = [OCRBlock("Mario", [0.1, 0.2, 0.2, 0.3]), OCRBlock("Rossi", [0.21, 0.2, 0.4, 0.3])]
    assert LocalizationEngine().locate("Mario Rossi", blocks) == [0.1, 0.2, 0.4, 0.3]


def test_localization_uses_model_position_for_repeated_value():
    blocks = [
        OCRBlock("123", [0.1, 0.1, 0.2, 0.15]),
        OCRBlock("altro", [0.3, 0.3, 0.4, 0.35]),
        OCRBlock("123", [0.8, 0.7, 0.9, 0.75]),
    ]
    assert LocalizationEngine().locate("123", blocks, hint=(0.82, 0.71)) == [
        0.8,
        0.7,
        0.9,
        0.75,
    ]


def test_consensus_prefers_corroborated_complete_reading():
    candidates = [
        Candidate("Giovanni", 1, None, "frontespizio", 0.75, []),
        Candidate("Siuvani", 2, None, "altra lettura", 0.55, []),
        Candidate("Giovai", 3, None, "altra lettura", 0.55, []),
        Candidate("Mario", 4, None, "candidato isolato", 0.72, []),
    ]
    field = SimpleNamespace(key="richiedente")
    ranked = EvidenceConsensusEngine().consolidate(candidates, field)
    assert ranked[0].value == "Giovanni"
    assert ranked[0].score > 0.8
    assert "confirmed across 3 pages" in ranked[0].reasons


def entity(candidate_id, field, value, page_number, bbox):
    return EntityCandidate(
        id=candidate_id,
        run_id="run",
        document_id="document",
        field_key=field,
        entity_type="text",
        raw_value=value,
        normalized_value="".join(value.casefold().split()),
        page_number=page_number,
        semantic_role=field,
        semantic_confidence=0.8,
        ocr_confidence=0.9,
        vision_confidence=0.8,
        bounding_box=bbox,
    )


def test_protocol_date_is_normalized_and_strictly_validated():
    orchestrator = AgentOrchestrator()
    assert orchestrator._valid("protocollo", "174$6")
    assert not orchestrator._valid("protocollo", "d'intesa")
    assert orchestrator._normalize_value("data_protocollo", "3.8.2005") == "03/08/2005"
    assert orchestrator._valid("data_protocollo", "03/08/2005")
    assert not orchestrator._valid("data_protocollo", "09/108")
    assert not orchestrator._valid("data_protocollo", "31/02/2005")
    assert orchestrator._normalize_value("comune", "COMUNE DI COPERTINO") == "COPERTINO"
    assert not orchestrator._valid("comune", "PROVINCIA DI LECCE")
    assert not orchestrator._semantically_valid("foglio", "17", "Via Bologna n. 17")
    assert orchestrator._semantically_valid("foglio", "17", "Foglio catastale 17")
    assert not orchestrator._semantically_valid(
        "esito_valutazione", "accettazione dell'incarico", "firma del tecnico"
    )
    assert orchestrator._normalize_value("data_valutazione", "3.8.2005") == "03/08/2005"
    assert orchestrator._normalize_value("richiedente", "Sig.ra Trincera Franca A.") == "TRINCERA FRANCA A."
    assert orchestrator._normalize_value("comune", "Copertino alla via Amendola") == "COPERTINO"
    assert orchestrator._normalize_value("esito_valutazione", "parere favorevole") == "POSITIVO"
    assert orchestrator._valid("categoria_catastale", "A/02")
    assert not orchestrator._valid("categoria_catastale", "A/2")
    assert orchestrator._valid("subalterno", "1")
    assert orchestrator._valid("subalterno", "34")
    assert not orchestrator._valid("subalterno", "34.11")
    assert not orchestrator._valid("subalterno", "123")
    assert orchestrator._valid("odonimo", "Via Ten. G. Colaci")
    assert not orchestrator._valid("odonimo", "Località o frazione Copertino")
    assert not orchestrator._valid("odonimo", "Foglio: 43 Allegato: B")
    assert not orchestrator._valid("odonimo", "via")


def test_requester_role_prefers_explicit_local_legal_role():
    engine = DeterministicMicroMemoryEngine()
    assert engine.role("richiedente", "committente Sig.ra Antonella Schito") == "RICHIEDENTE"
    assert engine.role("richiedente", "tecnico Ing. Ildebrando Palma") == "TECNICO"
    assert engine.role("richiedente", "ha sollecitato molte volte") == "SCONOSCIUTO"


def test_semantic_roles_remain_available_to_the_global_selector():
    property_address = entity(20, "odonimo", "Via Amendola", 7, [0.1, 0.1, 0.3, 0.2])
    property_address.semantic_role = "IMMOBILE_RICHIESTA"
    residence = entity(21, "odonimo", "Via Puccini", 6, [0.1, 0.1, 0.3, 0.2])
    residence.semantic_role = "RICHIEDENTE_RESIDENZA"
    technician = entity(22, "odonimo", "Via Roma", 8, [0.1, 0.1, 0.3, 0.2])
    technician.semantic_role = "TECNICO"
    assert AgentOrchestrator._eligible_candidates(
        "odonimo", [residence, property_address, technician]
    ) == [residence, property_address, technician]
    assert not AgentOrchestrator()._selection_allowed("odonimo", technician)


def test_protocol_date_proximity_is_scored_before_conflict_detection():
    orchestrator = AgentOrchestrator()
    protocol = entity(1, "protocollo", "17496", 24, [0.6, 0.15, 0.7, 0.18])
    nearby = entity(2, "data_protocollo", "23/08/2005", 24, [0.6, 0.18, 0.7, 0.21])
    unrelated = entity(3, "data_protocollo", "25/07/2005", 14, [0.1, 0.1, 0.2, 0.2])
    bonuses = orchestrator._relational_bonuses(
        {"protocollo": [protocol], "data_protocollo": [nearby, unrelated]}
    )
    assert bonuses[nearby.id] > bonuses[unrelated.id]


def test_protocol_uses_the_same_deterministic_candidate_contract_as_other_fields():
    memory = page(23, "In riferimento alla comunicazione protocollo n. 17496")
    memory.vision_features = {"text_source": "native_text", "text_quality": 0.99}
    review = DeterministicMicroMemoryEngine().analyze(memory, deterministic_fields(), None)

    candidate = next(item for item in review.candidates if item["field_key"] == "protocollo")
    assert candidate["raw_value"] == "17496"
    assert candidate["semantic_role"] == "PROTOCOLLO_RICHIAMATO"
    assert candidate["source_engine"] == "deterministic_python"


def test_protocol_preserves_anomalous_ocr_token_for_model_review():
    memory = page(21, "Prot.n.174$6")
    memory.vision_features = {"text_source": "native_text", "text_quality": 0.99}
    review = DeterministicMicroMemoryEngine().analyze(memory, deterministic_fields(), None)
    candidate = next(item for item in review.candidates if item["field_key"] == "protocollo")
    assert candidate["raw_value"] == "174$6"
    assert candidate["semantic_confidence"] < 0.9


def test_address_is_scored_as_one_occurrence_then_split():
    orchestrator = AgentOrchestrator()
    comune = entity(10, "comune", "Copertino", 1, [0.1, 0.5, 0.3, 0.55])
    odonimo = entity(11, "odonimo", "Via Trinchera", 1, [0.3, 0.5, 0.6, 0.55])
    civico = entity(12, "civico", "77", 1, [0.61, 0.5, 0.66, 0.55])
    isolated = entity(13, "civico", "5", 4, [0.1, 0.1, 0.2, 0.2])
    bonuses = orchestrator._relational_bonuses(
        {"comune": [comune], "odonimo": [odonimo], "civico": [civico, isolated]}
    )
    assert all(bonuses[item.id] > 0 for item in (comune, odonimo, civico))
    assert bonuses[isolated.id] == 0


def test_property_address_without_civic_number_keeps_pair_bonus():
    orchestrator = AgentOrchestrator()
    comune = entity(30, "comune", "Copertino", 19, [0.1, 0.50, 0.3, 0.54])
    odonimo = entity(31, "odonimo", "Via Ten. G. Colaci", 19, [0.3, 0.50, 0.7, 0.54])
    odonimo.semantic_role = "IMMOBILE_RICHIESTA"
    unrelated_number = entity(32, "civico", "1980", 19, [0.3, 0.30, 0.4, 0.34])
    unrelated_number.evidence_text = "iscritto all'Ordine degli Ingegneri al n. 1980"
    bonuses = orchestrator._relational_bonuses(
        {"comune": [comune], "odonimo": [odonimo], "civico": [unrelated_number]}
    )
    assert bonuses[comune.id] > 0
    assert bonuses[odonimo.id] > 0
    assert bonuses[unrelated_number.id] == 0


def test_unique_valid_100_percent_cluster_is_locked_before_qwen():
    orchestrator = AgentOrchestrator()
    field = FieldDefinition(key="odonimo", label="Odonimo", enabled=True)
    correct = entity(40, "odonimo", "Via Ten. G. Colaci", 19, [0.1, 0.5, 0.5, 0.54])
    correct.semantic_role = "IMMOBILE_RICHIESTA"
    correct.evidence_text = "UBICAZIONE: Via Ten. G. Colaci"
    locks = orchestrator._deterministic_locks(
        [field], {"odonimo": [correct]}, {correct.id: 0.30}
    )
    assert locks["odonimo"].id == correct.id


def test_two_distinct_100_percent_clusters_are_not_locked():
    orchestrator = AgentOrchestrator()
    field = FieldDefinition(key="odonimo", label="Odonimo", enabled=True)
    first = entity(50, "odonimo", "Via Alfa", 1, [0.1, 0.5, 0.4, 0.54])
    second = entity(51, "odonimo", "Via Beta", 2, [0.1, 0.5, 0.4, 0.54])
    for candidate in (first, second):
        candidate.semantic_role = "IMMOBILE_RICHIESTA"
        candidate.evidence_text = f"UBICAZIONE: {candidate.raw_value}"
    locks = orchestrator._deterministic_locks(
        [field], {"odonimo": [first, second]}, {first.id: 0.30, second.id: 0.30}
    )
    assert "odonimo" not in locks


def test_page_phase_schema_has_system_priority(monkeypatch, tmp_path):
    captured = {}

    class Response:
        is_error = False

        @staticmethod
        def json():
            return {"choices": [{"message": {"content": "{}"}}]}

    def fake_post(url, json, timeout):
        captured.update(json)
        return Response()

    monkeypatch.setattr("app.services.extraction.httpx.post", fake_post)
    settings = SimpleNamespace(
        model_backend="mlx", model_endpoint="http://model", model_name="vision"
    )

    test_page = page(7, "testo pagina")
    image_path = tmp_path / "page.png"
    image_path.write_bytes(b"png")
    test_page.render_path = str(image_path)
    ModelGateway(settings).complete_page(
        "ISTRUZIONI GLOBALI\n\n23. OUTPUT FINALE\nNon aggiungere entity candidates",
        GlobalDocumentMemory("x", pages=[test_page]),
        None,
    )

    assert captured["messages"][0]["role"] == "system"
    assert "VISION RECOVERY DELLA SOLA PAGINA 7" in captured["messages"][0]["content"]
    assert "entity_candidates" in captured["messages"][0]["content"]
    assert captured["messages"][1]["role"] == "user"
    user_content = captured["messages"][1]["content"]
    assert user_content[0]["type"] == "text"
    assert user_content[0]["text"].startswith('{"agent":"PROTOCOL"')
    assert "23. OUTPUT FINALE" not in user_content[0]["text"]
    assert "Non aggiungere entity candidates" not in user_content[0]["text"]
    assert [part["type"] for part in user_content] == ["text", "image_url", "text"]
    assert "OCR DELLA PAGINA" in user_content[-1]["text"]
    assert "VISION RECOVERY DELLA SOLA PAGINA 7" in user_content[-1]["text"]


def deterministic_fields():
    return [
        FieldDefinition(
            key=key,
            label=label,
            instructions="",
            strategy={"type": "text", "keywords": keywords, "pattern": pattern},
        )
        for key, label, keywords, pattern in DEFAULT_FIELDS
    ]


def test_native_text_micro_memory_is_contextual_and_python_reviewed():
    blocks = [
        OCRBlock("Ubicazione", [0.10, 0.10, 0.22, 0.13]),
        OCRBlock("immobile:", [0.23, 0.10, 0.33, 0.13]),
        OCRBlock("Via", [0.34, 0.10, 0.39, 0.13]),
        OCRBlock("Roma", [0.40, 0.10, 0.48, 0.13]),
        OCRBlock("n.", [0.49, 0.10, 0.52, 0.13]),
        OCRBlock("77", [0.53, 0.10, 0.57, 0.13]),
    ]
    memory = PageMemory(
        number=1,
        text="Ubicazione immobile: Via Roma n. 77",
        blocks=blocks,
        vision_features={"text_source": "native_text", "text_quality": 0.99},
    )
    review = DeterministicMicroMemoryEngine().analyze(memory, deterministic_fields(), None)

    assert review.accepted
    assert review.metrics["prompt_tokens"] == 0
    civico = next(item for item in review.candidates if item["field_key"] == "civico")
    assert civico["raw_value"] == "77"
    assert civico["semantic_role"] == "IMMOBILE_RICHIESTA"
    assert civico["context"]["line_text"] == memory.text
    assert civico["context"]["block_id"] == "page-0001:line-0001"


def test_address_without_comma_extracts_street_and_civic_as_one_occurrence():
    blocks = [
        OCRBlock("Immobile", [0.05, 0.10, 0.16, 0.13]),
        OCRBlock("sito", [0.17, 0.10, 0.22, 0.13]),
        OCRBlock("in", [0.23, 0.10, 0.25, 0.13]),
        OCRBlock("Piazza", [0.26, 0.10, 0.34, 0.13]),
        OCRBlock("Mazzini", [0.35, 0.10, 0.44, 0.13]),
        OCRBlock("24", [0.45, 0.10, 0.48, 0.13]),
    ]
    memory = PageMemory(
        number=7,
        text="Immobile sito in Piazza Mazzini 24",
        blocks=blocks,
        vision_features={"text_source": "native_text", "text_quality": 0.99},
    )
    review = DeterministicMicroMemoryEngine().analyze(memory, deterministic_fields(), None)
    odonimo = next(
        item for item in review.candidates
        if item["field_key"] == "odonimo" and item["raw_value"] == "Piazza Mazzini"
    )
    civico = next(
        item for item in review.candidates
        if item["field_key"] == "civico" and item["raw_value"] == "24"
    )
    assert odonimo["evidence_text"] == civico["evidence_text"] == memory.text
    assert odonimo["semantic_role"] == civico["semantic_role"] == "IMMOBILE_RICHIESTA"


def test_address_parser_accepts_comma_and_nc_but_not_unrelated_numbers():
    engine = DeterministicMicroMemoryEngine()
    assert engine.ADDRESS_WITH_CIVIC.search("Fabbricato in Piazza Mazzini, 24 a piano terra")
    match = engine.ADDRESS_WITH_CIVIC.search("Immobile in Piazza Mazzini n.c. 24")
    assert match and match.group("civic") == "24"
    ocr_match = engine.ADDRESS_WITH_CIVIC.search("Copertino, Piazza Mazzini 24 NC EUINGAT")
    assert ocr_match and ocr_match.group("street") == "Piazza Mazzini"
    assert ocr_match.group("civic") == "24"
    assert not engine.ADDRESS_WITH_CIVIC.search("Legge 24/1993 e protocollo 537")


def test_missing_civic_is_verified_only_when_source_explicitly_says_snc():
    orchestrator = AgentOrchestrator()
    plain = entity(70, "odonimo", "Piazza Mazzini", 7, [0.2, 0.2, 0.4, 0.24])
    plain.evidence_text = "Immobile in Piazza Mazzini"
    snc = entity(71, "odonimo", "Piazza Mazzini", 8, [0.2, 0.2, 0.4, 0.24])
    snc.evidence_text = "Immobile in Piazza Mazzini s.n.c."
    assert not orchestrator._explicitly_without_civic(plain)
    assert orchestrator._explicitly_without_civic(snc)


def test_vision_observation_gets_three_lines_of_python_context():
    blocks = [
        OCRBlock(f"riga {index}", [0.1, index / 10, 0.8, index / 10 + 0.03])
        for index in range(1, 8)
    ]
    memory = PageMemory(number=4, text="\n".join(block.text for block in blocks), blocks=blocks)
    context = DeterministicMicroMemoryEngine().context_for(memory, "riga 4")
    assert context["line_text"] == "riga 4"
    assert context["previous_lines"] == ["riga 1", "riga 2", "riga 3"]
    assert context["next_lines"] == ["riga 5", "riga 6", "riga 7"]


def test_python_review_routes_ambiguous_native_text_to_vision():
    memory = PageMemory(
        number=2,
        text="Protocollo: non leggibile",
        blocks=[
            OCRBlock("Protocollo:", [0.1, 0.1, 0.3, 0.13]),
            OCRBlock("non", [0.31, 0.1, 0.36, 0.13]),
            OCRBlock("leggibile", [0.37, 0.1, 0.5, 0.13]),
        ],
        vision_features={"text_source": "native_text", "text_quality": 0.95},
    )
    review = DeterministicMicroMemoryEngine().analyze(memory, deterministic_fields(), None)

    assert not review.accepted
    assert review.metrics["fallback_to_vision"] is True
    assert any("protocollo" in reason for reason in review.reasons)


def test_tesseract_text_can_be_accepted_deterministically():
    blocks = [
        OCRBlock("Ubicazione immobile: Via Roma n. 77", [0.1, 0.10, 0.8, 0.13]),
        OCRBlock("Pratica edilizia", [0.1, 0.20, 0.4, 0.23]),
        OCRBlock("Dati identificativi", [0.1, 0.30, 0.4, 0.33]),
        OCRBlock("Oggetto della richiesta", [0.1, 0.40, 0.5, 0.43]),
        OCRBlock("Documentazione allegata", [0.1, 0.50, 0.5, 0.53]),
    ]
    memory = PageMemory(
        number=3,
        text="\n".join(block.text for block in blocks),
        blocks=blocks,
        vision_features={"text_source": "tesseract_ocr", "text_quality": 1.0},
    )
    review = DeterministicMicroMemoryEngine(
        {
            "review": {
                "tesseract_text_quality_threshold": 0.85,
                "tesseract_risk_penalty": 0.10,
                "tesseract_min_line_count": 5,
            }
        }
    ).analyze(memory, deterministic_fields(), None)

    assert review.accepted
    assert review.metrics["fallback_to_vision"] is False
    assert review.metrics["effective_text_quality"] == 0.9
    assert any(item["field_key"] == "civico" for item in review.candidates)


def test_sparse_tesseract_text_routes_to_vision():
    memory = PageMemory(
        number=1,
        text="Documento illeggibile",
        blocks=[OCRBlock("Documento illeggibile", [0.1, 0.1, 0.5, 0.13])],
        vision_features={"text_source": "tesseract_ocr", "text_quality": 1.0},
    )
    review = DeterministicMicroMemoryEngine(
        {"review": {"tesseract_min_line_count": 5}}
    ).analyze(memory, deterministic_fields(), None)

    assert not review.accepted
    assert review.metrics["fallback_to_vision"] is True
    assert any("too sparse" in reason for reason in review.reasons)


def test_competing_valid_candidates_are_deferred_without_vision():
    assert not AgentOrchestrator._needs_vision_recovery(
        ["competing civico values in role IMMOBILE_RICHIESTA"], 2
    )
    assert AgentOrchestrator._needs_vision_recovery(
        ["label detected without a valid civico candidate"], 0
    )


def test_global_review_contract_only_selects_existing_candidate_ids(monkeypatch):
    captured = {}
    gateway = ModelGateway(
        SimpleNamespace(model_backend="mlx", model_endpoint="http://model", model_name="text")
    )

    def fake_complete(prompt, role, memory, **kwargs):
        captured.update({"prompt": prompt, "role": role, **kwargs})
        return {
            "selections": [
                {
                    "field_key": "civico",
                    "selected_candidate_id": 12,
                    "confidence": 0.93,
                    "reason_codes": ["ubicazione_immobile"],
                }
            ]
        }

    monkeypatch.setattr(gateway, "complete", fake_complete)
    result = gateway.resolve_fields_global(
        "ISTRUZIONI GLOBALI",
        {"civico": [{"candidate_id": 12, "value": "77", "context": {}}]},
    )

    assert result["selections"][0]["selected_candidate_id"] == 12
    assert captured["role"]["role"] == "ADDRESS_GLOBAL_SELECTOR"
    assert "Non trascrivere" in captured["system_prompt"]
