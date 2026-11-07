const byId = (id) => document.getElementById(id);
const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (character) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
}[character]));

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  let payload;
  try {
    payload = await response.json();
  } catch {
    throw new Error("The server returned an invalid response.");
  }
  if (!response.ok) throw new Error(payload.error || "The request could not be completed.");
  return payload;
}

let latestHistory = [];
let toastTimer;

function notify(message) {
  const toast = byId("toast");
  toast.textContent = message;
  toast.hidden = false;
  window.clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => { toast.hidden = true; }, 5000);
}

function showResult(record) {
  byId("latest-result").hidden = false;
  const category = record.category || "PROCESSING_ERROR";
  byId("result-category").textContent = category.replaceAll("_", " ");
  byId("result-request").textContent = `“${record.request_text || ""}”`;
  const confidence = Number(record.confidence || 0);
  byId("result-confidence").textContent = record.confidence == null ? "—" : `${Math.round(confidence * 100)}%`;
  byId("confidence-bar").style.width = `${Math.max(0, Math.min(100, confidence * 100))}%`;
  byId("result-workflow").textContent = record.workflow ? record.workflow.replaceAll("_", " ") : "Human review";
  byId("result-validation").textContent = record.validation_reason || record.validation_status || "Failed";
  byId("result-explanation").textContent = record.explanation || record.error || "No classification explanation available.";
  const result = typeof record.result === "string" ? (() => { try { return JSON.parse(record.result); } catch { return {}; } })() : record.result;
  byId("result-execution").textContent = result?.message || record.review_reason || "";
  const status = record.status || "failed";
  byId("result-status").textContent = status.replaceAll("_", " ").toUpperCase();
  byId("result-status").className = `status-pill ${["pending_review", "awaiting_clarification"].includes(status) ? "review" : ["failed", "rejected"].includes(status) ? status : ""}`;
}

function renderHistory(records) {
  latestHistory = records;
  const body = byId("history-body");
  if (!records.length) {
    body.innerHTML = '<tr><td colspan="7" class="empty-state">No requests match this view.</td></tr>';
    return;
  }
  body.innerHTML = records.map((record) => {
    const time = record.created_at ? new Date(record.created_at).toLocaleString() : "—";
    const confidence = record.confidence == null ? "—" : `${Math.round(record.confidence * 100)}%`;
    return `<tr><td class="request-cell" title="${escapeHtml(record.request_text)}">${escapeHtml(record.request_text)}</td><td>${escapeHtml((record.category || "—").replaceAll("_", " "))}</td><td class="mono-cell">${confidence}</td><td>${escapeHtml((record.workflow || "—").replaceAll("_", " "))}</td><td><span class="table-status ${escapeHtml(record.status)}">${escapeHtml(record.status.replaceAll("_", " "))}</span></td><td class="mono-cell">${escapeHtml(time)}</td><td><button class="detail-button" type="button" data-request-id="${record.id}">Inspect</button></td></tr>`;
  }).join("");
}

function renderReviews(records) {
  byId("nav-review-count").textContent = records.length;
  const container = byId("review-list");
  if (!records.length) {
    container.innerHTML = '<div class="empty-state">No requests waiting for review.</div>';
    return;
  }
  container.innerHTML = records.map((record) => `<article class="review-item" data-review-id="${record.id}">
    <div class="review-copy"><div class="review-meta"><span>#${record.id}</span><span>${escapeHtml(record.category || "UNKNOWN")}</span><span>${record.confidence == null ? "NO SCORE" : `${Math.round(record.confidence * 100)}% CONFIDENCE`}</span></div>
      <p>${escapeHtml(record.request_text)}</p><p class="review-reason">${escapeHtml(record.review_reason || "Manual decision required.")}</p></div>
    <div class="review-actions"><label class="sr-only" for="feedback-${record.id}">Reviewer feedback</label><input id="feedback-${record.id}" maxlength="1000" placeholder="Feedback / clarification"><button class="approve" data-action="approve" type="button" ${!record.workflow ? "disabled title='Unknown requests cannot be approved for execution'" : ""}>Approve</button><button data-action="clarify" type="button">Clarify</button><button class="reject" data-action="reject" type="button">Reject</button></div>
  </article>`).join("");
}

