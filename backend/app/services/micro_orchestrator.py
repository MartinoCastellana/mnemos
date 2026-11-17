import hashlib
import json
import re
import time
from collections import defaultdict
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Callable

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import (
    AuditEvent,
    CadastralPair,
    Conflict,
    Document,
    EntityCandidate,
    EntityCluster,
    EntityRelationship,
    FieldDefinition,
    FieldResult,
    Page,
    PageMicroMemory,
    PageObservation,
    ProcessingRun,
    RecoveryRequest,
    ResolvedField,
)
from app.services.deterministic_memory import DeterministicMicroMemoryEngine
from app.services.extraction import EvidenceConsensusEngine, LocalizationEngine, ModelGateway
from app.services.memory import OCRBlock, PageMemory
from app.services.ocr import MiniCPMOCRService, load_pdf_page, optimize_pdf


def clamp(value, default: float = 0.0) -> float:
    return min(1.0, max(0.0, float(value))) if isinstance(value, (int, float)) else default


class ProcessingInterrupted(Exception):
    """Raised at a safe checkpoint after the user requests an interruption."""


class AgentOrchestrator:
    """Three-level page memory -> global memory -> final extraction pipeline."""

    def __init__(self):
        self.settings = get_settings()
        self.gateway = ModelGateway(self.settings)
        self.consensus = EvidenceConsensusEngine()
        self.localization = LocalizationEngine()
        self.deterministic = DeterministicMicroMemoryEngine(self.gateway.profiles.rules)

    def _audit(self, db: Session, document_id: str, stage: str, action: str, detail=None):
        db.add(
            AuditEvent(
                document_id=document_id,
                stage=stage,
                agent="MicroMemoryOrchestrator",
                action=action,
                detail=detail or {},
            )
        )

    @staticmethod
    def _valid(
        field_key: str, value: str, field: FieldDefinition | None = None
    ) -> bool:
        lowered = value.casefold()
        if not value.strip():
            return False
        if field:
            pattern = (field.validator or {}).get("value_pattern")
            if pattern:
                try:
                    return bool(re.fullmatch(str(pattern), value, flags=re.IGNORECASE))
                except re.error:
                    return False
        if field_key == "protocollo":
            digits = sum(character.isdigit() for character in value)
            return digits >= 2 and digits / max(len(value), 1) >= 0.5 and not any(
                character in value for character in "/.,"
            )
        if field_key in {"data_protocollo", "data_valutazione"}:
            if not re.fullmatch(r"\d{2}/\d{2}/\d{4}", value):
                return False
            try:
                day, month, year = (int(part) for part in value.split("/"))
                date(year, month, day)
            except ValueError:
                return False
            return True
        if field_key == "richiedente":
            forbidden = ("comune di", "residente", "domicili", "via ", "viale ", "piazza ")
            phrase_words = (
                "dichiara", "congiuntamente", "committente", "sottoscritt", "firma",
                "ha sollecitato", "chiede", "richiede", "presenta",
            )
            return (
                len(value.split()) >= 2
                and not any(token in lowered for token in forbidden + phrase_words)
                and not bool(re.search(r"\d{2,}", value))
            )
        if field_key == "odonimo":
            generic_form_labels = (
                "località o frazione", "localita o frazione", "foglio", "allegato",
                "ubicazione (via o piazza - piano)",
            )
            meaningful = re.sub(
                r"^(?:via|viale|piazza|strada|contrada|località|localita)\s+",
                "",
                lowered,
            ).strip(" .,:;-")
            return (
                lowered.strip(" .,:;-")
                not in {"via", "viale", "piazza", "strada", "contrada", "località", "localita"}
                and
                not any(token in lowered for token in generic_form_labels)
                and len(re.sub(r"[^a-zà-ÿ]", "", meaningful)) >= 2
                and not bool(re.search(r"(?:\s|,)n?\.?\s*\d+[A-Za-z]?$", value))
            )
        if field_key == "comune":
            return not any(
                token in lowered
                for token in ("provincia", "regione", "prefettura", "città metropolitana")
            ) and not bool(re.search(r"\d", value))
        if field_key == "civico":
            return bool(re.fullmatch(r"\d+[A-Za-z]?(?:[/ -][A-Za-z0-9]+)?", value))
        if field_key == "categoria_catastale":
            return bool(re.fullmatch(r"[A-Za-z]/\d{2}", value.replace(" ", "")))
        if field_key == "subalterno":
            return bool(re.fullmatch(r"\d{1,2}", value.strip()))
        if field:
            validator = field.validator or {}
            minimum = int(validator.get("min_length", 1))
            maximum = int(validator.get("max_length", 500))
            return minimum <= len(value.strip()) <= maximum
        return True

    @staticmethod
    def _normalize_value(field_key: str, value: str) -> str:
        """Normalize strict public formats before validation and persistence."""
        if field_key in {"data_protocollo", "data_valutazione"}:
            match = re.fullmatch(r"(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{4})", value)
            if match:
                day, month, year = (int(part) for part in match.groups())
                return f"{day:02d}/{month:02d}/{year:04d}"
        if field_key == "richiedente":
            value = re.sub(
                r"^(?:sig\.?ra?|signora?|dott\.?ssa?|ing\.?|arch\.?)\s+",
                "",
                value,
                flags=re.IGNORECASE,
            )
            value = re.split(
                r"\s+(?:nato|nata|residente|domiciliato|dichiara|congiuntamente)\b",
                value,
                maxsplit=1,
                flags=re.IGNORECASE,
            )[0]
            value = " ".join(value.strip(" ,;:-").split()).upper()
        if field_key == "comune":
            value = re.sub(r"^(?:comune|municipio|città)\s+di\s+", "", value, flags=re.IGNORECASE)
            value = re.split(
                r"\s+(?:alla|in)\s+(?:via|viale|piazza|strada|contrada|località)\b|\s+(?:via|viale|piazza|strada|contrada|località)\b",
                value,
                maxsplit=1,
                flags=re.IGNORECASE,
            )[0].strip(" ,;:-")
            value = value.upper()
        if field_key == "categoria_catastale":
            value = value.replace(" ", "").upper()
        if field_key == "esito_valutazione":
            if any(token in value.casefold() for token in ("approv", "favorevol", "positiv")):
                return "POSITIVO"
            if any(token in value.casefold() for token in ("respint", "contrari", "negativ", "rigett")):
                return "NEGATIVO"
        return value

    @staticmethod
    def _semantically_valid(field_key: str, value: str, evidence: str) -> bool:
        context = (evidence or "").casefold()
        value_lower = value.casefold().strip()
        if field_key == "richiedente" and value_lower in {
            "il richiedente",
            "il denunciante",
            "richiedente",
            "denunciante",
            "firma",
        }:
            return False
        cadastral_markers = {
            "foglio": ("foglio", "fg.", "fog."),
            "particella": ("particella", "p.lla", "mappale", "mapp."),
            "subalterno": ("subalterno", "sub.", "subalt."),
        }
        if field_key in cadastral_markers:
            return any(marker in context for marker in cadastral_markers[field_key])
        if field_key == "data_valutazione":
            return bool(re.fullmatch(r"\d{2}/\d{2}/\d{4}", value))
        if field_key == "esito_valutazione":
            return value_lower in {"positivo", "negativo"}
        if field_key == "civico":
            return any(
                marker in context
                for marker in ("via ", "viale ", "piazza ", "strada ", "contrada ", "località ", "ubicazione", "immobile")
            )
        return True

    @staticmethod
    def _date_value(value: str) -> date | None:
        try:
            day, month, year = (int(part) for part in value.split("/"))
            return date(year, month, day)
        except (TypeError, ValueError):
            return None

    def _summary(
        self,
        winners: dict[str, EntityCandidate | None],
        field_definitions: dict[str, FieldDefinition] | None = None,
    ) -> str:
        parts = []
        field_definitions = field_definitions or {}
        fields = self.gateway.profiles.rules.get("fields", {})
        summary = fields.get("sintesi", {})
        summary_fields = summary.get(
            "summary_fields", [key for key in fields if key != "sintesi"]
        )
        for key in summary_fields:
            item = winners.get(key)
            if item:
                label = (
                    field_definitions[key].label
                    if key in field_definitions
                    else fields.get(key, {}).get("label", key)
                )
                parts.append(f"{label}: {item.raw_value}")
        max_length = int(summary.get("max_length", 100))
        return "; ".join(parts)[:max_length] or "NON_RILEVATO"

    @staticmethod
    def _same_occurrence(left: EntityCandidate, right: EntityCandidate) -> bool:
        """Require same-page address components to share textual evidence."""
        if left.page_number != right.page_number:
            return False
        left_evidence = " ".join((left.evidence_text or "").casefold().split())
        right_evidence = " ".join((right.evidence_text or "").casefold().split())
        if left_evidence and right_evidence and (
            left_evidence == right_evidence
            or left_evidence in right_evidence
            or right_evidence in left_evidence
        ):
            return True
        return False

    def _relational_bonuses(self, by_field: dict[str, list[EntityCandidate]]) -> dict[int, float]:
        """Score correlated values as document blocks before choosing single fields."""
        bonuses: dict[int, float] = defaultdict(float)

        # A protocol date is meaningful when it is on the same page and close to a
        # plausible protocol number. This association must precede conflict detection.
        for protocol in by_field.get("protocollo", []):
            dates = [
                item
                for item in by_field.get("data_protocollo", [])
                if item.page_number == protocol.page_number
            ]
            if dates:
                date = max(dates, key=self._candidate_score)
                bonuses[protocol.id] += 0.08
                bonuses[date.id] += 0.18

        # Protocollo/data and valutazione/data-esito are the two explicit chronological
        # exceptions: within each domain the newest coherent occurrence gets priority.
        for left_key, right_key in (("protocollo", "data_protocollo"), ("esito_valutazione", "data_valutazione")):
            pairs = []
            for right in by_field.get(right_key, []):
                parsed = self._date_value(right.raw_value)
                if not parsed:
                    continue
                lefts = [item for item in by_field.get(left_key, []) if item.page_number == right.page_number]
                if lefts:
                    left = max(lefts, key=self._candidate_score)
                    pairs.append((parsed, left, right))
            if pairs:
                _, left, right = max(pairs, key=lambda item: item[0])
                bonuses[left.id] += 0.24
                bonuses[right.id] += 0.24

        # Comune and odonimo form a valid property address even when the source
        # explicitly has no civic number. A civic number is added only when it belongs
        # to the same visible occurrence as the odonimo.
        address_fields = ("comune", "odonimo", "civico")
        pages = {item.page_number for key in address_fields for item in by_field.get(key, [])}
        best_group: tuple[float, list[EntityCandidate]] | None = None
        for page in pages:
            groups = [
                [item for item in by_field.get(key, []) if item.page_number == page]
                for key in address_fields
            ]
            if not groups[0] or not groups[1]:
                continue
            for comune in groups[0]:
                for odonimo in groups[1]:
                    if comune.normalized_value == odonimo.normalized_value:
                        continue
                    pair_local = sum(self._candidate_score(item) for item in (comune, odonimo)) / 2
                    pair_role_bonus = (
                        0.35
                        if odonimo.semantic_role == "IMMOBILE_RICHIESTA"
                        else -0.20
                        if odonimo.semantic_role in {"RICHIEDENTE_RESIDENZA", "TECNICO", "PAGAMENTO"}
                        else 0.0
                    )
                    pair_score = pair_local + pair_role_bonus
                    if best_group is None or pair_score > best_group[0]:
                        best_group = (pair_score, [comune, odonimo])
                    for civico in (
                        item for item in groups[2]
                        if self._same_occurrence(odonimo, item)
                    ):
                        local = sum(
                            self._candidate_score(item) for item in (comune, odonimo, civico)
                        ) / 3
                        roles = {odonimo.semantic_role, civico.semantic_role}
                        role_bonus = (
                            0.45
                            if roles == {"IMMOBILE_RICHIESTA"}
                            else -0.40
                            if roles & {"RICHIEDENTE_RESIDENZA", "TECNICO", "PAGAMENTO"}
                            else 0.0
                        )
                        score = local + role_bonus
                        if best_group is None or score > best_group[0]:
                            best_group = (score, [comune, odonimo, civico])
        if best_group:
            for item in best_group[1]:
                bonuses[item.id] += 0.28
        return bonuses

    def _resume_or_create(
        self, db: Session, document: Document, prompt_hash: str, page_count: int
    ) -> ProcessingRun:
        runs = db.scalars(
            select(ProcessingRun)
            .where(
                ProcessingRun.document_id == document.id,
                ProcessingRun.prompt_hash == prompt_hash,
                ProcessingRun.status == "FAILED",
            )
            .order_by(ProcessingRun.started_at.desc())
        )
        for run in runs:
            completed = db.scalar(
                select(PageMicroMemory.id).where(PageMicroMemory.run_id == run.id).limit(1)
            )
            count = len(
                list(db.scalars(select(PageMicroMemory.id).where(PageMicroMemory.run_id == run.id)))
            )
            if completed and count < page_count:
                run.status, run.error, run.completed_at = "PROCESSING", None, None
                return run
        run = ProcessingRun(
            document_id=document.id,
            pipeline_version=self.gateway.profiles.version,
            model_name=self.settings.model_name,
            prompt_hash=prompt_hash,
            render_config={
                "dpi": 120,
                "preprocessing": "color_preserving",
                "orientation_detector": "tesseract_osd",
                "orientation_confidence_threshold": 12.0,
                "page_batch_size": 1,
                "checkpoint": "per_page",
                "ocr_engine": "MiniCPM-OCR",
                "python_micro_memory_review": True,
                "candidate_writer": "python_only",
                "global_candidates_per_field": int(
                    self.gateway.profiles.rules.get("review", {}).get(
                        "global_candidates_per_field", 5
                    )
                ),
                "fields_only": True,
                "python_only_writer": True,
            },
        )
        db.add(run)
        db.flush()
        return run

    def _load_page(
        self, db: Session, document: Document, page_number: int, pdf_path: str
    ) -> PageMemory:
        pdf_stat = Path(pdf_path).stat()
        pdf_revision = f"{pdf_stat.st_size}:{pdf_stat.st_mtime_ns}"
        stored = db.scalar(
            select(Page).where(Page.document_id == document.id, Page.page_number == page_number)
        )
        if stored:
            if (
                stored.vision_features.get("text_source") == "minicpm_ocr"
                and stored.vision_features.get("working_pdf") == Path(pdf_path).name
                and stored.vision_features.get("working_pdf_revision") == pdf_revision
            ):
                return PageMemory(
                    number=stored.page_number,
                    text=stored.text,
                    blocks=[OCRBlock(**block) for block in stored.blocks],
                    summary=stored.summary,
                    vision_features=stored.vision_features,
                    anchors=stored.anchors,
                    embedding=stored.embedding,
                    cluster=stored.cluster_label,
                    render_path=stored.render_path,
                )
        render_dir = Path(pdf_path).parent / "pages"
        page = load_pdf_page(pdf_path, render_dir, page_number)
        page.vision_features["working_pdf"] = Path(pdf_path).name
        page.vision_features["working_pdf_revision"] = pdf_revision
        page_values = {
            "text": page.text,
            "blocks": [
                {"text": block.text, "bbox": block.bbox, "confidence": block.confidence}
                for block in page.blocks
            ],
            "vision_features": page.vision_features,
            "render_path": page.render_path,
        }
        if stored:
            for key, value in page_values.items():
                setattr(stored, key, value)
        else:
            db.add(Page(document_id=document.id, page_number=page.number, **page_values))
        db.flush()
        return page

    @staticmethod
    def _deduplicate_payloads(payloads: list[dict]) -> list[dict]:
        unique: dict[tuple[str, str, int | None], dict] = {}
        for payload in payloads:
            key = str(payload.get("field_key", ""))
            value = " ".join(str(payload.get("raw_value", payload.get("value", ""))).split())
            page_number = payload.get("page_number")
            identity = (key, value.casefold(), page_number)
            previous = unique.get(identity)
            previous_score = clamp(previous.get("semantic_confidence")) if previous else -1
            if previous is None or clamp(payload.get("semantic_confidence")) > previous_score:
                unique[identity] = payload
        return list(unique.values())

    @staticmethod
    def _candidate_score(item: EntityCandidate) -> float:
        return item.semantic_confidence * 0.75 + item.ocr_confidence * 0.25

    @staticmethod
    def _eligible_candidates(field_key: str, rows: list[EntityCandidate]) -> list[EntityCandidate]:
        del field_key
        return list(rows)

    def _selection_allowed(
        self,
        field_key: str,
        item: EntityCandidate,
        definition: FieldDefinition | None = None,
    ) -> bool:
        field_rules = self.gateway.profiles.field_config(field_key)
        profile = self.gateway.profiles.rules.get("profiles", {}).get(
            field_rules.get("profile"), {}
        )
        strategy = definition.strategy or {} if definition else {}
        allowed_roles = strategy.get("allowed_roles", profile.get("allowed_roles", []))
        if allowed_roles and item.semantic_role not in allowed_roles:
            return False
        if not self._valid(field_key, item.raw_value, definition):
            return False
        if not self._semantically_valid(field_key, item.raw_value, item.evidence_text):
            return False
        if field_key == "richiedente" and item.semantic_role == "TECNICO":
            return False
        return not (
            field_key in {"comune", "odonimo", "civico"}
            and item.semantic_role in {"RICHIEDENTE_RESIDENZA", "TECNICO", "PAGAMENTO"}
        )

    def _analyze_page(
        self,
        db: Session,
        run: ProcessingRun,
        document: Document,
        page: PageMemory,
        previous: PageMicroMemory | None,
    ) -> PageMicroMemory:
        previous_context = None
        fields = list(
            db.scalars(
                select(FieldDefinition)
                .where(FieldDefinition.enabled.is_(True))
                .order_by(FieldDefinition.id)
            )
        )
        definitions_by_key = {field.key: field for field in fields}
        deterministic_review = self.deterministic.analyze(page, fields, previous_context)
        rejected_deterministic_fields = sorted(
            {
                str(item.get("field_key", ""))
                for item in deterministic_review.candidates
                if not self._valid(
                    str(item.get("field_key", "")),
                    str(item.get("raw_value", "")),
                    definitions_by_key.get(str(item.get("field_key", ""))),
                )
                or not self._semantically_valid(
                    str(item.get("field_key", "")),
                    str(item.get("raw_value", "")),
                    str(item.get("evidence_text", "")),
                )
            }
        )
        if rejected_deterministic_fields:
            deterministic_review.accepted = False
            deterministic_review.reasons.extend(
                f"python validator rejected {field_key} candidate"
                for field_key in rejected_deterministic_fields
            )
            deterministic_review.metrics.update(
                {
                    "accepted": False,
                    "reasons": deterministic_review.reasons,
                }
            )
        model_calls = [
            deterministic_review.metrics,
            page.vision_features.get("ocr_metrics", {}),
        ]
        payloads = list(deterministic_review.candidates)
        assignment = "fascicolo_non_segmentato"
        payloads = self._deduplicate_payloads(payloads)
        if any(item.get("field_key") == "esito_valutazione" for item in payloads):
            existing_dates = {
                self._normalize_value("data_valutazione", str(item.get("raw_value", "")))
                for item in payloads
                if item.get("field_key") == "data_valutazione"
            }
            for match in re.finditer(r"\b\d{1,2}[./-]\d{1,2}[./-]\d{4}\b", page.text):
                raw_date = match.group(0)
                normalized_date = self._normalize_value("data_valutazione", raw_date)
                if normalized_date in existing_dates or not self._valid(
                    "data_valutazione", normalized_date
                ):
                    continue
                context = self.deterministic.context_for(page, raw_date)
                line = str(context.get("line_text", "")).casefold()
                if "presentat" in line or "domanda" in line:
                    date_role = "DATA_PRESENTAZIONE"
                elif "riferimento" in line or "richiam" in line:
                    date_role = "DATA_RICHIAMATA"
                else:
                    date_role = "DATA_ATTO"
                context["date_context_role"] = date_role
                payloads.append(
                    {
                        "field_key": "data_valutazione",
                        "raw_value": raw_date,
                        "semantic_role": "VALUTAZIONE_FINALE",
                        "semantic_confidence": 0.84 if date_role == "DATA_ATTO" else 0.72,
                        "vision_confidence": 0.0,
                        "evidence_text": str(context.get("line_text", raw_date))[:240],
                        "bounding_box": self.localization.locate(raw_date, page.blocks),
                        "relationships": ["evaluation_event_date"],
                        "source_engine": "deterministic_python",
                        "context": context,
                    }
                )
                existing_dates.add(normalized_date)
            payloads = self._deduplicate_payloads(payloads)
        saved_payloads = []
        rejected_payloads: list[dict[str, str]] = []
        low_confidence_payloads: list[dict[str, str]] = []
        ocr_confidence = (
            sum(block.confidence for block in page.blocks) / len(page.blocks) if page.blocks else 0
        )
        valid_keys = {field.key for field in fields}
        for payload in payloads:
            field_key = str(payload.get("field_key", ""))
            value = " ".join(str(payload.get("raw_value", payload.get("value", ""))).split())
            value = self._normalize_value(field_key, value)
            evidence_text = " ".join(str(payload.get("evidence_text", "")).split())[:240]
            if field_key not in valid_keys or not value or field_key == "sintesi":
                rejected_payloads.append(
                    {
                        "field_key": field_key,
                        "value": value,
                        "reason": (
                            "python_deterministic_summary_only" if field_key == "sintesi"
                            else "unknown_field" if field_key not in valid_keys else "empty_value"
                        ),
                    }
                )
                continue
            format_valid = self._valid(field_key, value, definitions_by_key.get(field_key))
            semantics_valid = self._semantically_valid(field_key, value, evidence_text)
            validation_warning = None
            if not format_valid:
                validation_warning = "invalid_format"
            elif not semantics_valid:
                validation_warning = "invalid_semantics"
            if validation_warning:
                low_confidence_payloads.append(
                    {"field_key": field_key, "value": value, "reason": validation_warning}
                )
            bbox = payload.get("bounding_box")
            if (
                not isinstance(bbox, list)
                or len(bbox) != 4
                or not all(isinstance(value, (int, float)) and 0 <= value <= 1 for value in bbox)
            ):
                bbox = self.localization.locate(value, page.blocks)
            source_engine = str(payload.get("source_engine", "deterministic_python"))
            payload_context = payload.get("context") or self.deterministic.context_for(page, value)
            contextual_text = " | ".join(
                str(item)
                for item in (
                    payload_context.get("previous_lines", []),
                    payload_context.get("line_text", evidence_text),
                    payload_context.get("next_lines", []),
                )
            )
            semantic_role = (
                str(payload.get("semantic_role"))
                if source_engine == "deterministic_python" and payload.get("semantic_role")
                else self.deterministic.role(field_key, contextual_text)
            )
            semantic = (
                min(0.95, clamp(payload.get("semantic_confidence"), 0.5))
                if source_engine == "deterministic_python"
                else (0.86 if semantic_role != "SCONOSCIUTO" else 0.60)
            )
            vision = min(0.95, clamp(payload.get("vision_confidence"), 0.0))
            if semantic == 0:
                semantic = 0.45
            if re.search(r"[$€£§@#{}\[\]<>|\\]", value):
                semantic = max(0.25, semantic - 0.25)
            if field_key in {"comune", "odonimo", "civico"}:
                if semantic_role == "IMMOBILE_RICHIESTA":
                    semantic = min(1.0, semantic + (0.08 if field_key != "civico" else 0.14))
                elif semantic_role in {"RICHIEDENTE_RESIDENZA", "TECNICO", "PAGAMENTO"}:
                    semantic = max(0.20, semantic - 0.35)
            if validation_warning:
                semantic = min(semantic, 0.45)
                vision = min(vision, 0.45)
            row = EntityCandidate(
                run_id=run.id,
                document_id=document.id,
                field_key=field_key,
                entity_type="text",
                raw_value=value,
                normalized_value=self.consensus.normalize(value),
                page_number=page.number,
                chunk_id=f"page-{page.number:04d}",
                semantic_role=semantic_role,
                semantic_confidence=semantic,
                ocr_confidence=ocr_confidence,
                vision_confidence=vision,
                evidence_text=evidence_text,
                bounding_box=bbox,
                source_engine=source_engine,
                requires_review=bool(validation_warning) or semantic < 0.6 or (
                    source_engine != "deterministic_python" and vision < 0.6
                ),
            )
            db.add(row)
            db.flush()
            saved_payloads.append(
                {
                    **payload,
                    "candidate_id": row.id,
                    "raw_value": value,
                    "semantic_confidence": semantic,
                    "vision_confidence": vision,
                    "evidence_text": evidence_text,
                    "bounding_box": bbox,
                    "context": {**payload_context, "section_role": row.semantic_role},
                }
            )
        final_python_review = self.deterministic.review_payloads(saved_payloads)
        checkpoint_hash = hashlib.sha256(
            f"{run.prompt_hash}:{document.sha256}:{page.number}:{page.text}".encode()
        ).hexdigest()
        micro = PageMicroMemory(
            run_id=run.id,
            document_id=document.id,
            page_number=page.number,
            checkpoint_hash=checkpoint_hash,
            document_assignment=assignment,
            document_type="minicpm_ocr_document",
            page_type="minicpm_ocr",
            page_type_confidence=float(page.vision_features.get("text_quality", 0.0)),
            role_confidence=0.9 if deterministic_review.accepted else 0.55,
            continuation_confidence=0.0,
            new_document_confidence=0.0,
            boundary_confidence=0.0,
            starts_new_document=False,
            ocr={
                "text": page.text,
                "confidence": ocr_confidence,
                "blocks": [
                    {"text": block.text, "bbox": block.bbox, "confidence": block.confidence}
                    for block in page.blocks
                ],
            },
            vision_analysis={**page.vision_features, "model_calls": model_calls},
            field_states={
                "deterministic_review": {
                    "accepted": deterministic_review.accepted,
                    "reasons": deterministic_review.reasons,
                    "candidate_count": len(deterministic_review.candidates),
                },
                "candidate_generation": {"writer": "python", "engine": "MiniCPM-OCR"},
                "final_python_review": final_python_review,
                "candidate_validation": {
                    "received": len(payloads),
                    "accepted": len(saved_payloads),
                    "accepted_low_confidence": low_confidence_payloads,
                    "rejected": rejected_payloads,
                    "writer": "python_only",
                },
            },
            entity_candidates=saved_payloads,
            continuity_signals=[],
            separation_signals=[],
            page_summary=str(deterministic_review.output.get("page_summary", ""))[:500],
            evidence=[],
            local_conflicts=[],
            requires_review=bool(rejected_payloads) or not deterministic_review.accepted,
        )
        db.add(micro)
        db.add(
            PageObservation(
                run_id=run.id,
                document_id=document.id,
                page_number=page.number,
                chunk_ids=[f"page-{page.number:04d}"],
                rendered=True,
                ocr_completed=True,
                vision_completed=False,
                entities_saved=True,
                page_quality=max(ocr_confidence, micro.page_type_confidence),
                observations={"checkpoint_hash": checkpoint_hash},
            )
        )
        stored = db.scalar(
            select(Page).where(Page.document_id == document.id, Page.page_number == page.number)
        )
        stored.summary = micro.page_summary
        stored.cluster_label = "fascicolo_non_segmentato"
        db.flush()
        return micro

    def _cluster_rows(self, rows: list[EntityCandidate]) -> list[list[EntityCandidate]]:
        clusters: list[list[EntityCandidate]] = []
        for row in rows:
            matching = next(
                (
                    cluster
                    for cluster in clusters
                    if cluster[0].semantic_role == row.semantic_role
                    and self.consensus.similarity(cluster[0].raw_value, row.raw_value) >= 0.72
                ),
                None,
            )
            (matching if matching is not None else clusters.append([row]))
            if matching is not None:
                matching.append(row)
        return clusters

    def _global_pass(
        self, db: Session, run: ProcessingRun, document: Document, instructions: str
    ):
        global_started = time.perf_counter()
        for model in (
            EntityRelationship,
            EntityCluster,
            ResolvedField,
            Conflict,
            RecoveryRequest,
            CadastralPair,
        ):
            db.execute(delete(model).where(model.run_id == run.id))
        db.execute(delete(FieldResult).where(FieldResult.document_id == document.id))
        micro_memories = list(
            db.scalars(
                select(PageMicroMemory)
                .where(PageMicroMemory.run_id == run.id)
                .order_by(PageMicroMemory.page_number)
            )
        )
        all_rows = list(db.scalars(select(EntityCandidate).where(EntityCandidate.run_id == run.id)))
        by_field: dict[str, list[EntityCandidate]] = defaultdict(list)
        for row in all_rows:
            by_field[row.field_key].append(row)
        relational_bonuses = self._relational_bonuses(by_field)
        winners: dict[str, EntityCandidate | None] = {}
        confidences: dict[str, float] = {}
        fields = list(
            db.scalars(
                select(FieldDefinition)
                .where(FieldDefinition.enabled.is_(True))
                .order_by(FieldDefinition.id)
            )
        )
        context_by_candidate = {
            payload.get("candidate_id"): payload.get("context", {})
            for memory in micro_memories
            for payload in memory.entity_candidates
            if isinstance(payload, dict) and payload.get("candidate_id")
        }
        compact_global_memory: dict[str, list[dict]] = {}
        candidate_limit = min(
            5,
            max(1, int(self.gateway.profiles.rules.get("review", {}).get("global_candidates_per_field", 5))),
        )
        for field in fields:
            candidate_pool = [
                item
                for item in self._eligible_candidates(field.key, by_field[field.key])
                if self._selection_allowed(field.key, item, field)
            ]
            ranked_rows = sorted(
                candidate_pool,
                key=lambda item: -(
                    self._candidate_score(item)
                    + relational_bonuses.get(item.id, 0.0)
                ),
            )[:candidate_limit]
            compact_global_memory[field.key] = [
                {
                    "candidate_id": item.id,
                    "value": item.raw_value,
                    "page_number": item.page_number,
                    "semantic_role": item.semantic_role,
                    "calculated_confidence": round(
                        min(
                            1.0,
                            self._candidate_score(item)
                            + relational_bonuses.get(item.id, 0.0),
                        ),
                        3,
                    ),
                    "evidence": item.evidence_text,
                    "context": {
                        key: value
                        for key, value in context_by_candidate.get(item.id, {}).items()
                        if "bbox" not in str(key).casefold()
                    },
                }
                for item in ranked_rows
            ]
        global_review_metrics = None
        global_selections: dict[str, dict] = {}
        if any(compact_global_memory.values()):
            global_review = self.gateway.resolve_fields_global(
                instructions,
                compact_global_memory,
                {field.key: field for field in fields},
            )
            global_review_metrics = self.gateway.last_metrics
            selections = global_review.get("selections", [])
            if isinstance(selections, list):
                global_selections = {
                    str(item.get("field_key")): item
                    for item in selections
                    if isinstance(item, dict)
                }
        for field in fields:
            scored_clusters = []
            eligible_rows = self._eligible_candidates(field.key, by_field[field.key])
            selectable_rows = [
                item for item in eligible_rows if self._selection_allowed(field.key, item, field)
            ]
            if field.key == "civico" and winners.get("odonimo"):
                selectable_rows = [
                    item for item in selectable_rows
                    if self._same_occurrence(winners["odonimo"], item)
                ]
            for cluster in self._cluster_rows(selectable_rows):
                pages = sorted({item.page_number for item in cluster})
                representative = max(
                    cluster,
                    key=self._candidate_score,
                )
                local = self._candidate_score(representative)
                corroboration = min(0.22, 0.07 * max(0, len(pages) - 1))
                confidence = min(1.0, local + corroboration)
                confidence = min(
                    1.0,
                    confidence + max(relational_bonuses.get(item.id, 0.0) for item in cluster),
                )
                cluster_row = EntityCluster(
                    run_id=run.id,
                    field_key=field.key,
                    normalized_value=representative.normalized_value,
                    representative_value=representative.raw_value,
                    semantic_role=representative.semantic_role,
                    candidate_ids=[item.id for item in cluster],
                    page_numbers=pages,
                    document_assignments=["fascicolo_non_segmentato"],
                    global_confidence=confidence,
                    evidence=[item.evidence_text for item in cluster if item.evidence_text],
                )
                db.add(cluster_row)
                scored_clusters.append((confidence, representative, cluster_row, pages))
            scored_clusters.sort(key=lambda item: -item[0])
            winner = None
            global_selected_by_resolver = False
            global_selection = global_selections.get(field.key)
            if global_selection and scored_clusters:
                selected_id = global_selection.get("selected_candidate_id")
                if isinstance(selected_id, str) and selected_id.isdigit():
                    selected_id = int(selected_id)
                chosen = next(
                    (item for item in scored_clusters if selected_id in item[2].candidate_ids),
                    None,
                )
                selected_row = next(
                    (item for item in by_field[field.key] if item.id == selected_id), None
                )
                if chosen and selected_row and self._selection_allowed(field.key, selected_row, field):
                    winner = (
                        chosen[0],
                        selected_row,
                        chosen[2],
                        chosen[3],
                    )
                    global_selected_by_resolver = True

            verified_null = (
                field.key == "civico"
                and winners.get("odonimo") is not None
                and not scored_clusters
            )
            selected = winner[1] if winner else None
            confidence = (
                winner[0]
                if winner
                else confidences.get("odonimo", 0.0) if verified_null else 0.0
            )
            display_source = selected or (winners.get("odonimo") if verified_null else None)
            below_null_threshold = (
                field.key != "sintesi" and confidence < 0.60 and not verified_null
            )
            if below_null_threshold:
                selected = None
            winners[field.key] = selected
            confidences[field.key] = confidence
            if selected:
                selected.selected = True
            for row in by_field[field.key]:
                if not selected or row.id != selected.id:
                    row.rejection_reason = "lower global confidence or semantic relevance"
            deterministic_summary = field.key == "sintesi"
            value = (
                self._summary(winners, {item.key: item for item in fields})
                if deterministic_summary
                else (selected.raw_value if selected else None)
            )
            if deterministic_summary:
                confidence = min(
                    (confidences[key] for key in ("richiedente", "comune", "odonimo", "civico", "protocollo") if winners.get(key)),
                    default=0.0,
                )
                confidences[field.key] = confidence
            reason = (
                [
                    (
                        "; ".join(global_selection.get("reason_codes", []))
                        or "selected by local Qwen from Python Global Memory"
                    )
                    if global_selected_by_resolver
                    else "Python wrote null because the selector did not choose a validated candidate"
                ]
                if selected
                else [
                    "property address verified without a civic number; explicit null written"
                    if verified_null
                    else "candidate below 0.60 confidence; explicit null written"
                    if below_null_threshold and display_source
                    else "no evidence-backed candidate; explicit null written"
                ]
            )
            db.add(
                ResolvedField(
                    run_id=run.id,
                    document_id=document.id,
                    field_key=field.key,
                    value=value,
                    confidence=confidence,
                    selected_candidate_id=selected.id if selected else None,
                    source_page=display_source.page_number if display_source else None,
                    bounding_box=display_source.bounding_box if display_source else None,
                    selection_reason=reason,
                    rejected_candidates=[
                        {"candidate_id": row.id, "value": row.raw_value}
                        for row in by_field[field.key]
                        if not selected or row.id != selected.id
                    ],
                    requires_review=(selected is None and not deterministic_summary and not verified_null) or bool(selected and selected.requires_review),
                )
            )
            db.add(
                FieldResult(
                    document_id=document.id,
                    field_key=field.key,
                    value=value,
                    confidence=confidence,
                    page_number=display_source.page_number if display_source else None,
                    bbox=display_source.bounding_box if display_source else None,
                    evidence=display_source.evidence_text if display_source else ("Sintesi deterministica Python" if deterministic_summary else ""),
                    reasoning=reason,
                    validated_by=(
                        "PythonDeterministicSummary" if deterministic_summary
                        else "QwenGlobalSelector" if global_selected_by_resolver
                        else "PYTHON_NULL_UNSELECTED"
                    ),
                    candidates=[
                        {
                            "candidate_id": row.id,
                            "value": row.raw_value,
                            "page_number": row.page_number,
                            "semantic_role": row.semantic_role,
                            "confidence": row.semantic_confidence,
                        }
                        for row in by_field[field.key]
                    ],
                )
            )
        self._link_entities(db, run, document, winners, confidences)
        return {
            "duration_ms": round((time.perf_counter() - global_started) * 1000),
            "global_review_model_call": global_review_metrics,
            "candidates": len(all_rows),
            "resolved_fields": len(fields),
            "populated_fields": len(fields),
            "evidence_backed_fields": sum(1 for value in winners.values() if value is not None),
            "placeholder_fields": [key for key, value in winners.items() if value is None],
            "empty_fields": [],
        }

    def _link_entities(self, db, run, document, winners, confidences):
        specs = self.gateway.profiles.rules.get("relationships", [])
        for left_key, right_key, relation in specs:
            left, right = winners.get(left_key), winners.get(right_key)
            if not left or not right:
                continue
            same_evidence = left.page_number == right.page_number
            if relation == "odonimo_ha_civico" and not same_evidence:
                right.selected = False
                right.rejection_reason = "civico not from the selected odonimo occurrence"
                continue
            db.add(
                EntityRelationship(
                    run_id=run.id,
                    relation_type=relation,
                    source_candidate_id=left.id,
                    target_candidate_id=right.id,
                    page_number=left.page_number if same_evidence else None,
                    confidence=min(confidences.get(left_key, 0), confidences.get(right_key, 0)),
                    evidence="same_page_occurrence" if same_evidence else "global_relation",
                )
            )
            if relation == "particella_ha_subalterno":
                db.add(
                    CadastralPair(
                        run_id=run.id,
                        document_id=document.id,
                        page_number=left.page_number,
                        particella_candidate_id=left.id,
                        subalterno_candidate_id=right.id,
                        confidence=min(confidences.get(left_key, 0), confidences.get(right_key, 0)),
                    )
                )

    def process(
        self,
        db: Session,
        document_id: str,
        mode: str = "AUTO",
        should_cancel: Callable[[], bool] | None = None,
    ) -> None:
        document = db.get(Document, document_id)
        if not document:
            raise ValueError("Documento non trovato")
        if should_cancel and should_cancel():
            document.status, document.error = "CANCELLED", None
            self._audit(
                db,
                document.id,
                "INTERRUPT",
                "Queued processing interrupted before optimization",
                {"status": "CANCELLED"},
            )
            db.commit()
            return
        instructions = self.settings.load_instructions()
        canonical_rules = json.dumps(
            self.gateway.profiles.rules, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        prompt_hash = hashlib.sha256(f"{instructions}\n{canonical_rules}".encode()).hexdigest()
        optimized_path, total_pages, optimization = optimize_pdf(document.storage_path)
        self._audit(
            db,
            document.id,
            "OPTIMIZATION",
            "PDF optimized and page rotations normalized",
            optimization,
        )
        db.commit()
        run = self._resume_or_create(db, document, prompt_hash, total_pages)
        document.status, document.pipeline_mode, document.error = "PROCESSING", mode, None
        document.page_count = total_pages
        self._audit(
            db,
            document.id,
            "PIPELINE",
            "Page-by-page Micro-Memory processing started",
            {
                "pages": total_pages,
                "prompt_source": "ISTRUZIONI GLOBALI.md",
                "rules_source": "instructions/pipeline_rules.json",
                "rules_version": self.gateway.profiles.version,
            },
        )
        db.commit()
        try:
            if should_cancel and should_cancel():
                raise ProcessingInterrupted
            health = self.gateway.wait_until_available(
                retry_interval_sec=30, should_cancel=should_cancel
            )
            if should_cancel and should_cancel():
                raise ProcessingInterrupted
            self._audit(
                db,
                document.id,
                "MODEL_HEALTH",
                "Model server available",
                health,
            )
            completed_pages = set(
                db.scalars(
                    select(PageMicroMemory.page_number).where(PageMicroMemory.run_id == run.id)
                )
            )
            previous = None
            for page_number in range(1, total_pages + 1):
                if should_cancel and should_cancel():
                    raise ProcessingInterrupted
                existing = db.scalar(
                    select(PageMicroMemory).where(
                        PageMicroMemory.run_id == run.id,
                        PageMicroMemory.page_number == page_number,
                    )
                )
                if page_number in completed_pages and existing:
                    previous = existing
                    continue
                page_started = time.perf_counter()
                page = self._load_page(db, document, page_number, optimized_path)
                self._audit(
                    db,
                    document.id,
                    "OCR",
                    f"OCR completo pagina {page_number}",
                    {
                        "page": page_number,
                        "blocks": len(page.blocks),
                        "load_ocr_render_ms": round((time.perf_counter() - page_started) * 1000),
                    },
                )
                analysis_started = time.perf_counter()
                previous = self._analyze_page(db, run, document, page, previous)
                self._audit(
                    db,
                    document.id,
                    "PAGE_CHECKPOINT",
                    f"Micro-Memory pagina {page_number} salvata",
                    {
                        "page": page_number,
                        "assignment": previous.document_assignment,
                        "analysis_ms": round((time.perf_counter() - analysis_started) * 1000),
                        "model_calls": previous.vision_analysis.get("model_calls", []),
                        "candidates": len(previous.entity_candidates),
                        "candidate_validation": previous.field_states.get(
                            "candidate_validation", {}
                        ),
                    },
                )
                db.commit()
            if should_cancel and should_cancel():
                raise ProcessingInterrupted
            minicpm = MiniCPMOCRService(self.settings)
            standby = minicpm.wait_until_standby(
                self.settings.minicpm_standby_timeout_sec
            )
            self._audit(
                db,
                document.id,
                "MODEL_SWITCH",
                "MiniCPM entered standby before Qwen global selection",
                standby,
            )
            warmup = self.gateway.warmup()
            self._audit(
                db,
                document.id,
                "MODEL_WARMUP",
                "Qwen warmed after MiniCPM standby",
                warmup,
            )
            db.commit()
            global_metrics = self._global_pass(db, run, document, instructions)
            if should_cancel and should_cancel():
                raise ProcessingInterrupted
            run.status, run.completed_at = "COMPLETED", datetime.now(UTC)
            document.status = "COMPLETED"
            self._audit(
                db,
                document.id,
                "GLOBAL_PASS",
                "Global Document Memory consolidated and final fields selected",
                {"pages": total_pages, "rank_used": False, **global_metrics},
            )
            db.commit()
        except ProcessingInterrupted:
            db.rollback()
            document = db.get(Document, document_id)
            run = db.get(ProcessingRun, run.id)
            now = datetime.now(UTC)
            document.status, document.error = "CANCELLED", None
            run.status, run.error, run.completed_at = "CANCELLED", None, now
            self._audit(
                db,
                document.id,
                "INTERRUPT",
                "Processing interrupted at a safe checkpoint",
                {"status": "CANCELLED"},
            )
            db.commit()
        except Exception as exc:
            db.rollback()
            document = db.get(Document, document_id)
            run = db.get(ProcessingRun, run.id)
            document.status, document.error = "FAILED", str(exc)
            run.status, run.error, run.completed_at = "FAILED", str(exc), datetime.now(UTC)
            self._audit(db, document.id, "PIPELINE", "Processing failed", {"error": str(exc)})
            db.commit()
            raise
