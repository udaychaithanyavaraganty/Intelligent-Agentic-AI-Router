import json

import pytest
from google.genai import errors

from backend.agents.classification_agent import ClassificationError, load_categories
from backend.services.llm_service import (
    GeminiClassifier,
    LLMAuthenticationError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMUnavailableError,
    MissingAPIKeyError,
)


class FakeResponse:
    def __init__(self, text, response_id="fake-response-id", usage_metadata=None):
        self.text = text
        self.response_id = response_id
        self.model_version = "fake-model-version"
        self.usage_metadata = usage_metadata


class FakeModels:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.response


class FakeClient:
    def __init__(self, response=None, error=None):
        self.models = FakeModels(response, error)
        self.closed = False

    def close(self):
        self.closed = True


def classification_json(**overrides):
    result = {
        "category": "SOFTWARE_DEVELOPMENT",
        "confidence": 0.94,
        "explanation": "The request asks for software development assistance.",
        "requires_review": False,
        "metadata": {"intent": "write code"},
    }
    result.update(overrides)
    return json.dumps(result)


def test_gemini_sdk_request_uses_closed_set_json_schema_and_parses_response():
    client = FakeClient(FakeResponse(classification_json()))
    categories = load_categories()
    classifier = GeminiClassifier("not-a-real-key", "test-model", 3, categories, client=client)

    result = classifier.classify("Help me implement a Python function")

    call = client.models.calls[0]
    schema = call["config"].response_json_schema
    assert call["model"] == "test-model"
    assert call["contents"] == "Help me implement a Python function"
    assert call["config"].response_mime_type == "application/json"
    assert schema["properties"]["category"]["enum"] == list(categories)
    assert all(category in call["config"].system_instruction for category in categories)
    assert result["category"] == "SOFTWARE_DEVELOPMENT"
    assert result["metadata"]["provider"] == "gemini"
    assert result["metadata"]["mode"] == "real"
    assert result["metadata"]["model"] == "test-model"
    assert result["metadata"]["response_id"] == "fake-response-id"


def test_gemini_records_only_provider_reported_token_usage():
    usage = type("Usage", (), {
        "prompt_token_count": 101,
        "candidates_token_count": 27,
        "total_token_count": 128,
    })()
    classifier = GeminiClassifier(
        "not-a-real-key",
        "test-model",
        3,
        load_categories(),
        client=FakeClient(FakeResponse(classification_json(), usage_metadata=usage)),
    )

    result = classifier.classify("Help me implement a Python function")

    assert result["metadata"]["usage"] == {
        "prompt_tokens": 101,
        "candidate_tokens": 27,
        "total_tokens": 128,
    }


def test_gemini_retry_uses_checker_feedback_as_correction_context():
    client = FakeClient(FakeResponse(classification_json()))
    classifier = GeminiClassifier("test-key", "test-model", 3, load_categories(), client=client)
    classifier.classify_with_feedback("Help me write a function", "Confidence must be a finite number.")
    instruction = client.models.calls[0]["config"].system_instruction
    assert "Checker feedback from trusted validation code" in instruction
    assert "Confidence must be a finite number." in instruction


def test_missing_gemini_key_fails_without_fallback():
    with pytest.raises(MissingAPIKeyError, match="GEMINI_API_KEY"):
        GeminiClassifier("", "test-model", 3, load_categories())


def test_sdk_client_receives_timeout_in_milliseconds_and_is_closed(monkeypatch):
    client = FakeClient()
    captured = {}

    def create_client(**kwargs):
        captured.update(kwargs)
        return client

    monkeypatch.setattr("backend.services.llm_service.genai.Client", create_client)
    classifier = GeminiClassifier("test-key", "test-model", 1.25, load_categories())
    assert captured["api_key"] == "test-key"
    assert captured["http_options"].timeout == 1250
    classifier.close()
    assert client.closed


@pytest.mark.parametrize("text", ["not-json", '{"category":"UNKNOWN"}'])
def test_gemini_invalid_json_or_missing_fields_rejected(text):
    classifier = GeminiClassifier(
        "not-a-real-key", "test-model", 3, load_categories(), client=FakeClient(FakeResponse(text))
    )
    with pytest.raises(ClassificationError):
        classifier.classify("unclear request")


def test_gemini_sdk_rate_limit_is_mapped_to_safe_error():
    client = FakeClient(error=errors.ClientError(429, {"message": "secret detail"}))
    classifier = GeminiClassifier("not-a-real-key", "test-model", 3, load_categories(), client=client)
    with pytest.raises(LLMRateLimitError) as caught:
        classifier.classify("request")
    assert caught.value.safe_message == "Gemini rate limit reached. Wait briefly, then retry."
    assert "secret detail" not in caught.value.safe_message


@pytest.mark.parametrize("error,error_type", [
    (TimeoutError("socket timed out"), LLMTimeoutError),
    (errors.ServerError(503, {"message": "unavailable"}), LLMUnavailableError),
    (errors.ClientError(403, {"message": "denied"}), LLMAuthenticationError),
])
def test_gemini_provider_failures_are_classified_safely(error, error_type):
    classifier = GeminiClassifier("not-a-real-key", "test-model", 3, load_categories(), client=FakeClient(error=error))
    with pytest.raises(error_type):
        classifier.classify("request")