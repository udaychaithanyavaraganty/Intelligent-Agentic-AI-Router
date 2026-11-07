# INTELLIGENT AGENTIC AI ROUTER
## P18 — Closed-Set Classification and Deterministic Workflow Routing

### Academic Project Report

**Project domain:** Agentic AI, natural-language classification, workflow control  
**Report date:** 6 November 2026  
**Student:** [Enter student name]  
**Institution / Department:** [Enter institution and department]  
**Supervisor:** [Enter supervisor name]  
**Project status:** Local demonstrator; not a production service

---

## Abstract

The Intelligent Agentic AI Router is a local web application for classifying natural-language requests into a fixed set of intent categories and selecting a predefined workflow through deterministic rules. Its design separates classification from validation and routing: an optional language-model provider can suggest a category, but application code checks the category, confidence, and review flags before it can select or execute a route. A central orchestrator coordinates classification, validation, routing, execution, review, and checker components. It records actual stage inputs, outputs, outcomes, errors, timestamps, and retry attempts in SQLite. Ambiguous, unsupported, low-confidence, and policy-override requests are held for human review rather than automatically executed.

The application includes a responsive browser dashboard, a Flask JSON API, an operational history database, and a separate repeatable benchmark store. The saved version 2.0.0 benchmark contains 222 cases expanded from 37 locally authored labeled prompts. In the recorded `demo` run, classification accuracy and macro-F1 were both 1.0; the six configured supported categories each had 30 examples, and `UNKNOWN` had 42. The measured result describes the local keyword-based mock classifier on this fixed, locally authored benchmark only. It is not a real-LLM result, a representative production estimate, or evidence of production readiness. No Gemini evaluation was run.

The system provides no persistent agent memory, retrieval, self-reflection, external business-system integration, authentication, or role-based access control. Its registered workflows return demonstration guidance and do not modify external systems. This report documents the implementation and its measured limitations.

**Keywords:** closed-set classification, deterministic routing, agent orchestration, human-in-the-loop, SQLite, evaluation, workflow safety

## 1. Introduction

Natural-language interfaces make it convenient to express requests but do not, by themselves, provide a safe mechanism for deciding which application action should run. A system that lets a generative model directly select tools or execute arbitrary operations can blur the boundary between understanding a request and authorizing an action.

P18 addresses this control problem with a small, auditable pipeline. Classification proposes one label from a configured allowlist. Validation applies application-owned checks. Routing uses a fixed category-to-workflow mapping. Execution resolves a selected workflow through a local registry. Requests that do not pass the decision gates are placed in a human-review state. SQLite records the decision and agent trace so that the dashboard can present the actual processing history.

The implementation is a demonstration and evaluation platform. Its six workflow handlers intentionally return explanatory text; they are not integrations with account, file, network, or automation services.

## 2. Problem Statement

An unconstrained natural-language router can misinterpret ambiguous input, invent a category, select an unintended workflow, or treat adversarial text as policy. Without a persisted trace, it is also difficult to explain why an action was accepted, rejected, retried, or escalated.

The project therefore asks: **How can a request be classified into a finite intent set and routed through approved workflows while preserving validation, review, traceability, and measurable behavior?**

## 3. Objectives

1. Define a finite, configurable category vocabulary that includes an explicit `UNKNOWN` outcome.
2. Keep category validation and workflow selection under application control.
3. Ensure only registered workflow handlers can execute.
4. Escalate uncertain or unsafe decisions to a human instead of silently routing them.
5. Coordinate specialized processing stages through structured data and a shared per-request context.
6. Record request history, agent events, checker feedback, and review decisions in SQLite.
7. Present operational history, analytics, agent activity, and stored benchmark results in a dashboard.
8. Provide repeatable evaluation with sample sizes, per-class metrics, safety probes, latency, and limitations.

## 4. Existing System and Proposed System

### 4.1 Existing-system baseline

For comparison, a conventional baseline is a direct classifier-to-action design in which one prediction is treated as sufficient authority to execute an action. This is a conceptual baseline only; this project does not include a separately implemented or experimentally measured baseline. No performance comparison against such a system is claimed.

### 4.2 Proposed P18 system

P18 introduces explicit decision boundaries:

- The classifier can return only configured identifiers in real Gemini mode; the application also validates responses.
- `UNKNOWN`, unsupported categories, malformed outputs, and low-confidence decisions do not proceed to normal execution.
- The validator runs before the routing component.
- The deterministic router verifies its result against both the configured route map and the category configuration.
- The execution component uses a local workflow registry, not model-generated code or tool names.
- Checker results and retry feedback are recorded; classification/validation recovery is bounded to two attempts total.
- Execution failures are recorded and are not automatically retried.
- Human approval, rejection, and clarification are represented as explicit state transitions.

