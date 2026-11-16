import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from app.db.models import FieldDefinition
from app.services.memory import OCRBlock, PageMemory


@dataclass(slots=True)
class TextLine:
    text: str
    bbox: list[float]
    blocks: list[OCRBlock]


@dataclass(slots=True)
class DeterministicReview:
    output: dict[str, Any]
    candidates: list[dict[str, Any]]
    accepted: bool
    reasons: list[str]
    metrics: dict[str, Any]


class DeterministicMicroMemoryEngine:
    """Build and review contextual candidates without generative rewriting."""

    ADDRESS_WITH_CIVIC = re.compile(
        r"\b(?P<street>(?:via|viale|piazza|strada|contrada|località|localita)\s+"
        r"[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ' .\-]{1,60}?)"
        r"\s*,?\s+(?:(?:n(?:\s*\.\s*c)?\.?|civico|n[°º])\s*)?"
        r"(?P<civic>\d{1,4}[A-Za-z]?(?:[/ -][A-Za-z0-9]+)?)"
        r"(?=\s*(?:$|[,;.]|\b(?:a|al|piano|oggi|di|del|della|n\.?c\.?)\b))",
        re.IGNORECASE,
    )

    def __init__(self, rules: dict[str, Any] | None = None):
        self.rules = rules or {}
        review = self.rules.get("review", {})
        self.ocr_quality_threshold = float(
            review.get("minicpm_text_quality_threshold", 0.82)
        )
        self.candidate_confidence_threshold = float(
            review.get("deterministic_candidate_confidence_threshold", 0.88)
        )

    @staticmethod
    def _lines(blocks: list[OCRBlock]) -> list[TextLine]:
        # MiniCPM's layout stage already emits blocks in reading order. Their
        # geometry is retained for visual review only and does not order text.
        return [
            TextLine(text=text.strip(), bbox=block.bbox, blocks=[block])
            for block in blocks
            for text in block.text.splitlines()
            if text.strip()
        ]

    @staticmethod
    def _value_bbox(match: re.Match, line: TextLine) -> list[float]:
        return DeterministicMicroMemoryEngine._group_bbox(match, line, "value")

    @staticmethod
    def _group_bbox(match: re.Match, line: TextLine, group: str) -> list[float]:
        normalize = lambda text: re.sub(r"\W+", "", text.casefold())
        wanted = normalize(match.group(group))
        for start in range(len(line.blocks)):
            for end in range(start + 1, len(line.blocks) + 1):
                selected = line.blocks[start:end]
                current = normalize("".join(item.text for item in selected))
                if current == wanted:
                    return [
                        min(item.bbox[0] for item in selected),
                        min(item.bbox[1] for item in selected),
                        max(item.bbox[2] for item in selected),
                        max(item.bbox[3] for item in selected),
                    ]
                if len(current) > len(wanted) + 4:
                    break
        return line.bbox

    def _address_pair_candidates(
        self, page: PageMemory, lines: list[TextLine]
    ) -> list[dict[str, Any]]:
        """Extract street and civic number atomically, including unlabelled civics."""
        candidates: list[dict[str, Any]] = []
        for index, line in enumerate(lines):
            for match in self.ADDRESS_WITH_CIVIC.finditer(line.text):
                street = " ".join(match.group("street").strip(" :;,.-").split())
                civic = " ".join(match.group("civic").strip(" :;,.-").split())
                context = " | ".join(
                    item.text for item in lines[max(0, index - 3):min(len(lines), index + 4)]
                )
                role = self.role("odonimo", line.text)
                if role == "SCONOSCIUTO":
                    role = self.role("odonimo", context)
                common_context = {
                    "line_text": line.text,
                    "previous_line": lines[index - 1].text if index else "",
                    "next_line": lines[index + 1].text if index + 1 < len(lines) else "",
                    "previous_lines": [item.text for item in lines[max(0, index - 3):index]],
                    "next_lines": [item.text for item in lines[index + 1:min(len(lines), index + 4)]],
                    "label_text": match.group(0)[:match.start("civic") - match.start()],
                    "line_bbox": line.bbox,
                    "block_id": f"page-{page.number:04d}:line-{index + 1:04d}",
                    "section_role": role,
                    "extraction_rule": "atomic_address_with_optional_civic_separator",
                }
                for field_key, value, group in (
                    ("odonimo", street, "street"),
                    ("civico", civic, "civic"),
                ):
                    candidates.append(
                        {
                            "field_key": field_key,
                            "raw_value": value,
                            "semantic_role": role,
                            "semantic_confidence": 0.94 if role == "IMMOBILE_RICHIESTA" else 0.90,
                            "vision_confidence": 0.0,
                            "evidence_text": line.text[:240],
                            "bounding_box": self._group_bbox(match, line, group),
                            "relationships": ["odonimo_ha_civico"],
                            "source_engine": "deterministic_python",
                            "context": common_context,
                        }
                    )
        return candidates

    def context_for(self, page: PageMemory, value: str) -> dict[str, Any]:
        """Find OCR context by text; spatial boxes are reserved for review display."""
        lines = self._lines(page.blocks)
        if not lines:
            return {
                "line_text": value,
                "previous_line": "",
                "next_line": "",
                "previous_lines": [],
                "next_lines": [],
                "line_bbox": bbox,
                "section_role": "SCONOSCIUTO",
            }
        normalized = re.sub(r"\W+", "", value.casefold())
        matches = [
            (index, line)
            for index, line in enumerate(lines)
            if normalized and normalized in re.sub(r"\W+", "", line.text.casefold())
        ]
        if matches:
            index, line = matches[0]
        else:
            index, line = 0, lines[0]
        return {
            "line_text": line.text,
            "previous_line": lines[index - 1].text if index else "",
            "next_line": lines[index + 1].text if index + 1 < len(lines) else "",
            "previous_lines": [item.text for item in lines[max(0, index - 3):index]],
            "next_lines": [item.text for item in lines[index + 1:min(len(lines), index + 4)]],
            "line_bbox": line.bbox,
            "block_id": f"page-{page.number:04d}:line-{index + 1:04d}",
            "section_role": "SCONOSCIUTO",
            "extraction_rule": "vision_observation_localized_by_python",
        }

    @staticmethod
    def role(field_key: str, context: str) -> str:
        lowered = context.casefold()
        technical_markers = (
            "tecnico", "progettista", "direttore lavori", "architetto", "arch.",
            "geometra", "ingegnere", "ordine degli architetti", "albo professionale",
        )
        if field_key == "richiedente":
            applicant_markers = (
                "committente", "richiedente", "proprietario", "proprietaria",
                "titolare", "ditta", "istante",
            )
            if any(token in lowered for token in applicant_markers):
                return "RICHIEDENTE"
            if any(token in lowered for token in technical_markers):
                return "TECNICO"
            return "SCONOSCIUTO"
        if field_key in {"protocollo", "data_protocollo"}:
            return (
                "PROTOCOLLO_RICHIAMATO"
                if "in riferimento" in lowered or "comunicazione" in lowered
                else "PROTOCOLLO_PRATICA"
            )
        if field_key in {"foglio", "particella", "subalterno", "categoria_catastale"}:
            return "DATI_CATASTALI_IMMOBILE"
        if field_key in {"data_valutazione", "esito_valutazione"}:
            return "VALUTAZIONE_FINALE"
        if any(token in lowered for token in ("ubicazione", "immobile", "localizzazione")):
            return "IMMOBILE_RICHIESTA"
        if any(token in lowered for token in ("residente", "residenza", "domicilio")):
            return "RICHIEDENTE_RESIDENZA"
        if any(token in lowered for token in technical_markers):
            return "TECNICO"
        if any(token in lowered for token in ("pagamento", "versamento", "bollettino")):
            return "PAGAMENTO"
        if field_key == "sintesi":
            return "SINTESI_FASCICOLO"
        return "SCONOSCIUTO"

    @staticmethod
    def _has_signal(text: str, field: FieldDefinition) -> bool:
        return any(
            len(keyword.strip()) >= 4 and keyword.casefold() in text.casefold()
            for keyword in (field.strategy or {}).get("keywords", [])
        )

    def analyze(
        self, page: PageMemory, fields: Iterable[FieldDefinition], previous_context: dict | None
    ) -> DeterministicReview:
        fields, lines = list(fields), self._lines(page.blocks)
        candidates: list[dict[str, Any]] = []
        signalled: set[str] = set()
        for field in fields:
            pattern = (field.strategy or {}).get("pattern")
            if self._has_signal(page.text, field):
                signalled.add(field.key)
            if not pattern:
                continue
            try:
                compiled = re.compile(pattern, re.IGNORECASE)
            except re.error:
                continue
            for index, line in enumerate(lines):
                surrounding = lines[max(0, index - 3) : min(len(lines), index + 4)]
                context = " | ".join(item.text for item in surrounding)
                for match in compiled.finditer(line.text):
                    value = " ".join(match.group("value").strip(" :;,.-").split())
                    if not value:
                        continue
                    label = line.text[: match.start("value")].strip(" :;,-")[-100:]
                    # Prefer the candidate's own line; surrounding lines only supply
                    # a role when the occurrence itself is semantically neutral.
                    local_context = line.text[
                        max(0, match.start("value") - 80):min(len(line.text), match.end("value") + 80)
                    ]
                    role = self.role(
                        field.key,
                        local_context if field.key == "richiedente" else line.text,
                    )
                    if role == "SCONOSCIUTO":
                        role = self.role(field.key, context)
                    if role == "SCONOSCIUTO":
                        role = (field.strategy or {}).get("candidate_role") or role
                    suspicious = bool(re.search(r"[$€£§@#{}\[\]<>|\\]", line.text))
                    semantic_confidence = (0.92 if label else 0.78) - (0.25 if suspicious else 0)
                    candidates.append(
                        {
                            "field_key": field.key,
                            "raw_value": value,
                            "semantic_role": role,
                            "semantic_confidence": max(0.35, semantic_confidence),
                            "vision_confidence": 0.0,
                            "evidence_text": line.text[:240],
                            "bounding_box": self._value_bbox(match, line),
                            "relationships": [],
                            "source_engine": "deterministic_python",
                            "context": {
                                "line_text": line.text,
                                "previous_line": lines[index - 1].text if index else "",
                                "next_line": lines[index + 1].text if index + 1 < len(lines) else "",
                                "previous_lines": [item.text for item in lines[max(0, index - 3):index]],
                                "next_lines": [item.text for item in lines[index + 1:min(len(lines), index + 4)]],
                                "label_text": label,
                                "line_bbox": line.bbox,
                                "block_id": f"page-{page.number:04d}:line-{index + 1:04d}",
                                "section_role": role,
                                "extraction_rule": pattern,
                            },
                        }
                    )

        enabled = {field.key for field in fields}
        if {"odonimo", "civico"} <= enabled:
            paired = self._address_pair_candidates(page, lines)
            existing = {
                (item["field_key"], item["raw_value"].casefold(), item["evidence_text"].casefold())
                for item in candidates
            }
            for candidate in paired:
                key = (
                    candidate["field_key"],
                    candidate["raw_value"].casefold(),
                    candidate["evidence_text"].casefold(),
                )
                if key not in existing:
                    candidates.append(candidate)
                    existing.add(key)

        source = str(page.vision_features.get("text_source", "unknown"))
        quality = float(page.vision_features.get("text_quality", 0.0))
        effective_quality = quality
        quality_threshold = self.ocr_quality_threshold
        reasons: list[str] = []
        if source != "minicpm_ocr":
            reasons.append(f"unsupported text source {source}")
        if effective_quality < quality_threshold:
            reasons.append(
                "effective OCR text quality below threshold "
                f"({effective_quality:.2f} < {quality_threshold:.2f})"
            )
        found = {item["field_key"] for item in candidates}
        reasons.extend(
            f"label detected without a valid {key} candidate" for key in sorted(signalled - found)
        )
        grouped: dict[tuple[str, str], set[str]] = {}
        for candidate in candidates:
            key = (candidate["field_key"], candidate["semantic_role"])
            grouped.setdefault(key, set()).add(candidate["raw_value"].casefold())
            if float(candidate.get("semantic_confidence", 0.0)) < self.candidate_confidence_threshold:
                reasons.append(
                    f"low-confidence {candidate['field_key']} candidate without a reliable label"
                )
        for (field_key, role), values in grouped.items():
            if len(values) > 1 and field_key not in {"particella", "subalterno"}:
                reasons.append(f"competing {field_key} values in role {role}")
        accepted = not reasons
        output = {
            "document_assignment": (previous_context or {}).get(
                "document_assignment", "documento_principale"
            ),
            "document_type": "minicpm_ocr_document",
            "page_type": "minicpm_ocr",
            "page_type_confidence": effective_quality,
            "role_confidence": 0.9 if accepted else 0.55,
            "starts_new_document": page.number == 1,
            "continuation_confidence": 0.9 if page.number > 1 else 0.0,
            "new_document_confidence": 0.1 if page.number > 1 else 1.0,
            "boundary_confidence": 0.9 if accepted else 0.45,
            "continuity_signals": ["deterministic_text_review"],
            "separation_signals": [],
            "page_summary": " ".join(line.text for line in lines)[:500],
            "entity_candidates": candidates,
            "evidence": [],
            "local_conflicts": [],
            "requires_review": not accepted,
        }
        metrics = {
            "phase": "python_micro_memory_review",
            "text_source": source,
            "text_quality": round(quality, 3),
            "effective_text_quality": round(effective_quality, 3),
            "quality_threshold": quality_threshold,
            "source_risk_penalty": 0.0,
            "line_count": len(lines),
            "candidate_count": len(candidates),
            "accepted": accepted,
            "reasons": reasons,
            "prompt_tokens": 0,
            "completion_tokens": 0,
        }
        return DeterministicReview(output, candidates, accepted, reasons, metrics)

    @staticmethod
    def review_payloads(payloads: list[dict[str, Any]]) -> dict[str, Any]:
        """Mandatory Python review of candidates produced from MiniCPM OCR."""
        reasons: list[str] = []
        reviewed = 0
        for payload in payloads:
            field_key = str(payload.get("field_key", ""))
            value = str(payload.get("raw_value", payload.get("value", ""))).strip()
            if not field_key or not value:
                reasons.append("candidate missing field_key or value")
                continue
            bbox = payload.get("bounding_box")
            if bbox is not None and (
                not isinstance(bbox, list)
                or len(bbox) != 4
                or not all(isinstance(item, (int, float)) and 0 <= item <= 1 for item in bbox)
            ):
                reasons.append(f"invalid bounding box for {field_key}")
            reviewed += 1
        return {
            "status": "certified" if not reasons else "reviewed_with_warnings",
            "reviewed_candidates": reviewed,
            "warnings": sorted(set(reasons)),
            "writer": "python_only",
        }
