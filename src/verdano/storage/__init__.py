"""Pluggable persistence layer (D-021, D-024, D-025).

Defines the ``Repository`` protocol and concrete backends:
  - ``InMemoryRepository``: process-lifetime storage for trial / tests.
  - ``DuckDBRepository``:   file-backed DuckDB storage (D-025).

The Repository holds four concerns:
  1. Mapping result cache — avoids re-resolving known keys.
  2. Review labels — human corrections for supervised calibration.
  3. Audit log entries — tool invocation records for compliance.
  4. Residual history — per-SKU weekly drift classifications for Markov (D-024).
"""

from verdano.storage.repository import (
    AuditEntry,
    DuckDBRepository,
    InMemoryRepository,
    Repository,
    ResidualRecord,
    ReviewLabel,
)

__all__ = [
    "AuditEntry",
    "DuckDBRepository",
    "InMemoryRepository",
    "Repository",
    "ResidualRecord",
    "ReviewLabel",
]
