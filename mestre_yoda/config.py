"""Configuração central, lida do ambiente.

Tudo que muda entre instalações vive aqui, para que nenhum outro módulo precise
ler variáveis de ambiente diretamente.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

try:  # carregamento opcional do .env — não é obrigatório em produção
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover - dotenv é só conveniência de dev
    pass


_VALID_EFFORTS = {"low", "medium", "high", "xhigh", "max"}

# Versão GA da ferramenta de busca na web do Claude (sem beta header).
WEB_SEARCH_TOOL = {"type": "web_search_20260209", "name": "web_search"}


class ConfigError(RuntimeError):
    """Configuração ausente ou inválida."""


def _parse_bool(raw: str | None, default: bool) -> bool:
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in ("1", "true", "yes", "sim", "on")


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
    model: str = "claude-opus-4-8"
    db_path: str = "yoda_memory.db"
    effort: str = "high"
    max_history: int = 20
    enable_web_search: bool = True
    allowed_chat_ids: frozenset[int] = field(default_factory=frozenset)
    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> "Settings":
        telegram_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        anthropic_api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()

        missing = [
            name
            for name, value in (
                ("TELEGRAM_BOT_TOKEN", telegram_token),
                ("ANTHROPIC_API_KEY", anthropic_api_key),
            )
            if not value
        ]
        if missing:
            raise ConfigError(
                "Variáveis de ambiente obrigatórias ausentes: "
                + ", ".join(missing)
            )

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

        return cls(
            telegram_token=telegram_token,
            anthropic_api_key=anthropic_api_key,
            model=os.getenv("ANTHROPIC_MODEL", "claude-opus-4-8").strip(),
            db_path=os.getenv("YODA_DB_PATH", "yoda_memory.db").strip(),
            effort=effort,
            max_history=max_history,
            enable_web_search=_parse_bool(
                os.getenv("YODA_ENABLE_WEB_SEARCH"), default=True
            ),
            allowed_chat_ids=_parse_chat_ids(os.getenv("YODA_ALLOWED_CHAT_IDS")),
            log_level=os.getenv("YODA_LOG_LEVEL", "INFO").strip().upper(),
        )

    def chat_is_allowed(self, chat_id: int) -> bool:
        """True se o chat pode falar com o bot (lista vazia = todos)."""
        return not self.allowed_chat_ids or chat_id in self.allowed_chat_ids