function renderStats(stats) {
  byId("stat-total").textContent = stats.total_requests;
  byId("stat-classified").textContent = stats.classified_requests;
  byId("stat-routed").textContent = stats.routed_requests;
  byId("stat-review").textContent = stats.human_review_requests;
  byId("stat-failed").textContent = stats.failed_executions;
  byId("stat-execution-time").textContent = `${stats.average_execution_ms ?? 0} ms`;
  byId("count-failed-executions").textContent = stats.failed_executions;
  const classifiedRate = Math.round(stats.classification_success_rate * 100);
  const routedRate = Math.round(stats.routing_success_rate * 100);
  byId("rate-classified").textContent = `${classifiedRate}%`;
  byId("rate-routed").textContent = `${routedRate}%`;
  byId("bar-classified").style.width = `${classifiedRate}%`;
  byId("bar-routed").style.width = `${routedRate}%`;
  const executionRate = Math.round(stats.workflow_execution_success_rate * 100);
  byId("rate-execution").textContent = `${executionRate}%`;
  byId("bar-execution").style.width = `${executionRate}%`;
  byId("rate-review").textContent = `${Math.round(stats.human_review_rate * 100)}%`;
  byId("avg-latency").textContent = `${stats.average_latency_ms} ms`;
  byId("health-review").textContent = stats.human_review_requests;
}

function renderAgentActivity(activity) {
  const timeline = byId("agent-timeline");
  renderAgentStatuses(activity);
  if (!activity || !activity.trace?.length) {
    byId("agent-current").textContent = "No agent execution recorded.";
    timeline.innerHTML = '<div class="empty-state">Agent execution details will appear here.</div>';
    return;
  }
  const trace = activity.trace;
  const active = trace.find((event) => event.status === "running");
  byId("agent-current").textContent = active
    ? `Currently executing: ${active.agent.replaceAll("_", " ")} / request #${activity.request_id}`
    : `Request #${activity.request_id} / ${activity.status.replaceAll("_", " ")}`;
  timeline.innerHTML = trace.map((event) => {
    const duration = event.completed_at
      ? `${Math.max(0, new Date(event.completed_at) - new Date(event.started_at))} ms`
      : "in progress";
    const details = JSON.stringify({ inputs: event.inputs, outputs: event.outputs }, null, 2);
    return `<article class="agent-event">
      <div class="agent-event-heading">
        <span class="agent-event-name">${escapeHtml(event.agent.replaceAll("_", " "))}</span>
        <span class="agent-event-status ${escapeHtml(event.status)}">${escapeHtml(event.status)}</span>
      </div>
      <div class="agent-event-meta">Started ${escapeHtml(new Date(event.started_at).toLocaleString())} · ${escapeHtml(duration)} · attempt ${event.retry_attempt}</div>
      ${event.checker_feedback ? `<p class="agent-event-feedback">Checker: ${escapeHtml(event.checker_feedback)}</p>` : ""}
      ${event.error ? `<p class="agent-event-error">Error: ${escapeHtml(event.error)}</p>` : ""}
      <details><summary>Inputs and outputs</summary><pre>${escapeHtml(details)}</pre></details>
    </article>`;
  }).join("");
}

