# -*- coding: utf-8 -*-
"""Rede de proteção do detector J7 — inabilitação seletiva (dois pesos, duas medidas).

A unidade de análise é o **PAR**: mesma classe de falha, tratamentos divergentes. Um licitante
é inabilitado por certidão vencida enquanto outro, com a mesma falha, é saneado. Quando o
tolerado é o VENCEDOR, é a assinatura do favorecimento.

O detector tem uma trava de honestidade rara e importante: mesmo achando o par objetivo, ele
**não condena sozinho** — exige a confirmação de que as falhas são equivalentes. Sem isso vira
`nao_avaliavel`, porque o próprio pareamento pode ter juntado coisas de gravidade diferente.

E o contrapeso legal: o art. 64 MANDA sanear vício formal. Saneamento aplicado à mesma régua
para todos não é favorecimento — é cumprir a lei.

Sem rede, sem banco, sem LLM.
"""
from __future__ import annotations

import pytest

from compliance_agent.detectores.base import ANCORAS, STATUS_VALIDOS
from compliance_agent.detectores.j7_inabilitacao_seletiva import (
    J7InabilitacaoSeletiva,
    classificar_classe_falha,
)

_P = {"processo": "SEI-TESTE/000023/2026"}
_EQUIV = {"nivel": "falhas-equivalentes", "trecho": "ambas por certidão vencida na mesma sessão"}


def _dec(cnpj: str, falha: str, decisao: str, vencedor: bool = False) -> dict:
    return {"cnpj": cnpj, "falha": falha, "decisao": decisao, "vencedor": vencedor}


# ───────────────────────────── classificação de falha ─────────────────────────────────────────

@pytest.mark.parametrize("texto,classe", [
    ("certidão vencida do FGTS", "certidao_vencida"),
    ("CND vencida", "certidao_vencida"),
])
def test_classifica_falha_por_palavra_chave(texto, classe):
    assert classificar_classe_falha(texto) == classe


def test_falha_sem_palavra_chave_cai_em_outra():
    """Classe genérica NÃO força pareamento — é o guard contra parear coisas incomparáveis."""
    assert classificar_classe_falha("problema não especificado") == "outra"
    assert classificar_classe_falha("") == "outra"


# ───────────────────────────── invariante de honestidade ──────────────────────────────────────

def test_menos_de_duas_decisoes_e_nao_avaliavel():
    res = J7InabilitacaoSeletiva().avaliar({
        **_P, "decisoes": [_dec("111", "certidão vencida", "inabilitado")]})
    assert res.status == "nao_avaliavel"
    assert res.score == 0.0
    assert "campo ausente ≠ 0" in res.motivo_refutacao


def test_decisao_sem_resultado_mapeavel_e_ignorada():
    res = J7InabilitacaoSeletiva().avaliar({
        **_P, "decisoes": [_dec("111", "certidão vencida", "inabilitado"),
                           _dec("222", "certidão vencida", "situação indefinida")]})
    assert res.valores["n_decisoes_validas"] == 1
    assert res.status == "nao_avaliavel"


# ───────────────────────────── tratamento uniforme é legítimo ─────────────────────────────────

def test_todos_inabilitados_na_mesma_classe_nao_e_dois_pesos():
    res = J7InabilitacaoSeletiva().avaliar({
        **_P, "decisoes": [_dec("111", "certidão vencida", "inabilitado"),
                           _dec("222", "certidão vencida", "inabilitado")]})
    assert res.status == "descartado"
    assert res.score == 0.0


def test_todos_saneados_na_mesma_classe_e_o_art_64_cumprido():
    """A lei MANDA sanear vício formal. Diligência uniforme é legalidade, não favorecimento."""
    res = J7InabilitacaoSeletiva().avaliar({
        **_P, "decisoes": [_dec("111", "certidão vencida", "diligencia"),
                           _dec("222", "certidão vencida", "saneamento")]})
    assert res.status == "descartado"
    assert "art.64" in res.explicacao_inocente or "art.64" in res.motivo_refutacao


