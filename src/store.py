"""SQLite-backed persistence for searches and dossiers.

Replaces the in-memory ``SearchManager.active_searches`` / ``dossiers`` dicts
so that:

* Restarting the server does not erase running/queued searches.
* The PDF endpoint can survive worker restarts.
* The dashboard can list historical searches.

We keep it tiny on purpose — single file, no ORM, ~80 LOC, stdlib only.
"""

import json
import logging
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("store")


SCHEMA = """
CREATE TABLE IF NOT EXISTS searches (
    search_id      TEXT PRIMARY KEY,
    status         TEXT NOT NULL,
    stage          TEXT,
    progress       TEXT,
    image_path     TEXT,
    started_at     TEXT NOT NULL,
    completed_at   TEXT,
    errors         TEXT,
    dossier        TEXT
);
CREATE INDEX IF NOT EXISTS idx_searches_started_at ON searches(started_at DESC);
"""


class Store:
    """Thread-safe SQLite store for search lifecycle data."""

    def __init__(self, db_path: str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # ``check_same_thread`` is OK because we serialise via the lock.
        self._conn = sqlite3.connect(
            str(self.db_path),
            isolation_level=None,        # autocommit
            check_same_thread=False,
        )
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(SCHEMA)
        self._lock = threading.Lock()

    # ─── Lifecycle ─────────────────────────────────────────────────────────

    def create_search(self, search_id: str, image_path: str) -> Dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO searches (search_id, status, stage, progress, image_path, started_at, errors) "
                "VALUES (?, 'running', 'uploaded', ?, ?, ?, ?)",
                (search_id, json.dumps({}), image_path, now, json.dumps([])),
            )
        return self.get_search(search_id)  # type: ignore[return-value]

    def update_stage(
        self,
        search_id: str,
        stage: str,
        progress: Optional[Dict[str, Any]] = None,
    ) -> None:
        with self._lock:
            row = self._conn.execute(
                "SELECT progress FROM searches WHERE search_id = ?", (search_id,)
            ).fetchone()
            if not row:
                return
            current = json.loads(row[0] or "{}")
            if progress:
                current.update(progress)
            self._conn.execute(
                "UPDATE searches SET stage = ?, progress = ? WHERE search_id = ?",
                (stage, json.dumps(current), search_id),
            )

    def append_error(self, search_id: str, error: str) -> None:
        with self._lock:
            row = self._conn.execute(
                "SELECT errors FROM searches WHERE search_id = ?", (search_id,)
            ).fetchone()
            if not row:
                return
            errs = json.loads(row[0] or "[]")
            errs.append(error)
            self._conn.execute(
                "UPDATE searches SET errors = ? WHERE search_id = ?",
                (json.dumps(errs), search_id),
            )

    def finalize(
        self,
        search_id: str,
        status: str,
        dossier: Optional[Dict[str, Any]] = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self._conn.execute(
                "UPDATE searches SET status = ?, completed_at = ?, dossier = ? WHERE search_id = ?",
                (status, now, json.dumps(dossier, default=str) if dossier else None, search_id),
            )

    # ─── Reads ─────────────────────────────────────────────────────────────

    def get_search(self, search_id: str) -> Optional[Dict[str, Any]]:
        row = self._conn.execute(
            "SELECT search_id, status, stage, progress, image_path, started_at, completed_at, errors "
            "FROM searches WHERE search_id = ?",
            (search_id,),
        ).fetchone()
        if not row:
            return None
        return {
            "search_id": row[0],
            "status": row[1],
            "stage": row[2],
            "progress": json.loads(row[3] or "{}"),
            "image_path": row[4],
            "started_at": row[5],
            "completed_at": row[6],
            "errors": json.loads(row[7] or "[]"),
        }

    def get_dossier(self, search_id: str) -> Optional[Dict[str, Any]]:
        row = self._conn.execute(
            "SELECT dossier FROM searches WHERE search_id = ?", (search_id,)
        ).fetchone()
        if not row or not row[0]:
            return None
        return json.loads(row[0])

    def list_recent(self, limit: int = 25) -> List[Dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT search_id, status, stage, started_at, completed_at "
            "FROM searches ORDER BY started_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [
            {
                "search_id": r[0],
                "status": r[1],
                "stage": r[2],
                "started_at": r[3],
                "completed_at": r[4],
            }
            for r in rows
        ]

    def close(self) -> None:
        self._conn.close()
