# P18 Functional Audit Report

**Audit date:** 2026-11-06  
**Scope:** Project structure, Flask API, five agent modules, workflows, SQLite service, demo/Gemini provider integration, static frontend, configuration, and automated tests.

## Project structure and agent communication

- `backend/app.py` constructs the Flask application and orchestrates requests and reviews.
- `backend/agents/classification_agent.py` contains the closed-set demo classifier, category loader, and JSON response parser.
- `backend/agents/validation_agent.py` validates category, confidence, explanation, review flag, metadata, and confidence threshold.
- `backend/agents/routing_agent.py` resolves categories through the configured deterministic routing map.
- `backend/agents/execution_agent.py` invokes only names in the workflow registry in `backend/workflows/__init__.py`.
- `backend/agents/review_agent.py` enforces approval, rejection, and clarification state transitions.
- `backend/services/llm_service.py` adapts the demo provider or official Gemini SDK; the Gemini client is a classifier only and receives no workflow tools.
- `backend/services/history_service.py` persists request/review/execution records and aggregates metrics in SQLite.
- `backend/evaluate.py` evaluates the local labeled dataset; `backend/tests/` contains API, core decision, and Gemini adapter tests.
- `config/categories.json` and `config/routing_rules.json` hold category and route allowlists. `data/evaluation_dataset.json` is the demo evaluation set; `data/router.sqlite3` is local history.
- `frontend/index.html`, `frontend/css/style.css`, and `frontend/js/app.js` implement the same-origin dashboard. `README.md`, `.env.example`, `.gitignore`, `requirements.txt`, and this report document/configure the project.

**Request flow:** frontend → `/api/requests` → policy-override precheck → classifier → validation → deterministic routing → registered workflow if safe, otherwise SQLite review queue → dashboard/history. The review endpoint loads the stored record, checks the canonical route on approval, calls the review agent, and persists the resulting state.

## Component audit