## 5. Literature Review

Xiong et al. describe ResilioMate as a resilient multi-agent task-executing framework for enhancing small language models [1]. The title and bibliographic record establish a relevant research direction: combining specialized agent roles and resilience mechanisms around language-model capabilities. P18 adopts a narrower engineering pattern: a classifier proposes intent, application code validates it, and a checker reviews selected decisions. P18 does not reproduce ResilioMate, its experiments, or its reported findings.

The Autonomy Ladder Project Catalogue identifies this project as P18, “Closed-Set Classification and Deterministic Workflow Routing” [2]. The entry motivates the bounded-routing scope. The catalogue document, edition, publisher, and page number were not present in the workspace; those fields are intentionally not guessed.

In this implementation, reliability is supported by explicit contracts and persisted traces rather than by a claim that multiple agents inherently make a system reliable. The benchmark further separates class-quality measurements from escalation behavior and routing safety.

## 6. Research Gap

The project targets the gap between flexible language understanding and constrained application actions. A classifier can help interpret user intent, while a deterministic allowlist and explicit review gate keep the final workflow decision auditable. The contribution is a small working implementation and repeatable test/evaluation path, not a new classification algorithm or an empirical comparison with an unconstrained agent.

## 7. System Requirements

### 7.1 Functional requirements

- Accept a non-empty text request of at most 4,000 characters.
- Classify requests into one of six supported categories or `UNKNOWN`.
- Check structure, allowlist membership, finite confidence in `[0, 1]`, explanation, and review requirements.
- Use a configurable default confidence threshold of `0.65`.
- Select a workflow only from the deterministic map in `config/routing_rules.json`.
- Run only a workflow registered in `backend/workflows/__init__.py`.
- Queue review-required requests without automatic execution.
- Support human `approve`, `reject`, and `clarify` decisions.
- Persist requests and actual agent execution events in SQLite.
- Expose operational and evaluation data through HTTP JSON endpoints.
- Generate JSON and CSV evaluation reports in an evaluation-only store.

### 7.2 Non-functional requirements and observed limits

- **Auditability:** request records and agent traces have separate relational tables.
- **Bounded recovery:** at most two classification/validation attempts; workflow execution is not automatically retried.
- **Local operation:** Flask serves the dashboard and API from one origin; default bind is `127.0.0.1`.
- **Provider transparency:** `demo` and `gemini` are distinct modes; a missing Gemini key is an error, not a silent fallback.
- **Security scope:** request length and review-feedback size are bounded, SQL values are parameterized, and model-generated workflow names are not executed. Authentication, authorization, rate limiting, and production deployment controls are not implemented.

## 8. Technology Stack

| Layer | Implemented technology |
|---|---|
| Backend | Python, Flask |
| Optional language model | Google Gemini Developer API through `google-genai` |
| Local classification mode | Deterministic regular-expression demo classifier |
| Persistence | SQLite |
| Frontend | HTML, CSS, vanilla JavaScript |
| Evaluation | Python evaluation runner, JSON dataset, SQLite results, JSON/CSV snapshots |
| Tests | pytest |
| Configuration | JSON configuration files, environment variables, `.env` loading |

Dependency ranges are listed in [`requirements.txt`](requirements.txt). The project does not use a frontend framework, a separate queue service, a vector database, or an external workflow engine.

## 9. System Architecture

The Flask application serves static frontend assets and JSON API routes. Requests are persisted before orchestration starts. The orchestrator calls the configured classifier, validator, deterministic router, registered executor, checker, and review logic. The operational history service stores request and execution records; the evaluation store uses a separate database. The dashboard reads these APIs and displays stored facts. Mermaid diagrams and their source files are indexed in [`ARCHITECTURE.md`](ARCHITECTURE.md) and [`diagrams/`](diagrams/).

## 10. Detailed Methodology

