"""Coordinates existing agents and records their real execution trace."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from backend.agents.checker_agent import CheckerAgent, CheckResult
from backend.agents.classification_agent import ClassificationError, contains_routing_override
from backend.agents.routing_agent import select_workflow
from backend.agents.validation_agent import validate_classification


MAX_CLASSIFICATION_ATTEMPTS = 2


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class AgentOrchestrator:
    def __init__(
        self,
        history,
        classifier,
        categories,
        routing_rules,
        confidence_threshold: float,
        execute: Callable[[str, str], dict],
        checker: CheckerAgent | None = None,
    ):
        self.history = history
        self.classifier = classifier
        self.categories = categories
        self.routing_rules = routing_rules
        self.confidence_threshold = confidence_threshold
        self.execute = execute
        self.checker = checker or CheckerAgent()

    def _start(self, request_id: int, agent: str, inputs: Any, attempt: int = 1) -> int:
        return self.history.start_agent_execution(
            request_id=request_id,
            agent=agent,
            inputs=inputs,
            started_at=_now(),
            retry_attempt=attempt,
        )

    def _finish(
        self,
        execution_id: int,
        status: str,
        output: Any = None,
        error: str | None = None,
        feedback: str | None = None,
    ):
        self.history.finish_agent_execution(
            execution_id=execution_id,
            status=status,
            completed_at=_now(),
            output=output,
            error=error,
            checker_feedback=feedback,
        )

    def _run(self, request_id: int, agent: str, inputs: Any, operation, attempt: int = 1):
        execution_id = self._start(request_id, agent, inputs, attempt)
        try:
            output = operation()
        except Exception as error:
            self._finish(execution_id, "failed", error=str(error))
            raise
        self._finish(execution_id, "completed", output=output)
        return output

    def _check(self, request_id: int, check: Callable[[], CheckResult], inputs: Any, attempt: int = 1):
        execution_id = self._start(request_id, "checker_agent", inputs, attempt)
        result = check()
        self._finish(
            execution_id,
            "completed" if result.passed else "failed",
            output={"passed": result.passed, "retryable": result.retryable},
            feedback=result.feedback,
        )
        return result

    def process(self, request_id: int, request_text: str) -> dict[str, Any]:
        context: dict[str, Any] = {"request_id": request_id, "original_input": request_text}
        classification = None
        validation = None
        correction_feedback = None
        for attempt in range(1, MAX_CLASSIFICATION_ATTEMPTS + 1):
            try:
                classification_input = {"request_text": request_text}
                if correction_feedback:
                    classification_input["checker_feedback"] = correction_feedback
                if contains_routing_override(request_text):
                    classify = lambda: {
                        "category": "UNKNOWN",
                        "confidence": 0.0,
                        "explanation": "The request attempts to alter routing policy and was sent for human review.",
                        "requires_review": True,
                        "metadata": {"guard": "routing_override"},
                    }
                else:
                    classify_with_feedback = getattr(self.classifier, "classify_with_feedback", None)
                    if correction_feedback and callable(classify_with_feedback):
                        classify = lambda: classify_with_feedback(request_text, correction_feedback)
                    else:
                        classify = lambda: self.classifier.classify(request_text)
                classification = self._run(
                    request_id, "classification_agent", classification_input, classify, attempt,
                )
                check = self._check(
                    request_id,
                    lambda: self.checker.check_classification(classification),
                    {"classification": classification},
                    attempt,
                )
                if not check.passed:
                    correction_feedback = check.feedback
                    if attempt == MAX_CLASSIFICATION_ATTEMPTS:
                        classification = None
                        validation = None
                        break
                    continue
                validation = self._run(
                    request_id, "validation_agent",
                    {"classification": classification, "threshold": self.confidence_threshold},
                    lambda: validate_classification(classification, self.categories, self.confidence_threshold),
                    attempt,
                )
                context["classification"] = classification
                context["validation"] = {
                    "valid": validation.valid,
                    "needs_review": validation.needs_review,
                    "reason": validation.reason,
                }
                check = self._check(
                    request_id,
                    lambda: self.checker.check_validation(
                        classification, validation, self.categories, self.confidence_threshold
                    ),
                    context["validation"],
                    attempt,
                )
                if check.passed:
                    break
                correction_feedback = check.feedback
                if not check.retryable:
                    break
                if attempt == MAX_CLASSIFICATION_ATTEMPTS:
                    classification = None
                    validation = None
                    break
            except ClassificationError as error:
                feedback = str(error)
                correction_feedback = feedback
                check = self._check(
                    request_id,
                    lambda: CheckResult(False, feedback, True),
                    {"error": feedback},
                    attempt,
                )
                if attempt == MAX_CLASSIFICATION_ATTEMPTS:
                    classification = None
                    validation = None
                    break
        if classification is None or validation is None:
            return {
                **context,
                "classification": {
                    "category": "UNKNOWN",
                    "confidence": None,
                    "explanation": "Classifier output could not be parsed or validated.",
                    "metadata": {},
                },
                "validation": {
                    "valid": True,
                    "needs_review": True,
                    "reason": "Classification failed after the maximum retry attempts.",
                },
                "workflow": None,
                "result": None,
                "status": "pending_review",
                "validation_status": "review",
                "error": "Classification failed after the maximum retry attempts.",
            }

        classification.setdefault("metadata", {})
        context["classification"] = classification
        context["validation"] = {
            "valid": validation.valid,
            "needs_review": validation.needs_review,
            "reason": validation.reason,
        }
        workflow = None
        result = None
        if validation.valid and classification["category"] != "UNKNOWN":
            workflow = self._run(
                request_id,
                "routing_agent",
                {"category": classification["category"], "routing_rules": self.routing_rules},
                lambda: select_workflow(classification["category"], self.routing_rules, self.categories),
            )
            expected = self.categories[classification["category"]]["workflow"]
            route_check = self._check(
                request_id,
                lambda: self.checker.check_route(classification["category"], workflow, expected),
                {"category": classification["category"], "workflow": workflow, "expected": expected},
            )
            if not route_check.passed:
                raise RuntimeError(route_check.feedback)
        else:
            workflow = None

        status = "pending_review" if validation.needs_review or not validation.valid else "completed"
        self.history.update(
            request_id,
            category=classification.get("category"),
            confidence=classification.get("confidence"),
            explanation=classification.get("explanation"),
            metadata=classification.get("metadata", {}),
            validation_status="review" if validation.needs_review or not validation.valid else "passed",
            review_reason=validation.reason if validation.needs_review or not validation.valid else None,
            workflow=workflow,
            status="processing",
        )
        if status == "completed":
            result = self._run(
                request_id,
                "execution_agent",
                {"workflow": workflow, "request_text": request_text},
                lambda: self.execute(workflow, request_text),
            )
            result_check = self._check(
                request_id,
                lambda: self.checker.check_execution(workflow, result),
                {"workflow": workflow, "result": result},
            )
            if not result_check.passed:
                raise RuntimeError(result_check.feedback)

        metadata = dict(classification.get("metadata", {}))
        return {
            **context,
            "classification": classification,
            "validation": context["validation"],
            "workflow": workflow,
            "result": result,
            "status": status,
            "validation_status": "review" if validation.needs_review or not validation.valid else "passed",
            "review_reason": validation.reason if validation.needs_review or not validation.valid else None,
            "metadata": metadata,
            "error": None,
        }

    def record_review(self, request_id: int, action: str, feedback: str, workflow: str | None, operation):
        def execute_tracked(selected_workflow: str, request_text: str):
            return self._run(
                request_id,
                "execution_agent",
                {"workflow": selected_workflow, "request_text": request_text},
                lambda: self.execute(selected_workflow, request_text),
            )

        review_result = self._run(
            request_id,
            "review_agent",
            {"action": action, "feedback": feedback},
            lambda: operation(execute_tracked),
        )
        if action == "approve":
            result = review_result.get("result")
            result_check = self._check(
                request_id,
                lambda: self.checker.check_execution(workflow, result),
                {"workflow": workflow, "result": result},
            )
            if not result_check.passed:
                raise RuntimeError(result_check.feedback)
        self._check(
            request_id,
            lambda: self.checker.check_review(review_result["status"], action),
            {"action": action, "status": review_result["status"]},
        )
        return review_result

    def check_approval_route(self, request_id: int, category: str, workflow: str):
        expected = self.categories[category]["workflow"]
        result = self._check(
            request_id,
            lambda: self.checker.check_route(category, workflow, expected),
            {"category": category, "workflow": workflow, "expected": expected, "approval": True},
        )
        if not result.passed:
            raise RuntimeError(result.feedback)

    def record_failure_feedback(self, request_id: int, error: Exception):
        self._check(
            request_id,
            lambda: CheckResult(False, f"Pipeline stopped after {type(error).__name__}: {error}"),
            {"error_type": type(error).__name__},
        )
