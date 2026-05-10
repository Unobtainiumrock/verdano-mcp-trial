"""Tests for the LLM integration layer (fully mocked — no API calls)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock

import pytest

from verdano.llm.client import LLMClient, OpenAIClient, create_llm_client


class FakeLLMClient:
    """Test double that implements the LLMClient protocol."""

    def __init__(self, response: str) -> None:
        self._response = response

    def complete(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        return self._response


class TestLLMClientProtocol:
    def test_fake_satisfies_protocol(self) -> None:
        client = FakeLLMClient("hello")
        assert isinstance(client, LLMClient)

    def test_complete_returns_string(self) -> None:
        client = FakeLLMClient("test response")
        result = client.complete([{"role": "user", "content": "hi"}])
        assert result == "test response"


class TestCreateLLMClient:
    def test_returns_none_when_no_key(self) -> None:
        @dataclass
        class FakeSettings:
            llm_api_key: Any = None
            llm_base_url: str = "http://localhost:8000"
            llm_model: str = "test"

        assert create_llm_client(FakeSettings()) is None

    def test_returns_none_when_empty_key(self) -> None:
        from pydantic import SecretStr

        @dataclass
        class FakeSettings:
            llm_api_key: SecretStr = SecretStr("")
            llm_base_url: str = "http://localhost:8000"
            llm_model: str = "test"

        assert create_llm_client(FakeSettings()) is None


class TestLLMEntityResolution:
    def test_e5_handler_returns_result(self) -> None:
        from verdano.canonical import MappingResult, RetailerProductKey
        from verdano.erp.models import Product
        from verdano.llm.entity_resolution import make_llm_stratum
        from verdano.mapping.resolver import MasterIndex

        products = [
            Product(
                sku="VG-SOUP-400",
                name="Tomato Basil Soup 400g",
                category="soup",
                status="active",
                current_gtins=[],
                legacy_gtins=[],
                aliases=[],
                case_pack=6,
                temperature_band="ambient",
            ),
        ]
        master = MasterIndex(products)

        llm_response = json.dumps({"sku": "VG-SOUP-400", "confidence": 0.85})
        client = FakeLLMClient(llm_response)

        handler = make_llm_stratum(client, master, min_confidence=0.3)

        from verdano.mapping.resolver import ResolverContext
        from verdano.mapping.priors import DEFAULT_PRIORS

        ctx = ResolverContext(
            master=master,
            priors=DEFAULT_PRIORS,
            auto_threshold=0.90,
            tfidf_min_score=0.5,
            tfidf_min_matched_tokens=2,
            fuzzy_jw_min_score=0.30,
        )

        key = RetailerProductKey(
            retailer="tesco", name="Tomato Soup", gtin=None
        )
        result = handler(ctx, key)
        assert result is not None
        assert result.erp_sku == "VG-SOUP-400"
        assert result.evidence is not None
        assert result.evidence.stratum == "llm_augmented"

    def test_e5_handler_returns_none_on_low_confidence(self) -> None:
        from verdano.canonical import RetailerProductKey
        from verdano.erp.models import Product
        from verdano.llm.entity_resolution import make_llm_stratum
        from verdano.mapping.resolver import MasterIndex, ResolverContext
        from verdano.mapping.priors import DEFAULT_PRIORS

        products = [
            Product(
                sku="VG-SOUP-400",
                name="Tomato Basil Soup 400g",
                category="soup",
                status="active",
                current_gtins=[],
                legacy_gtins=[],
                aliases=[],
                case_pack=6,
                temperature_band="ambient",
            ),
        ]
        master = MasterIndex(products)

        llm_response = json.dumps({"sku": "VG-SOUP-400", "confidence": 0.1})
        client = FakeLLMClient(llm_response)

        handler = make_llm_stratum(client, master, min_confidence=0.3)
        ctx = ResolverContext(
            master=master,
            priors=DEFAULT_PRIORS,
            auto_threshold=0.90,
            tfidf_min_score=0.5,
            tfidf_min_matched_tokens=2,
            fuzzy_jw_min_score=0.30,
        )

        key = RetailerProductKey(
            retailer="tesco", name="Tomato Soup", gtin=None
        )
        result = handler(ctx, key)
        assert result is None

    def test_e5_handler_returns_none_on_json_error(self) -> None:
        from verdano.canonical import RetailerProductKey
        from verdano.erp.models import Product
        from verdano.llm.entity_resolution import make_llm_stratum
        from verdano.mapping.resolver import MasterIndex, ResolverContext
        from verdano.mapping.priors import DEFAULT_PRIORS

        products = [
            Product(
                sku="VG-SOUP-400",
                name="Tomato Basil Soup 400g",
                category="soup",
                status="active",
                current_gtins=[],
                legacy_gtins=[],
                aliases=[],
                case_pack=6,
                temperature_band="ambient",
            ),
        ]
        master = MasterIndex(products)

        client = FakeLLMClient("not valid json")
        handler = make_llm_stratum(client, master)
        ctx = ResolverContext(
            master=master,
            priors=DEFAULT_PRIORS,
            auto_threshold=0.90,
            tfidf_min_score=0.5,
            tfidf_min_matched_tokens=2,
            fuzzy_jw_min_score=0.30,
        )

        key = RetailerProductKey(
            retailer="tesco", name="Tomato Soup", gtin=None
        )
        result = handler(ctx, key)
        assert result is None


class TestLLMDepotFallback:
    def test_llm_depot_fallback_resolves(self) -> None:
        from verdano.erp.models import Customer
        from verdano.mapping.depot import resolve_depot

        customers = [
            Customer(
                id="SHIP-TESCO-DAV",
                name="Tesco Daventry Chilled",
                type="ship_to",
                parent_id="CUST-TESCO",
                warehouse_id="WH-DAV",
            ),
        ]

        llm_response = json.dumps({"id": "SHIP-TESCO-DAV", "confidence": 0.9})
        client = FakeLLMClient(llm_response)

        result = resolve_depot(
            "Something Unrecognizable",
            customers,
            "tesco",
            fuzzy_threshold=100,
            llm_client=client,
        )
        assert result == "SHIP-TESCO-DAV"

    def test_llm_depot_fallback_rejects_low_confidence(self) -> None:
        from verdano.erp.models import Customer
        from verdano.mapping.depot import resolve_depot

        customers = [
            Customer(
                id="SHIP-TESCO-DAV",
                name="Tesco Daventry Chilled",
                type="ship_to",
                parent_id="CUST-TESCO",
                warehouse_id="WH-DAV",
            ),
        ]

        llm_response = json.dumps({"id": "SHIP-TESCO-DAV", "confidence": 0.2})
        client = FakeLLMClient(llm_response)

        result = resolve_depot(
            "Something Unrecognizable",
            customers,
            "tesco",
            fuzzy_threshold=100,
            llm_client=client,
        )
        assert result is None
