# -*- coding: utf-8 -*-
"""Catálogo canônico de VÍCIOS DE LICITAÇÃO — fonte única que cruza os três acervos da casa.

Antes deste módulo o conhecimento vivia em TRÊS lugares paralelos, sem cruzamento:
  • `detectores/` (28 detectores P/E/J/C/X registrados — o que RODA);
  • `lex_redflags._RF` (R2-R14 + DD/H-* — o que o Lex NARRA no parecer);
  • `knowledge/fraudes_licitacao.FRAUDES` + `jurisprudencia.INDICE_CLAUSULA`/`SUMULAS` (o que FUNDAMENTA).

Padrão importado do anthropics/claude-for-legal (2026-07-20): playbook ÚNICO que toda skill/produto lê —
cada vício é UMA entrada com ponteiros para detector, red flag do Lex, padrão de fraude, tipo de cláusula
do E7, base legal, teste objetivo e medida de escalada. `validar()` garante que nenhum ponteiro aponta
para o vazio (teste automatizado em tests/test_catalogo_vicios.py).

Honestidade metodológica:
  • `status="lacuna"` = vício catalogado SEM detector automatizado (declarado, não escondido);
    `status="parcial"` = coberto por ferramenta fora do REGISTRO (Lex, cruzamentos_intel, cérebro).
  • O rol NÃO é taxativo (mesma doutrina de conhecimento/restritividade_licitacoes.md).
  • `escalada` é a medida TÍPICA quando o vício se confirma com verossimilhança alta — a régua fina
    (matriz S×V, gatilhos de urgência) vive em `editais/escalada.py` e na skill analise-clausulas-br.

Origens metodológicas externas fundidas aqui:
  • anthropics/claude-for-legal — playbook-driven review, triagem 🟢🟡🔴, escalation-flagger;
  • redflags.eu (K-Monitor/TI Hungria) — indicadores determinísticos de edital e de resultado;
  • trilhas ALICE/CGU — fracionamento, prazos mínimos, dia não útil, sobrepreço, recém-criadas;
  • listas de verificação AGU (Lei 14.133) e checklists D1-D10 Transparência Brasil (já na perícia);
  • jurisprudência TCU/TCE-RJ (verbatim em knowledge/jurisprudencia.py).
"""
from __future__ import annotations

from dataclasses import dataclass

FASES = ("planejamento", "edital", "julgamento", "perfil_contratado", "execucao")
ESCALADAS = ("monitorar", "diligencia", "representacao", "representacao_cautelar", "auditoria_tematica")


@dataclass(frozen=True)
class Vicio:
    id: str                                   # slug canônico
    nome: str
    fase: str                                 # uma de FASES
    descricao: str                            # 1-2 linhas, linguagem de controle externo
    detectores: tuple[str, ...] = ()          # ids do REGISTRO (P1..X6, C, C6, J8)
    redflags_lex: tuple[str, ...] = ()        # chaves de lex_redflags._RF (R2..R14, DD/H-*)
    fraudes: tuple[str, ...] = ()             # ids de fraudes_licitacao.FRAUDES_POR_ID
    clausulas: tuple[str, ...] = ()           # tipos de jurisprudencia.INDICE_CLAUSULA
    dispositivos: tuple[str, ...] = ()        # base legal citável (verificada em fonte)
    sumulas: tuple[str, ...] = ()             # nomes resolvíveis por jurisprudencia.obter_sumula
    teste_objetivo: str = ""                  # regra determinística, se houver ("" = juízo qualitativo)
    escalada: str = "diligencia"              # uma de ESCALADAS
    origem: tuple[str, ...] = ("casa",)       # proveniência metodológica
    status: str = "coberto"                   # coberto | parcial | lacuna