def test_falhas_de_classes_diferentes_nao_sao_pareadas():
    """Inabilitar por um motivo e tolerar outro, diferente, não é dois pesos — são duas réguas."""
    res = J7InabilitacaoSeletiva().avaliar({
        **_P, "decisoes": [_dec("111", "certidão vencida", "inabilitado"),
                           _dec("222", "problema não especificado", "diligencia")]})
    assert res.valores["n_pares_divergentes"] == 0
    assert res.status == "descartado"


# ───────────────────────────── a trava da equivalência ────────────────────────────────────────

def test_par_divergente_sem_confirmacao_de_equivalencia_nao_condena():
    """Trava de honestidade: o pareamento objetivo pode ter juntado falhas de gravidade distinta.

    Sem a confirmação, o detector declara `nao_avaliavel` em vez de acusar por conta própria.
    """
    res = J7InabilitacaoSeletiva().avaliar({
        **_P, "decisoes": [_dec("111", "certidão vencida", "inabilitado"),
                           _dec("222", "certidão vencida", "diligencia")]})
    assert res.valores["n_pares_divergentes"] == 1
    assert res.status == "nao_avaliavel"
    assert res.score == 0.0
    assert "não condena" in res.motivo_refutacao


def test_rubrica_de_falhas_distintas_descarta_o_par():
    res = J7InabilitacaoSeletiva().avaliar({
        **_P, "decisoes": [_dec("111", "certidão vencida", "inabilitado"),
                           _dec("222", "certidão vencida", "diligencia")],
        "_rubrica_equivalencia": {"nivel": "falhas-distintas",
                                  "trecho": "uma era vício insanável, a outra formal"}})
    assert res.status == "descartado"
    assert res.score == 0.0


# ───────────────────────────── o achado ───────────────────────────────────────────────────────

def test_par_com_equivalencia_confirmada_e_forte():
    res = J7InabilitacaoSeletiva().avaliar({
        **_P, "decisoes": [_dec("111", "certidão vencida", "inabilitado"),
                           _dec("222", "certidão vencida", "diligencia")],
        "_rubrica_equivalencia": _EQUIV})
    assert res.score >= ANCORAS["forte"]
    assert res.status == "confirmado"


def test_tolerado_que_e_o_VENCEDOR_e_critico():
    """Rigor para o concorrente, tolerância para o preferido — a assinatura do dois-pesos."""
    res = J7InabilitacaoSeletiva().avaliar({
        **_P, "decisoes": [_dec("111", "certidão vencida", "inabilitado"),
                           _dec("222", "certidão vencida", "habilitado", vencedor=True)],
        "_rubrica_equivalencia": _EQUIV})
    assert res.score >= ANCORAS["critico"] or res.score == pytest.approx(1.0)
    assert "dois-pesos" in res.motivo_refutacao


def test_mesma_empresa_em_momentos_distintos_nao_e_dois_pesos():
    """Dois-pesos é entre LICITANTES diferentes; a mesma empresa tratada de formas distintas em
    sessões distintas é outra discussão."""
    res = J7InabilitacaoSeletiva().avaliar({
        **_P, "decisoes": [_dec("111", "certidão vencida", "inabilitado"),
                           _dec("111", "certidão vencida", "diligencia")]})
    assert res.valores["n_pares_divergentes"] == 0


def test_serie_historica_da_comissao_entra_no_pareamento():
    """A unidade de análise pode cruzar sessões da MESMA comissão."""
    res = J7InabilitacaoSeletiva().avaliar({
        **_P, "comissao": "CPL-01",
        "decisoes": [_dec("111", "certidão vencida", "inabilitado")],
        "serie_comissao": [_dec("222", "certidão vencida", "diligencia")],
        "_rubrica_equivalencia": _EQUIV})
    assert res.valores["n_decisoes_validas"] == 2
    assert res.score >= ANCORAS["forte"]


def test_schema_de_saida_conforme_spec():
    d = J7InabilitacaoSeletiva().avaliar({
        **_P, "decisoes": [_dec("111", "certidão vencida", "inabilitado"),
                           _dec("222", "certidão vencida", "diligencia")],
        "_rubrica_equivalencia": _EQUIV}).to_dict()
    for campo in ("detector", "processo", "score", "valores", "evidencia",
                  "explicacao_inocente", "refutada", "motivo_refutacao", "status"):
        assert campo in d
    assert d["detector"] == "J7"
    assert d["status"] in STATUS_VALIDOS
