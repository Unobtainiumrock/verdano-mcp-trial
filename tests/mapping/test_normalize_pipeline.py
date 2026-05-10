"""Tests for the composable NormalizationPipeline."""

from __future__ import annotations

from verdano.mapping.normalize import (
    DEFAULT_PIPELINE,
    NormalizationPipeline,
    collapse_whitespace,
    lowercase,
    normalize,
    normalize_sizes,
    remove_stop_words,
    strip_brand_prefixes,
    tokens,
)


class TestIndividualSteps:
    def test_lowercase(self) -> None:
        assert lowercase("Hello WORLD") == "hello world"

    def test_collapse_whitespace(self) -> None:
        assert collapse_whitespace("  hello   world  ") == "hello world"

    def test_normalize_sizes_kg(self) -> None:
        assert normalize_sizes("0.5kg") == "500g"

    def test_normalize_sizes_litre(self) -> None:
        assert normalize_sizes("2l") == "2000ml"

    def test_normalize_sizes_no_match(self) -> None:
        assert normalize_sizes("500g") == "500g"


class TestStripBrandPrefixes:
    def test_strips_matching_prefix(self) -> None:
        step = strip_brand_prefixes({"verdano ", "vd "})
        assert step("verdano falafel bowl") == "falafel bowl"

    def test_no_prefix_match(self) -> None:
        step = strip_brand_prefixes({"verdano "})
        assert step("chicken tikka") == "chicken tikka"

    def test_longest_prefix_first(self) -> None:
        step = strip_brand_prefixes({"vd ", "verdano deluxe "})
        assert step("verdano deluxe soup") == "soup"


class TestRemoveStopWords:
    def test_removes_stop_words(self) -> None:
        step = remove_stop_words({"the", "a", "of"})
        assert step("the bag of rice") == "bag rice"

    def test_no_stops(self) -> None:
        step = remove_stop_words({"the"})
        assert step("falafel bowl") == "falafel bowl"


class TestPipeline:
    def test_default_pipeline_matches_normalize(self) -> None:
        s = "Tom Basil Soup 0.5Kg"
        assert DEFAULT_PIPELINE(s) == normalize(s)

    def test_custom_pipeline(self) -> None:
        pipe = NormalizationPipeline([lowercase, collapse_whitespace])
        assert pipe("  Hello   WORLD  ") == "hello world"

    def test_with_step_extends(self) -> None:
        base = NormalizationPipeline([lowercase])
        extended = base.with_step(collapse_whitespace)
        assert extended("  HELLO   WORLD  ") == "hello world"
        assert base("  HELLO   WORLD  ") == "  hello   world  "


class TestBackwardCompatibility:
    def test_normalize_function(self) -> None:
        assert normalize("Tom Basil Soup 0.5Kg") == "tom basil soup 500g"

    def test_tokens_function(self) -> None:
        assert tokens("tom basil soup 500g") == ["tom", "basil", "soup", "500g"]
