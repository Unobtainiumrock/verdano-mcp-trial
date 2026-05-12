"""Repository protocol and backends for CPG Reconciler persistence (D-021, D-025).

The ``Repository`` protocol defines a narrow interface for the four
persistence domains the system needs. Each method pair (save/get) operates
on simple Pydantic models so that any backend — in-memory, DuckDB, SQLite,
S3 — can satisfy the contract.

The ``InMemoryRepository`` is the default for the trial: zero external
dependencies, process-lifetime scope, suitable for tests and demos.

The ``DuckDBRepository`` provides persistent, file-backed storage via
DuckDB. Schema is auto-initialised on first connection (``CREATE TABLE
IF NOT EXISTS``). The ``duckdb`` package is optional — import is guarded.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from cpg_reconciler.canonical import MappingResult


class ReviewLabel(BaseModel):
    """Human correction applied to a mapping result during review."""

    model_config = ConfigDict(frozen=True)

    retailer_key_name: str
    retailer_key_gtin: str | None = None
    original_erp_sku: str | None = None
    corrected_erp_sku: str
    reviewer: str = "unknown"
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AuditEntry(BaseModel):
    """Record of a tool invocation for compliance traceability."""

    model_config = ConfigDict(frozen=True)

    tool_name: str
    retailer: str
    iso_week: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    parameters: dict[str, str] = Field(default_factory=dict)
    summary: str = ""


class ResidualRecord(BaseModel):
    """One week's residual classification for a single SKU (D-024).

    Persisted via ``Repository.save_residual_history`` and read back
    by the Markov drift strategy to build transition matrices.
    """

    model_config = ConfigDict(frozen=True)

    erp_sku: str
    iso_week: str
    direction: str
    pct_error: float
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


@runtime_checkable
class Repository(Protocol):
    """Minimal persistence contract for the CPG Reconciler system."""

    # --- Mapping cache ---

    def save_mapping(self, result: MappingResult) -> None:
        """Persist a resolved mapping result."""
        ...

    def get_mapping(self, retailer_key_name: str) -> MappingResult | None:
        """Retrieve a cached mapping by retailer key name, or None."""
        ...

    # --- Review labels ---

    def save_review_label(self, label: ReviewLabel) -> None:
        """Store a human correction for downstream calibration training."""
        ...

    def get_review_labels(self) -> list[ReviewLabel]:
        """Return all stored review labels."""
        ...

    def count_review_labels(self) -> int:
        """How many labels have been collected (for calibration readiness)."""
        ...

    # --- Audit log ---

    def log_audit(self, entry: AuditEntry) -> None:
        """Append an audit entry."""
        ...

    def get_audit_log(self, limit: int = 100) -> list[AuditEntry]:
        """Return recent audit entries, most recent first."""
        ...

    # --- Residual history (D-024) ---

    def save_residual_history(self, record: ResidualRecord) -> None:
        """Persist a single-week residual classification for a SKU."""
        ...

    def get_residual_history(
        self, erp_sku: str, max_weeks: int = 52
    ) -> list[ResidualRecord]:
        """Return residual history for a SKU, bounded by max_weeks, oldest first."""
        ...


class InMemoryRepository:
    """Process-lifetime storage — the trial-scope default.

    All data lives in plain dicts/lists and is lost when the process exits.
    Not thread-safe; suitable for single-process MCP usage where the
    FastMCP server is single-threaded by design.
    """

    def __init__(self) -> None:
        self._mappings: dict[str, MappingResult] = {}
        self._labels: list[ReviewLabel] = []
        self._audit: list[AuditEntry] = []
        self._residuals: dict[str, list[ResidualRecord]] = {}

    def save_mapping(self, result: MappingResult) -> None:
        self._mappings[result.retailer_key.name] = result

    def get_mapping(self, retailer_key_name: str) -> MappingResult | None:
        return self._mappings.get(retailer_key_name)

    def save_review_label(self, label: ReviewLabel) -> None:
        self._labels.append(label)

    def get_review_labels(self) -> list[ReviewLabel]:
        return list(self._labels)

    def count_review_labels(self) -> int:
        return len(self._labels)

    def log_audit(self, entry: AuditEntry) -> None:
        self._audit.append(entry)

    def get_audit_log(self, limit: int = 100) -> list[AuditEntry]:
        if limit <= 0:
            return []
        return list(reversed(self._audit[-limit:]))

    def save_residual_history(self, record: ResidualRecord) -> None:
        self._residuals.setdefault(record.erp_sku, []).append(record)

    def get_residual_history(
        self, erp_sku: str, max_weeks: int = 52
    ) -> list[ResidualRecord]:
        records = self._residuals.get(erp_sku, [])
        if max_weeks <= 0:
            return []
        return list(records[-max_weeks:])


class DuckDBRepository:
    """File-backed persistence via DuckDB (D-025).

    Schema is auto-initialised on first connection. The ``duckdb`` package
    is an optional dependency (``pip install cpg-reconciler[storage]``).

    Tables:
      - ``mapping_cache``: keyed on retailer_key_name, stores full
        MappingResult as JSON blob.
      - ``review_labels``: training data for the supervised calibrator.
      - ``audit_log``: append-only tool invocation records.
      - ``residual_history``: per-SKU weekly residual classifications
        for Markov drift detection (D-024).
    """

    _SCHEMA_SQL = """
        CREATE TABLE IF NOT EXISTS mapping_cache (
            retailer_key_name VARCHAR PRIMARY KEY,
            result_json       VARCHAR NOT NULL,
            updated_at        TIMESTAMP DEFAULT current_timestamp
        );
        CREATE TABLE IF NOT EXISTS review_labels (
            id                INTEGER PRIMARY KEY,
            retailer_key_name VARCHAR NOT NULL,
            retailer_key_gtin VARCHAR,
            original_erp_sku  VARCHAR,
            corrected_erp_sku VARCHAR NOT NULL,
            reviewer          VARCHAR DEFAULT 'unknown',
            created_at        TIMESTAMP DEFAULT current_timestamp
        );
        CREATE SEQUENCE IF NOT EXISTS review_labels_seq START 1;
        CREATE TABLE IF NOT EXISTS audit_log (
            id         INTEGER PRIMARY KEY,
            tool_name  VARCHAR NOT NULL,
            retailer   VARCHAR NOT NULL,
            iso_week   VARCHAR NOT NULL,
            parameters VARCHAR DEFAULT '{}',
            summary    VARCHAR DEFAULT '',
            created_at TIMESTAMP DEFAULT current_timestamp
        );
        CREATE SEQUENCE IF NOT EXISTS audit_log_seq START 1;
        CREATE TABLE IF NOT EXISTS residual_history (
            id         INTEGER PRIMARY KEY,
            erp_sku    VARCHAR NOT NULL,
            iso_week   VARCHAR NOT NULL,
            direction  VARCHAR NOT NULL,
            pct_error  DOUBLE NOT NULL,
            created_at TIMESTAMP DEFAULT current_timestamp
        );
        CREATE SEQUENCE IF NOT EXISTS residual_history_seq START 1;
    """

    def __init__(self, db_path: str) -> None:
        try:
            import duckdb
        except ImportError as exc:
            raise ImportError(
                "DuckDBRepository requires the 'duckdb' package. "
                "Install it with: pip install cpg-reconciler[storage]"
            ) from exc

        self._db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = duckdb.connect(db_path)
        self._conn.execute("BEGIN TRANSACTION")
        for stmt in self._SCHEMA_SQL.strip().split(";"):
            stmt = stmt.strip()
            if stmt:
                self._conn.execute(stmt)
        self._conn.execute("COMMIT")

    # --- Mapping cache ---

    def save_mapping(self, result: MappingResult) -> None:
        self._conn.execute(
            """
            INSERT OR REPLACE INTO mapping_cache (retailer_key_name, result_json, updated_at)
            VALUES (?, ?, current_timestamp)
            """,
            [result.retailer_key.name, result.model_dump_json()],
        )

    def get_mapping(self, retailer_key_name: str) -> MappingResult | None:
        row = self._conn.execute(
            "SELECT result_json FROM mapping_cache WHERE retailer_key_name = ?",
            [retailer_key_name],
        ).fetchone()
        if row is None:
            return None
        return MappingResult.model_validate_json(row[0])

    # --- Review labels ---

    def save_review_label(self, label: ReviewLabel) -> None:
        self._conn.execute(
            """
            INSERT INTO review_labels
                (id, retailer_key_name, retailer_key_gtin, original_erp_sku,
                 corrected_erp_sku, reviewer, created_at)
            VALUES (nextval('review_labels_seq'), ?, ?, ?, ?, ?, ?)
            """,
            [
                label.retailer_key_name,
                label.retailer_key_gtin,
                label.original_erp_sku,
                label.corrected_erp_sku,
                label.reviewer,
                label.timestamp,
            ],
        )

    def get_review_labels(self) -> list[ReviewLabel]:
        rows = self._conn.execute(
            """
            SELECT retailer_key_name, retailer_key_gtin, original_erp_sku,
                   corrected_erp_sku, reviewer, created_at
            FROM review_labels ORDER BY created_at
            """
        ).fetchall()
        return [
            ReviewLabel(
                retailer_key_name=r[0],
                retailer_key_gtin=r[1],
                original_erp_sku=r[2],
                corrected_erp_sku=r[3],
                reviewer=r[4],
                timestamp=r[5],
            )
            for r in rows
        ]

    def count_review_labels(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) FROM review_labels").fetchone()
        return row[0] if row else 0

    # --- Audit log ---

    def log_audit(self, entry: AuditEntry) -> None:
        self._conn.execute(
            """
            INSERT INTO audit_log
                (id, tool_name, retailer, iso_week, parameters, summary, created_at)
            VALUES (nextval('audit_log_seq'), ?, ?, ?, ?, ?, ?)
            """,
            [
                entry.tool_name,
                entry.retailer,
                entry.iso_week,
                json.dumps(entry.parameters),
                entry.summary,
                entry.timestamp,
            ],
        )

    def get_audit_log(self, limit: int = 100) -> list[AuditEntry]:
        if limit <= 0:
            return []
        rows = self._conn.execute(
            """
            SELECT tool_name, retailer, iso_week, parameters, summary, created_at
            FROM audit_log ORDER BY created_at DESC LIMIT ?
            """,
            [limit],
        ).fetchall()
        return [
            AuditEntry(
                tool_name=r[0],
                retailer=r[1],
                iso_week=r[2],
                parameters=json.loads(r[3]) if isinstance(r[3], str) else r[3],
                summary=r[4],
                timestamp=r[5],
            )
            for r in rows
        ]

    # --- Residual history (D-024) ---

    def save_residual_history(self, record: ResidualRecord) -> None:
        self._conn.execute(
            """
            INSERT INTO residual_history
                (id, erp_sku, iso_week, direction, pct_error, created_at)
            VALUES (nextval('residual_history_seq'), ?, ?, ?, ?, ?)
            """,
            [
                record.erp_sku,
                record.iso_week,
                record.direction,
                record.pct_error,
                record.timestamp,
            ],
        )

    def get_residual_history(
        self, erp_sku: str, max_weeks: int = 52
    ) -> list[ResidualRecord]:
        if max_weeks <= 0:
            return []
        rows = self._conn.execute(
            """
            SELECT erp_sku, iso_week, direction, pct_error, created_at
            FROM residual_history
            WHERE erp_sku = ?
            ORDER BY created_at ASC
            LIMIT ?
            """,
            [erp_sku, max_weeks],
        ).fetchall()
        return [
            ResidualRecord(
                erp_sku=r[0],
                iso_week=r[1],
                direction=r[2],
                pct_error=r[3],
                timestamp=r[4],
            )
            for r in rows
        ]
