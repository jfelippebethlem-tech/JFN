# -*- coding: utf-8 -*-
"""A API do Estado congela a paginação na página 10.000 — passar dali é andar sem sair do lugar.

DEFEITO MEDIDO (31/07/2026). `registros_folha` tinha **575 linhas** da folha do Executivo estadual
(`gesperj_estado`) enquanto a API declarava `totalElements = 909.916` para a competência 2026-06 —
0,06% do universo. E o progresso dizia `pagina: 12825`, ou seja: o coletor já havia caminhado mais
de meio milhão de registros.

Medido direto na fonte, com `size=50`:

    page=12825 · 12826 · 12840 · 12864 · 17000  → os MESMOS 50 registros (overlap 50/50)
    page=2000 · 4000 · 6000 · 8000 · 9000       → conteúdo distinto
    page=10000 em diante                        → fatia CONGELADA

É o teto de janela de resultados do backend. Acima dele a API não erra: ela devolve HTTP 200 com uma
fatia repetida — o pior tipo de falha, porque parece sucesso. O coletor caminhava, o dedup descartava
tudo, e ao chegar em `totalPages` (18.199) marcaria a competência como **completa** com 0,06% dos
dados.

Rendimento medido do coletor, 40 páginas em cada faixa:

    faixa congelada (a partir de 12825) → 2.000 registros, **0 novos**
    faixa válida    (a partir de 0)     → 2.000 registros, **458 novos**

`size` não ajuda (a API rejeita >50 com HTTP 400) e não há filtro para particionar: `orgao`,
`orgaoId` e `vinculo` são IGNORADOS (total não muda) e `nome` exige nome completo exato. Logo o
alcance real é 10.000 × 50 = **500.000 de 909.916 (55%)** — limite de FONTE, que precisa ficar dito
em voz alta em vez de virar "completa".
"""
from __future__ import annotations

import pytest

from compliance_agent.collectors import folha_estado as F


def test_existe_teto_de_pagina_declarado():
    """O número mágico precisa ter nome e viver no módulo, não espalhado no laço."""
    assert getattr(F, "_PAGINA_MAX", None) == 10_000


def test_pagina_alem_do_teto_nao_e_pedida(monkeypatch):
    """O ponto do defeito: pedir página ≥ 10.000 devolve fatia repetida com HTTP 200."""
    pedidas: list[int] = []

    def _get_falso(_client, params):
        pedidas.append(params["page"])
        return {"totalPages": 18_199, "remuneracoes": []}

    monkeypatch.setattr(F, "_get", _get_falso)
    monkeypatch.setattr(F, "_carregar_progresso",
                        lambda: {"competencia": "2026-06", "pagina": 9_998, "completa": False})
    monkeypatch.setattr(F, "_salvar_progresso", lambda *a, **k: None)

    F.coletar(paginas_por_run=20, pausa=0)

    assert pedidas, "nenhuma página pedida"
    assert max(pedidas) < F._PAGINA_MAX, (
        f"pediu página {max(pedidas)} — a partir de {F._PAGINA_MAX} a API repete a mesma fatia")


def test_parar_no_teto_nao_mente_dizendo_completa(monkeypatch):
    """`completa: true` com 55% dos dados faria o coletor nunca mais voltar nesta competência."""
    monkeypatch.setattr(F, "_get", lambda _c, p: {"totalPages": 18_199, "remuneracoes": []})
    monkeypatch.setattr(F, "_carregar_progresso",
                        lambda: {"competencia": "2026-06", "pagina": 9_998, "completa": False})
    salvos: list[tuple] = []
    monkeypatch.setattr(F, "_salvar_progresso",
                        lambda comp, pag, completa=False: salvos.append((comp, pag, completa)))

    r = F.coletar(paginas_por_run=20, pausa=0)

    assert r.get("teto_da_fonte") is True, "o resultado não avisa que parou no teto da fonte"
    assert all(not c for _, _, c in salvos), (
        f"marcou completa ao bater no teto — a competência ficaria congelada em 55%: {salvos}")


def test_fim_real_da_competencia_continua_marcando_completa(monkeypatch):
    """Guarda-costas: quando totalPages cabe abaixo do teto, `completa` volta a valer."""
    monkeypatch.setattr(F, "_get", lambda _c, p: {"totalPages": 3, "remuneracoes": []})
    monkeypatch.setattr(F, "_carregar_progresso",
                        lambda: {"competencia": "2026-06", "pagina": 0, "completa": False})
    salvos: list[tuple] = []
    monkeypatch.setattr(F, "_salvar_progresso",
                        lambda comp, pag, completa=False: salvos.append((comp, pag, completa)))

    r = F.coletar(paginas_por_run=20, pausa=0)

    assert not r.get("teto_da_fonte"), "não havia teto: totalPages=3 cabe inteiro"
    assert salvos and salvos[-1][2] is True, f"o fim real da competência não marcou completa: {salvos}"


@pytest.mark.parametrize("pagina_inicial", [0, 5_000, 9_999])
def test_faixa_valida_segue_sendo_percorrida(monkeypatch, pagina_inicial):
    """A correção não pode encolher o que já funcionava: abaixo do teto anda normal."""
    pedidas: list[int] = []
    monkeypatch.setattr(F, "_get", lambda _c, p: (pedidas.append(p["page"]) or
                                                  {"totalPages": 18_199, "remuneracoes": []}))
    monkeypatch.setattr(F, "_carregar_progresso",
                        lambda: {"competencia": "2026-06", "pagina": pagina_inicial, "completa": False})
    monkeypatch.setattr(F, "_salvar_progresso", lambda *a, **k: None)

    F.coletar(paginas_por_run=3, pausa=0)

    assert pedidas and pedidas[0] == pagina_inicial
