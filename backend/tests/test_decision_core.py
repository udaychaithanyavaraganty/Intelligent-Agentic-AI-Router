import pytest

from backend.agents.classification_agent import DemoClassifier, load_categories, parse_classification, ClassificationError
from backend.agents.routing_agent import RoutingError, load_routing_rules, select_workflow
from backend.agents.validation_agent import validate_classification
from backend.evaluate import confidence_reliability


@pytest.fixture
def categories():
    return load_categories()


def test_demo_classifier_assigns_supported_technical_category(categories):
    result = DemoClassifier(categories).classify("My printer is not working")
    assert result["category"] == "TECHNICAL_SUPPORT"
    assert validate_classification(result, categories, 0.65).needs_review is False


def test_ambiguous_intent_escalates(categories):
    result = DemoClassifier(categories).classify("Can you help me?")
    assert result["category"] == "UNKNOWN"
    assert validate_classification(result, categories, 0.65).needs_review is True


def test_low_confidence_escalates(categories):
    result = {"category": "GENERAL_INFORMATION", "confidence": 0.4, "explanation": "uncertain"}
    validation = validate_classification(result, categories, 0.65)
    assert validation.valid and validation.needs_review


def test_unsupported_category_is_never_routed(categories):
    with pytest.raises(RoutingError):
        select_workflow("ARBITRARY_WORKFLOW", load_routing_rules(), categories)


def test_routes_deterministically_and_unknown_only_to_review(categories):
    rules = load_routing_rules()
    assert select_workflow("SOFTWARE_DEVELOPMENT", rules, categories) == "software_development"
    assert select_workflow("SOFTWARE_DEVELOPMENT", rules, categories) == "software_development"
    assert select_workflow("UNKNOWN", rules, categories) == "human_review"


def test_malformed_provider_json_is_rejected(categories):
    with pytest.raises(ClassificationError):
        parse_classification("{not-json", categories)


@pytest.mark.parametrize("raw", [
    '{"category":"GENERAL_INFORMATION","confidence":true,"explanation":"x"}',
    '{"category":"GENERAL_INFORMATION","confidence":NaN,"explanation":"x"}',
    '{"category":"GENERAL_INFORMATION","confidence":1.1,"explanation":"x"}',
    '{"category":"GENERAL_INFORMATION","confidence":0.5}',
])
def test_malformed_classifier_fields_are_rejected(categories, raw):
    with pytest.raises(ClassificationError):
        parse_classification(raw, categories)


def test_confidence_reliability_reports_empirical_accuracy_gap():
    result = confidence_reliability([
        {"expected": "A", "predicted": "A", "confidence": 0.9},
        {"expected": "A", "predicted": "B", "confidence": 0.7},
    ])
    assert result["expected_calibration_error"] == 0.4
    assert [bucket["count"] for bucket in result["bins"]] == [0, 0, 1, 1]