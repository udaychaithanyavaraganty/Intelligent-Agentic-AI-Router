"""Validates classifier output before any route can be selected."""

from dataclasses import dataclass
import math
from typing import Any


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    needs_review: bool
    reason: str


def validate_classification(
    result: dict[str, Any], categories: dict[str, dict[str, str]], threshold: float
) -> ValidationResult:
    category = result.get("category")
    confidence = result.get("confidence")
    if not isinstance(category, str) or category not in categories:
        return ValidationResult(False, True, "Unsupported category returned by classifier.")
    try:
        finite_confidence = math.isfinite(confidence)
    except (TypeError, OverflowError):
        finite_confidence = False
    if (
        not isinstance(confidence, (int, float))
        or isinstance(confidence, bool)
        or not finite_confidence
        or not 0 <= confidence <= 1
    ):
        return ValidationResult(False, True, "Classifier confidence must be a finite number from 0 to 1.")
    explanation = result.get("explanation")
    if not isinstance(explanation, str) or not explanation.strip():
        return ValidationResult(False, True, "Classifier explanation must be a non-empty string.")
    if not isinstance(result.get("metadata", {}), dict):
        return ValidationResult(False, True, "Classifier metadata must be a JSON object.")
    if not isinstance(result.get("requires_review", False), bool):
        return ValidationResult(False, True, "Classifier requires_review must be a boolean.")
    if category == "UNKNOWN":
        return ValidationResult(True, True, "Classifier could not safely identify a supported intent.")
    if result.get("requires_review", False):
        return ValidationResult(True, True, "Classifier requested human review.")
    if confidence < threshold:
        return ValidationResult(True, True, f"Confidence {confidence:.2f} is below the {threshold:.2f} threshold.")
    return ValidationResult(True, False, "Classification passed closed-set and confidence validation.")