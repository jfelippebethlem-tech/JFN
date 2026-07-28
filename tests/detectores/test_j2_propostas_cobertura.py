# -*- coding: utf-8 -*-
"""Rede de proteção do detector J2 — propostas de cobertura (screens de preço).

A tese: num cartel, os perdedores não competem — cobrem. Suas propostas viram função
quase-linear da do vencedor, e os percentuais de cobertura ficam praticamente constantes. O
screen mede isso pela dispersão ROBUSTA (MAD/mediana), não pelo CV, para que um perdedor
genuinamente discrepante não mascare o padrão dos demais.

A cláusula crítica de honestidade deste detector é rara e merece destaque: **o PNCP só expõe o
vencedor**. Sem a lista de propostas dos perdedores não existe screen, e o detector se recusa a
pontuar conluio — não é zero, é `nao_avaliavel`.

Sem rede, sem banco, sem LLM.
"""
from __future__ import annotations

import pytest

from compliance_agent.detectores.base import ANCORAS, STATUS_VALIDOS
from compliance_agent.detectores.j2_propostas_cobertura import (
    J2PropostasCobertura,
    _disp_robusta,
    _vencedor_e_perdedores,
)

_P = {"processo": "SEI-TESTE/000007/2026"}


def _props(vencedor: float, *perdedores: float) -> list[dict]:
    out = [{"licitante_cnpj": "11222333000144", "valor": vencedor, "classificacao": 1}]
    for i, v in enumerate(perdedores):
        out.append({"licitante_cnpj": f"5566677700{i:04d}", "valor": v})
    return out


# ───────────────────────────── dispersão robusta ──────────────────────────────────────────────

def test_dispersao_zero_quando_todos_iguais():
    assert _disp_robusta([0.10, 0.10, 0.10, 0.10]) == 0.0


def test_dispersao_ignora_um_discrepante():
    """É o motivo de usar MAD/mediana em vez de CV: 3 coberturas coladas e 1 fora do padrão
    continuam sendo padrão. Com CV, o discrepante mascararia o conluio."""
    robusta = _disp_robusta([0.10, 0.10, 0.10, 0.90])
    assert robusta is not None and robusta < 0.05


def test_dispersao_alta_em_competicao_real():
    assert _disp_robusta([0.05, 0.31, 0.62, 0.88]) > 0.05


def test_dispersao_none_com_menos_de_dois_valores():
    assert _disp_robusta([0.10]) is None
    assert _disp_robusta([]) is None


def test_dispersao_none_quando_mediana_zero():
    """Divisão por mediana zero não pode virar infinito nem exceção."""
    assert _disp_robusta([0.0, 0.0, 0.0]) is None


# ───────────────────────────── vencedor e perdedores ──────────────────────────────────────────

def test_classificacao_explicita_define_o_vencedor():
    props = [{"valor": 100.0}, {"valor": 90.0, "classificacao": 1}]
    venc, perd = _vencedor_e_perdedores(props)
    assert venc["_valor"] == 90.0 and len(perd) == 1


@pytest.mark.parametrize("rotulo", ["vencedor", "1º", "primeiro", "homologado", "1o"])
def test_aceita_os_rotulos_de_classificacao_do_dado_real(rotulo):
    props = [{"valor": 200.0, "classificacao": rotulo}, {"valor": 100.0}]
    venc, _ = _vencedor_e_perdedores(props)
    assert venc["_valor"] == 200.0, "o rótulo manda, mesmo não sendo o menor valor"


def test_sem_classificacao_o_menor_valor_e_o_vencedor_presumido():
    venc, perd = _vencedor_e_perdedores([{"valor": 300.0}, {"valor": 100.0}, {"valor": 200.0}])
    assert venc["_valor"] == 100.0 and len(perd) == 2


def test_proposta_sem_valor_numerico_e_ignorada():
    venc, perd = _vencedor_e_perdedores([{"valor": 100.0}, {"valor": None},
                                         {"valor": "cem reais"}, {"valor": True}])
    assert venc["_valor"] == 100.0 and perd == []


