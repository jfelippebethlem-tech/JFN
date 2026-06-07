# -*- coding: utf-8 -*-
"""
lex_indicadores_fraude — Catálogo de INDICADORES DE RISCO DE FRAUDE em licitações,
para triagem automatizada pelo Lex/JFN.

Codifica a metodologia de "Indicadores de risco de fraude em licitações" (Bianca Vaz
Mondo) — material de detecção de fraude e corrupção em contratações públicas (PDF na
base do Lex). Os indicadores são organizados por FASE (interna/externa) e por ESCOPO
(uma licitação isolada × o conjunto de contratações de um órgão). A presença de um ou
mais indicadores serve para TRIAGEM: os procedimentos sinalizados passam por técnicas
adicionais de detecção.

ÉTICA (padrão JFN/Lex): indicador é INDÍCIO para priorização/diligência — NUNCA prova
nem acusação. A confirmação exige exame documental e contraditório (presunção de
regularidade dos atos administrativos). Liga-se a [[lex_sancoes]] (dosimetria) e ao
módulo de anomalias/red flags do JFN.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict, field

# ── Tipologias de fraude (taxonomia do material) ──────────────────────────────
TIPOS_FRAUDE = {
    "projeto_magico": "Projeto/TR moldado para um resultado/fornecedor predefinido",
    "edital_restritivo": "Cláusulas/exigências que restringem indevidamente a competição",
    "julgamento_negligente": "Julgamento negligente ou conivente (habilitação/inabilitação indevida)",
    "publicidade_precaria": "Publicidade precária — prazo exíguo/divulgação restrita",
    "contratacao_direta_indevida": "Dispensa/inexigibilidade/convite sem enquadramento legal",
    "fracionamento": "Fracionamento de despesa para fugir de modalidade mais competitiva",
    "conluio": "Conluio entre licitantes (combinação de propostas/resultados)",
    "cartel": "Cartel/rodízio (bid rigging) — divisão de mercado entre players",
    "empresa_fantasma": "Empresa fantasma/de fachada usada para simular competitividade",
    "sobrepreco": "Sobrepreço/superfaturamento frente ao valor de mercado",
}

# Faixas de risco da triagem
FAIXAS = [(0, "🟢 BAIXO"), (2, "🟡 MÉDIO"), (4, "🔴 ALTO")]


@dataclass
class Indicador:
    id: str
    descricao: str
    fase: str                 # "interna" | "externa" | "—"
    escopo: str               # "licitacao" | "conjunto"
    tipos: list[str]          # tipologias de TIPOS_FRAUDE
    peso: int                 # contribuição ao score de risco (1=leve..3=forte)
    rf: str = ""              # red flag JFN correlato (R3/R5/R7/R8/R9...)
    como_detectar: str = ""


# ── CATÁLOGO — indicadores por fase/escopo (fielmente do material) ────────────
INDICADORES: list[Indicador] = [
    # — Licitação isolada / fase interna —
    Indicador("CONTRAT_DIRETA", "Contratação sem licitação ou de baixa competitividade "
              "(dispensa, inexigibilidade, convite)", "interna", "licitacao",
              ["contratacao_direta_indevida", "projeto_magico"], 2, "R5",
              "Conferir o enquadramento legal (Lei 14.133 arts. 74-75) e a justificativa."),
    Indicador("VALOR_PROX_LIMITE", "Valor estimado muito próximo ao limite da modalidade adotada",
              "interna", "licitacao", ["fracionamento", "projeto_magico"], 2, "R9",
              "Comparar o estimado com o teto da modalidade; buscar objetos semelhantes no exercício."),
    Indicador("EDITAL_RESTRITIVO", "Edital/TR com indícios de direcionamento ou cláusulas restritivas",
              "interna", "licitacao", ["edital_restritivo", "projeto_magico"], 3, "R7",
              "Checar exigências de habilitação desproporcionais, marca, atestados restritivos."),
    Indicador("PUBLICIDADE_PRECARIA", "Prazo de publicidade exíguo e/ou publicação restrita",
              "interna", "licitacao", ["publicidade_precaria"], 2, "",
              "Verificar prazos mínimos legais e os meios de divulgação (PNCP obrigatório)."),
    # — Licitação isolada / fase externa —
    Indicador("ESCASSEZ_LICITANTES", "Escassez de licitantes e fraca disputa",
              "externa", "licitacao", ["edital_restritivo", "conluio", "projeto_magico"], 2, "",
              "Nº de propostas válidas; deságio total; comparar com certames similares."),
    Indicador("INABILITACAO_INDEVIDA", "Inabilitações em desacordo com o edital ou por excessiva formalidade",
              "externa", "licitacao", ["julgamento_negligente", "edital_restritivo"], 2, "",
              "Reexaminar atas de habilitação: formalismo excessivo eliminando concorrentes."),
    Indicador("DESCONTO_ATIPICO", "Desconto atípico (excessivamente baixo OU alto) frente ao valor estimado",
              "externa", "licitacao", ["sobrepreco", "projeto_magico", "julgamento_negligente"], 2, "R3",
              "Deságio fora da curva sugere sobrepreço no estimado ou proposta-isca."),
    Indicador("VENCEDOR_ME_EPP", "Licitação exclusiva/vencida por ME ou EPP com sinais de abuso do benefício",
              "externa", "licitacao", ["empresa_fantasma"], 1, "",
              "Cruzar porte declarado × capacidade real; uso de ME/EPP por grupo de médio/grande porte."),
    # — Conjunto de contratações do órgão —
    Indicador("CONCENTRACAO", "Concentração de contratos em um ou poucos fornecedores",
              "—", "conjunto", ["cartel", "edital_restritivo"], 2, "",
              "HHI por fornecedor/órgão; participação do maior favorecido (red flag ACFE ≥60%)."),
    Indicador("PERDEDORES_RECORRENTES", "Perdedores recorrentes — mesmo grupo participa e sempre perde",
              "—", "conjunto", ["empresa_fantasma", "conluio"], 3, "R8",
              "Padrão de empresas que dão aparência de disputa mas nunca vencem."),
    Indicador("COINCIDENCIA_PARTICIPANTES", "Coincidência de participantes em várias licitações",
              "—", "conjunto", ["cartel", "conluio"], 3, "R8",
              "Mesma cesta de licitantes co-ocorrendo; cruzar sócios/endereços (laranjas)."),
    Indicador("FRACIONAMENTO_SERIE", "Múltiplas contratações de objeto semelhante no exercício, "
              "somando acima do limite da modalidade", "—", "conjunto", ["fracionamento"], 3, "R9",
              "Somar contratações do mesmo objeto/órgão no ano vs. teto (Lei 14.133 art. 75 §1º)."),
]

_IDX = {i.id: i for i in INDICADORES}

# Técnicas de detecção sugeridas após a triagem (Parte III do material)
TECNICAS_DETECCAO = [
    "Monitoramento de processos com base em indicadores de risco",
    "Análise documental do edital/TR (especificações × restrição)",
    "Pesquisa de preços independente (cesta — Acórdão 1875/2021-TCU)",
    "Cruzamento societário e de endereços dos licitantes (laranjas/empresas-irmãs)",
    "Análise de rede de co-ocorrência entre participantes (cartel/rodízio)",
    "Pedidos via Lei de Acesso à Informação (LAI) para suprir lacunas documentais",
]


# ── FUNÇÕES ───────────────────────────────────────────────────────────────────

def _faixa(score: int) -> str:
    rot = FAIXAS[0][1]
    for limite, r in FAIXAS:
        if score >= limite:
            rot = r
    return rot


def triagem(sinais: dict) -> dict:
    """Aplica o catálogo a um conjunto de SINAIS observáveis e devolve os indicadores
    disparados + score de risco + tipologias + técnicas recomendadas.

    `sinais` aceita chaves (todas opcionais, derivadas dos dados que o JFN já tem):
      contratacao_direta(bool), valor_prox_limite(bool), edital_restritivo(bool),
      publicidade_precaria(bool), poucos_licitantes(bool), inabilitacao_indevida(bool),
      desconto_atipico(bool), abuso_me_epp(bool), concentracao_alta(bool),
      perdedores_recorrentes(bool), coincidencia_participantes(bool), fracionamento(bool).
    """
    mapa = {
        "contratacao_direta": "CONTRAT_DIRETA", "valor_prox_limite": "VALOR_PROX_LIMITE",
        "edital_restritivo": "EDITAL_RESTRITIVO", "publicidade_precaria": "PUBLICIDADE_PRECARIA",
        "poucos_licitantes": "ESCASSEZ_LICITANTES", "inabilitacao_indevida": "INABILITACAO_INDEVIDA",
        "desconto_atipico": "DESCONTO_ATIPICO", "abuso_me_epp": "VENCEDOR_ME_EPP",
        "concentracao_alta": "CONCENTRACAO", "perdedores_recorrentes": "PERDEDORES_RECORRENTES",
        "coincidencia_participantes": "COINCIDENCIA_PARTICIPANTES", "fracionamento": "FRACIONAMENTO_SERIE",
    }
    disparados, tipos, score = [], set(), 0
    for chave, ind_id in mapa.items():
        if sinais.get(chave):
            ind = _IDX[ind_id]
            disparados.append(ind)
            score += ind.peso
            tipos.update(ind.tipos)
    return {
        "n_indicadores": len(disparados),
        "score_risco": score,
        "faixa": _faixa(score),
        "indicadores": [asdict(i) for i in disparados],
        "tipologias": sorted(tipos),
        "tecnicas_recomendadas": TECNICAS_DETECCAO if disparados else [],
        "nota": "Triagem por indicadores — INDÍCIO para priorização/diligência, nunca prova ou acusação.",
    }


def sinais_do_contexto(ctx: dict, analise: dict | None = None) -> dict:
    """Deriva os sinais da triagem a partir do contexto/análise que o JFN já monta
    (HHI de concentração, dispensas TCE-RJ, red flags do Lex). Best-effort."""
    sinais: dict = {}
    p = (ctx or {}).get("pagamentos") or {}
    hhi = p.get("hhi") or {}
    if (hhi.get("top_share") or 0) >= 60:
        sinais["concentracao_alta"] = True
    tcerj = (analise or {}).get("tcerj") or {}
    if (tcerj.get("n_diretas_dispensa") or 0) > 0:
        sinais["contratacao_direta"] = True
    # red flags já detectados pelo Lex → sinais correlatos
    rfs = {str(a.get("rf", "")).upper() for a in (analise or {}).get("achados", [])}
    if any(r.startswith("R7") for r in rfs):
        sinais["edital_restritivo"] = True
    if any(r.startswith("R9") for r in rfs):
        sinais["fracionamento"] = True
    if any(r.startswith("R8") for r in rfs):
        sinais["coincidencia_participantes"] = True
    if any(r.startswith("R3") for r in rfs):
        sinais["desconto_atipico"] = True
    return sinais


def parecer_indicadores_md(resultado: dict) -> str:
    """Renderiza a triagem como bloco Markdown para o parecer do Lex (seção III-C)."""
    L: list[str] = []
    add = L.append
    add("## III-C. TRIAGEM POR INDICADORES DE RISCO DE FRAUDE")
    add("")
    add("> Metodologia de indicadores de risco em licitações (B. V. Mondo). "
        "**Indício para priorização/diligência — nunca prova nem acusação.**")
    add("")
    if not resultado.get("indicadores"):
        add("_Nenhum indicador de risco disparado a partir dos dados disponíveis._")
        return "\n".join(L)
    add(f"**Risco de triagem:** {resultado['faixa']} (score {resultado['score_risco']}; "
        f"{resultado['n_indicadores']} indicador(es)). "
        f"**Tipologias associadas:** {', '.join(TIPOS_FRAUDE.get(t, t) for t in resultado['tipologias'])}.")
    add("")
    add("| Indicador | Fase | Escopo | Tipologia | RF |")
    add("|---|---|---|---|---|")
    for i in resultado["indicadores"]:
        tip = ", ".join(i["tipos"][:2])
        add(f"| {i['descricao']} | {i['fase']} | {i['escopo']} | {tip} | {i['rf'] or '—'} |")
    add("")
    add("**Técnicas de detecção recomendadas:** " + "; ".join(resultado["tecnicas_recomendadas"]) + ".")
    return "\n".join(L)


if __name__ == "__main__":
    import json
    demo = {"contratacao_direta": True, "edital_restritivo": True,
            "concentracao_alta": True, "coincidencia_participantes": True}
    r = triagem(demo)
    print(json.dumps(r, ensure_ascii=False, indent=2))
    print("\n" + "=" * 70 + "\n")
    print(parecer_indicadores_md(r))
