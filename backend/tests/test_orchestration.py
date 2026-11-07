import threading

import pytest

import backend.app as app_module
from backend.agents.classification_agent import ClassificationError, DemoClassifier, load_categories
from backend.app import create_app


class SequenceClassifier:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = 0

    def classify(self, request_text):
        self.calls += 1
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


def classification(category="GENERAL_INFORMATION", confidence=0.9):
    return {
        "category": category,
        "confidence": confidence,
        "explanation": "Test classification.",
        "requires_review": False,
    }


@pytest.fixture
def make_client(tmp_path):
    def create(classifier=None):
        app = create_app({
            "TESTING": True,
            "DATABASE": str(tmp_path / "orchestrator.sqlite3"),
            "LLM_PROVIDER": "demo",
            "CLASSIFIER": classifier or DemoClassifier(load_categories()),
            "CONFIDENCE_THRESHOLD": 0.65,
        })
        return app.test_client(), app
    return create


def test_successful_collaboration_persists_structured_stage_trace(make_client):
    client, app = make_client()
    response = client.post("/api/requests", json={"request": "What is a REST API?"})
    assert response.status_code == 201
    record = response.json
    assert record["status"] == "completed"
    agents = [event["agent"] for event in record["agent_trace"]]
    assert agents == [
        "classification_agent", "checker_agent", "validation_agent", "checker_agent",
        "routing_agent", "checker_agent", "execution_agent", "checker_agent",
    ]
    assert all(event["status"] == "completed" for event in record["agent_trace"])
    assert all(event["started_at"] and event["completed_at"] for event in record["agent_trace"])
    assert record["agent_trace"][0]["inputs"]["request_text"] == "What is a REST API?"
    assert record["agent_trace"][-1]["outputs"]["passed"] is True
    assert client.get(f"/api/requests/{record['id']}/trace").json["trace"] == record["agent_trace"]
    assert client.get("/api/agent-activity").json["request_id"] == record["id"]
    assert app.extensions["history"].get(record["id"])["category"] == "GENERAL_INFORMATION"


def test_agent_activity_api_reports_currently_running_agent(tmp_path):
    started = threading.Event()
    release = threading.Event()

    class BlockingClassifier:
        def classify(self, request_text):
            started.set()
            assert release.wait(timeout=5)
            return classification()

    app = create_app({
        "TESTING": True,
        "DATABASE": str(tmp_path / "running-agent.sqlite3"),
        "LLM_PROVIDER": "demo",
        "CLASSIFIER": BlockingClassifier(),
    })
    response_holder = []
    worker = threading.Thread(
        target=lambda: response_holder.append(
            app.test_client().post("/api/requests", json={"request": "Explain this"})
        )
    )
    worker.start()
    assert started.wait(timeout=3)
    activity = app.test_client().get("/api/agent-activity").json
    assert activity["status"] == "processing"
    assert activity["trace"][-1]["agent"] == "classification_agent"
    assert activity["trace"][-1]["status"] == "running"
    release.set()
    worker.join(timeout=5)
    assert not worker.is_alive()
    assert response_holder[0].status_code == 201


def test_recoverable_classification_failure_retries_once_and_records_checker_feedback(make_client):
    classifier = SequenceClassifier([ClassificationError("malformed response"), classification()])
    client, _ = make_client(classifier)
    record = client.post("/api/requests", json={"request": "Explain a REST API"}).json
    classification_events = [event for event in record["agent_trace"] if event["agent"] == "classification_agent"]
    assert record["status"] == "completed"
    assert classifier.calls == 2
    assert [event["retry_attempt"] for event in classification_events] == [1, 2]
    assert any(event["checker_feedback"] for event in record["agent_trace"] if event["agent"] == "checker_agent")


