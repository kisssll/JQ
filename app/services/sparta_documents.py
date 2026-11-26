"""Canonical, versioned training agreements for Sparta."""

import hashlib
import json
from pathlib import Path


DEFAULT_AGREEMENTS = json.loads(Path(__file__).with_name("sparta_agreements.json").read_text(encoding="utf-8"))


def training_agreements(saved: dict | None) -> dict:
    agreements = {}
    for audience, default in DEFAULT_AGREEMENTS.items():
        content = (saved or {}).get(audience, default)
        version = hashlib.sha256(json.dumps(content, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        agreements[audience] = {**content, "version": version}
    return agreements