function renderAgentStatuses(activity) {
  const agents = [
    ["classification_agent", "Classification Agent"],
    ["validation_agent", "Validation Agent"],
    ["routing_agent", "Routing Agent"],
    ["execution_agent", "Execution Agent"],
    ["checker_agent", "Checker Agent"],
    ["review_agent", "Review Agent"],
  ];
  const trace = activity?.trace || [];
  byId("agent-status-grid").innerHTML = agents.map(([key, label]) => {
    const event = [...trace].reverse().find((item) => item.agent === key);
    let status = event?.status || (activity?.status === "processing" ? "pending" : "not_run");
    if (key === "review_agent" && activity?.status === "pending_review") status = "waiting_review";
    if (key === "execution_agent" && activity?.status === "pending_review" && activity.workflow) status = "waiting_review";
    return `<article class="agent-status-card"><span>${escapeHtml(label)}</span><strong class="agent-state ${escapeHtml(status)}">${escapeHtml(status.replaceAll("_", " "))}</strong><small>${event ? `Attempt ${event.retry_attempt}` : status === "pending" ? "Awaiting its execution stage" : "No execution recorded"}</small></article>`;
  }).join("");
}

async function loadAgentTrace(requestId) {
  if (!requestId) {
    renderAgentActivity(null);
    return;
  }
  const activity = await api(`/api/requests/${requestId}/trace`);
  renderAgentActivity(activity);
}

function renderBarChart(containerId, rows, labelKey, valueKey, options = {}) {
  const container = byId(containerId);
  if (!Array.isArray(rows) || !rows.length || rows.every((row) => !(Number(row[valueKey]) > 0))) {
    container.innerHTML = '<div class="chart-empty">No recorded data for this period.</div>';
    return;
  }
  const visible = options.limit ? rows.slice(-options.limit) : rows;
  const max = Math.max(1, ...visible.map((row) => Number(row[valueKey]) || 0));
  const width = 560;
  const rowHeight = 28;
  const height = Math.max(100, visible.length * rowHeight + 20);
  const labelWidth = options.labelWidth || 132;
  const availableWidth = width - labelWidth - 68;
  const bars = visible.map((row, index) => {
    const value = Number(row[valueKey]) || 0;
    const y = index * rowHeight + 8;
    const barWidth = value > 0 ? Math.max(2, availableWidth * value / max) : 0;
    return `<text x="0" y="${y + 13}" class="chart-label">${escapeHtml(row[labelKey])}</text><rect x="${labelWidth}" y="${y}" width="${barWidth}" height="15" rx="3" class="chart-bar ${options.variant || ""}"/><text x="${labelWidth + barWidth + 6}" y="${y + 12}" class="chart-value">${escapeHtml(value)}</text>`;
  }).join("");
  container.innerHTML = `<svg class="bar-chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="${escapeHtml(options.ariaLabel || "Recorded values")}">${bars}</svg>`;
}

function renderExecutionOutcomes(rows) {
  const container = byId("chart-outcomes");
  const completed = rows.find((row) => row.status === "completed")?.count || 0;
  const failed = rows.find((row) => row.status === "failed")?.count || 0;
  const total = completed + failed;
  if (!total) {
    container.innerHTML = '<div class="chart-empty">No workflow execution records.</div>';
    return;
  }
  container.innerHTML = `<div class="outcome-numbers"><span><strong>${completed}</strong> completed</span><span><strong>${failed}</strong> failed</span></div><div class="outcome-track" role="img" aria-label="${completed} completed, ${failed} failed"><span style="width:${completed / total * 100}%"></span></div>`;
}

