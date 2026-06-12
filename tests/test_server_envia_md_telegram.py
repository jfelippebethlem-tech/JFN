# -*- coding: utf-8 -*-
"""
Teste do envio de documentos ao Telegram (P2.3 do QA):
`_enviar_docs_telegram` deve incluir o path_md na lista enviada (junto de pdf/xlsx/lex),
p/ o Yoda mandar MD+PDF (antes o MD ficava de fora).

Stubado (sem rede/sem bot): substituímos as funções do módulo telegram e capturamos os paths enviados.

Como rodar:
    cd ~/JFN && .venv/bin/python -m pytest tests/test_server_envia_md_telegram.py -v
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import server  # noqa: E402
from compliance_agent.notifications import telegram as _tg  # noqa: E402


def _capturar(monkeypatch):
    enviados: list[str] = []
    msgs: list[str] = []

    async def fake_arquivo(p, caption=""):
        enviados.append(p)

    async def fake_msg(txt):
        msgs.append(txt)

    monkeypatch.setattr(_tg, "enviar_arquivo", fake_arquivo)
    monkeypatch.setattr(_tg, "enviar_mensagem", fake_msg)
    return enviados, msgs


def test_inclui_md_junto_de_pdf_xlsx_lex(monkeypatch):
    enviados, _ = _capturar(monkeypatch)
    result = {
        "path_md": "/r/x.md", "path_pdf": "/r/x.pdf",
        "path_xlsx": "/r/x.xlsx", "path_lex": "/r/x_lex.pdf",
        "resumo": "ok",
    }
    asyncio.run(server._enviar_docs_telegram(result, "Relatório X"))
    assert "/r/x.md" in enviados   # P2.3: o MD agora vai junto
    assert "/r/x.pdf" in enviados
    assert "/r/x.xlsx" in enviados
    assert "/r/x_lex.pdf" in enviados


def test_pdf_vem_antes_do_md(monkeypatch):
    """PDF primeiro (recebe a caption), MD logo após — ordem MD+PDF chega completa."""
    enviados, _ = _capturar(monkeypatch)
    result = {"path_md": "/r/x.md", "path_pdf": "/r/x.pdf", "resumo": ""}
    asyncio.run(server._enviar_docs_telegram(result, "T"))
    assert enviados.index("/r/x.pdf") < enviados.index("/r/x.md")


def test_so_md_disponivel_ainda_envia(monkeypatch):
    """Se só houver MD (sem PDF), ele ainda deve ser enviado — não cai no 'sem arquivos'."""
    enviados, msgs = _capturar(monkeypatch)
    result = {"path_md": "/r/so.md", "resumo": ""}
    asyncio.run(server._enviar_docs_telegram(result, "T"))
    assert enviados == ["/r/so.md"]
    assert msgs == []  # não avisou "sem arquivos"


def test_sem_arquivos_avisa(monkeypatch):
    enviados, msgs = _capturar(monkeypatch)
    asyncio.run(server._enviar_docs_telegram({"resumo": ""}, "T"))
    assert enviados == []
    assert msgs and "sem arquivos" in msgs[0]
