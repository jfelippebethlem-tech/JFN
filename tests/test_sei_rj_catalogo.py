# -*- coding: utf-8 -*-
"""Catálogo do SEI estadual pela pesquisa pública (23/09/2026): parser do HTML do AJAX e desvio
dos registros "envenenados" que derrubam a janela de 50 inteira."""
from __future__ import annotations

import pytest

from tools.sei_rj_catalogo import Envenenada, parse_linhas, varrer_janelas

HTML = """<tr class="pesquisaTituloRegistro">
<td colspan="2" class="pesquisaTituloEsquerda" data-prot="SEI-150016/185935/2026"><a href="x" title="Acessar" class="arvore"><img border="0" src="../../svg/arvore.svg" alt="Acessar" title="Acessar" class="arvore" /></a>Contrata&ccedil;&atilde;o: Inexigibilidade n&ordm;<a href="x" class="protocoloNormal">SEI-150016/185935/2026</a></td>
<td class="pesquisaTituloDireita"></td></tr>
<tr><td class="pesquisaMetatag" width="33%"><b>Unidade:</b> <a alt="Serviço de Protocolo" title="Servi&ccedil;o de Protocolo" class="ancoraSigla">DETRAN/SERVPROT</a></td>
<td class="pesquisaMetatag" width="33%"></td><td class="pesquisaMetatag" width="33%"><b>Data:</b> 22/09/2026</td></tr>"""


def test_parse_linhas():
    [x] = parse_linhas(HTML)
    assert x == {"numero": "SEI-150016/185935/2026", "tipo": "Contratação: Inexigibilidade",
                 "unidade_sigla": "DETRAN/SERVPROT", "unidade_nome": "Serviço de Protocolo",
                 "orgao": "DETRAN", "data": "2026-09-22"}


def _fonte(total, envenenados, pagina=50):
    chamadas = []

    def buscar(inicio):
        chamadas.append(inicio)
        fim = min(inicio + pagina, total)
        if any(inicio <= b < fim for b in envenenados):
            raise Envenenada(inicio)
        return [{"numero": f"P{k}"} for k in range(inicio, fim)]
    return buscar, chamadas


def test_sem_envenenado_pagina_em_passos_de_50():
    buscar, chamadas = _fonte(230, [])
    linhas, env, perd = varrer_janelas(buscar, 230)
    assert len(linhas) == 230 and env == [] and perd == 0 and chamadas == [0, 50, 100, 150, 200]


@pytest.mark.parametrize("bs", [[73], [50], [99], [0], [229], [73, 160]])
def test_um_envenenado_por_faixa_perde_so_ele(bs):
    buscar, chamadas = _fonte(230, bs)
    linhas, env, perd = varrer_janelas(buscar, 230)
    assert sorted(env) == bs and perd == 0
    assert set(linhas) == set(range(230)) - set(bs)
    assert all(linhas[p]["numero"] == f"P{p}" for p in linhas)
    assert len(chamadas) < 60


def test_dois_envenenados_colados_contam_perda_sem_inventar():
    buscar, _ = _fonte(200, [60, 70])
    linhas, env, perd = varrer_janelas(buscar, 200)
    assert 60 not in linhas and 70 not in linhas
    assert len(linhas) + len(env) + perd == 200
    assert all(linhas[p]["numero"] == f"P{p}" for p in linhas)


def _base_datada(regs):
    """regs: [(numero, dias_atras, envenenado)] em ordem de data desc (como o servidor)."""
    import re as _re

    def pagina(pf, inicio):
        m = _re.search(r"NOW/DAY([+-]\d+)DAYS TO NOW/DAY([+-]\d+)DAYS", pf)
        lo, hi = -int(m.group(1)), -int(m.group(2))          # dias atrás: (hi, lo]
        sel = [r for r in regs if hi < r[1] <= lo]
        orgs = _re.findall(r"id_org_ger:(\w+)", pf)
        if orgs:
            sel = [r for r in sel if r[3] in orgs]
        jan = sel[inicio:inicio + 50]
        if any(r[2] for r in jan):
            raise Envenenada(inicio)
        return len(sel) if jan else 0, [{"numero": r[0]} for r in jan]
    return pagina


def test_bissecao_por_data_isola_o_envenenado():
    from tools.sei_rj_catalogo import coletar_por_data
    regs = [(f"P{k}", k // 7, k in (13, 14, 200, 201, 202), f"o{k % 4}") for k in range(700)]  # 7/dia; grupos colados
    regs += [(f"Q{k}", 500, k == 3, "o1") for k in range(120)]                        # dia lotado com envenenado
    out = coletar_por_data(_base_datada(regs), "sta_prot:P", b=1000, orgaos=["o0", "o1", "o2", "o3"])
    esperados = {r[0] for r in regs if not r[2]}
    assert set(out["linhas"]) <= esperados
    falta = esperados - set(out["linhas"])
    assert out["perdidos"] == len(falta) and out["envenenados"] == 6
    # só se perde o que precede um envenenado na MESMA fatia dia × órgão (limite do servidor), e é contado
    fatias_env = {(r[1], r[3]) for r in regs if r[2]}
    assert all((r[1], r[3]) in fatias_env for r in regs if r[0] in falta)
    assert len(falta) <= 7
    assert out["fatias_perdidas"] == []


def test_total_da_consulta_desvia_da_primeira_janela_envenenada():
    from tools.sei_rj_catalogo import total_da_consulta
    regs = [(f"P{k}", 1, k == 0, "o0") for k in range(120)]
    assert total_da_consulta(_base_datada(regs), "x AND dta_ger:[NOW/DAY-5DAYS TO NOW/DAY+1DAYS}") == 120
    todos = [(f"P{k}", 1, True, "o0") for k in range(3)]
    assert total_da_consulta(_base_datada(todos), "x AND dta_ger:[NOW/DAY-5DAYS TO NOW/DAY+1DAYS}") is None
