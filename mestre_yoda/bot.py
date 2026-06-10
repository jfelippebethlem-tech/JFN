"""Camada de Telegram do Mestre Yoda.

Aqui mora tudo que é específico do Telegram. Esta camada traduz updates em
`AgentRequest`, chama o Hermes e devolve o texto — sem deixar detalhes da
plataforma vazarem para o agente.
"""

from __future__ import annotations

import logging

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from .briefing import compose_briefing
from .config import Settings
from .hermes import HermesAgent
from .memory import ConversationMemory
from .persona import greeting, help_text
from .protocol import CHAT, AgentRequest

logger = logging.getLogger(__name__)

_TELEGRAM_LIMIT = 4096


def _split(text: str, limit: int = _TELEGRAM_LIMIT) -> list[str]:
    """Quebra textos longos em pedaços que cabem numa mensagem do Telegram."""
    if len(text) <= limit:
        return [text]
    pedacos: list[str] = []
    restante = text
    while len(restante) > limit:
        corte = restante.rfind("\n", 0, limit)
        if corte <= 0:
            corte = limit
        pedacos.append(restante[:corte])
        restante = restante[corte:].lstrip("\n")
    if restante:
        pedacos.append(restante)
    return pedacos


class YodaBot:
    """Liga os handlers do Telegram ao Hermes e à memória."""

    def __init__(
        self,
        settings: Settings,
        agent: HermesAgent,
        memory: ConversationMemory,
    ) -> None:
        self._settings = settings
        self._agent = agent
        self._memory = memory

    def build_application(self) -> Application:
        app = (
            Application.builder()
            .token(self._settings.telegram_token)
            .post_init(self._on_startup)
            .build()
        )
        app.add_handler(CommandHandler("start", self._cmd_start))
        app.add_handler(CommandHandler("help", self._cmd_help))
        app.add_handler(CommandHandler("esquecer", self._cmd_forget))
        app.add_handler(CommandHandler("lembrancas", self._cmd_facts))
        app.add_handler(CommandHandler("status", self._cmd_status))
        app.add_handler(CommandHandler("metricas", self._cmd_metricas))
        app.add_handler(CommandHandler("atualizar", self._cmd_atualizar))
        app.add_handler(CommandHandler("bomdia", self._cmd_bomdia))
        app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self._on_message)
        )
        if self._settings.briefing_enabled:
            self._schedule_briefing(app)
        return app

    # --- startup ---------------------------------------------------------
    async def _on_startup(self, app: Application) -> None:
        """Notifica o Mestre Jorge quando o bot acorda (útil após atualizações)."""
        chat_id = self._settings.briefing_chat_id
        if chat_id is None:
            return
        try:
            await app.bot.send_message(
                chat_id,
                "Despertei, Mestre Jorge. 👁️ Mestre Yoda online.\n"
                "Use /help para ver os comandos disponíveis.",
            )
        except Exception:  # noqa: BLE001
            logger.warning("Não foi possível enviar notificação de startup")

    # --- rotina diária "BOM DIA" -----------------------------------------
    def _schedule_briefing(self, app: Application) -> None:
        """Agenda a rotina matinal no horário/fuso configurados."""
        job_queue = app.job_queue
        if job_queue is None:
            logger.warning(
                "JobQueue indisponível; rotina BOM DIA não agendada. "
                "Instale 'python-telegram-bot[job-queue]'."
            )
            return
        when = self._settings.briefing_time.replace(
            tzinfo=self._settings.briefing_tzinfo()
        )
        job_queue.run_daily(self._job_briefing, time=when, name="bom-dia")
        logger.info(
            "Rotina BOM DIA agendada para %s (%s), chat %s.",
            when.strftime("%H:%M"),
            self._settings.briefing_timezone,
            self._settings.briefing_chat_id,
        )

    async def _job_briefing(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        await self._deliver_briefing(context.bot, self._settings.briefing_chat_id)

    async def _deliver_briefing(self, bot, chat_id: int | None) -> None:
        if chat_id is None:
            return
        response = await compose_briefing(self._agent)
        if response.usage:
            logger.info("BOM DIA chat %s — uso: %s", chat_id, response.usage)
        for pedaco in _split(response.text):
            await bot.send_message(chat_id, pedaco)

    # --- guarda de acesso ------------------------------------------------
    def _denied(self, update: Update) -> bool:
        chat = update.effective_chat
        if chat is None:
            return True
        if not self._settings.chat_is_allowed(chat.id):
            logger.info("Chat não autorizado: %s", chat.id)
            return True
        return False

    # --- comandos --------------------------------------------------------
    async def _cmd_start(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        if self._denied(update) or update.message is None:
            return
        await update.message.reply_text(greeting())

    async def _cmd_help(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        if self._denied(update) or update.message is None:
            return
        await update.message.reply_text(help_text())

    async def _cmd_forget(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        if self._denied(update) or update.message is None:
            return
        self._memory.forget(update.effective_chat.id)
        await update.message.reply_text(
            "Pronto. Nossa conversa, esqueci eu. Recomeçar, podemos. 🍃\n"
            "(O que sobre você guardei como fato, mantive.)"
        )

    async def _cmd_facts(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        if self._denied(update) or update.message is None:
            return
        facts = self._memory.facts(update.effective_chat.id)
        if not facts:
            await update.message.reply_text(
                "Nada sobre você guardei ainda. Conversar mais, devemos."
            )
            return
        linhas = "\n".join(f"• {k}: {v}" for k, v in facts.items())
        await update.message.reply_text(f"O que sobre você lembro:\n\n{linhas}")

    async def _cmd_status(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        """Mostra a saúde da memória deste chat (mensagens, fatos, tamanho)."""
        if self._denied(update) or update.message is None:
            return
        s = self._memory.stats(update.effective_chat.id)
        kib = int(s["db_bytes"]) / 1024
        resumo = "sim" if s["has_summary"] else "não"
        await update.message.reply_text(
            "Minha memória, esta é:\n\n"
            f"• Mensagens guardadas: {s['messages']}\n"
            f"• Fatos sobre você: {s['facts']}\n"
            f"• Resumo da conversa: {resumo}\n"
            f"• Banco de memória: {kib:.1f} KiB\n\n"
            "Encher, ela não enche — podo o que é antigo, eu."
        )

    async def _cmd_bomdia(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Dispara a rotina BOM DIA sob demanda, no chat que pediu."""
        if self._denied(update) or update.message is None:
            return
        chat_id = update.effective_chat.id
        await context.bot.send_chat_action(chat_id, ChatAction.TYPING)
        await self._deliver_briefing(context.bot, chat_id)

    async def _cmd_metricas(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        """Mostra tokens consumidos desde o início desta sessão."""
        if self._denied(update) or update.message is None:
            return
        usage = self._agent.usage_today()
        if not usage:
            await update.message.reply_text(
                "Tokens usados: nenhum ainda nesta sessão."
            )
            return
        inp = usage.get("input_tokens", 0)
        out = usage.get("output_tokens", 0)
        cache_r = usage.get("cache_read_input_tokens", 0)
        cache_w = usage.get("cache_creation_input_tokens", 0)
        await update.message.reply_text(
            "Tokens desta sessão:\n\n"
            f"• Entrada: {inp:,}\n"
            f"• Saída: {out:,}\n"
            f"• Cache leitura: {cache_r:,}\n"
            f"• Cache escrita: {cache_w:,}\n\n"
            "Econômico com a Força, o Yoda é. 🌿"
        )

    async def _cmd_atualizar(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Puxa o código mais recente e reinicia (zero-downtime com Docker)."""
        if self._denied(update) or update.message is None:
            return
        chat_id = update.effective_chat.id

        async def _send(text: str) -> None:
            await context.bot.send_message(chat_id, text)

        from .updater import run_update  # importação lazy — mantém bot.py leve

        await run_update(_send, repo_path=self._settings.repo_path)

    # --- conversa --------------------------------------------------------
    async def _on_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if self._denied(update) or update.message is None or not update.message.text:
            return

        chat = update.effective_chat
        user = update.effective_user
        await context.bot.send_chat_action(chat.id, ChatAction.TYPING)

        request = AgentRequest(
            chat_id=chat.id,
            user_text=update.message.text,
            user_name=(user.full_name if user else None),
            kind=CHAT,
            metadata={"source": "telegram"},
        )
        response = await self._agent.respond(request)

        if response.usage:
            logger.info("Chat %s — uso: %s", chat.id, response.usage)

        for pedaco in _split(response.text):
            await update.message.reply_text(pedaco)
