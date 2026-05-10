"""FastMCP server exposing the pipeline functions as tools.

Run via `python -m verdano.mcp_server` (stdio transport) for use under an MCP
host like Claude Desktop or `mcp` CLI.

Tools are *coarse-grained* (per Gemini iteration 4 + our agreement):
exposing `analyze_week_fulfillment(week)` rather than per-row primitives means
the model gets one round-trip per question, not N. That keeps context windows
clean and reduces failure rate.
"""

from __future__ import annotations

import hashlib
import os
import re
import sys
from collections.abc import Callable
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from verdano.canonical import RetailerCode, validate_retailer_code
from verdano.config import Settings, load_settings
from verdano.erp import Client, ERPHTTPError, OrderDraftLine, OrderDraftRequest
from verdano.llm.client import LLMClient, create_llm_client
from verdano.mapping.depot import resolve_depot
from verdano.mapping.priors import CalibrationPriors
from verdano.mapping.resolver import DEFAULT_HANDLERS, StratumHandler
from verdano.pipeline import (
    ErpSnapshot,
    analyze_forecast_plausibility,
    analyze_week_fulfillment,
    customer_for_retailer,
)

ErpClientFactory = Callable[[], AbstractContextManager[Client]]


def _validate_retailer(retailer: str) -> dict[str, Any] | None:
    """Return an error dict if ``retailer`` is not registered, else None."""
    try:
        validate_retailer_code(retailer)
    except ValueError as exc:
        return {"error": str(exc)}
    return None


_ISO_WEEK_RE = re.compile(r"^(\d{4})-W(\d{2})$")


def _validate_iso_week(iso_week: str) -> dict[str, Any] | None:
    """Return an error dict if `iso_week` is malformed or out of range, else None."""
    m = _ISO_WEEK_RE.match(iso_week)
    if not m:
        return {"error": f"invalid iso_week format {iso_week!r}; expected YYYY-Wnn"}
    from datetime import date
    try:
        date.fromisocalendar(int(m.group(1)), int(m.group(2)), 1)
    except ValueError:
        return {"error": f"iso_week {iso_week!r} is out of range"}
    return None


# Trial-scope: forecast CSV path is determined by retailer code at the
# project root. Production: this would come from a config / object-store.
def _forecast_csv_for(retailer: RetailerCode, project_root: Path) -> Path:
    return project_root / "data" / f"{retailer}_forecast_week20.csv"


def _actuals_csv_for(retailer: RetailerCode, project_root: Path) -> Path:
    return project_root / "data" / f"{retailer}_epos_actuals_week19.csv"


def _erp_snapshot_from_live(client: Client) -> ErpSnapshot:
    """Fetch a fresh ERP snapshot in one shot."""
    return ErpSnapshot(
        products=client.list_products(),
        customers=client.list_customers(),
        warehouses=client.list_warehouses(),
        inventory=client.list_inventory(),
        open_orders=client.list_open_orders(),
    )


def _deterministic_external_reference(
    retailer: RetailerCode, sku: str, iso_week: str, ship_to: str
) -> str:
    """Per D-010 §7: external_reference = sha256(retailer | sku | week | ship_to).

    Truncated to 32 chars for a readable identifier. Idempotent draft creation
    by construction — re-running the pipeline cannot duplicate drafts.
    """
    payload = f"{retailer}|{sku}|{iso_week}|{ship_to}".encode()
    return f"verdano-{hashlib.sha256(payload).hexdigest()[:32]}"


def _resolve_project_root() -> Path:
    """Resolve project root from env or CWD, shared by all entry paths."""
    env_root = os.environ.get("VERDANO_PROJECT_ROOT")
    return Path(env_root) if env_root else Path.cwd()


def _build_handlers(
    settings: Settings,
    llm_client: LLMClient | None,
    erp_products: list[Any] | None = None,
) -> list[tuple[str, StratumHandler]]:
    """Assemble the ordered handler chain, optionally appending an LLM stratum."""
    handlers = list(DEFAULT_HANDLERS)
    if llm_client is not None and erp_products is not None:
        from verdano.llm.entity_resolution import make_llm_stratum
        from verdano.mapping.resolver import MasterIndex

        master = MasterIndex(erp_products)
        handlers.append(("llm_augmented", make_llm_stratum(llm_client, master)))
    return handlers


