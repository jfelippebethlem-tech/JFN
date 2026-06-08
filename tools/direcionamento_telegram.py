#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Envia ao Telegram o PACOTE MASTIGADO de direcionamento (p/ o Mestre Jorge encaminhar ao Claude do
celular): contratação + parâmetros + trecho do documento + parecer do GEMINI + a pergunta p/ o Claude
pensar em cima do Gemini.

Uso:
  PYTHONPATH=. .venv/bin/python -m tools.direcionamento_telegram --id "CNPJ-1-SEQ/ANO"
  PYTHONPATH=. .venv/bin/python -m tools.direcionamento_telegram --scan 8   # varre N editais RJ recentes
  (opção --so-flag envia só os amarelo/vermelho; default envia todos os avaliados)
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date, timedelta
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))
from compliance_agent.envfile import carregar_env

carregar_env()
from compliance_agent.collectors import pncp
from compliance_agent import direcionamento_cerebro as DC
from compliance_agent.notifications.telegram import enviar_mensagem


async def _docs_edital_ata(id_pncp: str) -> tuple[str, str]:
    docs = await pncp.baixar_documentos(id_pncp, max_arquivos=14)
    edital, ata = [], []
    for d in docs:
        t = (d.get("texto") or "")
        low = t.lower()
        if len(t) < 2000:
            continue
        # ata de julgamento real: tem desclassificações/inabilitações de licitantes (não só cláusula do edital)
        if (low.count("desclassific") + low.count("inabilit") >= 3) and "será desclassific" not in low[:3000]:
            ata.append(t)
        else:
            edital.append(t)
    return "\n".join(edital), "\n".join(ata)


async def _processar(c: dict, so_flag: bool) -> str | None:
    edital, ata = await _docs_edital_ata(c["id_pncp"])
    if not edital and not ata:
        return None
    res = await DC.avaliar_direcionamento(edital_txt=edital, ata_txt=ata,
                                          contexto={"objeto": c.get("objeto"), "valor": c.get("valor")})
    if so_flag and str(res.get("grau")) not in ("amarelo", "vermelho"):
        return None
    trecho = DC._trechos_relevantes(ata or edital, DC._KW_ATA if ata else DC._KW_EDITAL, 1500)
    pacote = DC.montar_pacote_claude(c, res, trecho)
    r = await enviar_mensagem(pacote)
    grau = res.get("grau")
    if not r.get("ok"):
        return f"  {c['id_pncp']}: grau={grau} | FALHA no envio: {r.get('error') or r}"
    return f"  ✅ {c['id_pncp']}: grau={grau} → enviado ao Telegram"


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", help="id_pncp específico")
    ap.add_argument("--scan", type=int, default=0, help="varrer N editais RJ recentes")
    ap.add_argument("--so-flag", action="store_true", help="enviar só amarelo/vermelho")
    args = ap.parse_args()

    casos = []
    if args.id:
        cs = await pncp.buscar_contratacoes(uf="RJ", modalidade=6,
                                            data_ini=date.today() - timedelta(days=120), data_fim=date.today(),
                                            max_paginas=2)
        casos = [c for c in cs if args.id in c["id_pncp"]][:1]
        if not casos:
            casos = [{"id_pncp": args.id, "objeto": "(consulta direta)", "valor": None}]
    else:
        n = max(1, args.scan or 6)
        cs = await pncp.buscar_contratacoes(uf="RJ", modalidade=6,
                                            data_ini=date.today() - timedelta(days=60), data_fim=date.today(),
                                            max_paginas=2)
        casos = cs[:n]

    print(f"processando {len(casos)} contratação(ões)…")
    enviados = 0
    for c in casos:
        try:
            msg = await _processar(c, args.so_flag)
        except Exception as e:  # noqa: BLE001
            msg = f"  {c.get('id_pncp')}: ERRO {str(e)[:80]}"
        if msg:
            print(msg)
            if "enviado" in msg:
                enviados += 1
    print(f"\nTotal enviado ao Telegram: {enviados}")


if __name__ == "__main__":
    asyncio.run(main())
