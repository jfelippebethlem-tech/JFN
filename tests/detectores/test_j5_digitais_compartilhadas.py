# -*- coding: utf-8 -*-
"""Rede de proteção do detector J5 — digitais compartilhadas entre propostas.

Cruza metadados de arquivo, contatos profissionais, hashes de componentes embutidos, IP e
horário de envio entre licitantes DISTINTOS. Duas empresas concorrentes não produzem documentos
com o mesmo autor, nem enviam do mesmo IP, por acaso.

Dois guards essenciais:
· valor **genérico** (Microsoft Word, Adobe, "usuário") não é digital — é template universal;
· comparação só entre licitantes DIFERENTES: dois arquivos da mesma empresa compartilham tudo,
  e isso não é coincidência nenhuma.

Sem rede, sem banco.
"""
from __future__ import annotations

import pytest

from compliance_agent.detectores.base import ANCORAS, STATUS_VALIDOS
from compliance_agent.detectores.j5_digitais_compartilhadas import (
    J5DigitaisCompartilhadas,
    _eh_generico,
)

_P = {"processo": "SEI-TESTE/000021/2026"}


def _prop(cnpj: str, **campos) -> dict:
    return {"licitante_cnpj": cnpj, **campos}


# ───────────────────────────── genérico não é digital ─────────────────────────────────────────

@pytest.mark.parametrize("valor", ["microsoft word", "adobe acrobat", "usuario", ""])
def test_valor_generico_nao_conta_como_digital(valor):
    """Metade do país gera PDF pelo Word. Isso não liga duas empresas."""
    assert _eh_generico(valor) is True


def test_nome_proprio_nao_e_generico():
    assert _eh_generico("joao.silva") is False


# ───────────────────────────── invariante de honestidade ──────────────────────────────────────

def test_menos_de_duas_propostas_com_dado_e_nao_avaliavel():
    res = J5DigitaisCompartilhadas().avaliar({
        **_P, "propostas": [_prop("11222333000144", metadados={"author": "joao"})]})
    assert res.status == "nao_avaliavel"
    assert res.score == 0.0
    assert "campo ausente ≠ 0" in res.motivo_refutacao


def test_propostas_sem_metadado_algum_sao_nao_avaliaveis_e_o_motivo_orienta():
    """O motivo diz o que coletar — impressão e re-digitalização destroem os metadados."""
    res = J5DigitaisCompartilhadas().avaliar({
        **_P, "propostas": [_prop("11222333000144"), _prop("44555666000177")]})
    assert res.status == "nao_avaliavel"
    assert "exiftool" in res.motivo_refutacao


def test_propostas_independentes_nao_pontuam():
    props = [_prop("11222333000144", metadados={"author": "joao.silva"}, ip_envio="200.1.1.1"),
             _prop("44555666000177", metadados={"author": "maria.souza"}, ip_envio="200.2.2.2")]
    res = J5DigitaisCompartilhadas().avaliar({**_P, "propostas": props})
    assert res.score == 0.0
    assert res.status == "descartado"


# ───────────────────────────── as cinco digitais ──────────────────────────────────────────────

def test_autor_identico_entre_concorrentes_e_forte():
    props = [_prop("11222333000144", metadados={"author": "joao.silva"}),
             _prop("44555666000177", metadados={"author": "joao.silva"})]
    res = J5DigitaisCompartilhadas().avaliar({**_P, "propostas": props})
    assert res.score >= ANCORAS["forte"]
    assert res.evidencia


def test_autor_generico_identico_nao_pontua():
    props = [_prop("11222333000144", metadados={"author": "Microsoft Word"}),
             _prop("44555666000177", metadados={"author": "Microsoft Word"})]
    res = J5DigitaisCompartilhadas().avaliar({**_P, "propostas": props})
    assert res.score == 0.0


@pytest.mark.parametrize("campo", ["contador_crc", "advogado_oab", "telefone", "email"])
def test_contato_profissional_compartilhado_e_forte(campo):
    props = [_prop("11222333000144", contatos={campo: "XYZ-123"}),
             _prop("44555666000177", contatos={campo: "XYZ-123"})]
    res = J5DigitaisCompartilhadas().avaliar({**_P, "propostas": props})
    assert res.score >= ANCORAS["forte"]


def test_hash_de_componente_embutido_identico_e_forte():
    """Mesma imagem de logotipo embutida em propostas de empresas diferentes."""
    props = [_prop("11222333000144", hashes_embutidos=["abc123def456"]),
             _prop("44555666000177", hashes_embutidos=["abc123def456"])]
    res = J5DigitaisCompartilhadas().avaliar({**_P, "propostas": props})
    assert res.score >= ANCORAS["forte"]


def test_mesmo_ip_de_envio_e_critico():
    """Duas propostas concorrentes saindo da mesma máquina é o sinal mais forte do detector."""
    props = [_prop("11222333000144", ip_envio="200.1.1.1"),
             _prop("44555666000177", ip_envio="200.1.1.1")]
    res = J5DigitaisCompartilhadas().avaliar({**_P, "propostas": props})
    assert res.score >= ANCORAS["critico"] or res.score == pytest.approx(1.0)


def test_mesmo_horario_de_envio_e_forte():
    props = [_prop("11222333000144", horario_envio="2026-03-10T14:32:07"),
             _prop("44555666000177", horario_envio="2026-03-10T14:32:07")]
    res = J5DigitaisCompartilhadas().avaliar({**_P, "propostas": props})
    assert res.score >= ANCORAS["forte"]


# ───────────────────────────── o guard do mesmo licitante ─────────────────────────────────────

def test_dois_arquivos_do_mesmo_licitante_nao_sao_coincidencia():
    """A empresa usa o mesmo computador nos próprios documentos. Isso é o esperado, não indício."""
    props = [_prop("11222333000144", metadados={"author": "joao.silva"}, ip_envio="200.1.1.1"),
             _prop("11222333000144", metadados={"author": "joao.silva"}, ip_envio="200.1.1.1")]
    res = J5DigitaisCompartilhadas().avaliar({**_P, "propostas": props})
    assert res.score == 0.0


def test_schema_de_saida_conforme_spec():
    props = [_prop("11222333000144", ip_envio="200.1.1.1"),
             _prop("44555666000177", ip_envio="200.1.1.1")]
    d = J5DigitaisCompartilhadas().avaliar({**_P, "propostas": props}).to_dict()
    for campo in ("detector", "processo", "score", "valores", "evidencia",
                  "explicacao_inocente", "refutada", "motivo_refutacao", "status"):
        assert campo in d
    assert d["detector"] == "J5"
    assert d["status"] in STATUS_VALIDOS
