import base64
import json
import re
import time
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, ClassVar

import fitz
import httpx

from app.core.config import Settings
from app.db.models import FieldDefinition
from app.services.instruction_profiles import InstructionProfileCompiler, load_pipeline_rules
from app.services.memory import GlobalDocumentMemory, OCRBlock


@dataclass(slots=True)
class Candidate:
    value: str
    page_number: int
    bbox: list[float] | None
    evidence: str
    score: float
    reasons: list[str]
    agent: str = "ExtractionEngine"
    candidate_id: int | None = None


class ComplexityAnalyzer:
    def analyze(
        self, memory: GlobalDocumentMemory, field: FieldDefinition, candidates: list[Candidate]
    ) -> dict:
        low_ocr = sum(not page.text.strip() for page in memory.pages) / max(len(memory.pages), 1)
        conflicts = len({candidate.value.casefold() for candidate in candidates})
        score = min(
            1.0, len(memory.pages) / 300 * 0.35 + low_ocr * 0.4 + max(0, conflicts - 1) * 0.15
        )
        return {
            "score": round(score, 3),
            "conflicts": conflicts,
            "low_ocr_ratio": round(low_ocr, 3),
            "field_type": field.strategy.get("type", "text"),
        }


class ModelRouter:
    def route(self, complexity: dict, role: str = "MAIN_EXTRACTOR") -> dict:
        score = complexity["score"]
        size = "14B" if score >= 0.72 else "7B" if score >= 0.38 else "3B"
        return {"role": role, "model_size": size}


