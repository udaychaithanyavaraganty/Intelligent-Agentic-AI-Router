"""Closed-set request classification with a deterministic local demo provider."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


CATEGORY_FILE = Path(__file__).resolve().parents[2] / "config" / "categories.json"
ROUTING_OVERRIDE_PATTERNS = (
    r"\b(ignore|disregard|override|rewrite|replace)\b.{0,80}\b(category|categories|routing|route|workflow|instructions)\b",
    r"\b(create|invent|add)\b.{0,40}\b(new\s+)?(category|workflow|route)\b",
    r"\b(bypass|skip)\b.{0,40}\b(validation|review|routing|approval)\b",
)


def contains_routing_override(request_text: str) -> bool:
    return any(re.search(pattern, request_text, re.IGNORECASE) for pattern in ROUTING_OVERRIDE_PATTERNS)


class ClassificationError(Exception):
    """Raised when a provider response cannot be parsed or validated structurally."""


class Classifier(Protocol):
    def classify(self, request_text: str) -> dict[str, Any]: ...


def load_categories() -> dict[str, dict[str, str]]:
    with CATEGORY_FILE.open(encoding="utf-8") as file:
        records = json.load(file)
    return {record["id"]: record for record in records}


@dataclass
class DemoClassifier:
    """Transparent, key-free local classifier for demonstrations and testing."""

    categories: dict[str, dict[str, str]]

    _patterns = {
        "TECHNICAL_SUPPORT": r"\b(error|issue|broken|not working|crash|problem|troubleshoot|wifi|printer)\b",
        "GENERAL_INFORMATION": r"\b(what is|who is|when did|where is|explain|define|how does)\b",
        "DATA_ANALYSIS": r"\b(analy[sz]e|analysis|dataset|spreadsheet|trend|statistics|average|chart)\b",
        "SOFTWARE_DEVELOPMENT": r"\b(code|program|function|debug|python|javascript|software|compile|bug)\b",
        "ACCOUNT_MANAGEMENT": r"\b(account|password|login|sign in|profile|subscription|billing|username)\b",
        "TASK_AUTOMATION": r"\b(automate|automation|schedule|repetitive|batch|workflow)\b",
    }

    def classify(self, request_text: str) -> dict[str, Any]:
        if contains_routing_override(request_text):
            return {
                "category": "UNKNOWN",
                "confidence": 0.0,
                "explanation": "The request attempts to alter routing policy and was sent for human review.",
                "requires_review": True,
                "metadata": {"provider": "demo", "guard": "routing_override"},
            }
        text = request_text.lower()
        matches = [category for category, pattern in self._patterns.items() if re.search(pattern, text)]
        if len(matches) != 1:
            return {
                "category": "UNKNOWN",
                "confidence": 0.35 if matches else 0.1,
                "explanation": "The request is ambiguous or outside the local demo classifier's clear intent patterns.",
                "requires_review": True,
                "metadata": {"provider": "demo", "matched_categories": matches},
            }
        category = matches[0]
        return {
            "category": category,
            "confidence": 0.82,
            "explanation": f"Matched the local demo intent pattern for {category.replace('_', ' ').lower()}.",
            "requires_review": False,
            "metadata": {"provider": "demo", "matched_categories": matches},
        }


def parse_classification(raw: str, categories: dict[str, dict[str, str]]) -> dict[str, Any]:
    """Parse strict JSON; category allow-list checks are performed by the validator."""
    try:
        result = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as error:
        raise ClassificationError("Classifier returned malformed JSON.") from error
    required = {"category", "confidence", "explanation", "requires_review"}
    if not isinstance(result, dict) or not required.issubset(result):
        raise ClassificationError("Classifier response is missing required fields.")
    confidence = result["confidence"]
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not 0 <= confidence <= 1:
        raise ClassificationError("Classifier confidence must be a number from 0 to 1.")
    if not isinstance(result["requires_review"], bool):
        raise ClassificationError("Classifier requires_review must be a boolean.")
    result["category"] = str(result["category"]).upper()
    if not isinstance(result.get("metadata", {}), dict):
        raise ClassificationError("Classifier metadata must be a JSON object.")
    result["metadata"] = result.get("metadata", {})
    return result