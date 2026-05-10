"""Cascade-floor and dedup behaviors locked under D-014.

Three regressions surfaced by an empirical probe of the live ERP master:
1. Same-SKU appearing twice under one alias key (when D-013 size-normalizer
   collapses a product's canonical name + alias into the same string)
   inflated K_x from 1 to 2 → false NeedsVerification on a clean exact match.
2. E4 had no minimum-confidence floor → garbage strings ("Bicycle Tyre")
   returned a misleading candidate ("Chickpea Curry"). Now drops to Unmapped
   below `fuzzy_jw_min_score`.
3. E3b would fire on a single-rare-token retailer string (e.g., "VD")
   because the IDF-overlap ratio normalizes by retailer mass — a 1-of-1 match
   scores 1.0. Now E3b requires at least `tfidf_min_matched_tokens` tokens
   shared with the candidate.
"""

from __future__ import annotations

from verdano.canonical import RetailerProductKey
from verdano.erp.models import Product
from verdano.mapping import MasterIndex, Resolver


def _p(sku: str, name: str, aliases: list[str] | None = None) -> Product:
    return Product(
        sku=sku, name=name, category="ready_meal", temperature_band="ambient",
        case_pack=8, current_gtins=[], legacy_gtins=[],
        aliases=aliases or [], status="active",
    )


# ----------------------------- Fix #1: K_x dedup -----------------------------

def test_kx_does_not_inflate_when_size_normalizer_collapses_name_and_alias() -> None:
    """When `_norm` collapses a product's name + alias to the same canonical
    string (D-013 size unification), the alias-index entry must list the SKU
    once, not twice."""
    products = [
        # Both `name` and the alias normalize to "tomato basil soup 500g"
        # because of the kg→g rescale.
        _p("VG-TOMS", "Tomato Basil Soup 500g", aliases=["Tomato Basil Soup 0.5kg"]),
    ]
    res = Resolver(MasterIndex(products))
    r = res.resolve(RetailerProductKey(retailer="sainsburys", name="Tomato Basil Soup 0.5kg"))
    assert r.evidence is not None
    assert r.evidence.stratum == "alias_exact"
    # The bug: K_x=2 inflated by the duplicate path. Should be 1.
    assert r.evidence.collision_count == 1
    assert r.state == "Resolved"


def test_kx_dedup_in_current_gtin_index() -> None:
    """A product listing the same GTIN twice (data-entry slip) must not
    inflate K_x at lookup time."""
    products = [
        Product(
            sku="VG-X", name="X", category="ready_meal", temperature_band="ambient",
            case_pack=1, current_gtins=["1234567890123", "1234567890123"],
            legacy_gtins=[], aliases=[], status="active",
        ),
    ]
    res = Resolver(MasterIndex(products))
    key = RetailerProductKey(
        retailer="sainsburys", name="anything", gtin="1234567890123"
    )
    r = res.resolve(key)
    assert r.evidence is not None
    assert r.evidence.stratum == "gtin_current"
    assert r.evidence.collision_count == 1


# --------------------------- Fix #2: E4 floor ------------------------------

def test_e4_floor_drops_low_confidence_candidates_to_unmapped() -> None:
    """Strings that don't legitimately match anything must not produce a
    candidate. The cascade should return Unmapped instead of a misleading
    'NeedsVerification' on a 0.28-confidence guess."""
    products = [
        _p("VG-DAAL", "Lentil Dal 400g"),
        _p("VG-CHCK", "Chickpea Curry 400g"),
    ]
    res = Resolver(MasterIndex(products), fuzzy_jw_min_score=0.30)
    r = res.resolve(RetailerProductKey(retailer="sainsburys", name="qwerty asdf"))
    assert r.state == "Unmapped"
    assert r.erp_sku is None
    assert r.evidence is None


def test_e4_floor_is_configurable() -> None:
    """An aggressive operator-tuned floor cuts more candidates."""
    products = [_p("VG-DAAL", "Lentil Dal 400g")]
    # JW² of "Bicycle Tyre" against "Lentil Dal 400g" is around 0.30 — sits
    # right at the boundary. Above-default floor cuts it; default lets it
    # through.
    aggressive = Resolver(MasterIndex(products), fuzzy_jw_min_score=0.50)
    r = aggressive.resolve(RetailerProductKey(retailer="sainsburys", name="Bicycle Tyre"))
    assert r.state == "Unmapped"


# ---------------------- Fix #3: E3b min-matched-tokens ---------------------

def test_e3b_does_not_fire_on_single_rare_token_match() -> None:
    """A retailer string whose only token happens to be a rare ERP-master
    token used to auto-Resolve via E3b at top_score=1.0. With the min-tokens
    guard, single-token matches fall through to E4."""
    products = [
        _p("VG-DAAL", "Lentil Dal 400g", aliases=["VD Lentil Dal 400g"]),
        _p("VG-CHCK", "Chickpea Curry 400g"),
    ]
    res = Resolver(MasterIndex(products))
    # "VD" shares only 1 token (`vd`) with the master.
    r = res.resolve(RetailerProductKey(retailer="sainsburys", name="VD"))
    # Either Unmapped (E4 also fails) or E4 at low conf — but never E3b.
    assert r.evidence is None or r.evidence.stratum != "tfidf_overlap"
    # The pre-fix behavior was E3b @ w=0.98; with the guard, it's not auto-resolved.
    assert r.state != "Resolved"


def test_e3b_still_fires_when_two_or_more_tokens_match() -> None:
    """Sanity check: the guard must not regress legitimate E3b cases."""
    products = [
        _p("VG-FALA-350", "Falafel Bowl 350g"),
        _p("VG-FALA-500", "Falafel Bowl 500g", aliases=["Falafel Bowl Large"]),
    ]
    res = Resolver(MasterIndex(products))
    r = res.resolve(RetailerProductKey(retailer="sainsburys", name="Falafel Bowl"))
    assert r.evidence is not None
    assert r.evidence.stratum == "tfidf_overlap"
    assert r.evidence.collision_count == 2  # both products share both tokens
    assert r.state == "NeedsVerification"


def test_e3b_min_tokens_is_configurable() -> None:
    """A more-permissive operator can lower the guard if their data is clean."""
    products = [_p("VG-DAAL", "Lentil Dal 400g", aliases=["VD Lentil Dal 400g"])]
    res = Resolver(MasterIndex(products), tfidf_min_matched_tokens=1)
    r = res.resolve(RetailerProductKey(retailer="sainsburys", name="VD"))
    # With min_tokens=1, the cascade reaches E3b on the single rare match.
    assert r.evidence is not None
    assert r.evidence.stratum == "tfidf_overlap"
