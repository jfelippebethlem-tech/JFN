"""Envia o relatório da eleição 2026 (link + HTML + planilha) pelo Yoda (Telegram, metade outbound)."""
import asyncio
import os
import sys

from dotenv import load_dotenv

sys.path.insert(0, os.path.expanduser("~/JFN"))
load_dotenv(os.path.expanduser("~/JFN/.env"))
from compliance_agent.notifications.telegram import enviar_arquivo, enviar_mensagem  # noqa: E402

OUT = os.path.expanduser("~/JFN/output/eleicoes2026")


async def main(link, texto):
    r1 = await enviar_mensagem(f"{texto}\n\n{link}")
    r2 = await enviar_arquivo(f"{OUT}/relatorio_jorge_felippe_neto_2026.html", "Relatório interativo (abre no navegador do celular)")
    r3 = await enviar_arquivo(f"{OUT}/Eleicao2026_RJ_secoes_Jorge_Felippe_Neto.xlsx", "Planilha com todas as tabelas e o comparativo seção a seção")
    for r in (r1, r2, r3):
        print(r.get("ok"), r.get("error") or r.get("description") or "")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], sys.argv[2]))
