"""SQLite persistence for request, review, and workflow outcomes."""

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone


class HistoryService:
    def __init__(self, database_path: str):
        self.database_path = database_path
        self.initialize()

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self):
        with self.connect() as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS requests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    request_text TEXT NOT NULL,
                    category TEXT,
                    confidence REAL,
                    explanation TEXT,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    validation_status TEXT NOT NULL,
                    review_reason TEXT,
                    workflow TEXT,
                    status TEXT NOT NULL,
                    result TEXT,
                    error TEXT,
                    reviewer_feedback TEXT,
                    created_at TEXT NOT NULL,
                    latency_ms REAL
                )"""
            )
            connection.execute("CREATE INDEX IF NOT EXISTS idx_requests_created_at ON requests(created_at)")
            connection.execute("CREATE INDEX IF NOT EXISTS idx_requests_category_status ON requests(category, status)")
            connection.execute(
                """CREATE TABLE IF NOT EXISTS agent_executions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    request_id INTEGER NOT NULL,
                    agent TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    inputs TEXT NOT NULL,
                    outputs TEXT,
                    error TEXT,
                    checker_feedback TEXT,
                    retry_attempt INTEGER NOT NULL DEFAULT 1,
                    FOREIGN KEY(request_id) REFERENCES requests(id)
                )"""
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_agent_executions_request ON agent_executions(request_id, id)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_agent_executions_agent_request_status "
                "ON agent_executions(agent, request_id, status)"
            )

    def create(self, **fields) -> dict:
        fields.setdefault("created_at", datetime.now(timezone.utc).isoformat())
        fields["metadata"] = json.dumps(fields.get("metadata", {}))
        with self.connect() as connection:
            cursor = connection.execute(
                """INSERT INTO requests
                (request_text, category, confidence, explanation, metadata, validation_status,
                 review_reason, workflow, status, result, error, reviewer_feedback, created_at, latency_ms)
                VALUES (:request_text, :category, :confidence, :explanation, :metadata, :validation_status,
                 :review_reason, :workflow, :status, :result, :error, :reviewer_feedback, :created_at, :latency_ms)""",
                {key: fields.get(key) for key in (
                    "request_text", "category", "confidence", "explanation", "metadata", "validation_status",
                    "review_reason", "workflow", "status", "result", "error", "reviewer_feedback", "created_at", "latency_ms"
                )},
            )
            request_id = cursor.lastrowid
        return self.get(request_id)

    def get(self, request_id: int) -> dict | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM requests WHERE id = ?", (request_id,)).fetchone()
        return self._serialize(row) if row else None

    def update(self, request_id: int, **fields) -> dict | None:
        if "metadata" in fields:
            fields["metadata"] = json.dumps(fields["metadata"])
        if "result" in fields and fields["result"] is not None and not isinstance(fields["result"], str):
            fields["result"] = json.dumps(fields["result"])
        assignments = ", ".join(f"{field} = :{field}" for field in fields)
        with self.connect() as connection:
            connection.execute(
                f"UPDATE requests SET {assignments} WHERE id = :id",
                {**fields, "id": request_id},
            )
        return self.get(request_id)

    def start_agent_execution(
        self,
        request_id: int,
        agent: str,
        inputs,
        started_at: str,
        retry_attempt: int = 1,
    ) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                """INSERT INTO agent_executions
                (request_id, agent, status, started_at, inputs, retry_attempt)
                VALUES (?, ?, 'running', ?, ?, ?)""",
                (request_id, agent, started_at, self._json(inputs), retry_attempt),
            )
            return cursor.lastrowid

    def finish_agent_execution(
        self,
        execution_id: int,
        status: str,
        completed_at: str,
        output=None,
        error: str | None = None,
        checker_feedback: str | None = None,
    ):
        with self.connect() as connection:
            connection.execute(
                """UPDATE agent_executions
                SET status = ?, completed_at = ?, outputs = ?, error = ?, checker_feedback = ?
                WHERE id = ?""",
                (
                    status,
                    completed_at,
                    self._json(output) if output is not None else None,
                    error,
                    checker_feedback,
                    execution_id,
                ),
            )

    def agent_trace(self, request_id: int) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM agent_executions WHERE request_id = ? ORDER BY id",
                (request_id,),
            ).fetchall()
        return [
            {
                **dict(row),
                "inputs": json.loads(row["inputs"]),
                "outputs": json.loads(row["outputs"]) if row["outputs"] else None,
            }
            for row in rows
        ]

    def latest_agent_activity(self) -> dict | None:
        with self.connect() as connection:
            row = connection.execute(
                """SELECT r.id, r.status, r.workflow
                FROM requests r
                WHERE EXISTS (SELECT 1 FROM agent_executions a WHERE a.request_id = r.id)
                ORDER BY CASE WHEN EXISTS (
                    SELECT 1 FROM agent_executions a
                    WHERE a.request_id = r.id AND a.status = 'running'
                ) THEN 0 ELSE 1 END, r.id DESC
                LIMIT 1"""
            ).fetchone()
        if not row:
            return None
        return {
            "request_id": row["id"],
            "status": row["status"],
            "workflow": row["workflow"],
            "trace": self.agent_trace(row["id"]),
        }

    def list(
        self,
        search: str = "",
        status: str = "",
        limit: int = 100,
        category: str = "",
        from_date: str = "",
        to_date: str = "",
    ) -> list[dict]:
        query = "SELECT * FROM requests WHERE 1=1"
        values = []
        if search:
            query += " AND (request_text LIKE ? OR category LIKE ? OR workflow LIKE ?)"
            values.extend([f"%{search}%"] * 3)
        if status:
            query += " AND status = ?"
            values.append(status)
        if category:
            query += " AND category = ?"
            values.append(category)
        if from_date:
            query += " AND created_at >= ?"
            values.append(from_date)
        if to_date:
            query += " AND created_at < date(?, '+1 day')"
            values.append(to_date)
        query += " ORDER BY id DESC LIMIT ?"
        values.append(max(1, min(int(limit), 500)))
        with self.connect() as connection:
            rows = connection.execute(query, values).fetchall()
        return [self._serialize(row) for row in rows]

    def stats(self) -> dict:
        with self.connect() as connection:
            row_stats = connection.execute(
                """SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN validation_status = 'passed' THEN 1 ELSE 0 END) AS classified,
                    SUM(CASE WHEN workflow IS NOT NULL AND status IN ('completed', 'failed') THEN 1 ELSE 0 END) AS routed,
                    SUM(CASE WHEN status IN ('pending_review', 'awaiting_clarification') THEN 1 ELSE 0 END) AS review,
                    SUM(CASE WHEN validation_status = 'review' THEN 1 ELSE 0 END) AS escalated,
                    SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed_requests,
                    AVG(latency_ms) AS average_latency,
                    MIN(confidence) AS confidence_min,
                    MAX(confidence) AS confidence_max
                FROM requests"""
            ).fetchone()
            execution_stats = self._execution_metrics(connection)
        failed_execution_count = execution_stats["failed"]
        execution_count = execution_stats["completed"] + failed_execution_count
        return {
            "total_requests": row_stats["total"] or 0,
            "classified_requests": row_stats["classified"] or 0,
            "routed_requests": row_stats["routed"] or 0,
            "human_review_requests": row_stats["review"] or 0,
            "failed_executions": failed_execution_count,
            "failed_requests": row_stats["failed_requests"] or 0,
            "workflow_execution_success_rate": round(
                execution_stats["completed"] / execution_count, 4
            ) if execution_count else 0,
            "human_review_rate": round((row_stats["escalated"] or 0) / row_stats["total"], 4) if row_stats["total"] else 0,
            "classification_success_rate": round((row_stats["classified"] or 0) / row_stats["total"], 4) if row_stats["total"] else 0,
            "routing_success_rate": round((row_stats["routed"] or 0) / row_stats["total"], 4) if row_stats["total"] else 0,
            "average_latency_ms": round(row_stats["average_latency"], 2) if row_stats["average_latency"] is not None else 0,
            "confidence_min": row_stats["confidence_min"],
            "confidence_max": row_stats["confidence_max"],
            "average_execution_ms": round(execution_stats["average_ms"], 2) if execution_stats["average_ms"] is not None else 0,
        }

    @staticmethod
    def _execution_metrics(connection, from_date: str = "", to_date: str = "") -> dict:
        clauses = []
        values = []
        if from_date:
            clauses.append("r.created_at >= ?")
            values.append(from_date)
        if to_date:
            clauses.append("r.created_at < date(?, '+1 day')")
            values.append(to_date)
        request_date_filter = "".join(f" AND {clause}" for clause in clauses)
        query = f"""WITH execution_records AS (
            SELECT a.status,
                (julianday(a.completed_at) - julianday(a.started_at)) * 86400000.0 AS duration_ms
            FROM agent_executions a
            JOIN requests r ON r.id = a.request_id
            WHERE a.agent = 'execution_agent' AND a.status IN ('completed', 'failed')
                AND a.completed_at IS NOT NULL{request_date_filter}
            UNION ALL
            SELECT r.status, NULL AS duration_ms
            FROM requests r
            WHERE r.workflow IS NOT NULL AND r.status IN ('completed', 'failed')
                AND NOT EXISTS (
                    SELECT 1 FROM agent_executions a
                    WHERE a.request_id = r.id AND a.agent = 'execution_agent'
                ){request_date_filter}
        )
        SELECT
            SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS completed,
            SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed,
            AVG(duration_ms) AS average_ms
        FROM execution_records"""
        result = connection.execute(query, values + values).fetchone()
        return {
            "completed": result["completed"] or 0,
            "failed": result["failed"] or 0,
            "average_ms": result["average_ms"],
        }

    def analytics(self, from_date: str = "", to_date: str = "") -> dict:
        clauses = []
        values = []
        if from_date:
            clauses.append("created_at >= ?")
            values.append(from_date)
        if to_date:
            clauses.append("created_at < date(?, '+1 day')")
            values.append(to_date)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.connect() as connection:
            summary = connection.execute(
                f"""SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN validation_status = 'passed' THEN 1 ELSE 0 END) AS classified,
                    SUM(CASE WHEN workflow IS NOT NULL AND status IN ('completed', 'failed') THEN 1 ELSE 0 END) AS routed,
                    SUM(CASE WHEN status IN ('pending_review', 'awaiting_clarification') THEN 1 ELSE 0 END) AS pending_reviews,
                    SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed_requests
                FROM requests{where}""",
                values,
            ).fetchone()
            requests_over_time = connection.execute(
                f"SELECT date(created_at) AS bucket, COUNT(*) AS count FROM requests{where} "
                "GROUP BY date(created_at) ORDER BY bucket",
                values,
            ).fetchall()
            categories = connection.execute(
                f"SELECT COALESCE(category, 'UNKNOWN') AS category, COUNT(*) AS count FROM requests{where} "
                "GROUP BY COALESCE(category, 'UNKNOWN') ORDER BY category",
                values,
            ).fetchall()
            confidence_bins = connection.execute(
                f"""SELECT CASE
                    WHEN confidence < 0.2 THEN 0
                    WHEN confidence < 0.4 THEN 1
                    WHEN confidence < 0.6 THEN 2
                    WHEN confidence < 0.8 THEN 3
                    ELSE 4 END AS bin, COUNT(*) AS count
                    FROM requests{where + ' AND' if where else ' WHERE'} confidence IS NOT NULL
                    GROUP BY bin""",
                values,
            ).fetchall()
            reviews_over_time = connection.execute(
                f"""SELECT date(created_at) AS bucket, COUNT(*) AS count FROM requests
                {where + ' AND' if where else ' WHERE'} validation_status = 'review'
                GROUP BY date(created_at) ORDER BY bucket""",
                values,
            ).fetchall()
            agent_rows = connection.execute(
                f"""SELECT a.agent, COUNT(*) AS count,
                    AVG((julianday(a.completed_at) - julianday(a.started_at)) * 86400000.0) AS average_ms
                FROM agent_executions a
                JOIN requests r ON r.id = a.request_id
                WHERE a.completed_at IS NOT NULL
                {"AND r.created_at >= ?" if from_date else ""}
                {"AND r.created_at < date(?, '+1 day')" if to_date else ""}
                GROUP BY a.agent ORDER BY a.agent""",
                values,
            ).fetchall()
            execution_metrics = self._execution_metrics(connection, from_date, to_date)
        bins = [
            {"label": f"{lower:.1f}–{upper:.1f}", "count": 0}
            for lower, upper in ((0, .2), (.2, .4), (.4, .6), (.6, .8), (.8, 1.01))
        ]
        for row in confidence_bins:
            bins[row["bin"]]["count"] = row["count"]
        return {
            "kpis": {
                "total_requests": summary["total"] or 0,
                "classified_requests": summary["classified"] or 0,
                "routed_requests": summary["routed"] or 0,
                "pending_reviews": summary["pending_reviews"] or 0,
                "failed_executions": execution_metrics["failed"],
                "average_execution_ms": round(execution_metrics["average_ms"], 2) if execution_metrics["average_ms"] is not None else 0,
            },
            "requests_over_time": [{"date": row["bucket"], "count": row["count"]} for row in requests_over_time],
            "category_distribution": [{"category": row["category"], "count": row["count"]} for row in categories],
            "confidence_distribution": bins,
            "execution_outcomes": [
                {"status": status, "count": execution_metrics[status]}
                for status in ("completed", "failed")
            ],
            "human_reviews_over_time": [{"date": row["bucket"], "count": row["count"]} for row in reviews_over_time],
            "agent_latency": [
                {"agent": row["agent"], "count": row["count"], "average_ms": round(row["average_ms"], 2)}
                for row in agent_rows
            ],
            "evaluation": None,
            "memory": {"available": False, "reason": "No memory modules or memory tables are configured."},
        }

    @staticmethod
    def _serialize(row):
        record = dict(row)
        record["metadata"] = json.loads(record["metadata"] or "{}")
        if record["result"]:
            try:
                record["result"] = json.loads(record["result"])
            except json.JSONDecodeError:
                pass
        return record

    @staticmethod
    def _json(value):
        def encode(item):
            if is_dataclass(item):
                return asdict(item)
            raise TypeError(f"Object of type {type(item).__name__} is not JSON serializable")

        return json.dumps(value, default=encode)