async function refreshAnalytics() {
  const params = new URLSearchParams();
  if (byId("history-from").value) params.set("from", byId("history-from").value);
  if (byId("history-to").value) params.set("to", byId("history-to").value);
  const analytics = await api(`/api/analytics?${params}`);
  const requiredArrays = [
    "requests_over_time",
    "category_distribution",
    "confidence_distribution",
    "execution_outcomes",
    "human_reviews_over_time",
    "agent_latency",
  ];
  if (!analytics || typeof analytics !== "object" || !analytics.kpis
      || requiredArrays.some((key) => !Array.isArray(analytics[key]))) {
    throw new Error("The server returned an incomplete analytics response.");
  }
  const kpis = analytics.kpis;
  ["total_requests", "classified_requests", "routed_requests", "pending_reviews", "failed_executions"].forEach((key) => {
    if (!Number.isFinite(kpis[key])) throw new Error(`Analytics response is missing ${key}.`);
  });
  if (!Number.isFinite(kpis.average_execution_ms)) {
    throw new Error("Analytics response is missing average_execution_ms.");
  }
  byId("stat-total").textContent = kpis.total_requests;
  byId("stat-classified").textContent = kpis.classified_requests;
  byId("stat-routed").textContent = kpis.routed_requests;
  byId("stat-review").textContent = kpis.pending_reviews;
  byId("stat-failed").textContent = kpis.failed_executions;
  byId("stat-execution-time").textContent = `${kpis.average_execution_ms} ms`;
  byId("analytics-window").textContent = byId("history-from").value || byId("history-to").value
    ? `${byId("history-from").value || "START"} → ${byId("history-to").value || "TODAY"}`
    : "ALL RECORDED DATA";
  renderBarChart("chart-requests", analytics.requests_over_time, "date", "count", { limit: 14, ariaLabel: "Requests per day" });
  renderBarChart("chart-categories", analytics.category_distribution, "category", "count", { labelWidth: 170 });
  renderBarChart("chart-confidence", analytics.confidence_distribution, "label", "count", { variant: "secondary" });
  renderExecutionOutcomes(analytics.execution_outcomes);
  renderBarChart("chart-reviews", analytics.human_reviews_over_time, "date", "count", { limit: 14, variant: "secondary" });
  renderBarChart("chart-latency", analytics.agent_latency, "agent", "average_ms", {
    labelWidth: 170,
    variant: "secondary",
  });
  byId("evaluation-note").textContent = "Offline benchmark results are shown separately in Evaluation; benchmark cases are not mixed into operational request metrics.";
  byId("memory-state").textContent = analytics.memory?.available
    ? "Memory records are available."
    : analytics.memory?.reason || "Memory is not configured; no memory records are available.";
}

function evaluationMetric(label, value, note = "") {
  return `<article class="evaluation-kpi"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong><small>${escapeHtml(note)}</small></article>`;
}

function evaluationPercent(value, digits = 1) {
  return Number.isFinite(value) ? `${(value * 100).toFixed(digits)}%` : "—";
}

