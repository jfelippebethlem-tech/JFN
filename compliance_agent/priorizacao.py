# -*- coding: utf-8 -*-
"""
Priorização de achados — SEGUNDO eixo do scoring (playbook do dono).

O JFN já calcula o **risco de ACHADO** (probabilidade de a irregularidade ser real —
nº + convergência de flags + cruzamento confirmatório; `investigacao_dd.investigar` → score/grau).
Este módulo acrescenta o eixo INDEPENDENTE que faltava (manual, seção "Scoring (2 eixos)"):

  **Risco de PUNIÇÃO** = viabilidade de responsabilização, 0-100, a partir de
    • materialidade   — o VALOR em jogo (`total_pago`, em faixas; OB = pagamento = verdade)
    • tipificação     — cada família de achado mapeia (ou não) numa norma → enquadramento claro
    • autoria         — há pessoa/empresa identificável (CNPJ/CPF/sócio) a responsabilizar?
    • competência     — para qual instância roteia (TCE / MP / CADE / CGE-CGU)

Filosofia de honestidade (CLAUDE.md §6 / regra-mãe do `investigacao_dd`):
  INDISPONÍVEL ≠ 0. Quando um componente não pode ser avaliado (sem dado), ele NÃO entra
  na média — não infla nem desinfla o score. O score é a média dos componentes DISPONÍVEIS.
  Nada é inventado: tipificação/competência saem de um mapa explícito família→norma; se a
  família é desconhecida, o componente fica INDISPONÍVEL (não "limpo", não "grave").

Uso (puro, sem rede, sem DB):
    >>> rp = risco_punicao(achados, total_pago=2_000_000.0)
    >>> quadrante(risco_achado=72.0, risco_punicao=rp["score"])
    'alto-alto'   # PRIORITÁRIO — o manual manda atacar este quadrante primeiro

Base legal do mapa de tipificação (manual JFN):
  Lei 14.133/2021 · 8.429/1992 (improbidade) · 12.846/2013 (anticorrupção/PAR) ·
  12.529/2011 (CADE/cartel) · CP arts. 337-E a 337-P (fraude a licitação; 337-F = conluio).
"""
from __future__ import annotations

import re

# ───────────────────────── tipificação: família de achado → norma + competência ─────────────────────────
# Cada entrada: codigo/família → {norma, competencia, forca}.
#   forca: peso da tipificação (0-100) — quão claro/forte é o enquadramento dessa família.
#   competencia: para onde rotear (manual, seção "Enquadramento / destinatário").
# Famílias derivam dos códigos H-* emitidos por investigacao_dd + as 3 famílias do manual
# (conluio/cartel, direcionamento/fachada, superfaturamento).
_TIPIFICACAO: dict[str, dict] = {
    # ── CONLUIO / CARTEL (sócios em comum, rodízio de vencedores) → MP + CADE ──
    "conluio":       {"norma": "CP art. 337-F + Lei 12.529/2011 (cartel)", "competencia": "MP + CADE", "forca": 90},
    "cartel":        {"norma": "Lei 12.529/2011 (infração à ordem econômica)", "competencia": "CADE + MP", "forca": 90},
    "rodizio":       {"norma": "CP art. 337-F (frustração do caráter competitivo)", "competencia": "MP + CADE", "forca": 85},
    "concentracao":  {"norma": "CP art. 337-F + Lei 12.529/2011 (cartel)", "competencia": "MP + CADE", "forca": 85},
    # ── DIRECIONAMENTO / FACHADA / LARANJA → improbidade (MP) + débito (TCE) ──
    "fachada":       {"norma": "Lei 8.429/1992 art. 10 (dano ao erário) + CP 337-F", "competencia": "MP + TCE-RJ", "forca": 75},
    "laranja":       {"norma": "Lei 8.429/1992 (improbidade) — interposição de pessoas", "competencia": "MP + TCE-RJ", "forca": 75},
    "direcionamento": {"norma": "Lei 14.133/2021 + CP art. 337-E (frustrar licitação)", "competencia": "MP + TCE-RJ", "forca": 70},
    # ── SUPERFATURAMENTO / SOBREPREÇO → dano ao erário (TCE débito) + improbidade ──
    "sobrepreco":    {"norma": "Lei 8.429/1992 art. 10 (dano ao erário)", "competencia": "TCE-RJ (débito) + MP", "forca": 80},
    "superfaturamento": {"norma": "Lei 8.429/1992 art. 10 (dano ao erário)", "competencia": "TCE-RJ (débito) + MP", "forca": 80},
    "sobrepreço":    {"norma": "Lei 8.429/1992 art. 10 (dano ao erário)", "competencia": "TCE-RJ (débito) + MP", "forca": 80},
    # ── sanção/reencarnação (contratar empresa inidônea) → PAR + TCE ──
    "sancao":        {"norma": "Lei 14.133/2021 art. 156 + Lei 12.846/2013 (PAR)", "competencia": "CGE-CGU + TCE-RJ", "forca": 70},
    "reencarnacao":  {"norma": "Lei 14.133/2021 (burla a sanção)", "competencia": "CGE-CGU + TCE-RJ", "forca": 65},
    # ── conflito de interesse / nepotismo / PEP → improbidade ──
    "conflito":      {"norma": "Lei 8.429/1992 + Lei 12.813/2013 (conflito de interesses)", "competencia": "MP + TCE-RJ", "forca": 70},
    "pep":           {"norma": "Lei 8.429/1992 (improbidade) — relação política", "competencia": "MP + TCE-RJ", "forca": 50},
    # ── teto / supersalário → administrativo ──
    "teto":          {"norma": "CF art. 37, XI (teto remuneratório)", "competencia": "TCE-RJ + órgão", "forca": 55},
    "acumulo":       {"norma": "CF art. 37, XVI/XVII (acumulação de cargos)", "competencia": "TCE-RJ + órgão", "forca": 55},
}

