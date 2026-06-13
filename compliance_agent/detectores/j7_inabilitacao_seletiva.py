# -*- coding: utf-8 -*-
"""J7 · INABILITAÇÃO SELETIVA / DOIS PESOS (spec V2 do dono, §J7).

Mecanismo: a comissão de licitação aplica rigor formal MÁXIMO a concorrentes indesejados e TOLERÂNCIA
(diligência, prazo para sanar, saneamento) ao licitante PREFERIDO — direcionamento DENTRO da sessão de
julgamento. A assinatura objetiva é a INCONSISTÊNCIA de tratamento: a MESMA CLASSE de falha (certidão
vencida, assinatura faltante, índice contábil, atestado, documentação) gera INABILITAÇÃO para um licitante
e SANEAMENTO/DILIGÊNCIA/tolerância para outro (especialmente o vencedor).

UNIDADE DE ANÁLISE = o PAR comparado, NUNCA a decisão isolada (spec). Um par crítico é
(perdedor inabilitado) × (vencedor/preferido tolerado) na MESMA classe de falha.

PARÂMETROS OBJETIVOS (no CÓDIGO — limiar nunca vai ao prompt do LLM, spec §1.3):
  • CÓDIGO normaliza cada falha em CLASSE (dicionário de palavras-chave) quando `classe_falha` não vier dada.
  • CÓDIGO pareia decisões de MESMA CLASSE com resultados DIVERGENTES (inabilitação × tolerância) ........ forte
  • o par crítico (perdedor inabilitado × vencedor tolerado) AGRAVA ................................. eleva p/ crítico

PARTE SUBJETIVA — DUAS rubricas fechadas (LLM-OPCIONAL, degrada honesto):
  (1) "Equivalência das falhas comparadas" [falhas-equivalentes / falhas-distintas]: protege contra FALSO
      POSITIVO do próprio detector (pareou errado). SÓ pares 'equivalentes' pontuam. Sem essa confirmação
      o par fica nao_avaliavel (não condena por conta própria).
  (2) "Qualidade da fundamentação" [fundamentada-com-base-legal / generica /
      contraditoria-com-decisao-anterior-da-propria-comissao]: 'contraditória' → forte (0.85).

TESTE EXCULPATÓRIO (spec): Lei 14.133 art. 64 MANDA sanear vícios formais — diligência NÃO é favorecimento.
Favorecimento é diligenciar para UNS e não para OUTROS, em falhas EQUIVALENTES. Tratamento UNIFORME (todos
saneados, ou todos inabilitados) é art.64 legítimo → descartado. Par marcado 'falhas-distintas' pela rubrica
(1) é falso positivo do detector → descartado.

HONESTIDADE JFN: indício ≠ acusação; sem atas/decisões pareáveis (< 2 decisões com falha + resultado) →
nao_avaliavel (campo ausente ≠ 0); nunca inventa número.
"""
from __future__ import annotations

from compliance_agent.detectores.base import (
    Detector,
    ResultadoDetector,
    ancora,
    avaliar_rubrica,
)

# ── Rubrica (1): equivalência das falhas pareadas. Protege contra falso positivo do próprio detector.
# SÓ 'falhas-equivalentes' pontua; 'falhas-distintas' = o detector pareou errado → não condena.
_RUBRICA_EQUIVALENCIA = {
    "falhas-equivalentes": "forte",   # mesma natureza E gravidade → o par sustenta o indício
    "falhas-distintas": "ausente",    # detector pareou errado → falso positivo, descarta o par
}

# ── Rubrica (2): qualidade da fundamentação das decisões comparadas.
_RUBRICA_FUNDAMENTACAO = {
    "fundamentada-com-base-legal": "ausente",                       # decisão justificada → não agrava
    "generica": "medio",                                            # fundamentação genérica/frouxa
    "contraditoria-com-decisao-anterior-da-propria-comissao": "forte",  # dois pesos explícito
}

# Resultados que contam como TOLERÂNCIA (caminho de saneamento — o licitante segue no certame).
_TOLERANCIA = {"diligencia", "diligência", "saneamento", "habilitado", "habilitada", "tolerado"}
# Resultados que contam como INABILITAÇÃO (rigor formal — o licitante é eliminado).
_INABILITACAO = {"inabilitado", "inabilitada", "desclassificado", "desclassificada"}

