from backend.agents.classification_agent import DemoClassifier, load_categories
from backend.app import create_app


def make_client(database):
    app = create_app({
        "TESTING": True,
        "DATABASE": str(database),
        "LLM_PROVIDER": "demo",
        "CLASSIFIER": DemoClassifier(load_categories()),
    })
    return app.test_client(), app


def test_analytics_are_calculated_from_saved_requests_and_agent_traces(tmp_path):
    client, _ = make_client(tmp_path / "metrics.sqlite3")
    completed = client.post("/api/requests", json={"request": "What is a REST API?"}).json
    pending = client.post("/api/requests", json={"request": "Can you help me?"}).json
    analytics = client.get("/api/analytics").json

    assert analytics["kpis"]["total_requests"] == 2
    assert analytics["kpis"]["classified_requests"] == 1
    assert analytics["kpis"]["routed_requests"] == 1
    assert analytics["kpis"]["pending_reviews"] == 1
    assert analytics["kpis"]["failed_executions"] == 0
    assert analytics["kpis"]["average_execution_ms"] > 0
    assert {"category": "GENERAL_INFORMATION", "count": 1} in analytics["category_distribution"]
    assert sum(item["count"] for item in analytics["confidence_distribution"]) == 2
    assert analytics["execution_outcomes"] == [
        {"status": "completed", "count": 1},
        {"status": "failed", "count": 0},
    ]
    assert sum(item["count"] for item in analytics["human_reviews_over_time"]) == 1
    assert any(item["agent"] == "execution_agent" for item in analytics["agent_latency"])
    assert analytics["evaluation"] is None
    assert analytics["memory"]["available"] is False
    assert client.get(f"/api/requests/{completed['id']}/trace").status_code == 200
    assert client.get(f"/api/requests/{pending['id']}/trace").status_code == 200


def test_empty_database_analytics_are_explicit_and_zero_valued(tmp_path):
    client, _ = make_client(tmp_path / "empty-metrics.sqlite3")
    analytics = client.get("/api/analytics").json
    assert analytics["kpis"] == {
        "total_requests": 0,
        "classified_requests": 0,
        "routed_requests": 0,
        "pending_reviews": 0,
        "failed_executions": 0,
        "average_execution_ms": 0,
    }
    assert analytics["requests_over_time"] == []
    assert analytics["category_distribution"] == []
    assert all(item["count"] == 0 for item in analytics["confidence_distribution"])
    assert analytics["agent_latency"] == []
    assert analytics["memory"]["available"] is False


def test_history_category_and_date_filters_are_applied(tmp_path):
    client, _ = make_client(tmp_path / "filters.sqlite3")
    general = client.post("/api/requests", json={"request": "What is a REST API?"}).json
    client.post("/api/requests", json={"request": "My printer is broken"}).json
    day = general["created_at"][:10]

    result = client.get(f"/api/history?category=GENERAL_INFORMATION&from={day}&to={day}")
    assert result.status_code == 200
    assert [row["id"] for row in result.json] == [general["id"]]
    assert client.get("/api/dashboard?category=INVALID").status_code == 400
    assert client.get("/api/analytics?from=2026-02-31").status_code == 400
    assert client.get("/api/history?from=2026-12-01&to=2026-11-01").status_code == 400


def test_awaiting_clarification_is_in_pending_review_metrics_and_queue(tmp_path):
    client, app = make_client(tmp_path / "clarification-metrics.sqlite3")
    record = app.extensions["history"].create(
        request_text="Please clarify this request.",
        validation_status="review",
        metadata={},
        status="awaiting_clarification",
    )

    dashboard = client.get("/api/dashboard").json
    analytics = client.get("/api/analytics").json

    assert analytics["kpis"]["pending_reviews"] == 1
    assert [item["id"] for item in dashboard["reviews"]] == [record["id"]]


def test_execution_analytics_include_legacy_workflow_records_without_double_counting(tmp_path):
    client, app = make_client(tmp_path / "legacy-executions.sqlite3")
    client.post("/api/requests", json={"request": "What is a REST API?"})
    history = app.extensions["history"]
    for status in ("completed", "failed"):
        history.create(
            request_text=f"Legacy {status} request",
            category="GENERAL_INFORMATION",
            confidence=0.8,
            metadata={},
            validation_status="passed",
            workflow="general_information",
            status=status,
        )

    analytics = client.get("/api/analytics").json

    assert analytics["execution_outcomes"] == [
        {"status": "completed", "count": 2},
        {"status": "failed", "count": 1},
    ]
    assert analytics["kpis"]["failed_executions"] == 1
    assert analytics["kpis"]["average_execution_ms"] > 0
    assert client.get("/api/dashboard").json["stats"]["failed_executions"] == 1
