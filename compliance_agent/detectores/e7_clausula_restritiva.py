# -*- coding: utf-8 -*-
"""E7 · CLÁUSULA RESTRITIVA — análise finalística cláusula-a-cláusula + efeito combinado (spec V2 do dono, §E7).

Complementa o E1 (a régua NUMÉRICA dura — atestado>50%, capital>10% com corroboração pelo resultado). O E7 é a
régua FINALÍSTICA: percorre CADA cláusula do edital (catálogo de `coletor_edital._CATALOGO_CLAUSULAS`), aplica o
teste de pertinência/proporcionalidade ao objeto (o "teste finalístico" do `restritividade_licitacoes.md` §4,
codificado), e — o mais sutil — mede o EFEITO COMBINADO: N cláusulas individualmente defensáveis que, juntas,
desenham o incumbente. Cada cláusula confirmada é AMARRADA à súmula/acórdão via `knowledge.jurisprudencia`.

PARÂMETROS OBJETIVOS (no CÓDIGO — limiar nunca vai ao prompt do LLM, spec §1.3):
  • capital/PL > 10% do estimado (Súmula TCU 275/art.69) ....................................... forte
  • capital/PL E garantia de participação CUMULADOS (Súmula 275 — só NÃO cumulativos) .......... forte
  • garantia de participação > 1% do valor estimado ............................................ forte
  • marca/modelo SEM "ou equivalente/similar" (Súmula 270; art.41) ............................. forte
  • visita técnica obrigatória SEM declaração substitutiva (art.63; Súmula TCE-RJ 01) .......... forte
  • vínculo empregatício prévio do profissional (Súmula TCE-RJ 10; Súmula 272) ................. forte
  • sede/domicílio/fabricação como habilitação (art.9 I 'b'/art.3 §1º) ......................... forte
  • atestado com quantitativo > 50% do licitado ............................................... forte (senão medio)
  • índice contábil sem justificativa nos autos (Súmula 289) .................................. medio
  • amostra/PoC de todos antes do julgamento (Súmula 272) .................................... medio
  • pontuação técnica subjetiva/dirigida (Súmula 272; art.37) ................................ medio
  • EFEITO COMBINADO: ≥ 3 categorias de cláusula restritiva DISTINTAS no mesmo edital ......... eleva p/ forte
    (Ac. TCU 1.065/2024 — direcionamento aferido pelo dano concreto à competitividade)
  • CRUZA com o RESULTADO da ata: inabilitações em cascata + poucos licitantes ................ eleva p/ forte
    (explica o resultado: "cláusula X restritiva → inabilitou A,B,C → sobrou o pretendido")

EXCULPATÓRIA (spec / honestidade): objeto crítico (UTI/segurança/dados sensíveis) justifica exigência acima do
usual → rebaixa. Rubrica de pertinência (LLM-opcional, degrada honesto): cláusula 'proporcional_ao_risco' →
rebaixa. Cláusula com "ou equivalente"/declaração substitutiva/justificativa nos autos NÃO pontua.

HONESTIDADE JFN: indício ≠ acusação; sem `clausulas_edital` no contexto → nao_avaliavel (campo ausente ≠ 0);
nunca inventa número. Cada cláusula confirmada cita súmula/dispositivo; itens com `verificar_antes_de_citar`
carregam o aviso (o relatório o exibe)."""
from __future__ import annotations

from compliance_agent.detectores.base import (
    Detector,
    ResultadoDetector,
    ancora,
    avaliar_rubrica,
)
from compliance_agent.knowledge.jurisprudencia import fundamentar_clausula

# rubrica fechada de pertinência ao risco (mesma escala do E1 — um só idioma no motor)
_RUBRICA_PERTINENCIA = {
    "proporcional_ao_risco": "ausente",
    "excessiva_mas_defensavel": "medio",
    "sem_relacao_com_capacidade": "forte",
}


