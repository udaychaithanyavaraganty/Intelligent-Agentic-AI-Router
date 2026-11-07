# Architecture and Technical Diagrams

This document describes the current source implementation, not a proposed production architecture. In particular, the project has no persistent agent memory, no external workflow integrations, and no autonomous agent service processes. The only optional external AI call is classification through the Gemini provider.

## Architecture summary

The browser uses same-origin HTTP requests to a Flask application. Flask validates and persists a request before handing it to `AgentOrchestrator`. The orchestrator calls the configured classifier, validation logic, deterministic route selector, registered workflow function, checker, and review logic. `HistoryService` persists operational request and agent-execution records in the application SQLite database. Evaluation runs use temporary request databases and a separate evaluation database. The browser never connects to SQLite directly.

Agent names identify instrumented application stages, not independently deployed models. The checker uses deterministic code checks. Agent status shown by the dashboard is sourced from `agent_executions`; the dashboard polls API endpoints rather than receiving SSE or WebSocket events.

## Diagram index

| Diagram | Source |
|---|---|
| High-level system architecture | [`diagrams/high_level_architecture.mmd`](diagrams/high_level_architecture.mmd) |
| Multi-agent architecture | [`diagrams/multi_agent_architecture.mmd`](diagrams/multi_agent_architecture.mmd) |
| Agent interaction/data handoff | [`diagrams/agent_interaction.mmd`](diagrams/agent_interaction.mmd) |
| Data-flow diagram, Level 0 | [`diagrams/data_flow_level_0.mmd`](diagrams/data_flow_level_0.mmd) |
| Data-flow diagram, Level 1 | [`diagrams/data_flow_level_1.mmd`](diagrams/data_flow_level_1.mmd) |
| UML use-case-style diagram | [`diagrams/uml_use_case.mmd`](diagrams/uml_use_case.mmd) |
| UML class diagram | [`diagrams/uml_class.mmd`](diagrams/uml_class.mmd) |
| UML sequence diagram | [`diagrams/uml_sequence.mmd`](diagrams/uml_sequence.mmd) |
| Activity diagram | [`diagrams/activity.mmd`](diagrams/activity.mmd) |
| Database ER diagram | [`diagrams/database_erd.mmd`](diagrams/database_erd.mmd) |
| Request-processing flowchart | [`diagrams/request_flowchart.mmd`](diagrams/request_flowchart.mmd) |

The `.mmd` files contain Mermaid source and can be rendered by a Markdown viewer that supports Mermaid. The diagrams deliberately show data stores as separate: ordinary request history is not used as the evaluation run/case store.

## Backend component map

| Module | Responsibility |
|---|---|
| `backend/app.py` | Creates the Flask app, validates app configuration, wires services and classifier, exposes dashboard, request, review, trace, health, history, analytics, and evaluation endpoints |
| `backend/agents/orchestrator_agent.py` | Coordinates actual stage calls, request context, trace lifecycle, bounded classification correction, and review-time execution |
| `backend/agents/classification_agent.py` | Defines classifier protocol, category loading, demo rules, strict response parsing, and routing-override detection |
| `backend/services/llm_service.py` | Creates the demo/Gemini provider; validates and records only provider-returned usage metadata |
| `backend/agents/validation_agent.py` | Enforces closed-set, confidence, schema-adjacent, and review policy checks |
| `backend/agents/routing_agent.py` | Selects the configured workflow after category and route cross-checks |
| `backend/agents/execution_agent.py` | Invokes only the local `WORKFLOWS` registry |
| `backend/agents/checker_agent.py` | Deterministically checks classification, validation, route, result, and review transitions |
| `backend/agents/review_agent.py` | Allows approve/reject/clarify only from the pending-review state |
| `backend/services/history_service.py` | Creates operational SQLite tables, request records, execution traces, stats, history filters, and analytics |
| `backend/services/evaluation_store.py` | Persists run summaries and cases separately, retrieves reports, and creates CSV exports |
| `backend/evaluation.py`, `backend/evaluate.py` | Loads and fingerprints the benchmark, executes isolated evaluations and robustness checks, calculates metrics, and writes reports |
| `backend/workflows/__init__.py` | Registers six response-only example handlers |

## Request data contracts

The classifier returns a structured mapping containing `category`, `confidence`, `explanation`, `requires_review`, and optional object-valued `metadata`. Validation produces a `ValidationResult(valid, needs_review, reason)`. Routing produces a workflow identifier from the configuration. Execution produces a mapping with a non-empty `message` and a request summary. Checker calls return `CheckResult(passed, feedback, retryable)`. These values are passed as inputs and outputs to stage wrappers, which persist trace events.

## Persistence model

The operational database has `requests` and `agent_executions` tables. `agent_executions.request_id` has a declared foreign-key relationship to `requests.id`, and events contain status, start/end timestamps, JSON input/output, error, checker feedback, and retry number. The history connection does not explicitly enable SQLite foreign-key enforcement, so referential integrity is not claimed to be enforced by SQLite at runtime.

The evaluation database has `evaluation_runs` and `evaluation_cases`. The run row stores an aggregate report without the per-case array; cases are stored by index and reassembled for downloads. Evaluation requests run through an isolated temporary history database, preventing benchmark cases from appearing as ordinary user history.

The `evaluation_cases.run_id` column has a foreign key to `evaluation_runs.run_id`; the evaluation store enables SQLite foreign-key enforcement. Evaluation cases are ordered by their run-local `case_index`.

## Security and failure boundaries

- The application checks request body shape and length before orchestration.
- A request record is committed before the classifier starts; a history database error returns `503` without invoking the classifier or workflow.
- Category identifiers and routes come from checked configuration. The model does not choose an executable function.
- `UNKNOWN`, malformed output, unsupported categories, and low-confidence/review decisions do not enter ordinary execution.
- Gemini output must parse as JSON and is still validated locally. Provider errors map to safe client messages; credentials are not returned to frontend routes.
- SQL query values are bound parameters; the dashboard escapes user-provided values when rendering HTML.
- Registered handlers do not perform external side effects.
- No authentication, reviewer identity, authorization, rate limiting, production CSRF defense, or production secret-management system is implemented.
- `/api/health` verifies that the operational and evaluation SQLite stores can be queried; it does not call the configured LLM provider.

## Mermaid render validation

The diagram sources are plain Mermaid text. No Mermaid renderer or PDF renderer is a project dependency in this environment, so this documentation does not claim that a rendered image or PDF was generated.
