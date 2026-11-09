"""Flask API and static dashboard for the Intelligent Agentic AI Router."""

import atexit
import json
import math
import os
import sqlite3
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, Response, jsonify, request, send_from_directory

from backend.agents.classification_agent import (
    load_categories,
)
from backend.agents.execution_agent import execute_workflow
from backend.agents.orchestrator_agent import AgentOrchestrator
from backend.agents.review_agent import ReviewError, resolve_review
from backend.agents.routing_agent import load_routing_rules, select_workflow
from backend.services.history_service import HistoryService
from backend.services.evaluation_store import EvaluationStore
from backend.services.llm_service import LLMProviderError, create_classifier


ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


def create_app(test_config=None):
    app = Flask(__name__, static_folder=None)
    app.config.from_mapping(
        DATABASE=os.getenv("DATABASE_PATH", str(ROOT / "data" / "router.sqlite3")),
        EVALUATION_DATABASE=os.getenv(
            "EVALUATION_DATABASE", str(ROOT / "data" / "evaluation_results.sqlite3")
        ),
        CONFIDENCE_THRESHOLD=float(os.getenv("CONFIDENCE_THRESHOLD", "0.65")),
        LLM_PROVIDER=os.getenv("LLM_PROVIDER", "demo").lower(),
        GEMINI_API_KEY=os.getenv("GEMINI_API_KEY", ""),
        GEMINI_MODEL=os.getenv("GEMINI_MODEL", "gemini-3.8-flash"),
        LLM_TIMEOUT=float(os.getenv("LLM_TIMEOUT", "20")),
    )
    if test_config:
        app.config.update(test_config)
        if "EVALUATION_DATABASE" not in test_config:
            app.config["EVALUATION_DATABASE"] = f'{app.config["DATABASE"]}.evaluations.sqlite3'
    if app.config["LLM_PROVIDER"] not in {"demo", "gemini"}:
        raise ValueError("LLM_PROVIDER must be 'demo' or 'gemini'.")
    threshold = app.config["CONFIDENCE_THRESHOLD"]
    if (
        not isinstance(threshold, (int, float))
        or isinstance(threshold, bool)
        or not math.isfinite(threshold)
        or not 0 <= threshold <= 1
    ):
        raise ValueError("CONFIDENCE_THRESHOLD must be a finite number between 0 and 1.")
    timeout = app.config["LLM_TIMEOUT"]
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("LLM_TIMEOUT must be a finite positive number.")

    # Create both parent directories up front. The Render database paths point
    # to /var/data, which may not exist until the persistent disk is mounted.
    for database_path in (app.config["DATABASE"], app.config["EVALUATION_DATABASE"]):
        Path(database_path).parent.mkdir(parents=True, exist_ok=True)

    categories = load_categories()
    routing_rules = load_routing_rules()
    history = HistoryService(app.config["DATABASE"])
    evaluation_store = EvaluationStore(app.config["EVALUATION_DATABASE"])
    classifier = app.config.get("CLASSIFIER") or create_classifier(
        app.config["LLM_PROVIDER"],
        app.config["GEMINI_API_KEY"],
        app.config["GEMINI_MODEL"],
        app.config["LLM_TIMEOUT"],
        categories,
    )
    if callable(getattr(classifier, "close", None)):
        atexit.register(classifier.close)
    mode = "real" if app.config["LLM_PROVIDER"] == "gemini" else "demo"

    app.extensions["history"] = history
    app.extensions["evaluation_store"] = evaluation_store
    app.extensions["classifier"] = classifier
    app.extensions["orchestrator_factory"] = lambda: AgentOrchestrator(
        history=history,
        classifier=classifier,
        categories=categories,
        routing_rules=routing_rules,
        confidence_threshold=app.config["CONFIDENCE_THRESHOLD"],
        execute=lambda workflow, text: execute_workflow(workflow, text),
    )

    @app.get("/")
    def index():
        return send_from_directory(ROOT / "frontend", "index.html")

    @app.get("/assets/<path:filename>")
    def frontend_assets(filename):
        return send_from_directory(ROOT / "frontend", filename)

    @app.get("/api/health")
    def health():
        try:
            with history.connect() as connection:
                connection.execute("SELECT 1 FROM requests LIMIT 1").fetchone()
            with evaluation_store.connect() as connection:
                connection.execute("SELECT 1 FROM evaluation_runs LIMIT 1").fetchone()
        except sqlite3.Error:
            app.logger.exception("Health check failed because SQLite storage is unavailable.")
            return jsonify({
                "status": "unavailable",
                "provider": app.config["LLM_PROVIDER"],
                "mode": mode,
                "model": app.config["GEMINI_MODEL"] if mode == "real" else None,
                "storage": "unavailable",
            }), 503
        return jsonify({
            "status": "ok",
            "provider": app.config["LLM_PROVIDER"],
            "mode": mode,
            "model": app.config["GEMINI_MODEL"] if mode == "real" else None,
            "storage": "ok",
        })

    @app.get("/api/dashboard")
    def dashboard():
        filters, error = read_history_filters()
        if error:
            return error
        return jsonify({
            "stats": history.stats(),
            "history": history.list(
                filters["search"],
                filters["status"],
                200,
                filters["category"],
                filters["from_date"],
                filters["to_date"],
            ),
            "reviews": history.list(status="pending_review") + history.list(status="awaiting_clarification"),
            "categories": list(categories.values()),
            "provider": app.config["LLM_PROVIDER"],
            "mode": mode,
            "model": app.config["GEMINI_MODEL"] if mode == "real" else None,
            "confidence_threshold": app.config["CONFIDENCE_THRESHOLD"],
        })

    def read_history_filters():
        from_date = request.args.get("from", "").strip()
        to_date = request.args.get("to", "").strip()
        for label, value in (("from", from_date), ("to", to_date)):
            if value:
                try:
                    datetime.strptime(value, "%Y-%m-%d")
                except ValueError:
                    return None, (jsonify({"error": f"'{label}' must be an ISO date (YYYY-MM-DD)."}), 400)
        if from_date and to_date and from_date > to_date:
            return None, (jsonify({"error": "'from' date must not be after 'to' date."}), 400)
        category = request.args.get("category", "").strip()
        if category and category not in categories:
            return None, (jsonify({"error": "Unsupported category filter."}), 400)
        return {
            "search": request.args.get("search", "").strip(),
            "status": request.args.get("status", "").strip(),
            "category": category,
            "from_date": from_date,
            "to_date": to_date,
        }, None

    @app.get("/api/analytics")
    def analytics():
        filters, error = read_history_filters()
        if error:
            return error
        return jsonify(history.analytics(filters["from_date"], filters["to_date"]))

    @app.get("/api/evaluations")
    def evaluation_runs():
        return jsonify({"runs": evaluation_store.list_runs()})

    @app.get("/api/evaluations/<run_id>")
    def evaluation_report(run_id):
        report = evaluation_store.get_report(run_id)
        if report is None:
            return jsonify({"error": "Evaluation run not found."}), 404
        report = dict(report)
        report.pop("cases", None)
        return jsonify(report)

    @app.get("/api/evaluations/<run_id>/download")
    def download_evaluation_report(run_id):
        report = evaluation_store.get_report(run_id)
        if report is None:
            return jsonify({"error": "Evaluation run not found."}), 404
        report_format = request.args.get("format", "json").lower()
        if report_format == "csv":
            content = evaluation_store.get_csv(run_id)
            if content is None:
                return jsonify({"error": "Evaluation case results are unavailable."}), 404
            return Response(
                content,
                content_type="text/csv; charset=utf-8",
                headers={"Content-Disposition": f'attachment; filename="p18-evaluation-{run_id}.csv"'},
            )
        if report_format != "json":
            return jsonify({"error": "Report format must be 'csv' or 'json'."}), 400
        report["cases"] = evaluation_store.get_cases(run_id)
        return Response(
            json.dumps(report, ensure_ascii=False, indent=2),
            content_type="application/json; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="p18-evaluation-{run_id}.json"'},
        )

    @app.get("/api/requests/<int:request_id>/trace")
    def request_trace(request_id):
        record = history.get(request_id)
        if not record:
            return jsonify({"error": "Request not found."}), 404
        return jsonify({
            "request_id": request_id,
            "status": record["status"],
            "workflow": record["workflow"],
            "trace": history.agent_trace(request_id),
        })

    @app.get("/api/agent-activity")
    def agent_activity():
        return jsonify(history.latest_agent_activity())

    @app.post("/api/requests")
    def submit_request():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"error": "Request body must be a JSON object."}), 400
        request_text = payload.get("request", "")
        if not isinstance(request_text, str) or not request_text.strip():
            return jsonify({"error": "Enter a non-empty text request."}), 400
        if len(request_text) > 4000:
            return jsonify({"error": "Request must be 4,000 characters or fewer."}), 400
        request_text = request_text.strip()
        started = time.perf_counter()
        try:
            record = history.create(
                request_text=request_text,
                category=None,
                confidence=None,
                explanation=None,
                metadata={"provider": app.config["LLM_PROVIDER"], "mode": mode},
                validation_status="processing",
                review_reason=None,
                workflow=None,
                status="processing",
                result=None,
                error=None,
                latency_ms=None,
            )
        except sqlite3.Error as error:
            app.logger.exception("Could not persist request; no agent was started.", exc_info=error)
            return jsonify({"error": "Request storage is unavailable; no workflow was executed."}), 503
        orchestrator = app.extensions["orchestrator_factory"]()
        try:
            outcome = orchestrator.process(record["id"], request_text)
            classification = outcome["classification"]
            metadata = dict(outcome.get("metadata", {}))
            metadata.setdefault("provider", app.config["LLM_PROVIDER"])
            metadata.setdefault("mode", mode)
            metadata["requires_review"] = outcome["validation"]["needs_review"]
            updated = history.update(
                record["id"],
                category=classification.get("category"),
                confidence=classification.get("confidence"),
                explanation=classification.get("explanation"),
                metadata=metadata,
                validation_status=outcome["validation_status"],
                review_reason=outcome.get("review_reason"),
                workflow=outcome.get("workflow"),
                status=outcome["status"],
                result=outcome.get("result"),
                error=outcome.get("error"),
                latency_ms=round((time.perf_counter() - started) * 1000, 2),
            )
            updated["validation_reason"] = outcome["validation"]["reason"]
            updated["requires_review"] = outcome["validation"]["needs_review"]
            updated["agent_trace"] = history.agent_trace(record["id"])
            return jsonify(updated), 201
        except Exception as error:
            provider_error = error if isinstance(error, LLMProviderError) else None
            client_error = provider_error.safe_message if provider_error else "Classification or execution failed. Check server configuration and logs."
            orchestrator.record_failure_feedback(record["id"], error)
            existing = history.get(record["id"])
            failure_fields = {
                "status": "failed",
                "error": client_error,
                "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            }
            if existing["validation_status"] == "processing":
                failure_fields["validation_status"] = "failed"
            failed = history.update(
                record["id"],
                **failure_fields,
            )
            if provider_error:
                app.logger.warning("LLM provider error %s for record %s", provider_error.code, failed["id"])
            else:
                app.logger.exception("Request processing failed for record %s", failed["id"], exc_info=error)
            return jsonify({
                "id": failed["id"],
                "status": "failed",
                "error": client_error,
                "agent_trace": history.agent_trace(failed["id"]),
                "error_code": provider_error.code if provider_error else "PROCESSING_FAILED",
            }), provider_error.http_status if provider_error else 502

    @app.post("/api/reviews/<int:request_id>")
    def review_request(request_id):
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"error": "Review body must be a JSON object."}), 400
        record = history.get(request_id)
        if not record:
            return jsonify({"error": "Request not found."}), 404
        try:
            action = payload.get("action", "")
            feedback = str(payload.get("feedback", ""))[:1000]
            orchestrator = app.extensions["orchestrator_factory"]()
            if payload.get("action") == "approve" and record["category"] in categories and record["category"] != "UNKNOWN":
                canonical_workflow = select_workflow(record["category"], routing_rules, categories)
                if record["workflow"] != canonical_workflow:
                    return jsonify({"error": "Stored workflow does not match the predefined category route."}), 409
                orchestrator.check_approval_route(request_id, record["category"], canonical_workflow)
            changes = orchestrator.record_review(
                request_id,
                action,
                feedback,
                record["workflow"],
                lambda tracked_execute: resolve_review(record, action, feedback, tracked_execute),
            )
            updated = history.update(request_id, **changes)
            updated["agent_trace"] = history.agent_trace(request_id)
            return jsonify(updated)
        except ReviewError as error:
            app.extensions["orchestrator_factory"]().record_failure_feedback(request_id, error)
            return jsonify({"error": str(error)}), 400
        except Exception as error:
            app.extensions["orchestrator_factory"]().record_failure_feedback(request_id, error)
            history.update(request_id, status="failed", error="Approved workflow execution failed.")
            app.logger.exception("Reviewed workflow failed for record %s", request_id, exc_info=error)
            return jsonify({"error": "Workflow execution failed; the failure was recorded."}), 500

    @app.get("/api/history")
    def request_history():
        filters, error = read_history_filters()
        if error:
            return error
        return jsonify(history.list(
            filters["search"],
            filters["status"],
            200,
            filters["category"],
            filters["from_date"],
            filters["to_date"],
        ))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(
        host=os.getenv("FLASK_HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "5000")),
        debug=os.getenv("FLASK_DEBUG") == "1",
    )
