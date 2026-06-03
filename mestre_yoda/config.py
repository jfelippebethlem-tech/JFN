"""Configuração central, lida do ambiente.

Tudo que muda entre instalações vive aqui, para que nenhum outro módulo precise
ler variáveis de ambiente diretamente.
"""

from __future__ import annotations

import datetime as _dt
import os
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

try:  # carregamento opcional do .env — não é obrigatório em produção
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover - dotenv é só conveniência de dev
    pass


_VALID_EFFORTS = {"low", "medium", "high", "xhigh", "max"}
_VALID_PROVIDERS = {"anthropic", "openrouter", "compat"}

# Endpoint e modelo padrão quando se usa OpenRouter (provedor gratuito).
_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
_DEFAULT_OPENROUTER_MODEL = "stepfun/step-3.7-flash:free"

# Fuso e horário padrão da rotina "BOM DIA" (alinhado com README-AGENTES.md: 7:30).
_DEFAULT_BRIEFING_TIME = _dt.time(7, 30)
_DEFAULT_BRIEFING_TZ = "America/Sao_Paulo"

# Versão GA da ferramenta de busca na web do Claude (sem beta header).
WEB_SEARCH_TOOL = {"type": "web_search_20260209", "name": "web_search"}


class ConfigError(RuntimeError):
    """Configuração ausente ou inválida."""


def _parse_bool(raw: str | None, default: bool) -> bool:
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in ("1", "true", "yes", "sim", "on")


def _parse_time(raw: str | None, default: _dt.time) -> _dt.time:
    if raw is None or not raw.strip():
        return default
    raw = raw.strip()
    try:
        parts = raw.split(":")
        if len(parts) not in (2, 3):
            raise ValueError
        hh, mm = int(parts[0]), int(parts[1])
        ss = int(parts[2]) if len(parts) == 3 else 0
        return _dt.time(hh, mm, ss)
    except ValueError as exc:
        raise ConfigError(
            f"YODA_BRIEFING_TIME inválido: {raw!r}. Use HH:MM (ex.: 07:00)."
        ) from exc


def _parse_chat_ids(raw: str | None) -> frozenset[int]:
    if not raw:
        return frozenset()
    ids: set[int] = set()
    for piece in raw.replace(";", ",").split(","):
        piece = piece.strip()
        if not piece:
            continue
        try:
            ids.add(int(piece))
        except ValueError as exc:
            raise ConfigError(
                f"YODA_ALLOWED_CHAT_IDS contém um valor inválido: {piece!r}"
            ) from exc
    return frozenset(ids)