# Dicionário de NORMALIZAÇÃO de classe de falha por palavras-chave (CÓDIGO, não LLM).
# Ordem importa: classes mais específicas antes das genéricas ('documentação' é fallback amplo).
_CLASSES_FALHA: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("certidao_vencida", ("certidão vencida", "certidao vencida", "certidão venc", "certidao venc",
                          "certidão expirada", "certidao expirada", "regularidade fiscal", "cnd vencida")),
    ("assinatura", ("assinatura", "não assinado", "nao assinado", "sem assinatura", "rubrica", "firma")),
    ("indice_contabil", ("índice", "indice", "liquidez", "endividamento", "solvência", "solvencia",
                         "balanço", "balanco", "qualificação econômica", "qualificacao economica")),
    ("atestado", ("atestado", "capacidade técnica", "capacidade tecnica", "acervo técnico",
                  "acervo tecnico", "qualificação técnica", "qualificacao tecnica", "cat")),
    ("documentacao", ("documentação", "documentacao", "documento", "habilitação jurídica",
                      "habilitacao juridica", "faltou", "ausência de", "ausencia de", "não anexou",
                      "nao anexou", "incompleta", "incompleto")),
)


def classificar_classe_falha(texto: str) -> str:
    """Normaliza um texto livre de falha numa CLASSE (CÓDIGO, determinístico). Sem casar nenhuma palavra-chave
    → 'outra' (classe genérica, não força pareamento). Atalho público p/ teste de classificação."""
    t = (texto or "").strip().lower()
    if not t:
        return "outra"
    for classe, chaves in _CLASSES_FALHA:
        if any(k in t for k in chaves):
            return classe
    return "outra"


def _resultado_tipo(decisao: str) -> str | None:
    """Mapeia o campo `decisao` numa categoria: 'inabilitacao' | 'tolerancia' | None (desconhecido)."""
    d = (decisao or "").strip().lower()
    if d in _INABILITACAO:
        return "inabilitacao"
    if d in _TOLERANCIA:
        return "tolerancia"
    return None


def _decisoes_validas(contexto: dict) -> list[dict]:
    """Reúne decisões do contexto (atual + série histórica da comissão) que tenham falha + resultado mapeável.
    A série histórica entra porque a unidade de análise pode parear decisões de sessões diferentes da MESMA
    comissão (spec: série histórica de decisões da mesma comissão)."""
    brutas: list[dict] = []
    brutas.extend(x for x in (contexto.get("decisoes") or []) if isinstance(x, dict))
    brutas.extend(x for x in (contexto.get("serie_comissao") or []) if isinstance(x, dict))
    validas: list[dict] = []
    for x in brutas:
        tipo = _resultado_tipo(str(x.get("decisao") or ""))
        falha = str(x.get("falha") or "").strip()
        if tipo is None or not falha:
            continue
        classe = str(x.get("classe_falha") or "").strip().lower() or classificar_classe_falha(falha)
        validas.append({
            "cnpj": str(x.get("cnpj") or "?"),
            "falha": falha,
            "classe": classe,
            "tipo": tipo,
            "decisao": str(x.get("decisao") or "").strip().lower(),
            "fundamento": str(x.get("fundamento") or "").strip(),
            "vencedor": bool(x.get("vencedor")),
        })
    return validas


def _parear_divergentes(decisoes: list[dict]) -> list[dict]:
    """Pareia decisões de MESMA CLASSE com resultados DIVERGENTES (inabilitação × tolerância). Cada par é a
    unidade de análise. Marca `critico=True` quando o tolerado é o VENCEDOR (perdedor inabilitado × vencedor
    tolerado — a assinatura do dois-pesos)."""
    pares: list[dict] = []
    por_classe: dict[str, list[dict]] = {}
    for d in decisoes:
        if d["classe"] == "outra":
            continue  # classe genérica não força pareamento (evita falso positivo)
        por_classe.setdefault(d["classe"], []).append(d)
    for classe, grupo in por_classe.items():
        inabilitados = [d for d in grupo if d["tipo"] == "inabilitacao"]
        tolerados = [d for d in grupo if d["tipo"] == "tolerancia"]
        for inab in inabilitados:
            for tol in tolerados:
                if inab["cnpj"] == tol["cnpj"]:
                    continue  # mesma empresa em momentos distintos não é dois-pesos entre licitantes
                pares.append({
                    "classe": classe,
                    "inabilitado": inab,
                    "tolerado": tol,
                    "critico": bool(tol["vencedor"]),
                })
    # pares críticos (vencedor tolerado) primeiro
    pares.sort(key=lambda p: not p["critico"])
    return pares


