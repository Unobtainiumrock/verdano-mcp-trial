"""Tests for config helpers and iso_week validation."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from verdano.config import _find_env_file
from verdano.mcp_server.server import _validate_iso_week


class TestFindEnvFile:
    """_find_env_file resolution logic."""

    def test_verdano_project_root_takes_priority(self, tmp_path: Path) -> None:
        env = tmp_path / ".env"
        env.write_text("VERDANO_ERP_API_KEY=test\n")
        with patch.dict(os.environ, {"VERDANO_PROJECT_ROOT": str(tmp_path)}):
            result = _find_env_file()
        assert result == str(env)

    def test_walks_up_from_file_when_no_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("VERDANO_PROJECT_ROOT", raising=False)
        result = _find_env_file()
        assert isinstance(result, str)

    def test_cwd_fallback_when_nothing_found(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("VERDANO_PROJECT_ROOT", raising=False)
        monkeypatch.chdir(tmp_path)
        import verdano.config as cfg_mod
        monkeypatch.setattr(cfg_mod, "__file__", str(tmp_path / "nonexistent" / "config.py"))
        result = _find_env_file()
        assert result == ".env"


class TestValidateIsoWeek:
    """_validate_iso_week edge cases."""

    def test_valid_week(self) -> None:
        assert _validate_iso_week("2026-W20") is None

    def test_rejects_w00(self) -> None:
        err = _validate_iso_week("2026-W00")
        assert err is not None
        assert "out of range" in err["error"]

    def test_rejects_w99(self) -> None:
        err = _validate_iso_week("2026-W99")
        assert err is not None
        assert "out of range" in err["error"]

    def test_rejects_w53_in_non_53_week_year(self) -> None:
        # 2025 has only 52 ISO weeks
        err = _validate_iso_week("2025-W53")
        assert err is not None
        assert "out of range" in err["error"]

    def test_accepts_w53_in_53_week_year(self) -> None:
        # 2020 has 53 ISO weeks
        assert _validate_iso_week("2020-W53") is None

    def test_rejects_bad_format(self) -> None:
        err = _validate_iso_week("week20")
        assert err is not None
        assert "invalid iso_week format" in err["error"]

    def test_rejects_missing_w_prefix(self) -> None:
        err = _validate_iso_week("2026-20")
        assert err is not None
        assert "invalid iso_week format" in err["error"]
