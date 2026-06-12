# -*- coding: utf-8 -*-
"""Framework de DETECTORES de corrupção em licitações (spec V2 do dono).

Fundamento em `base.py` (schema padrão · score com âncoras fixas · rubrica fechada · verificador adversarial
LLM-opcional que degrada honesto · pipeline + convergência multiplicativa §7.2). Cards de detector plugam aqui
e REUSAM o que o JFN já tem (ver o MAPA DOS 30 DETECTORES no docstring de `base.py`).

    from compliance_agent.detectores import Detector, ResultadoDetector, pipeline, REGISTRO
    res = pipeline(list(REGISTRO.values()), contexto)

ORQUESTRADOR (entrada do mundo real → lista de ResultadoDetector, schema fixo §1.4):
    from compliance_agent.detectores import rodar_orgao, rodar_fornecedor
    rodar_orgao("036100")            # J1 (conluio/cartel por UG)
    rodar_fornecedor("12.345.678/0001-90")  # P3 (sobrepreço) + C (C1/C2/C3-5/C4 fachada)
"""
from __future__ import annotations

from typing import Any

from compliance_agent.detectores.base import (
    ANCORAS,
    PESOS_FAMILIA,
    Detector,
    ResultadoDetector,
    ancora,
    aplicar_exculpatoria,
    avaliar_rubrica,
    evidencia,
    pipeline,
    score_processo,
    verificar_adversarial,
)
from compliance_agent.detectores.c_fachada import CFachada
from compliance_agent.detectores.e1_barreira import E1Barreira
from compliance_agent.detectores.e2_prazos import E2Prazos
from compliance_agent.detectores.e3_lote_pacote import E3LotePacote
from compliance_agent.detectores.j1_cartel import J1Cartel
from compliance_agent.detectores.p1_especificacao_dirigida import P1EspecificacaoDirigida
from compliance_agent.detectores.p2_cotacoes_combinadas import P2CotacoesCombinadas
from compliance_agent.detectores.p3_sobrepreco import P3Sobrepreco
from compliance_agent.detectores.p4_fracionamento import P4Fracionamento
from compliance_agent.detectores.p5_emergencia_fabricada import P5EmergenciaFabricada

# REGISTRO de detectores disponíveis (id → instância). Os próximos cards se registram aqui.
REGISTRO: dict[str, Detector] = {
    d.id: d for d in (
        P4Fracionamento(),
        J1Cartel(),
        P3Sobrepreco(),
        CFachada(),
        E1Barreira(),    # fase de edital — barreira de entrada/qualificação
        E2Prazos(),      # fase de edital — publicidade e prazos minimizados
        E3LotePacote(),  # fase de edital — lote-pacote/agregação anticompetitiva
        P1EspecificacaoDirigida(),  # fase de planejamento — especificação dirigida/marca disfarçada
        P2CotacoesCombinadas(),     # fase de planejamento — cotações combinadas/orçamentos de fachada
        P5EmergenciaFabricada(),    # fase de planejamento — emergência fabricada (dispensa art. 75 VIII)
    )
}

# pesos por detector p/ a convergência multiplicativa (§7.2): herdam o peso da família do detector.
PESOS_DETECTOR: dict[str, float] = {
    "P4": PESOS_FAMILIA["violacao_legal"],
    "J1": PESOS_FAMILIA["conluio"],
    "P3": PESOS_FAMILIA["preco"],
    "C1": PESOS_FAMILIA["perfil"], "C2": PESOS_FAMILIA["perfil"],
    "C3/C5": PESOS_FAMILIA["perfil"], "C4": PESOS_FAMILIA["perfil"],
    "E1": PESOS_FAMILIA["desenho_certame"],
    "E2": PESOS_FAMILIA["desenho_certame"],
    "E3": PESOS_FAMILIA["desenho_certame"],
    "P1": PESOS_FAMILIA["desenho_certame"],
    "P2": PESOS_FAMILIA["preco"],
    "P5": PESOS_FAMILIA["desenho_certame"],
}


def rodar_orgao(ug: str, *, contexto: dict | None = None, exculpatoria: bool = False, gerar=None) -> list[ResultadoDetector]:
    """Orquestra os detectores de ÓRGÃO (entrada = UG). Hoje: J1 (conluio/cartel por concentração de grupo +
    rodízio temporal). Reusa `pipeline` (isola detector que quebra → nao_avaliavel honesto, não derruba os outros).

    `contexto` extra (opcional) é mesclado — em teste, injete `concentracao`/`rodizio` aqui p/ não tocar DuckDB."""
    ctx: dict[str, Any] = {"processo": str(ug), "ug": str(ug)}
    if contexto:
        ctx.update(contexto)
    dets = [d for d in REGISTRO.values() if d.familia == "conluio"]
    return pipeline(dets, ctx, exculpatoria=exculpatoria, gerar=gerar)