| Component name | Current functionality | Test performed | Result | Issues identified / fixes implemented | Remaining limitations |
|---|---|---|---|---|---|
| Classification Agent and provider | Demo keyword classifier and Gemini JSON-schema classifier both output category, confidence, explanation, review flag, and metadata. Provider selection is explicit. | API tests cover each of the six supported categories and the UNKNOWN/ambiguous path. Core and mocked-SDK tests cover unsupported categories, malformed JSON, missing fields, confidence edge cases, provider failure mapping, and the schema enum. | **PASS** | Existing parsing and validation reject malformed structures and prevent unsupported categories from routing. No additional code change was required during this audit. | Demo mode is heuristic. No live Gemini request was made; model confidence is not calibrated. |
| Validation Agent | Checks category allowlist, finite numeric confidence in `[0, 1]`, nonempty explanation, metadata shape, review flag, and configured threshold. | Tests cover low confidence, explicit review, missing fields, invalid category/confidence, and invalid threshold settings. | **PASS** | Existing startup validation rejects non-finite/out-of-range thresholds; invalid classifier results are held for review without a workflow. | Confidence quality depends on the provider; low-confidence requests still need an authorized human decision. |
| Routing Agent | Maps only configured categories through `routing_rules.json` and checks the selected route against the category’s declared workflow. UNKNOWN maps to human review. | Repeated route selection, all six configured routes, UNKNOWN, arbitrary category, and mismatched routes are tested. | **PASS** | No route bypass was found; invalid route configuration fails closed. | The routes are static configuration and require coordinated edits to both JSON allowlists for new categories. |
| Execution Agent and workflows | Executes only names registered in the local workflow map. Handlers return explanatory demo responses and have no external side effects. | API tests invoke all supported workflow handlers; arbitrary workflow names and forced workflow failures are tested. | **PASS** | Invalid or unapproved requests do not execute. Failed execution is recorded and counted. No code change was required. | These handlers do not perform real analysis, account changes, or automation; production integrations need authorization and idempotency controls. |
| Review Agent | Supports approve, reject, and clarify transitions from `pending_review`; UNKNOWN or missing routes cannot be approved. API approval verifies the stored route against canonical configuration. | Tests cover approved low-confidence request, rejection, clarification, unknown approval denial, tampered route denial, and invalid review payload. | **PASS** | Invalid JSON-object review bodies return 400 and leave the pending record unchanged. | Clarification transitions to `awaiting_clarification`; this implementation has no follow-on endpoint to submit clarification and resume classification. Concurrent approval claiming is not atomic. |
| Flask API and configuration | Serves the frontend, health/dashboard/history, request submission, and review endpoints. Provider credentials remain server-side. | API tests cover input validation, routes, health/assets, provider/config errors, error responses, and sanitized failures. Browser test submits requests through the actual dashboard. | **PASS** | Non-object request/review bodies are rejected; provider, confidence threshold, and timeout are validated. No code change was required. | No reviewer authentication/authorization or rate limiting; do not expose the development server to a network without controls. |
| SQLite history and metrics | Persists requests, classification, validation, workflow, result, reviewer feedback, errors, timestamps, and latency; dashboard computes aggregate metrics and filters history. | Tests cover persistence across app recreation, completed/review/rejected states, failure/routing metrics, and search. Browser requests were visible in the dashboard history; the six exact records created by the browser audit were removed afterward. | **PASS** | Existing metrics distinguish failed requests from failed workflow executions and count only validation-passed requests as classified. | Request text has no retention policy. Metrics are local aggregates, not a production observability system. |
| Frontend | Same-origin HTML/CSS/JS dashboard displays provider mode, request outcome, review queue, history, and metrics. Dynamic user content is escaped. | Real browser flow verified successful category display, ambiguous UNKNOWN queued for review, rejection reflected in history, and HTML-like user content displayed as text with zero injected image elements. API tests also cover the override guard. | **PASS** | HTML-like input did not create an image element. No code change was required. | The UI communicates with the API but does not provide reviewer identity or access control. |
| Security, duplicate code, and dependencies | Workflow execution uses explicit category and handler allowlists. Direct dependencies are Flask, `google-genai`, and `python-dotenv`; `pytest` is used for tests and is listed in the shared requirements file. | A separate security review examined API, agents, LLM integration, SQLite, workflow execution, frontend rendering, and configuration. Python imports were compared with direct requirements; source search checked for duplicate helpers and unsafe execution patterns. | **PASS** | Security review reported no exploitable vulnerabilities in the reviewed areas. No significant duplicate implementation or unused direct dependency was identified. | Request text is stored locally. The API has no authentication/rate limiting; review concurrency needs hardening before side-effecting workflows are introduced. |

## Automated verification

- `python -m pytest -q`: **68 passed**.
- `python -m backend.evaluate`: 15 demo-labeled examples; accuracy **1.00**, macro precision/recall/F1 **1.00**, confidence range **0.00–0.82**, review rate **0.20**, ECE **0.3307**.
- `python -m compileall -q backend`: passed.
- `node --check frontend/js/app.js`: passed.
- Browser smoke flow through the dashboard: supported request completed, ambiguous request entered review and was rejected, and HTML-like input rendered safely. Six exact rows created by these browser checks were removed; pre-existing rows were left untouched.

Evaluation metrics above describe only the small checked-in hand-curated dataset and keyword demo classifier; they are not production accuracy claims. The Gemini adapter and error paths were tested with a mocked SDK client. `python -m backend.evaluate --provider gemini` and any live Gemini call were not run.

## Security review findings

No exploitable vulnerabilities were reported in the reviewed code. The application's default development binding is `127.0.0.1`; authentication, authorization, rate limiting, data retention, and atomic review claims remain deployment concerns rather than verified protections.

## Overall conclusion and limitations

The current automated tests and the tested browser flow pass. During this audit, no source changes were necessary: the inspected implementation already has the guards exercised by the tests. This does not constitute a live Gemini/provider test or production-readiness assessment. Remaining material limits are heuristic demo classification, non-side-effecting demo workflows, small evaluation data, non-atomic approval handling, unavailable clarification continuation, and absent API authentication/rate limiting/retention controls.

The project directory has no Git metadata, so no change diff or commit history was available.