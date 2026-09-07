"""Trava o bug de 2026-09-05: erro de rede gravado como ausência apaga o contrato do universo.

O sweep gravava SEM_ARQUIVO sempre que o PNCP não devolvia lista. Mas as respostas eram 502,
503, timeout e disconnect — falha de requisição, não ausência de documento. Como SEM_ARQUIVO
é definitivo e a fila excluía quem já tinha registro, 455 contratos sairiam da fila PARA SEMPRE
e eu concluiria "sem documento publicado" sobre o que nunca foi baixado.
"""
import asyncio

import pytest

from compliance_agent.collectors import pncp
from compliance_agent.collectors.pncp import PncpIndisponivel, baixar_arquivos_contrato


def _resposta(valor, monkeypatch):
    async def _fake(endpoint, params):
        return valor
    monkeypatch.setattr(pncp, "_get_pncp", _fake)


def test_requisicao_falha_levanta_em_vez_de_devolver_vazio(monkeypatch):
    """None = a requisição falhou. Devolver [] aqui seria afirmar que não há arquivo."""
    _resposta(None, monkeypatch)
    with pytest.raises(PncpIndisponivel):
        asyncio.run(baixar_arquivos_contrato("42498733000148", "2026", "708"))


def test_lista_vazia_e_ausencia_de_verdade(monkeypatch):
    """[] veio do PNCP: o contrato realmente não tem arquivo. Isso pode virar SEM_ARQUIVO."""
    _resposta([], monkeypatch)
    assert asyncio.run(baixar_arquivos_contrato("42498733000148", "2026", "708")) == []


def test_a_fila_do_sweep_retenta_erro_de_rede():
    """Sem esta cláusula o contrato com ERRO_REDE nunca mais seria tentado."""
    from tools.sweep_integra_contratos_pcrj import _pendentes
    import inspect
    sql = inspect.getsource(_pendentes)
    assert "ERRO_REDE" in sql, "a fila precisa retentar o que falhou por rede"
