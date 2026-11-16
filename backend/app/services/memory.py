from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class OCRBlock:
    text: str
    bbox: list[float]
    confidence: float = 1.0


@dataclass(slots=True)
class PageMemory:
    number: int
    text: str
    blocks: list[OCRBlock]
    summary: str = ""
    vision_features: dict[str, Any] = field(default_factory=dict)
    anchors: dict[str, Any] = field(default_factory=dict)
    embedding: list[float] = field(default_factory=list)
    cluster: str = "Documento principale"
    render_path: str | None = None


@dataclass(slots=True)
class GlobalDocumentMemory:
    document_id: str
    pages: list[PageMemory] = field(default_factory=list)
    relationships: list[dict[str, Any]] = field(default_factory=list)
    clusters: dict[str, list[int]] = field(default_factory=dict)
    state: dict[str, Any] = field(default_factory=dict)

    @property
    def full_text(self) -> str:
        return "\n\n".join(f"[PAGE {p.number}]\n{p.text}" for p in self.pages)

    def page(self, number: int) -> PageMemory:
        return next(page for page in self.pages if page.number == number)
