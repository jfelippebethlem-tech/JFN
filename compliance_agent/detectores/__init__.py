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
from compliance_agent.detectores.c6_vinculo_politico import C6VinculoPolitico
from compliance_agent.detectores.c_fachada import CFachada
from compliance_agent.detectores.e1_barreira import E1Barreira
from compliance_agent.detectores.e2_prazos import E2Prazos
from compliance_agent.detectores.e3_lote_pacote import E3LotePacote
from compliance_agent.detectores.e4_visita_tecnica import E4VisitaTecnica
from compliance_agent.detectores.e5_edital_iterado import E5EditalIterado
from compliance_agent.detectores.e6_pontuacao_dirigida import E6PontuacaoDirigida
from compliance_agent.detectores.e7_clausula_restritiva import E7ClausulaRestritiva
from compliance_agent.detectores.e8_deserto_dirigido import E8DesertoDirigido
from compliance_agent.detectores.j1_cartel import J1Cartel
from compliance_agent.detectores.j2_propostas_cobertura import J2PropostasCobertura
from compliance_agent.detectores.j3_desconto_anomalo import J3DescontoAnomalo
from compliance_agent.detectores.j4_supressao_propostas import J4SupressaoPropostas
from compliance_agent.detectores.j5_digitais_compartilhadas import J5DigitaisCompartilhadas
from compliance_agent.detectores.j6_subcontratacao_cruzada import J6SubcontratacaoCruzada
from compliance_agent.detectores.j7_inabilitacao_seletiva import J7InabilitacaoSeletiva
from compliance_agent.detectores.j_atestado_cruzado import JAtestadoCruzado
from compliance_agent.detectores.p1_especificacao_dirigida import P1EspecificacaoDirigida
from compliance_agent.detectores.p2_cotacoes_combinadas import P2CotacoesCombinadas
from compliance_agent.detectores.p3_sobrepreco import P3Sobrepreco
from compliance_agent.detectores.p4_fracionamento import P4Fracionamento
from compliance_agent.detectores.p5_emergencia_fabricada import P5EmergenciaFabricada
from compliance_agent.detectores.x1_crescimento_aditivo import X1CrescimentoAditivo
from compliance_agent.detectores.x2_prorrogacao_perpetua import X2ProrrogacaoPerpetua
from compliance_agent.detectores.x3_execucao_financeira import X3ExecucaoFinanceira
from compliance_agent.detectores.x4_carona_abusiva import X4CaronaAbusiva
from compliance_agent.detectores.x5_jogo_planilha import X5JogoDePlanilha
from compliance_agent.detectores.x6_entrega_fantasma import X6EntregaFantasma

# REGISTRO de detectores disponíveis (id → instância). Os próximos cards se registram aqui.
REGISTRO: dict[str, Detector] = {
    d.id: d for d in (
        P4Fracionamento(),
        J1Cartel(),
        J2PropostasCobertura(),  # fase de julgamento — propostas de cobertura (screens de preço)
        J3DescontoAnomalo(),     # fase de julgamento — desconto anômalo/irrisório recorrente
        J4SupressaoPropostas(),  # fase de julgamento — supressão de propostas/licitante único
        P3Sobrepreco(),
        CFachada(),
        J5DigitaisCompartilhadas(),  # julgamento — propostas com metadados/redação/origem compartilhados
        J6SubcontratacaoCruzada(),   # julgamento/execução — subcontratar perdedores / consórcio anômalo
        J7InabilitacaoSeletiva(),    # julgamento — inabilitação seletiva (dois pesos na sessão)
        JAtestadoCruzado(),          # habilitação — atestado emitido por empresa vinculada (Ac. TCU 725/2026)
        E1Barreira(),    # fase de edital — barreira de entrada/qualificação
        E2Prazos(),      # fase de edital — publicidade e prazos minimizados
        E3LotePacote(),  # fase de edital — lote-pacote/agregação anticompetitiva
        E4VisitaTecnica(),     # fase de edital — visita técnica obrigatória como filtro
        E5EditalIterado(),     # fase de edital — republicações dirigidas (edital iterado)
        E6PontuacaoDirigida(),  # fase de edital — pontuação técnica dirigida (técnica e preço)
        E7ClausulaRestritiva(),  # fase de edital — cláusula-a-cláusula finalística + efeito combinado (jurisprudência)
        E8DesertoDirigido(),     # fase de edital — deserto/fracassado reincidente convertido em contratação direta
        P1EspecificacaoDirigida(),  # fase de planejamento — especificação dirigida/marca disfarçada
        P2CotacoesCombinadas(),     # fase de planejamento — cotações combinadas/orçamentos de fachada
        P5EmergenciaFabricada(),    # fase de planejamento — emergência fabricada (dispensa art. 75 VIII)
        C6VinculoPolitico(),   # perfil do contratado — vínculo político-financeiro (doações TSE); multiplicador
        X1CrescimentoAditivo(),  # execução — crescimento aditivo (teto art. 125)
        X2ProrrogacaoPerpetua(),  # execução — prorrogação perpétua sem teste de mercado
        X3ExecucaoFinanceira(),   # execução — execução financeira anômala (tríade SIAFE/atesto/fila)
        X4CaronaAbusiva(),        # execução — carona abusiva em ARP (limites art. 86)
        X5JogoDePlanilha(),       # execução — jogo de planilha (sobrepreço correlacionado a aditivo)
        X6EntregaFantasma(),      # execução — entrega fantasma / atesto de fachada (culmina em diligência)
    )
}

