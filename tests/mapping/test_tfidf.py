"""TF-IDF token-overlap scorer (D-013, stratum tfidf_overlap).

Per Gemini iteration 5 option 1 + our pushback on the formalism: rare-token
matches carry more signal than common-token matches. These tests pin the
behavior on hand-crafted product fixtures and on the real ERP master loaded
from cassette.
"""

from __future__ import annotations

from verdano.erp.models import Product
from verdano.mapping.tfidf import TfIdfIndex


def _p(sku: str, name: str, aliases: list[str] | None = None) -> Product:
    """Compact Product factory for fixtures — only the fields TfIdfIndex reads."""
    return Product(
        sku=sku,
        name=name,
        category="ready_meal",
        temperature_band="chilled",
        case_pack=6,
        current_gtins=[],
        legacy_gtins=[],
        aliases=aliases or [],
        status="active",
    )


def test_idf_higher_for_rarer_tokens() -> None:
    """Tokens that appear in fewer products carry more IDF mass."""
    products = [
        _p("VG-1", "Lentil Dal 400g"),
        _p("VG-2", "Chickpea Curry 400g"),
        _p("VG-3", "Thai Green Curry 400g"),
    ]
    idx = TfIdfIndex(products)
    # "400g" appears in all 3 — common, low IDF.
    # "lentil" appears in 1 — rare, high IDF.
    assert idx.idf["lentil"] > idx.idf["400g"]
    assert idx.idf["dal"] > idx.idf["400g"]
    # "curry" appears in 2 — middle.
    assert idx.idf["lentil"] > idx.idf["curry"] > idx.idf["400g"]


def test_score_unique_token_match_dominates_common_match() -> None:
    """A retailer string sharing a rare token with a product scores higher
    than one sharing only a common token."""
    products = [
        _p("VG-LENTIL", "Lentil Dal 400g"),
        _p("VG-CHICK",  "Chickpea Curry 400g"),
        _p("VG-THAI",   "Thai Green Curry 400g"),
    ]
    idx = TfIdfIndex(products)
    # Retailer says "Lentil X 400g" — "lentil" is rare, "400g" is common.
    score_lentil = idx.score("Lentil X 400g", "VG-LENTIL")
    score_chick  = idx.score("Lentil X 400g", "VG-CHICK")
    # The lentil match should dominate the share-only-400g match.
    assert score_lentil > score_chick


def test_best_match_returns_tied_candidates() -> None:
    """K_x semantics: when multiple products achieve the same top score, all
    are returned so the cascade can apply the FS collision penalty."""
    products = [
        _p("VG-FALA-350", "Falafel Bowl 350g"),
        _p("VG-FALA-500", "Falafel Bowl Large"),
        _p("VG-OTHER",    "Lentil Dal 400g"),
    ]
    idx = TfIdfIndex(products)
    top, score = idx.best_match("Falafel Bowl")  # ambiguous fixture
    # Both Falafel products share both retailer tokens; tied at the top.
    assert set(top) == {"VG-FALA-350", "VG-FALA-500"}
    assert score > 0.0


def test_no_tokens_in_common_returns_zero_score() -> None:
    products = [_p("VG-LENTIL", "Lentil Dal 400g")]
    idx = TfIdfIndex(products)
    assert idx.score("totally unrelated string", "VG-LENTIL") == 0.0


def test_full_match_scores_one() -> None:
    """A retailer string whose every token is in the product vocab → 1.0."""
    products = [_p("VG-LENTIL", "Lentil Dal 400g")]
    idx = TfIdfIndex(products)
    # All retailer tokens appear in the product's vocab.
    assert idx.score("Lentil Dal 400g", "VG-LENTIL") == 1.0


def test_aliases_contribute_to_vocab() -> None:
    """A product's aliases extend its TF-IDF vocabulary, not just its name."""
    products = [_p("VG-DAAL", "Lentil Dal 400g", aliases=["VD Lentil Dal 400g"])]
    idx = TfIdfIndex(products)
    # `vd` only appears via the alias; should be matchable.
    assert idx.score("VD", "VG-DAAL") > 0.0


def test_size_normalization_propagates_to_tfidf() -> None:
    """0.5kg in retailer string and 500g in product alias should match (D-013)."""
    products = [_p("VG-TOMS", "Tomato Soup 500g")]
    idx = TfIdfIndex(products)
    score = idx.score("Tomato Soup 0.5kg", "VG-TOMS")
    # All retailer tokens normalize to the product's vocab tokens.
    assert score == 1.0
