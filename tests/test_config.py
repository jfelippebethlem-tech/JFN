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


def test_resiliencia_padroes(monkeypatch):
    _base_env(monkeypatch)
    for var in ("YODA_MAX_RETRIES", "YODA_RETRY_BASE_DELAY", "YODA_SUMMARY_BUFFER"):
        monkeypatch.delenv(var, raising=False)
    s = Settings.from_env()
    assert s.max_retries == 2
    assert s.retry_base_delay == 0.5
    assert s.summary_buffer == 10
    assert s.max_facts == 200


def test_max_facts_invalido(monkeypatch):
    _base_env(monkeypatch)
    monkeypatch.setenv("YODA_MAX_FACTS", "-5")
    with pytest.raises(ConfigError):
        Settings.from_env()


def test_max_retries_negativo(monkeypatch):
    _base_env(monkeypatch)
    monkeypatch.setenv("YODA_MAX_RETRIES", "-1")
    with pytest.raises(ConfigError):
        Settings.from_env()


def test_summary_buffer_invalido(monkeypatch):
    _base_env(monkeypatch)
    monkeypatch.setenv("YODA_SUMMARY_BUFFER", "muito")
    with pytest.raises(ConfigError):
        Settings.from_env()


def test_briefing_desligado_por_padrao(monkeypatch):
    _base_env(monkeypatch)
    monkeypatch.delenv("YODA_BRIEFING_ENABLED", raising=False)
    s = Settings.from_env()
    assert s.briefing_enabled is False
    assert s.briefing_time == dt.time(7, 30)
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


# --- seleção de provedor de modelo --------------------------------------
def _clear_providers(monkeypatch):
    for var in (
        "ANTHROPIC_API_KEY",
        "OPENROUTER_API_KEY",
        "YODA_LLM_BASE_URL",
        "YODA_LLM_API_KEY",
        "YODA_PROVIDER",
    ):
        monkeypatch.delenv(var, raising=False)


def test_provider_anthropic_por_padrao(monkeypatch):
    _base_env(monkeypatch)
    s = Settings.from_env()
    assert s.provider == "anthropic"
    assert s.llm_api_key == "key"
    assert s.model == "claude-opus-4-8"


def test_provider_openrouter_sem_chave_anthropic(monkeypatch):
    _clear_providers(monkeypatch)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-abc")
    s = Settings.from_env()
    assert s.provider == "openrouter"
    assert s.llm_api_key == "sk-or-v1-abc"
    assert s.model == "stepfun/step-3.7-flash:free"
    assert s.llm_base_url.startswith("https://openrouter.ai")


def test_provider_openrouter_modelo_customizado(monkeypatch):
    _clear_providers(monkeypatch)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-abc")
    monkeypatch.setenv("OPENROUTER_SMART_MODEL", "qwen/qwen-2.5-72b-instruct:free")
    s = Settings.from_env()
    assert s.model == "qwen/qwen-2.5-72b-instruct:free"


def test_provider_compat_generico(monkeypatch):
    _clear_providers(monkeypatch)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("YODA_LLM_BASE_URL", "http://127.0.0.1:11434/v1")
    monkeypatch.setenv("YODA_LLM_API_KEY", "ollama")
    monkeypatch.setenv("YODA_MODEL", "llama3.1")
    s = Settings.from_env()
    assert s.provider == "compat"
    assert s.llm_base_url == "http://127.0.0.1:11434/v1"
    assert s.model == "llama3.1"


def test_sem_nenhum_provedor_erra(monkeypatch):
    _clear_providers(monkeypatch)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    with pytest.raises(ConfigError):
        Settings.from_env()


def test_yoda_model_sobrepoe_anthropic(monkeypatch):
    _base_env(monkeypatch)
    monkeypatch.setenv("YODA_MODEL", "claude-sonnet-4-6")
    s = Settings.from_env()
    assert s.model == "claude-sonnet-4-6"
