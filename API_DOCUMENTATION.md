# HTTP API Documentation

The Flask application serves the dashboard and API from one origin. The default local address is `http://127.0.0.1:5000`. Responses are JSON unless an endpoint explicitly returns a CSV file. No authentication or authorization mechanism is implemented; do not expose this service to untrusted networks.

## Conventions

- Request bodies use `Content-Type: application/json`.
- Request IDs are integer SQLite primary keys.
- Evaluation run IDs are UUID strings.
- Timestamps are ISO-8601 strings; agent trace timestamps are generated in UTC.
- Error responses have the shape `{"error": "..."}` unless noted.
- The default confidence threshold is `0.65`.

## Endpoint index

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/` | Serve the dashboard |
| `GET` | `/assets/<path:filename>` | Serve frontend assets |
| `GET` | `/api/health` | Report application/provider mode |
| `GET` | `/api/dashboard` | Return dashboard KPIs, filtered history, review queue, categories, and provider config |
| `GET` | `/api/analytics` | Return database-derived charts and metrics |
| `POST` | `/api/requests` | Validate, persist, classify, validate, route/review, and return a request |
| `GET` | `/api/requests/<request_id>/trace` | Return one request and its persisted agent trace |
| `GET` | `/api/agent-activity` | Return the latest persisted trace or `null` |
| `POST` | `/api/reviews/<request_id>` | Approve, reject, or clarify a pending request |
| `GET` | `/api/history` | Return filtered request history |
| `GET` | `/api/evaluations` | List stored evaluation run summaries |
| `GET` | `/api/evaluations/<run_id>` | Return one report summary without per-case data |
| `GET` | `/api/evaluations/<run_id>/download?format=json` | Download full report including per-case data |
| `GET` | `/api/evaluations/<run_id>/download?format=csv` | Download per-case CSV |

## Health

### `GET /api/health`

Example:

```json
{
  "status": "ok",
  "provider": "demo",
  "mode": "demo",
  "model": null,
  "storage": "ok"
}
```

`provider` is either `demo` or `gemini`. The model field is populated only in real Gemini mode. The endpoint checks that operational and evaluation SQLite tables can be queried; storage failure returns HTTP `503` and `"storage":"unavailable"`. It does not call Gemini, so an `ok` status is not a provider availability check.

## Submit a request

### `POST /api/requests`

Request:

```json
{
  "request": "My printer is not working after the latest update."
}
```

The body must be a JSON object; `request` must be a non-empty string after trimming and no longer than 4,000 characters. The application stores a request record before starting classification.

Successful requests return `201 Created` with the persisted request fields and additional decision/trace fields. Example fields:

```json
{
  "id": 41,
  "request_text": "My printer is not working after the latest update.",
  "category": "TECHNICAL_SUPPORT",
  "confidence": 0.82,
  "explanation": "Matched the local demo intent pattern for technical support.",
  "metadata": {
    "provider": "demo",
    "matched_categories": ["TECHNICAL_SUPPORT"],
    "requires_review": false,
    "mode": "demo"
  },
  "validation_status": "passed",
  "validation_reason": "Classification passed closed-set and confidence validation.",
  "workflow": "technical_support",
  "status": "completed",
  "result": {
    "message": "Technical support workflow completed. This demonstration provides a response only; it does not change external systems.",
    "request_summary": "My printer is not working after the latest update."
  },
  "requires_review": false,
  "agent_trace": [
    {
      "agent": "classification_agent",
      "status": "completed",
      "retry_attempt": 1,
      "inputs": {"request_text": "My printer is not working after the latest update."},
      "outputs": {"category": "TECHNICAL_SUPPORT", "confidence": 0.82},
      "error": null,
      "checker_feedback": null
    }
  ]
}
```

The trace shown is abbreviated for readability; an actual response includes event IDs and start/completion timestamps for each recorded stage. The six demo workflows return structured guidance and do not perform external operations.

Review-required classifications return `201` with a state such as `pending_review`, no normal executable workflow, and no execution-agent event. Provider transport/availability failures return safe errors and do not route.

Common errors:

| Status | Condition |
|---:|---|
| `400` | Body is malformed/non-object, request is empty/whitespace, or request exceeds 4,000 characters |
| `429` | Gemini provider rate limit |
| `502` | Provider or general processing failure |
| `503` | Request storage unavailable before classification or provider temporarily unavailable |
| `504` | Gemini provider timeout |

Selecting Gemini without an API key prevents application startup; provider authentication errors during a request return a safe provider error.

SQLite creation failure returns `503` with the message that no workflow was executed. Provider errors are sanitized; detailed exception information is logged server-side.

## Request trace and live activity

### `GET /api/requests/<request_id>/trace`

Returns:

```json
{
  "request_id": 41,
  "status": "completed",
  "workflow": "technical_support",
  "trace": [
    {
      "id": 1,
      "request_id": 41,
      "agent": "classification_agent",
      "status": "completed",
      "started_at": "2026-11-06T17:50:00+00:00",
      "completed_at": "2026-11-06T17:50:00+00:00",
      "inputs": {"request_text": "My printer is not working after the latest update."},
      "outputs": {"category": "TECHNICAL_SUPPORT"},
      "error": null,
      "checker_feedback": null,
      "retry_attempt": 1
    }
  ]
}
```

The values above illustrate field names only; timestamp and result values are examples. A missing request returns `404`.

### `GET /api/agent-activity`

Returns the latest request with persisted agent events, preferring a request with an actively running event; returns JSON `null` when no activity exists. Activity is polled by the dashboard; no SSE/WebSocket stream is implemented.

## Human review

### `POST /api/reviews/<request_id>`

Request:

```json
{
  "action": "approve",
  "feedback": "Reviewed"
}
```

`action` must be `approve`, `reject`, or `clarify`. Feedback is converted to text and truncated to 1,000 characters. Only a pending-review record can be reviewed. Approval requires a supported category and a stored workflow matching its canonical configured route. `UNKNOWN` cannot be approved for automatic execution. Approval runs the registered workflow and is recorded in the agent trace; reject and clarify do not execute a workflow.

| Status | Meaning |
|---:|---|
| `200` | Review action accepted; updated record and trace returned |
| `400` | Invalid body/action, request not pending, or ineligible `UNKNOWN` approval |
| `404` | Request ID not found |
| `409` | Stored workflow conflicts with the configured canonical route |
| `500` | Approved workflow failed; failure is recorded |

## Dashboard and operational analytics

### `GET /api/dashboard`

Optional query parameters:

| Parameter | Meaning |
|---|---|
| `search` | Search request text, category, or workflow |
| `status` | Exact request status filter |
| `category` | Configured category ID; unsupported values return `400` |
| `from` | Inclusive ISO date, `YYYY-MM-DD` |
| `to` | Inclusive ISO date, `YYYY-MM-DD` |

The dashboard object contains:

- `stats`: total/classified/routed/review/failure counts and derived execution/latency rates;
- `history`: up to 200 filtered request records;
- `reviews`: records awaiting review or clarification;
- `categories`: configured category records;
- `provider`, `mode`, `model`, and `confidence_threshold`.

Malformed dates and a `from` date later than `to` return `400`. Search and status strings are treated as filter values; the server does not reject unknown status strings.

### `GET /api/analytics`

Accepts `from` and `to` date bounds. Returns `kpis`, `requests_over_time`, `category_distribution`, `confidence_distribution`, `execution_outcomes`, `human_reviews_over_time`, and `agent_latency`. Values are queried from operational SQLite records. The response includes `evaluation: null` and an explicit `memory.available: false`; evaluation runs are served separately.

### `GET /api/history`

Accepts the same `search`, `status`, `category`, `from`, and `to` filters as `/api/dashboard`. Returns a JSON array, limited by the API to 200 records. An empty match returns `[]`.

## Evaluation reports

### `GET /api/evaluations`

Returns `{"runs": [...]}` with up to 50 run summaries from the separate evaluation database. Each summary contains the run ID, timestamp, provider/model, dataset identity/hash/sample size, computed metrics, and limitations.

### `GET /api/evaluations/<run_id>`

Returns the stored aggregate report without the per-case array. A missing run returns `404`.

### `GET /api/evaluations/<run_id>/download`

`format` may be `json` (default) or `csv`.

- JSON includes configuration, metrics, robustness checks, limitations, and all stored per-case results.
- CSV contains one row per case. Text cells beginning with spreadsheet formula characters are prefixed to reduce CSV formula injection risk.
- Unknown run IDs return `404`; unsupported formats return `400`.

Evaluation runs are created by the CLI, not by an HTTP mutation endpoint. See [`README.md`](README.md) and [`EVALUATION_REPORT.md`](EVALUATION_REPORT.md).

## Filtering and state vocabulary

Request statuses observed in the application include `processing`, `completed`, `pending_review`, `awaiting_clarification`, `rejected`, and `failed`. Agent execution statuses include `running`, `completed`, and `failed`. Validation statuses include `processing`, `passed`, `review`, and `failed`. The checker also records a completed/failed trace event with a `passed` output flag; checker rejection does not authorize routing.

## Security notes

These are local demonstration APIs and have no identity/authentication layer. Do not rely on the dashboard's visible buttons as authorization. Before using real actions or exposing the server, add authentication, reviewer authorization, rate controls, deployment-grade CSRF and secret management, and operational monitoring.
