"""Deterministic category-to-workflow routing."""

import json
from pathlib import Path


ROUTING_FILE = Path(__file__).resolve().parents[2] / "config" / "routing_rules.json"


class RoutingError(ValueError):
    pass


def load_routing_rules() -> dict[str, str]:
    with ROUTING_FILE.open(encoding="utf-8") as file:
        return json.load(file)


def select_workflow(category: str, rules: dict[str, str], categories: dict[str, dict[str, str]]) -> str:
    if category not in categories:
        raise RoutingError("Refusing to route an unsupported category.")
    if category == "UNKNOWN":
        return "human_review"
    workflow = rules.get(category)
    if not workflow or workflow != categories[category]["workflow"]:
        raise RoutingError("No valid predefined workflow exists for this category.")
    return workflow