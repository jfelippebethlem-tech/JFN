# -*- coding: utf-8 -*-
"""Teste TARGETED dos detectores da FASE DE JULGAMENTO / conluio: J2 (propostas de cobertura), J3 (desconto
anômalo/irrisório recorrente), J4 (supressão de propostas/licitante único) — spec V2 do dono.

Estratégia (leve, VM 2 vCPU/sem swap): fixtures de CONTEXTO (dicts), LLM ausente OU rubrica pré-classificada
injetada (sem rede). Para cada detector: (a) caso que CONFIRMA, (b) caso exculpatório/descartado, (c) SEM dados
de proposta → nao_avaliavel (o caso MAIS importante — honestidade do gap PNCP: só o vencedor é exposto).
Rodar só este arquivo:  .venv/bin/python -m pytest tests/test_detectores_julgamento.py -q
"""
from __future__ import annotations

from compliance_agent.detectores import (
    ANCORAS,
    REGISTRO,
    J2PropostasCobertura,
    J3DescontoAnomalo,
    J4SupressaoPropostas,
    ResultadoDetector,
    rodar_julgamento,
    score_processo,
)
from compliance_agent.detectores.base import STATUS_VALIDOS


def _valido(r: ResultadoDetector) -> None:
    """Invariantes do schema §1.4."""
    assert isinstance(r, ResultadoDetector)
    assert r.status in STATUS_VALIDOS
    assert 0.0 <= r.score <= 1.0
    assert isinstance(r.evidencia, list)
    d = r.to_dict()
    assert set(d) == {"detector", "processo", "score", "valores", "evidencia",
                      "explicacao_inocente", "refutada", "motivo_refutacao", "status"}


# ═══════════════════════════════ J2 — propostas de cobertura ═══════════════════════════════
def test_j2_confirma_coberturas_constantes():
    """Perdedores a percentuais ~constantes acima do vencedor (CV das coberturas baixíssimo) → forte."""
    ctx = {
        "processo": "julg-1",
        "propostas": [
            {"licitante_cnpj": "11111111000100", "valor": 100.0, "classificacao": 1},
            {"licitante_cnpj": "22222222000100", "valor": 115.0, "classificacao": 2},
            {"licitante_cnpj": "33333333000100", "valor": 115.5, "classificacao": 3},
            {"licitante_cnpj": "44444444000100", "valor": 116.0, "classificacao": 4},
        ],
    }
    r = J2PropostasCobertura().avaliar(ctx)
    _valido(r)
    assert r.status == "confirmado"
    assert r.score >= ANCORAS["forte"]
    assert r.valores["cv_coberturas"] is not None and r.valores["cv_coberturas"] < 0.05
    assert r.evidencia


def test_j2_recorrencia_pares_eleva_para_critico():
    """Cobertura constante no certame + mesmos pares vencedor↔perdedor recorrentes na série → crítico."""
    serie = [
        {"propostas": [{"licitante_cnpj": "11111111000100", "valor": 90.0, "classificacao": 1},
                       {"licitante_cnpj": "22222222000100", "valor": 104.0, "classificacao": 2}]},
        {"propostas": [{"licitante_cnpj": "11111111000100", "valor": 95.0, "classificacao": 1},
                       {"licitante_cnpj": "22222222000100", "valor": 109.0, "classificacao": 2}]},
    ]
    ctx = {
        "processo": "julg-2",
        "propostas": [
            {"licitante_cnpj": "11111111000100", "valor": 100.0, "classificacao": 1},
            {"licitante_cnpj": "22222222000100", "valor": 115.0, "classificacao": 2},
            {"licitante_cnpj": "33333333000100", "valor": 115.4, "classificacao": 3},
        ],
        "certames_relacionados": serie,
    }
    r = J2PropostasCobertura().avaliar(ctx)
    _valido(r)
    assert r.status == "confirmado"
    assert r.score == ANCORAS["critico"]
    assert r.valores["recorrencia_pares"]["n_pares_recorrentes"] >= 1


def test_j2_exculpatorio_mercado_homogeneo_descartado():
    """CV das coberturas baixo MAS mercado homogêneo (poucos players/custos similares) → não pontua → descartado."""
    ctx = {
        "processo": "julg-3",
        "propostas": [
            {"licitante_cnpj": "1", "valor": 100.0, "classificacao": 1},
            {"licitante_cnpj": "2", "valor": 115.0, "classificacao": 2},
            {"licitante_cnpj": "3", "valor": 115.3, "classificacao": 3},
        ],
        "mercado_homogeneo": True,
    }
    r = J2PropostasCobertura().avaliar(ctx)
    _valido(r)
    assert r.status == "descartado"
    assert r.score == 0.0


