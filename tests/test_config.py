import datetime as dt

import pytest

from mestre_yoda.config import ConfigError, Settings


def _base_env(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "key")


def test_from_env_minimo(monkeypatch):
    _base_env(monkeypatch)
    monkeypatch.delenv("YODA_ALLOWED_CHAT_IDS", raising=False)
    s = Settings.from_env()
    assert s.telegram_token == "tok"
    assert s.anthropic_api_key == "key"
    assert s.model == "claude-opus-4-8"
    assert s.effort == "high"


def test_faltando_token(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "key")
    with pytest.raises(ConfigError):
        Settings.from_env()


def test_effort_invalido(monkeypatch):
    _base_env(monkeypatch)
    monkeypatch.setenv("YODA_EFFORT", "turbo")
    with pytest.raises(ConfigError):
        Settings.from_env()


def test_max_history_minimo(monkeypatch):
    _base_env(monkeypatch)
    monkeypatch.setenv("YODA_MAX_HISTORY", "1")
    with pytest.raises(ConfigError):
        Settings.from_env()


def test_chat_ids_parse_e_allow(monkeypatch):
    _base_env(monkeypatch)
    monkeypatch.setenv("YODA_ALLOWED_CHAT_IDS", "10, 20 ;30")
    s = Settings.from_env()
    assert s.allowed_chat_ids == frozenset({10, 20, 30})
    assert s.chat_is_allowed(10)
    assert not s.chat_is_allowed(99)


def test_lista_vazia_libera_todos(monkeypatch):
    _base_env(monkeypatch)
    monkeypatch.setenv("YODA_ALLOWED_CHAT_IDS", "")
    s = Settings.from_env()
    assert s.chat_is_allowed(12345)


def test_web_search_padrao_ligado(monkeypatch):
    _base_env(monkeypatch)
    monkeypatch.delenv("YODA_ENABLE_WEB_SEARCH", raising=False)
    assert Settings.from_env().enable_web_search is True


def test_web_search_desligado(monkeypatch):
    _base_env(monkeypatch)
    monkeypatch.setenv("YODA_ENABLE_WEB_SEARCH", "false")
    assert Settings.from_env().enable_web_search is False


def test_briefing_desligado_por_padrao(monkeypatch):
    _base_env(monkeypatch)
    monkeypatch.delenv("YODA_BRIEFING_ENABLED", raising=False)
    s = Settings.from_env()
    assert s.briefing_enabled is False
    assert s.briefing_time == dt.time(7, 0)
    assert s.briefing_timezone == "America/Sao_Paulo"


def test_briefing_ligado_exige_chat_id(monkeypatch):
    _base_env(monkeypatch)
    monkeypatch.setenv("YODA_BRIEFING_ENABLED", "true")
    monkeypatch.delenv("YODA_BRIEFING_CHAT_ID", raising=False)
    with pytest.raises(ConfigError):
        Settings.from_env()


def test_briefing_completo(monkeypatch):
    _base_env(monkeypatch)
    monkeypatch.setenv("YODA_BRIEFING_ENABLED", "true")
    monkeypatch.setenv("YODA_BRIEFING_CHAT_ID", "45338178")
    monkeypatch.setenv("YODA_BRIEFING_TIME", "06:30")
    s = Settings.from_env()
    assert s.briefing_enabled is True
    assert s.briefing_chat_id == 45338178
    assert s.briefing_time == dt.time(6, 30)
    assert s.briefing_tzinfo().key == "America/Sao_Paulo"


def test_briefing_time_invalido(monkeypatch):
    _base_env(monkeypatch)
    monkeypatch.setenv("YODA_BRIEFING_TIME", "25h")
    with pytest.raises(ConfigError):
        Settings.from_env()


def test_briefing_timezone_invalido(monkeypatch):
    _base_env(monkeypatch)
    monkeypatch.setenv("YODA_BRIEFING_TIMEZONE", "Marte/Olympus")
    with pytest.raises(ConfigError):
        Settings.from_env()