1. **Input gate:** `POST /api/requests` requires a JSON object with a non-empty string `request`; strings longer than 4,000 characters are rejected.
2. **Durable intake:** the application creates a `processing` request record. If SQLite cannot save it, the API returns `503` before creating an orchestrator or calling a classifier.
3. **Classification:** the orchestrator calls `DemoClassifier` or `GeminiClassifier`. A routing-policy override pattern is handled locally as `UNKNOWN` before a provider call.
4. **Classification check:** the checker verifies the returned object and required classification fields.
5. **Validation:** the validator checks allowlist membership, finite bounded confidence, explanation, review flag, `UNKNOWN`, and the configured threshold.
6. **Validation check:** the checker independently verifies the decision invariants. Retryable classification/validation errors may produce a corrected second attempt using checker feedback.
7. **Escalation or route:** a valid known category requiring no review is mapped to its single configured workflow. An `UNKNOWN` category or other review-required classification receives no normal workflow.
8. **Route check:** the checker compares the chosen workflow to the category's configured canonical workflow.
9. **Execution:** the executor resolves the workflow in `WORKFLOWS`; each current handler returns a structured demonstration message.
10. **Execution check:** the checker requires a non-empty message in the execution result. A failed execution is traced and is not automatically retried.
11. **Human review:** a pending record can be approved, rejected, or clarified. Approval is restricted to a known supported category with its canonical registered workflow; `UNKNOWN` cannot be approved for automatic execution.
12. **Response and dashboard:** the API returns the record and trace; dashboard polling reads persisted history and activity.

## 11. Agent Architecture

| Component | Responsibility and implementation |
|---|---|
| Classification Agent | Calls the selected classifier and returns category, confidence, explanation, review flag, and metadata. |
| Validation Agent | Calls `validate_classification`; checks closed-set membership and review policy. |
| Routing Agent | Calls `select_workflow`; maps only a configured category to its canonical route. |
| Execution Agent | Resolves a route through the static `WORKFLOWS` registry. It does not interpret or execute model-generated code. |
| Checker Agent | Checks classification structure, validation consistency, routing, execution output, and review-state transitions. |
| Review Agent | Applies `approve`, `reject`, or `clarify` to pending requests and records reviewer feedback. |
| Agent Orchestrator | Passes structured data between components, maintains request context, bounds retries, and starts/finishes persisted trace events. |

These are cooperating application components, not independent autonomous services. The classifier is the only stage that may make an external model call. Every persisted activity row is created around an actual backend operation or checker invocation.

## 12. Classification Mechanism

The configured label set is defined in [`config/categories.json`](config/categories.json):

`TECHNICAL_SUPPORT`, `GENERAL_INFORMATION`, `DATA_ANALYSIS`, `SOFTWARE_DEVELOPMENT`, `ACCOUNT_MANAGEMENT`, `TASK_AUTOMATION`, and `UNKNOWN`.

The default `demo` provider uses fixed keyword regular expressions and returns confidence `0.82` for exactly one matched supported category. Zero or multiple matches return `UNKNOWN` and request review. Routing-override text is conservatively classified as `UNKNOWN`.

The optional Gemini provider is configured with the identifiers and descriptions from the same category file, a JSON response schema, temperature `0`, a maximum output size, and a timeout. The response is parsed as JSON and is still validated locally. Model confidence is treated as an estimate, not a calibrated probability. Provider errors are converted to safe error responses; selecting Gemini without credentials fails rather than falling back.

## 13. Validation Mechanism

`validate_classification` rejects a category not in the configured map, invalid or non-finite confidence, malformed explanation/metadata, or a non-boolean review flag. `UNKNOWN`, an explicit model review request, and confidence below the configured threshold produce a valid-but-review-required result. With the default threshold, the normal known-intent path requires confidence at least `0.65` and no review flag.

Validation is an application control, not a model instruction. A validation failure or provider parse failure cannot authorize a route.

## 14. Deterministic Routing

The workflow mapping is held in [`config/routing_rules.json`](config/routing_rules.json) and cross-checked against the workflow property in `categories.json`. `select_workflow` raises an error for an unsupported category and maps `UNKNOWN` to the human-review marker rather than an executable registry entry. All six executable workflows have local registered handlers. The checker verifies the route against the expected mapping before execution.

## 15. Multi-Agent Collaboration and Execution Trace

The orchestrator uses a per-request context containing request ID, original request, classification, validation decision, and later route/execution outcome. Each actual operation is recorded in `agent_executions` with agent name, running/completed/failed status, UTC start and completion timestamps, JSON inputs/outputs, error, checker feedback, and retry number.

The maximum classification loop is two attempts total. Checker feedback is passed to the classifier only when it supports a feedback method. Successful benchmark cases have no retries; the controlled evaluation fault probe separately verifies one checker-detected malformed response and successful retry. Workflow execution failures are recorded and not automatically repeated.

## 16. Memory and Self-Reflection

