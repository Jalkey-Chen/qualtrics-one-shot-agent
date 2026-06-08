from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml


LEDGER_KEYS = [
    "demographics",
    "preferences",
    "attitudes",
    "examples_given",
    "numeric_answers",
    "open_ended_summaries",
    "uncertainties",
]


def load_respondent_card(path: str | Path) -> dict[str, Any]:
    card_path = Path(path)
    if not card_path.exists():
        raise FileNotFoundError(f"Respondent card not found: {card_path}")
    data = yaml.safe_load(card_path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError("respondent_card.yaml must contain a YAML object")
    return data


def create_initial_ledger(respondent_card: dict[str, Any]) -> dict[str, Any]:
    ledger = {key: {} for key in LEDGER_KEYS}
    ledger["demographics"] = deepcopy(respondent_card.get("demographic_traits", {}))
    ledger["preferences"] = deepcopy(respondent_card.get("stable_preferences", {}))
    ledger["attitudes"] = deepcopy(respondent_card.get("value_tendencies", {}))
    ledger["examples_given"] = {}
    ledger["numeric_answers"] = {}
    ledger["open_ended_summaries"] = {}
    ledger["uncertainties"] = {}
    return ledger


def merge_memory_patch(ledger: dict[str, Any], patch: dict[str, Any] | None, legacy_updates: list[str] | None = None) -> dict[str, Any]:
    if patch:
        for key, value in patch.items():
            if key not in LEDGER_KEYS:
                ledger.setdefault("uncertainties", {})[f"unclassified_{key}"] = value
                continue
            if isinstance(value, dict):
                ledger.setdefault(key, {}).update(value)
            elif isinstance(value, list):
                current = ledger.setdefault(key, [])
                if isinstance(current, list):
                    current.extend(value)
                else:
                    ledger[key] = value
            else:
                ledger[key] = value
    if legacy_updates:
        summaries = ledger.setdefault("open_ended_summaries", {})
        existing = summaries.setdefault("legacy_memory_update", [])
        if isinstance(existing, list):
            existing.extend(legacy_updates)
        else:
            summaries["legacy_memory_update"] = legacy_updates
    return ledger

