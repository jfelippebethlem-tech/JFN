# -*- coding: utf-8 -*-
"""X7 · REEQUILÍBRIO INDEVIDO — a recomposição que na verdade é acréscimo, ou que é dupla.

POR QUE ESTE CARD EXISTE. Antes dele, a palavra "reequilíbrio" aparecia UMA vez em todo o código
do JFN, e como regex de classificação. Nenhum detector olhava o art. 124. O buraco custou caro na
estreia da varredura de execução (2026-07-29): um termo de "revisão dos valores vigentes" com
R$ 40,6 mi, fundamentado no art. 124, II, "d", entrou no teto do art. 125 como se fosse acréscimo
quantitativo e produziu um achado CRÍTICO fabricado — 45% dos X1 daquela rodada eram isso.

A régua de classificação (`limites_aditivo`) resolveu o falso positivo: reequilíbrio saiu do teto.
Mas tirar do teto não é o mesmo que auditar. Reequilíbrio mal instruído é um dos vetores mais
convenientes de fuga do art. 125 justamente porque NÃO tem teto percentual: basta chamar de
"revisão" o que é acréscimo, e o contrato cresce sem limite.

O QUE O ART. 124 EXIGE (Lei 14.133/2021):
  · a revisão pressupõe ÁLEA EXTRAORDINÁRIA — fato imprevisível, ou previsível de consequências
    incalculáveis, que desequilibre a equação econômico-financeira original;
  · aumento de custo ordinário (inflação, dissídio, câmbio corrente) é REAJUSTE ou REPACTUAÇÃO,
    que têm índice e periodicidade próprios — não revisão;
  · a demonstração do desequilíbrio é ônus de quem pleiteia, com memória de cálculo.

OS CINCO TESTES OBJETIVOS (no CÓDIGO — limiar nunca vai ao prompt):
  T1 DUPLA CORREÇÃO — reequilíbrio e reajuste incidindo sobre o MESMO período .......... critico
  T2 ÍNDICE DIVERGENTE — índice aplicado ≠ índice contratado ........................... forte
  T3 SEM PLEITO — revisão concedida de ofício, sem provocação do contratado nos autos ... forte
  T4 MAGNITUDE — recomposição que sozinha supera o teto do art. 125 do contrato ........ forte
  T5 REITERAÇÃO — 3+ revisões no mesmo contrato ........................................ medio

PARTE SUBJETIVA (rubrica fechada, LLM-opcional, degrada honesto):
  ÁLEA [extraordinaria_documentada / ordinaria_disfarcada / nao_demonstrada] — o pleito descreve
  fato imprevisível e ALHEIO à vontade das partes, com documento, ou apenas invoca "aumento de
  custos"? `ordinaria_disfarcada` → forte AUTÔNOMO (é reajuste vestido de revisão).

HONESTIDADE JFN: indício ≠ acusação. Sem aditivos de reequilíbrio no contexto → nao_avaliavel
(ausência ≠ zero). A ausência de memória de cálculo na BASE não prova ausência nos AUTOS: o card
declara a lacuna de captura em vez de convertê-la em achado — foi a lição das 9.863 red flags do
sweep SEI em que 59% eram queixa de captura, não vício.
"""
from __future__ import annotations

from compliance_agent.detectores.base import (
    Detector,
    ResultadoDetector,
    ancora,
    avaliar_rubrica,
)
from compliance_agent.limites_aditivo import ato_normativo, teto_acrescimo
from compliance_agent.reporting.intel_base import moeda

# ── parâmetros objetivos (CÓDIGO, nunca no prompt — spec §1.3) ────────────────────────────────
_REVISOES_REITERADAS = 3      # 3+ revisões no mesmo contrato: padrão, não evento extraordinário
_JANELA_DUPLA_DIAS = 365      # reequilíbrio e reajuste no mesmo período anual = dupla correção

_RUBRICA_ALEA = {
    "extraordinaria_documentada": "ausente",   # fato imprevisível, datado e documentado → exculpa
    "nao_demonstrada": "medio",                # o pleito não descreve o fato, só pede o valor
    "ordinaria_disfarcada": "forte",           # inflação/dissídio chamado de revisão → é reajuste
}