def rodar_fornecedor(cnpj: str, *, contexto: dict | None = None, exculpatoria: bool = False, gerar=None) -> list[ResultadoDetector]:
    """Orquestra os detectores de FORNECEDOR (entrada = CNPJ). Hoje: P3 (sobrepreço interno) + C (C1/C2/C3-5/C4
    perfil de fachada/laranja). C produz VÁRIOS resultados por investigação (`avaliar_todos`), então é tratado à
    parte; P3 (e qualquer outro detector de fornecedor de 1 resultado) passa pelo `pipeline` padrão.

    `contexto` extra (opcional) é mesclado — em teste, injete `investigacao`/`achados`/`registros` p/ não tocar
    rede/DuckDB. `exculpatoria=True` roda o verificador adversarial nos achados confirmados (LLM-opcional)."""
    ctx: dict[str, Any] = {"processo": str(cnpj), "cnpj": str(cnpj)}
    if contexto:
        ctx.update(contexto)

    resultados: list[ResultadoDetector] = []
    # P3 e outros detectores de fornecedor de 1-resultado via pipeline padrão
    simples = [d for d in REGISTRO.values() if d.familia == "preco"]
    resultados.extend(pipeline(simples, ctx, exculpatoria=exculpatoria, gerar=gerar))

    # C (fachada) — multi-resultado por investigação
    cdet = REGISTRO.get("C")
    if isinstance(cdet, CFachada):
        cres = cdet.avaliar_todos(ctx)
        if exculpatoria:
            for r in cres:
                if r.status == "confirmado":
                    achado = f"{r.detector} score={r.score}: {r.explicacao_inocente or 'indício de fachada'}"
                    aplicar_exculpatoria(r, achado, gerar=gerar)
        resultados.extend(cres)
    return resultados


def rodar_edital(processo: str, *, contexto: dict | None = None, exculpatoria: bool = False, gerar=None) -> list[ResultadoDetector]:
    """Orquestra os detectores da FASE DE EDITAL (E1/E2/E3) sobre o CONTEXTO DE EDITAL de um certame. Reusa
    `pipeline` (um detector que quebra vira nao_avaliavel honesto, não derruba os outros).

    `contexto` traz o que os cards pedem (interface honesta — campo essencial ausente → nao_avaliavel):
      E1 → {exigencias_habilitacao[], valor_estimado, quantitativos, editais_analogos[], resultado{licitantes,inabilitados}, objeto_critico?}
      E2 → {data_publicacao, data_abertura, modalidade, criterio?, feriados?, no_pncp?, versoes[]}
      E3 → {lotes[{itens[{descricao,catmat|catser|classe}]}], catmat_por_item?, justificativa_nao_parcelamento, resultado}
    `gerar` (callable) alimenta as rubricas LLM-opcionais; ausente → partes subjetivas degradam para nao_avaliavel."""
    ctx: dict[str, Any] = {"processo": str(processo)}
    if contexto:
        ctx.update(contexto)
    if gerar is not None and "gerar" not in ctx:
        ctx["gerar"] = gerar
    dets = [d for d in REGISTRO.values() if d.id in ("E1", "E2", "E3")]
    return pipeline(dets, ctx, exculpatoria=exculpatoria, gerar=gerar)


def rodar_planejamento(processo: str, *, contexto: dict | None = None, exculpatoria: bool = False, gerar=None) -> list[ResultadoDetector]:
    """Orquestra os detectores da FASE DE PLANEJAMENTO (P1/P2/P5) sobre o CONTEXTO de planejamento de um processo.
    Reusa `pipeline` (um detector que quebra vira nao_avaliavel honesto, não derruba os outros).

    `contexto` traz o que os cards pedem (interface honesta — campo essencial ausente → nao_avaliavel):
      P1 → {tr_texto?, requisitos[{requisito,valor,unidade,nominativo?}], datasheets_finalistas?,
            editais_analogos[], resultado{licitantes,vencedor,produto_ofertado?}, processo_padronizacao?,
            justificativa_marca?}
      P2 → {cotacoes[{cnpj,razao,data,valores,itens,contato,metadados_pdf?}], qsa_por_cnpj?, vencedor_cnpj,
            ref_pncp?, item_preco_regulado?}
      P5 → {data_abertura_processo, data_contrato?, vigencia?, fato_gerador{descricao,data}, contratado?,
            data_proposta?, contrato_anterior?{vencimento}, emergencias_orgao_24m?, desastre_confirmado?,
            certame_anterior_fracassado?}
    `gerar` (callable) alimenta as rubricas LLM-opcionais; ausente → partes subjetivas degradam para nao_avaliavel."""
    ctx: dict[str, Any] = {"processo": str(processo)}
    if contexto:
        ctx.update(contexto)
    if gerar is not None and "gerar" not in ctx:
        ctx["gerar"] = gerar
    dets = [d for d in REGISTRO.values() if d.id in ("P1", "P2", "P5")]
    return pipeline(dets, ctx, exculpatoria=exculpatoria, gerar=gerar)


__all__ = [
    "Detector",
    "ResultadoDetector",
    "pipeline",
    "score_processo",
    "ancora",
    "avaliar_rubrica",
    "verificar_adversarial",
    "aplicar_exculpatoria",
    "evidencia",
    "ANCORAS",
    "PESOS_FAMILIA",
    "PESOS_DETECTOR",
    "REGISTRO",
    "P4Fracionamento",
    "J1Cartel",
    "P3Sobrepreco",
    "CFachada",
    "E1Barreira",
    "E2Prazos",
    "E3LotePacote",
    "P1EspecificacaoDirigida",
    "P2CotacoesCombinadas",
    "P5EmergenciaFabricada",
    "rodar_orgao",
    "rodar_fornecedor",
    "rodar_edital",
    "rodar_planejamento",
]
