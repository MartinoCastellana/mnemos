import re
from functools import lru_cache
from html import unescape
from pathlib import Path
from typing import Literal
from zipfile import ZipFile

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Mnemos"
    database_url: str = "sqlite:///./document_ai.db"
    storage_dir: Path = Path("./storage")
    cors_origins: str = "http://localhost:5173"
    model_backend: Literal["mlx"] = "mlx"
    model_endpoint: str = "http://localhost:8081"
    model_name: str = "mlx-community/Qwen3-4B-Instruct-2507-4bit"
    model_supervisor_endpoint: str = "http://host.docker.internal:18500"
    model_supervisor_token: str = ""
    minicpm_endpoint: str = "http://localhost:18499"
    minicpm_model_name: str = "minicpm-ocr"
    minicpm_layout_provider: str = "ppdoclayout3_torch"
    minicpm_layout_model_dir: str = ""
    minicpm_layout_threshold: float = 0.3
    minicpm_timeout_sec: int = 300
    minicpm_sleep_idle_seconds: int = 30
    minicpm_standby_timeout_sec: int = 90
    minicpm_render_dpi: int = 120
    minicpm_max_tokens: int = 4096
    instructions_path: Path = Path("../docs/ISTRUZIONI GLOBALI.md")
    pipeline_rules_path: Path = Path("../docs/instructions/pipeline_rules.json")
    max_upload_mb: int = 150

    model_config = SettingsConfigDict(env_file=".env", env_prefix="DOC_AI_", extra="ignore")

    @property
    def origins(self) -> list[str]:
        return [value.strip() for value in self.cors_origins.split(",") if value.strip()]

    def load_instructions(self) -> str:
        candidates = [
            self.instructions_path,
            Path("docs/ISTRUZIONI GLOBALI.md"),
            Path("/app/docs/ISTRUZIONI GLOBALI.md"),
            Path(__file__).parents[3] / "docs" / "ISTRUZIONI GLOBALI.md",
            Path("docs/ISTRUZIONI GLOBALI def.docx"),
            Path("/app/docs/ISTRUZIONI GLOBALI def.docx"),
            Path(__file__).parents[3] / "docs" / "ISTRUZIONI GLOBALI def.docx",
        ]
        for candidate in candidates:
            if candidate.is_file():
                if candidate.suffix.casefold() == ".docx":
                    with ZipFile(candidate) as archive:
                        xml = archive.read("word/document.xml").decode("utf-8")
                    xml = re.sub(r"</w:p>", "\n", xml)
                    xml = re.sub(r"<w:tab[^>]*/>", "\t", xml)
                    return unescape(re.sub(r"<[^>]+>", "", xml)).strip()
                return candidate.read_text(encoding="utf-8")
        raise FileNotFoundError("ISTRUZIONI GLOBALI def.docx non trovato")


@lru_cache
def get_settings() -> Settings:
    return Settings()