def build_server(
    project_root: Path | None = None,
    erp_client_factory: ErpClientFactory | None = None,
    settings: Settings | None = None,
) -> FastMCP:
    """Construct (but do not run) the MCP server.

    Splitting construction from execution lets tests inject a fake client
    and exercise tool behavior without touching the network.
    """
    project_root = project_root or _resolve_project_root()
    factory = erp_client_factory or Client.from_env
    cfg = settings or load_settings()
    llm_client = create_llm_client(cfg)

    priors = CalibrationPriors(
        epsilon=cfg.fs_epsilon,
        gamma=cfg.fs_gamma,
        alpha=cfg.fs_alpha,
    )

    server: FastMCP = FastMCP("verdano-mcp")

    @server.tool()
    def analyze_week_fulfillment_tool(
        retailer: RetailerCode,
        iso_week: str,
    ) -> dict[str, Any]:
        """Compare a retailer's forecast for a given ISO week against ERP inventory and open orders.

        Returns a per-line classification (Safe / AtRisk / AtRiskSevere / Blocked)
        with the resolved ERP SKU, free-to-promise cases, fill rate, and an
        operator-readable reason.

        Args:
            retailer: Registered retailer code (e.g. "tesco", "sainsburys").
            iso_week: ISO 8601 week, e.g. "2026-W20".
        """
        if err := _validate_retailer(retailer):
            return err
        if err := _validate_iso_week(iso_week):
            return err
        with factory() as client:
            erp = _erp_snapshot_from_live(client)
        handlers = _build_handlers(cfg, llm_client, erp.products)
        result = analyze_week_fulfillment(
            forecast_csv=_forecast_csv_for(retailer, project_root),
            retailer=retailer,
            iso_week=iso_week,
            erp=erp,
            priors=priors,
            auto_threshold=cfg.auto_threshold,
            tau_safe=cfg.tau_safe,
            tfidf_min_score=cfg.tfidf_min_score,
            tfidf_min_matched_tokens=cfg.tfidf_min_matched_tokens,
            e4_min_score=cfg.e4_min_score,
            handlers=handlers,
        )
        return result.model_dump(mode="json")

    @server.tool()
    def list_review_queue_tool(
        retailer: RetailerCode,
        iso_week: str,
    ) -> dict[str, Any]:
        """Return only the lines that need human review (Blocked + low-confidence mappings).

        This is the surface the operator should look at first. Each item carries
        the lineage (which stratum fired) and confidence so the reviewer
        understands why the system surfaced it.

        Args:
            retailer: Registered retailer code (e.g. "tesco", "sainsburys").
            iso_week: ISO 8601 week, e.g. "2026-W20".
        """
        if err := _validate_retailer(retailer):
            return err
        if err := _validate_iso_week(iso_week):
            return err
        with factory() as client:
            erp = _erp_snapshot_from_live(client)
        handlers = _build_handlers(cfg, llm_client, erp.products)
        result = analyze_week_fulfillment(
            forecast_csv=_forecast_csv_for(retailer, project_root),
            retailer=retailer,
            iso_week=iso_week,
            erp=erp,
            priors=priors,
            auto_threshold=cfg.auto_threshold,
            tau_safe=cfg.tau_safe,
            tfidf_min_score=cfg.tfidf_min_score,
            tfidf_min_matched_tokens=cfg.tfidf_min_matched_tokens,
            e4_min_score=cfg.e4_min_score,
            handlers=handlers,
        )
        review_items = [
            c for c in result.classifications
            if c.classification in {"Blocked", "AtRiskSevere", "NeedsVerification"}
        ]
        return {
            "retailer": retailer,
            "iso_week": iso_week,
            "count": len(review_items),
            "items": [c.model_dump(mode="json") for c in review_items],
        }

    @server.tool()
    def create_drafts_for_safe_lines_tool(
        retailer: RetailerCode,
        iso_week: str,
        required_date: str,
        ship_to_location_id: str = "",
    ) -> dict[str, Any]:
        """Create ERP order drafts for every Safe-classified line.

        Idempotent by construction: external_reference is a deterministic
        hash of (retailer, sku, iso_week, ship_to). Re-running this tool on
        the same inputs returns the existing drafts — no duplicates.

        Lines whose mapped ERP product is in a different temperature band
        than the chosen ship_to's warehouse are *skipped* (not attempted) —
        the ERP would reject them as cross-band. Lines that hit unexpected
        ERP errors are *failed* — collected per-line, not raised.

        If ``ship_to_location_id`` is omitted, the depot resolver attempts
        to auto-resolve it from the first forecast line's location label.

        Args:
            retailer: Registered retailer code (e.g. "tesco", "sainsburys").
            iso_week: ISO 8601 week, e.g. "2026-W20".
            required_date: ISO date for the draft, e.g. "2026-05-13".
            ship_to_location_id: ERP ship_to id (e.g., "SHIP-TESCO-DAV").
                If omitted, auto-resolved from forecast location labels.
        """
        if err := _validate_retailer(retailer):
            return err
        if err := _validate_iso_week(iso_week):
            return err
        try:
            from datetime import date as _date
            req_date = _date.fromisoformat(required_date)
        except ValueError:
            return {"error": f"invalid required_date {required_date!r}; expected YYYY-MM-DD"}
        with factory() as client:
            erp = _erp_snapshot_from_live(client)
            handlers = _build_handlers(cfg, llm_client, erp.products)
            result = analyze_week_fulfillment(
                forecast_csv=_forecast_csv_for(retailer, project_root),
                retailer=retailer,
                iso_week=iso_week,
                erp=erp,
                priors=priors,
                auto_threshold=cfg.auto_threshold,
                tau_safe=cfg.tau_safe,
                tfidf_min_score=cfg.tfidf_min_score,
                tfidf_min_matched_tokens=cfg.tfidf_min_matched_tokens,
                e4_min_score=cfg.e4_min_score,
                handlers=handlers,
            )
            effective_ship_to = ship_to_location_id
            if not effective_ship_to and result.classifications:
                first_label = result.classifications[0].demand.location_label
                resolved = resolve_depot(
                    first_label, erp.customers, retailer,
                    fuzzy_threshold=cfg.depot_fuzzy_threshold,
                    llm_client=llm_client,
                )
                if resolved:
                    effective_ship_to = resolved
                else:
                    return {
                        "error": (
                            f"could not auto-resolve ship_to from location "
                            f"label {first_label!r}; pass ship_to_location_id explicitly"
                        ),
                    }

            customer = customer_for_retailer(erp.customers, retailer)
            if customer is None:
                return {"error": f"no sold-to customer found for {retailer}"}
            bill_to = next(
                (c for c in erp.customers
                 if c.type == "bill_to" and c.parent_id == customer.id),
                None,
            )
            if bill_to is None:
                return {
                    "error": f"no bill-to customer found under sold-to {customer.id}"
                }

            ship_to = next(
                (c for c in erp.customers
                 if c.type == "ship_to" and c.id == effective_ship_to),
                None,
            )
            if ship_to is None:
                return {
                    "error": f"ship_to_location_id {effective_ship_to} not found",
                }
            ship_to_warehouse_id = ship_to.warehouse_id
            warehouses_by_id = {w.id: w for w in erp.warehouses}
            ship_to_band: str | None = (
                warehouses_by_id[ship_to_warehouse_id].temperature_band
                if ship_to_warehouse_id and ship_to_warehouse_id in warehouses_by_id
                else None
            )
            products_by_sku = {p.sku: p for p in erp.products}

            drafts_created: list[dict[str, Any]] = []
            drafts_existing: list[dict[str, Any]] = []
            skipped: list[dict[str, Any]] = []
            failed: list[dict[str, Any]] = []

            for c in result.classifications:
                if c.classification != "Safe" or c.erp_sku is None:
                    continue
                if c.demand.quantity_cases < 1:
                    continue
                # Pre-filter: skip cross-band SKUs that the ERP would reject.
                product = products_by_sku.get(c.erp_sku)
                product_band = product.temperature_band if product else None
                if (
                    ship_to_band is not None
                    and product_band is not None
                    and product_band != ship_to_band
                ):
                    skipped.append({
                        "sku": c.erp_sku,
                        "quantity_cases": c.demand.quantity_cases,
                        "reason": "temperature_band_mismatch",
                        "product_band": product_band,
                        "ship_to_band": ship_to_band,
                    })
                    continue

                ext_ref = _deterministic_external_reference(
                    retailer, c.erp_sku, iso_week, effective_ship_to
                )
                request = OrderDraftRequest(
                    external_reference=ext_ref,
                    sold_to_customer_id=customer.id,
                    bill_to_customer_id=bill_to.id,
                    ship_to_location_id=effective_ship_to,
                    required_date=req_date,
                    lines=[
                        OrderDraftLine(
                            sku=c.erp_sku, quantity_cases=c.demand.quantity_cases
                        )
                    ],
                    notes=f"verdano-mcp auto-draft for {retailer} {iso_week}",
                )
                try:
                    response = client.create_order_draft(request)
                except ERPHTTPError as e:
                    failed.append({
                        "sku": c.erp_sku,
                        "quantity_cases": c.demand.quantity_cases,
                        "external_reference": ext_ref,
                        "status_code": e.status_code,
                        "body": e.body,
                    })
                    continue

                bucket = drafts_created if response.status == "created" else drafts_existing
                bucket.append({
                    "draft_id": response.draft_id,
                    "status": response.status,
                    "external_reference": ext_ref,
                    "sku": c.erp_sku,
                    "quantity_cases": c.demand.quantity_cases,
                })

        return {
            "retailer": retailer,
            "iso_week": iso_week,
            "ship_to_location_id": effective_ship_to,
            "ship_to_band": ship_to_band,
            "drafts_created": drafts_created,
            "drafts_existing": drafts_existing,
            "skipped": skipped,
            "failed": failed,
        }

    @server.tool()
    def compare_actuals_vs_forecast_tool(
        retailer: RetailerCode,
        iso_week_forecast: str,
        iso_week_actuals: str,
    ) -> dict[str, Any]:
        """Lagged-actuals plausibility check on the retailer's forecast.

        **Important framing:** this is *not* classical drift detection.
        Classical drift compares a forecast to the actuals from the same
        period; the trial fixture only provides forward-looking forecasts and
        lagged actuals. We instead compute the ratio
        `forecast_eaches / max(lagged_actuals_eaches, 1)` per resolved SKU,
        threshold-flagging implausible deviations after promo segmentation.
        See DECISIONS.md D-012 for the framing.

        Promo-flagged forecast lines (Tesco only — Sainsbury's has no flag
        column) are excluded from threshold-based flagging since promo
        creates expected uplift. Markov-style true-drift modeling is
        deferred per D-006.

        Args:
            retailer: Registered retailer code (e.g. "tesco", "sainsburys").
            iso_week_forecast: e.g. "2026-W20".
            iso_week_actuals:  e.g. "2026-W19".
        """
        if err := _validate_retailer(retailer):
            return err
        for wk in (iso_week_forecast, iso_week_actuals):
            if err := _validate_iso_week(wk):
                return err
        with factory() as client:
            erp = _erp_snapshot_from_live(client)
        report = analyze_forecast_plausibility(
            forecast_csv=_forecast_csv_for(retailer, project_root),
            actuals_csv=_actuals_csv_for(retailer, project_root),
            retailer=retailer,
            iso_week_forecast=iso_week_forecast,
            iso_week_actuals=iso_week_actuals,
            erp=erp,
            priors=priors,
            auto_threshold=cfg.auto_threshold,
            threshold_low=cfg.drift_threshold_low,
            threshold_high=cfg.drift_threshold_high,
        )
        return report.model_dump(mode="json")

    return server


