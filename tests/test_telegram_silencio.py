"""Dono 17/11/2026: avisos automáticos de sistema não vão mais ao Telegram (só log); respostas a comando vão."""
import asyncio
import json

from compliance_agent.notifications import silencio, telegram


def test_aviso_automatico_silenciado_e_resposta_a_comando_passa(tmp_path, monkeypatch):
    monkeypatch.setattr(silencio, "DATA", tmp_path)
    (tmp_path / "telegram_silencio.json").write_text(json.dumps({"ativo": True}))
    monkeypatch.delenv("JFN_TELEGRAM_PEDIDO", raising=False)
    r = asyncio.run(telegram.enviar_mensagem("🔴 serviço caiu"))
    assert r["ok"] is False and r["silenciado"] is True   # O7.6: silenciado não é entrega
    linha = json.loads((tmp_path / "telegram_silenciado.jsonl").read_text().splitlines()[-1])
    assert linha["inicio"] == "🔴 serviço caiu" and linha["origem"]
    # resposta a comando (chat_id explícito) nunca é silenciada; relatório pedido passa com a variável
    assert silencio.silenciar("x") is True
    monkeypatch.setenv("JFN_TELEGRAM_PEDIDO", "1")
    assert silencio.silenciar("x") is False


def test_sem_arquivo_de_silencio_fica_silenciado(tmp_path, monkeypatch):
    """Worktree/checkout sem o arquivo NÃO pode falar com o dono (aviso do zelador vazou assim em 22/11)."""
    monkeypatch.setattr(silencio, "DATA", tmp_path)
    monkeypatch.delenv("JFN_TELEGRAM_PEDIDO", raising=False)
    assert silencio.silenciar("x") is True
    (tmp_path / "telegram_silencio.json").write_text(json.dumps({"ativo": False}))
    assert silencio.silenciar("x") is False


def test_pedido_do_dono_numa_tarefa_passa_e_nao_vaza(tmp_path, monkeypatch):
    """Relatório pedido (rotas/produtos.py marca a tarefa) passa; o resto do processo segue silenciado."""
    monkeypatch.setattr(silencio, "DATA", tmp_path)
    (tmp_path / "telegram_silencio.json").write_text(json.dumps({"ativo": True}))
    monkeypatch.delenv("JFN_TELEGRAM_PEDIDO", raising=False)

    async def pedido():
        silencio.PEDIDO.set(True)
        return silencio.silenciar("relatório pedido")

    async def principal():
        r = await asyncio.create_task(pedido())
        return r, silencio.silenciar("aviso de sistema")

    assert asyncio.run(principal()) == (False, True)