Persistent short-term memory, long-term memory, retrieval, reflection reports, and stored corrective strategies are **not implemented**. Checker feedback is request-scoped and the trace may persist that feedback for audit; this is not cross-request learning or a memory subsystem. The dashboard explicitly reports memory as unavailable. Evaluation does not claim a memory comparison.

## 17. Human-in-the-Loop Mechanism

The dashboard lists requests whose status is `pending_review` or `awaiting_clarification`. A reviewer may approve, reject, or ask for clarification, with optional feedback capped at 1,000 characters. Approval requires a supported, non-`UNKNOWN` category and a stored route matching the configured route. Rejection and clarification do not call a workflow. Review transitions and any approval-time execution are recorded by the review and checker agents.

The current application has no login or reviewer identity/role system. Human review is a functional workflow gate, not a production identity or authorization solution.

## 18. Database Design

The operational database contains:

- **`requests`** — request text, predicted category/confidence, explanation, JSON metadata, validation status/reason, workflow, request status, result/error, reviewer feedback, creation time, and end-to-end latency.
- **`agent_executions`** — foreign-key-linked agent events with status, timestamps, JSON inputs/outputs, error, checker feedback, and retry attempt.

Indexes support request time/category/status and request/agent trace lookup. The separate evaluation database contains:

- **`evaluation_runs`** — run/provider/model, dataset identity/version/hash/sample count, timestamp, and metrics/configuration report JSON.
- **`evaluation_cases`** — one JSON record per case, keyed by run and case index.

Benchmark request traces use temporary request-history databases. Evaluation cases and run summaries do not enter ordinary request history. The schema diagram is [`diagrams/database_erd.mmd`](diagrams/database_erd.mmd).

## 19. Implementation and Dashboard

The frontend is a static HTML document with CSS and vanilla JavaScript. It uses same-origin `fetch` calls to Flask, checks HTTP errors, renders request text with escaping/text APIs, and refreshes persisted dashboard/agent data. It includes overview KPIs, request submission, status timeline, operational charts, review queue, search/filterable history, evaluation-run selection/downloads, theme switching, and a system-health area.

Operational charts and KPIs are derived from saved request and agent-execution records. Evaluation metrics come from saved evaluation runs. The Memory section reports that the feature is not configured rather than displaying synthetic records. Live monitoring is polling of backend state; it is not an event stream or WebSocket.

## 20. API, Error Handling, and Security

The API is documented in [`API_DOCUMENTATION.md`](API_DOCUMENTATION.md). Important implemented controls include:

- request and review input validation and length caps;
- strict structured classifier parsing and configured category validation;
- local route map and workflow registry;
- no workflow execution before validation and route checking;
- no execution for `UNKNOWN`;
- parameterized SQL for user-supplied query values;
- sanitized provider/application errors and server-side logging;
- creation of a durable request record before orchestration;
- no credentials sent to the browser.

The application binds to loopback by default. There is no authentication, role-based authorization, rate limiter, deployment-grade CSRF defense, or encryption layer in this project. The demonstration workflows have no external side effects. These conditions must be addressed before exposing the service to untrusted users or connecting real actions.

## 21. Testing Methodology and Results

Tests use pytest and isolated temporary SQLite databases, and mock the Gemini SDK rather than calling a paid provider. The full command `python -m pytest -q` completed with **89 passed**. Python compilation (`python -m compileall -q backend`) and frontend syntax validation (`node --check frontend\js\app.js`) also passed in the documented validation session.

Coverage includes supported and unknown categories, routing invariants, confidence and schema validation, malformed JSON, provider failures, review decisions, trace/retry behavior, execution failures, database-write failures, operational analytics/filters, empty-database behavior, dataset metrics, separated evaluation persistence, downloads, and mocked Gemini behavior. [`TESTING_REPORT.md`](TESTING_REPORT.md) lists test IDs, conditions, expectations, observed results, and source test names.

## 22. Evaluation and Results

The latest saved run is `101d139d-fe97-4dbd-adb9-f34c54f75657`, provider `demo`, dataset version `2.0.0`, SHA-256 `dc3202a29c3bb0193d7c3226644d0d82ef826b15ba2c1119670cef577e431b37`. It contains 222 cases: 30 per supported category and 42 `UNKNOWN`.