# Mapa de prefixo de código H-* (investigacao_dd) → família canônica acima.
_CODIGO_FAMILIA: dict[str, str] = {
    "H-END-RESID": "fachada", "H-END-EXISTE": "fachada", "H-COEND": "fachada",
    "H-CAPITAL": "fachada", "H-RECENTE": "fachada", "H-PORTE": "fachada",
    "H-SITUACAO": "reencarnacao", "H-SOCIO-UNICO": "laranja",
    "H-PEP": "pep", "H-BENEFICIO": "laranja",
    "H-CARTEL": "conluio", "H-CONLUIO": "conluio", "H-RODIZIO": "rodizio",
    "H-CONCENTRACAO": "concentracao", "H-SOBREPRECO": "sobrepreco",
    "H-CONFLITO": "conflito", "H-SANCAO": "sancao", "H-TETO": "teto", "H-ACUMULO": "acumulo",
}

# ───────────────────────── materialidade: faixas de valor (R$) ─────────────────────────
# Quanto maior o valor em jogo, maior a viabilidade/prioridade da responsabilização (e o
# interesse do controle externo). Faixas conservadoras; OB = pagamento (CLAUDE.md §2).
_FAIXAS_MATERIALIDADE: list[tuple[float, int, str]] = [
    (50_000_000, 100, "≥ R$ 50 mi — materialidade altíssima"),
    (10_000_000, 90, "≥ R$ 10 mi — materialidade muito alta"),
    (1_000_000, 75, "≥ R$ 1 mi — materialidade alta"),
    (250_000, 55, "≥ R$ 250 mil — materialidade relevante"),
    (50_000, 35, "≥ R$ 50 mil — materialidade moderada"),
    (0, 15, "< R$ 50 mil — materialidade baixa"),
]

_INDISPONIVEL = "INDISPONIVEL"

# pesos relativos dos componentes (re-normalizados só sobre os DISPONÍVEIS)
_PESOS = {"materialidade": 0.30, "tipificacao": 0.30, "autoria": 0.20, "competencia": 0.20}


# ───────────────────────── helpers ─────────────────────────

def _digitos(s) -> str:
    return re.sub(r"\D", "", str(s or ""))


def _num(v) -> float | None:
    try:
        if v is None or v == "":
            return None
        return float(str(v).replace(".", "").replace(",", ".")) if isinstance(v, str) else float(v)
    except (TypeError, ValueError):
        return None


def _familia_do_achado(a: dict) -> str | None:
    """Família canônica de um achado: usa `familia` explícita, senão deriva do `codigo` H-*."""
    fam = str(a.get("familia") or "").strip().lower()
    if fam:
        return fam
    cod = str(a.get("codigo") or "").strip().upper()
    if cod in _CODIGO_FAMILIA:
        return _CODIGO_FAMILIA[cod]
    # tenta casar pelo prefixo (H-CAPITAL-X → H-CAPITAL)
    for pref, f in _CODIGO_FAMILIA.items():
        if cod.startswith(pref):
            return f
    return None


