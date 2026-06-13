# -*- coding: utf-8 -*-
"""X5 · JOGO DE PLANILHA (spec V2 do dono, §X5 — fase de execução).

Mecanismo: na licitação por preço GLOBAL, o proponente DESEQUILIBRA a planilha — SUPERFATURA os itens que sabe
que vão crescer na execução e SUBCOTA os itens que serão suprimidos. O desconto global parece ótimo na disputa; a
execução real, depois dos aditivos de quantitativo, sai cara. É o clássico "jogo de planilha" do TCU.

PARÂMETROS OBJETIVOS (no CÓDIGO — esta é a PEÇA CENTRAL, estatística; limiar nunca vai ao prompt do LLM, §1.3):
  • Para cada item: desvio unitário = (preço_contratado − referencial) / referencial. Item com desvio > 0 está
    SOBREPRECIFICADO; desvio < 0 está SUBCOTADO. Marca-se o padrão de COEXISTÊNCIA (itens caros + itens baratos).
  • Casa-se com a EXECUÇÃO: variação de quantidade por item = (qtd_executada − qtd_contratada) / qtd_contratada.
  • CORRELAÇÃO DIRECIONAL (Pearson, inline) entre desvio unitário e variação de quantidade. Correlação POSITIVA
    forte = itens sobreprecificados cresceram E itens subcotados sumiram → assinatura do desenho:
        r ≥ 0.5 (n suficiente) → forte ; r ≥ 0.8 → critico.
  • SEM execução (só o desequilíbrio inicial da planilha) → no MÁXIMO medio (0.6): desequilíbrio sozinho tem
    explicação inocente comum (margens heterogêneas por linha). O que NÃO existe sem desenho é a correlação.
  • DANO (R$): Σ (preço_contratado − referencial) × quantidade_executada, APENAS nos itens SOBREPRECIFICADOS.

PARTE SUBJETIVA (LLM-OPCIONAL, degrada honesto): rubrica fechada da JUSTIFICATIVA TÉCNICA das variações de
quantitativo [superveniente_documentado / erro_de_projeto_alegado / sem_justificativa]. Combinada com a correlação
objetiva, 'erro de projeto' NÃO salva: erro ALEATÓRIO de projeto não produz correlação DIRECIONAL entre sobrepreço
e crescimento. Sem LLM → a justificativa fica nao_avaliavel (a correlação objetiva permanece como indício).

TESTE EXCULPATÓRIO (spec): estratégias de preço heterogêneas existem SEM fraude (margens diferentes por linha) —
o desequilíbrio INICIAL sozinho fica em 0.3–0.6 (fraco/médio). O que NÃO existe sem desenho é a CORRELAÇÃO
DIRECIONAL entre sobrepreço e crescimento; por isso o detector estatístico é a peça central.

HONESTIDADE JFN: indício ≠ acusação; sem planilha+referencial → nao_avaliavel (campo ausente ≠ 0); sem execução,
limita-se ao desequilíbrio (não inventa o crescimento); nunca inventa número. Valores em R$.
"""
from __future__ import annotations

from math import sqrt

from compliance_agent.detectores.base import (
    Detector,
    ResultadoDetector,
    ancora,
    avaliar_rubrica,
)

# Rubrica fechada da justificativa técnica das variações de quantitativo (spec X5). LLM-opcional; degrada honesto.
# Nota: 'erro de projeto' NÃO salva quando há correlação direcional (combinação é feita no código, não na rubrica):
# a rubrica só classifica a NATUREZA da justificativa; o peso exculpatório/agravante é aplicado no avaliar().
_RUBRICA_JUSTIFICATIVA = {
    "superveniente_documentado": "ausente",   # fato novo genuíno e documentado → exculpatória
    "erro_de_projeto_alegado": "medio",        # alegação de erro de projeto — não salva se há correlação direcional
    "sem_justificativa": "forte",              # variações sem qualquer justificativa técnica → agrava
}

# Limiares estatísticos (CÓDIGO). n mínimo para a correlação ser confiável e limiares de Pearson.
_N_MIN_CORRELACAO = 4
_R_FORTE = 0.5
_R_CRITICO = 0.8
# Tolerância para "sobreprecificado"/"subcotado": desvio relativo mínimo para considerar a linha desequilibrada.
_TOL_DESVIO = 0.05


