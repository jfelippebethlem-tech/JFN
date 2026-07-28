# -*- coding: utf-8 -*-
"""Rede de proteção do detector P6 — contratação direta acima do teto (art. 75 I-II).

Fecha o ramo OBJETIVO do vício: dispensa por VALOR acima do limite do exercício. O teto vem da
fonte única `limites_dispensa` — este detector é o modelo de como se usa (o projeto já teve 5
cópias divergentes do mesmo número, duas delas congeladas em 2024).

Guards que os testes trancam: inexigibilidade não tem teto (art. 74 é outro instituto), amparo
declarado em outro inciso afasta o teste de valor, e o intervalo entre o teto de compras e o de
obras vira 'medio' com a dúvida declarada — não 'crítico' — porque o objeto pode ser engenharia.
"""
from __future__ import annotations

import pytest

from compliance_agent.detectores.base import ANCORAS, STATUS_VALIDOS
from compliance_agent.detectores.p6_direta_indevida import (
    MODALIDADE_DISPENSA,
    MODALIDADE_INEXIGIBILIDADE,
    P6DiretaIndevida,
)
from compliance_agent.limites_dispensa import limite_dispensa

_P = {"processo": "SEI-TESTE/000010/2026", "modalidade_id": MODALIDADE_DISPENSA}


def test_inexigibilidade_nao_tem_teto_de_valor():
    """Art. 74 é inviabilidade de competição, não faixa de valor. Aplicar teto aqui seria erro de direito."""
    res = P6DiretaIndevida().avaliar({**_P, "modalidade_id": MODALIDADE_INEXIGIBILIDADE,
                                      "valor_total": 10_000_000.0, "ano": 2026})
    assert res.status == "nao_avaliavel"
    assert res.score == 0.0
    assert "art. 74" in res.motivo_refutacao


def test_modalidade_competitiva_nao_e_contratacao_direta():
    res = P6DiretaIndevida().avaliar({**_P, "modalidade_id": 6, "valor_total": 999_999.0, "ano": 2026})
    assert res.status == "nao_avaliavel"


@pytest.mark.parametrize("falta", ["valor_total", "ano"])
def test_sem_valor_ou_ano_e_nao_avaliavel(falta):
    ctx = {**_P, "valor_total": 100_000.0, "ano": 2026}
    ctx.pop(falta)
    res = P6DiretaIndevida().avaliar(ctx)
    assert res.status == "nao_avaliavel"
    assert "INDISPONÍVEL ≠ 0" in res.motivo_refutacao


@pytest.mark.parametrize("amparo", ["art. 75 III", "inciso VIII", "art. 75, IV"])
def test_amparo_em_outro_inciso_afasta_o_teste_de_teto(amparo):
    """Emergência (VIII) e deserto (III) não são dispensa POR VALOR — o teto não os alcança."""
    res = P6DiretaIndevida().avaliar({**_P, "valor_total": 10_000_000.0, "ano": 2026,
                                      "amparo_declarado": amparo})
    assert res.status == "descartado"
    assert res.score == 0.0


def test_valor_dentro_do_teto_do_exercicio_e_descartado():
    teto = limite_dispensa(2026, "compras")
    res = P6DiretaIndevida().avaliar({**_P, "valor_total": teto - 1, "ano": 2026})
    assert res.status == "descartado"
    assert res.score == 0.0


def test_teto_e_do_exercicio_nao_um_valor_fixo():
    """59.906,02 vale só para 2024. Em 2026 o teto é 65.492,11 — usar o fixo daria falso positivo."""
    valor = 63_000.0
    assert P6DiretaIndevida().avaliar({**_P, "valor_total": valor, "ano": 2024}).status == "confirmado"
    assert P6DiretaIndevida().avaliar({**_P, "valor_total": valor, "ano": 2026}).status == "descartado"


def test_acima_do_teto_de_obras_e_critico():
    res = P6DiretaIndevida().avaliar({**_P, "valor_total": limite_dispensa(2026, "obras") + 1,
                                      "ano": 2026})
    assert res.score >= ANCORAS["critico"] or res.score == pytest.approx(1.0)
    assert res.valores["teste_objetivo"] == "violado"
    assert res.evidencia


def test_entre_os_dois_tetos_e_medio_com_a_duvida_declarada():
    """Pode ser engenharia, que tem teto maior. O detector diz isso em vez de concluir."""
    meio = (limite_dispensa(2026, "compras") + limite_dispensa(2026, "obras")) / 2
    res = P6DiretaIndevida().avaliar({**_P, "valor_total": meio, "ano": 2026})
    assert res.score == pytest.approx(ANCORAS["medio"])
    assert res.valores["teste_objetivo"] == "nao_aferivel"
    assert "engenharia" in res.evidencia[0]


def test_objeto_de_obra_usa_o_teto_maior():
    meio = (limite_dispensa(2026, "compras") + limite_dispensa(2026, "obras")) / 2
    res = P6DiretaIndevida().avaliar({**_P, "valor_total": meio, "ano": 2026,
                                      "tipo_objeto": "obras"})
    assert res.status == "descartado"


def test_valores_citam_o_ato_normativo():
    """Peça de controle externo precisa citar o decreto que fixa o teto."""
    res = P6DiretaIndevida().avaliar({**_P, "valor_total": 1_000_000.0, "ano": 2026})
    assert res.valores["ato"]
    assert "Decreto" in res.valores["ato"] or "Lei" in res.valores["ato"]


def test_schema_de_saida_conforme_spec():
    d = P6DiretaIndevida().avaliar({**_P, "valor_total": 1_000_000.0, "ano": 2026}).to_dict()
    for campo in ("detector", "processo", "score", "valores", "evidencia",
                  "explicacao_inocente", "refutada", "motivo_refutacao", "status"):
        assert campo in d
    assert d["detector"] == "P6"
    assert d["status"] in STATUS_VALIDOS
