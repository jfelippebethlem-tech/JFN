# -*- coding: utf-8 -*-
"""Lift por detector — publicar o número muda a fila; escondê-lo mantém sinal inútil no topo.

Quatro erros que este painel existe para não cometer:

  1. **Ordenar amostra pequena junto com amostra grande.** Vinte empresas não sustentam razão de
     taxas; um lift 4,0 sobre n=12 no topo da lista desviaria a atenção do fiscal.
  2. **Esconder lift abaixo de 1.** É informação: o sinal aponta para empresas MENOS sancionadas
     que a média, e usá-lo para priorizar desperdiça atenção.
  3. **Deixar detector circular disputar o ranking.** Quem usa sanção como insumo prevê sanção
     por construção.
  4. **Ler lift alto como grau de evidência.** Detector preditivo produz achado mais VALIOSO, não
     achado mais PROVADO.
"""
from __future__ import annotations

import pytest

from compliance_agent.reporting import painel_lift as L


def _res(*detectores, taxa_base=0.07):
    return {"ok": True, "taxa_base": taxa_base, "universo": 10000,
            "sancionados_universo": 700, "detectores": list(detectores)}


def _d(nome, n=100, lift=1.0, circular=False):
    return {"detector": nome, "n": n, "sancionados": int(n * 0.1), "taxa": 0.1,
            "lift": lift, "circular": circular}


# ─────────────────── a classificação ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("lift,classe", [(3.0, "forte"), (1.5, "util"), (1.0, "neutro"),
                                         (0.5, "nao_prediz")])
def test_faixas_de_lift(lift, classe):
    assert L.classificar(lift, 100)[0] == classe


def test_amostra_pequena_tem_classe_PROPRIA_e_nao_vira_neutro():
    """Lift 4,0 sobre 12 empresas não é 'forte' — é ruído com aparência de medição."""
    classe, leitura = L.classificar(4.0, 12)
    assert classe == "amostra_pequena" and "12 empresas" in leitura


def test_detector_circular_nao_disputa_o_ranking():
    classe, leitura = L.classificar(9.9, 500, circular=True)
    assert classe == "circular" and "por construção" in leitura


def test_sem_sinal_registrado_e_NAO_MEDIDO_nunca_sem_valor():
    classe, leitura = L.classificar(None, 0)
    assert classe == "nao_medido" and "não 'sem valor'" in leitura


# ─────────────────── lift abaixo de 1 é publicado ─────────────────────────────────────────────

def test_lift_abaixo_de_um_vira_ALERTA_e_nao_some():
    p = L.montar(_res(_d("corrida_dezembro", n=120, lift=0.59)))
    assert p["alertas"] and "corrida_dezembro" in p["alertas"][0]
    assert "MENOS sancionadas" in p["detectores"][0]["leitura"]


def test_o_detector_ruim_aparece_na_tabela_do_html():
    html = L.render_html(L.montar(_res(_d("ruim", n=120, lift=0.4))))
    assert "ruim" in html and "0.40" in html


# ─────────────────── ordenação por utilidade real ─────────────────────────────────────────────

def test_amostra_pequena_fica_ABAIXO_de_quem_tem_amostra():
    p = L.montar(_res(_d("pequeno_mas_alto", n=10, lift=8.0),
                      _d("grande_e_util", n=200, lift=1.6)))
    assert [d["detector"] for d in p["detectores"]][0] == "grande_e_util"


def test_dentro_da_mesma_classe_ordena_por_lift():
    p = L.montar(_res(_d("a", n=100, lift=2.1), _d("b", n=100, lift=3.4)))
    assert [d["detector"] for d in p["detectores"]] == ["b", "a"]


def test_circular_vai_para_o_fim():
    p = L.montar(_res(_d("circ", n=500, lift=9.0, circular=True), _d("normal", n=100, lift=1.5)))
    assert p["detectores"][-1]["detector"] == "circ"


def test_conta_quantos_tem_amostra_suficiente():
    p = L.montar(_res(_d("a", n=100, lift=2.0), _d("b", n=5, lift=2.0)))
    assert p["n_detectores"] == 2 and p["n_com_amostra"] == 1


# ─────────────────── honestidade ──────────────────────────────────────────────────────────────

def test_sem_medicao_o_painel_declara_e_nao_desenha_tabela():
    p = L.montar({"ok": False, "erro": "sem sinal_ledger"})
    assert p["estado"] == "sem_medicao"
    assert "<table" not in L.render_html(p)


def test_ressalva_diz_que_o_gabarito_e_PROXY():
    p = L.montar(_res(_d("a")))
    assert "PROXY" in p["ressalva"] and "nunca vira sanção" in p["ressalva"]


def test_ressalva_impede_ler_lift_como_grau_de_evidencia():
    p = L.montar(_res(_d("a")))
    assert "não promove grau" in p["ressalva"].replace("NÃO", "não")
    assert "mais valioso, não achado mais provado" in p["ressalva"]


def test_taxa_base_sai_no_html_para_o_lift_ser_interpretavel():
    html = L.render_html(L.montar(_res(_d("a"), taxa_base=0.0701)))
    assert "7.01%" in html or "7,01%" in html