class J7InabilitacaoSeletiva(Detector):
    """Detector J7 — inabilitação seletiva / dois pesos na sessão de julgamento (spec V2 §J7).

    `avaliar(contexto)` espera:
      contexto["processo"]: id do certame/processo.
      contexto["decisoes"]: list[dict] de decisões de habilitação. Cada item:
          {cnpj, falha (texto livre da falha apontada),
           classe_falha (opcional; se ausente, o CÓDIGO classifica por palavras-chave),
           decisao ('inabilitado'|'habilitado'|'diligencia'|'saneamento'|...),
           fundamento (opcional, texto da fundamentação),
           vencedor (opcional bool — o tolerado é o vencedor do certame?)}.
      contexto["comissao"] (opcional): identificação da comissão julgadora.
      contexto["serie_comissao"] (opcional): list[dict] de decisões HISTÓRICAS da mesma comissão (mesmo schema
          de `decisoes`) — para parear entre sessões.
      contexto["_rubrica_equivalencia"] / contexto["_rubrica_fundamentacao"] (opcional, teste): rubricas LLM
          pré-classificadas (sem rede). contexto["gerar"] (opcional): callable (prompt, sistema)->str.

    Honesto: < 2 decisões com falha + resultado mapeável → nao_avaliavel (campo ausente ≠ 0). A rubrica de
    equivalência protege contra falso positivo do próprio pareamento: sem 'falhas-equivalentes', o par não
    condena."""

    id = "J7"
    nome = "Inabilitação seletiva (dois pesos)"
    familia = "conluio"  # J7 — peso conluio (0.9) na convergência §7.2

    def avaliar(self, contexto: dict) -> ResultadoDetector:
        processo = str(contexto.get("processo") or contexto.get("id") or "?")
        res = self._novo(processo, status="nao_avaliavel")

        decisoes = _decisoes_validas(contexto)
        if len(decisoes) < 2:
            res.motivo_refutacao = (
                "nao_avaliavel: menos de 2 decisões de habilitação com falha + resultado mapeável — sem pares "
                "comparáveis não há como aferir dois-pesos (a unidade de análise é o PAR; campo ausente ≠ 0)")
            res.valores = {"n_decisoes_validas": len(decisoes), "tem_pares": False}
            return res

        pares = _parear_divergentes(decisoes)
        valores: dict = {
            "comissao": contexto.get("comissao"),
            "n_decisoes_validas": len(decisoes),
            "n_pares_divergentes": len(pares),
            "classes_pareadas": sorted({p["classe"] for p in pares}),
        }

        if not pares:
            res.status = "descartado"
            res.motivo_refutacao = (
                "sem par divergente: na mesma classe de falha o tratamento foi UNIFORME (todos inabilitados ou "
                "todos saneados) — saneamento/diligência uniforme é art.64 legítimo, não favorecimento")
            res.valores = valores
            res.explicacao_inocente = (
                "Lei 14.133 art.64 MANDA sanear vícios formais; diligência aplicada à mesma régua para todos NÃO é "
                "favorecimento. Sem divergência de tratamento na mesma classe de falha, não há dois-pesos.")
            return res

        # ── RUBRICA (1): equivalência das falhas pareadas (protege contra falso positivo do detector) ──
        equiv = self._avaliar_equivalencia(contexto)
        valores["equivalencia_falhas"] = equiv["status"]
        if equiv["status"] == "falhas-distintas":
            res.status = "descartado"
            res.motivo_refutacao = (
                "rubrica equivalência: 'falhas-distintas' — o detector pareou falhas de natureza/gravidade "
                "diferentes (falso positivo do próprio pareamento); o par NÃO sustenta dois-pesos")
            res.valores = valores
            res.explicacao_inocente = (
                "As falhas comparadas não são equivalentes (naturezas/gravidades distintas); tratar de forma "
                "diferente falhas diferentes é legítimo — não há dois-pesos.")
            return res
        if equiv["status"] != "falhas-equivalentes":
            # nao_avaliavel: sem a confirmação de equivalência, o detector NÃO condena por conta própria (honesto)
            res.status = "nao_avaliavel"
            res.motivo_refutacao = (
                f"pareamento objetivo encontrou {len(pares)} par(es) de tratamento divergente na mesma classe, MAS "
                f"a equivalência das falhas não foi confirmada ({equiv['motivo']}) — sem isso o detector não condena "
                "(a rubrica de equivalência protege contra falso positivo do próprio pareamento)")
            res.valores = valores
            for p in pares[:6]:
                self._evidenciar_par(res, p)
            return res

        # equivalência CONFIRMADA → o pareamento objetivo pontua
        score = ancora("forte")
        razoes: list[str] = [
            f"{len(pares)} par(es) de tratamento DIVERGENTE na mesma classe de falha "
            "(inabilitação × saneamento/diligência) com falhas confirmadas EQUIVALENTES"]
        criticos = [p for p in pares if p["critico"]]
        if criticos:
            score = ancora("critico")
            razoes.append(
                f"{len(criticos)} par(es) CRÍTICO(s): perdedor INABILITADO × VENCEDOR tolerado na mesma falha "
                "(assinatura do dois-pesos: rigor para o concorrente, tolerância para o preferido)")

        for p in pares[:6]:
            self._evidenciar_par(res, p)

        # ── RUBRICA (2): qualidade da fundamentação ──
        fund = self._avaliar_fundamentacao(contexto)
        valores["qualidade_fundamentacao"] = fund["status"]
        if fund["status"] == "contraditoria-com-decisao-anterior-da-propria-comissao":
            score = max(score, ancora("forte"))
            razoes.append("rubrica fundamentação: decisão CONTRADITÓRIA com decisão anterior da própria comissão")
        elif fund["status"] == "generica":
            razoes.append("rubrica fundamentação: genérica/frouxa (registra; não eleva sozinha)")
        elif fund["status"] == "fundamentada-com-base-legal":
            razoes.append("rubrica fundamentação: decisões com base legal (registra; o pareamento objetivo permanece)")

        res.score = round(score, 4)
        res.status = "confirmado"
        res.valores = valores
        res.motivo_refutacao = "; ".join(razoes)
        res.explicacao_inocente = (
            "FALSO POSITIVO a descartar (spec J7): Lei 14.133 art.64 MANDA sanear vícios formais — diligência NÃO é "
            "favorecimento. Favorecimento é diligenciar para UNS e não para OUTROS em falhas EQUIVALENTES. Confirmar "
            "que as falhas pareadas são da MESMA natureza e gravidade (rubrica de equivalência) e que o tolerado é o "
            "vencedor. O PAR comparado é a unidade de análise, nunca a decisão isolada.")
        return res

    # ─────────────────────────── helpers de evidência ───────────────────────────
    def _evidenciar_par(self, res: ResultadoDetector, par: dict) -> None:
        """Adiciona a evidência de um par divergente — trechos das decisões LADO A LADO (exigência do spec)."""
        inab, tol = par["inabilitado"], par["tolerado"]
        marca = " [PAR CRÍTICO: vencedor tolerado]" if par["critico"] else ""
        trecho = (
            f"classe '{par['classe']}'{marca} — "
            f"INABILITADO {inab['cnpj']}: {inab['falha'][:120]} (decisão: {inab['decisao']}; "
            f"fund.: {inab['fundamento'][:120] or 'n/d'}) "
            f"× TOLERADO {tol['cnpj']}: {tol['falha'][:120]} (decisão: {tol['decisao']}; "
            f"fund.: {tol['fundamento'][:120] or 'n/d'})")
        res.add_evidencia(fonte="atas/decisões de habilitação (par comparado)", trecho=trecho)

    # ─────────────────────────── rubricas LLM-opcionais ───────────────────────────
    def _avaliar_equivalencia(self, contexto: dict) -> dict:
        """Rubrica (1): equivalência das falhas pareadas. Atalho de teste: `_rubrica_equivalencia` no contexto.
        Sem rubrica e sem LLM → nao_avaliavel honesto (o detector não condena sem confirmar equivalência)."""
        return self._rodar_rubrica(
            contexto,
            chave_pre="_rubrica_equivalencia",
            escala=_RUBRICA_EQUIVALENCIA,
            sistema=(
                "Você é auditor de controle externo. As decisões de habilitação abaixo foram pareadas pelo "
                "detector como sendo da MESMA CLASSE de falha. Diga se as falhas são EQUIVALENTES (mesma natureza "
                "E gravidade) ou DISTINTAS (o pareamento errou). Responda SOMENTE com JSON: "
                '{"nivel":"falhas-equivalentes|falhas-distintas","trecho":"<citação literal das decisões>"}. '
                "Sem trecho, não classifique."),
            prompt=self._prompt_decisoes(contexto,
                                         "As falhas comparadas são equivalentes (mesma natureza e gravidade) "
                                         "ou distintas (o detector pareou errado)?"),
        )

    def _avaliar_fundamentacao(self, contexto: dict) -> dict:
        """Rubrica (2): qualidade da fundamentação. Atalho de teste: `_rubrica_fundamentacao` no contexto.
        Sem rubrica e sem LLM → nao_avaliavel honesto."""
        return self._rodar_rubrica(
            contexto,
            chave_pre="_rubrica_fundamentacao",
            escala=_RUBRICA_FUNDAMENTACAO,
            sistema=(
                "Você é auditor de controle externo. Classifique a QUALIDADE da fundamentação das decisões de "
                "habilitação. Responda SOMENTE com JSON: "
                '{"nivel":"fundamentada-com-base-legal|generica|'
                'contraditoria-com-decisao-anterior-da-propria-comissao","trecho":"<citação literal>"}. '
                "Sem trecho, não classifique."),
            prompt=self._prompt_decisoes(contexto,
                                         "A fundamentação tem base legal, é genérica, ou é contraditória com "
                                         "decisão anterior da própria comissão?"),
        )

    # atalhos de teste (no molde do J4: expõem a rubrica isolada)
    def _rubrica_equivalencia(self, contexto: dict) -> dict:
        return self._avaliar_equivalencia(contexto)

    def _rubrica_fundamentacao(self, contexto: dict) -> dict:
        return self._avaliar_fundamentacao(contexto)

    def _prompt_decisoes(self, contexto: dict, pergunta: str) -> str:
        decisoes = _decisoes_validas(contexto)
        linhas = "; ".join(
            f"{d['cnpj']} [{d['classe']}/{d['decisao']}]: {d['falha'][:80]}"
            for d in decisoes[:10])
        return f"Decisões de habilitação pareadas: {linhas[:1200]}\n\n{pergunta}"

    def _rodar_rubrica(self, contexto: dict, *, chave_pre: str, escala: dict, sistema: str, prompt: str) -> dict:
        """Núcleo comum das duas rubricas (molde do J4). Rubrica pré-injetada (teste) tem prioridade; senão LLM
        via `gerar`; sem LLM → nao_avaliavel honesto."""
        pre = contexto.get(chave_pre)
        if pre is not None:
            nivel, _score, motivo = avaliar_rubrica(pre, escala)
            if nivel is None:
                return {"status": "nao_avaliavel", "motivo": motivo}
            return {"status": (pre.get("nivel") or pre.get("classificacao") or "").strip().lower(), "motivo": motivo}
        gerar = contexto.get("gerar")
        if gerar is None:
            return {"status": "nao_avaliavel", "motivo": "LLM ausente — rubrica não auditada (honesto)"}
        try:
            raw = gerar(prompt, sistema)
        except Exception as ex:  # noqa: BLE001 — degrada honesto
            return {"status": "nao_avaliavel", "motivo": f"LLM indisponível ({str(ex)[:50]})"}
        from compliance_agent.detectores.base import _parse_json
        dados = _parse_json(raw)
        nivel, _score, motivo = avaliar_rubrica(dados, escala)
        if nivel is None or not isinstance(dados, dict):
            return {"status": "nao_avaliavel", "motivo": motivo}
        return {"status": (dados.get("nivel") or "").strip().lower(), "motivo": motivo}
