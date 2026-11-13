"""Laudo de motores 13/11/2026 (4.14): página posterior falhou → `parcial=True`, nunca "verificado".

Em 09/11/2026 o `jfn-fisc-refresh` teve 751 de 774 chamadas `/contratos` com HTTP 429. Se a página 1
passava e a 2 falhava, o loop fazia `break` e devolvia `verificado: True` — um conjunto PARCIAL
apresentado como completo. Os itens já colhidos valem (upsert), mas o resultado tem de dizer que falta.
"""
import asyncio

from compliance_agent.collectors import pncp


def _paginas(monkeypatch, falha_em: int, total: int = 3):
    async def _fake(endpoint, params, tentativas=3):
        p = params["pagina"]
        if p == falha_em:
            return None                     # 429 esgotou as tentativas
        return {"totalPaginas": total, "data": [{"numeroControlePNCP": f"x-{params.get('codigoModalidadeContratacao', 0)}-{p}"}]}
    monkeypatch.setattr(pncp, "_consulta_retry", _fake)
    monkeypatch.setattr(pncp.asyncio, "sleep", _sem_sono)


async def _sem_sono(_s):
    return None


def test_contratos_429_na_pagina_2_e_parcial(monkeypatch):
    _paginas(monkeypatch, falha_em=2)
    r = asyncio.run(pncp.coletar_contratos_pcrj("20260101", "20260630", cnpj_orgao="00000000000100"))
    assert r["parcial"] is True and r["verificado"] is False
    assert len(r["itens"]) == 1 and "página 2" in r["motivo"]


def test_contratos_completos_nao_sao_parciais(monkeypatch):
    _paginas(monkeypatch, falha_em=99)
    r = asyncio.run(pncp.coletar_contratos_pcrj("20260101", "20260630", cnpj_orgao="00000000000100"))
    assert r["verificado"] is True and r["parcial"] is False and len(r["itens"]) == 3


def test_contratos_pagina_1_falha_continua_indisponivel(monkeypatch):
    _paginas(monkeypatch, falha_em=1)
    r = asyncio.run(pncp.coletar_contratos_pcrj("20260101", "20260630", cnpj_orgao="00000000000100"))
    assert r["verificado"] is False and r["parcial"] is False and r["itens"] == []


def test_contratacoes_pagina_posterior_falha_e_parcial(monkeypatch):
    _paginas(monkeypatch, falha_em=2)
    r = asyncio.run(pncp.coletar_contratacoes_municipio_rio("20260101", "20260630", modalidades=[6, 8]))
    assert r["parcial"] is True and r["verificado"] is False and len(r["itens"]) == 2


def test_fisc_coletar_tudo_grava_o_parcial_e_declara(monkeypatch):
    """O resumo do refresh propaga o parcial: grava o que veio e diz quantas janelas ficaram incompletas."""
    from tools import fisc_coletar_tudo as F
    assert F._rotulo({"verificado": True, "parcial": False, "itens": [1]}) == ""
    assert "PARCIAL" in F._rotulo({"verificado": False, "parcial": True, "itens": [1], "motivo": "página 2"})
    assert "INDISPONÍVEL" in F._rotulo({"verificado": False, "parcial": False, "itens": []})
    assert F._gravavel({"verificado": False, "parcial": True, "itens": [1]}) is True
    assert F._gravavel({"verificado": False, "parcial": False, "itens": []}) is False
