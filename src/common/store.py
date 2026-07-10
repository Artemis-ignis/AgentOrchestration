"""SQLite persistence for agents, task records, and workflows.

Rows are stored as JSON blobs keyed by id — the in-memory structures stay the
source of truth at runtime; the store is a write-through backup that lets a
restarted orchestrator pick up where it left off.
"""

import json
import sqlite3
from threading import Lock
from typing import Any, Dict, List


class SqliteStore:
    def __init__(self, path: str):
        self.path = path
        self._lock = Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        with self._lock, self._conn:
            for table in ("agents", "tasks", "workflows"):
                self._conn.execute(
                    f"CREATE TABLE IF NOT EXISTS {table} (id TEXT PRIMARY KEY, data TEXT NOT NULL)"
                )

    def _upsert(self, table: str, record: Dict[str, Any]) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                f"INSERT INTO {table} (id, data) VALUES (?, ?) "
                "ON CONFLICT(id) DO UPDATE SET data = excluded.data",
                (record["id"], json.dumps(record, default=str)),
            )

    def _delete(self, table: str, record_id: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(f"DELETE FROM {table} WHERE id = ?", (record_id,))

    def _load(self, table: str) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(f"SELECT data FROM {table}").fetchall()
        return [json.loads(row[0]) for row in rows]

    # -- agents --------------------------------------------------------------

    def upsert_agent(self, agent: Dict[str, Any]) -> None:
        self._upsert("agents", agent)

    def delete_agent(self, agent_id: str) -> None:
        self._delete("agents", agent_id)

    def load_agents(self) -> List[Dict[str, Any]]:
        return self._load("agents")

    # -- tasks ---------------------------------------------------------------

    def upsert_task(self, task: Dict[str, Any]) -> None:
        self._upsert("tasks", task)

    def load_tasks(self) -> List[Dict[str, Any]]:
        return self._load("tasks")

    # -- workflows -----------------------------------------------------------

    def upsert_workflow(self, workflow: Dict[str, Any]) -> None:
        self._upsert("workflows", workflow)

    def delete_workflow(self, workflow_id: str) -> None:
        self._delete("workflows", workflow_id)

    def load_workflows(self) -> List[Dict[str, Any]]:
        return self._load("workflows")

    def close(self) -> None:
        with self._lock:
            self._conn.close()
