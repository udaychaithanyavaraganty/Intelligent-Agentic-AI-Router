"""Independent consistency checks for the agent orchestration pipeline."""

from dataclasses import dataclass
import math
from typing import Any


@dataclass(frozen=True)
class CheckResult:
    passed: bool
    feedback: str
    retryable: bool = False


class CheckerAgent:
    def check_classification(self, classification: Any) -> CheckResult:
        if not isinstance(classification, dict):
            return CheckResult(False, "Classifier output must be an object.", True)
        required = {"category", "confidence", "explanation", "requires_review"}
        if not required.issubset(classification):
            return CheckResult(False, "Classification is missing required fields.", True)
        return CheckResult(True, "Classification structure is complete.")

    def check_validation(
        self,
        classification: dict,
        validation,
        categories: dict[str, dict[str, str]],
        threshold: float,
    ) -> CheckResult:
        if not isinstance(validation.valid, bool) or not isinstance(validation.needs_review, bool):
            return CheckResult(False, "Validation agent returned invalid decision flags.", True)
        category = classification["category"]
        if not isinstance(category, str):
            return CheckResult(False, "Validation received a non-string category.", True)
        if category not in categories and validation.valid:
            return CheckResult(False, "Validation accepted a category outside the configured allowlist.", True)
        if not validation.valid and not validation.needs_review:
            return CheckResult(False, "Invalid classification was not escalated for review.", True)
        if not validation.valid:
            return CheckResult(False, validation.reason, True)
        if classification["category"] == "UNKNOWN" and not validation.needs_review:
            return CheckResult(False, "UNKNOWN classifications must require human review.")
        if classification.get("requires_review") and not validation.needs_review:
            return CheckResult(False, "Classifier-requested human review was not preserved.")
        confidence = classification["confidence"]
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
            return CheckResult(False, "Validation accepted an invalid confidence score.", True)
        if validation.valid and category != "UNKNOWN" and not validation.needs_review and confidence < threshold:
            return CheckResult(False, "Below-threshold classification was incorrectly approved.")
        return CheckResult(True, validation.reason)

    @staticmethod
    def check_route(category: str, workflow: str, expected_workflow: str) -> CheckResult:
        if workflow != expected_workflow:
            return CheckResult(False, "Selected workflow does not match the approved category route.")
        return CheckResult(True, f"{category} maps to the predefined {workflow} workflow.")

    @staticmethod
    def check_execution(workflow: str, result: Any) -> CheckResult:
        if not isinstance(result, dict) or not isinstance(result.get("message"), str) or not result["message"].strip():
            return CheckResult(False, f"{workflow} returned an invalid execution result.")
        return CheckResult(True, f"{workflow} returned a structured execution result.")

    @staticmethod
    def check_review(status: str, action: str) -> CheckResult:
        expected = {"approve": "completed", "reject": "rejected", "clarify": "awaiting_clarification"}
        if expected.get(action) != status:
            return CheckResult(False, "Review agent returned an inconsistent state transition.")
        return CheckResult(True, f"Human {action} action recorded as {status}.")
