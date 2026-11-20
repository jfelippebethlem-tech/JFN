# -*- coding: utf-8 -*-
"""Coleta de resultados do PNCP: API fora do ar NÃO é "zero resultado" (20/11/2026).

Medido no journal de 15/11/2026: o PNCP respondeu 503 em tudo, o resumo saiu
{"meses": 2, "certames": 7573, "itens_com_resultado": 0, "gravados": 0}, o serviço terminou "Finished" e
`pncp_resultado` ficou parado em 10/11 — a base de sobrepreço, sancionadas e comparador — sem aviso nenhum.
"""
from __future__ import annotations

import asyncio

from compliance_agent.collectors import pncp_resultados as P


class _Resp:
    def __init__(self, status, corpo=None):
        self.status_code, self._corpo = status, corpo

    def json(self):
        return self._corpo


class _Cliente:
    def __init__(self, status, corpo=None):
        self.status, self.corpo = status, corpo

    async def get(self, *a, **k):
        return _Resp(self.status, self.corpo)


def test_503_conta_como_falha_e_nao_como_lista_vazia():
    # 20/11/2026 (untangle dos coletores): 503 LEVANTA PncpIndisponivel (o chamador conta o mês/página como falha)
    # e continua contado — nunca volta como a lista vazia do "certame sem resultado".
    import pytest
    from compliance_agent.collectors.pncp import PncpIndisponivel
    P._FALHAS["api"] = 0
    with pytest.raises(PncpIndisponivel):
        asyncio.run(P._resultado_item(_Cliente(503), "42498600000171", "2026", 1, 1))
    with pytest.raises(PncpIndisponivel):
        asyncio.run(P._consulta_itens(_Cliente(503), "42498600000171", "2026", 1))
    with pytest.raises(PncpIndisponivel):
        asyncio.run(P._consulta(_Cliente(503), "/contratacoes/publicacao", {}))
    assert P._FALHAS["api"] == 3


def test_404_e_204_sao_ausencia_legitima_nao_falha():
    """Controle negativo: item sem resultado homologado (404/204) não acusa a fonte."""
    P._FALHAS["api"] = 0
    assert asyncio.run(P._resultado_item(_Cliente(404), "42498600000171", "2026", 1, 1)) == []
    assert asyncio.run(P._consulta_itens(_Cliente(204), "42498600000171", "2026", 1)) == []
    assert asyncio.run(P._resultado_item(_Cliente(200, [{"x": 1}]), "42498600000171", "2026", 1, 1)) == [{"x": 1}]
    assert P._FALHAS["api"] == 0


def test_veredito_da_coleta():
    ok, motivo = P.veredito_da_coleta({"meses": 2, "certames": 7573, "itens_com_resultado": 0, "gravados": 0,
                                       "falhas_api": 7573})
    assert ok is False and "INDISPONÍVEL" in motivo and "7573" in motivo          # o caso de 15/11
    assert P.veredito_da_coleta({"certames": 0, "itens_com_resultado": 0, "falhas_api": 4})[0] is False
    ok, motivo = P.veredito_da_coleta({"certames": 100, "itens_com_resultado": 80, "falhas_api": 3})
    assert ok is True and "parcial" in motivo
    assert P.veredito_da_coleta({"certames": 50, "itens_com_resultado": 0, "falhas_api": 0}) == (True, "")  # mês sem homologação
