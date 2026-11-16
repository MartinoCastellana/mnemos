import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any


def _rule_candidates() -> list[Path]:
    return [
        Path("docs/instructions/pipeline_rules.json"),
        Path("/app/docs/instructions/pipeline_rules.json"),
        Path(__file__).parents[3] / "docs" / "instructions" / "pipeline_rules.json",
    ]


@lru_cache
def load_pipeline_rules(path: str | None = None) -> dict[str, Any]:
    candidates = [Path(path)] if path else _rule_candidates()
    for candidate in candidates:
        if candidate.is_file():
            return json.loads(candidate.read_text(encoding="utf-8"))
    raise FileNotFoundError("pipeline_rules.json non trovato")


class InstructionProfileCompiler:
    """Compile phase-specific views from one structured canonical rule set."""

    def __init__(self, rules: dict[str, Any] | None = None):
        self.rules = rules or load_pipeline_rules()

    @property
    def version(self) -> str:
        return str(self.rules.get("version", "unknown"))

    def field_config(self, field_key: str) -> dict[str, Any]:
        return dict(self.rules.get("fields", {}).get(field_key, {}))

    def focus_fields(self, reasons: list[str], available_candidates: list[dict]) -> list[str]:
        known = list(self.rules.get("fields", {}))
        detected = {
            key
            for key in known
            if any(re.search(rf"\b{re.escape(key)}\b", reason) for reason in reasons)
        }
        detected.update(
            str(candidate.get("field_key"))
            for candidate in available_candidates
            if candidate.get("field_key") in known
        )
        if not detected:
            return known
        profiles = self.rules.get("profiles", {})
        expanded = set(detected)
        for profile in profiles.values():
            if expanded & set(profile.get("fields", [])):
                expanded.update(profile.get("fields", []))
        return [key for key in known if key in expanded]

    def profiles_for_fields(self, field_keys: list[str]) -> list[str]:
        profiles = self.rules.get("profiles", {})
        return [
            name
            for name, profile in profiles.items()
            if set(field_keys) & set(profile.get("fields", []))
        ]

    def agent_definition(self, profile_name: str, phase: str) -> str:
        profile = self.rules.get("profiles", {}).get(profile_name, {})
        fields = {
            key: self.field_config(key)
            for key in profile.get("fields", [])
        }
        return json.dumps(
            {
                "agent": profile_name.upper(),
                "phase": phase,
                "fields": fields,
                "allowed_roles": profile.get("allowed_roles", ["SCONOSCIUTO"]),
                "selection_instruction": profile.get("selection_instruction", ""),
                "contract": {
                    "python_only_writer": True,
                    "selection_must_reference_candidate_id": phase == "global_selection",
                    "never_rewrite_existing_candidates": True,
                },
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )

    def compile_global(self, instructions: str) -> str:
        del instructions
        return "\n".join(
            self.agent_definition(profile, "global_selection")
            for profile in self.rules.get("profiles", {})
        )
