# Testing Report

## 1. Execution summary

| Item | Observed result |
|---|---|
| Test command | `python -m pytest -q` |
| Pytest result | **90 passed in 18.70 seconds** |
| Python syntax/bytecode check | `python -m compileall -q backend` — passed |
| Frontend JavaScript syntax check | `node --check frontend\js\app.js` — passed |
| Real Gemini network calls in tests | None; provider SDK behavior is tested with mocked clients |
| Databases used by tests | Isolated temporary SQLite files |

The test result is from the final application implementation, including the updated storage-aware health check. Later edits in this step changed documentation and deployment configuration only. Test cases below combine parameterized test function invocations where appropriate; the 90 count is pytest's executed case count, not the number of named Python test functions.

## 2. Test case ledger

Every listed case passed in the full test run. “Actual” means the assertions recorded by the test completed successfully; it does not imply a manual production deployment test.

| ID | Test description and input condition | Expected output | Actual output / result | Source test(s) |
|---|---|---|---|---|
| TC-001 | Submit “My WiFi has an error” | `TECHNICAL_SUPPORT`, completed, registered workflow, result message | All assertions passed; **PASS** | `test_common_categories_route_successfully` |
| TC-002 | Submit “What is a REST API?” | `GENERAL_INFORMATION`, completed, registered workflow, result message | All assertions passed; **PASS** | `test_common_categories_route_successfully` |
| TC-003 | Submit “Help me debug this Python function” | `SOFTWARE_DEVELOPMENT`, completed, registered workflow, result message | All assertions passed; **PASS** | `test_common_categories_route_successfully` |
| TC-004 | Submit “Analyze the trend in my dataset” | `DATA_ANALYSIS`, completed, registered workflow, result message | All assertions passed; **PASS** | `test_common_categories_route_successfully` |
| TC-005 | Submit “Reset my account password” | `ACCOUNT_MANAGEMENT`, completed, registered workflow, result message | All assertions passed; **PASS** | `test_common_categories_route_successfully` |
| TC-006 | Submit “Automate this repetitive task” | `TASK_AUTOMATION`, completed, registered workflow, result message | All assertions passed; **PASS** | `test_common_categories_route_successfully` |
| TC-007 | Submit empty/whitespace text or a non-object JSON payload | Reject before orchestration with `400` | Requests rejected; **PASS** | `test_empty_input_is_rejected`; `test_non_object_request_payload_is_rejected` |
| TC-008 | Submit ambiguous “Can you help me?” | Pending human review, no workflow or execution | `pending_review`, no workflow; execution was guarded; **PASS** | `test_ambiguous_request_is_queued_without_execution` |
| TC-009 | Supply known category with confidence `0.3` | Keep candidate workflow for review, do not execute | Pending review, no result; **PASS** | `test_low_confidence_is_queued_without_execution` |
| TC-010 | Classifier returns `DELETE_ALL_DATA` | Treat as unsupported; no route or execution; do not count as classified | Pending review, no workflow; classified count remained zero; **PASS** | `test_unsupported_category_cannot_execute` |
| TC-011 | Confidence is boolean, NaN, negative, over 1, string, null, or excessively large | Never route invalid confidence | All parameter cases were held for review with no workflow; **PASS** | `test_invalid_confidence_values_are_never_routed` |
| TC-012 | Request says to ignore category rules and launch a new workflow | Detect policy override before provider call; force `UNKNOWN` review | Provider was not called; no workflow; **PASS** | `test_routing_override_attempt_is_held_before_provider_call` |
| TC-013 | Provider raises an unexpected exception | Record failed request, return safe error, do not count as execution failure | API returned `502`; failed-request metric incremented; **PASS** | `test_provider_failures_are_logged` |
| TC-014 | Classifier returns malformed JSON or incomplete classification object | Hold as `UNKNOWN`, do not route, increment review count | Both parameter cases entered review without workflow; **PASS** | `test_malformed_classification_is_held_for_review`; `test_malformed_provider_json_is_rejected`; `test_malformed_classifier_fields_are_rejected` |
| TC-015 | Review attempts approve/reject/clarify, including an unsupported approval or non-pending record | Allow only eligible state transitions; prevent unsupported execution | Review state/route checks passed; **PASS** | `test_review_approval_executes_only_predefined_workflow`; `test_review_approval_rejects_noncanonical_stored_route`; `test_review_reject_and_clarify_actions`; `test_non_object_review_payload_does_not_change_pending_record`; `test_review_agent_requires_pending_status` |
| TC-016 | Request directly names a workflow not in the local registry | Reject arbitrary workflow identifier | `ExecutionError` asserted; **PASS** | `test_execution_registry_rejects_arbitrary_workflow` |
| TC-017 | Registered workflow raises during execution | Record one failed execution and error; do not retry automatically | Failure persisted and dashboard execution-failure count incremented; **PASS** | `test_workflow_failure_is_recorded`; `test_execution_failure_is_traced_and_never_automatically_retried` |
| TC-018 | Operational database insert fails before request processing | Return `503`; neither classifier nor workflow is called | Safe 503 asserted and execution was prevented; **PASS** | `test_database_failure_returns_safe_error_before_classifier_or_workflow` |
| TC-019 | Filter/search history and change review state | Persist records and derive metrics from current stored state | Search, filtering, and review metric assertions passed; **PASS** | `test_history_filter_search`; `test_history_persists_and_dashboard_metrics_follow_review_state` |
| TC-020 | Request history contains successful and review events | Dashboard/analytics reflect saved requests, traces, charts, and unavailable memory | Calculated values matched fixtures; **PASS** | `test_analytics_are_calculated_from_saved_requests_and_agent_traces` |
| TC-021 | Query a newly initialized empty database | Explicit zero KPIs, empty time/category/agent series, unavailable memory | Empty-state assertions passed; **PASS** | `test_empty_database_analytics_are_explicit_and_zero_valued` |
| TC-022 | Apply valid category/date filters and invalid category/date bounds | Return matching rows; reject invalid filters with `400` | Filter and validation assertions passed; **PASS** | `test_history_category_and_date_filters_are_applied` |
| TC-023 | Add `awaiting_clarification` record | Include it in review queue and pending-review metrics | Queue and count assertions passed; **PASS** | `test_awaiting_clarification_is_in_pending_review_metrics_and_queue` |
| TC-024 | Combine trace-backed and legacy workflow records | Count execution outcomes once; preserve latency/failure metrics | Completed/failed counts and no-double-counting assertions passed; **PASS** | `test_execution_analytics_include_legacy_workflow_records_without_double_counting` |
| TC-025 | Complete a normal orchestration path | Persist classification/checker/validation/routing/execution/checker sequence with inputs, outputs, and timestamps | Expected sequence and trace API contents matched; **PASS** | `test_successful_collaboration_persists_structured_stage_trace` |
| TC-026 | Block classifier while a request is running | Activity endpoint reports current request and `running` classification event | Running state observed before release; **PASS** | `test_agent_activity_api_reports_currently_running_agent` |
| TC-027 | Classifier raises one recoverable parse error, then succeeds | Record checker feedback; one correction retry; finish completed | Two attempts and feedback persisted; **PASS** | `test_recoverable_classification_failure_retries_once_and_records_checker_feedback`; `test_checker_feedback_is_passed_to_a_corrective_classifier_retry` |
| TC-028 | Classifier remains malformed beyond retry bound | Stop after two total attempts, escalate, never route/execute | Exactly two attempts and no routing/execution; **PASS** | `test_classification_retry_limit_escalates_to_review_without_routing` |
| TC-029 | First classification is unsupported; second is valid | Checker feedback supports one controlled reclassification | Second validation attempt succeeded; **PASS** | `test_validation_failure_feedback_causes_only_one_controlled_reclassification` |
| TC-030 | Complete a low-confidence request with human approval or rejection | Trace review and any eligible approval execution; record final state | Review execution trace/state assertions passed; **PASS** | `test_human_approval_and_rejection_are_traced` |
| TC-031 | Load versioned benchmark repeatedly | At least 200 unique examples; fixed labels include all configured categories and adversarial kinds; stable hash | Dataset version, size, coverage, uniqueness, hash assertions passed; **PASS** | `test_versioned_benchmark_is_reproducible_diverse_and_closed_set` |
| TC-032 | Compute classification metrics including `UNKNOWN` | Confusion matrix, support, F1, and unknown label are calculated correctly | Small fixture produced expected 2/3 accuracy and weighted F1; **PASS** | `test_classification_metrics_include_unknown_in_confusion_and_f1` |
| TC-033 | Run benchmark with a small test dataset alongside an ordinary history database | Write run/cases separately, preserve ordinary history, export CSV, exercise checker recovery and unauthorized-execution probe | Separation and metric assertions passed; **PASS** | `test_benchmark_uses_isolated_traces_and_persists_exportable_results` |
| TC-034 | Query evaluation list/detail and JSON/CSV downloads | Summary excludes cases; JSON download includes them; CSV valid; missing/unsupported formats handled | API response/status/content assertions passed; **PASS** | `test_evaluation_report_api_and_download_formats` |
| TC-035 | Configure real provider without a key or with invalid app settings | Fail configuration rather than silently switching providers | Missing key/provider/configuration checks passed; **PASS** | `test_gemini_provider_requires_api_key`; `test_invalid_confidence_threshold_is_rejected`; `test_unknown_provider_is_rejected`; `test_invalid_llm_timeout_is_rejected` |
| TC-036 | Serve dashboard and frontend assets from Flask | Return dashboard HTML and assets successfully | Routes served successfully; **PASS** | `test_dashboard_and_assets_are_served_from_api_app` |
| TC-039 | Make operational SQLite unavailable during health check | Return sanitized `503` and unavailable status, without disclosing database exception | HTTP status and JSON status asserted; **PASS** | `test_health_check_reports_storage_failure` |
| TC-037 | Use mocked Gemini response with allowed category, unsupported category, malformed/incomplete content, low confidence, and explicit review | Require structured JSON and local validation; route only allowed, confident, approved classifications | All mocked provider behavior assertions passed; **PASS** | `test_gemini_sdk_success_uses_closed_set_and_routes`; `test_gemini_unsupported_category_is_held_for_review`; `test_gemini_malformed_or_incomplete_response_is_held_for_review`; `test_gemini_model_can_request_review_even_when_score_is_high`; `test_gemini_low_confidence_is_reviewed_without_execution` |
| TC-038 | Mock Gemini request, usage metadata, checker correction, rate limit, timeout, auth/outage, and SDK lifecycle | Preserve only reported usage, use timeout, close owned client, map provider errors safely, never fallback | Mock-based provider assertions passed; **PASS** | `test_gemini_sdk_request_uses_closed_set_json_schema_and_parses_response`; `test_gemini_records_only_provider_reported_token_usage`; `test_gemini_retry_uses_checker_feedback_as_correction_context`; `test_missing_gemini_key_fails_without_fallback`; `test_sdk_client_receives_timeout_in_milliseconds_and_is_closed`; `test_gemini_invalid_json_or_missing_fields_rejected`; `test_gemini_sdk_rate_limit_is_mapped_to_safe_error`; `test_gemini_provider_failures_are_classified_safely` |

