"""Size-unit normalization (D-013).

Pure regex; no ERP master needed. These tests pin down the boundary cases
(what gets normalized, what's left alone) so future edits to the normalizer
don't silently break the cascade.
"""

from __future__ import annotations

import pytest

from cpg_reconciler.mapping.normalize import normalize, tokens


@pytest.mark.parametrize(
    "raw,expected",
    [
        # Core conversions.
        ("0.5kg", "500g"),
        ("1.5kg", "1500g"),
        ("2kg", "2000g"),
        ("0.25kg", "250g"),
        ("2L", "2000ml"),
        ("1l", "1000ml"),
        ("0.5l", "500ml"),
        # Inside a longer string.
        ("Tom Basil Soup 0.5kg", "tom basil soup 500g"),
        ("Tomato Soup 500g", "tomato soup 500g"),  # already canonical
        ("Vegan Smoothie 1L", "vegan smoothie 1000ml"),
        # Whitespace between number and unit.
        ("0.5 kg", "500g"),
        ("2 L", "2000ml"),
        # Already-canonical sizes pass through unchanged.
        ("500g", "500g"),
        ("250ml", "250ml"),
        ("400G", "400g"),  # case folded only; no kg/l so no rescale
    ],
)
def test_normalize_size_units(raw: str, expected: str) -> None:
    assert normalize(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "100ml",       # `l` not preceded by digit-then-optional-space
        "1lb",         # `\b` fails — "b" is a word char
        "kgallon",     # `kg` not preceded by digit
        "1kgallon",    # `kg` followed by word char fails `\b`
        "T-9101",      # SKU-like string with no kg/l
    ],
)
def test_normalize_does_not_eat_false_positives(raw: str) -> None:
    """Regex must not match patterns that aren't size units."""
    out = normalize(raw)
    # The size-unit regex must not have fired — output is just lowercased+collapsed.
    assert out == " ".join(raw.lower().split())


def test_normalize_is_idempotent() -> None:
    """Applying normalize twice yields the same string."""
    s = "Tom Basil Soup 0.5kg with 2 L milk"
    once = normalize(s)
    twice = normalize(once)
    assert once == twice


def test_tokens_splits_on_whitespace() -> None:
    assert tokens(normalize("Falafel Bowl 350g")) == ["falafel", "bowl", "350g"]
    assert tokens(normalize("  Lentil   Dal  400g  ")) == ["lentil", "dal", "400g"]


def test_normalize_unifies_kg_and_g_forms_for_lookup() -> None:
    """The whole point of D-013: 0.5kg and 500g normalize to the same string,
    so the alias dict matches across notations."""
    assert normalize("Tomato Soup 0.5kg") == normalize("Tomato Soup 500g")
    assert normalize("Smoothie 1l") == normalize("Smoothie 1000ml")
