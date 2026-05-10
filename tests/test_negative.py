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
from verdano.adapters.spec import get_spec, register_retailer
from verdano.canonical import (
    known_retailer_codes,
    validate_retailer_code,
)
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


class TestAdapterEdgeCases:
    """Edge cases for CSV data quality."""

    @pytest.fixture()
    def tesco_spec(self):
        return get_spec("tesco")

    @pytest.fixture()
    def sainsburys_spec(self):
        return get_spec("sainsburys")

    def test_non_numeric_quantity_skipped(self, tesco_spec, tmp_path: Path) -> None:
        """Rows with non-numeric quantity should be skipped with a warning."""
        csv = tmp_path / "bad_qty.csv"
        csv.write_text(
            "delivery_date,product_description,depot,forecast_cases,"
            "tesco_item,promo_flag,notes\n"
            "2026-05-11,Good Product,Daventry,100,T001,N,\n"
            "2026-05-11,Bad Product,Daventry,abc,T002,N,\n"
        )
        adapter = Adapter(tesco_spec)
        result = adapter.normalize_forecast(csv)
        assert len(result) == 1
        assert result[0].retailer_key.name == "Good Product"

    def test_duplicate_rows_aggregate(self, tesco_spec, tmp_path: Path) -> None:
        """Duplicate daily rows for the same product/location aggregate to weekly sum."""
        csv = tmp_path / "dupes.csv"
        csv.write_text(
            "delivery_date,product_description,depot,forecast_cases,"
            "tesco_item,promo_flag,notes\n"
            "2026-05-11,Product A,Daventry,50,T001,N,\n"
            "2026-05-12,Product A,Daventry,30,T001,N,\n"
        )
        adapter = Adapter(tesco_spec)
        result = adapter.normalize_forecast(csv)
        assert len(result) == 1
        assert result[0].raw_quantity == 80

    def test_float_quantity_truncated(self, tesco_spec, tmp_path: Path) -> None:
        """Float quantity like '3.7' is truncated to int by int()."""
        csv = tmp_path / "float_qty.csv"
        csv.write_text(
            "delivery_date,product_description,depot,forecast_cases,"
            "tesco_item,promo_flag,notes\n"
            "2026-05-11,Product A,Daventry,3.7,T001,N,\n"
        )
        adapter = Adapter(tesco_spec)
        result = adapter.normalize_forecast(csv)
        # Polars reads "3.7" as float 3.7; int(3.7) = 3 (truncation)
        assert len(result) == 1
        assert result[0].raw_quantity == 3


class TestGetSpecNegative:
    """get_spec domain errors."""

    def test_unknown_retailer_raises(self) -> None:
        with pytest.raises(ValueError, match="no adapter spec registered"):
            get_spec("unknown_retailer")  # type: ignore[arg-type]


class TestRetailerCodeRegistry:
    """Runtime registry for RetailerCode (D-015)."""

    def test_builtin_codes_registered(self) -> None:
        codes = known_retailer_codes()
        assert "tesco" in codes
        assert "sainsburys" in codes

    def test_validate_known_code(self) -> None:
        assert validate_retailer_code("tesco") == "tesco"

    def test_validate_unknown_code_raises(self) -> None:
        with pytest.raises(ValueError, match="unknown retailer code"):
            validate_retailer_code("nonexistent_retailer")

    def test_register_new_retailer(self) -> None:
        from verdano.adapters.spec import TESCO_SPEC

        register_retailer("test_retailer", TESCO_SPEC)
        try:
            assert "test_retailer" in known_retailer_codes()
            assert validate_retailer_code("test_retailer") == "test_retailer"
        finally:
            from verdano.canonical.models import _RETAILER_REGISTRY
            from verdano.adapters.spec import _REGISTRY
            _RETAILER_REGISTRY.discard("test_retailer")
            _REGISTRY.pop("test_retailer", None)