CATALOGO: tuple[Vicio, ...] = (
    # ───────────────────────────── PLANEJAMENTO ─────────────────────────────
    Vicio("especificacao_dirigida", "Especificação dirigida / marca disfarçada", "planejamento",
          "TR/ETP descreve o produto de UM fornecedor (marca, part-number ou combinação única de requisitos).",
          detectores=("P1", "E7"), redflags_lex=("R7",), fraudes=("direcionamento_edital",),
          clausulas=("marca_dirigida",), dispositivos=("Lei 14.133/2021 art. 9º I", "Lei 14.133/2021 art. 41 I"),
          sumulas=("Súmula TCU 270", "Súmula TCU 177"),
          teste_objetivo="marca sem 'ou equivalente/similar' → violado (teste_finalistico:marca)",
          escalada="representacao", origem=("casa", "TCU")),
    Vicio("cotacoes_combinadas", "Cotações combinadas (orçamentos de fachada)", "planejamento",
          "Pesquisa de preços com orçamentos de empresas ligadas entre si ou emitidos em sequência/mesma digital.",
          detectores=("P2",), redflags_lex=("R3",),
          dispositivos=("Lei 14.133/2021 art. 23",), escalada="diligencia", origem=("casa", "CGU")),
    Vicio("sobrepreco_estimativa", "Sobrepreço na estimativa", "planejamento",
          "Valor de referência acima da mediana de mercado/interna para o mesmo item (cesta de preços deficiente).",
          detectores=("P3",), redflags_lex=("R3", "R4"), fraudes=("superfaturamento_preco",),
          dispositivos=("Lei 14.133/2021 art. 11 III", "Lei 14.133/2021 art. 23"),
          teste_objetivo="preço unitário vs mediana/p90 interna (comparador_precos)",
          escalada="diligencia", origem=("casa", "ALICE/CGU")),
    Vicio("fracionamento_despesa", "Fracionamento de despesa", "planejamento",
          "Despesas do mesmo objeto/UG/exercício divididas para caber no teto de dispensa ou fugir de modalidade.",
          detectores=("P4",), redflags_lex=("R2",), fraudes=("fracionamento_objeto",),
          dispositivos=("Lei 14.133/2021 art. 75 §1º",),
          teste_objetivo="soma anual por objeto/UG colada no teto de dispensa (P4)",
          escalada="representacao", origem=("casa", "ALICE/CGU")),
    Vicio("emergencia_fabricada", "Emergência fabricada para dispensa", "planejamento",
          "Urgência criada por inércia administrativa (contrato deixado vencer) para contratar direto (art. 75 VIII).",
          detectores=("P5",), redflags_lex=("R5",), fraudes=("dispensa_emergencia_fabricada",),
          dispositivos=("Lei 14.133/2021 art. 75 VIII",), escalada="representacao", origem=("casa",)),
    Vicio("planejamento_fachada", "Planejamento de fachada (DFD/ETP/TR genéricos)", "planejamento",
          "Estudos e termo de referência genéricos/copiados que não sustentam a contratação (presinais do cérebro).",
          redflags_lex=("R12",), dispositivos=("Lei 14.133/2021 art. 5º", "Lei 14.133/2021 art. 18"),
          escalada="diligencia", origem=("casa",), status="parcial"),
    Vicio("contratacao_direta_indevida", "Dispensa/inexigibilidade indevida", "planejamento",
          "Enquadramento forçado em contratação direta (arts. 72-75) sem os pressupostos; inclui limites de valor "
          "(ferramenta transversal compliance_agent/limites_dispensa.py, fora do REGISTRO).",
          redflags_lex=("R5",), fraudes=("inexigibilidade_indevida",),
          dispositivos=("Lei 14.133/2021 arts. 72-75",), escalada="representacao",
          origem=("casa",), status="parcial"),

    # ─────────────────────────────── EDITAL ───────────────────────────────
    Vicio("barreira_habilitacao", "Barreira de entrada na habilitação", "edital",
          "Qualificação técnica/econômica desproporcional ao objeto (atestados, capital, índices, vínculo prévio).",
          detectores=("E1", "E7"), redflags_lex=("R7",), fraudes=("habilitacao_excessiva",),
          clausulas=("atestado_quantitativo", "capital_patrimonio", "indices_contabeis", "vinculo_profissional"),
          dispositivos=("Lei 14.133/2021 art. 67", "Lei 14.133/2021 art. 69"),
          sumulas=("Súmula TCU 263", "Súmula TCU 272", "Súmula TCU 275", "Súmula TCU 289", "Súmula TCE-RJ 10"),
          teste_objetivo="atestado ≤50% (S.263); capital/PL ≤10% e não cumulado (S.275) — teste_finalistico",
          escalada="representacao_cautelar", origem=("casa", "TCU", "redflags.eu")),
    Vicio("faturamento_minimo_exigido", "Faturamento/receita mínima exigida", "edital",
          "Exigência de faturamento mínimo não consta do rol restrito de habilitação econômico-financeira do "
          "art. 69 (capital OU patrimônio líquido, ≤ 10%); acima de 10% é desproporcional por analogia direta.",
          detectores=("E1", "E7"), clausulas=("faturamento_minimo",),
          dispositivos=("Lei 14.133/2021 art. 69", "Lei 14.133/2021 art. 66"), sumulas=("Súmula TCU 275",),
          teste_objetivo=">10% do estimado → violado; qualquer % → atípico, juízo ao colegiado (teste_finalistico)",
          escalada="diligencia", origem=("redflags.eu",)),
    Vicio("publicidade_prazos_minimizados", "Publicidade e prazos minimizados", "edital",
          "Prazo útil entre publicação e abertura abaixo do mínimo do art. 55, data-sombra ou retificação "
          "substancial sem reabertura de prazo.",
          detectores=("E2",), dispositivos=("Lei 14.133/2021 art. 54", "Lei 14.133/2021 art. 55"),
          teste_objetivo="dias ÚTEIS reais vs tabela MINIMOS_ART55 (E2) — violação objetiva se abaixo",
          escalada="representacao_cautelar", origem=("casa", "ALICE/CGU", "redflags.eu")),
    Vicio("lote_pacote", "Lote-pacote (agregação anticompetitiva)", "edital",
          "Objetos divisíveis reunidos num lote único que só o incumbente/grupo consegue atender.",
          detectores=("E3",), sumulas=("Súmula TCU 247",),
          teste_objetivo="divisibilidade do objeto vs adjudicação global (E3)",
          escalada="diligencia", origem=("casa", "TCU")),
    Vicio("visita_tecnica_filtro", "Visita técnica obrigatória como filtro", "edital",
          "Visita presencial obrigatória (janela única/agendamento restrito) usada para censo e coação de entrantes.",
          detectores=("E4",), clausulas=("visita_tecnica",), dispositivos=("Lei 14.133/2021 art. 63",),
          sumulas=("Súmula TCE-RJ 01",), escalada="diligencia", origem=("casa", "TCE-RJ")),
    Vicio("republicacao_dirigida", "Republicações dirigidas do edital", "edital",
          "Edital republicado com mudanças que estreitam a competição a cada versão (diff entre versões).",
          detectores=("E5",), dispositivos=("Lei 14.133/2021 art. 55 §1º",),
          escalada="diligencia", origem=("casa",)),
    Vicio("pontuacao_dirigida", "Pontuação técnica dirigida", "edital",
          "Quesitos de pontuação subjetivos/onerosos que dirigem técnica-e-preço ao fornecedor pré-escolhido.",
          detectores=("E6",), clausulas=("pontuacao_dirigida",),
          dispositivos=("Lei 14.133/2021 arts. 36-37",), sumulas=("Súmula TCU 272",),
          escalada="representacao", origem=("casa", "TCU")),
    Vicio("clausula_restritiva_combinada", "Efeito combinado de cláusulas restritivas", "edital",
          "Cláusulas individualmente defensáveis que, somadas (≥3 categorias distintas), fecham o certame — "
          "aferição finalística cláusula-a-cláusula com cascata na ata (E7).",
          detectores=("E7",), redflags_lex=("R7",), clausulas=("direcionamento_conjunto",),
          dispositivos=("Lei 14.133/2021 art. 9º I", "Lei 14.133/2021 art. 5º"), sumulas=("Súmula TCU 272",),
          escalada="representacao_cautelar", origem=("casa", "claude-for-legal")),
    Vicio("garantia_proposta_excessiva", "Garantia de proposta acima do teto", "edital",
          "Garantia de participação superior a 1% do estimado, ou cumulada com capital/PL mínimo.",
          detectores=("E1", "E7"), clausulas=("garantia_proposta",),
          dispositivos=("Lei 14.133/2021 art. 58 §1º",), sumulas=("Súmula TCU 275",),
          teste_objetivo="garantia ≤1% (teste_finalistico); cumulação com capital/PL = vício autônomo (S.275)",
          escalada="diligencia", origem=("casa", "redflags.eu")),
    Vicio("vigencia_excessiva", "Vigência inicial excessiva ou indeterminada", "edital",
          "Serviço contínuo com vigência inicial acima de 5 anos (art. 106) ou prazo indeterminado fora da "
          "hipótese de monopólio (art. 109); contratos por escopo seguem regra própria (art. 111).",
          detectores=("E7",), clausulas=("vigencia_contratual",),
          dispositivos=("Lei 14.133/2021 art. 106", "Lei 14.133/2021 art. 107",
                        "Lei 14.133/2021 art. 109", "Lei 14.133/2021 art. 111"),
          teste_objetivo=">60 meses contínuo ou indeterminado sem monopólio → violado (teste_finalistico)",
          escalada="diligencia", origem=("redflags.eu",)),
    Vicio("recorte_geografico", "Recorte geográfico de habilitação", "edital",
          "Sede/filial/escritório local exigido como CONDIÇÃO de participação (não de execução).",
          detectores=("E7",), clausulas=("recorte_geografico",),
          dispositivos=("Lei 14.133/2021 art. 9º I 'b'",), escalada="representacao",
          origem=("casa", "redflags.eu")),
    Vicio("atestado_unico", "Vedação de somatório de atestados", "edital",
          "Exigir que a experiência venha de UM só contrato/atestado quando o somatório demonstraria a aptidão.",
          detectores=("E7",), clausulas=("atestado_identico",), sumulas=("Súmula TCU 263",),
          dispositivos=("Lei 14.133/2021 art. 67",), escalada="diligencia",
          origem=("casa", "TCU", "redflags.eu")),
    Vicio("deserto_fracassado_dirigido", "Deserto/fracassado reincidente → contratação direta", "edital",
          "Certame repetidamente deserto/fracassado (edital propositalmente inviável) para justificar dispensa "
          "(art. 75 III). Detector E8 sobre a série do órgão/objeto; exculpatória = republicação flexibilizada.",
          detectores=("E8",), dispositivos=("Lei 14.133/2021 art. 75 III",),
          teste_objetivo="≥2 desertos/fracassados sem ajuste + conversão em direta → crítico (E8)",
          escalada="diligencia", origem=("redflags.eu",)),

    # ────────────────────────────── JULGAMENTO ──────────────────────────────
    Vicio("cartel_rodizio", "Cartel — rodízio de vencedores", "julgamento",
          "Mesmo grupo alternando vitórias entre órgãos/certames (grafo + janela temporal).",
          detectores=("J1",), redflags_lex=("R14",), fraudes=("bid_rigging_cartel",),
          dispositivos=("Lei 12.529/2011 art. 36 §3º I 'd'", "Lei 14.133/2021 art. 155"),
          escalada="representacao", origem=("casa", "OCDE")),
    Vicio("propostas_cobertura", "Propostas de cobertura", "julgamento",
          "Concorrentes-sombra com preços coordenados para simular disputa (screens CV/RD/skewness).",
          detectores=("J2",), redflags_lex=("R14",), escalada="representacao", origem=("casa", "OCDE")),
    Vicio("desconto_irrisorio", "Desconto irrisório recorrente", "julgamento",
          "Vencedor fecha rente ao teto estimado (<2%) sistematicamente — ausência de disputa real.",
          detectores=("J3",), teste_objetivo="desconto < 2% sem preço regulado (J3)",
          escalada="diligencia", origem=("casa", "OCDE")),
    Vicio("homologado_acima_estimado", "Homologação acima do orçamento estimado", "julgamento",
          "Proposta que permanece acima do estimado após negociação deve ser DESCLASSIFICADA (art. 59 III); "
          "homologar acima é violação objetiva.",
          detectores=("J3",), dispositivos=("Lei 14.133/2021 art. 59 III",),
          teste_objetivo="valor_homologado > valor_estimado → desconto negativo (J3)",
          escalada="representacao", origem=("redflags.eu",)),
    Vicio("licitante_unico_supressao", "Supressão de propostas / licitante único", "julgamento",
          "Menos de 3 propostas válidas ou licitante único recorrente no órgão/objeto (desistências suspeitas).",
          detectores=("J4",), redflags_lex=("R14",), escalada="diligencia",
          origem=("casa", "redflags.eu")),
    Vicio("digitais_compartilhadas", "Digitais compartilhadas entre licitantes", "julgamento",
          "Metadados de PDF, redação ou origem de envio idênticos entre propostas 'concorrentes'.",
          detectores=("J5",), redflags_lex=("R14",), escalada="representacao", origem=("casa", "ALICE/CGU")),
    Vicio("subcontratacao_cruzada", "Subcontratação cruzada / consórcio anômalo", "julgamento",
          "Perdedor vira subcontratado do vencedor (prêmio de conluio) ou consórcio junta quem deveria competir.",
          detectores=("J6",), escalada="diligencia", origem=("casa", "OCDE")),
    Vicio("inabilitacao_seletiva", "Inabilitação seletiva (dois pesos)", "julgamento",
          "Comissão inabilita entrantes por minúcia e releva falha igual do preferido (checklist D4/CGU).",
          detectores=("J7",), escalada="representacao", origem=("casa", "CGU")),
    Vicio("atestado_cruzado", "Atestado de capacidade emitido pelo próprio grupo", "julgamento",
          "Atestado técnico emitido por empresa do mesmo grupo econômico do licitante.",
          detectores=("J8",), escalada="diligencia", origem=("casa",)),
    Vicio("proposta_dia_nao_util", "Propostas registradas em dia não útil", "julgamento",
          "Propostas de 'concorrentes' cadastradas em fim de semana/feriado, em horários próximos — indício de "
          "operador único (trilha ALICE). Requer timestamps de envio — sem detector dedicado ainda.",
          escalada="diligencia", origem=("ALICE/CGU",), status="lacuna"),

    # ─────────────────────────── PERFIL DO CONTRATADO ───────────────────────────
    Vicio("empresa_fachada", "Empresa-fachada / laranja", "perfil_contratado",
          "CNPJ recém-nascido, estrutura/capital incompatível, CNAE divergente, QSA-laranja, reencarnação de "
          "sancionada (C1-C5) — perfil integrado com verificação de endereço e Static View.",
          detectores=("C",),
          redflags_lex=("DD/H-END-RESID", "DD/H-END-EXISTE", "DD/H-COEND", "DD/H-CAPITAL", "DD/H-RECENTE",
                        "DD/H-SITUACAO", "DD/H-PORTE", "DD/H-SOCIO-UNICO", "DD/H-BENEFICIO"),
          fraudes=("empresa_recente_grande_contrato",),
          dispositivos=("Lei 14.133/2021 art. 14", "Código Penal art. 337-F"),
          escalada="representacao", origem=("casa", "ALICE/CGU")),
    Vicio("cnae_incompativel", "CNAE incompatível com o objeto", "perfil_contratado",
          "Atividade-fim registrada diversa do objeto contratado (proxy de fachada/atravessador).",
          detectores=("C",), redflags_lex=("R11",),
          dispositivos=("Lei 14.133/2021 arts. 62-63",), escalada="diligencia", origem=("casa",)),
    Vicio("sancionada_contratada", "Sancionada contratada (à época)", "perfil_contratado",
          "Empresa com sanção vigente (CEIS/CNEP/inidôneos TCU) NA DATA do contrato/certame — cobertura via "
          "lex_sancoes + cruzamentos_intel (sancionadas estado/município), fora do REGISTRO.",
          dispositivos=("Lei 14.133/2021 art. 156 §§4º-5º", "Lei 14.133/2021 art. 14"),
          escalada="representacao", origem=("casa", "ALICE/CGU"), status="parcial"),
    Vicio("vinculo_politico", "Vínculo político-financeiro do fornecedor", "perfil_contratado",
          "Doações eleitorais/PEP no QSA correlacionadas com receita pública (grafo de poder).",
          detectores=("C6",), redflags_lex=("DD/H-PEP",),
          fraudes=("doacao_contrato_reciproco", "nomeacao_cargo_retribuicao"),
          dispositivos=("Lei 14.133/2021 art. 9º", "Lei 12.813/2013"),
          escalada="representacao", origem=("casa",)),
    Vicio("servidor_socio", "Servidor público no QSA de contratada", "perfil_contratado",
          "Agente público do órgão contratante como sócio/administrador da contratada (folha × QSA em "
          "cruzamentos_intel, corroboração por fragmento de CPF — fora do REGISTRO).",
          dispositivos=("Lei 14.133/2021 art. 14 I", "Lei 8.429/1992 art. 11"),
          escalada="representacao", origem=("casa", "CGU"), status="parcial"),

    # ─────────────────────────────── EXECUÇÃO ───────────────────────────────
    Vicio("aditivo_excessivo", "Crescimento aditivo acima dos limites", "execucao",
          "Acréscimos além de 25% (50% em reforma) ou sucessão de aditivos que desfigura o objeto licitado.",
          detectores=("X1",), redflags_lex=("R9",), fraudes=("aditivo_excessivo",),
          dispositivos=("Lei 14.133/2021 arts. 125-126",),
          teste_objetivo="Σ aditivos vs teto 25%/50% (X1)", escalada="representacao",
          origem=("casa", "claude-for-legal")),
    Vicio("prorrogacao_perpetua", "Prorrogação perpétua", "execucao",
          "Contrato renovado além do teto decenal ou sem demonstração de vantajosidade a cada prorrogação.",
          detectores=("X2",), dispositivos=("Lei 14.133/2021 art. 107",),
          teste_objetivo="vigência acumulada > 10 anos (X2)", escalada="diligencia", origem=("casa",)),
    Vicio("execucao_financeira_anomala", "Execução financeira anômala", "execucao",
          "Tríade empenho→liquidação→OB com estornos, OB R$ 0,00, liquidação sem lastro (só OB SIAFE = pago).",
          detectores=("X3",), redflags_lex=("R10",),
          dispositivos=("Lei 4.320/1964 arts. 62-63",), escalada="diligencia", origem=("casa",)),
    Vicio("carona_abusiva", "Carona abusiva em ata de registro de preços", "execucao",
          "Adesões além dos limites do art. 86 ou por órgãos sem pertinência com o objeto registrado.",
          detectores=("X4",), dispositivos=("Lei 14.133/2021 art. 86 §§3º-4º",),
          escalada="diligencia", origem=("casa",)),
    Vicio("jogo_planilha", "Jogo de planilha", "execucao",
          "Mergulho no certame recuperado por aditivos que engordam exatamente os itens subcotados.",
          detectores=("X5",), redflags_lex=("R13",),
          dispositivos=("Lei 14.133/2021 art. 125",), escalada="representacao", origem=("casa", "TCU")),
    Vicio("entrega_fantasma", "Entrega fantasma / atesto de fachada", "execucao",
          "Pagamento sem contraprestação verificável (medições sem prova, atesto genérico, foto reciclada).",
          detectores=("X6",), fraudes=("medicao_fraudulenta",),
          dispositivos=("Lei 4.320/1964 arts. 62-63", "Código Penal art. 337-L"),
          escalada="representacao", origem=("casa", "CGU")),
    Vicio("sub_rogacao_ilegal", "Sub-rogação/troca de controle pós-contrato", "execucao",
          "Contrato transferido de fato a terceiro (sub-rogação vedada) ou controle societário alterado após "
          "receita pública relevante (R6 no Lex — fora do REGISTRO).",
          redflags_lex=("R6",), fraudes=("sub_rogacao_ilegal",),
          dispositivos=("Lei 14.133/2021 art. 14",), escalada="diligencia",
          origem=("casa",), status="parcial"),
)