def _tem_autoria(a: dict) -> bool:
    """Há identificação de quem responsabilizar (CNPJ/CPF/sócio) no achado?"""
    for chave in ("cnpj", "cpf", "documento", "doc"):
        if len(_digitos(a.get(chave))) in (11, 14):
            return True
    socios = a.get("socios") or a.get("socio")
    if socios:
        return True
    # alguns achados carregam a autoria dentro de `evidencia`/`autor`
    if str(a.get("autor") or "").strip():
        return True
    return False


# ───────────────────────── componentes ─────────────────────────

def _comp_materialidade(total_pago) -> dict:
    valor = _num(total_pago)
    if valor is None or valor < 0:
        return {"score": _INDISPONIVEL, "nota": "valor (total pago) indisponível — não computado"}
    for piso, score, nota in _FAIXAS_MATERIALIDADE:
        if valor >= piso:
            return {"score": score, "nota": nota, "valor": valor}
    return {"score": 15, "nota": "materialidade baixa", "valor": valor}


def _comp_tipificacao(achados: list[dict]) -> dict:
    """Maior força de tipificação entre as famílias reconhecidas dos achados."""
    reconhecidas: list[tuple[str, dict]] = []
    desconhecidas = 0
    for a in achados:
        fam = _familia_do_achado(a)
        if fam and fam in _TIPIFICACAO:
            reconhecidas.append((fam, _TIPIFICACAO[fam]))
        else:
            desconhecidas += 1
    if not reconhecidas:
        return {"score": _INDISPONIVEL,
                "nota": "nenhuma família de achado mapeável a norma — tipificação indisponível",
                "normas": []}
    # o enquadramento mais forte governa (basta UMA tipificação clara para responsabilizar)
    fam, melhor = max(reconhecidas, key=lambda x: x[1]["forca"])
    normas = sorted({t["norma"] for _, t in reconhecidas})
    return {"score": melhor["forca"], "nota": f"{fam} → {melhor['norma']}",
            "normas": normas, "familia_dominante": fam}


def _comp_autoria(achados: list[dict]) -> dict:
    if not achados:
        return {"score": _INDISPONIVEL, "nota": "sem achados — autoria indisponível"}
    n_com = sum(1 for a in achados if _tem_autoria(a))
    if n_com == 0:
        # honestidade: ausência de identificação no payload ≠ "não há autor" — fica INDISPONÍVEL
        return {"score": _INDISPONIVEL,
                "nota": "nenhum achado traz CNPJ/CPF/sócio — autoria não identificável no dado"}
    frac = n_com / len(achados)
    score = round(40 + 60 * frac)  # ≥1 identificável já vale; cobre todos → 100
    return {"score": score, "nota": f"{n_com}/{len(achados)} achados com autoria identificável"}


def _comp_competencia(tip: dict) -> dict:
    """Competência deriva da tipificação: se há norma clara, há instância para a qual rotear."""
    if tip.get("score") == _INDISPONIVEL:
        return {"score": _INDISPONIVEL, "nota": "sem tipificação — competência indeterminada", "destinatarios": []}
    fam = tip.get("familia_dominante")
    dest = _TIPIFICACAO.get(fam, {}).get("competencia", "")
    # forum múltiplo (ex.: "MP + CADE") = caminho de responsabilização robusto → score cheio
    n_foros = len([p for p in re.split(r"[+/]", dest) if p.strip()])
    score = 100 if n_foros >= 2 else (75 if n_foros == 1 else _INDISPONIVEL)
    return {"score": score, "nota": dest or "indeterminada",
            "destinatarios": [p.strip() for p in re.split(r"[+/]", dest) if p.strip()]}


# ───────────────────────── API pública ─────────────────────────