def _f(v) -> float | None:
    """Converte para float; None/inválido → None (campo ausente ≠ 0, honesto)."""
    if v is None or isinstance(v, bool):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    """Correlação de Pearson INLINE (sem scipy). r = Σ(dx·dy) / sqrt(Σdx²·Σdy²). Retorna None se n<2 ou se
    qualquer das séries é constante (variância nula → correlação indefinida). Determinístico, leve (VM-safe)."""
    n = len(xs)
    if n < 2 or n != len(ys):
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 0 or syy <= 0:
        return None
    return sxy / sqrt(sxx * syy)


class X5JogoDePlanilha(Detector):
    """Detector X5 — jogo de planilha (desequilíbrio + correlação direcional sobrepreço×crescimento).

    `avaliar(contexto)` espera:
      contexto["processo"]: id do contrato/processo.
      contexto["itens"]: list[dict], cada item com:
          {item, preco_contratado, referencial, quantidade_contratada?, quantidade_executada?,
           justificativa_aditivo?}.
        ESSENCIAL: preco_contratado + referencial em cada linha (planilha + referencial SINAPI/SICRO/medianas).
        Para a CORRELAÇÃO direcional (peça central): também quantidade_contratada + quantidade_executada por item.
      contexto["gerar"] (opcional): callable síncrono (prompt, sistema)->str para a rubrica da justificativa.
      contexto["_rubrica_justificativa"] (opcional, teste): rubrica pré-classificada (sem rede).

    Honesto: sem itens, ou nenhum item com preço_contratado+referencial → nao_avaliavel. Sem execução, o máximo é
    medio (só o desequilíbrio inicial). Sem indício de desequilíbrio → descartado."""

    id = "X5"
    nome = "Jogo de planilha"
    familia = "execucao"  # X5 — peso 0.8 (execução) na convergência §7.2

    def avaliar(self, contexto: dict) -> ResultadoDetector:
        processo = str(contexto.get("processo") or contexto.get("id") or "?")
        res = self._novo(processo, status="nao_avaliavel")
        itens = contexto.get("itens") or []

        if not itens:
            res.motivo_refutacao = "nao_avaliavel: nenhum item de planilha no contexto (campo ausente ≠ 0)"
            res.valores = {"n_itens": 0}
            return res

        # ── Camada essencial: desvio unitário por item (precisa preço_contratado + referencial) ──
        linhas: list[dict] = []
        for it in itens:
            pc = _f(it.get("preco_contratado"))
            ref = _f(it.get("referencial"))
            if pc is None or ref is None or ref == 0:
                continue  # linha sem dado essencial é IGNORADA (não inventamos referencial)
            desvio = (pc - ref) / ref
            qc = _f(it.get("quantidade_contratada"))
            qe = _f(it.get("quantidade_executada"))
            var_qtd = None
            if qc is not None and qc != 0 and qe is not None:
                var_qtd = (qe - qc) / qc
            linhas.append({
                "item": it.get("item") or it.get("descricao") or "?",
                "preco_contratado": pc,
                "referencial": ref,
                "desvio": desvio,
                "quantidade_contratada": qc,
                "quantidade_executada": qe,
                "var_qtd": var_qtd,
                "justificativa": it.get("justificativa_aditivo") or it.get("justificativa"),
            })

        if not linhas:
            res.motivo_refutacao = ("nao_avaliavel: nenhum item com preço_contratado + referencial — sem planilha "
                                    "contratada e referencial (SINAPI/SICRO/medianas) não há como aferir desvio "
                                    "unitário (campo ausente ≠ 0)")
            res.valores = {"n_itens": len(itens), "n_itens_avaliaveis": 0}
            return res

        sobreprecificados = [ln for ln in linhas if ln["desvio"] > _TOL_DESVIO]
        subcotados = [ln for ln in linhas if ln["desvio"] < -_TOL_DESVIO]
        n_av = len(linhas)

        valores: dict = {
            "n_itens": len(itens),
            "n_itens_avaliaveis": n_av,
            "n_sobreprecificados": len(sobreprecificados),
            "n_subcotados": len(subcotados),
            "desvio_medio": round(sum(ln["desvio"] for ln in linhas) / n_av, 4),
            "tem_execucao": False,
            "correlacao_pearson": None,
            "dano_estimado_reais": None,
        }

        # Coexistência de itens caros + baratos = condição NECESSÁRIA do jogo de planilha (mas não suficiente).
        desequilibrio = len(sobreprecificados) >= 1 and len(subcotados) >= 1
        if not desequilibrio:
            res.status = "descartado"
            res.motivo_refutacao = ("sem coexistência de itens sobreprecificados E subcotados — não há padrão de "
                                    "desequilíbrio de planilha")
            res.valores = valores
            res.explicacao_inocente = ("os desvios unitários não exibem o padrão caro+barato simultâneo; planilha "
                                       "sem desequilíbrio estruturado")
            return res

        score = 0.0
        razoes: list[str] = []

        # ── PEÇA CENTRAL: correlação direcional sobrepreço × crescimento de quantidade ──
        with_exec = [ln for ln in linhas if ln["var_qtd"] is not None]
        r = None
        if len(with_exec) >= 2:
            valores["tem_execucao"] = True
            xs = [ln["desvio"] for ln in with_exec]
            ys = [ln["var_qtd"] for ln in with_exec]
            r = _pearson(xs, ys)
            valores["correlacao_pearson"] = round(r, 4) if r is not None else None
            valores["n_itens_com_execucao"] = len(with_exec)

        if r is not None and len(with_exec) >= _N_MIN_CORRELACAO:
            if r >= _R_CRITICO:
                score = max(score, ancora("critico"))
                razoes.append(
                    f"correlação direcional CRÍTICA (Pearson r={r:.2f}, n={len(with_exec)}) entre sobrepreço e "
                    "crescimento de quantidade: itens caros cresceram, subcotados sumiram — assinatura do desenho")
            elif r >= _R_FORTE:
                score = max(score, ancora("forte"))
                razoes.append(
                    f"correlação direcional FORTE (Pearson r={r:.2f}, n={len(with_exec)}) entre sobrepreço e "
                    "crescimento de quantidade — desequilíbrio explorado na execução")
            else:
                # desequilíbrio com execução, mas SEM correlação direcional → exculpatória do spec (margens
                # heterogêneas sem desenho); fica no patamar do desequilíbrio (médio).
                score = max(score, ancora("medio"))
                razoes.append(
                    f"desequilíbrio de planilha com execução, mas correlação fraca (r={r:.2f}) — sem direcionamento "
                    "claro; pode ser estratégia de margens heterogêneas (exculpatória do spec)")
        else:
            # Sem execução suficiente: SÓ o desequilíbrio inicial → no máximo médio (spec).
            score = max(score, ancora("medio"))
            razoes.append(
                f"desequilíbrio inicial da planilha ({len(sobreprecificados)} itens sobreprecificados + "
                f"{len(subcotados)} subcotados) SEM execução medida suficiente — limitado a médio (a correlação "
                "direcional é a peça central e não pôde ser computada)")

        # ── DANO (R$): Σ (preço_contratado − referencial) × qtd_executada, SÓ nos sobreprecificados ──
        dano = 0.0
        dano_computavel = False
        for ln in sobreprecificados:
            qe = ln["quantidade_executada"]
            if qe is not None:
                dano += (ln["preco_contratado"] - ln["referencial"]) * qe
                dano_computavel = True
        if dano_computavel:
            valores["dano_estimado_reais"] = round(dano, 2)
            razoes.append(f"dano estimado (sobrepreço × qtd executada nos itens caros): R$ {dano:,.2f}")

        # ── Evidência (higiene probatória §7.4): itens sobreprecificados que cresceram + a correlação ──
        for ln in sorted(sobreprecificados, key=lambda x: x["desvio"], reverse=True)[:8]:
            cresceu = ln["var_qtd"] is not None and ln["var_qtd"] > 0
            res.add_evidencia(
                fonte=f"item '{ln['item']}' (planilha × referencial × execução)",
                trecho=(f"preço_contratado=R$ {ln['preco_contratado']:,.2f} referencial=R$ {ln['referencial']:,.2f} "
                        f"desvio={ln['desvio'] * 100:+.1f}% "
                        f"var_qtd={'%.1f%%' % (ln['var_qtd'] * 100) if ln['var_qtd'] is not None else '?'} "
                        f"{'CRESCEU' if cresceu else ''}".strip()),
            )
        if r is not None:
            res.add_evidencia(
                fonte="correlação direcional sobrepreço×crescimento (Pearson, n=%d)" % len(with_exec),
                trecho=f"coeficiente de correlação de Pearson r={r:.4f} (≥{_R_FORTE} forte, ≥{_R_CRITICO} crítico)",
            )

        # ── PARTE SUBJETIVA (LLM-opcional): justificativa técnica das variações ──
        just = self._avaliar_justificativa(contexto, linhas)
        valores["justificativa_variacoes"] = just["status"]
        if just["status"] == "superveniente_documentado":
            # fato novo documentado é exculpatória — MAS só rebaixa quando NÃO há correlação direcional forte
            # (erro/fato genuíno não produz correlação dirigida; se a correlação é forte, o documento não explica
            #  por que justamente os itens CAROS cresceram). Rebaixa, não zera.
            if r is None or r < _R_FORTE:
                score = min(score, ancora("fraco"))
                razoes.append("rubrica: variação superveniente documentada e sem correlação direcional → rebaixa a fraco")
            else:
                razoes.append("rubrica: alega superveniente documentado, MAS a correlação direcional forte não é "
                              "explicada por fato novo (itens caros é que cresceram) — mantém o achado estatístico")
        elif just["status"] == "sem_justificativa":
            score = min(1.0, score + 0.05)
            razoes.append("rubrica: variações de quantitativo SEM justificativa técnica — agrava")
        elif just["status"] == "erro_de_projeto_alegado":
            razoes.append("rubrica: alega erro de projeto — NÃO salva: erro aleatório não produz correlação "
                          "direcional entre sobrepreço e crescimento (registra; achado estatístico permanece)")

        res.score = round(score, 4)
        res.status = "confirmado"
        res.valores = valores
        res.motivo_refutacao = "; ".join(razoes)
        res.explicacao_inocente = (
            "FALSO POSITIVO a descartar (spec X5): estratégias de preço HETEROGÊNEAS por linha existem sem fraude "
            "(margens diferentes por item); o desequilíbrio INICIAL sozinho fica em 0.3–0.6. O que NÃO existe sem "
            "desenho é a CORRELAÇÃO DIRECIONAL entre sobrepreço e crescimento de quantidade — verificar se as "
            "variações de quantitativo têm fato superveniente documentado.")
        return res

    def _avaliar_justificativa(self, contexto: dict, linhas: list[dict]) -> dict:
        """Rubrica fechada LLM-opcional da justificativa técnica das variações de quantitativo. Atalho de teste:
        `_rubrica_justificativa` injetado no contexto. Sem rubrica e sem LLM → nao_avaliavel honesto (não inventa
        o juízo subjetivo)."""
        pre = contexto.get("_rubrica_justificativa")
        if pre is not None:
            nivel, _score, motivo = avaliar_rubrica(pre, _RUBRICA_JUSTIFICATIVA)
            if nivel is None:
                return {"status": "nao_avaliavel", "motivo": motivo}
            return {"status": (pre.get("nivel") or pre.get("classificacao") or "").strip().lower(), "motivo": motivo}

        gerar = contexto.get("gerar")
        if gerar is None:
            return {"status": "nao_avaliavel", "motivo": "LLM ausente — justificativa das variações não auditada (honesto)"}

        justs = "; ".join(str(ln.get("justificativa") or "")[:80] for ln in linhas if ln.get("justificativa"))
        sistema = (
            "Você é auditor de controle externo avaliando JOGO DE PLANILHA. Classifique a JUSTIFICATIVA TÉCNICA das "
            "variações de quantitativo dos aditivos conforme a rubrica fechada. Responda SOMENTE com JSON: "
            '{"nivel":"superveniente_documentado|erro_de_projeto_alegado|sem_justificativa",'
            '"trecho":"<citação literal da justificativa>"}. Sem trecho, não classifique.')
        prompt = (f"Justificativas dos aditivos de quantitativo: {justs[:1000] or '(nenhuma justificativa anexada)'}\n\n"
                  "Classifique a natureza da justificativa técnica das variações.")
        try:
            raw = gerar(prompt, sistema)
        except Exception as ex:  # noqa: BLE001 — degrada honesto
            return {"status": "nao_avaliavel", "motivo": f"LLM indisponível ({str(ex)[:50]})"}
        from compliance_agent.detectores.base import _parse_json
        dados = _parse_json(raw)
        nivel, _score, motivo = avaliar_rubrica(dados, _RUBRICA_JUSTIFICATIVA)
        if nivel is None or not isinstance(dados, dict):
            return {"status": "nao_avaliavel", "motivo": motivo}
        return {"status": (dados.get("nivel") or "").strip().lower(), "motivo": motivo}
