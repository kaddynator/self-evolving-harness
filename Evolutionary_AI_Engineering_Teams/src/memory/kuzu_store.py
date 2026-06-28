from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import kuzu


class KuzuStore:
    """Graph store for agent topology gene pool (embedded, no server)."""

    def __init__(self, db_path: str = "/tmp/kuzu_harness"):
        Path(db_path).mkdir(parents=True, exist_ok=True)
        self._db = kuzu.Database(db_path)
        self._conn = kuzu.Connection(self._db)
        self._init_schema()

    def _init_schema(self) -> None:
        stmts = [
            "CREATE NODE TABLE IF NOT EXISTS Task(id STRING, description STRING, PRIMARY KEY(id))",
            "CREATE NODE TABLE IF NOT EXISTS Workflow(id STRING, score DOUBLE, PRIMARY KEY(id))",
            "CREATE NODE TABLE IF NOT EXISTS AgentNode(id STRING, model STRING, prompt STRING, tools STRING, PRIMARY KEY(id))",
            "CREATE NODE TABLE IF NOT EXISTS Tool(name STRING, PRIMARY KEY(name))",
            "CREATE REL TABLE IF NOT EXISTS RAN(FROM Task TO Workflow)",
            "CREATE REL TABLE IF NOT EXISTS HAS_NODE(FROM Workflow TO AgentNode)",
            "CREATE REL TABLE IF NOT EXISTS CONNECTS_TO(FROM AgentNode TO AgentNode)",
            "CREATE REL TABLE IF NOT EXISTS USES_TOOL(FROM AgentNode TO Tool)",
            "CREATE REL TABLE IF NOT EXISTS SIMILAR_TO(FROM Task TO Task, score DOUBLE)",
        ]
        for s in stmts:
            try:
                self._conn.execute(s)
            except Exception:
                pass

    def upsert_workflow(self, workflow_id: str, score: float, task_id: str, task_desc: str, agents: List[Dict[str, Any]], edges: List[Dict[str, Any]]) -> None:
        self._conn.execute(
            "MERGE (t:Task {id: $id}) ON MATCH SET t.description = $desc ON CREATE SET t.description = $desc",
            {"id": task_id, "desc": task_desc},
        )
        self._conn.execute(
            "MERGE (w:Workflow {id: $id}) ON MATCH SET w.score = $score ON CREATE SET w.score = $score",
            {"id": workflow_id, "score": score},
        )
        try:
            self._conn.execute(
                "MATCH (t:Task {id: $tid}), (w:Workflow {id: $wid}) MERGE (t)-[:RAN]->(w)",
                {"tid": task_id, "wid": workflow_id},
            )
        except Exception:
            pass

        for agent in agents:
            node_id = f"{workflow_id}_{agent['id']}"
            self._conn.execute(
                "MERGE (a:AgentNode {id: $id}) ON MATCH SET a.model = $model, a.prompt = $prompt, a.tools = $tools ON CREATE SET a.model = $model, a.prompt = $prompt, a.tools = $tools",
                {"id": node_id, "model": agent.get("model", ""), "prompt": agent.get("prompt", "")[:500], "tools": json.dumps(agent.get("tools", []))},
            )
            try:
                self._conn.execute(
                    "MATCH (w:Workflow {id: $wid}), (a:AgentNode {id: $aid}) MERGE (w)-[:HAS_NODE]->(a)",
                    {"wid": workflow_id, "aid": node_id},
                )
            except Exception:
                pass

        for edge in edges:
            from_id = f"{workflow_id}_{edge['from']}"
            to_id = f"{workflow_id}_{edge['to']}"
            try:
                self._conn.execute(
                    "MATCH (a:AgentNode {id: $fid}), (b:AgentNode {id: $tid}) MERGE (a)-[:CONNECTS_TO]->(b)",
                    {"fid": from_id, "tid": to_id},
                )
            except Exception:
                pass

    def get_top_topologies(self, task_ids: List[str], limit: int = 3) -> List[Dict[str, Any]]:
        if not task_ids:
            return []
        placeholders = ", ".join(f"'{tid}'" for tid in task_ids)
        try:
            result = self._conn.execute(
                f"MATCH (t:Task)-[:RAN]->(w:Workflow)-[:HAS_NODE]->(a:AgentNode) "
                f"WHERE t.id IN [{placeholders}] "
                f"RETURN w.id AS workflow_id, w.score AS score, collect(a.id) AS nodes "
                f"ORDER BY w.score DESC LIMIT {limit}"
            )
            rows = []
            while result.has_next():
                r = result.get_next()
                rows.append({"workflow_id": r[0], "score": r[1], "nodes": r[2]})
            return rows
        except Exception:
            return []
