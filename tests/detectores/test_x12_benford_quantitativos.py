# -*- coding: utf-8 -*-
"""X12 — Benford nos quantitativos, e a disciplina de não deixar a estatística virar acusação.

A ideia tem literatura brasileira específica (IBRAOP): quantitativo derivado de projeto obedece
razoavelmente à Lei de Benford; quando alguém ESCOLHE os números — para inflar o item caro e
enxugar o barato — a assinatura digital muda.

Só que Benford sobre quantitativo é mais fraco que sobre pagamento, por razões que nada têm a ver
com fraude: quantidade de engenharia sai de medição geométrica, planilha real tem muito "1"
legítimo, e unidades diferentes misturam escalas incomparáveis.

E há um número que só apareceu porque um teste falhou: com o `min_n=50` padrão do módulo, uma
série PERFEITAMENTE benfordiana é rotulada "NÃO CONFORMIDADE" em 100% das vezes — as faixas de
Nigrini pressupõem amostra grande, e abaixo de n≈800 o ruído amostral estoura o limiar sozinho.
O card passou a exigir 800 e a só ler a faixa quando o módulo a declara legível.

Daí as duas travas deste arquivo: **o score não passa de `medio` sem convergência**, e **amostra
pequena não produz achado** — baixar o limiar para caber no dado que existe é o modo mais comum
de um teste estatístico virar decoração.
"""
from __future__ import annotations

import math
import random

import pytest

from compliance_agent.detectores import REGISTRO
from compliance_agent.detectores.x12_benford_quantitativos import MIN_ITENS, fracao_redondos

X12 = REGISTRO["X12"]


def _benfordianos(n=1000, semente=7):
    """Série que segue Benford por construção: 10^u com u uniforme."""
    rnd = random.Random(semente)
    return [round(10 ** rnd.uniform(0, 4), 2) for _ in range(n)]


def _ctx(quantidades, **kw):
    base = {"processo": "P-1", "itens": [{"quantidade": q} for q in quantidades]}
    base.update(kw)
    return base


# ───────────────────────── amostra insuficiente ───────────────────────────────────────────────

def test_sem_itens_e_nao_avaliavel():
    r = X12.avaliar({"processo": "P-1"})
    assert r.status == "nao_avaliavel"
    assert "não há tabela de itens" in r.motivo_refutacao


def test_amostra_pequena_nao_vira_achado():
    """Baixar o limiar para caber no dado transformaria o teste em decoração."""
    r = X12.avaliar(_ctx([10.0] * 20))
    assert r.status == "nao_avaliavel"
    assert "decoração" in r.motivo_refutacao
    assert r.valores["benford_n"] == 20 and r.valores["min_itens"] == MIN_ITENS


def test_o_limiar_medido_e_MUITO_maior_que_o_default_do_modulo():
    """Com n=50 (o default de `analysis/benford`), 100% das séries benfordianas são acusadas."""
    from compliance_agent.analysis.benford import N_CONFIAVEL_MAD

    assert MIN_ITENS == N_CONFIAVEL_MAD >= 800


def test_serie_benfordiana_de_120_itens_NAO_e_acusada_pelo_card():
    """O teste que revelou o problema: n=120 dispara 'NÃO CONFORMIDADE' por ruído amostral."""
    r = X12.avaliar(_ctx(_benfordianos(120), min_itens=100))
    assert not any("NÃO CONFORMIDADE" in e["trecho"] for e in (r.evidencia or [])), (
        "faixa ilegível foi lida como achado")


def test_limiar_pode_ser_baixado_por_quem_chama_e_fica_registrado():
    r = X12.avaliar(_ctx(_benfordianos(60), min_itens=25))
    assert r.status in {"descartado", "confirmado"}
    assert r.valores["min_itens"] == 25


def test_itens_sem_quantidade_entram_como_lacuna_nao_como_zero():
    itens = [{"quantidade": q} for q in _benfordianos(900)] + [{"descricao": "verba"}] * 5
    r = X12.avaliar({"processo": "P-1", "itens": itens})
    assert r.valores["sem_quantidade"] == 5
    assert r.valores["n_com_quantidade"] == 900


# ───────────────────────── série conforme ─────────────────────────────────────────────────────

def test_serie_benfordiana_e_descartada():
    r = X12.avaliar(_ctx(_benfordianos()))
    assert r.status == "descartado" and r.score == 0.0


# ───────────────────────── T2 · arredondamento ────────────────────────────────────────────────

def test_planilha_toda_redonda_dispara_o_arredondamento():
    r = X12.avaliar(_ctx([10.0, 20.0, 30.0, 50.0, 100.0, 200.0] * 150))
    assert r.status == "confirmado"
    assert any("ARREDONDAMENTO" in e["trecho"] for e in r.evidencia)


def test_fracao_de_redondos_mede_o_que_promete():
    assert fracao_redondos([10.0, 20.0, 3.0, 7.0]) == pytest.approx(0.5)
    assert fracao_redondos([]) == 0.0


# ───────────────────────── o teto de gravidade ────────────────────────────────────────────────

def test_sinal_isolado_nao_passa_de_MEDIO():
    """Benford é triagem — o card assume isso em vez de fingir robustez."""
    r = X12.avaliar(_ctx([10.0, 20.0, 30.0, 50.0, 100.0, 200.0] * 150))
    conforme = str(r.valores["faixa_primeiro"] or "").upper().startswith("NÃO CONFORMIDADE")
    if not conforme:
        assert r.score <= 0.6, "sinal isolado passou de médio"


def test_convergencia_dos_dois_sinais_vira_forte():
    """Não conformidade E arredondamento excessivo: a planilha vai para a mesa."""
    r = X12.avaliar(_ctx([100.0] * 500 + [500.0] * 500))
    assert r.status == "confirmado"
    assert r.score >= 0.6


# ───────────────────────── contrato de saída ──────────────────────────────────────────────────

def test_explicacao_inocente_diz_que_isto_e_FILA_nao_achado():
    r = X12.avaliar(_ctx([100.0] * 500 + [500.0] * 500))
    assert "FILA DE CONFERÊNCIA" in r.explicacao_inocente
    assert "medição geométrica" in r.explicacao_inocente


def test_cobertura_parcial_e_declarada():
    itens = ([{"quantidade": 100.0} for _ in range(500)]
             + [{"quantidade": 500.0} for _ in range(500)]
             + [{"descricao": "verba"} for _ in range(7)])
    r = X12.avaliar({"processo": "P-1", "itens": itens})
    assert any("COBERTURA" in e["trecho"] for e in r.evidencia)


def test_evidencia_tem_hash_e_fonte():
    r = X12.avaliar(_ctx([100.0] * 500 + [500.0] * 500))
    for e in r.evidencia:
        assert e["hash"] and e["fonte"] and e["capturado_em"]


def test_quantidade_zero_ou_negativa_nao_entra():
    r = X12.avaliar(_ctx([0.0, -5.0] + _benfordianos(900)))
    assert r.valores["n_com_quantidade"] == 900
    assert r.valores["sem_quantidade"] == 2


def test_aceita_o_nome_alternativo_do_campo():
    itens = [{"quantidade_contratada": q} for q in _benfordianos(900)]
    r = X12.avaliar({"processo": "P-1", "itens": itens})
    assert r.valores["n_com_quantidade"] == 900
