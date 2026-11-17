from functools import lru_cache
from io import BytesIO
from pathlib import Path
from threading import Lock
import time

import httpx

import fitz
import pytesseract
from PIL import Image
import numpy as np
from minicpmvocr import DEFAULT_PROMPT_MAP, create_backend, create_layout_detector

from app.core.config import Settings, get_settings
from app.services.memory import OCRBlock, PageMemory


class RenderingService:
    def render(self, page: fitz.Page, output: Path, dpi: int = 120) -> str:
        output.parent.mkdir(parents=True, exist_ok=True)
        page.get_pixmap(dpi=dpi, alpha=False).save(output)
        return str(output)


def optimize_pdf(pdf_path: str) -> tuple[str, int, dict]:
    """Normalize page orientation and rasterize in color at 120 DPI."""
    source = Path(pdf_path)
    optimized = source.with_name("optimized.pdf")
    dpi = 120
    orientation_dpi = 240
    orientation_confidence_threshold = 12.0
    page_rotations: list[dict] = []
    metadata_rotated_pages = 0
    orientation_rotated_pages = 0
    uncertain_orientation_pages = 0
    with fitz.open(source) as pdf:
        result = fitz.open()
        page_count = len(pdf)
        for page_number, page in enumerate(pdf, start=1):
            metadata_rotation = int(page.rotation or 0)
            if metadata_rotation:
                page.remove_rotation()
                metadata_rotated_pages += 1

            orientation_pixmap = page.get_pixmap(
                dpi=orientation_dpi, colorspace=fitz.csGRAY, alpha=False
            )
            orientation_image = Image.frombytes(
                "L", (orientation_pixmap.width, orientation_pixmap.height), orientation_pixmap.samples
            )
            pixmap = page.get_pixmap(dpi=dpi, colorspace=fitz.csRGB, alpha=False)
            image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
            detected_rotation = 0
            orientation_confidence = 0.0
            orientation_status = "uncertain"
            try:
                orientation = pytesseract.image_to_osd(
                    orientation_image,
                    output_type=pytesseract.Output.DICT,
                    config="--psm 0",
                )
                orientation_confidence = float(orientation.get("orientation_conf", 0) or 0)
                proposed_rotation = int(orientation.get("rotate", 0) or 0) % 360
                if orientation_confidence >= orientation_confidence_threshold:
                    detected_rotation = proposed_rotation
                    orientation_status = "rotated" if detected_rotation else "upright"
                else:
                    uncertain_orientation_pages += 1
            except (pytesseract.TesseractError, pytesseract.TesseractNotFoundError):
                uncertain_orientation_pages += 1
                orientation_status = "unavailable"

            if detected_rotation:
                image = image.rotate(-detected_rotation, expand=True)
                orientation_rotated_pages += 1

            buffer = BytesIO()
            image.save(buffer, format="PNG", optimize=True, compress_level=9)
            output_page = result.new_page(
                width=image.width * 72 / dpi,
                height=image.height * 72 / dpi,
            )
            output_page.insert_image(output_page.rect, stream=buffer.getvalue())
            page_rotations.append(
                {
                    "page": page_number,
                    "pdf_rotation": metadata_rotation,
                    "detected_rotation": detected_rotation,
                    "orientation_confidence": round(orientation_confidence, 2),
                    "orientation_status": orientation_status,
                }
            )
        result.save(optimized, garbage=4, deflate=True, clean=True)
        result.close()
    rotated_pages = sum(
        item["pdf_rotation"] != 0 or item["detected_rotation"] != 0
        for item in page_rotations
    )
    return str(optimized), page_count, {
        "source_bytes": source.stat().st_size,
        "optimized_bytes": optimized.stat().st_size,
        "dpi": dpi,
        "orientation_detection_dpi": orientation_dpi,
        "color_mode": "rgb",
        "rotated_pages": rotated_pages,
        "metadata_rotated_pages": metadata_rotated_pages,
        "orientation_rotated_pages": orientation_rotated_pages,
        "uncertain_orientation_pages": uncertain_orientation_pages,
        "orientation_confidence_threshold": orientation_confidence_threshold,
        "page_rotations": page_rotations,
    }


