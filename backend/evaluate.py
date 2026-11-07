"""Run a reproducible classification and multi-agent benchmark."""

import argparse
import json
import os
from pathlib import Path

from dotenv import load_dotenv

from backend.evaluation import DEFAULT_DATASET, run_evaluation


ROOT = Path(__file__).resolve().parents[1]


def confidence_reliability(records: list[dict]) -> dict:
    """Summarize empirical accuracy against mean confidence in fixed score bins."""
    ranges = ((0.0, 0.5), (0.5, 0.65), (0.65, 0.8), (0.8, 1.0))
    bins = []
    weighted_gap = 0.0
    for lower, upper in ranges:
        members = [
            record for record in records
            if lower <= record["confidence"] < upper
            or upper == 1.0 and lower <= record["confidence"] <= upper
        ]
        accuracy = sum(record["predicted"] == record["expected"] for record in members) / len(members) if members else None
        mean_confidence = sum(record["confidence"] for record in members) / len(members) if members else None
        if members:
            weighted_gap += len(members) / len(records) * abs(accuracy - mean_confidence)
        bins.append({
            "range": f"{lower:.2f}-{upper:.2f}",
            "count": len(members),
            "accuracy": round(accuracy, 4) if accuracy is not None else None,
            "mean_confidence": round(mean_confidence, 4) if mean_confidence is not None else None,
        })
    return {"expected_calibration_error": round(weighted_gap, 4), "bins": bins}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=("demo", "gemini"), default="demo")
    parser.add_argument("--model", default=None, help="Override GEMINI_MODEL for a real-provider run.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--threshold", type=float, default=None)
    parser.add_argument("--timeout", type=float, default=None)
    parser.add_argument(
        "--database",
        type=Path,
        default=ROOT / "data" / "evaluation_results.sqlite3",
        help="Separate SQLite file for benchmark results; ordinary request history is not modified.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "data" / "evaluation_reports",
        help="Directory for downloadable-style JSON and CSV snapshots.",
    )
    arguments = parser.parse_args(argv)
    load_dotenv(ROOT / ".env")
    threshold = arguments.threshold
    if threshold is None:
        threshold = float(os.getenv("CONFIDENCE_THRESHOLD", "0.65"))
    timeout = arguments.timeout
    if timeout is None:
        timeout = float(os.getenv("LLM_TIMEOUT", "20"))
    model = arguments.model or os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
    if not 0 <= threshold <= 1:
        parser.error("--threshold must be between 0 and 1.")
    if timeout <= 0:
        parser.error("--timeout must be positive.")
    report = run_evaluation(
        provider=arguments.provider,
        model=model if arguments.provider == "gemini" else "",
        api_key=os.getenv("GEMINI_API_KEY", ""),
        threshold=threshold,
        timeout=timeout,
        dataset_path=arguments.dataset,
        store_path=arguments.database,
    )
    arguments.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = arguments.output_dir / f'{report["run_id"]}.json'
    csv_path = arguments.output_dir / f'{report["run_id"]}.csv'
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    from backend.services.evaluation_store import EvaluationStore

    csv_path.write_text(
        EvaluationStore(arguments.database).get_csv(report["run_id"]) or "",
        encoding="utf-8-sig",
    )
    print(json.dumps({
        "run_id": report["run_id"],
        "provider": report["configuration"]["provider"],
        "dataset": report["dataset"],
        "metrics": report["metrics"],
        "robustness": report["robustness"],
        "reports": {"json": str(json_path), "csv": str(csv_path)},
        "results_database": str(arguments.database),
    }, indent=2))


if __name__ == "__main__":
    main()
