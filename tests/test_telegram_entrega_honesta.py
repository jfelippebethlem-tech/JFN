"""Entrega honesta no Telegram (plano mestre v2 §8 "Entrega honesta"; O7.6).

`silenciado` devolve `ok=False` e sucesso só com `result.message_id` inteiro conferido. Antes, o silêncio de
17/11 devolvia `{"ok": True, "silenciado": True}` e qualquer resposta com `ok: true` virava "enviado" — quem
chamava (rotas/produtos.py, canário, triagem…) declarava entrega que não houve (memória telegram-silencio-devolve-ok).

Transporte FALSO: `httpx.AsyncClient` trocado por um dublê; nenhuma mensagem real sai (o Yoda só fala quando o
dono pede).
"""
import asyncio
import json

import pytest

from compliance_agent.notifications import silencio, telegram


class _Resp:
    def __init__(self, data):
        self._d = data

    def json(self):
        return self._d


def _dublê(respostas, chamadas):
    class _Cliente:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, **kw):
            chamadas.append(url.rsplit("/", 1)[-1])
            return _Resp(respostas.pop(0))
    return _Cliente


@pytest.fixture
def ambiente(tmp_path, monkeypatch):
    monkeypatch.setattr(silencio, "DATA", tmp_path)
    (tmp_path / "telegram_silencio.json").write_text(json.dumps({"ativo": True}))
    monkeypatch.delenv("JFN_TELEGRAM_PEDIDO", raising=False)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "000:falso")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
    chamadas = []

    def usar(*respostas):
        monkeypatch.setattr(telegram.httpx, "AsyncClient", _dublê(list(respostas), chamadas))
        return chamadas
    return usar


def test_silenciado_devolve_ok_false_e_nao_chama_o_transporte(ambiente, tmp_path):
    chamadas = ambiente()
    r = asyncio.run(telegram.enviar_mensagem("aviso automático"))
    assert r["ok"] is False and r["silenciado"] is True
    assert chamadas == []
    r = asyncio.run(telegram.enviar_arquivo(tmp_path / "telegram_silencio.json", caption="x"))
    assert r["ok"] is False and r["silenciado"] is True
    assert chamadas == []


@pytest.mark.parametrize("resposta", [
    {"ok": True},                                  # ok sem result
    {"ok": True, "result": {}},                    # result sem message_id
    {"ok": True, "result": {"message_id": None}},
    {"ok": True, "result": {"message_id": "12"}},  # message_id não inteiro
    {"ok": True, "result": {"message_id": True}},  # bool não é id
    {"ok": False, "description": "Bad Request: chat not found"},
])
def test_sem_message_id_inteiro_nao_e_entrega(ambiente, tmp_path, resposta):
    ambiente(dict(resposta))
    r = asyncio.run(telegram.enviar_mensagem("resposta a comando", chat_id="123"))
    assert r["ok"] is False, r
    arq = tmp_path / "relatorio.pdf"
    arq.write_bytes(b"%PDF-1.4")
    ambiente(dict(resposta))
    r = asyncio.run(telegram.enviar_arquivo(arq, caption="pedido", chat_id="123"))
    assert r["ok"] is False, r


def test_message_id_inteiro_e_entrega(ambiente, tmp_path):
    chamadas = ambiente({"ok": True, "result": {"message_id": 4321, "chat": {"id": 123}}})
    r = asyncio.run(telegram.enviar_mensagem("resposta a comando", chat_id="123"))
    assert r["ok"] is True and r["result"]["message_id"] == 4321
    arq = tmp_path / "relatorio.pdf"
    arq.write_bytes(b"%PDF-1.4")
    ambiente({"ok": True, "result": {"message_id": 99}})
    r = asyncio.run(telegram.enviar_arquivo(arq, caption="pedido", chat_id="123"))
    assert r["ok"] is True and r["result"]["message_id"] == 99
    assert chamadas == ["sendMessage", "sendDocument"]


def test_fallback_de_markdown_tambem_confere_message_id(ambiente):
    chamadas = ambiente({"ok": False, "description": "Bad Request: can't parse entities"},
                        {"ok": True, "result": {}})
    r = asyncio.run(telegram.enviar_mensagem("nome_com_*", chat_id="123"))
    assert r["ok"] is False
    assert chamadas == ["sendMessage", "sendMessage"]
