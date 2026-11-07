"""Reproducible, isolated evaluation of classification and agent orchestration."""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import statistics
import tempfile
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any

from backend.agents.classification_agent import (
    ClassificationError,
    DemoClassifier,
    load_categories,
)
from backend.agents.execution_agent import execute_workflow
from backend.agents.orchestrator_agent import AgentOrchestrator
from backend.agents.routing_agent import RoutingError, load_routing_rules, select_workflow
from backend.app import create_app
from backend.services.evaluation_store import EvaluationStore
from backend.services.llm_service import LLMTimeoutError, create_classifier


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = ROOT / "data" / "evaluation_dataset_v2.json"


def load_dataset(path: str | Path = DEFAULT_DATASET) -> tuple[dict, list[dict]]:
    source = Path(path).read_bytes()
    spec = json.loads(source)
    if not isinstance(spec, dict) or not isinstance(spec.get("examples"), list):
        raise ValueError("Evaluation dataset must define an examples array.")
    variants = spec.get("variants", [{"prefix": "", "suffix": ""}])
    expanded = []
    seen = set()
    for seed in spec["examples"]:
        if not isinstance(seed, dict) or not isinstance(seed.get("text"), str):
            raise ValueError("Every evaluation seed must contain string text.")
        if not isinstance(seed.get("expected"), str) or not seed["expected"]:
            raise ValueError("Every evaluation seed must contain an expected label.")
        for variant_index, variant in enumerate(variants, start=1):
            text = f'{variant["prefix"]}{seed["text"]}{variant["suffix"]}'.strip()
            if not text or text in seen:
                raise ValueError("Evaluation examples must be non-empty and unique.")
            seen.add(text)
            expanded.append({
                "case_id": f'{seed["id"]}-v{variant_index}',
                "seed_id": seed["id"],
                "kind": seed.get("kind", seed["expected"].lower()),
                "text": text,
                "expected": seed["expected"],
            })
    dataset = {
        "name": spec["name"],
        "version": spec["version"],
        "description": spec["description"],
        "seed": spec.get("seed"),
        "seed_count": len(spec["examples"]),
        "sample_count": len(expanded),
        "sha256": hashlib.sha256(
            json.dumps(expanded, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest(),
    }
    return dataset, expanded


def classification_metrics(cases: list[dict], labels: list[str]) -> dict:
    matrix = {actual: {predicted: 0 for predicted in labels} for actual in labels}
    for case in cases:
        actual = case["expected"]
        predicted = case.get("predicted")
        if actual not in matrix:
            raise ValueError(f"Unknown expected label in dataset: {actual}")
        if predicted not in matrix[actual]:
            predicted = "UNKNOWN" if "UNKNOWN" in labels else labels[0]
        matrix[actual][predicted] += 1
    per_category = {}
    total = len(cases)
    correct = 0
    weighted_f1 = 0.0
    for category in labels:
        true_positive = matrix[category][category]
        support = sum(matrix[category].values())
        predicted_count = sum(matrix[actual][category] for actual in labels)
        false_negative = support - true_positive
        precision = true_positive / predicted_count if predicted_count else 0.0
        recall = true_positive / support if support else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        per_category[category] = {
            "support": support,
            "predicted_count": predicted_count,
            "precision": round(precision, 6),
            "recall": round(recall, 6),
            "f1": round(f1, 6),
        }
        correct += true_positive
        weighted_f1 += f1 * support
    class_count = len(labels)
    return {
        "sample_count": total,
        "accuracy": round(correct / total, 6) if total else 0.0,
        "macro_precision": round(sum(row["precision"] for row in per_category.values()) / class_count, 6),
        "macro_recall": round(sum(row["recall"] for row in per_category.values()) / class_count, 6),
        "macro_f1": round(sum(row["f1"] for row in per_category.values()) / class_count, 6),
        "weighted_f1": round(weighted_f1 / total, 6) if total else 0.0,
        "confusion_matrix": matrix,
        "per_category": per_category,
        "unknown_label_included": "UNKNOWN" in labels,
    }


def confidence_reliability(cases: list[dict]) -> dict:
    """Measure empirical confidence calibration only where a valid score exists."""
    ranges = ((0.0, 0.5), (0.5, 0.65), (0.65, 0.8), (0.8, 1.0))
    scored = [
        case for case in cases
        if isinstance(case.get("confidence"), (int, float))
        and not isinstance(case.get("confidence"), bool)
        and math.isfinite(case["confidence"])
        and 0 <= case["confidence"] <= 1
    ]
    bins = []
    weighted_gap = 0.0
    for lower, upper in ranges:
        members = [
            case for case in scored
            if lower <= case["confidence"] < upper
            or upper == 1.0 and lower <= case["confidence"] <= upper
        ]
        accuracy = sum(case["predicted"] == case["expected"] for case in members) / len(members) if members else None
        mean_confidence = statistics.fmean(case["confidence"] for case in members) if members else None
        if members:
            weighted_gap += len(members) / len(scored) * abs(accuracy - mean_confidence)
        bins.append({
            "range": f"{lower:.2f}-{upper:.2f}",
            "count": len(members),
            "accuracy": round(accuracy, 6) if accuracy is not None else None,
            "mean_confidence": round(mean_confidence, 6) if mean_confidence is not None else None,
        })
    return {
        "sample_count": len(scored),
        "confidence_min": min((case["confidence"] for case in scored), default=None),
        "confidence_max": max((case["confidence"] for case in scored), default=None),
        "expected_calibration_error": round(weighted_gap, 6) if scored else None,
        "bins": bins,
        "note": "Empirical calibration on this fixed benchmark only; model confidence is not assumed to be a calibrated probability.",
    }


def percentile(values: list[float], percentage: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(percentage * len(ordered)))
    return round(ordered[rank - 1], 3)


def _event_duration_ms(event: dict) -> float | None:
    if not event.get("started_at") or not event.get("completed_at"):
        return None
    try:
        started = datetime.fromisoformat(event["started_at"])
        completed = datetime.fromisoformat(event["completed_at"])
    except (TypeError, ValueError):
        return None
    return max(0.0, (completed - started).total_seconds() * 1000)


def _latency_summary(values: list[float]) -> dict:
    return {
        "sample_count": len(values),
        "average_ms": round(statistics.fmean(values), 3) if values else None,
        "median_ms": percentile(values, 0.5),
        "p95_ms": percentile(values, 0.95),
    }


def _make_app(database_path: Path, classifier, provider: str, model: str, threshold: float, timeout: float):
    return create_app({
        "TESTING": True,
        "DATABASE": str(database_path),
        "LLM_PROVIDER": provider,
        "GEMINI_MODEL": model,
        "LLM_TIMEOUT": timeout,
        "CONFIDENCE_THRESHOLD": threshold,
        "CLASSIFIER": classifier,
    })


def _evaluation_cases(app, examples: list[dict]) -> list[dict]:
    categories = load_categories()
    client = app.test_client()
    cases = []
    for example in examples:
        started = perf_counter()
        response = client.post("/api/requests", json={"request": example["text"]})
        response_latency = (perf_counter() - started) * 1000
        body = response.get_json(silent=True) or {}
        trace = body.get("agent_trace") or []
        category = body.get("category")
        predicted = category if category in categories else "UNKNOWN"
        expected_workflow = categories.get(example["expected"], {}).get("workflow")
        workflow = body.get("workflow")
        validation = body.get("validation_status")
        execution_events = [event for event in trace if event["agent"] == "execution_agent"]
        classification_events = [event for event in trace if event["agent"] == "classification_agent"]
        execution_durations = [duration for event in execution_events if (duration := _event_duration_ms(event)) is not None]
        classification_durations = [duration for event in classification_events if (duration := _event_duration_ms(event)) is not None]
        raw_confidence = body.get("confidence")
        cases.append({
            **example,
            "predicted": predicted,
            "raw_predicted": category,
            "confidence": raw_confidence,
            "requires_review": bool(body.get("requires_review")),
            "metadata": body.get("metadata") or {},
            "validation_status": validation,
            "status": body.get("status", "failed"),
            "workflow": workflow,
            "expected_workflow": expected_workflow,
            "correct_route": bool(expected_workflow and workflow == expected_workflow),
            "response_latency_ms": round(response_latency, 3),
            "classification_latency_ms": round(sum(classification_durations), 3) if classification_durations else None,
            "execution_latency_ms": round(sum(execution_durations), 3) if execution_durations else None,
            "agent_trace": trace,
            "error": body.get("error"),
            "http_status": response.status_code,
        })
    return cases


class _RetryFaultClassifier:
    """Inject one malformed provider result, then use the real local classifier."""

    def __init__(self, categories, delegate=None):
        self.delegate = delegate or DemoClassifier(categories)
        self.calls = 0

    def classify(self, request_text):
        self.calls += 1
        if self.calls == 1:
            raise ClassificationError("Controlled evaluation fault: malformed model response.")
        return self.delegate.classify(request_text)

    def classify_with_feedback(self, request_text, feedback):
        classify_with_feedback = getattr(self.delegate, "classify_with_feedback", None)
        if callable(classify_with_feedback):
            return classify_with_feedback(request_text, feedback)
        return self.classify(request_text)


class _AlwaysMalformedClassifier:
    def classify(self, _request_text):
        raise ClassificationError("Controlled evaluation fault: malformed JSON.")


class _UnsupportedClassifier:
    def classify(self, _request_text):
        return {
            "category": "UNREGISTERED_WORKFLOW",
            "confidence": 0.99,
            "explanation": "Controlled invalid category probe.",
            "requires_review": False,
        }


class _TimeoutClassifier:
    def classify(self, _request_text):
        raise LLMTimeoutError()


def _robustness_scenarios(app, evaluated_cases: list[dict], database_path: Path, threshold: float, timeout: float) -> dict:
    categories = load_categories()
    client = app.test_client()
    input_checks = {
        "empty_input_rejected": client.post("/api/requests", json={"request": ""}).status_code == 400,
        "whitespace_input_rejected": client.post("/api/requests", json={"request": "  "}).status_code == 400,
        "oversized_input_rejected": client.post("/api/requests", json={"request": "x" * 4001}).status_code == 400,
        "malformed_json_rejected": client.post(
            "/api/requests", data="{not-json", content_type="application/json"
        ).status_code == 400,
    }

    invalid_route_rejected = False
    try:
        select_workflow("UNREGISTERED_WORKFLOW", load_routing_rules(), categories)
    except RoutingError:
        invalid_route_rejected = True

    injection_cases = [case for case in evaluated_cases if case["kind"] == "adversarial"]
    injection_prevented = sum(
        case["workflow"] is None
        and not any(event["agent"] == "execution_agent" for event in case["agent_trace"])
        and case["status"] in {"pending_review", "awaiting_clarification"}
        for case in injection_cases
    )

    probe_results = {}
    probe_text = "What is a REST API?"
    for name, classifier in (
        ("malformed_classifier_response_held", _AlwaysMalformedClassifier()),
        ("unsupported_category_held", _UnsupportedClassifier()),
        ("provider_timeout_fails_closed", _TimeoutClassifier()),
    ):
        probe_db = database_path.parent / f"{name}.sqlite3"
        probe_app = _make_app(probe_db, classifier, "demo", "", threshold, timeout)
        response = probe_app.test_client().post("/api/requests", json={"request": probe_text})
        result = response.get_json(silent=True) or {}
        trace = result.get("agent_trace", [])
        execution_started = any(event["agent"] == "execution_agent" for event in trace)
        if name == "provider_timeout_fails_closed":
            probe_results[name] = response.status_code == 504 and not execution_started
        else:
            probe_results[name] = result.get("workflow") is None and not execution_started and (
                result.get("status") in {"pending_review", "awaiting_clarification"}
            )

    behavioral_app = _make_app(
        database_path.parent / "behavioral-probes.sqlite3",
        DemoClassifier(categories),
        "demo",
        "",
        threshold,
        timeout,
    )
    behavioral_client = behavioral_app.test_client()
    repeated = "What is a REST API?"
    first = behavioral_client.post("/api/requests", json={"request": repeated}).get_json()
    second = behavioral_client.post("/api/requests", json={"request": repeated}).get_json()
    repeated_requests_isolated = bool(first and second and first["id"] != second["id"])

    concurrency_requests = [
        "My printer is broken",
        "Explain how photosynthesis works",
        "Analyze this dataset",
        "Debug this Python function",
    ]

    def submit_concurrently(text):
        with behavioral_app.test_client() as thread_client:
            response = thread_client.post("/api/requests", json={"request": text})
            return response.status_code, response.get_json(silent=True)

    with ThreadPoolExecutor(max_workers=4) as executor:
        concurrent = list(executor.map(submit_concurrently, concurrency_requests))
    concurrent_requests_ok = all(status == 201 and body for status, body in concurrent)
    concurrent_ids = [body["id"] for _, body in concurrent if body]
    concurrent_requests_ok = concurrent_requests_ok and len(set(concurrent_ids)) == len(concurrency_requests)

    failure_db = database_path.parent / "execution-failure.sqlite3"
    failure_app = _make_app(failure_db, DemoClassifier(categories), "demo", "", threshold, timeout)
    history = failure_app.extensions["history"]

    def fail_execution(_workflow, _text):
        raise RuntimeError("Controlled evaluation execution failure.")

    failure_app.extensions["orchestrator_factory"] = lambda: AgentOrchestrator(
        history=history,
        classifier=failure_app.extensions["classifier"],
        categories=categories,
        routing_rules=load_routing_rules(),
        confidence_threshold=threshold,
        execute=fail_execution,
    )
    failure_response = failure_app.test_client().post(
        "/api/requests", json={"request": "What is a REST API?"}
    )
    failure_body = failure_response.get_json(silent=True) or {}
    failure_trace = failure_body.get("agent_trace", [])
    failed_execution_events = [
        event for event in failure_trace if event["agent"] == "execution_agent"
    ]
    execution_failure_recorded_once = (
        failure_response.status_code == 502
        and len(failed_execution_events) == 1
        and failed_execution_events[0]["status"] == "failed"
    )

    db_classifier = _RetryFaultClassifier(categories)
    db_failure_app = _make_app(database_path.parent / "database-failure.sqlite3", db_classifier, "demo", "", threshold, timeout)
    history = db_failure_app.extensions["history"]
    history.create = lambda **_fields: (_ for _ in ()).throw(sqlite3.OperationalError("controlled database failure"))
    database_response = db_failure_app.test_client().post(
        "/api/requests", json={"request": probe_text}
    )
    database_failed_before_execution = (
        database_response.status_code == 503
        and db_classifier.calls == 0
        and "no workflow was executed" in database_response.get_json()["error"]
    )

    return {
        "input_validation": input_checks,
        "invalid_category_rejected": invalid_route_rejected,
        "unauthorized_execution_prevention": {
            "adversarial_examples": len(injection_cases),
            "prevented": injection_prevented,
            "rate": round(injection_prevented / len(injection_cases), 6) if injection_cases else None,
        },
        "controlled_failure_probes": probe_results,
        "repeated_requests_get_distinct_records": repeated_requests_isolated,
        "concurrent_requests_succeeded": concurrent_requests_ok,
        "execution_failure_recorded_without_retry": execution_failure_recorded_once,
        "database_failure_prevented_classification_and_execution": database_failed_before_execution,
    }


def _checker_recovery_probe(app, categories) -> dict:
    history = app.extensions["history"]
    retry_classifier = _RetryFaultClassifier(
        categories,
        delegate=app.extensions["classifier"],
    )
    previous_factory = app.extensions["orchestrator_factory"]
    app.extensions["orchestrator_factory"] = lambda: AgentOrchestrator(
        history=history,
        classifier=retry_classifier,
        categories=categories,
        routing_rules=load_routing_rules(),
        confidence_threshold=app.config["CONFIDENCE_THRESHOLD"],
        execute=execute_workflow,
    )
    started = perf_counter()
    try:
        response = app.test_client().post(
            "/api/requests",
            json={"request": "What is a REST API? (controlled checker retry probe)"},
        )
    finally:
        app.extensions["orchestrator_factory"] = previous_factory
    elapsed_ms = (perf_counter() - started) * 1000
    outcome = response.get_json(silent=True) or {}
    trace = outcome.get("agent_trace", [])
    checker_events = [event for event in trace if event["agent"] == "checker_agent"]
    classification_attempts = [
        event for event in trace if event["agent"] == "classification_agent"
    ]
    detected_faults = sum(
        event["status"] == "failed" and bool(event["checker_feedback"])
        for event in checker_events
    )
    recovered = outcome.get("status") == "completed" and len(classification_attempts) > 1
    return {
        "scenario": "One controlled malformed classifier result, checker feedback, then retry with the local demo classifier.",
        "injected_faults": 1,
        "checker_detections": detected_faults,
        "checker_detection_rate": round(detected_faults, 6),
        "retry_attempts": max(0, len(classification_attempts) - 1),
        "retry_succeeded": recovered,
        "final_status": outcome.get("status", "failed"),
        "metadata": outcome.get("metadata") or {},
        "elapsed_ms": round(elapsed_ms, 3),
        "trace": trace,
    }


def run_evaluation(
    provider: str = "demo",
    model: str = "",
    api_key: str = "",
    threshold: float = 0.65,
    timeout: float = 20,
    dataset_path: str | Path = DEFAULT_DATASET,
    store_path: str | Path | None = None,
) -> dict:
    dataset, examples = load_dataset(dataset_path)
    categories = load_categories()
    labels = sorted(categories)
    if any(example["expected"] not in categories for example in examples):
        raise ValueError("Evaluation dataset contains a label outside the configured closed set.")
    classifier = create_classifier(provider, api_key, model, timeout, categories)
    with tempfile.TemporaryDirectory(prefix="p18-evaluation-") as temporary:
        work = Path(temporary)
        app = _make_app(work / "request_traces.sqlite3", classifier, provider, model, threshold, timeout)
        cases = _evaluation_cases(app, examples)
        robustness = _robustness_scenarios(app, cases, work / "robustness", threshold, timeout)
        recovery = _checker_recovery_probe(app, categories)
        traces = [event for case in cases for event in case["agent_trace"]]
        execution_agents = [event for event in traces if event["agent"] == "execution_agent"]
        completed_agents = sum(event["status"] == "completed" for event in traces)
        failed_agents = sum(event["status"] == "failed" for event in traces)
        checker_events = [event for event in traces if event["agent"] == "checker_agent"]
        agent_groups = {}
        for event in traces:
            group = agent_groups.setdefault(
                event["agent"],
                {"invocations": 0, "completed": 0, "failed": 0, "durations": []},
            )
            group["invocations"] += 1
            group[event["status"]] = group.get(event["status"], 0) + 1
            duration = _event_duration_ms(event)
            if duration is not None:
                group["durations"].append(duration)
        per_agent = {
            name: {
                "invocations": data["invocations"],
                "completed": data["completed"],
                "failed": data["failed"],
                "success_rate": round(data["completed"] / data["invocations"], 6)
                if data["invocations"] else None,
                "average_latency_ms": round(statistics.fmean(data["durations"]), 3)
                if data["durations"] else None,
            }
            for name, data in sorted(agent_groups.items())
        }
        dataset_retry_counts = [
            max(
                (event["retry_attempt"] for event in case["agent_trace"]
                 if event["agent"] == "classification_agent"),
                default=1,
            ) - 1
            for case in cases
        ]
        benchmark_retry_attempts = sum(dataset_retry_counts)
        total_retry_attempts = benchmark_retry_attempts + recovery["retry_attempts"]
        retried_cases = [
            case for case, retries in zip(cases, dataset_retry_counts)
            if retries > 0
        ]
        retry_successes = sum(case["status"] == "completed" for case in retried_cases)
        if recovery["retry_attempts"]:
            retried_cases.append({"status": recovery["final_status"]})
            retry_successes += recovery["retry_succeeded"]
        escalated = [
            case for case in cases
            if case["status"] in {"pending_review", "awaiting_clarification"}
        ]
        expected_unknown = [case for case in cases if case["expected"] == "UNKNOWN"]
        correct_routes = [case for case in cases if case["correct_route"]]
        known_examples = [case for case in cases if case["expected"] != "UNKNOWN"]
        execution_failures = sum(event["status"] == "failed" for event in execution_agents)
        latencies = [case["response_latency_ms"] for case in cases]
        classification_latencies = [
            case["classification_latency_ms"] for case in cases
            if case["classification_latency_ms"] is not None
        ]
        agent_latencies = [
            duration for event in traces if (duration := _event_duration_ms(event)) is not None
        ]
        workflow_latencies = [
            duration for event in execution_agents if (duration := _event_duration_ms(event)) is not None
        ]
        tokens = [
            case["metadata"]["usage"]
            for case in cases
            if isinstance(case.get("metadata"), dict) and isinstance(case["metadata"].get("usage"), dict)
        ]
        if isinstance(recovery.get("metadata"), dict) and isinstance(recovery["metadata"].get("usage"), dict):
            tokens.append(recovery["metadata"]["usage"])
        token_totals = {}
        for usage in tokens:
            for token_name, value in usage.items():
                if isinstance(value, int) and not isinstance(value, bool):
                    token_totals[token_name] = token_totals.get(token_name, 0) + value
        metrics = {
            "classification": {
                **classification_metrics(cases, labels),
                "confidence_reliability": confidence_reliability(cases),
            },
            "escalation": {
                "expected_review_count": len(expected_unknown),
                "actual_escalation_count": len(escalated),
                "unknown_escalated_count": sum(case in escalated for case in expected_unknown),
                "unknown_recall": round(
                    sum(case in escalated for case in expected_unknown) / len(expected_unknown), 6
                ) if expected_unknown else None,
                "escalation_rate": round(len(escalated) / len(cases), 6) if cases else 0,
                "unexpected_escalation_count": sum(
                    case["expected"] != "UNKNOWN" and case in escalated for case in cases
                ),
                "note": "UNKNOWN is scored as a classification label; escalation is reported separately from class accuracy.",
            },
            "routing": {
                "known_intent_count": len(known_examples),
                "correct_workflow_count": len(correct_routes),
                "correct_workflow_selection_rate": round(len(correct_routes) / len(known_examples), 6) if known_examples else None,
                "invalid_category_rejection_rate": 1.0 if robustness["invalid_category_rejected"] else 0.0,
                "unauthorized_execution_prevention_rate": robustness["unauthorized_execution_prevention"]["rate"],
                "workflow_execution_success_rate": round(
                    sum(event["status"] == "completed" for event in execution_agents)
                    / len(execution_agents), 6
                ) if execution_agents else None,
            },
            "multi_agent": {
                "agent_invocations": completed_agents + failed_agents,
                "agent_execution_success_rate": round(
                    completed_agents / (completed_agents + failed_agents), 6
                ) if completed_agents + failed_agents else None,
                "agent_failure_rate": round(
                    failed_agents / (completed_agents + failed_agents), 6
                ) if completed_agents + failed_agents else None,
                "checker_invocations": len(checker_events),
                "per_agent": per_agent,
                "checker_failures_with_feedback": sum(
                    event["status"] == "failed" and bool(event["checker_feedback"])
                    for event in checker_events
                ),
                "checker_detection_rate_controlled_fault": recovery["checker_detection_rate"],
                "retry_attempts": total_retry_attempts,
                "benchmark_retry_attempts": benchmark_retry_attempts,
                "controlled_probe_retry_attempts": recovery["retry_attempts"],
                "average_retries_per_evaluated_request": round(
                    sum(dataset_retry_counts) / len(cases), 6
                ) if cases else 0,
                "retry_successes": retry_successes,
                "retry_success_rate": round(retry_successes / len(retried_cases), 6) if retried_cases else None,
                "recovery_probe": {key: value for key, value in recovery.items() if key != "trace"},
                "human_intervention_frequency": len(escalated),
                "human_intervention_rate": round(len(escalated) / len(cases), 6) if cases else 0,
            },
            "performance": {
                "response_latency": _latency_summary(latencies),
                "classification_latency": _latency_summary(classification_latencies),
                "agent_execution_latency": _latency_summary(agent_latencies),
                "workflow_execution_time": {
                    "workflow_invocations": len(execution_agents),
                    "total_ms": round(sum(workflow_latencies), 3),
                    **_latency_summary(workflow_latencies),
                },
                "provider_token_usage": {
                    "available": bool(token_totals),
                    "observed_invocations": len(tokens),
                    "totals": token_totals if token_totals else None,
                },
                "api_cost_usd": None,
                "api_cost_note": "No verified provider pricing configuration is available; cost is not estimated.",
            },
        }
        report = {
            "schema_version": "1.0",
            "run_id": str(uuid.uuid4()),
            "executed_at": datetime.now(timezone.utc).isoformat(),
            "configuration": {
                "provider": provider,
                "mode": "real" if provider != "demo" else "demo",
                "model": model or None,
                "confidence_threshold": threshold,
                "timeout_seconds": timeout,
                "random_seed": dataset.get("seed"),
                "execution": "isolated temporary SQLite request history; evaluation results are stored separately",
                "retrieved_memory": False,
            },
            "dataset": dataset,
            "metrics": metrics,
            "robustness": robustness,
            "checker_recovery_probe": {key: value for key, value in recovery.items() if key != "trace"},
            "comparative_analysis": {
                "normal_vs_checker_recovery": {
                    "available": True,
                    "provider": provider,
                    "normal_response_latency": _latency_summary(latencies),
                    "controlled_retry_response_latency_ms": recovery["elapsed_ms"],
                    "controlled_retry_final_status": recovery["final_status"],
                    "note": "The controlled recovery request uses the same selected provider after one injected local parse failure; this single fault-injection sample is descriptive, not a significance or improvement claim.",
                },
                "memory_comparison": {
                    "available": False,
                    "reason": "The project has no retrieval or memory module to evaluate.",
                },
                "checker_disabled_baseline": {
                    "available": False,
                    "reason": "Disabling the checker would bypass a safety control and is not benchmarked.",
                },
            },
            "limitations": [
                "This is a fixed, locally authored benchmark with deterministic context variants, not a representative production sample.",
                "Demo-provider scores characterize keyword heuristics and are not estimates of real-world semantic accuracy.",
                "Real-provider runs require explicit provider selection and may consume billable quota; no real-provider run is implied by demo results.",
                "No pricing is configured, so API cost is intentionally null.",
                "Memory-based classification is unavailable in this project; no memory benefit is claimed.",
                "The controlled checker retry probe is fault injection, not a randomized reliability estimate.",
            ],
            "cases": cases,
        }
    if store_path:
        store = EvaluationStore(store_path)
        matches = [
            run for run in store.list_runs()
            if run["dataset"]["sha256"] == report["dataset"]["sha256"]
            and run["provider"] != provider
        ]
        report["comparative_analysis"]["same_dataset_provider_runs"] = [
            {
                "run_id": run["run_id"],
                "provider": run["provider"],
                "model": run["model"],
                "sample_count": run["dataset"]["sample_count"],
                "classification_accuracy": run["metrics"]["classification"]["accuracy"],
                "macro_f1": run["metrics"]["classification"]["macro_f1"],
                "accuracy_delta_current_minus_comparison": round(
                    report["metrics"]["classification"]["accuracy"]
                    - run["metrics"]["classification"]["accuracy"],
                    6,
                ),
                "macro_f1_delta_current_minus_comparison": round(
                    report["metrics"]["classification"]["macro_f1"]
                    - run["metrics"]["classification"]["macro_f1"],
                    6,
                ),
                "note": "Descriptive paired dataset result only; not a causal or production-quality improvement claim.",
            }
            for run in matches
        ]
        report["comparative_analysis"]["provider_comparison_available"] = bool(matches)
        if not matches:
            report["comparative_analysis"]["provider_comparison_note"] = (
                "No stored run from another provider uses this exact dataset version and SHA-256."
            )
        store.save(report)
    return report
