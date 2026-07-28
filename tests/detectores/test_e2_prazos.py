# -*- coding: utf-8 -*-
"""Rede de proteção do detector E2 — publicidade e prazos minimizados (art. 54/55 Lei 14.133/2021).

Primeiro dos 10 detectores que rodavam sem NENHUM teste. Serve de gabarito para os demais: cobre
as cinco famílias obrigatórias — régua objetiva, invariante de honestidade (INDISPONÍVEL ≠ 0),
caso conforme, guard anti-falso-positivo e conformidade com o schema §1.4.

Sem rede, sem banco: o detector é puro sobre `contexto`.
"""
from __future__ import annotations

from datetime import date

import pytest

from compliance_agent.detectores.base import ANCORAS, STATUS_VALIDOS
from compliance_agent.detectores.e2_prazos import (
    E2Prazos,
    _is_data_sombra,
    dias_uteis,
    minimo_art55,
)

_BASE = {"processo": "SEI-TESTE/000001/2026", "modalidade": "pregao",
         "criterio": "menor_preco", "feriados": []}


# ───────────────────────────── régua objetiva: mínimos do art. 55 ─────────────────────────────

@pytest.mark.parametrize("modalidade,criterio,esperado", [
    ("pregao", "menor_preco", 8),
    ("pregao", None, 8),
    ("concorrencia", "menor_preco", 8),
    ("concorrencia", "tecnica_e_preco", 15),
    ("concorrencia", "obras_servicos_engenharia", 10),
    ("concorrencia", "obras_servicos_engenharia_especiais", 25),
    ("concurso", None, 35),
    ("leilao", None, 15),
    ("dialogo_competitivo", None, 25),
])
def test_minimo_do_art55_por_modalidade_e_criterio(modalidade, criterio, esperado):
    assert minimo_art55(modalidade, criterio) == esperado


@pytest.mark.parametrize("grafia", ["pregão", "PREGÃO", " Pregao ", "Pregao"])
def test_modalidade_normaliza_acento_caixa_e_espaco(grafia):
    """O dado vem do PNCP e do edital com grafia livre — a régua não pode depender disso."""
    assert minimo_art55(grafia, "menor_preco") == 8


def test_criterio_desconhecido_cai_no_default_da_modalidade():
    assert minimo_art55("concorrencia", "criterio_que_nao_existe") == 8


def test_modalidade_desconhecida_devolve_none_em_vez_de_chutar():
    """Não inventamos o piso legal: modalidade fora da tabela vira nao_avaliavel no detector."""
    assert minimo_art55("modalidade_inexistente") is None
    assert minimo_art55(None) is None


# ───────────────────────────── régua objetiva: contagem em dias úteis ─────────────────────────

def test_conta_dias_uteis_pulando_fim_de_semana():
    """Contagem EXCLUSIVA na publicação e INCLUSIVA na abertura (é assim que o código conta).

    01/07/2026 é quarta; 08/07 é a quarta seguinte. Contam qui, sex, seg, ter, qua = 5.
    """
    assert dias_uteis(date(2026, 7, 1), date(2026, 7, 8), set()) == 5


def test_feriado_encurta_o_prazo_util():
    assert dias_uteis(date(2026, 7, 1), date(2026, 7, 8), {date(2026, 7, 3)}) == 4


def test_feriado_em_fim_de_semana_nao_desconta_duas_vezes():
    """04/07/2026 é sábado: já não contava. Informá-lo como feriado não pode mudar nada."""
    assert dias_uteis(date(2026, 7, 1), date(2026, 7, 8), {date(2026, 7, 4)}) == 5


def test_intervalo_nulo_ou_invertido_e_zero():
    assert dias_uteis(date(2026, 7, 8), date(2026, 7, 8), set()) == 0
    assert dias_uteis(date(2026, 7, 8), date(2026, 7, 1), set()) == 0


# ───────────────────────────── régua objetiva: data-sombra ────────────────────────────────────

def test_vespera_de_feriado_e_data_sombra():
    from datetime import datetime
    sombra, motivo = _is_data_sombra(datetime(2026, 7, 2, 10, 0), {date(2026, 7, 3)})
    assert sombra and "feriado" in motivo


def test_sexta_apos_16h_e_data_sombra():
    from datetime import datetime
    sombra, motivo = _is_data_sombra(datetime(2026, 7, 3, 17, 30), set())
    assert sombra and "sexta" in motivo


def test_sexta_sem_hora_nao_marca_sombra_sozinha():
    """Guard anti-falso-positivo: hora 00:00 quase sempre significa 'hora não informada'.

    Tratar isso como publicação noturna de sexta acusaria metade dos editais sem base.
    """
    from datetime import datetime
    sombra, _ = _is_data_sombra(datetime(2026, 7, 3, 0, 0), set())
    assert sombra is False


# ───────────────────────────── invariante de honestidade ──────────────────────────────────────

@pytest.mark.parametrize("faltando", ["data_publicacao", "data_abertura", "modalidade"])
def test_campo_ausente_devolve_nao_avaliavel_e_nao_zero(faltando):
    """Invariante absoluto do projeto: INDISPONÍVEL ≠ 0. Sem dado não há juízo."""
    ctx = {**_BASE, "data_publicacao": "2026-07-01", "data_abertura": "2026-07-10"}
    ctx.pop(faltando)
    res = E2Prazos().avaliar(ctx)
    assert res.status == "nao_avaliavel"
    assert res.score == 0.0
    assert res.motivo_refutacao, "tem de dizer POR QUE não avaliou"