# pesos por detector p/ a convergência multiplicativa (§7.2): herdam o peso da família do detector.
PESOS_DETECTOR: dict[str, float] = {
    "P4": PESOS_FAMILIA["violacao_legal"],
    "J1": PESOS_FAMILIA["conluio"],
    "J2": PESOS_FAMILIA["conluio"],
    "J3": PESOS_FAMILIA["conluio"],
    "J4": PESOS_FAMILIA["conluio"],
    "J5": PESOS_FAMILIA["conluio"],
    "J6": PESOS_FAMILIA["conluio"],
    "J7": PESOS_FAMILIA["conluio"],
    "J8": PESOS_FAMILIA["conluio"],
    "P3": PESOS_FAMILIA["preco"],
    "C1": PESOS_FAMILIA["perfil"], "C2": PESOS_FAMILIA["perfil"],
    "C3/C5": PESOS_FAMILIA["perfil"], "C4": PESOS_FAMILIA["perfil"],
    "C6": PESOS_FAMILIA["perfil"],
    "E1": PESOS_FAMILIA["desenho_certame"],
    "E2": PESOS_FAMILIA["desenho_certame"],
    "E3": PESOS_FAMILIA["desenho_certame"],
    "E4": PESOS_FAMILIA["desenho_certame"],
    "E5": PESOS_FAMILIA["desenho_certame"],
    "E6": PESOS_FAMILIA["desenho_certame"],
    "E7": PESOS_FAMILIA["desenho_certame"],
    "P1": PESOS_FAMILIA["desenho_certame"],
    "P2": PESOS_FAMILIA["preco"],
    "P5": PESOS_FAMILIA["desenho_certame"],
    "X1": PESOS_FAMILIA["execucao"],
    "X2": PESOS_FAMILIA["execucao"],
    "X3": PESOS_FAMILIA["execucao"],
    "X4": PESOS_FAMILIA["execucao"],
    "X5": PESOS_FAMILIA["execucao"],
    "X6": PESOS_FAMILIA["execucao"],
}


