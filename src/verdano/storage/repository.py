"""Repository protocol and backends for Verdano persistence (D-021).

The ``Repository`` protocol defines a narrow interface for the four
persistence domains the system needs. Each method pair (save/get) operates
on simple Pydantic models so that any backend — in-memory, DuckDB, SQLite,
S3 — can satisfy the contract.

The ``InMemoryRepository`` is the default for the trial: zero external
dependencies, process-lifetime scope, suitable for tests and demos.

The ``DuckDBRepository`` is the production-path placeholder: it will
provide persistent storage, OLAP-friendly queries over audit logs, and
indexed lookup for the calibration training pipeline.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from verdano.canonical import MappingResult


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
    """Minimal persistence contract for the Verdano system."""

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
    """Placeholder for DuckDB-backed persistence (D-021).

    The production implementation will require the ``duckdb`` package and
    a writable path. The planned schema will include:
      - ``mapping_cache``: keyed on retailer_key_name, stores full
        MappingResult JSON.
      - ``review_labels``: training data for the supervised calibrator.
      - ``audit_log``: append-only, partitioned by ISO week.
      - ``residual_history``: per-SKU weekly residual classifications
        for Markov drift detection (D-024).

    Raises ``NotImplementedError`` until the DuckDB schema is finalized.
    """

    def __init__(self, db_path: str = ".local/verdano.duckdb") -> None:
        self._db_path = db_path

    def _not_impl(self) -> NotImplementedError:
        return NotImplementedError(
            f"DuckDBRepository at {self._db_path!r} is not yet implemented; "
            "use InMemoryRepository for trial scope"
        )

    def save_mapping(self, result: MappingResult) -> None:
        raise self._not_impl()

    def get_mapping(self, retailer_key_name: str) -> MappingResult | None:
        raise self._not_impl()

    def save_review_label(self, label: ReviewLabel) -> None:
        raise self._not_impl()

    def get_review_labels(self) -> list[ReviewLabel]:
        raise self._not_impl()

    def count_review_labels(self) -> int:
        raise self._not_impl()

    def log_audit(self, entry: AuditEntry) -> None:
        raise self._not_impl()

    def get_audit_log(self, limit: int = 100) -> list[AuditEntry]:
        raise self._not_impl()

    def save_residual_history(self, record: ResidualRecord) -> None:
        raise self._not_impl()

    def get_residual_history(
        self, erp_sku: str, max_weeks: int = 52
    ) -> list[ResidualRecord]:
        raise self._not_impl()