def test_modalidade_fora_da_tabela_nao_inventa_piso():
    res = E2Prazos().avaliar({**_BASE, "modalidade": "carta_convite_extinta",
                              "data_publicacao": "2026-07-01", "data_abertura": "2026-07-03"})
    assert res.status == "nao_avaliavel"
    assert "não inventamos" in res.motivo_refutacao


# ───────────────────────────── caso violado e caso conforme ───────────────────────────────────

def test_prazo_abaixo_do_minimo_pontua_forte():
    res = E2Prazos().avaliar({**_BASE, "data_publicacao": "2026-07-01",
                              "data_abertura": "2026-07-03"})
    assert res.score >= ANCORAS["forte"]
    assert res.valores["prazo_util_dias"] == 2
    assert res.valores["minimo_art55_dias"] == 8
    assert res.evidencia, "violação objetiva tem de vir com evidência citável"


def test_prazo_no_piso_legal_e_apenas_agravante():
    """Piso é LÍCITO. Marcar como violação seria acusar quem cumpriu a lei."""
    res = E2Prazos().avaliar({**_BASE, "data_publicacao": "2026-07-01",
                              "data_abertura": "2026-07-13"})
    assert res.valores["prazo_util_dias"] == res.valores["minimo_art55_dias"] == 8
    assert res.score == pytest.approx(ANCORAS["fraco"])


def test_prazo_folgado_nao_inventa_indicio():
    res = E2Prazos().avaliar({**_BASE, "data_publicacao": "2026-07-01",
                              "data_abertura": "2026-08-15"})
    assert res.score == 0.0


# ───────────────────────────── dado sujo ──────────────────────────────────────────────────────

def test_abertura_antes_da_publicacao_e_dado_sujo_nao_violacao():
    """Guard: inconsistência de dado não pode virar o achado mais grave do parecer."""
    res = E2Prazos().avaliar({**_BASE, "data_publicacao": "2026-07-10",
                              "data_abertura": "2026-07-01"})
    assert res.status == "nao_avaliavel"
    assert res.score == 0.0
    assert "dado sujo" in res.motivo_refutacao


# ───────────────────────────── agravantes ─────────────────────────────────────────────────────

def test_data_sombra_agrava_mas_nao_cria_achado_sozinha():
    """+0,10 só incide quando JÁ há pontuação — sombra isolada não é irregularidade."""
    folgado_sombra = E2Prazos().avaliar({**_BASE, "data_publicacao": "2026-07-03T17:00",
                                         "data_abertura": "2026-08-15"})
    assert folgado_sombra.score == 0.0

    curto = E2Prazos().avaliar({**_BASE, "data_publicacao": "2026-07-01",
                                "data_abertura": "2026-07-03"})
    curto_sombra = E2Prazos().avaliar({**_BASE, "data_publicacao": "2026-07-01T09:00",
                                       "data_abertura": "2026-07-03T17:00"})
    assert curto_sombra.score > curto.score


def test_ausencia_no_pncp_so_pontua_quando_informada_como_false():
    """`None`/ausente ≠ False. Não saber se está no PNCP não é prova de que não está."""
    sem_info = E2Prazos().avaliar({**_BASE, "data_publicacao": "2026-07-01",
                                   "data_abertura": "2026-08-15"})
    assert sem_info.score == 0.0

    fora = E2Prazos().avaliar({**_BASE, "data_publicacao": "2026-07-01",
                               "data_abertura": "2026-08-15", "no_pncp": False})
    assert fora.score >= ANCORAS["forte"]


# ───────────────────────────── schema §1.4 ────────────────────────────────────────────────────

def test_schema_de_saida_conforme_spec():
    res = E2Prazos().avaliar({**_BASE, "data_publicacao": "2026-07-01",
                              "data_abertura": "2026-07-03"})
    d = res.to_dict()
    for campo in ("detector", "processo", "score", "valores", "evidencia",
                  "explicacao_inocente", "refutada", "motivo_refutacao", "status"):
        assert campo in d, f"schema §1.4 exige {campo}"
    assert d["detector"] == "E2"
    assert d["status"] in STATUS_VALIDOS
    assert 0.0 <= d["score"] <= 1.0


# ───────────────────────────── regressão: parse de data com hora ──────────────────────────────

@pytest.mark.parametrize("valor,hora_esperada", [
    ("2026-07-03T17:00", 17),      # ISO sem segundos — é como o PNCP entrega
    ("2026-07-03T17:00:00", 17),
    ("2026-07-03 17:00", 17),
    ("2026-07-03 17:00:00", 17),
    ("03/07/2026 17:00", 17),      # grafia BR
    ("2026-07-03", 0),             # só data: 00:00 é legítimo aqui
])
def test_parse_de_data_preserva_a_hora(valor, hora_esperada):
    """A hora era DESCARTADA em silêncio no formato ISO sem segundos.

    `_to_datetime` trunca a string pelo tamanho do formato; sem `%Y-%m-%dT%H:%M` na lista,
    "2026-07-03T17:00" casava com "%Y-%m-%d" e virava 00:00. Como a regra de data-sombra depende
    da hora, ela NUNCA disparava para data em ISO — falso negativo calado.
    """
    from compliance_agent.detectores.e2_prazos import _to_datetime
    dt = _to_datetime(valor)
    assert dt is not None and dt.hour == hora_esperada


def test_sombra_dispara_com_data_iso_apos_o_conserto():
    from datetime import datetime
    from compliance_agent.detectores.e2_prazos import _to_datetime
    sombra, motivo = _is_data_sombra(_to_datetime("2026-07-03T17:00"), set())
    assert sombra and "sexta" in motivo
    assert _to_datetime("2026-07-03T17:00") == datetime(2026, 7, 3, 17, 0)
