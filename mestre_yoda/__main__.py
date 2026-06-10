"""Ponto de entrada: `python -m mestre_yoda`.

Monta as peças (configuração → memória → Hermes → bot) e inicia o *polling* do
Telegram.
"""

from __future__ import annotations

import logging
import sys

from .bot import YodaBot
from .config import ConfigError, Settings
from .hermes import HermesAgent
from .memory import ConversationMemory, MemoryStore
from .persona import YODA_SYSTEM_PROMPT


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # O httpx do telegram é falador demais em INFO.
    logging.getLogger("httpx").setLevel(logging.WARNING)


def main() -> int:
    try:
        settings = Settings.from_env()
    except ConfigError as exc:
        print(f"Erro de configuração: {exc}", file=sys.stderr)
        return 2

    _setup_logging(settings.log_level)
    logger = logging.getLogger("mestre_yoda")

    # Cliente do modelo conforme o provedor (Claude, OpenRouter ou compat).
    # Importado aqui para não exigir as libs de rede nos testes.
    from .providers import build_client

    client = build_client(settings)

    # Busca na web server-side só existe na Anthropic; nos demais, desliga.
    enable_web_search = (
        settings.enable_web_search and settings.provider == "anthropic"
    )
    if settings.enable_web_search and not enable_web_search:
        logger.info(
            "Busca na web desativada: provedor %r não tem web_search "
            "server-side. Cotações reais (yfinance) seguem funcionando.",
            settings.provider,
        )

    store = MemoryStore(settings.db_path)
    memory = ConversationMemory(
        store,
        max_history=settings.max_history,
        summary_buffer=settings.summary_buffer,
        max_facts=settings.max_facts,
    )

    agent = HermesAgent(
        client,
        memory,
        model=settings.model,
        system_prompt=YODA_SYSTEM_PROMPT,
        effort=settings.effort,
        enable_web_search=enable_web_search,
        max_retries=settings.max_retries,
        retry_base_delay=settings.retry_base_delay,
    )
    # O resumidor da memória é o próprio Hermes — fecha o ciclo aqui para
    # evitar dependência circular na construção.
    memory.set_summarizer(agent.summarize)

    bot = YodaBot(settings, agent, memory)
    app = bot.build_application()

    logger.info(
        "Mestre Yoda acordou. Provedor: %s | Modelo: %s. Começar, vamos.",
        settings.provider,
        settings.model,
    )
    try:
        app.run_polling(allowed_updates=["message"])
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
