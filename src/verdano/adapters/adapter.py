"""The single config-driven adapter.

Per D-001: one Adapter class parameterized by a `RetailerSpec`. Onboarding a
new retailer = adding a new spec instance to `adapters/spec.py`. Zero new
Python code paths per retailer.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import polars as pl

from verdano.adapters.raw import RawActualsLine, RawDemandLine
from verdano.adapters.spec import RetailerSpec
from verdano.canonical import RetailerProductKey


class Adapter:
    """Convert retailer CSVs to raw canonical lines per a `RetailerSpec`."""

    def __init__(self, spec: RetailerSpec) -> None:
        self._spec = spec

    @property
    def spec(self) -> RetailerSpec:
        return self._spec

    # ------------------------------------------------------------------ forecast

    def normalize_forecast(self, csv_path: str | Path) -> list[RawDemandLine]:
        """Parse a forecast CSV and emit one `RawDemandLine` per row.

        Daily-grain rows (Tesco) are aggregated up to ISO week.
        Weekly-grain rows (Sainsbury's) pass through.
        """
        df = pl.read_csv(csv_path)
        rows = df.to_dicts()

        intermediate: list[RawDemandLine] = []
        for row in rows:
            iso_week = self._iso_week_from_row(row)
            key = self._product_key_from_forecast_row(row)
            promo_col = self._spec.forecast.promo_flag
            promo = self._truthy(row.get(promo_col)) if promo_col else False
            notes_col = self._spec.forecast.notes
            notes_val = row.get(notes_col) if notes_col else None
            notes = str(notes_val) if notes_val else None
            quantity = int(row[self._spec.forecast.quantity])
            location = str(row[self._spec.forecast.location])

            intermediate.append(
                RawDemandLine(
                    retailer=self._spec.code,
                    iso_week=iso_week,
                    retailer_key=key,
                    location_label=location,
                    raw_quantity=quantity,
                    raw_unit_mode=self._spec.forecast_unit_mode,
                    promo_flag=promo,
                    notes=notes,
                    inferred=False,
                )
            )

        # Daily rows aggregate up to weekly. Group by (iso_week, retailer_key,
        # location, promo, raw_unit_mode); sum quantities; concatenate notes.
        if self._spec.forecast_time_mode == "daily":
            return self._aggregate_to_weekly(intermediate)
        return intermediate

    # -------------------------------------------------------------- actuals/EPOS

    def normalize_actuals(self, csv_path: str | Path) -> list[RawActualsLine]:
        """Parse an EPOS / actuals CSV and emit one `RawActualsLine` per row."""
        df = pl.read_csv(csv_path)
        rows = df.to_dicts()

        out: list[RawActualsLine] = []
        for row in rows:
            iso_week = self._iso_week_from_actuals_row(row)
            key = self._product_key_from_actuals_row(row)
            out.append(
                RawActualsLine(
                    retailer=self._spec.code,
                    iso_week=iso_week,
                    retailer_key=key,
                    segment_label=str(row[self._spec.actuals.segment]),
                    units_sold=int(row[self._spec.actuals.units_sold]),
                    sales_value_gbp=Decimal(str(row[self._spec.actuals.sales_value])),
                )
            )
        return out

    # ----------------------------------------------------------------- internal

    def _iso_week_from_row(self, row: dict[str, object]) -> str:
        col = self._spec.forecast.time
        raw = row[col]
        if self._spec.forecast_time_mode == "iso_week":
            return str(raw)
        # daily — parse to a date and compute ISO year-week.
        return _date_to_iso_week(_to_date(raw))

    def _iso_week_from_actuals_row(self, row: dict[str, object]) -> str:
        col = self._spec.actuals.time
        raw = row[col]
        if isinstance(raw, str) and "W" in raw:
            return raw
        return _date_to_iso_week(_to_date(raw))

    def _product_key_from_forecast_row(self, row: dict[str, object]) -> RetailerProductKey:
        gtin = self._opt_str(row, self._spec.forecast.gtin)
        tesco_item = self._opt_str(row, self._spec.forecast.tesco_item)
        return RetailerProductKey(
            retailer=self._spec.code,
            name=str(row[self._spec.forecast.name]),
            gtin=gtin,
            tesco_item=tesco_item,
        )

    def _product_key_from_actuals_row(self, row: dict[str, object]) -> RetailerProductKey:
        gtin = self._opt_str(row, self._spec.actuals.gtin)
        tesco_item = self._opt_str(row, self._spec.actuals.tesco_item)
        return RetailerProductKey(
            retailer=self._spec.code,
            name=str(row[self._spec.actuals.name]),
            gtin=gtin,
            tesco_item=tesco_item,
        )

    @staticmethod
    def _opt_str(row: dict[str, object], col: str | None) -> str | None:
        if col is None:
            return None
        v = row.get(col)
        if v is None:
            return None
        s = str(v).strip()
        return s if s else None

    def _truthy(self, v: object) -> bool:
        if v is None:
            return False
        return str(v) in self._spec.promo_flag_truthy

    @staticmethod
    def _aggregate_to_weekly(rows: list[RawDemandLine]) -> list[RawDemandLine]:
        """Sum daily forecast cases up to weekly grain.

        Group key: (iso_week, retailer_key, location, raw_unit_mode). Promo
        flag becomes True if any constituent day was promoted. Notes
        concatenate (unique values, semicolon-delimited).
        """
        buckets: dict[tuple[object, ...], list[RawDemandLine]] = {}
        for r in rows:
            key = (
                r.iso_week,
                r.retailer_key.model_dump_json(),
                r.location_label,
                r.raw_unit_mode,
            )
            buckets.setdefault(key, []).append(r)

        agg: list[RawDemandLine] = []
        for group in buckets.values():
            head = group[0]
            total = sum(r.raw_quantity for r in group)
            promo_any = any(r.promo_flag for r in group)
            unique_notes = sorted({r.notes for r in group if r.notes})
            notes = "; ".join(unique_notes) if unique_notes else None
            agg.append(
                RawDemandLine(
                    retailer=head.retailer,
                    iso_week=head.iso_week,
                    retailer_key=head.retailer_key,
                    location_label=head.location_label,
                    raw_quantity=total,
                    raw_unit_mode=head.raw_unit_mode,
                    promo_flag=promo_any,
                    notes=notes,
                    inferred=False,
                )
            )
        return agg


def _to_date(raw: object) -> date:
    if isinstance(raw, date) and not isinstance(raw, datetime):
        return raw
    if isinstance(raw, datetime):
        return raw.date()
    return date.fromisoformat(str(raw))


def _date_to_iso_week(d: date) -> str:
    iso = d.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"