POR_ID: dict[str, Vicio] = {v.id: v for v in CATALOGO}


def obter(vicio_id: str) -> Vicio | None:
    return POR_ID.get(vicio_id)


def por_fase(fase: str) -> list[Vicio]:
    return [v for v in CATALOGO if v.fase == fase]


def por_detector(codigo: str) -> list[Vicio]:
    return [v for v in CATALOGO if codigo in v.detectores]


def por_clausula(tipo: str) -> list[Vicio]:
    return [v for v in CATALOGO if tipo in v.clausulas]


def lacunas() -> list[Vicio]:
    """Vícios catalogados sem cobertura plena — a lista HONESTA do que ainda não roda sozinho."""
    return [v for v in CATALOGO if v.status != "coberto"]


def resumo() -> dict:
    return {
        "total": len(CATALOGO),
        "por_fase": {f: len(por_fase(f)) for f in FASES},
        "cobertos": sum(1 for v in CATALOGO if v.status == "coberto"),
        "parciais": sum(1 for v in CATALOGO if v.status == "parcial"),
        "lacunas": sum(1 for v in CATALOGO if v.status == "lacuna"),
    }


def validar() -> list[str]:
    """Confere TODO ponteiro do catálogo contra os acervos reais. Lista vazia = íntegro.

    Imports tardios: mantém o módulo leve na importação e evita ciclo com lex_redflags."""
    problemas: list[str] = []
    from compliance_agent.detectores import REGISTRO
    from compliance_agent.knowledge.fraudes_licitacao import FRAUDES_POR_ID
    from compliance_agent.knowledge.jurisprudencia import INDICE_CLAUSULA, obter_sumula
    from compliance_agent.lex_redflags import _RF

    ids = [v.id for v in CATALOGO]
    for dup in {i for i in ids if ids.count(i) > 1}:
        problemas.append(f"id duplicado: {dup}")
    for v in CATALOGO:
        if v.fase not in FASES:
            problemas.append(f"{v.id}: fase desconhecida '{v.fase}'")
        if v.escalada not in ESCALADAS:
            problemas.append(f"{v.id}: escalada desconhecida '{v.escalada}'")
        if v.status not in ("coberto", "parcial", "lacuna"):
            problemas.append(f"{v.id}: status desconhecido '{v.status}'")
        if v.status == "coberto" and not v.detectores:
            problemas.append(f"{v.id}: status 'coberto' sem detector — rebaixar para parcial/lacuna")
        for d in v.detectores:
            if d not in REGISTRO:
                problemas.append(f"{v.id}: detector '{d}' não está no REGISTRO")
        for r in v.redflags_lex:
            if r not in _RF:
                problemas.append(f"{v.id}: red flag Lex '{r}' não existe em _RF")
        for fid in v.fraudes:
            if fid not in FRAUDES_POR_ID:
                problemas.append(f"{v.id}: padrão de fraude '{fid}' não existe em FRAUDES")
        for c in v.clausulas:
            if c not in INDICE_CLAUSULA:
                problemas.append(f"{v.id}: tipo de cláusula '{c}' não existe no INDICE_CLAUSULA")
        for s in v.sumulas:
            if obter_sumula(s) is None:
                problemas.append(f"{v.id}: súmula '{s}' não resolve em SUMULAS")
    return problemas
