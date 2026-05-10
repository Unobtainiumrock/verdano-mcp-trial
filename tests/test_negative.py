"""Negative / error-path tests.

Covers:
- Adapter: empty CSV, wrong headers (rows skipped with warning)
- Drift: invalid threshold
- get_spec: unknown retailer
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from verdano.adapters.adapter import Adapter
from verdano.adapters.spec import get_spec
from verdano.drift.baseline import BaselineCompare


class TestAdapterNegative:
    """Edge cases for the CSV adapter."""

    @pytest.fixture()
    def tesco_spec(self):
        return get_spec("tesco")

    def test_empty_csv_raises(self, tesco_spec, tmp_path: Path) -> None:
        csv = tmp_path / "empty.csv"
        csv.write_text("")
        adapter = Adapter(tesco_spec)
        with pytest.raises(pl.exceptions.NoDataError):
            adapter.normalize_forecast(csv)

    def test_wrong_headers_skips_all_rows(self, tesco_spec, tmp_path: Path) -> None:
        csv = tmp_path / "bad_headers.csv"
        csv.write_text("col_a,col_b,col_c\n1,2,3\n")
        adapter = Adapter(tesco_spec)
        result = adapter.normalize_forecast(csv)
        assert result == [], "malformed rows should be skipped, yielding empty list"


class TestDriftNegative:
    """BaselineCompare validation."""

    def test_invalid_threshold_order_raises(self) -> None:
        with pytest.raises(ValueError, match="require 0 < threshold_low"):
            BaselineCompare(threshold_low=1.5, threshold_high=0.5)

    def test_threshold_low_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="require 0 < threshold_low"):
            BaselineCompare(threshold_low=0.0, threshold_high=1.5)

    def test_threshold_low_above_one_raises(self) -> None:
        with pytest.raises(ValueError, match="require 0 < threshold_low"):
            BaselineCompare(threshold_low=1.1, threshold_high=2.0)


class TestGetSpecNegative:
    """get_spec domain errors."""

    def test_unknown_retailer_raises(self) -> None:
        with pytest.raises(ValueError, match="no adapter spec registered"):
            get_spec("unknown_retailer")  # type: ignore[arg-type]