def _pct_do_estimado(c: dict, valor_estimado: float | None) -> float | None:
    """Percentual do valor estimado que a cláusula exige (via `pct` direto, ou `valor`/estimado). None se não der."""
    pct = c.get("pct")
    if pct is not None:
        return float(pct)
    valor = c.get("valor")
    if valor is not None and valor_estimado:
        try:
            return float(valor) / float(valor_estimado)
        except (TypeError, ValueError, ZeroDivisionError):
            return None
    return None


# ───────────────────────────── testes finalísticos por tipo (CÓDIGO, limiar nunca no prompt) ─────────────────────────────
def _teste_capital(c: dict, ve: float | None) -> tuple[str | None, str]:
    p = _pct_do_estimado(c, ve)
    if p is not None and p > 0.10:
        return "forte", f"capital/PL = {p:.1%} do valor estimado (> 10% — teto do art. 69; Súmula TCU 275)"
    if p is not None:
        return "ausente", f"capital/PL = {p:.1%} ≤ 10% do estimado (dentro do teto legal)"
    return None, "capital/PL sem valor/percentual literal — nao_avaliavel (a régua numérica é do E1)"


def _teste_garantia(c: dict, ve: float | None) -> tuple[str | None, str]:
    p = _pct_do_estimado(c, ve)
    if p is not None and p > 0.01:
        return "forte", f"garantia de participação = {p:.1%} do valor estimado (> 1% — restritivo)"
    if p is not None:
        return "ausente", f"garantia de participação = {p:.1%} ≤ 1% do estimado"
    return None, "garantia sem valor/percentual literal — nao_avaliavel (cumulação c/ capital é checada à parte)"


def _teste_marca(c: dict, ve: float | None) -> tuple[str | None, str]:
    if c.get("tem_ou_equivalente"):
        return "ausente", "marca/modelo acompanhada de 'ou equivalente/similar' — não restritiva"
    return "forte", "marca/modelo SEM 'ou equivalente/similar' (Súmula TCU 270; art. 41 — direcionamento)"


def _teste_visita(c: dict, ve: float | None) -> tuple[str | None, str]:
    if c.get("tem_declaracao_substitutiva"):
        return "ausente", "visita admite declaração substitutiva de pleno conhecimento — não restritiva"
    return "forte", ("visita técnica obrigatória SEM declaração substitutiva (art. 63; Súmula TCE-RJ 01 — "
                     "barreira à competitividade)")


def _teste_vinculo(c: dict, ve: float | None) -> tuple[str | None, str]:
    return "forte", ("exige vínculo empregatício prévio do profissional (Súmula TCE-RJ 10; Súmula TCU 272 — basta "
                     "declaração de disponibilidade)")


def _teste_geografico(c: dict, ve: float | None) -> tuple[str | None, str]:
    return "forte", ("sede/domicílio/fabricação como condição de habilitação (art. 9º I 'b' / art. 3º §1º — vedada "
                     "distinção geográfica)")


def _teste_atestado(c: dict, ve: float | None) -> tuple[str | None, str]:
    pct = c.get("pct")
    if pct is not None and pct > 0.50:
        return "forte", f"atestado exige {pct:.0%} do quantitativo (> 50% — restritivo, Súmula TCU 263)"
    return "medio", "exigência de atestado de capacidade técnica (avaliar parcela de maior relevância — Súmula 263)"


def _teste_atestado_identico(c: dict, ve: float | None) -> tuple[str | None, str]:
    return "medio", "veda somatório / exige atestado idêntico (o somatório é a regra — Ac. TCU 1.153/2024)"


def _teste_indices(c: dict, ve: float | None) -> tuple[str | None, str]:
    if c.get("justificativa_autos"):
        return "ausente", "índice contábil com justificativa nos autos"
    return "medio", "índice contábil sem justificativa nos autos / parâmetro de mercado (Súmula TCU 289)"