def test_j2_descartado_dispersao_competitiva():
    """Coberturas dispersas (competição real) → descartado."""
    ctx = {
        "processo": "julg-4",
        "propostas": [
            {"licitante_cnpj": "1", "valor": 100.0, "classificacao": 1},
            {"licitante_cnpj": "2", "valor": 118.0, "classificacao": 2},
            {"licitante_cnpj": "3", "valor": 145.0, "classificacao": 3},
        ],
    }
    r = J2PropostasCobertura().avaliar(ctx)
    _valido(r)
    assert r.status == "descartado"
    assert r.score == 0.0


def test_j2_nao_avaliavel_sem_lista_de_propostas():
    """CASO MAIS IMPORTANTE (gap PNCP): só o vencedor exposto, sem a lista de perdedores → nao_avaliavel."""
    ctx = {
        "processo": "julg-5",
        "propostas": [{"licitante_cnpj": "11111111000100", "valor": 100.0, "classificacao": 1}],
        "valor_estimado": 120.0,
    }
    r = J2PropostasCobertura().avaliar(ctx)
    _valido(r)
    assert r.status == "nao_avaliavel"
    assert r.score == 0.0
    assert "PNCP" in r.motivo_refutacao
    assert r.valores["gap_pncp"]


def test_j2_nao_avaliavel_sem_propostas():
    r = J2PropostasCobertura().avaliar({"processo": "julg-5b"})
    _valido(r)
    assert r.status == "nao_avaliavel"


# ═══════════════════════════════ J3 — desconto anômalo ═══════════════════════════════
def test_j3_confirma_desconto_irrisorio():
    """Desconto < 2% (rente ao teto) → medio."""
    ctx = {"processo": "julg-6", "valor_estimado": 1000.0, "valor_homologado": 990.0}  # 1% desconto
    r = J3DescontoAnomalo().avaliar(ctx)
    _valido(r)
    assert r.status == "confirmado"
    assert r.score >= ANCORAS["medio"]
    assert r.valores["desconto_pct"] == 1.0


def test_j3_confirma_recorrencia_serie():
    """Desconto irrisório recorrente em série ≥ 12 certames → forte."""
    serie = [{"valor_estimado": 100.0, "valor_homologado": 99.0} for _ in range(12)]  # todos ~1%
    ctx = {"processo": "julg-7", "valor_estimado": 1000.0, "valor_homologado": 991.0,
           "serie_certames_orgao": serie}
    r = J3DescontoAnomalo().avaliar(ctx)
    _valido(r)
    assert r.status == "confirmado"
    assert r.score >= ANCORAS["forte"]
    assert r.valores["recorrencia"]["n_serie"] == 12


def test_j3_recorrencia_nao_avaliavel_serie_curta():
    """Série < 12 certames → componente recorrência nao_avaliavel (honesto: 1 isolado não sustenta 'recorrente')."""
    ctx = {"processo": "julg-8", "valor_estimado": 1000.0, "valor_homologado": 990.0,
           "serie_certames_orgao": [{"valor_estimado": 100.0, "valor_homologado": 99.0}]}
    r = J3DescontoAnomalo().avaliar(ctx)
    _valido(r)
    # desconto irrisório do certame confirma (medio), mas a recorrência fica nao_avaliavel
    assert r.valores["recorrencia"]["n_serie"] == 1
    assert "nao_avaliavel" in r.motivo_refutacao or r.score <= ANCORAS["medio"] + 0.11


def test_j3_exculpatorio_item_regulado_descartado():
    """Desconto baixo MAS item de preço regulado (commodity) → não pontua → descartado."""
    ctx = {"processo": "julg-9", "valor_estimado": 1000.0, "valor_homologado": 995.0,
           "item_preco_regulado": True}
    r = J3DescontoAnomalo().avaliar(ctx)
    _valido(r)
    assert r.status == "descartado"
    assert r.score == 0.0


def test_j3_descartado_desconto_substantivo():
    """Desconto substantivo (20%) → descartado."""
    ctx = {"processo": "julg-10", "valor_estimado": 1000.0, "valor_homologado": 800.0}
    r = J3DescontoAnomalo().avaliar(ctx)
    _valido(r)
    assert r.status == "descartado"
    assert r.score == 0.0


def test_j3_nao_avaliavel_sem_valores():
    r = J3DescontoAnomalo().avaliar({"processo": "julg-11", "valor_estimado": 1000.0})  # sem homologado
    _valido(r)
    assert r.status == "nao_avaliavel"


# ═══════════════════════════════ J4 — supressão de propostas ═══════════════════════════════
def test_j4_confirma_afunilamento():
    """Muitos inscritos → 1 classificado (inabilitações/desistências) → forte."""
    ctx = {
        "processo": "julg-12",
        "licitantes_inscritos": 6,
        "licitantes_classificados": 1,
        "inabilitados": [{"cnpj": "2", "motivo": "documentação incompleta"},
                         {"cnpj": "3", "motivo": "certidão vencida"}],
        "desistencias": ["4", "5"],
    }
    r = J4SupressaoPropostas().avaliar(ctx)
    _valido(r)
    assert r.status == "confirmado"
    assert r.score >= ANCORAS["forte"]
    assert r.valores["inscritos_efetivo"] == 6


