# -*- coding: utf-8 -*-
"""Prazo além de qualquer hipótese legal não é violação maior — é DADO ERRADO.

Sequência real de 2026-08-04, e ela vale como método: liguei a vigência do contrato registrado no
TCE-RJ ao caminho do SEI, e o X2 — que nunca conseguira avaliar nada — produziu o **primeiro
achado novo da sessão**, levando um processo a EXTREMO com "tempo total no objeto = 23,01 anos".

Antes de comemorar, fui aos autos: SEI-260007/009935/2024 é a **"AQUISIÇÃO DO MEDICAMENTO
CIPROFLOXACINO" por R$ 58.608,00**, uma compra pontual. Vigência de 23 anos para isso é
impossível — o `vig_inicio` de 08/06/2002 é erro no registro da fonte.

O fio que eu acabara de ligar teria produzido um EXTREMO falso. A cura é a mesma do X9 ("não se
suprime mais do que existe"): acima do plausível, o detector diz o que não fecha em vez de
acusar.
"""
from compliance_agent.detectores.x2_prorrogacao_perpetua import X2ProrrogacaoPerpetua


def _avaliar(**ctx):
    return X2ProrrogacaoPerpetua().avaliar({"processo": "SEI-000000/000001/2024", **ctx})


def test_vigencia_de_23_anos_e_erro_de_data_nao_achado():
    r = _avaliar(vigencia_inicio="2002-06-08", vigencia_fim_atual="2025-06-11")
    assert r.status == "nao_avaliavel"
    assert r.score == 0.0
    assert r.valores.get("prazo_implausivel") is True
    assert "23.0 anos" in r.motivo_refutacao and "DATA" in r.motivo_refutacao


def test_prazo_longo_mas_POSSIVEL_continua_sendo_achado():
    """12 anos cabe na hipótese excepcional e é exatamente o que o detector existe para pegar."""
    r = _avaliar(vigencia_inicio="2013-01-01", vigencia_fim_atual="2025-01-01")
    assert r.status == "confirmado" and r.score >= 0.9


def test_prazo_dentro_do_teto_nao_acusa():
    r = _avaliar(vigencia_inicio="2022-01-01", vigencia_fim_atual="2025-01-01")
    assert r.status != "confirmado" or r.score < 0.85


def test_sem_vigencia_segue_nao_avaliavel():
    """Campo ausente ≠ 0 — o detector nunca inventa prazo."""
    r = _avaliar()
    assert r.status == "nao_avaliavel"
    assert "prazo_implausivel" not in r.valores