def risco_punicao(achados, total_pago, *, prescricao_anos=None) -> dict:
    """
    Risco de PUNIÇÃO (viabilidade de responsabilização), 0-100.

    Args:
        achados: lista de dicts (achados/hipóteses), cada um com pelo menos `codigo` ou `familia`,
                 e opcionalmente `cnpj`/`cpf`/`socios` (autoria). Aceita o formato de
                 `investigacao_dd.investigar()["hipoteses"]`.
        total_pago: valor pago (R$, OB) — base da materialidade. None/ausente → INDISPONÍVEL.
        prescricao_anos: (opcional) anos restantes até a prescrição. Se informado e ≤0, sinaliza
                 prescrição consumada (penaliza o score como TETO=0); se >0 ou None, não penaliza
                 (sem dado de prazo ≠ prescrito — honestidade).

    Returns:
        {score, materialidade, tipificacao, autoria, competencia, prescricao, nota, cobertura}
        Componentes INDISPONÍVEIS não entram na média (não inflam/desinflam o score).
    """
    achados = list(achados or [])

    materialidade = _comp_materialidade(total_pago)
    tipificacao = _comp_tipificacao(achados)
    autoria = _comp_autoria(achados)
    competencia = _comp_competencia(tipificacao)

    componentes = {
        "materialidade": materialidade,
        "tipificacao": tipificacao,
        "autoria": autoria,
        "competencia": competencia,
    }

    # média ponderada SÓ sobre os disponíveis (re-normaliza os pesos)
    disp = {k: c for k, c in componentes.items() if c["score"] != _INDISPONIVEL}
    if not disp:
        score: float = 0.0
        cobertura = "0/4 componentes — score INDISPONÍVEL (sem base p/ priorizar punição)"
    else:
        peso_total = sum(_PESOS[k] for k in disp)
        score = sum(_PESOS[k] * disp[k]["score"] for k in disp) / peso_total
        cobertura = f"{len(disp)}/4 componentes avaliados"

    # prescrição: só penaliza se houver DADO afirmativo de prazo esgotado (honestidade)
    prescricao = {"score": _INDISPONIVEL, "nota": "prazo prescricional não informado — não computado"}
    if prescricao_anos is not None:
        anos = _num(prescricao_anos)
        if anos is not None and anos <= 0:
            prescricao = {"score": 0, "nota": "prescrição consumada — responsabilização inviável"}
            score = 0.0  # teto-zero: sem prazo não há punição, qualquer que seja o resto
            cobertura += " · PRESCRITO"
        elif anos is not None:
            prescricao = {"score": min(100, round(anos * 12)), "nota": f"{anos:g} ano(s) até a prescrição"}

    score = round(min(100.0, max(0.0, score)), 1)
    eixo = "alto" if score >= 50 else "baixo"

    return {
        "score": score,
        "eixo": eixo,
        "materialidade": materialidade,
        "tipificacao": tipificacao,
        "autoria": autoria,
        "competencia": competencia,
        "prescricao": prescricao,
        "cobertura": cobertura,
        "nota": _resumo_punicao(score, materialidade, tipificacao, competencia),
    }


def _resumo_punicao(score, materialidade, tipificacao, competencia) -> str:
    partes = [f"Risco de punição {score:.0f}/100"]
    if materialidade["score"] != _INDISPONIVEL:
        partes.append(f"materialidade: {materialidade['nota']}")
    if tipificacao["score"] != _INDISPONIVEL:
        partes.append(f"tipificação: {tipificacao['nota']}")
    if competencia["score"] != _INDISPONIVEL:
        partes.append(f"competência: {competencia['nota']}")
    return " · ".join(partes)


def quadrante(risco_achado: float, risco_punicao: float, *, limiar: float = 50.0) -> str:
    """
    Classifica o achado no plano (risco de ACHADO × risco de PUNIÇÃO).

    Retorna (manual, seção "Scoring (2 eixos)" — priorizar o **alto-alto**):
        "alto-alto"  → PRIORITÁRIO (achado provável E punível) — atacar primeiro.
        "alto-baixo" → achado provável, punição inviável → inteligência de padrão / monitorar.
        "baixo-alto" → punível se confirmado, mas indício fraco → aprofundar apuração.
        "baixo-baixo"→ baixa prioridade.

    `risco_achado` e `risco_punicao` são 0-100; `limiar` separa alto/baixo (default 50).
    """
    ra = "alto" if (_num(risco_achado) or 0) >= limiar else "baixo"
    rp = "alto" if (_num(risco_punicao) or 0) >= limiar else "baixo"
    return f"{ra}-{rp}"


def rotulo_quadrante(q: str) -> str:
    """Rótulo humano do quadrante (para relatórios)."""
    return {
        "alto-alto": "PRIORITÁRIO — achado provável e punível (atacar primeiro)",
        "alto-baixo": "Inteligência de padrão — provável, mas punição inviável (monitorar)",
        "baixo-alto": "Aprofundar — punível se confirmado; indício ainda fraco",
        "baixo-baixo": "Baixa prioridade",
    }.get(q, q)
