# Live-run evidence — Verdano MCP draft creation

This file is reviewer evidence that the deliverable works end-to-end against the live trial ERP, not just against tests with faked/recorded data.

- **Date of run:** 2026-05-10.
- **ERP base URL:** `https://erp.corvera.ai`.
- **Driver:** [`scripts/live_draft_run.py`](../scripts/live_draft_run.py).
- **Retailer:** `tesco` for ISO week `2026-W20`.
- **Required date on drafts:** `2026-05-13`.

The driver invokes the registered MCP tool handlers directly with the real `Client.from_env` factory (no faking). Drafts created by this run persist in the trial ERP indefinitely — that's by design: the deterministic `external_reference` hash makes re-runs idempotent, so re-execution does not duplicate.

## What `analyze_week_fulfillment_tool` returned

Tesco W20 against the live ERP master:

```
summary: { Safe: 7, AtRisk: 2, AtRiskSevere: 3, Blocked: 0 }   (12 lines total)
```

(Same as the cassette-based reference output in `docs/usage.md`. Live ERP and recorded cassette agree on classification — confirms the cassettes are still representative.)

## What `create_drafts_for_safe_lines_tool` did — first run

### `SHIP-TESCO-DAV` (chilled) — 4 created, 3 skipped (cross-band), 0 failed

| Disposition | SKU | Qty | Reason / draft_id |
|---|---|---|---|
| Created | `VG-CHIL-400` | 18 | `DRAFT-8237DA0A` |
| Created | `VG-FALA-350` | 20 | `DRAFT-E986E7F2` |
| Created | `VG-GRSM-250` | 14 | `DRAFT-4A433017` |
| Created | `VG-BRSM-250` | 12 | `DRAFT-7B10271F` |
| Skipped | `VG-TOMS-500` | 40 | `temperature_band_mismatch` (ambient SKU → chilled ship_to) |
| Skipped | `VG-MUSH-500` | 22 | `temperature_band_mismatch` |
| Skipped | `VG-CARR-500` | 16 | `temperature_band_mismatch` |

### `SHIP-TESCO-RDG` (ambient) — 3 created, 4 skipped (cross-band), 0 failed

| Disposition | SKU | Qty | Reason / draft_id |
|---|---|---|---|
| Created | `VG-TOMS-500` | 40 | `DRAFT-E2CDA112` |
| Created | `VG-MUSH-500` | 22 | `DRAFT-6B4F09C8` |
| Created | `VG-CARR-500` | 16 | `DRAFT-A452B9F6` |
| Skipped | `VG-CHIL-400` | 18 | `temperature_band_mismatch` (chilled SKU → ambient ship_to) |
| Skipped | `VG-FALA-350` | 20 | `temperature_band_mismatch` |
| Skipped | `VG-GRSM-250` | 14 | `temperature_band_mismatch` |
| Skipped | `VG-BRSM-250` | 12 | `temperature_band_mismatch` |

**Net first-run effect:** 7 distinct drafts created across 7 distinct SKUs. The pre-filter caught every cross-band line before the ERP could reject it; **`failed` was empty** — no surprise validation errors at the boundary. The 7 = 4 + 3 split across ship_tos exactly matches the count of `Safe`-classified lines from `analyze_week_fulfillment_tool` (the unmatched 3 go to AtRiskSevere; 2 to AtRisk).

## Idempotency confirmation — second run

Re-ran the same tool with identical args at both ship_tos:

```
SHIP-TESCO-DAV (chilled): first run created=4 existing=0 | second run created=0 existing=4 ✓
SHIP-TESCO-RDG (ambient): first run created=3 existing=0 | second run created=0 existing=3 ✓
```

- `drafts_created` was empty on the second run.
- `drafts_existing` contained exactly the draft_ids from the first run.
- The driver script asserts no leaked or missed draft_ids — both assertions passed.

This confirms the **deterministic `external_reference` hash** (formalism §7) actually produces the production-scope idempotency D-010 requires. Re-running the entire pipeline cannot duplicate drafts.

## Live ERP draft inventory at end-of-run

`Client.list_order_drafts()` (bypassing MCP, raw client call) returned 8 drafts with the `verdano-` prefix:

| Draft ID | SKU | Qty | Ship-to | Source |
|---|---|---|---|---|
| `DRAFT-8237DA0A` | `VG-CHIL-400` | 18 | `SHIP-TESCO-DAV` | this run (chilled) |
| `DRAFT-E986E7F2` | `VG-FALA-350` | 20 | `SHIP-TESCO-DAV` | this run (chilled) |
| `DRAFT-4A433017` | `VG-GRSM-250` | 14 | `SHIP-TESCO-DAV` | this run (chilled) |
| `DRAFT-7B10271F` | `VG-BRSM-250` | 12 | `SHIP-TESCO-DAV` | this run (chilled) |
| `DRAFT-E2CDA112` | `VG-TOMS-500` | 40 | `SHIP-TESCO-RDG` | this run (ambient) |
| `DRAFT-6B4F09C8` | `VG-MUSH-500` | 22 | `SHIP-TESCO-RDG` | this run (ambient) |
| `DRAFT-A452B9F6` | `VG-CARR-500` | 16 | `SHIP-TESCO-RDG` | this run (ambient) |
| `DRAFT-C191E161` | `VG-FALA-500` | 8 | `SHIP-TESCO-DAV` | earlier cassette-recording smoke (`verdano-trial-smoke-001`) |

The 7 drafts from this run plus the one historical artifact from the earlier ERP-client cassette recording. No duplicates. No stragglers.

## What this validates

1. **SSL through TLS-MITM proxy works** (the `_resolve_ssl_context` helper in `src/verdano/erp/client.py` correctly combines certifi roots with extra dev CAs).
2. **The MCP tool's pre-filter on temperature band catches every incompatible draft** before the ERP sees it (`failed` empty across both ship_tos).
3. **Idempotency is real, not hypothetical** — re-runs return `existing` for every previously-created draft, no new draft_ids appear.
4. **The deterministic `external_reference` hash is correct** — the same (retailer, sku, week, ship_to) tuple always produces the same `verdano-<sha256-prefix>` string.
5. **The full pipeline path agrees with the cassette-tested path** — same classifications, same SKUs flagged as Safe.

## Reproducing the run

```bash
uv run python scripts/live_draft_run.py
```

Drafts persist in the trial ERP between runs. Subsequent invocations will report `existing` for every line and create nothing new.