function renderEvaluationReport(report) {
  const content = byId("evaluation-content");
  if (!report) {
    content.hidden = true;
    byId("evaluation-empty").hidden = false;
    return;
  }
  const metrics = report.metrics;
  const classification = metrics.classification;
  const routing = metrics.routing;
  const multiAgent = metrics.multi_agent;
  const performance = metrics.performance;
  content.hidden = false;
  byId("evaluation-empty").hidden = true;
  byId("evaluation-run-meta").textContent =
    `FIXED LOCAL HOLDOUT · NOT PRODUCTION ACCURACY · ${report.dataset.name} v${report.dataset.version} · ${report.dataset.sample_count} samples from ${report.dataset.seed_count} labeled seeds · ${report.configuration.provider.toUpperCase()}${report.configuration.model ? ` / ${report.configuration.model}` : ""} · ${new Date(report.executed_at).toLocaleString()}`;
  byId("evaluation-kpis").innerHTML = [
    evaluationMetric("ACCURACY", `${(classification.accuracy * 100).toFixed(1)}%`, `${classification.sample_count} labeled cases`),
    evaluationMetric("MACRO F1", classification.macro_f1.toFixed(3), "Equal weight per configured category"),
    evaluationMetric("WEIGHTED F1", classification.weighted_f1.toFixed(3), "Weighted by category support"),
    evaluationMetric("CORRECT ROUTES", evaluationPercent(routing.correct_workflow_selection_rate), `${routing.correct_workflow_count} / ${routing.known_intent_count} known intents`),
    evaluationMetric("MEAN RESPONSE", `${performance.response_latency.average_ms ?? "—"} ms`, `p95 ${performance.response_latency.p95_ms ?? "—"} ms`),
    evaluationMetric("AGENT SUCCESS", evaluationPercent(multiAgent.agent_execution_success_rate), `${multiAgent.agent_invocations} benchmark trace events; fault probe reported separately`),
  ].join("");

  const categoryRows = Object.entries(classification.per_category).map(([category, row]) =>
    `<tr><td>${escapeHtml(category.replaceAll("_", " "))}</td><td>${row.support}</td><td>${(row.precision * 100).toFixed(1)}%</td><td>${(row.recall * 100).toFixed(1)}%</td><td>${row.f1.toFixed(3)}</td></tr>`,
  ).join("");
  const confidence = classification.confidence_reliability;
  const ece = confidence.expected_calibration_error == null ? "—" : confidence.expected_calibration_error.toFixed(3);
  byId("evaluation-classification").innerHTML = `<p>Macro precision ${(classification.macro_precision * 100).toFixed(1)}% · macro recall ${(classification.macro_recall * 100).toFixed(1)}% · confidence ECE ${ece} (${confidence.sample_count} scored cases)</p><div class="table-wrap"><table><thead><tr><th>CATEGORY</th><th>N</th><th>PRECISION</th><th>RECALL</th><th>F1</th></tr></thead><tbody>${categoryRows}</tbody></table></div><p class="evaluation-footnote">${escapeHtml(metrics.escalation.note)} UNKNOWN recall ${evaluationPercent(metrics.escalation.unknown_recall)}; unexpected escalations ${metrics.escalation.unexpected_escalation_count}. ${escapeHtml(confidence.note)}</p>`;
  byId("evaluation-routing").innerHTML = `<dl class="evaluation-list"><dt>Correct predefined workflow</dt><dd>${evaluationPercent(routing.correct_workflow_selection_rate)}</dd><dt>Invalid category rejected</dt><dd>${evaluationPercent(routing.invalid_category_rejection_rate)}</dd><dt>Adversarial execution prevented</dt><dd>${evaluationPercent(routing.unauthorized_execution_prevention_rate)}</dd><dt>Workflow execution success</dt><dd>${evaluationPercent(routing.workflow_execution_success_rate)}</dd><dt>Review/escalation rate</dt><dd>${evaluationPercent(metrics.escalation.escalation_rate)}</dd></dl>`;
  byId("evaluation-agents").innerHTML = `<dl class="evaluation-list"><dt>Agent failures</dt><dd>${evaluationPercent(multiAgent.agent_failure_rate, 2)}</dd><dt>Checker feedback events</dt><dd>${multiAgent.checker_failures_with_feedback}</dd><dt>Controlled fault detected</dt><dd>${evaluationPercent(multiAgent.checker_detection_rate_controlled_fault)}</dd><dt>Retry success</dt><dd>${evaluationPercent(multiAgent.retry_success_rate)}</dd><dt>Mean retries / benchmark case</dt><dd>${multiAgent.average_retries_per_evaluated_request.toFixed(3)}</dd><dt>Human interventions requested</dt><dd>${multiAgent.human_intervention_frequency}</dd></dl>`;
  const latencyRows = [
    ["Response mean", performance.response_latency.average_ms],
    ["Response median", performance.response_latency.median_ms],
    ["Response p95", performance.response_latency.p95_ms],
    ["Classification", performance.classification_latency.average_ms],
    ["All agent spans", performance.agent_execution_latency.average_ms],
    ["Workflow execution", performance.workflow_execution_time.average_ms],
  ].filter(([, value]) => Number.isFinite(value)).map(([label, value]) => ({label, value}));
  renderBarChart("evaluation-latency", latencyRows, "label", "value", {labelWidth: 150, variant: "secondary"});
  const agentLatency = Object.entries(multiAgent.per_agent || {}).map(([agent, stats]) => ({
    agent,
    average_ms: stats.average_latency_ms,
  })).filter((item) => Number.isFinite(item.average_ms));
  renderBarChart("evaluation-agent-latency", agentLatency, "agent", "average_ms", {
    labelWidth: 170,
    variant: "secondary",
  });
  const labels = Object.keys(classification.confusion_matrix);
  const matrixHeader = labels.map((label) => `<th title="${escapeHtml(label)}">${escapeHtml(label.replaceAll("_", " "))}</th>`).join("");
  const matrixRows = labels.map((actual) => `<tr><th>${escapeHtml(actual.replaceAll("_", " "))}</th>${labels.map((predicted) => `<td>${classification.confusion_matrix[actual][predicted]}</td>`).join("")}</tr>`).join("");
  byId("evaluation-confusion").innerHTML = `<table><thead><tr><th>ACTUAL / PREDICTED</th>${matrixHeader}</tr></thead><tbody>${matrixRows}</tbody></table>`;
  const comparisons = report.comparative_analysis.same_dataset_provider_runs || [];
  const providerComparison = comparisons.length
    ? comparisons.map((comparison) => `<p>${escapeHtml(report.configuration.provider)} vs ${escapeHtml(comparison.provider)} on identical dataset (${comparison.sample_count} cases): accuracy delta ${comparison.accuracy_delta_current_minus_comparison >= 0 ? "+" : ""}${(comparison.accuracy_delta_current_minus_comparison * 100).toFixed(1)} pp; macro-F1 delta ${comparison.macro_f1_delta_current_minus_comparison >= 0 ? "+" : ""}${comparison.macro_f1_delta_current_minus_comparison.toFixed(3)}. <small>${escapeHtml(comparison.note)}</small></p>`).join("")
    : `<p>${escapeHtml(report.comparative_analysis.provider_comparison_note || "No comparable provider run is available.")}</p>`;
  const recoveryComparison = report.comparative_analysis.normal_vs_checker_recovery;
  const recoveryLine = recoveryComparison
    ? `<p>Normal mean response ${recoveryComparison.normal_response_latency.average_ms} ms (${recoveryComparison.normal_response_latency.sample_count} cases); controlled checker-retry response ${recoveryComparison.controlled_retry_response_latency_ms} ms (${escapeHtml(recoveryComparison.controlled_retry_final_status)}). <small>${escapeHtml(recoveryComparison.note)}</small></p>`
    : "";
  byId("evaluation-comparison").innerHTML = providerComparison + recoveryLine;
  const recovery = report.checker_recovery_probe;
  const limitations = [
    `Configuration: ${JSON.stringify(report.configuration, null, 2)}`,
    `Robustness: ${JSON.stringify(report.robustness, null, 2)}`,
    `Checker fault injection: ${JSON.stringify(recovery, null, 2)}`,
    `Limitations: ${JSON.stringify(report.limitations, null, 2)}`,
    `Comparative analysis: ${JSON.stringify(report.comparative_analysis, null, 2)}`,
  ].join("\n\n");
  byId("evaluation-limitations").textContent = limitations;
  byId("evaluation-download-json").href = `/api/evaluations/${encodeURIComponent(report.run_id)}/download?format=json`;
  byId("evaluation-download-csv").href = `/api/evaluations/${encodeURIComponent(report.run_id)}/download?format=csv`;
}

