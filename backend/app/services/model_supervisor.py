from __future__ import annotations

import httpx

from app.core.config import Settings


class ModelSupervisor:
    """Ask the macOS host to keep exactly one local model service loaded."""

    def __init__(self, settings: Settings):
        self.endpoint = settings.model_supervisor_endpoint.rstrip("/")
        self.token = settings.model_supervisor_token

    def _post(self, action: str, model: str | None = None) -> dict:
        if not self.token:
            raise RuntimeError(
                "Model supervisor non configurato. Avvia Mnemos con "
                "AVVIA_FASCICOLO_AI.command per gestire i modelli in esclusiva."
            )
        try:
            response = httpx.post(
                f"{self.endpoint}/{action}",
                headers={"X-Mnemos-Token": self.token},
                json={"model": model} if model else {},
                timeout=900,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            detail = ""
            if isinstance(exc, httpx.HTTPStatusError):
                detail = f": {exc.response.text[:1000]}"
            raise RuntimeError(f"Model supervisor {action} non riuscito{detail}") from exc
        payload = response.json()
        if not payload.get("ok", False):
            raise RuntimeError(str(payload.get("error", "Operazione supervisor fallita")))
        return payload

    def acquire(self, model: str) -> dict:
        return self._post("acquire", model)

    def release(self, model: str) -> dict:
        return self._post("release", model)