def _teste_amostra(c: dict, ve: float | None) -> tuple[str | None, str]:
    return "medio", "amostra/PoC de todos antes do julgamento (custo antecipado — Súmula TCU 272)"


def _teste_pontuacao(c: dict, ve: float | None) -> tuple[str | None, str]:
    return "medio", "pontuação técnica subjetiva/dirigida (critérios objetivos e motivados — Súmula 272; art. 37)"


def _teste_temporal(c: dict, ve: float | None) -> tuple[str | None, str]:
    return None, "prazo restritivo depende de baseline de mercado ausente — nao_avaliavel (campo ausente ≠ 0)"


# tipo de cláusula → (teste finalístico, tipo p/ fundamentar_clausula)
_TESTES_FINALISTICOS: dict[str, tuple] = {
    "capital_patrimonio": (_teste_capital, "capital_patrimonio"),
    "garantia_proposta": (_teste_garantia, "garantia_proposta"),
    "marca_dirigida": (_teste_marca, "marca_dirigida"),
    "visita_tecnica": (_teste_visita, "visita_tecnica"),
    "vinculo_profissional": (_teste_vinculo, "vinculo_profissional"),
    "recorte_geografico": (_teste_geografico, "recorte_geografico"),
    "atestado_quantitativo": (_teste_atestado, "atestado_quantitativo"),
    "atestado_identico": (_teste_atestado_identico, "atestado_identico"),
    "indices_contabeis": (_teste_indices, "indices_contabeis"),
    "amostra_poc": (_teste_amostra, "amostra_poc"),
    "pontuacao_dirigida": (_teste_pontuacao, "pontuacao_dirigida"),
    "recorte_temporal": (_teste_temporal, "recorte_temporal"),
}

_NIVEIS_MARCA = {"medio", "forte", "critico"}  # níveis que contam como cláusula restritiva marcada