def get_tool_handler(server: FastMCP, tool_name: str) -> Any:
    """Retrieve a tool's underlying callable from a FastMCP server.

    Centralizes the internal-API access pattern so tests and scripts have a
    single call site to update if FastMCP's internal layout changes.
    """
    return server._tool_manager._tools[tool_name].fn  # type: ignore[attr-defined]


def _run_health_check(project_root: Path) -> int:
    """Verify env, ERP connectivity, and tool registration. Returns exit code."""
    from pydantic import ValidationError

    from verdano.config import Settings

    checks: list[tuple[str, bool, str]] = []

    env_path = project_root / ".env"
    checks.append((".env exists", env_path.is_file(), str(env_path)))

    try:
        settings = Settings()  # type: ignore[call-arg]
        has_key = bool(settings.erp_api_key.get_secret_value().strip())
    except (ValidationError, OSError):
        has_key = False
    checks.append(("API key configured", has_key, "VERDANO_ERP_API_KEY"))

    erp_ok = False
    erp_detail = ""
    if has_key:
        try:
            with Client.from_env() as client:
                prods = client.list_products()
                erp_ok = len(prods) > 0
                erp_detail = f"{len(prods)} products"
        except Exception as exc:
            erp_detail = str(exc)[:120]
    checks.append(("ERP connectivity", erp_ok, erp_detail))

    server = build_server(project_root=project_root)
    tool_names = sorted(server._tool_manager._tools.keys())  # type: ignore[attr-defined]
    checks.append(("Tools registered", len(tool_names) >= 4, ", ".join(tool_names)))

    all_ok = True
    for label, ok, detail in checks:
        symbol = "+" if ok else "x"
        print(f"  [{symbol}] {label}: {detail}")
        if not ok:
            all_ok = False

    print()
    if all_ok:
        print("All checks passed — MCP server is ready.")
    else:
        print("Some checks failed — see above.")
    return 0 if all_ok else 1


def run() -> None:
    """Entry-point for `verdano-mcp` / `python -m verdano.mcp_server`."""
    root = _resolve_project_root()
    if "--health" in sys.argv:
        raise SystemExit(_run_health_check(root))
    server = build_server(project_root=root)
    server.run()