async function loadEvaluationReport(runId) {
  if (!runId) {
    renderEvaluationReport(null);
    return;
  }
  const report = await api(`/api/evaluations/${encodeURIComponent(runId)}`);
  renderEvaluationReport(report);
}

async function refreshEvaluationRuns() {
  const response = await api("/api/evaluations");
  if (!response || !Array.isArray(response.runs)) {
    throw new Error("The server returned an invalid evaluation-run list.");
  }
  const selector = byId("evaluation-run-select");
  const selected = selector.value;
  selector.replaceChildren();
  response.runs.forEach((run) => {
    const option = document.createElement("option");
    option.value = run.run_id;
    option.textContent = `${run.provider.toUpperCase()} · ${run.dataset.version} · ${new Date(run.executed_at).toLocaleString()}`;
    selector.append(option);
  });
  if (!response.runs.length) {
    selector.add(new Option("No evaluation runs", ""));
    await loadEvaluationReport("");
    return;
  }
  selector.value = response.runs.some((run) => run.run_id === selected) ? selected : response.runs[0].run_id;
  await loadEvaluationReport(selector.value);
}

byId("evaluation-run-select").addEventListener("change", () => {
  loadEvaluationReport(byId("evaluation-run-select").value).catch(showLoadError);
});
byId("evaluation-refresh").addEventListener("click", () => {
  refreshEvaluationRuns().catch(showLoadError);
});