def test_j4_confirma_rubrica_rigor_seletivo():
    """Rubrica injetada 'rigor_seletivo_desproporcional' (sem rede) → forte."""
    ctx = {
        "processo": "julg-13",
        "licitantes_inscritos": 4,
        "licitantes_classificados": 1,
        "inabilitados": [{"cnpj": "2", "motivo": "erro grosseiro"}],
        "_rubrica_inabilitacao": {"nivel": "rigor_seletivo_desproporcional", "trecho": "dois pesos na ata"},
    }
    r = J4SupressaoPropostas().avaliar(ctx)
    _valido(r)
    assert r.status == "confirmado"
    assert r.score >= ANCORAS["forte"]
    assert r.valores["gravidade_inabilitacao"] == "rigor_seletivo_desproporcional"


def test_j4_exculpatorio_fundada_uniforme_descartado():
    """Inabilitação técnica fundada e uniforme (art.64, mesma régua) → não pontua → descartado."""
    ctx = {
        "processo": "julg-14",
        "licitantes_inscritos": 5,
        "licitantes_classificados": 1,
        "inabilitados": [{"cnpj": "2", "motivo": "documentação"}, {"cnpj": "3", "motivo": "documentação"}],
        "inabilitacao_fundada_uniforme": True,
    }
    r = J4SupressaoPropostas().avaliar(ctx)
    _valido(r)
    assert r.status == "descartado"
    assert r.score == 0.0


def test_j4_descartado_competicao_preservada():
    """Vários classificados, sem afunilamento → descartado."""
    ctx = {"processo": "julg-15", "licitantes_inscritos": 5, "licitantes_classificados": 4}
    r = J4SupressaoPropostas().avaliar(ctx)
    _valido(r)
    assert r.status == "descartado"
    assert r.score == 0.0


def test_j4_nao_avaliavel_sem_classificados():
    """Sem licitantes_classificados → nao_avaliavel (sem dados de proposta/ata)."""
    r = J4SupressaoPropostas().avaliar({"processo": "julg-16", "licitantes_inscritos": 5})
    _valido(r)
    assert r.status == "nao_avaliavel"


# ═══════════════════════════════ orquestrador + registro ═══════════════════════════════
def test_registro_tem_os_novos_julgamento():
    assert {"J2", "J3", "J4"} <= set(REGISTRO)
    # não quebrou os existentes (P1-5/J1/C/E1-3)
    assert {"P1", "P2", "P3", "P4", "P5", "J1", "C", "E1", "E2", "E3"} <= set(REGISTRO)


def test_rodar_julgamento_combina_j2_j3_j4():
    ctx = {
        # J2
        "propostas": [
            {"licitante_cnpj": "11111111000100", "valor": 100.0, "classificacao": 1},
            {"licitante_cnpj": "22222222000100", "valor": 115.0, "classificacao": 2},
            {"licitante_cnpj": "33333333000100", "valor": 115.4, "classificacao": 3},
        ],
        # J3
        "valor_estimado": 1000.0,
        "valor_homologado": 990.0,
        # J4
        "licitantes_inscritos": 6,
        "licitantes_classificados": 1,
        "inabilitados": [{"cnpj": "2", "motivo": "documentação incompleta"}],
        "desistencias": ["4", "5"],
    }
    res = rodar_julgamento("processo-z", contexto=ctx)
    ids = {r.detector for r in res}
    assert {"J2", "J3", "J4"} <= ids
    for r in res:
        _valido(r)
    from compliance_agent.detectores import PESOS_DETECTOR
    s = score_processo(res, PESOS_DETECTOR)
    assert 0.0 <= s <= 1.0


def test_rodar_julgamento_gap_pncp_so_vencedor():
    """Gap PNCP no orquestrador: só o vencedor → J2 nao_avaliavel, mas pipeline não quebra (honesto)."""
    ctx = {"propostas": [{"licitante_cnpj": "11111111000100", "valor": 100.0, "classificacao": 1}]}
    res = rodar_julgamento("processo-w", contexto=ctx)
    j2 = next(r for r in res if r.detector == "J2")
    assert j2.status == "nao_avaliavel"
    for r in res:
        _valido(r)


def test_rodar_julgamento_exculpatoria_degrada_sem_llm():
    """exculpatoria=True com gerar que SIMULA LLM offline → não refuta, não quebra (honesto)."""
    def _gerar_offline(prompt, sistema):
        raise RuntimeError("LLM offline")

    ctx = {"valor_estimado": 1000.0, "valor_homologado": 990.0}
    res = rodar_julgamento("processo-v", contexto=ctx, exculpatoria=True, gerar=_gerar_offline)
    for r in res:
        _valido(r)
        if r.status == "confirmado":
            assert r.refutada is False