## 3. Coverage summary

| Area | Verified behavior |
|---|---|
| Closed-set classification | Six supported labels, `UNKNOWN`, parsing, schema, confidence, override detection |
| Routing/execution safety | Deterministic map, unsupported rejection, canonical review approval, local registry restriction |
| Orchestration | Actual stage ordering, trace persistence, current running state, checker feedback, bounded retries |
| Human review | Approve/reject/clarify, pending-state requirement, route consistency, no `UNKNOWN` execution |
| Persistence and dashboard | SQLite history, execution metrics, filters, empty database, review queue, activity APIs |
| Evaluation | Versioned dataset, `UNKNOWN` scoring, isolated history/store, report API, JSON/CSV output |
| Provider handling | Gemini schema/parsing/errors/token usage behavior tested with mocks only |
| Robustness checks | The saved 222-case evaluation report records empty/oversized/malformed input, invalid category, malformed classifier, provider timeout, repeated/concurrent requests, execution failure, and database failure probes |

## 4. Test limitations

- Tests use local deterministic classifiers and mocked provider SDK objects; they do not establish behavior against a live Gemini service.
- The automated suite is not a penetration test, load test, accessibility audit, or production deployment verification.
- Concurrency checks are small in-process probes, not a capacity benchmark.
- The evaluation robustness section is the recorded output of the evaluation runner; it is not a substitute for tests against real external services.
