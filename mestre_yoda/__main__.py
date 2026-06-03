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

    # Cliente Claude (async). Importado aqui para não exigir a lib nos testes.
    from anthropic import AsyncAnthropic

    client = AsyncAnthropic(api_key=settings.anthropic_api_key)

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
        enable_web_search=settings.enable_web_search,
        max_retries=settings.max_retries,
        retry_base_delay=settings.retry_base_delay,
    )
    # O resumidor da memória é o próprio Hermes — fecha o ciclo aqui para
    # evitar dependência circular na construção.
    memory.set_summarizer(agent.summarize)

    bot = YodaBot(settings, agent, memory)
    app = bot.build_application()

    logger.info("Mestre Yoda acordou. Modelo: %s. Começar, vamos.", settings.model)
    try:
        app.run_polling(allowed_updates=["message"])
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
