# -*- coding: utf-8 -*-
"""
lex_sancoes — Instrumentalização da DOSIMETRIA DE SANÇÕES administrativas para o Lex.

Operacionaliza o "Manual para a Aplicação de Sanções nos casos de Inexecução Parcial
ou Total dos Contratos Administrativos" (PGE-RJ) e a Lei 14.133/2021 (regime atual do
JFN), cobrindo também o regime legado (Lei 8.666/93 + Lei 10.520/02), pois contratos
firmados sob a vigência da 8.666 ainda se regem por ela.

ÉTICA (igual ao resto do JFN/Lex): isto é uma PROPOSTA PRELIMINAR de enquadramento e
dosimetria — subsídio técnico ao gestor. NUNCA é decisão nem acusação. A sanção exige
processo administrativo com contraditório e ampla defesa, decisão motivada da
Autoridade Competente e é discricionária dentro da proporcionalidade (presunção de
regularidade dos atos administrativos).

Fontes: Lei 14.133/21 arts. 155-156; Lei 8.666/93 arts. 86-88; Lei 10.520/02 art. 7º;
Lei RJ 5.427/2009 arts. 70-72 (atenuantes/agravantes); LINDB (DL 4.657/42) art. 22 §2º;
Decreto RJ 3.149/1980 arts. 42, 86-87; CC art. 412 (teto da mora).
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Optional

# ──────────────────────────────────────────────────────────────────────────────
# 1. PARÂMETROS — taxonomia de sanções por regime
# ──────────────────────────────────────────────────────────────────────────────

# Gravidade canônica usada em todo o módulo (ordem crescente).
GRAVIDADES = ("leve", "media", "grave", "gravissima")
_PESO_GRAV = {"leve": 1, "media": 2, "grave": 3, "gravissima": 4}


@dataclass
class Sancao:
    codigo: str
    nome: str
    base_legal: str
    gravidade_minima: str          # gravidade a partir da qual costuma caber
    cumulavel_com_multa: bool      # multa é cumulável com as demais (8.666 art.87 §2º)
    prazo_min: Optional[str] = None
    prazo_max: Optional[str] = None
    exige_dolo: bool = False
    obs: str = ""


# Regime ATUAL — Lei 14.133/2021, art. 156
SANCOES_14133 = {
    "advertencia": Sancao(
        "advertencia", "Advertência", "Lei 14.133/21, art. 156, I",
        "leve", True, obs="Inexecução parcial de menor gravidade, sem justa causa."),
    "multa": Sancao(
        "multa", "Multa", "Lei 14.133/21, art. 156, II e §3º",
        "leve", True, prazo_min="0,5%", prazo_max="30%",
        obs="Não inferior a 0,5% nem superior a 30% do valor do contrato licitado/celebrado; "
            "cumulável com as demais sanções."),
    "impedimento": Sancao(
        "impedimento", "Impedimento de licitar e contratar",
        "Lei 14.133/21, art. 156, III e §4º",
        "grave", True, prazo_max="3 anos",
        obs="Âmbito do ente federativo que aplicou; até 3 anos; infrações dos incisos II a VII do art. 155."),
    "inidoneidade": Sancao(
        "inidoneidade", "Declaração de inidoneidade para licitar ou contratar",
        "Lei 14.133/21, art. 156, IV e §5º",
        "gravissima", True, prazo_min="3 anos", prazo_max="6 anos", exige_dolo=False,
        obs="Todos os entes; 3 a 6 anos; infrações dos incisos VIII a XII do art. 155 (as mais graves)."),
}

# Regime LEGADO — Lei 8.666/93 art. 87 + Lei 10.520/02 art. 7º + multa de mora
SANCOES_8666 = {
    "advertencia": Sancao(
        "advertencia", "Advertência", "Lei 8.666/93, art. 87, I",
        "leve", True, obs="Infrações leves; caráter educativo; sem prejuízo à execução."),
    "multa": Sancao(
        "multa", "Multa administrativa (punitiva)", "Lei 8.666/93, art. 87, II",
        "leve", True, prazo_max="20%",
        obs="Até 20% do valor do contrato/empenho (Decreto RJ 3.149/80 art. 87); proporcional às "
            "parcelas não executadas; dobra na reincidência específica; única cumulável (art. 87 §2º)."),
    "suspensao": Sancao(
        "suspensao", "Suspensão temporária + impedimento de contratar",
        "Lei 8.666/93, art. 87, III",
        "grave", True, prazo_max="2 anos",
        obs="Infração grave; até 2 anos; âmbito do órgão/Estado."),
    "inidoneidade": Sancao(
        "inidoneidade", "Declaração de inidoneidade",
        "Lei 8.666/93, art. 87, IV (e art. 88)",
        "gravissima", True, prazo_min="2 anos (reabilitação)", exige_dolo=False,
        obs="Infrações gravíssimas (conduta culposa/dolosa); sem prazo prefixado — perdura até "
            "reabilitação (mín. 2 anos) + ressarcimento; competência exclusiva do Secretário de Estado. "
            "Art. 88 (fraude fiscal dolosa, atos ilícitos) PRESSUPÕE dolo."),
}

# Pregão (Lei 10.520/02 art. 7º): sanção ÚNICA escolhida pelo legislador — se a conduta
# se enquadra aqui, NÃO se aplica o art. 87 da 8.666; só se dosa o PRAZO.
SANCAO_10520 = Sancao(
    "impedimento_pregao", "Impedimento de licitar e contratar + descredenciamento no Sicaf",
    "Lei 10.520/02, art. 7º", "grave", True, prazo_max="5 anos",
    obs="Pregão: impedimento de até 5 anos. Se a conduta se enquadra no art. 7º, a Autoridade "
        "NÃO pode aplicar o art. 87 da 8.666 — só dosa o prazo (proporcionalidade).")

# Multa de MORA (contratual, por atraso) — natureza distinta da multa punitiva.
MULTA_MORA = {
    "percentual_dia": 0.01,                 # 1% ao dia útil (Decreto RJ 3.149/80 art. 42; Lei RJ 287/77 art. 227)
    "por_dia_util": True,
    "base": "nota de empenho ou saldo não atendido",
    "teto": "valor da obrigação principal (CC art. 412)",
    "base_legal": "Lei 8.666/93 art. 86; Decreto RJ 3.149/80 art. 42",
    "cumulavel_com_multa_administrativa": True,   # art. 86 §1º / Lei RJ 287/77 art. 227 §2º
}

# ──────────────────────────────────────────────────────────────────────────────
# 2. PARÂMETROS — dosimetria (atenuantes / agravantes / fatores)
# ──────────────────────────────────────────────────────────────────────────────

# Fatores gerais (Lei RJ 5.427/09 art. 70 + LINDB art. 22 §2º)
FATORES_DOSIMETRIA = [
    "natureza e gravidade da infração",
    "prejuízos causados à Administração",
    "obrigação principal (objeto) vs. acessória",
    "antecedentes do infrator / reincidência",
    "situação econômica do infrator",
    "circunstâncias atenuantes e agravantes",
]

# Atenuantes — Lei RJ 5.427/09 art. 71 (sempre atenuam)
ATENUANTES = {
    "baixa_instrucao": "baixo grau de instrução ou escolaridade do infrator",
    "reparacao_espontanea": "reparação espontânea do dano ou sua limitação significativa",
    "comunicacao_previa": "comunicação prévia, pelo infrator, do risco de danos",
    "colaboracao": "colaboração com a fiscalização",
    "programa_integridade": "implementação/aperfeiçoamento de programa de integridade (Lei 14.133 art. 156 §1º V)",
}

# Agravantes — Lei RJ 5.427/09 art. 72 (sempre agravam, quando não qualificam a infração)
AGRAVANTES = {
    "reincidencia": "reincidência nas infrações",
    "ausencia_comunicacao": "ausência de comunicação do risco de danos",
    "vantagem_torpe": "infração para obter vantagem pecuniária ou por motivo torpe",
    "coacao": "coagir outrem para a execução material da infração",
    "dano_saude_ambiente": "expor a perigo, de modo grave, a saúde pública ou o meio ambiente",
    "dano_propriedade": "causar danos à propriedade alheia",
    "fraude_abuso_confianca": "mediante fraude ou abuso de confiança",
    "abuso_licenca": "mediante abuso de direito de licença/permissão/autorização",
    "interesse_verba_publica": "no interesse de PJ mantida por verbas públicas / incentivos fiscais",
}

# ──────────────────────────────────────────────────────────────────────────────
# 3. PARÂMETROS — processo (prazos, autoridade) — base PGE-RJ / Lei 8.666 art. 109
# ──────────────────────────────────────────────────────────────────────────────

PRAZOS_DEFESA = {  # dias ÚTEIS (exclui dia início, inclui vencimento; só dias com expediente)
    "advertencia": 5, "multa": 5, "suspensao": 5, "impedimento": 5, "impedimento_pregao": 5,
    "inidoneidade": 10,  # art. 87 §3º / Decreto RJ 3.149 art. 86 §6º
}
PRAZOS_RECURSO = {  # dias úteis (art. 109 Lei 8.666)
    "padrao": 5, "convite": 2, "reconsideracao_inidoneidade": 10,
}
AUTORIDADE_COMPETENTE = {
    "advertencia": "Ordenador de despesa do órgão/entidade",
    "multa": "Ordenador de despesa do órgão/entidade",
    "suspensao": "Ordenador de despesa, com ratificação do Secretário de Estado",
    "impedimento": "Ordenador de despesa, com ratificação do Secretário de Estado",
    "impedimento_pregao": "Ordenador de despesa, com apreciação do Secretário de Estado",
    "inidoneidade": "Secretário de Estado (competência EXCLUSIVA, indelegável)",
}
PROVIDENCIAS_POS_DECISAO = [
    "registro da penalidade no Cadastro de Fornecedores (SIGA)",
    "publicação do extrato no Diário Oficial (suspensão/impedimento/inidoneidade)",
    "comunicação à CGE para registro no CEIS (Cadastro Nacional de Empresas Inidôneas e Suspensas)",
    "cobrança da multa: garantia → retenção de créditos → notificação → dívida ativa/execução fiscal",
]

# ──────────────────────────────────────────────────────────────────────────────
# 4. MAPEAMENTO — red flags do Lex → gravidade/dolo presumidos
#    (heurística de PROPOSTA; o código do red flag (rf) vem dos achados do Lex)
# ──────────────────────────────────────────────────────────────────────────────
# Cada entrada: prefixo do rf -> (gravidade sugerida, indica_dolo, nota)
RF_PARA_GRAVIDADE = {
    "R3": ("media", False, "pesquisa de preços deficiente"),
    "R5": ("grave", False, "dispensa/inexigibilidade sem enquadramento sólido"),
    "R7": ("grave", False, "cláusula/edital restritivo da competição"),
    "R9": ("media", False, "aditivos acima do limite legal (>25% / >50% serviços)"),
    "FRAUDE": ("gravissima", True, "fraude/conluio — conduta dolosa"),
    "CARTEL": ("gravissima", True, "indício de cartel/conluio entre licitantes"),
}


def gravidade_do_rf(rf: str, grav_achado: str | None = None) -> tuple[str, bool, str]:
    """Resolve (gravidade, indica_dolo, nota) a partir do código do red flag do Lex.
    Se o achado já trouxer uma gravidade textual, ela prepondera."""
    rf = (rf or "").upper()
    for pref, val in RF_PARA_GRAVIDADE.items():
        if rf.startswith(pref):
            grav, dolo, nota = val
            break
    else:
        grav, dolo, nota = ("media", False, "indício a verificar")
    if grav_achado is not None and grav_achado != "":
        # o Lex usa grav INTEIRO (1=leve..4=gravissima); aceita também rótulos textuais
        if isinstance(grav_achado, (int, float)) or str(grav_achado).strip().isdigit():
            g = {1: "leve", 2: "media", 3: "grave", 4: "gravissima"}.get(int(grav_achado))
        else:
            g = str(grav_achado).strip().lower()
            g = {"alta": "grave", "alto": "grave", "média": "media", "médio": "media",
                 "baixa": "leve", "baixo": "leve", "extrema": "gravissima"}.get(g, g)
        if g in _PESO_GRAV:
            grav = g
    return grav, dolo, nota


# ──────────────────────────────────────────────────────────────────────────────
# 5. FUNÇÕES — dosimetria e cálculo
# ──────────────────────────────────────────────────────────────────────────────

def dosimetria(gravidade: str, atenuantes: list[str] | None = None,
               agravantes: list[str] | None = None, reincidencia: bool = False) -> dict:
    """Ajusta a gravidade pelo saldo de agravantes/atenuantes (não está adstrita à ordem do art. 87;
    o que determina a sanção é a gravidade proporcional). Retorna gravidade ajustada + fundamentos."""
    atenuantes = atenuantes or []
    agravantes = list(agravantes or [])
    if reincidencia and "reincidencia" not in agravantes:
        agravantes.append("reincidencia")
    base = _PESO_GRAV.get((gravidade or "media").lower(), 2)
    saldo = len(agravantes) - len(atenuantes)
    ajustado = max(1, min(4, base + (1 if saldo > 0 else -1 if saldo < 0 else 0)))
    grav_final = [k for k, v in _PESO_GRAV.items() if v == ajustado][0]
    return {
        "gravidade_base": gravidade,
        "gravidade_ajustada": grav_final,
        "atenuantes": [ATENUANTES.get(a, a) for a in atenuantes],
        "agravantes": [AGRAVANTES.get(a, a) for a in agravantes],
        "reincidencia": reincidencia,
        "fundamento": "Lei RJ 5.427/09 arts. 70-72; LINDB art. 22 §2º; proporcionalidade (CF art. 37).",
    }


def calcular_multa(valor_contrato: float, gravidade: str, regime: str = "14133",
                   parcelas_nao_executadas_pct: float = 1.0, reincidencia_especifica: bool = False) -> dict:
    """Calcula a multa punitiva proporcional à gravidade e às parcelas não executadas.
    regime: '14133' (0,5%–30%) ou '8666' (até 20%, dobra na reincidência específica)."""
    g = (gravidade or "media").lower()
    if regime == "8666":
        teto, piso = 0.20, 0.0
        # escala por gravidade dentro do teto de 20%
        pct = {"leve": 0.05, "media": 0.10, "grave": 0.15, "gravissima": 0.20}.get(g, 0.10)
        if reincidencia_especifica:
            pct = min(teto, pct * 2)            # dobra (art. 87 Decreto RJ 3.149/80)
        base_legal = SANCOES_8666["multa"].base_legal
    else:  # 14.133
        piso, teto = 0.005, 0.30
        pct = {"leve": 0.05, "media": 0.10, "grave": 0.20, "gravissima": 0.30}.get(g, 0.10)
        pct = max(piso, min(teto, pct))
        base_legal = SANCOES_14133["multa"].base_legal
    pct_efetivo = round(pct * max(0.0, min(1.0, parcelas_nao_executadas_pct)), 4)
    valor = round((valor_contrato or 0.0) * pct_efetivo, 2)
    return {
        "percentual": pct, "percentual_efetivo": pct_efetivo, "valor": valor,
        "teto": teto, "piso": piso, "base_legal": base_legal,
        "nota": "Proporcional às parcelas não executadas; cumulável com as demais sanções.",
    }


def calcular_multa_mora(base_empenho_ou_saldo: float, dias_uteis_atraso: int) -> dict:
    """Multa de mora 1%/dia útil sobre empenho/saldo, com teto no valor da obrigação principal (CC 412)."""
    bruto = round((base_empenho_ou_saldo or 0.0) * MULTA_MORA["percentual_dia"] * max(0, dias_uteis_atraso), 2)
    valor = min(bruto, round(base_empenho_ou_saldo or 0.0, 2))
    return {
        "percentual_dia": MULTA_MORA["percentual_dia"], "dias_uteis": max(0, dias_uteis_atraso),
        "valor_bruto": bruto, "valor": valor, "teto_aplicado": bruto > valor,
        "base_legal": MULTA_MORA["base_legal"],
        "nota": "Contratual (atraso); incentiva o cumprimento; cumulável com a multa punitiva; "
                "devida ainda que a obrigação seja cumprida depois.",
    }


def sancoes_aplicaveis(gravidade: str, regime: str = "14133", dolo: bool = False,
                       modalidade_pregao: bool = False) -> list[dict]:
    """Propõe as sanções compatíveis com a gravidade (proporcionalidade). A multa é sempre
    cumulável. No pregão (10.520), a sanção é única (impedimento ≤5a) — só dosa o prazo."""
    peso = _PESO_GRAV.get((gravidade or "media").lower(), 2)
    if regime == "8666" and modalidade_pregao:
        return [{**asdict(SANCAO_10520),
                 "motivo": "Conduta enquadrável no art. 7º da Lei 10.520/02 — afasta o art. 87 da 8.666."}]
    cat = SANCOES_14133 if regime != "8666" else SANCOES_8666
    out = []
    for s in cat.values():
        gmin = _PESO_GRAV.get(s.gravidade_minima, 1)
        if peso >= gmin or s.codigo == "multa":      # multa cabe sempre (cumulável)
            if s.exige_dolo and not dolo:
                continue
            out.append({**asdict(s), "compativel_com_gravidade": peso >= gmin})
    return out


def prazos(sancao_codigo: str, modalidade: str = "padrao") -> dict:
    rec = PRAZOS_RECURSO.get("convite" if modalidade == "convite" else "padrao")
    if sancao_codigo == "inidoneidade":
        rec = PRAZOS_RECURSO["reconsideracao_inidoneidade"]
    return {
        "defesa_dias_uteis": PRAZOS_DEFESA.get(sancao_codigo, 5),
        "recurso_dias_uteis": rec,
        "autoridade": AUTORIDADE_COMPETENTE.get(sancao_codigo, "Autoridade Competente (ordenador de despesa)"),
        "contagem": "exclui o dia do início, inclui o do vencimento; só dias com expediente (Lei 8.666 art. 110).",
    }


# ──────────────────────────────────────────────────────────────────────────────
# 6. ORQUESTRAÇÃO — proposta de sanções a partir dos achados do Lex
# ──────────────────────────────────────────────────────────────────────────────

def sugerir_sancoes(achados: list[dict], valor_contrato: float = 0.0, regime: str = "14133",
                    modalidade_pregao: bool = False, atenuantes: list[str] | None = None,
                    agravantes: list[str] | None = None, reincidencia: bool = False) -> dict:
    """Recebe os achados do Lex (cada um com {rf, obs, grav}) e devolve a PROPOSTA preliminar
    de enquadramento + dosimetria + sanções + multa + prazos. Subsídio técnico, não decisão."""
    achados = achados or []
    if not achados:
        return {"sem_achados": True,
                "nota": "Sem achados sancionáveis nos dados disponíveis. Presunção de regularidade."}
    # gravidade-mãe = a mais alta entre os achados; dolo se algum achado indicar
    gravs, dolo = [], False
    for a in achados:
        g, d, _ = gravidade_do_rf(a.get("rf", ""), a.get("grav"))
        gravs.append(g); dolo = dolo or d
    gravidade = max(gravs, key=lambda g: _PESO_GRAV.get(g, 2))
    dose = dosimetria(gravidade, atenuantes, agravantes, reincidencia)
    grav_final = dose["gravidade_ajustada"]
    # Calibração conservadora: a inidoneidade (gravíssima) é reservada às condutas mais
    # graves, em regra DOLOSAS (14.133 art. 155, VIII-XII; 8.666 art. 88). Sem dolo
    # indiciado, não escala além de "grave" — evita propor inidoneidade por mero somatório
    # de agravantes culposos. Proporcionalidade (CF art. 37).
    if grav_final == "gravissima" and not dolo:
        grav_final = "grave"
        dose["gravidade_ajustada"] = "grave"
        dose["cap_sem_dolo"] = ("gravíssima rebaixada para grave: inidoneidade pressupõe dolo "
                                "(14.133 art. 155 VIII-XII / 8.666 art. 88).")
    sancoes = sancoes_aplicaveis(grav_final, regime, dolo, modalidade_pregao)
    multa = calcular_multa(valor_contrato, grav_final, regime,
                           reincidencia_especifica=reincidencia) if valor_contrato else None
    principal = next((s for s in sancoes if s["codigo"] != "multa"), sancoes[0] if sancoes else None)
    return {
        "regime": regime, "gravidade": grav_final, "dolo": dolo,
        "dosimetria": dose, "sancoes_propostas": sancoes,
        "sancao_principal": principal["codigo"] if principal else None,
        "multa": multa,
        "prazos": prazos(principal["codigo"], "padrao") if principal else None,
        "providencias": PROVIDENCIAS_POS_DECISAO,
    }


def parecer_sancionatorio_md(proposta: dict) -> str:
    """Renderiza a proposta de sanções como bloco Markdown para o parecer do Lex (seção II-C),
    no padrão estético/ético do JFN (🟢🟡🔴, indício/proposta, nunca acusação)."""
    L: list[str] = []
    add = L.append
    add("## IV-C. PROPOSTA PRELIMINAR DE SANÇÃO ADMINISTRATIVA (dosimetria)")
    add("")
    add("> Subsídio técnico ao gestor com base no Manual de Sanções da PGE-RJ e na Lei 14.133/21. "
        "**Não é decisão nem acusação** — a sanção exige processo com contraditório, ampla defesa e "
        "decisão motivada da Autoridade Competente (presunção de regularidade dos atos administrativos).")
    add("")
    if proposta.get("sem_achados"):
        add(f"_{proposta['nota']}_")
        return "\n".join(L)
    g = proposta["gravidade"]
    emoji = {"leve": "🟢", "media": "🟡", "grave": "🔴", "gravissima": "🔴"}.get(g, "🟡")
    add(f"**Gravidade ajustada:** {emoji} {g.upper()} · **Dolo indiciado:** {'sim' if proposta['dolo'] else 'não'} · "
        f"**Regime:** Lei {'14.133/21' if proposta['regime'] != '8666' else '8.666/93 + 10.520/02'}")
    d = proposta["dosimetria"]
    if d["agravantes"]:
        add(f"- **Agravantes:** {'; '.join(d['agravantes'])}")
    if d["atenuantes"]:
        add(f"- **Atenuantes:** {'; '.join(d['atenuantes'])}")
    add(f"- **Fundamento da dosimetria:** {d['fundamento']}")
    add("")
    add("**Sanções compatíveis (proporcionalidade — não vinculam a ordem legal):**")
    add("")
    add("| Sanção | Base legal | Prazo/limite | Cumulável c/ multa |")
    add("|---|---|---|:---:|")
    for s in proposta["sancoes_propostas"]:
        lim = s.get("prazo_max") or s.get("prazo_min") or "—"
        add(f"| {s['nome']} | {s['base_legal']} | {lim} | {'sim' if s['cumulavel_com_multa'] else '—'} |")
    add("")
    m = proposta.get("multa")
    if m:
        add(f"**Multa estimada:** {m['percentual_efetivo']*100:.1f}% → R$ {m['valor']:,.2f} "
            f"(teto {m['teto']*100:.0f}%; {m['base_legal']}). {m['nota']}")
        add("")
    pr = proposta.get("prazos")
    if pr:
        add(f"**Processo:** defesa {pr['defesa_dias_uteis']} dias úteis · recurso {pr['recurso_dias_uteis']} dias úteis · "
            f"autoridade: {pr['autoridade']}.")
        add("")
    add("**Providências pós-decisão:** " + "; ".join(proposta["providencias"]) + ".")
    return "\n".join(L)


if __name__ == "__main__":
    import json
    # Demo: achados típicos do Lex (dispensa frágil + aditivo + restrição) sobre contrato de R$ 2,4 mi
    demo = [
        {"rf": "R5", "obs": "Dispensa de licitação sem 3 cotações comprovadas", "grav": "alta"},
        {"rf": "R9", "obs": "Aditivos somando 41% do valor original", "grav": "média"},
        {"rf": "R7", "obs": "Exigência de atestado restritiva da competição", "grav": "alta"},
    ]
    prop = sugerir_sancoes(demo, valor_contrato=2_400_000.0, regime="14133",
                           agravantes=["interesse_verba_publica"], reincidencia=False)
    print(json.dumps(prop, ensure_ascii=False, indent=2, default=str))
    print("\n" + "=" * 70 + "\n")
    print(parecer_sancionatorio_md(prop))