_SYS_ALEA = (
    "Você é AUDITOR DE CONTROLE EXTERNO avaliando o PLEITO DE REEQUILÍBRIO econômico-financeiro "
    "de um contrato administrativo (art. 124, II, 'd', da Lei 14.133/2021). A revisão pressupõe "
    "ÁLEA EXTRAORDINÁRIA: fato IMPREVISÍVEL — ou previsível de consequências incalculáveis — e "
    "ALHEIO à vontade das partes. Aumento ordinário de custos (inflação, dissídio da categoria, "
    "variação cambial corrente) NÃO é álea extraordinária: é reajuste ou repactuação, que têm "
    "índice e periodicidade próprios.\n"
    "Classifique APENAS: 'extraordinaria_documentada' = o texto descreve o fato, com data e "
    "documento (laudo, decisão, ato normativo, boletim); 'ordinaria_disfarcada' = o texto invoca "
    "aumento de custos corrente, inflação ou dissídio; 'nao_demonstrada' = pede a recomposição "
    "sem descrever fato algum; 'nao_sei' quando o texto não permite concluir.\n"
    "Responda SÓ um JSON: {\"nivel\":\"...\",\"trecho\":\"citação LITERAL do texto\"}. "
    "Sem trecho literal a resposta será DESCARTADA. Nunca invente fato fora do texto."
)


def _f(v) -> float | None:
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _ano(data) -> str:
    return str(data or "")[:4]


def _norm_indice(s) -> str:
    """'IPCA-E' / 'ipca e' / 'IPCA' → 'ipca'. Sem isso, a comparação de índices vira ruído."""
    import re
    t = re.sub(r"[^a-z]", "", str(s or "").lower())
    for chave in ("ipca", "incc", "igpm", "igp", "inpc", "cub", "sinapi", "icv"):
        if t.startswith(chave) or chave in t:
            return chave
    return t