@lru_cache(maxsize=4)
def _minicpm_client(endpoint: str, model_name: str, timeout: int):
    return create_backend(
        {
            "engine": {
                "type": "llamacpp",
                "model_name": model_name,
                "server_url": endpoint,
                "request_timeout_sec": timeout,
                "request_ready_timeout_sec": timeout,
            },
            "mm": {"downsample_mode": "4x", "max_slice_nums": 9},
            "decode": {
                "temperature": 0.01,
                "top_p": 0.001,
                "top_k": 1,
                "repetition_penalty": 1.0,
                "no_repeat_ngram_size": 100,
            },
        }
    )


def _ensure_torch_layout_model(model_dir: str) -> str:
    path = Path(model_dir).expanduser()
    if not (path / "config.json").is_file() or not (path / "model.safetensors").is_file():
        from huggingface_hub import snapshot_download

        snapshot_download(
            repo_id="PaddlePaddle/PP-DocLayoutV3_safetensors",
            local_dir=str(path),
            allow_patterns=["*.json", "*.safetensors"],
        )
    return str(path)


_layout_detectors: dict[tuple[str, str, float], object] = {}
_layout_detector_lock = Lock()


def _minicpm_layout_detector(provider: str, model_dir: str, threshold: float):
    key = (provider, model_dir, threshold)
    with _layout_detector_lock:
        if key in _layout_detectors:
            return _layout_detectors[key]
        if provider == "ppdoclayout3_paddlex":
            from minicpmvocr.layouts.download import ensure_layout_model

            model_dir = str(ensure_layout_model(Path(model_dir)))
        elif provider == "ppdoclayout3_torch":
            model_dir = _ensure_torch_layout_model(model_dir)
        detector = create_layout_detector(
            {
                "provider": provider,
                "model_dir": model_dir,
                "device": "cpu",
                "threshold": threshold,
                "nms": True,
            }
        )
        detector.start()
        _layout_detectors[key] = detector
        return detector


