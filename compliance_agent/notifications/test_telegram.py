"""Teste oficial do Telegram do JFN.

Uso:
  python -m compliance_agent.notifications.test_telegram
  python -m compliance_agent.notifications.test_telegram "chat_id_aqui"
"""

import asyncio
import os
from datetime import date

from compliance_agent.notifications.telegram import (
    testar_conexao,
    enviar_resumo_diario,
    BOT_TOKEN,
    CHAT_ID,
)


async def main(chat_id: str = "") -> None:
    if not BOT_TOKEN:
        print("ERRO: TELEGRAM_BOT_TOKEN não configurado.")
        return

    target = chat_id.strip() or CHAT_ID
    if not target:
        print("ERRO: Nenhum chat_id disponível.")
        return

    print("Token: presente")
    print(f"Chat: {target}")
    print()

    ok = await testar_conexao(chat_id=target)
    print("Conexão:", "OK" if ok else "FALHA")
    if not ok:
        return

    resumo = {
        "data": str(date.today()),
        "doerj": {
            "total_publicacoes": 0,
            "nomeacoes": 0,
            "contratos": 0,
            "licitacoes": 0,
        },
        "alertas": {
            "alta": 1,
            "media": 0,
            "baixa": 0,
            "total": 1,
        },
        "alertas_detalhe": [
            {
                "titulo": "Bot de teste JFN ativo",
                "severidade": "alta",
            }
        ],
    }
    r = await enviar_resumo_diario(resumo)
    print("Resumo diário:", r)


if __name__ == "__main__":
    chat = os.sys.argv[1] if len(os.sys.argv) > 1 else ""
    asyncio.run(main(chat))