class X7ReequilibrioIndevido(Detector):
    """Detector X7 — reequilíbrio econômico-financeiro indevido (art. 124, Lei 14.133/2021).

    `avaliar(contexto)` espera:
      contexto["processo"]: id do contrato/processo.
      contexto["valor_inicial"]: float — base do teto do art. 125, para o teste de magnitude (T4).
      contexto["aditivos"]: list[dict] com {tipo, valor, data?, descricao_objeto?, justificativa?,
          indice_aplicado?, houve_pleito?} — `tipo` vem de `limites_aditivo.classificar_natureza`
          ('reajuste' cobre reajuste, repactuação e revisão/reequilíbrio).
      contexto["indice_contratado"]: opcional str — índice previsto no contrato (T2).
      contexto["tipo_objeto"]: opcional — define o teto do art. 125 usado em T4.
      contexto["gerar"]: opcional callable(prompt, sistema)->str — rubrica de álea; ausente →
          a parte subjetiva fica nao_avaliavel e o cálculo objetivo permanece.
      contexto["_rubricas_alea"]: opcional list[dict] — atalho de teste, sem rede.

    Honesto: sem aditivos de recomposição → nao_avaliavel (campo ausente ≠ 0)."""

    id = "X7"
    nome = "Reequilíbrio econômico-financeiro indevido"
    familia = "execucao"

    def avaliar(self, contexto: dict) -> ResultadoDetector:
        processo = str(contexto.get("processo") or contexto.get("id") or "?")
        res = self._novo(processo, status="nao_avaliavel")

        aditivos = [a for a in (contexto.get("aditivos") or []) if isinstance(a, dict)]
        if not aditivos:
            res.motivo_refutacao = ("nao_avaliavel: sem aditivos no contexto — nada a aferir "
                                    "quanto a recomposição (campo ausente ≠ 0)")
            res.valores = {"n_aditivos": 0}
            return res

        recomposicoes = [a for a in aditivos if str(a.get("tipo") or "") == "reajuste"]
        if not recomposicoes:
            res.motivo_refutacao = ("nao_avaliavel: nenhum aditivo de recomposição (reajuste/"
                                    "repactuação/revisão) entre os termos — X7 não se aplica")
            res.valores = {"n_aditivos": len(aditivos), "n_recomposicoes": 0}
            return res

        valor_inicial = _f(contexto.get("valor_inicial"))
        teto = teto_acrescimo(contexto.get("tipo_objeto"))
        indice_contratado = _norm_indice(contexto.get("indice_contratado"))
        soma = sum(abs(_f(a.get("valor")) or _f(a.get("valor_acrescido")) or 0.0)
                   for a in recomposicoes)

        valores: dict = {
            "n_aditivos": len(aditivos), "n_recomposicoes": len(recomposicoes),
            "valor_recomposicoes": round(soma, 2), "valor_inicial": valor_inicial,
            "teto_art125_referencia": teto, "indice_contratado": indice_contratado or None,
            "ato_normativo": ato_normativo(),
        }
        achados: list[tuple[str, str]] = []   # (nivel_ancora, evidência)
        lacunas: list[str] = []

        # ── T1 · DUPLA CORREÇÃO ────────────────────────────────────────────────────────────────
        # Reequilíbrio recompõe a equação; reajuste corrige a inflação. Aplicar os dois sobre o
        # mesmo período paga duas vezes pela mesma perda de valor.
        anos_recomp = {_ano(a.get("data")) for a in recomposicoes if _ano(a.get("data"))}
        anos_reaj_indice = {_ano(a.get("data")) for a in recomposicoes
                            if a.get("indice_aplicado") and _ano(a.get("data"))}
        dupla = sorted(anos_recomp & anos_reaj_indice) if len(recomposicoes) > 1 else []
        # dois termos de recomposição no MESMO ano é o sinal mais direto
        por_ano: dict[str, int] = {}
        for a in recomposicoes:
            ano = _ano(a.get("data"))
            if ano:
                por_ano[ano] = por_ano.get(ano, 0) + 1
        anos_repetidos = sorted(ano for ano, n in por_ano.items() if n > 1)
        if anos_repetidos:
            achados.append(("critico",
                            f"DUPLA CORREÇÃO: {len(anos_repetidos)} exercício(s) com mais de uma "
                            f"recomposição ({', '.join(anos_repetidos)}) — reequilíbrio e reajuste "
                            f"sobre o mesmo período pagam duas vezes a mesma perda de valor "
                            f"(art. 124 × art. 92 §3º)"))
            valores["anos_com_dupla_correcao"] = anos_repetidos
        elif dupla:
            achados.append(("forte", f"recomposição com índice aplicado no mesmo exercício de "
                                     f"outra recomposição ({', '.join(dupla)})"))

        # ── T2 · ÍNDICE DIVERGENTE ─────────────────────────────────────────────────────────────
        if indice_contratado:
            divergentes = sorted({_norm_indice(a.get("indice_aplicado")) for a in recomposicoes
                                  if a.get("indice_aplicado")
                                  and _norm_indice(a.get("indice_aplicado")) != indice_contratado})
            if divergentes:
                achados.append(("forte",
                                f"ÍNDICE DIVERGENTE: contrato prevê '{indice_contratado}', "
                                f"aplicado(s) '{', '.join(divergentes)}' — a troca de índice é "
                                f"alteração de cláusula econômica, não simples cálculo"))
                valores["indices_divergentes"] = divergentes
        else:
            lacunas.append("indice_contratado não consta do contexto — T2 não aferido")

        # ── T3 · SEM PLEITO ────────────────────────────────────────────────────────────────────
        # O ônus de demonstrar o desequilíbrio é de quem o alega. Revisão de ofício inverte isso.
        sem_pleito = [a for a in recomposicoes if a.get("houve_pleito") is False]
        if sem_pleito:
            achados.append(("forte",
                            f"SEM PLEITO: {len(sem_pleito)} recomposição(ões) concedida(s) sem "
                            f"provocação do contratado — o ônus de demonstrar o desequilíbrio é "
                            f"de quem o alega"))
            valores["n_sem_pleito"] = len(sem_pleito)
        elif not any("houve_pleito" in a for a in recomposicoes):
            lacunas.append("existência de pleito não consta dos dados — T3 não aferido "
                           "(INDISPONÍVEL ≠ ausência de pleito)")

        # ── T4 · MAGNITUDE ─────────────────────────────────────────────────────────────────────
        if valor_inicial and valor_inicial > 0:
            pct = soma / valor_inicial
            valores["pct_recomposicao"] = round(pct, 4)
            # A BASE VEM DA MESMA EXTRAÇÃO QUE JÁ MENTIU NO X1. Medido em 2026-08-04: nos
            # processos da UG 070002 a base saía com ~R$ 50 mil enquanto os autos declaram
            # R$ 55-87 MILHÕES, e o T4 anunciava "recomposições somam 4.671%" e "29.879%".
            # Percentual de quatro dígitos não é contrato crescendo por recomposição: é base
            # errada. Quando o próprio processo declara outro valor que desmente a base, o T4
            # não afirma magnitude — a mesma doutrina do `base_contraditada` no X1.
            from compliance_agent.execucao_fatos import base_contraditada
            outra = base_contraditada(str(contexto.get("_texto_fonte") or ""), valor_inicial, soma)
            if outra:
                valores["base_contraditada_por"] = round(outra, 2)
                lacunas.append(
                    f"T4 (magnitude) NÃO aferido: a base extraída (R$ {moeda(valor_inicial)}) "
                    f"daria {pct:.0%}, e os próprios autos declaram R$ {moeda(outra)} — duas "
                    "leituras do mesmo processo não fecham; conferir o valor inicial")
            elif pct > teto:
                achados.append(("forte",
                                f"MAGNITUDE: recomposições somam {pct:.1%} do valor inicial "
                                f"(R$ {moeda(soma)} sobre R$ {moeda(valor_inicial)}), acima do "
                                f"próprio teto de ACRÉSCIMO do {ato_normativo()} ({teto:.0%}) — "
                                f"recomposição não tem teto percentual, e é por isso que ela é "
                                f"a via conveniente para crescer o contrato sem limite"))
        else:
            lacunas.append("valor_inicial ausente — T4 (magnitude) não aferido")

        # ── T5 · REITERAÇÃO ────────────────────────────────────────────────────────────────────
        if len(recomposicoes) >= _REVISOES_REITERADAS:
            achados.append(("medio",
                            f"REITERAÇÃO: {len(recomposicoes)} recomposições no mesmo contrato — "
                            f"álea EXTRAORDINÁRIA é, por definição, excepcional; a repetição "
                            f"sugere que o desequilíbrio é estrutural (erro de planejamento) e "
                            f"não superveniente"))

        # ── parte subjetiva: rubrica de ÁLEA (LLM-opcional) ────────────────────────────────────
        rubricas = contexto.get("_rubricas_alea")
        gerar = contexto.get("gerar")
        if rubricas is None and gerar:
            rubricas = []
            for a in recomposicoes[:6]:
                texto = str(a.get("justificativa") or a.get("descricao_objeto") or "")
                if not texto.strip():
                    continue
                try:
                    bruto = gerar(f"PLEITO/OBJETO DO TERMO:\n{texto[:2000]}\n\nResponda só o JSON.",
                                  _SYS_ALEA)
                except Exception as exc:  # noqa: BLE001 — LLM fora do ar não zera o objetivo
                    lacunas.append(f"rubrica de álea indisponível: {str(exc)[:60]}")
                    break
                from compliance_agent.llm.json_resposta import parse_json_llm
                rubricas.append({"resposta": parse_json_llm(bruto) or {}, "fonte": texto})

        if rubricas:
            for r in rubricas:
                resposta = r.get("resposta", r) if isinstance(r, dict) else {}
                fonte = r.get("fonte") if isinstance(r, dict) else None
                nivel, score, motivo = avaliar_rubrica(resposta, _RUBRICA_ALEA, fonte)
                if nivel and nivel != "ausente":
                    achados.append((nivel, f"ÁLEA: {motivo}"))
                    valores.setdefault("rubricas_alea", []).append(resposta.get("nivel"))
        elif not gerar:
            lacunas.append("sem `gerar`: a rubrica de álea (parte subjetiva) ficou nao_avaliavel")

        valores["lacunas"] = lacunas
        if not achados:
            res.status = "descartado"
            res.score = 0.0
            res.motivo_refutacao = (
                f"{len(recomposicoes)} recomposição(ões) sem sinal objetivo de irregularidade nos "
                f"testes aplicados. " + (f"Não aferidos: {'; '.join(lacunas)}." if lacunas else ""))
            res.valores = valores
            return res

        ordem = {"critico": 4, "forte": 3, "medio": 2, "fraco": 1, "ausente": 0}
        achados.sort(key=lambda t: -ordem.get(t[0], 0))
        nivel_final = achados[0][0]
        res.status = "confirmado"
        res.score = ancora(nivel_final)
        res.valores = valores
        res.evidencia = self._evidencias([e for _, e in achados])
        res.motivo_refutacao = ""
        res.explicacao_inocente = (
            "Recomposição pode ser legítima: álea extraordinária real (mudança tributária, "
            "colapso de fornecimento, decisão judicial) desequilibra a equação original e o "
            "art. 124 existe para isso. O achado é INDÍCIO — a apuração pede o pleito, a memória "
            "de cálculo e o parecer que instruíram o termo.")
        return res

    # ── utilitários locais (mantêm o card independente do formato de evidência) ────────────────
    def _evidencias(self, textos: list[str]) -> list[dict]:
        from compliance_agent.detectores.base import evidencia
        return [evidencia("contrato_aditivo / autos do processo", t) for t in textos]
