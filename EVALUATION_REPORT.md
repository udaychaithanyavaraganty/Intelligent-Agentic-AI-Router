# Evaluation and Benchmarking Report

## 1. Run identity and scope

| Field | Recorded value |
|---|---|
| Run ID | `101d139d-fe97-4dbd-adb9-f34c54f75657` |
| Run date | 6 November 2026 |
| Provider / mode | `demo` / mock |
| Real LLM evaluated | No |
| Dataset | P18 Intent and Safety Benchmark, version `2.0.0` |
| Dataset SHA-256 | `dc3202a29c3bb0193d7c3226644d0d82ef826b15ba2c1119670cef577e431b37` |
| Labeled seed prompts | 37 |
| Expanded cases | 222 |
| Random seed recorded | `1806` |
| Confidence threshold | `0.65` |
| Retrieved memory | No; no memory module is implemented |
| Ordinary request history modified | No; isolated temporary request database used |

The fixed dataset is [`data/evaluation_dataset_v2.json`](data/evaluation_dataset_v2.json). It is expanded deterministically from the seed examples using the versioned context variants. The benchmark includes examples marked ambiguous, unsupported, malformed-looking, and adversarial. The variants increase case count but are not independent samples from real traffic. The locally authored dataset is not a production-representative or externally audited holdout.

## 2. Classification methodology

The classifier's `UNKNOWN` outcome is treated as an ordinary class for accuracy, precision, recall, F1, and confusion-matrix calculations. Escalation is measured separately so that successful safe escalation is not conflated with a correct supported-intent label. Per-category precision uses true positives divided by predictions for that label; recall uses true positives divided by the label support; F1 is the harmonic mean. Macro metrics weight the seven labels equally, while weighted F1 weights each label by its support.

### Overall metrics

| Metric | Result |
|---|---:|
| Sample count | 222 |
| Accuracy | 1.000000 |
| Macro precision | 1.000000 |
| Macro recall | 1.000000 |
| Macro F1 | 1.000000 |
| Weighted F1 | 1.000000 |

### Per-category metrics

| Category | Support | Predicted count | Precision | Recall | F1 |
|---|---:|---:|---:|---:|---:|
| `ACCOUNT_MANAGEMENT` | 30 | 30 | 1.000000 | 1.000000 | 1.000000 |
| `DATA_ANALYSIS` | 30 | 30 | 1.000000 | 1.000000 | 1.000000 |
| `GENERAL_INFORMATION` | 30 | 30 | 1.000000 | 1.000000 | 1.000000 |
| `SOFTWARE_DEVELOPMENT` | 30 | 30 | 1.000000 | 1.000000 | 1.000000 |
| `TASK_AUTOMATION` | 30 | 30 | 1.000000 | 1.000000 | 1.000000 |
| `TECHNICAL_SUPPORT` | 30 | 30 | 1.000000 | 1.000000 | 1.000000 |
| `UNKNOWN` | 42 | 42 | 1.000000 | 1.000000 | 1.000000 |

### Confusion matrix

Rows are expected labels; columns are predicted labels. The stored matrix has a diagonal count equal to the support for each class and zero off-diagonal counts.

| Expected \ Predicted | ACCOUNT_MANAGEMENT | DATA_ANALYSIS | GENERAL_INFORMATION | SOFTWARE_DEVELOPMENT | TASK_AUTOMATION | TECHNICAL_SUPPORT | UNKNOWN |
|---|---:|---:|---:|---:|---:|---:|---:|
| `ACCOUNT_MANAGEMENT` | 30 | 0 | 0 | 0 | 0 | 0 | 0 |
| `DATA_ANALYSIS` | 0 | 30 | 0 | 0 | 0 | 0 | 0 |
| `GENERAL_INFORMATION` | 0 | 0 | 30 | 0 | 0 | 0 | 0 |
| `SOFTWARE_DEVELOPMENT` | 0 | 0 | 0 | 30 | 0 | 0 | 0 |
| `TASK_AUTOMATION` | 0 | 0 | 0 | 0 | 30 | 0 | 0 |
| `TECHNICAL_SUPPORT` | 0 | 0 | 0 | 0 | 0 | 30 | 0 |
| `UNKNOWN` | 0 | 0 | 0 | 0 | 0 | 0 | 42 |

### Escalation results

| Measurement | Result |
|---|---:|
| Expected review cases | 42 |
| Actual escalations | 42 |
| `UNKNOWN` cases escalated | 42/42 |
| `UNKNOWN` recall | 1.000000 |
| Overall escalation rate | 42/222 = 0.189189 |
| Unexpected escalation count | 0 |

The perfect classification metrics are specific to the local demo classifier and the locally authored benchmark. They do not measure Gemini quality or general semantic understanding.

## 3. Routing and execution results

| Metric | Numerator / denominator | Result |
|---|---:|---:|
| Correct workflow selection for known intents | 180 / 180 | 1.000000 |
| Invalid-category rejection rate | All controlled invalid-category probes rejected | 1.000000 |
| Unauthorized execution prevention | 12 / 12 adversarial benchmark examples | 1.000000 |
| Workflow execution success | 180 / 180 execution-agent events | 1.000000 |

Routing correctness is checked against the configured deterministic category map. The six demo workflows are local response-only handlers. This result is not evidence that an external business workflow would be reliable.