class MiniCPMOCRService:
    """Run MiniCPM-OCR through the Python SDK's local llama.cpp backend."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.client = _minicpm_client(
            self.settings.minicpm_endpoint,
            self.settings.minicpm_model_name,
            self.settings.minicpm_timeout_sec,
        )
        default_layout_model = (
            "PP-DocLayoutV3_infer"
            if self.settings.minicpm_layout_provider == "ppdoclayout3_paddlex"
            else "PP-DocLayoutV3_safetensors"
        )
        self.layout = _minicpm_layout_detector(
            self.settings.minicpm_layout_provider,
            str(
                self.settings.minicpm_layout_model_dir
                or self.settings.storage_dir / "models" / default_layout_model
            ),
            self.settings.minicpm_layout_threshold,
        )
        self.last_metrics: dict = {}

    def wait_until_standby(self, timeout_sec: int) -> dict:
        """Wait until llama.cpp confirms its model and inference memory are asleep."""
        started = time.perf_counter()
        deadline = time.monotonic() + timeout_sec
        last_error = None
        while time.monotonic() < deadline:
            try:
                response = httpx.get(f"{self.client.server_url.rstrip('/')}/props", timeout=5)
                response.raise_for_status()
                payload = response.json()
                sleeping = (
                    payload.get("is_sleeping", payload.get("sleeping"))
                    if isinstance(payload, dict)
                    else None
                )
                if sleeping is True:
                    return {
                        "standby": True,
                        "wait_ms": round((time.perf_counter() - started) * 1000),
                        "endpoint": f"{self.client.server_url.rstrip('/')}/props",
                    }
                last_error = "llama-server does not report sleeping=true in /props"
            except (httpx.HTTPError, ValueError) as exc:
                last_error = str(exc)
            time.sleep(1)
        raise RuntimeError(
            "MiniCPM did not enter standby before the Qwen phase. "
            "Restart llama-server with --sleep-idle-seconds enabled; "
            f"last status: {last_error or 'timeout'}"
        )

    def extract(self, page: fitz.Page) -> tuple[str, list[OCRBlock]]:
        started = time.perf_counter()
        pixmap = page.get_pixmap(dpi=self.settings.minicpm_render_dpi, alpha=False)
        image = Image.open(BytesIO(pixmap.tobytes("png"))).convert("RGB")
        try:
            self.client.check_ready(self.client.server_url)
            detections = self.layout.detect([image])[0]
            crops = self.layout.crop(image, detections)
            page_width, page_height = image.size
            blocks = []
            output_tokens = 0
            for block in crops:
                crop = block.get("image")
                if crop is None:
                    continue
                crop_image = Image.fromarray(np.asarray(crop)).convert("RGB")
                try:
                    prompt = (
                        "Table Recognition:"
                        if block.get("label") == "table"
                        else DEFAULT_PROMPT_MAP["default"]["prompt"]
                    )
                    result = self.client.recognize(
                        crop_image,
                        prompt=prompt,
                        max_new_tokens=self.settings.minicpm_max_tokens,
                        slice_nums=9,
                    )
                finally:
                    crop_image.close()
                text = str(result.get("text", "")).strip()
                output_tokens += int(result.get("output_token_count", 0) or 0)
                if not text:
                    continue
                x1, y1, x2, y2 = (float(value) for value in block["bbox"])
                blocks.append(
                    OCRBlock(
                        text=text,
                        bbox=[
                            max(0.0, x1 / page_width),
                            max(0.0, y1 / page_height),
                            min(1.0, x2 / page_width),
                            min(1.0, y2 / page_height),
                        ],
                        confidence=0.9,
                    )
                )
            if not blocks:
                result = self.client.recognize(
                    image,
                    prompt=DEFAULT_PROMPT_MAP["default"]["prompt"],
                    max_new_tokens=self.settings.minicpm_max_tokens,
                    slice_nums=9,
                )
                text = str(result.get("text", "")).strip()
                output_tokens += int(result.get("output_token_count", 0) or 0)
                if text:
                    blocks.append(OCRBlock(text=text, bbox=[0.0, 0.0, 1.0, 1.0], confidence=0.0))
        finally:
            image.close()
        text = "\n".join(block.text for block in blocks)
        printable = sum(character.isprintable() and character != "\ufffd" for character in text)
        character_quality = printable / max(len(text), 1)
        density = min(1.0, len(blocks) / 10)
        self.text_quality = round(character_quality * 0.9 + density * 0.1, 3)
        self.last_metrics = {
            "engine": "minicpm_ocr",
            "model": self.settings.minicpm_model_name,
            "duration_ms": round((time.perf_counter() - started) * 1000),
            "output_tokens": output_tokens,
            "line_count": len(blocks),
            "layout_regions": len(detections),
            "text_quality": self.text_quality,
        }
        return text, blocks


class VisionService:
    def analyze(self, page: fitz.Page, blocks: list[OCRBlock]) -> dict:
        text = " ".join(block.text.lower() for block in blocks)
        return {
            "width": round(page.rect.width, 2),
            "height": round(page.rect.height, 2),
            "orientation": "landscape" if page.rect.width > page.rect.height else "portrait",
            "image_count": len(page.get_images(full=True)),
            "drawing_count": len(page.get_drawings()),
            "has_table": any("|" in block.text for block in blocks),
            "has_signature": any(token in text for token in ("firma", "sottoscritto", "firmato")),
        }


def load_pdf_once(pdf_path: str, render_dir: Path) -> list[PageMemory]:
    renderer, ocr, vision = RenderingService(), MiniCPMOCRService(), VisionService()
    memories: list[PageMemory] = []
    with fitz.open(pdf_path) as pdf:
        for index, page in enumerate(pdf, start=1):
            text, blocks = ocr.extract(page)
            render_path = renderer.render(page, render_dir / f"page-{index}.png")
            memories.append(
                PageMemory(
                    number=index,
                    text=text,
                    blocks=blocks,
                    vision_features={
                        **vision.analyze(page, blocks),
                        "text_source": "minicpm_ocr",
                        "text_quality": ocr.text_quality,
                        "ocr_metrics": ocr.last_metrics,
                    },
                    render_path=render_path,
                )
            )
    return memories


def pdf_page_count(pdf_path: str) -> int:
    with fitz.open(pdf_path) as pdf:
        return len(pdf)


def load_pdf_page(pdf_path: str, render_dir: Path, page_number: int) -> PageMemory:
    renderer, ocr, vision = RenderingService(), MiniCPMOCRService(), VisionService()
    with fitz.open(pdf_path) as pdf:
        page = pdf[page_number - 1]
        text, blocks = ocr.extract(page)
        render_path = renderer.render(page, render_dir / f"page-{page_number}.png")
        return PageMemory(
            number=page_number,
            text=text,
            blocks=blocks,
            vision_features={
                **vision.analyze(page, blocks),
                "text_source": "minicpm_ocr",
                "text_quality": ocr.text_quality,
                "ocr_metrics": ocr.last_metrics,
            },
            render_path=render_path,
        )
