# -*- coding: utf-8 -*-
"""X10 — "o aditivo é bem feito?" não se responde pelo percentual.

Um acréscimo de 10% pode ser irregular e um de 24% pode ser impecável: o que separa os dois é a
INSTRUÇÃO — o que os autos trazem para justificar a alteração. É o que um analista de Tribunal de
Contas confere primeiro, e o que o motor não olhava.

A linha que este card não cruza, e é o teste mais importante do arquivo: **documento ausente na
CAPTURA não é documento ausente nos AUTOS**. Foi a lição de 59% das 9.863 red flags do sweep SEI,
que eram queixa de captura e não vício. Daí os três estados por item, e só `ausente_declarado`
pontuar.
"""
from __future__ import annotations

import pytest

from compliance_agent.detectores import REGISTRO
from compliance_agent.detectores.x10_aditivo_desinstruido import ITENS

X10 = REGISTRO["X10"]

_COMPLETO = {k: "presente" for k in ITENS}


def _ctx(instrucao=None, **kw):
    base = {"processo": "P-1", "instrucao": instrucao if instrucao is not None else dict(_COMPLETO)}
    base.update(kw)
    return base


# ───────────────────────── captura ≠ ausência ─────────────────────────────────────────────────

def test_sem_checklist_e_nao_avaliavel():
    r = X10.avaliar({"processo": "P-1"})
    assert r.status == "nao_avaliavel" and "campo ausente ≠ instrução ausente" in r.motivo_refutacao


def test_nada_capturado_NAO_vira_nota_zero():
    """O erro que este card existe para não cometer."""
    r = X10.avaliar(_ctx({k: "nao_capturado" for k in ITENS}))
    assert r.status == "nao_avaliavel"
    assert "CAPTURA não é documento ausente nos AUTOS" in r.motivo_refutacao


def test_item_omitido_do_dict_e_tratado_como_nao_capturado():
    r = X10.avaliar(_ctx({"parecer_juridico": "presente"}))
    assert r.valores["nao_capturados"]
    assert "justificativa_tecnica" in r.valores["nao_capturados"]


def test_estado_invalido_vira_nao_capturado_nao_falta():
    r = X10.avaliar(_ctx({**_COMPLETO, "parecer_juridico": "sei_la"}))
    assert "parecer_juridico" in r.valores["nao_capturados"]


def test_nota_normaliza_sobre_o_APURAVEL():
    """4 itens lidos, 2 presentes → a nota é sobre o peso desses 4, não sobre os 7."""
    r = X10.avaliar(_ctx({"parecer_juridico": "presente", "justificativa_tecnica": "presente",
                          "dotacao_orcamentaria": "ausente_declarado",
                          "pesquisa_precos": "ausente_declarado"}))
    assert r.valores["peso_apuravel"] == 11 and r.valores["peso_atendido"] == 6


# ───────────────────────── o checklist ────────────────────────────────────────────────────────

def test_instrucao_completa_e_descartada():
    r = X10.avaliar(_ctx())
    assert r.status == "descartado" and r.score == 0.0
    assert "instrução completa" in r.motivo_refutacao


def test_falta_de_parecer_juridico_confirma():
    r = X10.avaliar(_ctx({**_COMPLETO, "parecer_juridico": "ausente_declarado"}))
    assert r.status == "confirmado"
    assert any("parecer jurídico" in e["trecho"] for e in r.evidencia)
    assert any("art. 53" in e["trecho"] for e in r.evidencia)


def test_condicao_de_VALIDADE_nunca_sai_como_achado_fraco():
    """Nota alta não pode transformar falta de dotação em ruído."""
    r = X10.avaliar(_ctx({**_COMPLETO, "dotacao_orcamentaria": "ausente_declarado"}))
    assert r.score >= 0.6, f"score {r.score} baixo demais para falta de condição de validade"


def test_falta_so_da_publicacao_e_menos_grave():
    """Publicação é condição de EFICÁCIA, não de validade."""
    so_extrato = X10.avaliar(_ctx({**_COMPLETO, "publicacao_extrato": "ausente_declarado"}))
    so_parecer = X10.avaliar(_ctx({**_COMPLETO, "parecer_juridico": "ausente_declarado"}))
    assert so_extrato.score < so_parecer.score


def test_instrucao_quase_toda_ausente_e_critica():
    r = X10.avaliar(_ctx({k: "ausente_declarado" for k in ITENS}))
    assert r.score == pytest.approx(1.0)


def test_o_desconto_preservado_esta_no_checklist():
    """O item que quase nunca é conferido e o que mais protege o erário."""
    assert "desconto_preservado" in ITENS
    r = X10.avaliar(_ctx({**_COMPLETO, "desconto_preservado": "ausente_declarado"}))
    assert any("desconto da proposta" in e["trecho"] for e in r.evidencia)


def test_anuencia_sai_da_conta_quando_nao_e_exigida():
    r = X10.avaliar(_ctx({**_COMPLETO, "anuencia_contratado": "ausente_declarado"},
                         exige_anuencia=False))
    assert r.status == "descartado", "anuência não exigida foi cobrada mesmo assim"


# ───────────────────────── cobertura e saída ──────────────────────────────────────────────────

def test_cobertura_parcial_e_declarada_no_achado():
    r = X10.avaliar(_ctx({"parecer_juridico": "ausente_declarado",
                          "justificativa_tecnica": "presente"}))
    assert any("COBERTURA" in e["trecho"] for e in r.evidencia)
    assert "pode alterá-la nos dois sentidos" in " ".join(e["trecho"] for e in r.evidencia)


def test_citacao_por_documento_e_folha_quando_ha():
    r = X10.avaliar(_ctx({**_COMPLETO, "parecer_juridico": "ausente_declarado"},
                         evidencias_instrucao={"parecer_juridico": {"doc": "SEI 123", "folha": "7"}}))
    assert "fl. 7" in " ".join(e["trecho"] for e in r.evidencia)


def test_explicacao_inocente_reconhece_instrucao_dispersa():
    r = X10.avaliar(_ctx({**_COMPLETO, "pesquisa_precos": "ausente_declarado"}))
    assert "parecer referencial" in r.explicacao_inocente
    assert "íntegra do processo" in r.explicacao_inocente


def test_todo_item_do_checklist_cita_fundamento():
    for item, meta in ITENS.items():
        assert meta["fundamento"], f"{item} sem fundamento"
        assert meta["gravidade"] in {"validade", "eficacia", "protecao_erario"}