def test_checker_feedback_is_passed_to_a_corrective_classifier_retry(make_client):
    class FeedbackClassifier(SequenceClassifier):
        def __init__(self):
            super().__init__([ClassificationError("malformed response"), classification()])
            self.feedback = []

        def classify_with_feedback(self, request_text, feedback):
            self.feedback.append(feedback)
            return self.classify(request_text)

    classifier = FeedbackClassifier()
    client, _ = make_client(classifier)
    record = client.post("/api/requests", json={"request": "Explain a REST API"}).json
    assert record["status"] == "completed"
    assert classifier.feedback == ["malformed response"]
    retry = [event for event in record["agent_trace"] if event["agent"] == "classification_agent"][1]
    assert retry["inputs"]["checker_feedback"] == "malformed response"


def test_classification_retry_limit_escalates_to_review_without_routing(make_client):
    classifier = SequenceClassifier([
        ClassificationError("malformed 1"),
        ClassificationError("malformed 2"),
        classification(),
    ])
    client, _ = make_client(classifier)
    record = client.post("/api/requests", json={"request": "Explain this"}).json
    assert record["status"] == "pending_review"
    assert record["category"] == "UNKNOWN"
    assert classifier.calls == 2
    assert not any(event["agent"] in ("routing_agent", "execution_agent") for event in record["agent_trace"])
    assert len([event for event in record["agent_trace"] if event["agent"] == "classification_agent"]) == 2


def test_validation_failure_feedback_causes_only_one_controlled_reclassification(make_client):
    classifier = SequenceClassifier([
        classification(category="NOT_CONFIGURED"),
        classification(category="GENERAL_INFORMATION"),
    ])
    client, _ = make_client(classifier)
    record = client.post("/api/requests", json={"request": "Explain this"}).json
    assert record["status"] == "completed"
    assert classifier.calls == 2
    checker_events = [event for event in record["agent_trace"] if event["agent"] == "checker_agent"]
    assert any(event["status"] == "failed" and event["checker_feedback"] for event in checker_events)
    assert [event["retry_attempt"] for event in record["agent_trace"] if event["agent"] == "validation_agent"] == [1, 2]


def test_execution_failure_is_traced_and_never_automatically_retried(make_client, monkeypatch):
    def fail(*_args):
        raise RuntimeError("execution unavailable")

    monkeypatch.setattr(app_module, "execute_workflow", fail)
    client, _ = make_client()
    response = client.post("/api/requests", json={"request": "What is a REST API?"})
    assert response.status_code == 502
    trace = response.json["agent_trace"]
    execution_events = [event for event in trace if event["agent"] == "execution_agent"]
    assert len(execution_events) == 1
    assert execution_events[0]["status"] == "failed"
    assert "execution unavailable" in execution_events[0]["error"]
    assert any(event["checker_feedback"] for event in trace if event["agent"] == "checker_agent")
    assert client.get("/api/dashboard").json["stats"]["classified_requests"] == 1


def test_human_approval_and_rejection_are_traced(make_client):
    classifier = SequenceClassifier([
        classification(confidence=0.4),
        classification(confidence=0.4),
    ])
    client, _ = make_client(classifier)
    pending = client.post("/api/requests", json={"request": "Explain this"}).json
    approved = client.post(f"/api/reviews/{pending['id']}", json={"action": "approve", "feedback": "Reviewed"}).json
    assert approved["status"] == "completed"
    assert [event["agent"] for event in approved["agent_trace"][-5:]] == [
        "checker_agent", "review_agent", "execution_agent", "checker_agent", "checker_agent",
    ]
    assert all(event["status"] == "completed" for event in approved["agent_trace"][-5:])

    pending = client.post("/api/requests", json={"request": "Explain this"}).json
    rejected = client.post(f"/api/reviews/{pending['id']}", json={"action": "reject"}).json
    assert rejected["status"] == "rejected"
    assert rejected["agent_trace"][-2]["agent"] == "review_agent"
    assert rejected["agent_trace"][-1]["agent"] == "checker_agent"
