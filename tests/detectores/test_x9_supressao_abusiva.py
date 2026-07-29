# -*- coding: utf-8 -*-
"""X9 — o lado esquecido do art. 125: encolher o contrato até ele deixar de ser o que foi licitado.

Toda a atenção da casa estava no acréscimo (X1 mede o quanto o contrato engorda). A supressão
nunca teve card, e é o vetor espelhado — mais discreto, porque encolher contrato não dispara
alarme de gasto.

Duas coisas que estes testes travam e que só aparecem lendo o texto legal com cuidado:

  · **A assimetria do art. 125.** "acréscimos ou supressões de até 25% ..., e, no caso de reforma
    ..., o limite para os ACRÉSCIMOS será de 50%". Os 50% são só do acréscimo; supressão fica nos
    25% em qualquer objeto, inclusive reforma. Usar o mesmo teto dos dois lados daria 50% de folga
    justamente onde a supressão costuma esvaziar o objeto.
  · **A perna espelhada do jogo de planilha.** Suprimir os itens BARATOS e manter os caros eleva o
    preço médio sem tocar no valor global — que é o número que todo mundo olha.
"""
from __future__ import annotations

import pytest

from compliance_agent.detectores import REGISTRO

X9 = REGISTRO["X9"]


def _sup(valor, objeto="supressão de itens do contrato"):
    return {"objeto": objeto, "valor_acrescido": valor}


def _ctx(**kw):
    base = {"processo": "P-1", "valor_inicial": 1_000_000.0, "aditivos": []}
    base.update(kw)
    return base


# ───────────────────────── honestidade ────────────────────────────────────────────────────────

def test_sem_valor_inicial_e_nao_avaliavel():
    r = X9.avaliar(_ctx(valor_inicial=0, aditivos=[_sup(300_000.0)]))
    assert r.status == "nao_avaliavel"


def test_sem_supressao_o_card_nao_se_aplica():
    r = X9.avaliar(_ctx(aditivos=[{"objeto": "acréscimo quantitativo", "valor_acrescido": 100.0}]))
    assert r.status == "descartado" and r.valores["supressao"] == 0.0


def test_supressao_dentro_do_teto_e_DIREITO_da_administracao():
    r = X9.avaliar(_ctx(aditivos=[_sup(150_000.0)]))     # 15%
    assert r.status == "descartado"
    assert "direito da Administração" in r.motivo_refutacao


# ───────────────────────── T1 · teto e a assimetria da reforma ────────────────────────────────

def test_supressao_acima_de_25_por_cento_e_critica():
    r = X9.avaliar(_ctx(aditivos=[_sup(300_000.0)]))     # 30%
    assert r.status == "confirmado" and r.score == pytest.approx(1.0)
    assert any("ACIMA DO TETO" in e["trecho"] for e in r.evidencia)


def test_supressao_rente_ao_teto_e_forte():
    r = X9.avaliar(_ctx(aditivos=[_sup(220_000.0)]))     # 22% — ≥80% do teto
    assert r.status == "confirmado" and r.score == pytest.approx(0.85)


def test_em_REFORMA_o_teto_de_supressao_continua_25():
    """O 50% do art. 125 é só do acréscimo — a assimetria que passa despercebida."""
    r = X9.avaliar(_ctx(tipo_objeto="reforma", aditivos=[_sup(300_000.0)]))
    assert r.status == "confirmado"
    assert r.valores["teto_supressao"] == pytest.approx(0.25)
    assert any("só para ACRÉSCIMOS" in e["trecho"] for e in r.evidencia)


# ───────────────────────── T2 · anuência ──────────────────────────────────────────────────────

def test_sem_anuencia_agrava():
    dentro = X9.avaliar(_ctx(aditivos=[_sup(220_000.0)]))
    sem = X9.avaliar(_ctx(aditivos=[_sup(220_000.0)], houve_anuencia=False))
    assert sem.score > dentro.score
    assert any("SEM ANUÊNCIA" in e["trecho"] for e in sem.evidencia)


def test_anuencia_ausente_e_LACUNA_nao_ausencia_de_acordo():
    """A anuência pode existir nos autos e não estar na base."""
    r = X9.avaliar(_ctx(aditivos=[_sup(220_000.0)]))
    assert "anuencia_nao_consta" in r.valores["lacunas"]


def test_anuencia_registrada_nao_agrava():
    r = X9.avaliar(_ctx(aditivos=[_sup(220_000.0)], houve_anuencia=True))
    assert not any("SEM ANUÊNCIA" in e["trecho"] for e in r.evidencia)


# ───────────────────────── T3 · assimetria de preço ───────────────────────────────────────────

def test_suprimir_so_o_BARATO_e_a_perna_espelhada_do_jogo_de_planilha():
    itens = [{"preco_contratado": 10.0, "referencial": 20.0} for _ in range(5)]
    r = X9.avaliar(_ctx(aditivos=[_sup(220_000.0)], itens_suprimidos=itens))
    assert r.score == pytest.approx(1.0)
    assert any("ASSIMETRIA DE PREÇO" in e["trecho"] for e in r.evidencia)


def test_supressao_equilibrada_de_itens_nao_dispara_o_T3():
    itens = [{"preco_contratado": 30.0, "referencial": 20.0} for _ in range(4)]
    r = X9.avaliar(_ctx(aditivos=[_sup(220_000.0)], itens_suprimidos=itens))
    assert not any("ASSIMETRIA" in e["trecho"] for e in r.evidencia)


def test_amostra_pequena_de_itens_vira_lacuna_nao_achado():
    r = X9.avaliar(_ctx(aditivos=[_sup(220_000.0)],
                        itens_suprimidos=[{"preco_contratado": 1.0, "referencial": 9.0}]))
    assert "itens_suprimidos_sem_referencial_suficiente" in r.valores["lacunas"]


# ───────────────────────── T4 · esvaziamento (art. 126) ───────────────────────────────────────

def test_supressao_que_consome_metade_do_objeto_e_transfiguracao():
    r = X9.avaliar(_ctx(aditivos=[_sup(600_000.0)]))     # 60%
    assert r.score == pytest.approx(1.0)
    e = " ".join(x["trecho"] for x in r.evidencia)
    assert "ESVAZIAMENTO" in e and "art. 126" in e


# ───────────────────────── contrato de saída ──────────────────────────────────────────────────

def test_explicacao_inocente_reconhece_supressao_legitima():
    r = X9.avaliar(_ctx(aditivos=[_sup(300_000.0)]))
    assert "legítima e até desejável" in r.explicacao_inocente
    assert "planilha com os itens retirados" in r.explicacao_inocente


def test_evidencia_tem_hash_e_fonte():
    r = X9.avaliar(_ctx(aditivos=[_sup(300_000.0)]))
    for e in r.evidencia:
        assert e["hash"] and e["fonte"] and e["capturado_em"]


def test_prorrogacao_e_reajuste_nao_entram_como_supressao():
    r = X9.avaliar(_ctx(aditivos=[
        {"objeto": "prorrogação de vigência", "valor_acrescido": 500_000.0},
        {"objeto": "reajuste pelo IPCA", "valor_acrescido": 300_000.0}]))
    assert r.status == "descartado" and r.valores["supressao"] == 0.0