def rodar_orgao(ug: str, *, contexto: dict | None = None, exculpatoria: bool = False, gerar=None) -> list[ResultadoDetector]:
    """Orquestra os detectores de ÓRGÃO (entrada = UG). Hoje: J1 (conluio/cartel por concentração de grupo +
    rodízio temporal). Reusa `pipeline` (isola detector que quebra → nao_avaliavel honesto, não derruba os outros).

    `contexto` extra (opcional) é mesclado — em teste, injete `concentracao`/`rodizio` aqui p/ não tocar DuckDB."""
    ctx: dict[str, Any] = {"processo": str(ug), "ug": str(ug)}
    if contexto:
        ctx.update(contexto)
    # J1 é o detector de conluio que opera por UG (concentração/rodízio). J2/J3/J4 operam por CERTAME
    # (lista de propostas/valores/atas) → ficam no `rodar_julgamento`, não aqui (evita nao_avaliavel inútil na UG).
    dets = [d for d in REGISTRO.values() if d.id == "J1"]
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
    # P3 (preço) + C6 (perfil/vínculo político, multiplicador) — detectores de fornecedor de 1-resultado via
    # pipeline padrão. C6 é conservador (máx. medio) e nao_avaliavel sem QSA+doações no contexto (honesto).
    simples = [d for d in REGISTRO.values() if d.familia == "preco" or d.id == "C6"]
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
      E7 → {clausulas_edital[{tipo,categoria,texto,pct?,valor?,tem_ou_equivalente?,tem_declaracao_substitutiva?,justificativa_autos?}], valor_estimado?, resultado{licitantes,inabilitados}, objeto_critico?}
    `gerar` (callable) alimenta as rubricas LLM-opcionais; ausente → partes subjetivas degradam para nao_avaliavel."""
    ctx: dict[str, Any] = {"processo": str(processo)}
    if contexto:
        ctx.update(contexto)
    if gerar is not None and "gerar" not in ctx:
        ctx["gerar"] = gerar
    dets = [d for d in REGISTRO.values() if d.id in ("E1", "E2", "E3", "E4", "E5", "E6", "E7", "E8")]
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


def rodar_julgamento(processo: str, *, contexto: dict | None = None, exculpatoria: bool = False, gerar=None) -> list[ResultadoDetector]:
    """Orquestra os detectores da FASE DE JULGAMENTO / conluio por CERTAME (J2/J3/J4) sobre o contexto de um
    certame. Reusa `pipeline` (um detector que quebra vira nao_avaliavel honesto, não derruba os outros).

    CLÁUSULA DE HONESTIDADE (gap PNCP): o PNCP só expõe o VENCEDOR — sem a LISTA de propostas/licitantes, J2
    (e em parte J4) viram `nao_avaliavel` por construção; conluio NUNCA é pontuado sem os dados das propostas.

    `contexto` traz o que os cards pedem (interface honesta — campo essencial ausente → nao_avaliavel):
      J2 → {propostas[{licitante_cnpj, valor, classificacao}], valor_estimado?, certames_relacionados?[], mercado_homogeneo?}
      J3 → {valor_estimado, valor_homologado, desconto_medio_orgao?, desconto_mercado_categoria?,
            serie_certames_orgao?[], item_preco_regulado?}
      J4 → {licitantes_inscritos?, licitantes_classificados, inabilitados[{cnpj,motivo}], desistencias[],
            inabilitacao_fundada_uniforme?}
    `gerar` (callable) alimenta as rubricas LLM-opcionais; ausente → partes subjetivas degradam para nao_avaliavel."""
    ctx: dict[str, Any] = {"processo": str(processo)}
    if contexto:
        ctx.update(contexto)
    if gerar is not None and "gerar" not in ctx:
        ctx["gerar"] = gerar
    dets = [d for d in REGISTRO.values() if d.id in ("J2", "J3", "J4", "J5", "J6", "J7")]
    return pipeline(dets, ctx, exculpatoria=exculpatoria, gerar=gerar)


def rodar_execucao(processo: str, *, contexto: dict | None = None, exculpatoria: bool = False, gerar=None) -> list[ResultadoDetector]:
    """Orquestra os detectores da FASE DE EXECUÇÃO (X1–X6) sobre o contexto de execução de um contrato. Reusa
    `pipeline` (um detector que quebra vira nao_avaliavel honesto, não derruba os outros).

    `contexto` traz o que os cards pedem (interface honesta — campo essencial ausente → nao_avaliavel):
      X1 → {valor_inicial, tipo_objeto?, aditivos[{data?,tipo,valor,justificativa?,descricao_objeto?}], data_inicio_execucao?, indice_atualizacao?}
      X2 → {vigencia_inicio?, vigencia_fim_atual?|tempo_total_anos?, prorrogacoes[{data?,anos?,pesquisa_vantajosidade?}], cadeia_emergencia?}
      X3 → {pagamentos[{data_empenho?,data_liquidacao?,data_pagamento,valor,data_atesto?}], tipo_objeto?, tem_cronograma?, fila_orgao?, medicoes?}
      X4 → {ata{itens[{item,quantitativo_registrado}]}, adesoes[{aderente,item,quantidade,data?,justificativa?,municipio?}], preco_ata_vs_mercado?}
      X5 → {itens[{item,preco_contratado,quantidade_contratada,referencial,quantidade_executada?}]}
      X6 → {pagamentos[{valor,data,tem_nf?,tem_recebimento?}]|atestos[{texto,data}], medicoes?, fiscais?, capacidade_fornecedor?, volume_contratado?, tipo_objeto?, documento_conflitante?}
    `gerar` (callable) alimenta as rubricas LLM-opcionais; ausente → partes subjetivas degradam para nao_avaliavel."""
    ctx: dict[str, Any] = {"processo": str(processo)}
    if contexto:
        ctx.update(contexto)
    if gerar is not None and "gerar" not in ctx:
        ctx["gerar"] = gerar
    dets = [d for d in REGISTRO.values() if d.id in ("X1", "X2", "X3", "X4", "X5", "X6")]
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
    "J2PropostasCobertura",
    "J3DescontoAnomalo",
    "J4SupressaoPropostas",
    "J5DigitaisCompartilhadas",
    "J6SubcontratacaoCruzada",
    "J7InabilitacaoSeletiva",
    "P3Sobrepreco",
    "CFachada",
    "C6VinculoPolitico",
    "E1Barreira",
    "E2Prazos",
    "E3LotePacote",
    "E4VisitaTecnica",
    "E5EditalIterado",
    "E6PontuacaoDirigida",
    "E7ClausulaRestritiva",
    "E8DesertoDirigido",
    "P1EspecificacaoDirigida",
    "P2CotacoesCombinadas",
    "P5EmergenciaFabricada",
    "X1CrescimentoAditivo",
    "X2ProrrogacaoPerpetua",
    "X3ExecucaoFinanceira",
    "X4CaronaAbusiva",
    "X5JogoDePlanilha",
    "X6EntregaFantasma",
    "rodar_orgao",
    "rodar_fornecedor",
    "rodar_edital",
    "rodar_planejamento",
    "rodar_julgamento",
    "rodar_execucao",
]
