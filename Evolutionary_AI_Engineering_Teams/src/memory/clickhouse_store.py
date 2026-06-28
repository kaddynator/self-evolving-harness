from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

import clickhouse_connect


_INIT_SQL = [
    """
    CREATE TABLE IF NOT EXISTS tasks (
        task_id     String,
        description String,
        category    String,
        ts          DateTime DEFAULT now()
    ) ENGINE = MergeTree()
    ORDER BY (category, ts)
    """,
    """
    CREATE TABLE IF NOT EXISTS runs (
        run_id      String,
        task_id     String,
        workflow_id String,
        cost_usd    Float32,
        quality     Float32,
        score       Float32,
        ts          DateTime DEFAULT now()
    ) ENGINE = MergeTree()
    ORDER BY (task_id, ts)
    TTL ts + INTERVAL 90 DAY DELETE
    """,
    """
    CREATE TABLE IF NOT EXISTS agent_nodes (
        node_id     String,
        workflow_id String,
        model       String,
        prompt_hash String,
        tools       String
    ) ENGINE = MergeTree()
    ORDER BY workflow_id
    """,
]


class ClickHouseStore:
    """Run history store with time-decay scoring."""

    def __init__(self, host: str = "localhost", port: int = 8123,
                 user: str = "harness", password: str = "harness123", database: str = "harness"):
        self._client = clickhouse_connect.get_client(
            host=host, port=port, username=user, password=password, database=database
        )
        self._init_tables()

    def _init_tables(self) -> None:
        for sql in _INIT_SQL:
            self._client.command(sql)

    def insert_task(self, task_id: str, description: str, category: str) -> None:
        self._client.insert("tasks", [[task_id, description, category]], column_names=["task_id", "description", "category"])

    def insert_run(self, task_id: str, workflow_id: str, quality: float, cost_usd: float = 0.01) -> str:
        run_id = str(uuid.uuid4())
        score = quality / max(cost_usd, 0.001)
        self._client.insert(
            "runs",
            [[run_id, task_id, workflow_id, cost_usd, quality, score]],
            column_names=["run_id", "task_id", "workflow_id", "cost_usd", "quality", "score"],
        )
        return run_id

    def insert_agents(self, workflow_id: str, agents: List[Dict[str, Any]]) -> None:
        import hashlib, json
        rows = []
        for a in agents:
            prompt_hash = hashlib.md5(a.get("prompt", "").encode()).hexdigest()[:8]
            rows.append([str(uuid.uuid4()), workflow_id, a.get("model", ""), prompt_hash, json.dumps(a.get("tools", []))])
        if rows:
            self._client.insert("agent_nodes", rows, column_names=["node_id", "workflow_id", "model", "prompt_hash", "tools"])

    def get_top_workflows(self, task_ids: List[str], limit: int = 5) -> List[Dict[str, Any]]:
        if not task_ids:
            return []
        ids_str = ", ".join(f"'{t}'" for t in task_ids)
        # Decay: score * exp(-days_old / 30)
        rows = self._client.query(
            f"""
            SELECT workflow_id,
                   avg(score * exp(-dateDiff('day', ts, now()) / 30.0)) AS decayed_score,
                   avg(quality) AS avg_quality
            FROM runs
            WHERE task_id IN ({ids_str})
            GROUP BY workflow_id
            ORDER BY decayed_score DESC
            LIMIT {limit}
            """
        ).result_rows
        return [{"workflow_id": r[0], "decayed_score": r[1], "avg_quality": r[2]} for r in rows]

    def leaderboard(self, limit: int = 10) -> List[Dict[str, Any]]:
        rows = self._client.query(
            f"""
            SELECT workflow_id, avg(score) AS avg_score, count() AS runs
            FROM runs
            GROUP BY workflow_id
            ORDER BY avg_score DESC
            LIMIT {limit}
            """
        ).result_rows
        return [{"workflow_id": r[0], "avg_score": r[1], "runs": r[2]} for r in rows]
