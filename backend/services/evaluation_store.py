"""Persistence for benchmark runs, isolated from request history."""

import csv
import io
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path


class EvaluationStore:
    def __init__(self, database_path: str):
        self.database_path = str(database_path)
        Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS evaluation_runs (
                    run_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    model TEXT,
                    dataset_name TEXT NOT NULL,
                    dataset_version TEXT NOT NULL,
                    dataset_sha256 TEXT NOT NULL,
                    sample_count INTEGER NOT NULL,
                    report_json TEXT NOT NULL
                )"""
            )
            connection.execute(
                """CREATE TABLE IF NOT EXISTS evaluation_cases (
                    run_id TEXT NOT NULL,
                    case_index INTEGER NOT NULL,
                    case_json TEXT NOT NULL,
                    PRIMARY KEY (run_id, case_index),
                    FOREIGN KEY (run_id) REFERENCES evaluation_runs(run_id)
                )"""
            )

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def save(self, report: dict) -> None:
        metadata = report["configuration"]
        summary = {key: value for key, value in report.items() if key != "cases"}
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO evaluation_runs
                (run_id, created_at, provider, model, dataset_name, dataset_version,
                 dataset_sha256, sample_count, report_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    report["run_id"],
                    report["executed_at"],
                    metadata["provider"],
                    metadata.get("model"),
                    report["dataset"]["name"],
                    report["dataset"]["version"],
                    report["dataset"]["sha256"],
                    report["dataset"]["sample_count"],
                    json.dumps(summary, ensure_ascii=False),
                ),
            )
            connection.executemany(
                "INSERT INTO evaluation_cases(run_id, case_index, case_json) VALUES (?, ?, ?)",
                [
                    (report["run_id"], index, json.dumps(case, ensure_ascii=False))
                    for index, case in enumerate(report["cases"])
                ],
            )

    def list_runs(self, limit: int = 50) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT run_id, created_at, provider, model, dataset_name,
                    dataset_version, dataset_sha256, sample_count, report_json
                FROM evaluation_runs ORDER BY created_at DESC LIMIT ?""",
                (max(1, min(int(limit), 200)),),
            ).fetchall()
        summaries = []
        for row in rows:
            report = json.loads(row["report_json"])
            summaries.append({
                "run_id": row["run_id"],
                "executed_at": row["created_at"],
                "provider": row["provider"],
                "model": row["model"],
                "dataset": {
                    "name": row["dataset_name"],
                    "version": row["dataset_version"],
                    "sha256": row["dataset_sha256"],
                    "sample_count": row["sample_count"],
                },
                "metrics": report["metrics"],
                "limitations": report["limitations"],
            })
        return summaries

    def get_report(self, run_id: str) -> dict | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT report_json FROM evaluation_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        return json.loads(row["report_json"]) if row else None

    def get_cases(self, run_id: str) -> list[dict] | None:
        with self.connect() as connection:
            run_exists = connection.execute(
                "SELECT 1 FROM evaluation_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if not run_exists:
                return None
            rows = connection.execute(
                "SELECT case_json FROM evaluation_cases WHERE run_id = ? ORDER BY case_index",
                (run_id,),
            ).fetchall()
        return [json.loads(row["case_json"]) for row in rows]

    def get_csv(self, run_id: str) -> str | None:
        cases = self.get_cases(run_id)
        if cases is None or not cases:
            return None
        output = io.StringIO(newline="")
        fields = (
            "case_id", "text", "expected", "predicted", "confidence", "requires_review",
            "status", "workflow", "expected_workflow", "correct_route",
            "response_latency_ms", "classification_latency_ms", "execution_latency_ms",
            "error",
        )
        writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for case in cases:
            safe_case = {
                key: self._spreadsheet_safe(value)
                for key, value in case.items()
            }
            writer.writerow(safe_case)
        return output.getvalue()

    @staticmethod
    def _spreadsheet_safe(value):
        if isinstance(value, str) and value.lstrip(" \t\r\n").startswith(("=", "+", "-", "@")):
            return "'" + value
        return value