## 4. Multi-agent and checker results

| Component | Invocations | Completed | Failed | Success rate | Average span |
|---|---:|---:|---:|---:|---:|
| Classification Agent | 222 | 222 | 0 | 1.000000 | 7.985 ms |
| Validation Agent | 222 | 222 | 0 | 1.000000 | 8.814 ms |
| Routing Agent | 180 | 180 | 0 | 1.000000 | 8.752 ms |
| Execution Agent | 180 | 180 | 0 | 1.000000 | 7.862 ms |
| Checker Agent | 804 | 804 | 0 | 1.000000 | 8.743 ms |
| **All recorded agent events** | **1,608** | **1,608** | **0** | **1.000000** | **8.551 ms** |

There were zero retry attempts on the 222 ordinary benchmark cases, so the benchmark's average retries per evaluated request was `0`. A separate controlled fault-injection probe returned one malformed classifier result, which the checker detected; one feedback-guided retry succeeded and completed. Its checker detection and retry success were both `1/1` for that single probe. These are controlled demonstration results, not estimates of general recovery rates.

Human intervention frequency was 42 requests, or `0.189189` of the dataset. This corresponds to the labeled `UNKNOWN` cases in this run.

## 5. Latency and resource usage

Latencies are measured on the local demo environment. Request latency uses an in-process Flask test client; stage durations are derived from persisted agent start/completion timestamps. Percentiles use the evaluation runner's nearest-rank calculation.

| Span | Sample count | Average | Median | P95 |
|---|---:|---:|---:|---:|
| End-to-end request response | 222 | 153.307 ms | 165.079 ms | 173.286 ms |
| Classification | 222 | 7.985 ms | 7.998 ms | 9.082 ms |
| All agent execution events | 1,608 | 8.551 ms | 8.602 ms | 10.001 ms |
| Workflow execution | 180 | 7.862 ms | 7.964 ms | 9.021 ms |

Provider usage metadata was unavailable for this demo run: zero provider-token observations were recorded. API cost is `null`; the project has no verified pricing configuration and does not estimate cost. No Gemini evaluation is included.

## 6. Robustness probes

The saved report records the following outcomes:

| Probe | Recorded result |
|---|---|
| Empty request rejected | Pass |
| Whitespace-only request rejected | Pass |
| Request larger than 4,000 characters rejected | Pass |
| Malformed request JSON rejected | Pass |
| Unsupported category rejected | Pass |
| Malformed classifier response held for review | Pass |
| Provider timeout fails closed | Pass |
| Prompt-injection/adversarial inputs | 12/12 did not execute |
| Repeated text creates distinct request records | Pass |
| Four in-process concurrent requests | Pass |
| Controlled execution failure recorded without retry | Pass |
| Database failure prevents classification and execution | Pass |

These are controlled functional probes, not a penetration test, high-load test, provider outage study, or exhaustive prompt-injection assessment.

## 7. Comparisons and unavailability

- **Mock vs. real LLM:** no stored Gemini run used the same dataset hash; provider comparison is unavailable.
- **Memory on vs. off:** unavailable; the application does not implement retrieval or memory.
- **Normal vs. checker-assisted recovery:** the report includes one controlled malformed-response retry probe. It is descriptive fault injection, not a statistically meaningful comparison.
- **Checker-disabled baseline:** intentionally unavailable because disabling the checker would remove an implemented safety control.

No improvement or causal benefit is claimed from these comparisons.

## 8. Reproduction and artifacts

From the project root:

```powershell
python -m backend.evaluate --provider demo
```

The CLI stores run metadata and cases in `data/evaluation_results.sqlite3` and writes JSON/CSV snapshots under `data/evaluation_reports/`. Evaluation request traces use temporary SQLite history. To opt into Gemini, configure `GEMINI_API_KEY` and explicitly run `python -m backend.evaluate --provider gemini`; that sends benchmark requests to the provider and may consume billable quota. It was not performed for this report.

Final saved artifacts:

- [Full JSON report](data/evaluation_reports/101d139d-fe97-4dbd-adb9-f34c54f75657.json)
- [Per-case CSV](data/evaluation_reports/101d139d-fe97-4dbd-adb9-f34c54f75657.csv)
- [Versioned source dataset](data/evaluation_dataset_v2.json)

The CSV contains 222 data rows; the JSON includes 222 per-case records. The API also serves stored reports from `/api/evaluations`.

## 9. Limitations and interpretation

1. The demo provider is a deterministic keyword-pattern classifier. Its prompts overlap intentionally with its keyword rules, so the measured perfect score is not a meaningful estimate of generalization.
2. The 37 seeds and six deterministic contexts are a small locally authored benchmark; context variants are correlated and should not be interpreted as 222 independent real-world requests.
3. There is no independent external annotation audit or real-provider result in this report.
4. Workflow handlers produce demonstration responses only.
5. Local timing depends on the test host, Python runtime, SQLite, and local scheduling; it is not a service-level objective.
6. Memory and cost comparisons are unavailable, and no token counts were fabricated.
7. The single checker fault probe demonstrates a code path but cannot establish a population detection or recovery probability.

Accordingly, the results validate selected implementation behavior on this fixed test corpus. They do not establish production readiness, real-world classification accuracy, or real-LLM performance.