| Measurement | Recorded result |
|---|---:|
| Accuracy | 1.000 |
| Macro precision / recall / F1 | 1.000 / 1.000 / 1.000 |
| Weighted F1 | 1.000 |
| Supported-category workflow selection | 180/180 (1.000) |
| Workflow execution success | 180/180 (1.000) |
| `UNKNOWN` escalation recall | 42/42 (1.000) |
| Adversarial examples prevented from execution | 12/12 (1.000) |
| Agent invocations completed | 1,608/1,608 (1.000) |
| Average / median / P95 request response | 153.307 / 165.079 / 173.286 ms |
| Average / median / P95 classification span | 7.985 / 7.998 / 9.082 ms |
| Average / median / P95 agent span | 8.551 / 8.602 / 10.001 ms |

The run is a mock-provider benchmark, not a real Gemini evaluation. Its locally authored keyword-oriented prompts and deterministic context variants are limited and not representative of production traffic. The controlled checker-retry probe is a single fault-injection demonstration, not a population reliability estimate. Token usage is unavailable for this demo run; API cost is null because verified pricing is not configured. See the complete matrix and caveats in [`EVALUATION_REPORT.md`](EVALUATION_REPORT.md).

## 23. Limitations

1. The demo provider is a small keyword-pattern classifier, not a semantic language model.
2. Only one fixed 222-case local benchmark has a saved final demo run; its perfect score is not a real-world estimate.
3. No real-provider benchmark has been run or reported.
4. Registered workflows are response-only demonstrations, not business actions.
5. Persistent memory, retrieval, and self-reflection are absent.
6. The service has no authentication, reviewer identity, authorization policy, or rate limiting.
7. SQLite and the local Flask server are appropriate for the demonstrator, not an asserted production scale.
8. The checker uses deterministic code checks; it is not an independent LLM verifier.
9. The P18 catalogue entry's full bibliographic metadata was unavailable.

## 24. Future Scope

Future work could add authenticated reviewer identities and role checks, rate limits, deployment-grade secret management, observability and retention policies, verified external workflow integrations with least privilege, stronger representative and independently labeled test data, repeated real-provider runs with cost controls, and a separately designed memory/retrieval evaluation. These are recommendations only; none is documented as already implemented.

## 25. Conclusion

P18 demonstrates an auditable request-routing pipeline in which language classification is separated from validation and deterministic execution. The code enforces a finite label set, fixed routes, an execution registry, human escalation, bounded correction attempts, and persisted request/agent histories. The dashboard and offline evaluation framework expose observed operational and benchmark data. The measured results show that the demo implementation behaves consistently on its fixed dataset and safety probes; they do not establish production accuracy, production security, or the performance of a real LLM provider.

## References

[1] Y. Xiong, M. Huang, X. Liang, and M. Tao, “ResilioMate: A Resilient Multi-Agent Task Executing Framework for Enhancing Small Language Models,” *IEEE Access*, vol. 13, pp. 86892–86911, 2025, doi: [10.1109/ACCESS.2025.3567244](https://doi.org/10.1109/ACCESS.2025.3567244). Bibliographic metadata was checked against the DOI record. This report does not claim to reproduce the paper's experiments.

[2] *Autonomy Ladder Project Catalogue*, entry P18, “Closed-Set Classification and Deterministic Workflow Routing.” User-supplied project title/entry reference; catalogue edition, author, publisher, date, and page were not available in the workspace and are not asserted.

## Appendix A. Source-code map

| Source | Documented role |
|---|---|
| `backend/app.py` | Flask application factory, API routes, input gates, service wiring, and error responses |
| `backend/agents/orchestrator_agent.py` | Shared per-request coordination, tracing, checker calls, and bounded classification retries |
| `backend/agents/classification_agent.py` | Demo classifier, category loader, response parser, routing-override detector |
| `backend/agents/validation_agent.py` | Closed-set and confidence/review validation |
| `backend/agents/routing_agent.py` | Deterministic category-to-workflow selection |
| `backend/agents/execution_agent.py` | Registered workflow lookup and invocation |
| `backend/agents/checker_agent.py` | Classification, validation, route, execution, and review checks |
| `backend/agents/review_agent.py` | Pending-review state transitions |
| `backend/services/llm_service.py` | Gemini adapter, provider errors, and provider-reported usage metadata |
| `backend/services/history_service.py` | Operational SQLite schema, request history, traces, statistics, and analytics |
| `backend/services/evaluation_store.py` | Isolated evaluation run/case persistence and CSV export |
| `backend/evaluation.py`, `backend/evaluate.py` | Benchmark, robustness probes, metrics, and repeatable CLI |
| `backend/workflows/__init__.py` | Safe response-only workflow registry |
| `frontend/` | Static dashboard HTML, CSS, and JavaScript |
| `config/`, `data/` | Categories, route map, versioned dataset, and generated evaluation data |