def test_lista_vazia_nao_quebra():
    assert _vencedor_e_perdedores([]) == (None, [])


# ───────────────────────────── a cláusula crítica de honestidade ──────────────────────────────

def test_sem_lista_de_propostas_nao_pontua_conluio():
    """O PNCP só dá o vencedor. Pontuar conluio aí seria inventar o dado que falta."""
    res = J2PropostasCobertura().avaliar({**_P, "propostas": _props(100.0)})
    assert res.status == "nao_avaliavel"
    assert res.score == 0.0
    assert "gap_pncp" in res.valores
    assert "NÃO é pontuado sem os dados" in res.motivo_refutacao


def test_duas_propostas_ainda_e_insuficiente():
    res = J2PropostasCobertura().avaliar({**_P, "propostas": _props(100.0, 110.0)})
    assert res.status == "nao_avaliavel"
    assert res.valores["n_propostas_com_valor"] == 2


def test_sem_propostas_e_nao_avaliavel():
    res = J2PropostasCobertura().avaliar({**_P})
    assert res.status == "nao_avaliavel"
    assert res.score == 0.0


# ───────────────────────────── screen de cobertura ────────────────────────────────────────────

def test_percentuais_constantes_com_tres_perdedores_e_forte():
    """Todos os perdedores exatamente 10% acima: é cobertura, não competição."""
    res = J2PropostasCobertura().avaliar({**_P, "propostas": _props(100.0, 110.0, 110.0, 110.0)})
    assert res.score >= ANCORAS["forte"]
    assert res.status == "confirmado"
    assert res.valores["cv_coberturas"] == 0.0
    assert res.evidencia


def test_com_apenas_dois_perdedores_o_teto_e_medio_e_a_ressalva_e_explicita():
    """Dispersão baixa entre 2 pontos é pouco informativa — o detector limita e DIZ que limitou."""
    res = J2PropostasCobertura().avaliar({**_P, "propostas": _props(100.0, 110.0, 110.0)})
    assert res.score == pytest.approx(ANCORAS["medio"])
    assert "ressalva_n_perdedores" in res.valores
    assert "mín. 3" in res.valores["ressalva_n_perdedores"] or "3" in res.valores["ressalva_n_perdedores"]


def test_competicao_real_nao_vira_achado():
    res = J2PropostasCobertura().avaliar({**_P, "propostas": _props(100.0, 105.0, 131.0, 168.0)})
    assert res.score == 0.0
    assert res.status == "descartado"
    assert res.explicacao_inocente


def test_mercado_homogeneo_e_exculpatoria():
    """Poucos players com estrutura de custo idêntica produzem propostas parecidas SEM combinar.

    Sem este guard o detector acusaria mercado concentrado legítimo (combustível, por exemplo).
    """
    res = J2PropostasCobertura().avaliar({**_P, "propostas": _props(100.0, 110.0, 110.0, 110.0),
                                          "mercado_homogeneo": True})
    assert res.score == 0.0


def test_calcula_a_cobertura_media():
    res = J2PropostasCobertura().avaliar({**_P, "propostas": _props(100.0, 110.0, 110.0, 110.0)})
    assert res.valores["cobertura_media"] == pytest.approx(0.10)
    assert res.valores["n_perdedores"] == 3
    assert res.valores["vencedor_valor"] == 100.0


# ───────────────────────────── robustez e schema ──────────────────────────────────────────────

def test_lixo_na_lista_de_propostas_nao_quebra():
    props = _props(100.0, 110.0, 110.0, 110.0) + [None, "texto", 42]
    res = J2PropostasCobertura().avaliar({**_P, "propostas": props})
    assert res.status in STATUS_VALIDOS


def test_schema_de_saida_conforme_spec():
    res = J2PropostasCobertura().avaliar({**_P, "propostas": _props(100.0, 110.0, 110.0, 110.0)})
    d = res.to_dict()
    for campo in ("detector", "processo", "score", "valores", "evidencia",
                  "explicacao_inocente", "refutada", "motivo_refutacao", "status"):
        assert campo in d
    assert d["detector"] == "J2"
    assert 0.0 <= d["score"] <= 1.0