async function refreshDashboard() {
  const params = new URLSearchParams();
  if (byId("history-search").value.trim()) params.set("search", byId("history-search").value.trim());
  if (byId("history-status").value) params.set("status", byId("history-status").value);
  if (byId("history-category").value) params.set("category", byId("history-category").value);
  if (byId("history-from").value) params.set("from", byId("history-from").value);
  if (byId("history-to").value) params.set("to", byId("history-to").value);
  const data = await api(`/api/dashboard?${params}`);
  byId("topbar-status").innerHTML = '<span class="live-dot"></span>Dashboard connected';
  renderStats(data.stats);
  renderHistory(data.history);
  renderReviews(data.reviews);
  byId("provider-name").textContent = data.provider.toUpperCase();
  byId("provider-mode").textContent = data.mode === "real"
    ? `REAL LLM MODE / ${data.model || "Gemini"}`
    : "DEMO MOCK MODE / NO API KEY";
  byId("confidence-floor").textContent = `${Math.round(data.confidence_threshold * 100)}%`;
  const categorySelect = byId("history-category");
  const selectedCategory = categorySelect.value;
  if (categorySelect.options.length === 1) {
    data.categories.forEach((category) => {
      const option = document.createElement("option");
      option.value = category.id;
      option.textContent = category.id.replaceAll("_", " ");
      categorySelect.append(option);
    });
  }
  categorySelect.value = selectedCategory;
  const selector = byId("agent-request-select");
  const previous = selector.value;
  selector.replaceChildren();
  data.history.forEach((record) => {
    const option = document.createElement("option");
    option.value = record.id;
    option.textContent = `#${record.id} · ${record.category || "Unclassified"} · ${record.status}`;
    selector.append(option);
  });
  const requested = data.history.some((record) => String(record.id) === String(previous))
    ? previous
    : data.history[0]?.id;
  if (requested) {
    selector.value = requested;
    await loadAgentTrace(requested);
  } else {
    renderAgentActivity(null);
  }
  await refreshAnalytics();
}

byId("agent-request-select").addEventListener("change", () => {
  loadAgentTrace(byId("agent-request-select").value).catch(showLoadError);
});

async function pollAgentActivity() {
  const activity = await api("/api/agent-activity");
  if (!activity) return;
  const selector = byId("agent-request-select");
  let option = [...selector.options].find((item) => item.value === String(activity.request_id));
  if (!option) {
    option = document.createElement("option");
    option.value = activity.request_id;
    option.textContent = `#${activity.request_id} · live activity · ${activity.status}`;
    selector.append(option);
  }
  if (activity.status === "processing" || !selector.value) selector.value = activity.request_id;
  if (selector.value === String(activity.request_id) || activity.status === "processing") {
    renderAgentActivity(activity);
  }
}

byId("request-input").addEventListener("input", (event) => {
  byId("char-count").textContent = `${event.target.value.length} / 4000`;
});

document.querySelectorAll(".example-chip").forEach((button) => {
  button.addEventListener("click", () => {
    byId("request-input").value = button.dataset.example;
    byId("request-input").dispatchEvent(new Event("input"));
    byId("request-input").focus();
  });
});