class ModelGateway:
    """Client for the local MLX Vision server."""

    MAX_GENERATION_TOKENS = 4096
    MAX_REPAIR_TOKENS = 2048

    def __init__(self, settings: Settings):
        self.settings = settings
        self.last_metrics: dict[str, Any] = {}
        rules_path = getattr(settings, "pipeline_rules_path", None)
        self.profiles = InstructionProfileCompiler(
            load_pipeline_rules(str(rules_path)) if rules_path else load_pipeline_rules()
        )

    def available(self) -> bool:
        return self.settings.model_backend == "mlx"

    def check_health(self) -> dict[str, Any]:
        started = time.perf_counter()
        response = httpx.get(
            f"{self.settings.model_endpoint.rstrip('/')}/v1/models", timeout=8
        )
        if response.is_error:
            raise RuntimeError(f"Model server health check {response.status_code}")
        payload = response.json()
        return {
            "available": True,
            "latency_ms": round((time.perf_counter() - started) * 1000),
            "models": len(payload.get("data", [])) if isinstance(payload, dict) else 0,
        }

    @staticmethod
    def _normalize_json_text(raw: str) -> str:
        """Extract the first balanced JSON object without inventing missing content."""
        cleaned = "".join(
            character
            for character in raw.lstrip("\ufeff")
            if character in "\n\r\t" or ord(character) >= 32
        ).strip()
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE)
        start = cleaned.find("{")
        if start < 0:
            return cleaned
        depth = 0
        in_string = False
        escaped = False
        for index, character in enumerate(cleaned[start:], start=start):
            if in_string:
                if escaped:
                    escaped = False
                elif character == "\\":
                    escaped = True
                elif character == '"':
                    in_string = False
                continue
            if character == '"':
                in_string = True
            elif character == "{":
                depth += 1
            elif character == "}":
                depth -= 1
                if depth == 0:
                    return cleaned[start : index + 1]
        return cleaned[start:]

    def _save_failed_json(
        self, raw: str, error: Exception, finish_reason: str | None, stage: str
    ) -> Path:
        diagnostic_dir = self.settings.storage_dir / "_diagnostics" / "model-json"
        diagnostic_dir.mkdir(parents=True, exist_ok=True)
        identifier = f"{time.time_ns()}-{stage}"
        raw_path = diagnostic_dir / f"{identifier}.txt"
        metadata_path = diagnostic_dir / f"{identifier}.json"
        raw_path.write_text(raw, encoding="utf-8")
        metadata_path.write_text(
            json.dumps(
                {
                    "stage": stage,
                    "error": str(error),
                    "finish_reason": finish_reason,
                    "characters": len(raw),
                    "raw_path": str(raw_path),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return raw_path

    @staticmethod
    def _parse_json(raw: str) -> tuple[dict[str, Any], str]:
        normalized = ModelGateway._normalize_json_text(raw)
        parsed = json.loads(normalized)
        if not isinstance(parsed, dict):
            raise TypeError("Il modello non ha restituito un oggetto JSON")
        return parsed, normalized

    def complete(
        self,
        prompt: str,
        role: dict,
        memory: GlobalDocumentMemory,
        system_prompt: str | None = None,
        after_file_prompt: str | None = None,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        shrink = 0 if len(memory.pages) <= 16 else 1 if len(memory.pages) <= 64 else 2
        for page in memory.pages:
            if page.render_path:
                if shrink:
                    pixmap = fitz.Pixmap(page.render_path)
                    pixmap.shrink(shrink)
                    image_bytes = pixmap.tobytes("png")
                else:
                    image_bytes = Path(page.render_path).read_bytes()
                encoded = base64.b64encode(image_bytes).decode("ascii")
                content.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{encoded}"},
                    }
                )
        if after_file_prompt:
            content.append({"type": "text", "text": after_file_prompt})
        messages: list[dict[str, Any]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": content})
        request_payload = {
                "model": self.settings.model_name,
                "messages": messages,
                "temperature": 0,
                # The KV cache is shared by instructions, image tokens, OCR and generation.
                # A page checkpoint is compact JSON; reserving the entire remaining context
                # made otherwise valid requests fail before generation even started.
                "max_tokens": max_tokens or self.MAX_GENERATION_TOKENS,
                "response_format": {"type": "json_object"},
            }
        started = time.perf_counter()
        response = httpx.post(
            f"{self.settings.model_endpoint.rstrip('/')}/v1/chat/completions",
            json=request_payload,
            timeout=600,
        )
        if response.is_error:
            raise RuntimeError(f"Model server {response.status_code}: {response.text[:1000]}")
        body = response.json()
        choice = body["choices"][0]
        raw = choice["message"]["content"]
        repaired = False
        try:
            parsed, normalized_raw = self._parse_json(raw)
        except (json.JSONDecodeError, TypeError) as first_error:
            first_failure_path = self._save_failed_json(
                raw, first_error, choice.get("finish_reason"), "initial"
            )
            # Regenerate from the source without feeding the malformed response back
            # into the context, where it could consume the repair token budget.
            repair_messages = [
                *messages,
                {
                    "role": "user",
                    "content": (
                        "La generazione precedente non ha rispettato il contratto JSON. "
                        "Rigenera dai dati sorgente un solo oggetto JSON valido e compatto. "
                        "Non restituire sintesi. Mantieni massimo 2 candidati per campo. "
                        "Chiudi stringhe, array e oggetto. Non aggiungere spiegazioni, "
                        "markdown o chiavi non richieste."
                    ),
                },
            ]
            repair_response = httpx.post(
                f"{self.settings.model_endpoint.rstrip('/')}/v1/chat/completions",
                json={**request_payload, "messages": repair_messages, "max_tokens": self.MAX_REPAIR_TOKENS},
                timeout=600,
            )
            if repair_response.is_error:
                raise RuntimeError(
                    f"Model JSON repair {repair_response.status_code}: "
                    f"{repair_response.text[:1000]}"
                ) from first_error
            repair_body = repair_response.json()
            choice = repair_body["choices"][0]
            raw = choice["message"]["content"]
            try:
                parsed, normalized_raw = self._parse_json(raw)
            except (json.JSONDecodeError, TypeError) as repair_error:
                repair_failure_path = self._save_failed_json(
                    raw, repair_error, choice.get("finish_reason"), "repair"
                )
                raise RuntimeError(
                    "Model returned invalid JSON after compact regeneration: "
                    f"{repair_error}; chars={len(raw)}; "
                    f"finish_reason={choice.get('finish_reason')}; "
                    f"initial_raw={first_failure_path}; repair_raw={repair_failure_path}"
                ) from repair_error
            body = repair_body
            repaired = True
        usage = body.get("usage", {}) if isinstance(body, dict) else {}
        self.last_metrics = {
            "duration_ms": round((time.perf_counter() - started) * 1000),
            "output_chars": len(normalized_raw),
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "finish_reason": choice.get("finish_reason"),
            "json_repaired": repaired,
            "max_tokens": request_payload["max_tokens"],
            "raw_response": normalized_raw,
            "initial_failure_path": str(first_failure_path) if repaired else None,
        }
        return parsed

    def resolve_fields_global(
        self, instructions: str, candidates_by_field: dict[str, list[dict]]
    ) -> dict[str, Any]:
        del instructions
        rules = self.profiles.rules
        global_memory = {
            field: [item for item in candidates[:5] if isinstance(item, dict)]
            for field, candidates in candidates_by_field.items()
            if candidates
        }
        field_rules: dict[str, dict[str, Any]] = {}
        for field_key in global_memory:
            config = self.profiles.field_config(field_key)
            profile = rules.get("profiles", {}).get(config.get("profile"), {})
            field_rules[field_key] = {
                "label": config.get("label", field_key),
                "allowed_roles": profile.get("allowed_roles", ["SCONOSCIUTO"]),
                "selection_instruction": profile.get("selection_instruction", ""),
            }
        source = {
            "fields": field_rules,
            "same_page_pairs": rules.get("same_page_pairs", []),
            "global_memory": global_memory,
        }
        source_text = json.dumps(source, ensure_ascii=False, separators=(",", ":"))
        prompt = "Scegli i candidati usando esclusivamente questa global memory:\n" + source_text
        system_prompt = """SELETTORE GLOBALE QWEN.
Per ogni campo elencato in fields scegli un solo candidate_id tra quelli presenti nella
relativa lista della global_memory. Non inventare, correggere, completare o trascrivere
valori: restituisci esclusivamente gli ID e brevi reason_codes. Considera ruolo,
evidenza, contesto, pagina e confidence. Rispetta le istruzioni e i ruoli ammessi per
ciascun campo. Le coppie in same_page_pairs devono riferirsi alla stessa pagina.
Restituisci un oggetto JSON con una scelta per ogni campo presente in fields:
{"selections":[{"field_key":"...","selected_candidate_id":0,"reason_codes":["..."]}]}.
"""

        def validate(payload: Any) -> list[dict[str, Any]] | None:
            if not isinstance(payload, list):
                return None
            expected = set(global_memory)
            grouped = {
                field: [
                    item for item in payload
                    if isinstance(item, dict) and str(item.get("field_key")) == field
                ]
                for field in expected
            }
            if any(len(items) != 1 for items in grouped.values()):
                return None
            accepted = [grouped[field][0] for field in global_memory]
            selected_pages: dict[str, int] = {}
            for item in accepted:
                field = str(item["field_key"])
                candidate_id = item.get("selected_candidate_id")
                if isinstance(candidate_id, str) and candidate_id.isdigit():
                    candidate_id = int(candidate_id)
                    item["selected_candidate_id"] = candidate_id
                selected = next(
                    (candidate for candidate in global_memory[field]
                     if candidate.get("candidate_id") == candidate_id),
                    None,
                )
                if selected is None:
                    return None
                if selected.get("page_number") is not None:
                    selected_pages[field] = int(selected["page_number"])
            for pair in source["same_page_pairs"]:
                if not isinstance(pair, list) or len(pair) != 2:
                    continue
                left, right = pair
                if left in selected_pages and right in selected_pages:
                    if selected_pages[left] != selected_pages[right]:
                        return None
            return accepted

        calls: list[dict[str, Any]] = []
        result = self.complete(
            prompt,
            {"role": "GLOBAL_SELECTOR"},
            GlobalDocumentMemory("global-selector"),
            system_prompt=system_prompt,
            max_tokens=max(600, 260 * len(global_memory)),
        )
        calls.append({"selector": "QWEN_GLOBAL", **self.last_metrics})
        accepted = validate(result.get("selections", []))
        if accepted is None:
            retry_prompt = (
                prompt
                + "\nLa risposta precedente non ha selezionato una volta ogni campo,"
                + " ha usato un ID assente o ha violato una coppia di pagine."
                + " Rigenera le scelte dalla stessa memoria senza proporre valori."
            )
            retry = self.complete(
                retry_prompt,
                {"role": "GLOBAL_SELECTOR_RETRY"},
                GlobalDocumentMemory("global-selector-retry"),
                system_prompt=system_prompt,
                max_tokens=max(600, 260 * len(global_memory)),
            )
            calls.append({"selector": "QWEN_GLOBAL_RETRY", **self.last_metrics})
            accepted = validate(retry.get("selections", []))
        self.last_metrics = {
            "calls": calls,
            "duration_ms": sum(int(item.get("duration_ms", 0)) for item in calls),
            "prompt_tokens": sum(int(item.get("prompt_tokens") or 0) for item in calls),
            "completion_tokens": sum(int(item.get("completion_tokens") or 0) for item in calls),
            "candidate_count": sum(len(items) for items in global_memory.values()),
            "field_count": len(global_memory),
        }
        return {"selections": accepted or []}


class RetrievalEngine:
    def retrieve(self, memory: GlobalDocumentMemory, field: FieldDefinition, limit: int = 8):
        keywords = field.strategy.get("keywords") or field.label.lower().split()
        scored = []
        for page in memory.pages:
            lower = page.text.lower()
            score = sum(lower.count(keyword.lower()) for keyword in keywords)
            if score:
                scored.append((score, page))
        return [
            page for _, page in sorted(scored, key=lambda item: (-item[0], item[1].number))[:limit]
        ] or memory.pages[:limit]


class LocalizationEngine:
    def locate(
        self,
        value: str,
        blocks: list[OCRBlock],
        hint: tuple[float, float] | None = None,
    ) -> list[float] | None:
        wanted = re.sub(r"\W", "", value).casefold()
        if not wanted:
            return None
        matches: list[list[float]] = []
        for start in range(len(blocks)):
            combined, selected = "", []
            for block in blocks[start : start + 12]:
                combined += re.sub(r"\W", "", block.text).casefold()
                selected.append(block)
                if wanted in combined or combined in wanted:
                    if wanted in combined:
                        matches.append(
                            [
                                min(b.bbox[0] for b in selected),
                                min(b.bbox[1] for b in selected),
                                max(b.bbox[2] for b in selected),
                                max(b.bbox[3] for b in selected),
                            ]
                        )
                        break
                elif len(combined) > len(wanted) * 2:
                    break
        if not matches:
            return None
        if not hint:
            return matches[0]
        return min(
            matches,
            key=lambda bbox: (bbox[0] - hint[0]) ** 2 + (bbox[1] - hint[1]) ** 2,
        )


class ExtractionEngine:
    def __init__(self):
        self.retrieval = RetrievalEngine()
        self.localization = LocalizationEngine()

    def extract(self, memory: GlobalDocumentMemory, field: FieldDefinition) -> list[Candidate]:
        pattern_text = field.strategy.get("pattern") or field.validator.get("pattern")
        keywords = [keyword.casefold() for keyword in field.strategy.get("keywords", [])]
        if not pattern_text:
            return []
        pattern = re.compile(pattern_text, re.IGNORECASE)
        candidates: list[Candidate] = []
        for page in self.retrieval.retrieve(memory, field):
            for match in pattern.finditer(page.text):
                value = (match.groupdict().get("value") if match.groupdict() else None) or (
                    match.group(1) if match.groups() else match.group(0)
                )
                value = " ".join(value.strip().split())
                context = page.text[
                    max(0, match.start() - 80) : min(len(page.text), match.end() + 80)
                ]
                keyword_hit = (
                    any(keyword in context.casefold() for keyword in keywords) if keywords else True
                )
                score = (
                    0.58
                    + (0.2 if keyword_hit else 0)
                    + (0.08 if page.cluster == "Documento principale" else 0)
                )
                candidates.append(
                    Candidate(
                        value=value,
                        page_number=page.number,
                        bbox=self.localization.locate(value, page.blocks),
                        evidence=context,
                        score=min(score, 0.98),
                        reasons=[
                            "validator regex matched",
                            "field keyword in evidence" if keyword_hit else "weak keyword context",
                            f"source: {page.cluster}",
                        ],
                    )
                )
        unique: dict[tuple[str, int], Candidate] = {}
        for candidate in candidates:
            unique.setdefault((candidate.value.casefold(), candidate.page_number), candidate)
        return list(unique.values())


class VerificationAgent:
    def verify(self, candidate: Candidate, field: FieldDefinition) -> Candidate:
        minimum = field.validator.get("min_length", 1)
        maximum = field.validator.get("max_length", 500)
        if not minimum <= len(candidate.value) <= maximum:
            candidate.score *= 0.3
            candidate.reasons.append("validator length failed")
        negative = [str(value).casefold() for value in field.negative_examples]
        if candidate.value.casefold() in negative:
            candidate.score *= 0.2
            candidate.reasons.append("negative example penalty")
        candidate.agent = "VerificationAgent"
        return candidate


class EvidenceConsensusEngine:
    """Clusters competing readings and scores the best-supported interpretation."""

    frontispiece_fields: ClassVar[set[str]] = {
        "protocollo",
        "data_protocollo",
        "richiedente",
    }

    @staticmethod
    def normalize(value: str) -> str:
        return re.sub(r"[^a-z0-9]", "", value.casefold())

    def similarity(self, left: str, right: str) -> float:
        a, b = self.normalize(left), self.normalize(right)
        if not a or not b:
            return 0
        return SequenceMatcher(None, a, b).ratio()

    def consolidate(self, candidates: list[Candidate], field: FieldDefinition) -> list[Candidate]:
        if not candidates:
            return []
        clusters: list[list[Candidate]] = []
        threshold = 0.9 if field.key in {"protocollo", "data_protocollo"} else 0.6
        for candidate in candidates:
            matching = next(
                (
                    cluster
                    for cluster in clusters
                    if max(self.similarity(candidate.value, item.value) for item in cluster)
                    >= threshold
                ),
                None,
            )
            if matching is not None:
                matching.append(candidate)
            else:
                clusters.append([candidate])

        for cluster in clusters:
            distinct_pages = {candidate.page_number for candidate in cluster}
            representative = max(
                cluster,
                key=lambda candidate: (
                    candidate.score,
                    len(self.normalize(candidate.value)),
                    -candidate.page_number,
                ),
            )
            corroboration = sum(
                self.similarity(representative.value, candidate.value) * candidate.score
                for candidate in cluster
                if candidate is not representative
            )
            if corroboration:
                representative.score += min(0.2, corroboration * 0.08)
                readings = sorted({candidate.value for candidate in cluster})
                representative.reasons.append(f"corroborated readings: {', '.join(readings)}")
            if len(distinct_pages) > 1:
                representative.score += min(0.15, 0.05 * (len(distinct_pages) - 1))
                representative.reasons.append(f"confirmed across {len(distinct_pages)} pages")
            if field.key in self.frontispiece_fields and representative.page_number == 1:
                representative.score += 0.15
                representative.reasons.append("frontispiece source priority")
            representative.score = min(representative.score, 1)

        representatives = [
            max(cluster, key=lambda candidate: candidate.score) for cluster in clusters
        ]
        representatives.sort(key=lambda candidate: (-candidate.score, candidate.page_number))
        if len(representatives) > 1:
            margin = representatives[0].score - representatives[1].score
            if margin < 0.08:
                representatives[0].score = min(representatives[0].score, 0.5)
                representatives[0].reasons.append(
                    "low confidence: competing interpretation with similar evidence"
                )
            else:
                representatives[0].reasons.append(f"won evidence comparison by {margin:.2f}")
        return representatives


class RankingEngine:
    def rank(self, candidates: list[Candidate], field: FieldDefinition) -> list[Candidate]:
        for candidate in candidates:
            for rule in field.ranking_rules:
                if (
                    rule.get("condition") == "main_document"
                    and "Documento principale" in candidate.reasons[-1]
                ):
                    candidate.score += float(rule.get("weight", 0))
                    candidate.reasons.append("ranking rule: main_document")
            candidate.score = min(max(candidate.score, 0), 1)
        return sorted(
            candidates, key=lambda item: (-item.score, item.page_number, item.value.casefold())
        )


def serialize_candidate(candidate: Candidate) -> dict[str, Any]:
    data = asdict(candidate)
    data["score"] = round(data["score"], 4)
    return data
