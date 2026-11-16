from app.db.models import FieldDefinition
from app.services.instruction_profiles import load_pipeline_rules

RULES = load_pipeline_rules()
DEFAULT_FIELDS = [
    (key, config["label"], config.get("keywords", []), config.get("pattern"))
    for key, config in RULES["fields"].items()
]


def seed_default_fields(db) -> None:
    existing = {field.key: field for field in db.query(FieldDefinition).all()}
    expected = {item[0] for item in DEFAULT_FIELDS}
    for key, field in existing.items():
        if key not in expected:
            db.delete(field)
    for key, label, keywords, pattern in DEFAULT_FIELDS:
        canonical = RULES["fields"][key]
        profile = RULES.get("profiles", {}).get(canonical.get("profile"), {})
        allowed_roles = profile.get("allowed_roles", [])
        candidate_role = canonical.get("candidate_role")
        if not candidate_role and len(allowed_roles) == 1:
            candidate_role = allowed_roles[0]
        values = {
            "label": label,
            "instructions": f"Applicare esclusivamente INSTRUCTIONS.md per {label}.",
            "positive_examples": [],
            "negative_examples": [],
            "validator": {"pattern": pattern, "min_length": 1, "max_length": 500}
            if pattern
            else {},
            "ranking_rules": [],
            "strategy": {
                "type": "text",
                "keywords": keywords,
                "pattern": pattern,
                "profile": canonical.get("profile"),
                "candidate_role": candidate_role,
                "allowed_roles": allowed_roles,
            }
            if pattern
            else {"type": "summary", "keywords": []},
            "enabled": True,
        }
        if key in existing:
            for attribute, value in values.items():
                setattr(existing[key], attribute, value)
        else:
            db.add(FieldDefinition(key=key, **values))
    db.commit()
