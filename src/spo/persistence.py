"""SQLite persistence helpers for accounts, jobs, tasks, and mappings."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from threading import RLock
from typing import TYPE_CHECKING, Any, TypedDict, Unpack

from spo.models import JobStatus, TaskState
from spo.utils import json_dumps, json_loads, utcnow

if TYPE_CHECKING:
    from pathlib import Path

JOB_UPDATE_FIELDS = frozenset(
    {
        "current_collection_kind",
        "finished_at",
        "last_error",
        "phase",
        "resume_token",
        "started_at",
        "status",
        "updated_at",
    },
)
JOB_COUNTER_FIELDS = frozenset(
    {
        "progress_applied_count",
        "progress_failed_count",
        "progress_skipped_count",
        "progress_snapshot_count",
    },
)
TASK_UPDATE_FIELDS = frozenset(
    {
        "cooldown_until",
        "last_error",
        "payload_json",
        "state",
        "target_entity_id",
        "updated_at",
    },
)


class JobUpdateFields(TypedDict, total=False):
    """Typed partial updates for job rows."""

    current_collection_kind: str | None
    finished_at: str | None
    last_error: str | None
    phase: str
    resume_token: str | None
    started_at: str | None
    status: str
    updated_at: str


class TaskUpdateFields(TypedDict, total=False):
    """Typed partial updates for task rows."""

    cooldown_until: str | None
    last_error: str | None
    payload_json: str
    state: str
    target_entity_id: str | None
    updated_at: str


@dataclass(slots=True)
class TaskUpsert:
    """Input payload for inserting or updating one task row."""

    job_id: int
    dedupe_key: str
    action: str
    collection_kind: str
    payload: dict[str, Any]
    source_entity_id: int | None = None
    target_entity_id: str | None = None
    state: str = TaskState.PENDING.value
    last_error: str | None = None
    cooldown_until: str | None = None


def _validate_update_fields(fields: dict[str, object], allowed_fields: frozenset[str], *, entity: str) -> None:
    unexpected = sorted(set(fields).difference(allowed_fields))
    if unexpected:
        joined = ", ".join(unexpected)
        message = f"Unsupported {entity} update fields: {joined}"
        raise ValueError(message)


class Database:
    """Persist application state in a SQLite database."""

    def __init__(self, path: Path) -> None:
        """Initialize the database wrapper for the given file path."""
        self.path = path
        self._lock = RLock()

    def connect(self) -> sqlite3.Connection:
        """Open a SQLite connection configured for this application."""
        connection = sqlite3.connect(self.path, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def initialize(self) -> None:
        """Create the database schema if it does not already exist."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, closing(self.connect()) as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS accounts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    service TEXT NOT NULL,
                    remote_account_id TEXT,
                    display_name TEXT,
                    auth_status TEXT NOT NULL,
                    oauth_state TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_accounts_service_remote
                    ON accounts(service, remote_account_id);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_accounts_oauth_state
                    ON accounts(oauth_state);

                CREATE TABLE IF NOT EXISTS service_credentials (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
                    credential_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    schema_version INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_validated_at TEXT
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_credentials_account_type
                    ON service_credentials(account_id, credential_type);

                CREATE TABLE IF NOT EXISTS jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_account_id INTEGER NOT NULL REFERENCES accounts(id),
                    target_account_id INTEGER NOT NULL REFERENCES accounts(id),
                    scope_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    phase TEXT NOT NULL,
                    current_collection_kind TEXT,
                    progress_snapshot_count INTEGER NOT NULL DEFAULT 0,
                    progress_applied_count INTEGER NOT NULL DEFAULT 0,
                    progress_skipped_count INTEGER NOT NULL DEFAULT 0,
                    progress_failed_count INTEGER NOT NULL DEFAULT 0,
                    started_at TEXT,
                    finished_at TEXT,
                    last_error TEXT,
                    resume_token TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS source_entities (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                    dedupe_key TEXT NOT NULL UNIQUE,
                    collection_kind TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    parent_source_id INTEGER REFERENCES source_entities(id) ON DELETE CASCADE,
                    canonical_payload TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    order_index INTEGER,
                    page_cursor TEXT,
                    fingerprint TEXT NOT NULL,
                    snapshot_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_source_entities_job_kind
                    ON source_entities(job_id, collection_kind, parent_source_id, order_index);

                CREATE TABLE IF NOT EXISTS entity_mappings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_service TEXT NOT NULL,
                    target_service TEXT NOT NULL,
                    source_fingerprint TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    target_kind TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    match_method TEXT NOT NULL,
                    last_verified_at TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_entity_mappings_unique
                    ON entity_mappings(source_service, target_service, source_fingerprint, target_kind);

                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                    dedupe_key TEXT NOT NULL UNIQUE,
                    action TEXT NOT NULL,
                    collection_kind TEXT NOT NULL,
                    source_entity_id INTEGER REFERENCES source_entities(id) ON DELETE CASCADE,
                    target_entity_id TEXT,
                    payload_json TEXT NOT NULL,
                    state TEXT NOT NULL,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    cooldown_until TEXT,
                    last_error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_tasks_job_state
                    ON tasks(job_id, state, collection_kind);

                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                    level TEXT NOT NULL,
                    message TEXT NOT NULL,
                    detail_json TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_events_job_id
                    ON events(job_id, id);

                CREATE TABLE IF NOT EXISTS service_cooldowns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
                    operation TEXT NOT NULL,
                    cooldown_until TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    vendor_hint TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_cooldowns_account_until
                    ON service_cooldowns(account_id, cooldown_until);
                """,
            )
            connection.commit()

    def _execute(self, query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self._lock, closing(self.connect()) as connection:
            cursor = connection.execute(query, params)
            rows = [dict(row) for row in cursor.fetchall()]
            connection.commit()
            return rows

    def _execute_one(self, query: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        rows = self._execute(query, params)
        return rows[0] if rows else None

    def _write(self, query: str, params: tuple[Any, ...] = ()) -> int:
        with self._lock, closing(self.connect()) as connection:
            cursor = connection.execute(query, params)
            connection.commit()
            if cursor.lastrowid is None:
                raise RuntimeError("Database write did not return a row id.")
            return cursor.lastrowid

    def _write_script(self, statements: list[tuple[str, tuple[Any, ...]]]) -> None:
        with self._lock, closing(self.connect()) as connection:
            for query, params in statements:
                connection.execute(query, params)
            connection.commit()

    def list_accounts(self) -> list[dict[str, Any]]:
        """Return all stored accounts ordered for display."""
        return self._execute("SELECT * FROM accounts ORDER BY service, display_name, id")

    def get_account(self, account_id: int) -> dict[str, Any] | None:
        """Return a stored account by its primary key."""
        return self._execute_one("SELECT * FROM accounts WHERE id = ?", (account_id,))

    def find_account_by_service(self, service: str) -> list[dict[str, Any]]:
        """Return accounts for a service ordered by most recent update."""
        return self._execute(
            "SELECT * FROM accounts WHERE service = ? ORDER BY updated_at DESC",
            (service,),
        )

    def find_account_by_oauth_state(self, service: str, oauth_state: str) -> dict[str, Any] | None:
        """Return the account associated with an OAuth callback state."""
        return self._execute_one(
            "SELECT * FROM accounts WHERE service = ? AND oauth_state = ?",
            (service, oauth_state),
        )

    def upsert_account(
        self,
        *,
        service: str,
        auth_status: str,
        account_id: int | None = None,
        remote_account_id: str | None = None,
        display_name: str | None = None,
        oauth_state: str | None = None,
    ) -> int:
        """Insert or update an account row and return its ID."""
        now = utcnow()
        if account_id is not None:
            self._write(
                """
                UPDATE accounts
                SET remote_account_id = ?, display_name = ?, auth_status = ?, oauth_state = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    remote_account_id,
                    display_name,
                    auth_status,
                    oauth_state,
                    now,
                    account_id,
                ),
            )
            return account_id

        existing = None
        if remote_account_id:
            existing = self._execute_one(
                "SELECT * FROM accounts WHERE service = ? AND remote_account_id = ?",
                (service, remote_account_id),
            )
        if existing:
            return self.upsert_account(
                service=service,
                auth_status=auth_status,
                account_id=int(existing["id"]),
                remote_account_id=remote_account_id,
                display_name=display_name,
                oauth_state=oauth_state,
            )
        return self._write(
            """
            INSERT INTO accounts(
                service,
                remote_account_id,
                display_name,
                auth_status,
                oauth_state,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                service,
                remote_account_id,
                display_name,
                auth_status,
                oauth_state,
                now,
                now,
            ),
        )

    def save_credentials(
        self,
        account_id: int,
        credential_type: str,
        payload: dict[str, Any],
        *,
        last_validated_at: str | None = None,
    ) -> int:
        """Insert or update credentials for an account and return the row ID."""
        now = utcnow()
        existing = self._execute_one(
            """
            SELECT id FROM service_credentials
            WHERE account_id = ? AND credential_type = ?
            """,
            (account_id, credential_type),
        )
        if existing:
            self._write(
                """
                UPDATE service_credentials
                SET payload_json = ?, updated_at = ?, last_validated_at = ?
                WHERE id = ?
                """,
                (
                    json_dumps(payload),
                    now,
                    last_validated_at,
                    int(existing["id"]),
                ),
            )
            return int(existing["id"])
        return self._write(
            """
            INSERT INTO service_credentials(
                account_id,
                credential_type,
                payload_json,
                created_at,
                updated_at,
                last_validated_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                account_id,
                credential_type,
                json_dumps(payload),
                now,
                now,
                last_validated_at,
            ),
        )

    def get_credentials(self, account_id: int) -> dict[str, Any] | None:
        """Return the latest credential payload stored for an account."""
        row = self._execute_one(
            """
            SELECT * FROM service_credentials
            WHERE account_id = ?
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (account_id,),
        )
        if row:
            row["payload"] = json_loads(row["payload_json"])
        return row

    def create_job(self, source_account_id: int, target_account_id: int, scope: list[str]) -> int:
        """Create a new synchronization job and return its ID."""
        now = utcnow()
        return self._write(
            """
            INSERT INTO jobs(source_account_id, target_account_id, scope_json, status, phase, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source_account_id,
                target_account_id,
                json_dumps(scope),
                JobStatus.DRAFT.value,
                JobStatus.DRAFT.value,
                now,
                now,
            ),
        )

    def get_job(self, job_id: int) -> dict[str, Any] | None:
        """Return a synchronization job by ID."""
        row = self._execute_one("SELECT * FROM jobs WHERE id = ?", (job_id,))
        if row:
            row["scope"] = json_loads(row["scope_json"]) or []
        return row

    def list_jobs(self) -> list[dict[str, Any]]:
        """Return all synchronization jobs with source and target labels."""
        rows = self._execute(
            """
            SELECT jobs.*, sa.display_name AS source_name, ta.display_name AS target_name,
                   sa.service AS source_service, ta.service AS target_service
            FROM jobs
            JOIN accounts sa ON sa.id = jobs.source_account_id
            JOIN accounts ta ON ta.id = jobs.target_account_id
            ORDER BY COALESCE(jobs.started_at, jobs.created_at) DESC, jobs.id DESC
            """,
        )
        for row in rows:
            row["scope"] = json_loads(row["scope_json"]) or []
        return rows

    def list_incomplete_jobs(self) -> list[dict[str, Any]]:
        """Return jobs that have not yet reached a terminal status."""
        terminal = (
            JobStatus.COMPLETED.value,
            JobStatus.COMPLETED_WITH_WARNINGS.value,
            JobStatus.FAILED.value,
            JobStatus.CANCELED.value,
        )
        rows = self._execute(
            """
            SELECT * FROM jobs
            WHERE status NOT IN (?, ?, ?, ?)
            ORDER BY updated_at ASC
            """,
            terminal,
        )
        for row in rows:
            row["scope"] = json_loads(row["scope_json"]) or []
        return rows

    def update_job(self, job_id: int, **fields: Unpack[JobUpdateFields]) -> None:
        """Apply a partial update to a job row."""
        if not fields:
            return
        updated_fields: dict[str, object] = {**fields, "updated_at": utcnow()}
        _validate_update_fields(updated_fields, JOB_UPDATE_FIELDS, entity="job")
        assignments = ", ".join(f"{key} = ?" for key in updated_fields)
        params = (*updated_fields.values(), job_id)
        query = f"UPDATE jobs SET {assignments} WHERE id = ?"  # noqa: S608 - keys validated against JOB_UPDATE_FIELDS
        self._write(query, params)

    def increment_job_counter(self, job_id: int, column: str, amount: int = 1) -> None:
        """Increment a numeric progress counter on a job."""
        if column not in JOB_COUNTER_FIELDS:
            message = f"Unsupported job counter column: {column}"
            raise ValueError(message)
        query = f"""
            UPDATE jobs
            SET {column} = {column} + ?, updated_at = ?
            WHERE id = ?
            """  # noqa: S608 - column validated against JOB_COUNTER_FIELDS
        self._write(
            query,
            (amount, utcnow(), job_id),
        )

    def append_event(
        self,
        job_id: int,
        level: str,
        message: str,
        detail: dict[str, Any] | None = None,
    ) -> int:
        """Append an event to a job's event stream and return its ID."""
        now = utcnow()
        return self._write(
            """
            INSERT INTO events(job_id, level, message, detail_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (job_id, level, message, json_dumps(detail) if detail else None, now),
        )

    def list_events(self, job_id: int, *, after_id: int = 0) -> list[dict[str, Any]]:
        """Return job events created after the provided event ID."""
        rows = self._execute(
            """
            SELECT * FROM events
            WHERE job_id = ? AND id > ?
            ORDER BY id ASC
            """,
            (job_id, after_id),
        )
        for row in rows:
            row["detail"] = json_loads(row["detail_json"])
        return rows

    def upsert_source_entity(
        self,
        *,
        job_id: int,
        dedupe_key: str,
        collection_kind: str,
        source_id: str,
        canonical_payload: dict[str, Any],
        payload: dict[str, Any],
        fingerprint: str,
        snapshot_hash: str,
        parent_source_id: int | None = None,
        order_index: int | None = None,
        page_cursor: str | None = None,
    ) -> tuple[int, bool]:
        """Insert a source snapshot entity unless it already exists."""
        existing = self._execute_one("SELECT id FROM source_entities WHERE dedupe_key = ?", (dedupe_key,))
        if existing:
            return int(existing["id"]), False
        entity_id = self._write(
            """
            INSERT INTO source_entities(job_id, dedupe_key, collection_kind, source_id, parent_source_id,
                                        canonical_payload, payload_json, order_index, page_cursor, fingerprint,
                                        snapshot_hash, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                dedupe_key,
                collection_kind,
                source_id,
                parent_source_id,
                json_dumps(canonical_payload),
                json_dumps(payload),
                order_index,
                page_cursor,
                fingerprint,
                snapshot_hash,
                utcnow(),
            ),
        )
        return entity_id, True

    def list_source_entities(
        self,
        job_id: int,
        *,
        collection_kind: str | None = None,
        parent_source_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return stored source entities filtered by collection and parent."""
        query = "SELECT * FROM source_entities WHERE job_id = ?"
        params: list[Any] = [job_id]
        if collection_kind is not None:
            query += " AND collection_kind = ?"
            params.append(collection_kind)
        if parent_source_id is None:
            query += " AND parent_source_id IS NULL"
        else:
            query += " AND parent_source_id = ?"
            params.append(parent_source_id)
        query += " ORDER BY COALESCE(order_index, 0), id"
        rows = self._execute(query, tuple(params))
        for row in rows:
            row["canonical"] = json_loads(row["canonical_payload"])
            row["payload"] = json_loads(row["payload_json"])
        return rows

    def count_source_entities(
        self,
        job_id: int,
        *,
        collection_kind: str | None = None,
        parent_source_id: int | None = None,
    ) -> int:
        """Count stored source entities for a job and optional parent."""
        query = "SELECT COUNT(*) AS count FROM source_entities WHERE job_id = ?"
        params: list[Any] = [job_id]
        if collection_kind is not None:
            query += " AND collection_kind = ?"
            params.append(collection_kind)
        if parent_source_id is None:
            query += " AND parent_source_id IS NULL"
        else:
            query += " AND parent_source_id = ?"
            params.append(parent_source_id)
        row = self._execute_one(query, tuple(params))
        return int(row["count"]) if row else 0

    def upsert_mapping(
        self,
        *,
        source_service: str,
        target_service: str,
        source_fingerprint: str,
        target_id: str,
        target_kind: str,
        confidence: float,
        match_method: str,
    ) -> None:
        """Insert or update a cached mapping between source and target items."""
        now = utcnow()
        existing = self._execute_one(
            """
            SELECT id FROM entity_mappings
            WHERE source_service = ? AND target_service = ? AND source_fingerprint = ? AND target_kind = ?
            """,
            (source_service, target_service, source_fingerprint, target_kind),
        )
        if existing:
            self._write(
                """
                UPDATE entity_mappings
                SET target_id = ?, confidence = ?, match_method = ?, last_verified_at = ?
                WHERE id = ?
                """,
                (target_id, confidence, match_method, now, int(existing["id"])),
            )
            return
        self._write(
            """
            INSERT INTO entity_mappings(source_service, target_service, source_fingerprint, target_id,
                                        target_kind, confidence, match_method, last_verified_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source_service,
                target_service,
                source_fingerprint,
                target_id,
                target_kind,
                confidence,
                match_method,
                now,
            ),
        )

    def find_mapping(
        self,
        *,
        source_service: str,
        target_service: str,
        source_fingerprint: str,
        target_kind: str,
    ) -> dict[str, Any] | None:
        """Return a cached mapping for a source fingerprint and target kind."""
        return self._execute_one(
            """
            SELECT * FROM entity_mappings
            WHERE source_service = ? AND target_service = ? AND source_fingerprint = ? AND target_kind = ?
            """,
            (source_service, target_service, source_fingerprint, target_kind),
        )

    def create_or_update_task(self, task: TaskUpsert) -> tuple[int, bool]:
        """Insert or update a synchronization task and return its ID plus creation flag."""
        now = utcnow()
        payload_json = json_dumps(task.payload)
        existing = self._execute_one("SELECT id FROM tasks WHERE dedupe_key = ?", (task.dedupe_key,))
        if existing:
            self._write(
                """
                UPDATE tasks
                SET target_entity_id = ?, payload_json = ?, state = ?, last_error = ?,
                    cooldown_until = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    task.target_entity_id,
                    payload_json,
                    task.state,
                    task.last_error,
                    task.cooldown_until,
                    now,
                    int(existing["id"]),
                ),
            )
            return int(existing["id"]), False
        task_id = self._write(
            """
            INSERT INTO tasks(job_id, dedupe_key, action, collection_kind, source_entity_id, target_entity_id,
                              payload_json, state, cooldown_until, last_error, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task.job_id,
                task.dedupe_key,
                task.action,
                task.collection_kind,
                task.source_entity_id,
                task.target_entity_id,
                payload_json,
                task.state,
                task.cooldown_until,
                task.last_error,
                now,
                now,
            ),
        )
        return task_id, True

    def get_task_by_dedupe_key(self, dedupe_key: str) -> dict[str, Any] | None:
        """Return a task looked up by its deduplication key."""
        row = self._execute_one("SELECT * FROM tasks WHERE dedupe_key = ?", (dedupe_key,))
        if row:
            row["payload"] = json_loads(row["payload_json"])
        return row

    def list_tasks(self, job_id: int) -> list[dict[str, Any]]:
        """Return all tasks associated with a job."""
        rows = self._execute(
            "SELECT * FROM tasks WHERE job_id = ? ORDER BY id ASC",
            (job_id,),
        )
        for row in rows:
            row["payload"] = json_loads(row["payload_json"])
        return rows

    def update_task(self, task_id: int, **fields: Unpack[TaskUpdateFields]) -> None:
        """Apply a partial update to a task row."""
        if not fields:
            return
        updated_fields: dict[str, object] = {**fields, "updated_at": utcnow()}
        _validate_update_fields(updated_fields, TASK_UPDATE_FIELDS, entity="task")
        assignments = ", ".join(f"{key} = ?" for key in updated_fields)
        params = (*updated_fields.values(), task_id)
        query = f"UPDATE tasks SET {assignments} WHERE id = ?"  # noqa: S608 - keys validated against TASK_UPDATE_FIELDS
        self._write(query, params)

    def set_cooldown(
        self,
        *,
        account_id: int,
        operation: str,
        cooldown_until: str,
        reason: str,
        vendor_hint: str | None = None,
    ) -> None:
        """Record a service cooldown for a specific account and operation."""
        now = utcnow()
        self._write(
            """
            INSERT INTO service_cooldowns(
                account_id,
                operation,
                cooldown_until,
                reason,
                vendor_hint,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (account_id, operation, cooldown_until, reason, vendor_hint, now, now),
        )

    def get_latest_cooldown(self, account_id: int) -> dict[str, Any] | None:
        """Return the most recent cooldown recorded for an account."""
        return self._execute_one(
            """
            SELECT * FROM service_cooldowns
            WHERE account_id = ?
            ORDER BY cooldown_until DESC, id DESC
            LIMIT 1
            """,
            (account_id,),
        )