byId("request-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const input = byId("request-input");
  const button = byId("submit-button");
  byId("form-error").textContent = "";
  button.disabled = true;
  button.textContent = "Classifying…";
  const activityPoll = window.setInterval(() => {
    api("/api/agent-activity").then(renderAgentActivity).catch(showLoadError);
  }, 500);
  try {
    const record = await api("/api/requests", { method: "POST", body: JSON.stringify({ request: input.value }) });
    showResult(record);
    byId("agent-request-select").value = record.id;
    await loadAgentTrace(record.id);
    input.value = "";
    input.dispatchEvent(new Event("input"));
    await refreshDashboard();
  } catch (error) {
    byId("form-error").textContent = error.message;
    notify(error.message);
    await refreshDashboard().catch(showLoadError);
  } finally {
    window.clearInterval(activityPoll);
    button.disabled = false;
    button.innerHTML = 'Classify &amp; route <span aria-hidden="true">↗</span>';
  }
});

byId("review-list").addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-action]");
  if (!button) return;
  const item = button.closest("[data-review-id]");
  const feedback = item.querySelector("input").value;
  button.disabled = true;
  try {
    const updated = await api(`/api/reviews/${item.dataset.reviewId}`, {
      method: "POST", body: JSON.stringify({ action: button.dataset.action, feedback }),
    });
    showResult(updated);
    await loadAgentTrace(updated.id);
    await refreshDashboard();
  } catch (error) {
    notify(error.message);
    button.disabled = false;
  }
});

let searchTimer;
byId("history-search").addEventListener("input", () => {
  window.clearTimeout(searchTimer);
  searchTimer = window.setTimeout(() => refreshDashboard().catch(showLoadError), 180);
});
byId("history-status").addEventListener("change", () => refreshDashboard().catch(showLoadError));
byId("history-category").addEventListener("change", () => refreshDashboard().catch(showLoadError));
byId("history-from").addEventListener("change", () => refreshDashboard().catch(showLoadError));
byId("history-to").addEventListener("change", () => refreshDashboard().catch(showLoadError));

byId("history-body").addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-request-id]");
  if (!button) return;
  const record = latestHistory.find((item) => String(item.id) === button.dataset.requestId);
  if (!record) return;
  try {
    const trace = await api(`/api/requests/${record.id}/trace`);
    const detail = byId("request-detail");
    detail.hidden = false;
    detail.innerHTML = `<div class="detail-heading"><h3>Request #${record.id}</h3><button type="button" class="detail-close" aria-label="Close request details">Close</button></div><p>${escapeHtml(record.request_text)}</p><p><strong>${escapeHtml(record.category || "UNKNOWN")}</strong> · ${escapeHtml(record.status.replaceAll("_", " "))} · ${escapeHtml(record.workflow || "No workflow")}</p><p>${escapeHtml(record.error || record.review_reason || "No recorded error or review feedback.")}</p><p>${trace.trace.length} actual agent events recorded.</p>`;
    byId("agent-request-select").value = record.id;
    renderAgentActivity(trace);
    detail.scrollIntoView({ behavior: "smooth", block: "nearest" });
  } catch (error) {
    notify(error.message);
  }
});

byId("request-detail").addEventListener("click", (event) => {
  if (event.target.closest(".detail-close")) byId("request-detail").hidden = true;
});

byId("theme-toggle").addEventListener("click", () => {
  const dark = document.body.classList.toggle("theme-dark");
  localStorage.setItem("p18-theme", dark ? "dark" : "light");
  byId("theme-toggle").setAttribute("aria-label", `Switch to ${dark ? "light" : "dark"} theme`);
});

if (localStorage.getItem("p18-theme") === "dark") {
  document.body.classList.add("theme-dark");
  byId("theme-toggle").setAttribute("aria-label", "Switch to light theme");
}

function showLoadError(error) {
  byId("health-status").innerHTML = `<span class="live-dot" style="background:#d66b45"></span>${escapeHtml(error.message)}`;
  byId("topbar-status").innerHTML = '<span class="live-dot" style="background:#d66b45"></span>Connection issue';
  notify(error.message || "Dashboard data could not be loaded.");
}

refreshDashboard().catch(showLoadError);
refreshEvaluationRuns().catch(showLoadError);
window.setInterval(() => refreshDashboard().catch(showLoadError), 5000);
window.setInterval(() => pollAgentActivity().catch(showLoadError), 2000);