@dataclass(frozen=True)
class Settings:
    """Configurações imutáveis da aplicação."""

    telegram_token: str
    anthropic_api_key: str
    # Provedor de modelo: "anthropic" (Claude), "openrouter" (gratuito) ou
    # "compat" (qualquer endpoint OpenAI-compatible). Resolvido em from_env.
    provider: str = "anthropic"
    llm_api_key: str = ""
    llm_base_url: str = ""
    model: str = "claude-opus-4-8"
    db_path: str = "yoda_memory.db"
    effort: str = "high"
    max_history: int = 20
    enable_web_search: bool = True
    allowed_chat_ids: frozenset[int] = field(default_factory=frozenset)
    log_level: str = "INFO"
    # Resiliência (retry/backoff) e memória (resumo em lote + teto de fatos).
    max_retries: int = 2
    retry_base_delay: float = 0.5
    summary_buffer: int = 10
    max_facts: int = 200
    # Rotina diária "BOM DIA do Mestre Jorge" (migrada do bot original).
    briefing_enabled: bool = False
    briefing_chat_id: int | None = None
    briefing_time: _dt.time = _DEFAULT_BRIEFING_TIME
    briefing_timezone: str = _DEFAULT_BRIEFING_TZ
    # Caminho local do repositório — usado pelo /atualizar para git pull + rebuild.
    repo_path: str = "."

    @classmethod
    def from_env(cls) -> "Settings":
        telegram_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        if not telegram_token:
            raise ConfigError(
                "Variável de ambiente obrigatória ausente: TELEGRAM_BOT_TOKEN"
            )

        # Provedor de modelo. Sem chave Anthropic, cai para OpenRouter (grátis)
        # ou para um endpoint OpenAI-compatible genérico (Nous, Ollama, etc.).
        anthropic_api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
        openrouter_api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
        compat_base = os.getenv("YODA_LLM_BASE_URL", "").strip()
        compat_key = os.getenv("YODA_LLM_API_KEY", "").strip()

        forced = os.getenv("YODA_PROVIDER", "").strip().lower()
        if forced:
            provider = forced
        elif anthropic_api_key:
            provider = "anthropic"
        elif openrouter_api_key:
            provider = "openrouter"
        elif compat_base and compat_key:
            provider = "compat"
        else:
            raise ConfigError(
                "Nenhum provedor de modelo configurado. Defina UM destes:\n"
                "  - ANTHROPIC_API_KEY (Claude, pago), ou\n"
                "  - OPENROUTER_API_KEY (modelos :free, gratuito), ou\n"
                "  - YODA_LLM_BASE_URL + YODA_LLM_API_KEY (OpenAI-compatible)."
            )
        if provider not in _VALID_PROVIDERS:
            raise ConfigError(
                f"YODA_PROVIDER inválido: {provider!r}. "
                f"Use um de: {', '.join(sorted(_VALID_PROVIDERS))}."
            )

        # Resolve chave, endpoint e modelo conforme o provedor escolhido.
        generic_model = os.getenv("YODA_MODEL", "").strip()
        if provider == "anthropic":
            if not anthropic_api_key:
                raise ConfigError(
                    "YODA_PROVIDER=anthropic exige ANTHROPIC_API_KEY."
                )
            llm_api_key = anthropic_api_key
            llm_base_url = ""
            model = (
                generic_model
                or os.getenv("ANTHROPIC_MODEL", "").strip()
                or "claude-opus-4-8"
            )
        elif provider == "openrouter":
            if not openrouter_api_key:
                raise ConfigError(
                    "YODA_PROVIDER=openrouter exige OPENROUTER_API_KEY."
                )
            llm_api_key = openrouter_api_key
            llm_base_url = (
                os.getenv("OPENROUTER_BASE_URL", _OPENROUTER_BASE_URL).strip()
                or _OPENROUTER_BASE_URL
            )
            model = (
                generic_model
                or os.getenv("OPENROUTER_SMART_MODEL", "").strip()
                or _DEFAULT_OPENROUTER_MODEL
            )
        else:  # compat
            if not (compat_base and compat_key):
                raise ConfigError(
                    "YODA_PROVIDER=compat exige YODA_LLM_BASE_URL e "
                    "YODA_LLM_API_KEY."
                )
            llm_api_key = compat_key
            llm_base_url = compat_base
            model = generic_model or _DEFAULT_OPENROUTER_MODEL

        effort = os.getenv("YODA_EFFORT", "high").strip().lower()
        if effort not in _VALID_EFFORTS:
            raise ConfigError(
                f"YODA_EFFORT inválido: {effort!r}. "
                f"Use um de: {', '.join(sorted(_VALID_EFFORTS))}."
            )

        try:
            max_history = int(os.getenv("YODA_MAX_HISTORY", "20"))
        except ValueError as exc:
            raise ConfigError("YODA_MAX_HISTORY deve ser um inteiro.") from exc
        if max_history < 2:
            raise ConfigError("YODA_MAX_HISTORY deve ser pelo menos 2.")

        try:
            max_retries = int(os.getenv("YODA_MAX_RETRIES", "2"))
        except ValueError as exc:
            raise ConfigError("YODA_MAX_RETRIES deve ser um inteiro.") from exc
        if max_retries < 0:
            raise ConfigError("YODA_MAX_RETRIES não pode ser negativo.")

        try:
            retry_base_delay = float(os.getenv("YODA_RETRY_BASE_DELAY", "0.5"))
        except ValueError as exc:
            raise ConfigError("YODA_RETRY_BASE_DELAY deve ser numérico.") from exc
        if retry_base_delay < 0:
            raise ConfigError("YODA_RETRY_BASE_DELAY não pode ser negativo.")

        try:
            summary_buffer = int(os.getenv("YODA_SUMMARY_BUFFER", "10"))
        except ValueError as exc:
            raise ConfigError("YODA_SUMMARY_BUFFER deve ser um inteiro.") from exc
        if summary_buffer < 0:
            raise ConfigError("YODA_SUMMARY_BUFFER não pode ser negativo.")

        try:
            max_facts = int(os.getenv("YODA_MAX_FACTS", "200"))
        except ValueError as exc:
            raise ConfigError("YODA_MAX_FACTS deve ser um inteiro.") from exc
        if max_facts < 0:
            raise ConfigError("YODA_MAX_FACTS não pode ser negativo.")

        briefing_enabled = _parse_bool(
            os.getenv("YODA_BRIEFING_ENABLED"), default=False
        )
        briefing_chat_id_raw = os.getenv("YODA_BRIEFING_CHAT_ID", "").strip()
        briefing_chat_id: int | None = None
        if briefing_chat_id_raw:
            try:
                briefing_chat_id = int(briefing_chat_id_raw)
            except ValueError as exc:
                raise ConfigError(
                    "YODA_BRIEFING_CHAT_ID deve ser um inteiro."
                ) from exc
        if briefing_enabled and briefing_chat_id is None:
            raise ConfigError(
                "YODA_BRIEFING_ENABLED está ligado, mas YODA_BRIEFING_CHAT_ID "
                "não foi definido. Informe o chat que receberá a rotina diária."
            )

        briefing_time = _parse_time(
            os.getenv("YODA_BRIEFING_TIME"), _DEFAULT_BRIEFING_TIME
        )
        briefing_timezone = (
            os.getenv("YODA_BRIEFING_TIMEZONE", _DEFAULT_BRIEFING_TZ).strip()
            or _DEFAULT_BRIEFING_TZ
        )
        try:
            ZoneInfo(briefing_timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ConfigError(
                f"YODA_BRIEFING_TIMEZONE inválido: {briefing_timezone!r}."
            ) from exc

        return cls(
            telegram_token=telegram_token,
            anthropic_api_key=anthropic_api_key,
            provider=provider,
            llm_api_key=llm_api_key,
            llm_base_url=llm_base_url,
            model=model,
            db_path=os.getenv("YODA_DB_PATH", "yoda_memory.db").strip(),
            effort=effort,
            max_history=max_history,
            enable_web_search=_parse_bool(
                os.getenv("YODA_ENABLE_WEB_SEARCH"), default=True
            ),
            allowed_chat_ids=_parse_chat_ids(os.getenv("YODA_ALLOWED_CHAT_IDS")),
            log_level=os.getenv("YODA_LOG_LEVEL", "INFO").strip().upper(),
            max_retries=max_retries,
            retry_base_delay=retry_base_delay,
            summary_buffer=summary_buffer,
            max_facts=max_facts,
            briefing_enabled=briefing_enabled,
            briefing_chat_id=briefing_chat_id,
            briefing_time=briefing_time,
            briefing_timezone=briefing_timezone,
            repo_path=os.getenv("YODA_REPO_PATH", ".").strip() or ".",
        )

    def chat_is_allowed(self, chat_id: int) -> bool:
        """True se o chat pode falar com o bot (lista vazia = todos)."""
        return not self.allowed_chat_ids or chat_id in self.allowed_chat_ids

    def briefing_tzinfo(self) -> ZoneInfo:
        """Fuso horário (objeto) da rotina diária."""
        return ZoneInfo(self.briefing_timezone)