class E7ClausulaRestritiva(Detector):
    """Detector E7 — análise finalística cláusula-a-cláusula + efeito combinado (art. 9º/art. 5º, Lei 14.133/2021).

    `avaliar(contexto)` espera:
      contexto["processo"]: id do certame.
      contexto["clausulas_edital"]: list[dict] (de `coletor_edital`), cada uma com {tipo, categoria, texto, prov}
          e flags/parametros (`pct`,`valor`,`tem_ou_equivalente`,`tem_declaracao_substitutiva`,`justificativa_autos`).
      contexto["valor_estimado"] (opcional): p/ os testes de capital/garantia (% do estimado).
      contexto["resultado"] (opcional): {licitantes, inabilitados, ...} da ata — p/ cruzar cláusula↔resultado.
      contexto["objeto_critico"] (opcional bool): exculpatória — objeto crítico rebaixa o score.
      contexto["gerar"] (opcional): callable p/ a rubrica de pertinência (LLM-opcional, degrada honesto).

    Honesto: sem `clausulas_edital` → nao_avaliavel (campo ausente ≠ 0)."""

    id = "E7"
    nome = "Cláusula restritiva (análise finalística + efeito combinado)"
    familia = "desenho_certame"  # E7 — peso desenho_certame (0.6) na convergência §7.2

    def avaliar(self, contexto: dict) -> ResultadoDetector:
        processo = str(contexto.get("processo") or contexto.get("id") or "?")
        res = self._novo(processo, status="nao_avaliavel")

        clausulas = contexto.get("clausulas_edital") or []
        if not clausulas:
            res.motivo_refutacao = "nao_avaliavel: sem cláusulas do edital no contexto (campo ausente ≠ 0)"
            res.valores = {"n_clausulas": 0}
            return res

        valor_estimado = contexto.get("valor_estimado")
        resultado = contexto.get("resultado") or {}
        objeto_critico = bool(contexto.get("objeto_critico"))

        score = 0.0
        razoes: list[str] = []
        marcadas: list[dict] = []           # cláusulas restritivas confirmadas (nivel medio+)
        fundamentacao: dict[str, dict] = {}  # tipo → fundamentação jurídica
        verificar_flags: list[str] = []

        # ── cláusula a cláusula (teste finalístico determinístico) ──
        for c in clausulas:
            tipo = str(c.get("tipo") or "")
            teste = _TESTES_FINALISTICOS.get(tipo)
            if teste is None:
                continue
            fn, tipo_fund = teste
            nivel, motivo = fn(c, valor_estimado)
            if nivel is None or nivel not in _NIVEIS_MARCA:
                continue  # 'ausente' (cláusula ok) ou nao_avaliavel → não marca
            nivel = self._pertinencia(c, nivel)  # exculpatória LLM-opcional pode rebaixar
            if nivel not in _NIVEIS_MARCA:
                razoes.append(f"[{tipo}] rebaixada por pertinência ao risco — não pontua")
                continue
            score = max(score, ancora(nivel))
            marcadas.append({**c, "_nivel": nivel})
            razoes.append(f"[{tipo}/{nivel}] {motivo}")
            res.add_evidencia(fonte=f"cláusula do edital ({tipo})", trecho=str(c.get("texto") or "")[:160])
            if tipo_fund not in fundamentacao:
                fund = fundamentar_clausula(tipo_fund)
                if fund:
                    fundamentacao[tipo_fund] = _fund_resumo(fund)
                    if fund.get("verificar_antes_de_citar"):
                        verificar_flags.append(tipo_fund)

        # ── cumulação capital/PL + garantia (Súmula 275 — só NÃO cumulativos) ──
        tipos_presentes = {str(c.get("tipo") or "") for c in clausulas}
        if {"capital_patrimonio", "garantia_proposta"} <= tipos_presentes:
            score = max(score, ancora("forte"))
            razoes.append("cumulação: capital/PL E garantia de participação exigidos juntos (Súmula TCU 275 — "
                          "só de forma NÃO cumulativa)")

        valores: dict = {
            "n_clausulas": len(clausulas),
            "n_marcadas": len(marcadas),
            "tipos_marcados": sorted({m["tipo"] for m in marcadas}),
            "categorias_marcadas": sorted({str(m.get("categoria") or "?") for m in marcadas}),
            "objeto_critico": objeto_critico,
        }

        if score <= 0 and "capital_patrimonio" not in tipos_presentes:
            res.status = "descartado"
            res.motivo_refutacao = ("cláusulas dentro dos limites finalísticos (pertinentes/proporcionais ao objeto) "
                                    "— sem indício de restritividade")
            res.valores = valores
            res.explicacao_inocente = "exigências proporcionais ao objeto e ao risco; praxe do setor"
            return res

        # ── EFEITO COMBINADO: ≥3 categorias distintas de cláusula restritiva (direcionamento por conjunto) ──
        combinado, motivo_comb = self._efeito_combinado(valores["categorias_marcadas"], contexto)
        if combinado > 0:
            score = max(score, combinado)
            razoes.append(motivo_comb)
            fund = fundamentar_clausula("direcionamento_conjunto")
            if fund:
                fundamentacao["direcionamento_conjunto"] = _fund_resumo(fund)

        # ── CRUZA COM O RESULTADO da ata (explica o resultado) ──
        elevado, motivo_res = self._cruzar_resultado(resultado, marcadas)
        if elevado > 0:
            score = max(score, elevado)
            razoes.append(motivo_res)
            res.add_evidencia(fonte="resultado da ata (cruzamento cláusula↔habilitação)", trecho=motivo_res[:160])

        # exculpatória estrutural: objeto crítico justifica exigência alta → rebaixa
        if objeto_critico and score > ancora("medio"):
            score = ancora("medio")
            razoes.append("objeto crítico (UTI/segurança/dados sensíveis) justifica exigência acima do usual — rebaixado")

        if score <= 0:
            res.status = "descartado"
            res.motivo_refutacao = "sem cláusula restritiva confirmada após o teste finalístico"
            res.valores = valores
            return res

        valores["fundamentacao_juridica"] = fundamentacao
        if verificar_flags:
            valores["verificar_antes_de_citar"] = sorted(set(verificar_flags))
        res.score = round(score, 4)
        res.status = "confirmado"
        res.valores = valores
        res.motivo_refutacao = "; ".join(razoes)
        res.explicacao_inocente = ("FALSO POSITIVO a descartar (spec E7): objeto crítico justifica exigência acima do "
                                   "usual; cláusula com 'ou equivalente', declaração substitutiva ou justificativa nos "
                                   "autos NÃO é restritiva; exigência igual à praxe de TODOS os órgãos não é "
                                   "direcionamento. O efeito combinado exige ≥3 categorias distintas.")
        return res

    # ─────────────────────────── efeito combinado + cruzamento ───────────────────────────
    def _efeito_combinado(self, categorias_marcadas: list[str], contexto: dict) -> tuple[float, str]:
        """Direcionamento por CONJUNTO: ≥3 categorias de cláusula restritiva DISTINTAS no mesmo edital → forte,
        ainda que cada uma isolada seja só 'medio' (Ac. TCU 1.065/2024 — dano concreto à competitividade)."""
        n = len(categorias_marcadas)
        if n >= 3:
            return ancora("forte"), (f"efeito combinado: {n} categorias distintas de cláusula restritiva "
                                     f"({', '.join(categorias_marcadas)}) — direcionamento por conjunto (Ac. TCU 1.065/2024)")
        return 0.0, ""

    def _cruzar_resultado(self, resultado: dict, marcadas: list[dict]) -> tuple[float, str]:
        """Cruza as cláusulas restritivas com o RESULTADO da ata: inabilitações + poucos licitantes corroboram o
        EFEITO mensurável da barreira e EXPLICAM o resultado. Sem resultado ou sem cláusula marcada → não eleva."""
        if not marcadas:
            return 0.0, ""
        n_lic = resultado.get("licitantes")
        n_inab = resultado.get("inabilitados")
        if isinstance(n_inab, int) and n_inab > 0 and isinstance(n_lic, int) and n_lic <= 2:
            return ancora("forte"), (f"resultado corrobora: {n_inab} inabilitado(s) e apenas {n_lic} licitante(s) — "
                                     "cláusulas restritivas produziram o efeito mensurável (cascata de inabilitação)")
        return 0.0, ""

    # ─────────────────────────── rubrica de pertinência (LLM-opcional) ───────────────────────────
    def _pertinencia(self, clausula: dict, nivel_atual: str) -> str:
        """Exculpatória de pertinência ao risco (mesma rubrica do E1). Rubrica pré-injetada na cláusula
        (`_rubrica_pertinencia`, teste) tem prioridade; senão o nível determinístico permanece. 'proporcional_ao_risco'
        → rebaixa para 'ausente' (não pontua). Sem rubrica → mantém o nível do código (não degrada o achado objetivo)."""
        pre = clausula.get("_rubrica_pertinencia")
        if pre is None:
            return nivel_atual
        nivel_ancora, _score, _motivo = avaliar_rubrica(pre, _RUBRICA_PERTINENCIA)
        if nivel_ancora is None:
            return nivel_atual  # rubrica sem citação/ inválida → mantém o objetivo (honesto)
        return nivel_ancora


def _fund_resumo(fund: dict) -> dict:
    """Resumo serializável da fundamentação (Acordao vira número+tema) p/ caber em `valores`."""
    return {
        "sumulas": fund.get("sumulas", []),
        "acordaos": [f"{a.orgao} {a.numero}" for a in fund.get("acordaos", [])],
        "dispositivos_legais": fund.get("dispositivos_legais", []),
        "teste_finalistico": fund.get("teste_finalistico", ""),
        "verificar_antes_de_citar": fund.get("verificar_antes_de_citar", False),
    }
