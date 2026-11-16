import hashlib
import math
import re
from collections import defaultdict

from app.services.memory import GlobalDocumentMemory, PageMemory

ANCHOR_PATTERNS = {
    "protocol": re.compile(
        r"\b(?:prot(?:ocollo)?[.:\s-]*)?([A-Z0-9]{2,}(?:[/.-][A-Z0-9]{2,}){1,3})\b", re.IGNORECASE
    ),
    "vat": re.compile(r"\b(?:P\.?\s*IVA\s*)?(IT)?\s*(\d{11})\b", re.IGNORECASE),
    "fiscal_code": re.compile(r"\b[A-Z]{6}\d{2}[A-Z]\d{2}[A-Z]\d{3}[A-Z]\b", re.IGNORECASE),
    "email": re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Z]{2,}\b", re.IGNORECASE),
}


class AnchorExtractionEngine:
    def extract(self, page: PageMemory) -> dict[str, list[str]]:
        values: dict[str, list[str]] = {}
        for name, pattern in ANCHOR_PATTERNS.items():
            matches = []
            for match in pattern.finditer(page.text):
                value = match.group(0).strip()
                if value not in matches:
                    matches.append(value)
            if matches:
                values[name] = matches[:10]
        headings = re.findall(r"(?:^|[.!?]\s+)([A-ZÀ-Ü][A-ZÀ-Ü\s]{5,50})", page.text)
        if headings:
            values["headings"] = [heading.strip() for heading in headings[:5]]
        return values


class EmbeddingEngine:
    dimensions = 32

    def embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        tokens = re.findall(r"\w+", text.lower())
        for token in tokens:
            digest = hashlib.blake2b(token.encode(), digest_size=4).digest()
            value = int.from_bytes(digest, "big")
            vector[value % self.dimensions] += 1 if value & 1 else -1
        norm = math.sqrt(sum(item * item for item in vector)) or 1
        return [round(item / norm, 5) for item in vector]


class PageRelationshipEngine:
    def build(self, memory: GlobalDocumentMemory) -> list[dict]:
        edges = []
        for i, left in enumerate(memory.pages):
            for right in memory.pages[i + 1 :]:
                shared = sum(
                    bool(set(left.anchors.get(key, [])) & set(right.anchors.get(key, [])))
                    for key in ("protocol", "vat", "fiscal_code", "email")
                )
                semantic = sum(a * b for a, b in zip(left.embedding, right.embedding))
                layout = (
                    1.0
                    if left.vision_features.get("orientation")
                    == right.vision_features.get("orientation")
                    else 0.0
                )
                score = round(min(1.0, 0.5 * shared + 0.4 * max(semantic, 0) + 0.1 * layout), 4)
                if score >= 0.18:
                    edges.append(
                        {
                            "source": left.number,
                            "target": right.number,
                            "score": score,
                            "shared_anchors": shared,
                        }
                    )
        return edges


class DocumentClusterEngine:
    def cluster(
        self, memory: GlobalDocumentMemory, threshold: float = 0.42
    ) -> dict[str, list[int]]:
        parents = {page.number: page.number for page in memory.pages}

        def find(node: int) -> int:
            while parents[node] != node:
                parents[node] = parents[parents[node]]
                node = parents[node]
            return node

        for edge in sorted(memory.relationships, key=lambda item: item["score"], reverse=True):
            if edge["score"] >= threshold:
                parents[find(edge["target"])] = find(edge["source"])
        groups: dict[int, list[int]] = defaultdict(list)
        for page in memory.pages:
            groups[find(page.number)].append(page.number)
        ordered = sorted(groups.values(), key=lambda pages: (-len(pages), min(pages)))[:7]
        clusters = {
            ("Documento principale" if index == 0 else f"Allegato {index}"): pages
            for index, pages in enumerate(ordered)
        }
        assigned = {number for pages in ordered for number in pages}
        clusters.setdefault("Documento principale", []).extend(
            page.number for page in memory.pages if page.number not in assigned
        )
        return clusters


class DocumentStructureAgent:
    def run(self, memory: GlobalDocumentMemory) -> None:
        for label, page_numbers in memory.clusters.items():
            for number in page_numbers:
                memory.page(number).cluster = label


def enrich_memory(memory: GlobalDocumentMemory) -> None:
    anchor_engine, embedding_engine = AnchorExtractionEngine(), EmbeddingEngine()
    for page in memory.pages:
        page.anchors = anchor_engine.extract(page)
        page.embedding = embedding_engine.embed(page.text)
        page.summary = page.text[:240].strip() or "Pagina senza testo incorporato"
    memory.relationships = PageRelationshipEngine().build(memory)
    memory.clusters = DocumentClusterEngine().cluster(memory)
    DocumentStructureAgent().run(memory)
