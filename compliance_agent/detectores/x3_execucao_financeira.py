# -*- coding: utf-8 -*-
"""X3 · EXECUÇÃO FINANCEIRA ANÔMALA (spec V2 do dono, §X3 · fase de execução).

Mecanismo: o DINHEIRO conta a história. Pagamentos rápidos demais (tríade empenho→liquidação→pagamento com deltas
curtos demais), concentrados em DEZEMBRO, ANTES do atesto/medição, ou desalinhados do cronograma físico indicam
processo de fachada ou favorecimento na FILA de pagamento. Fonte: SIAFE (empenhos/liquidações/pagamentos por
contrato — datas e valores), cronograma físico-financeiro, atestos/medições, fila de pagamentos do órgão.

PARÂMETROS OBJETIVOS (no CÓDIGO — limiar nunca vai ao prompt do LLM, spec §1.3):
  • TRÍADE empenho→liquidação→pagamento com DELTAS muito curtos (pagamento quase imediato) ........... 'medio' (indício)
      compressão da tríade abaixo de `_DELTA_TRIADE_CURTO_DIAS`. `pronto_pagamento` REBAIXA (compressão legítima).
  • Pagamento ANTES da data do atesto/medição (paga sem atestar) ..................................... 'forte'
  • SAZONALIDADE: % dos pagamentos concentrado em DEZEMBRO ≥ `_LIMIAR_DEZEMBRO` (40%) ................ 'medio'
      E SEM cronograma físico-financeiro (`tem_cronograma is False`) → 'forte'.
  • INVERSÃO da ordem cronológica da fila (pago na frente de quem chegou antes), recorrente .......... 'forte'

PARTE SUBJETIVA (LLM-OPCIONAL, degrada honesto): rubrica fechada da "Justificativa de quebra da ordem cronológica"
(art. 141, Lei 14.133/2021): [justificativa_documentada / alegada_sem_documento / inexistente]. 'inexistente'/
'alegada_sem_documento' → CONFIRMA a quebra (forte). Evidência: trecho do ato de quebra de ordem (ou ausência no DO).
Sem LLM → o componente subjetivo fica nao_avaliavel (a inversão objetiva da fila, quando houver, permanece).

TESTE EXCULPATÓRIO (spec): contratos de PRONTO PAGAMENTO (fornecimento imediato) comprimem a tríade legitimamente —
classificar o TIPO DE OBJETO antes de pontuar compressão. Dezembro concentra pagamentos em TODO órgão por dinâmica
orçamentária; o limiar de 40% E a AUSÊNCIA de cronograma é que separam o normal do anômalo.

HONESTIDADE JFN: indício ≠ acusação; sem a TRÍADE SIAFE (empenho/liquidação/pagamento) → nao_avaliavel (campo
ausente ≠ 0); INDISPONÍVEL ≠ 0; nunca inventa número; valores em R$.
"""
from __future__ import annotations

from datetime import date, datetime

from compliance_agent.detectores.base import (
    Detector,
    ResultadoDetector,
    ancora,
    avaliar_rubrica,
)

# ───────────────────────────── Limiares (CÓDIGO, nunca no prompt) ─────────────────────────────
# Compressão da tríade empenho→liquidação→pagamento: ciclo total (empenho→pagamento) abaixo disso = "rápido demais".
_DELTA_TRIADE_CURTO_DIAS = 3
# Sazonalidade: fração dos pagamentos (em VALOR) concentrada em dezembro a partir da qual há indício.
_LIMIAR_DEZEMBRO = 0.40
# Inversões de fila para caracterizar RECORRÊNCIA (uma só pode ser fortuita; o padrão é que condena).
_INVERSOES_RECORRENTES = 2

# Rubrica fechada da justificativa de quebra da ordem cronológica (art. 141) → nível de âncora.
_RUBRICA_QUEBRA_ORDEM = {
    "justificativa_documentada": "ausente",      # hipóteses legais presentes E documentadas → quebra justificada
    "alegada_sem_documento": "forte",            # alegada mas sem o ato/documento → confirma a quebra
    "inexistente": "forte",                      # nenhuma justificativa no DO → confirma a quebra
}


def _data(v) -> date | None:
    """Converte uma data heterogênea (date/datetime/str ISO ou BR) em `date`. Inparseável → None (honesto)."""
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, str):
        s = v.strip()
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y-%m-%dT%H:%M:%S"):
            try:
                return datetime.strptime(s[:19] if "T" in s else s[:10], fmt).date()
            except ValueError:
                continue
    return None


def _is_pronto_pagamento(tipo_objeto) -> bool:
    """O objeto é de PRONTO PAGAMENTO / fornecimento imediato? (exculpa a compressão da tríade)."""
    t = str(tipo_objeto or "").strip().lower()
    return any(k in t for k in ("pronto_pagamento", "pronto pagamento", "pronto-pagamento", "fornecimento imediato"))


class X3ExecucaoFinanceira(Detector):
    """Detector X3 — execução financeira anômala (SIAFE: empenho→liquidação→pagamento, fila, dezembro, atesto).

    `avaliar(contexto)` espera:
      contexto["processo"]: id do processo/contrato.
      contexto["pagamentos"] (ESSENCIAL): list[dict], cada um com pelo menos `data_pagamento` e `valor`, e
          opcionalmente {data_empenho, data_liquidacao, data_atesto}. Sem este campo → nao_avaliavel.
      contexto["tipo_objeto"] (opcional): se 'pronto_pagamento'/'fornecimento imediato', exculpa a COMPRESSÃO
          da tríade (rebaixa o indício de pagamento rápido demais).
      contexto["tem_cronograma"] (opcional bool): há cronograma físico-financeiro? `False` + dezembro≥40% → forte.
      contexto["fila_orgao"] (opcional): list[dict] {contrato, data_chegada, data_pago} — fila de pagamentos do
          órgão (ordem cronológica) para detectar INVERSÃO (pago na frente de quem chegou antes).
      contexto["medicoes"] (opcional): medições/atestos adicionais (reservado; o atesto principal vem por pagamento).
      contexto["_rubrica_quebra"] (opcional, teste) / contexto["gerar"] (opcional): rubrica LLM da justificativa
          de quebra da ordem cronológica (art. 141). Ausente → componente subjetivo nao_avaliavel (honesto).

    Honesto: sem a TRÍADE SIAFE (lista de pagamentos com datas) → nao_avaliavel (campo ausente ≠ 0)."""

    id = "X3"
    nome = "Execução financeira anômala"
    familia = "execucao"  # X3 — fase de execução (peso 0.8 na convergência §7.2)

    def avaliar(self, contexto: dict) -> ResultadoDetector:
        processo = str(contexto.get("processo") or contexto.get("id") or "?")
        res = self._novo(processo, status="nao_avaliavel")

        pagamentos = [p for p in (contexto.get("pagamentos") or []) if isinstance(p, dict)]
        if not pagamentos:
            res.motivo_refutacao = (
                "nao_avaliavel: sem a tríade SIAFE (empenho/liquidação/pagamento) — sem a lista de pagamentos com "
                "datas/valores não há como aferir execução financeira anômala (campo ausente ≠ 0)")
            res.valores = {"n_pagamentos": 0}
            return res

        pronto = _is_pronto_pagamento(contexto.get("tipo_objeto"))
        tem_cronograma = contexto.get("tem_cronograma")  # bool | None (None = não informado)

        score = 0.0
        razoes: list[str] = []
        valores: dict = {
            "n_pagamentos": len(pagamentos),
            "tipo_objeto": contexto.get("tipo_objeto"),
            "pronto_pagamento": pronto,
            "tem_cronograma": tem_cronograma,
        }

        # ── (a) TRÍADE com deltas muito curtos (pagamento quase imediato) ──
        ciclos: list[int] = []  # ciclo empenho→pagamento, em dias
        for p in pagamentos:
            de, dp = _data(p.get("data_empenho")), _data(p.get("data_pagamento"))
            if de and dp:
                ciclos.append((dp - de).days)
        min_ciclo = min(ciclos) if ciclos else None
        valores["min_ciclo_empenho_pagamento_dias"] = min_ciclo
        triade_comprimida = (
            min_ciclo is not None and min_ciclo >= 0 and min_ciclo < _DELTA_TRIADE_CURTO_DIAS
        )
        if triade_comprimida:
            if pronto:
                # pronto pagamento comprime a tríade LEGITIMAMENTE → não pontua (classificar o objeto antes)
                razoes.append(
                    f"tríade comprimida (ciclo mínimo {min_ciclo}d) MAS objeto de PRONTO PAGAMENTO — compressão "
                    "legítima (não pontua)")
            else:
                score = max(score, ancora("medio"))
                razoes.append(
                    f"tríade empenho→liquidação→pagamento comprimida: ciclo mínimo de {min_ciclo} dia(s) "
                    "(pagamento quase imediato) — indício")

        # ── (b) Pagamento ANTES do atesto/medição (paga sem atestar) → forte ──
        antes_atesto = []
        for p in pagamentos:
            da, dp = _data(p.get("data_atesto")), _data(p.get("data_pagamento"))
            if da and dp and dp < da:
                antes_atesto.append((dp, da, float(p.get("valor") or 0)))
        valores["n_pagamentos_antes_do_atesto"] = len(antes_atesto)
        if antes_atesto:
            score = max(score, ancora("forte"))
            razoes.append(f"{len(antes_atesto)} pagamento(s) ANTES da data do atesto/medição (paga sem atestar)")
            for dp, da, val in antes_atesto[:6]:
                res.add_evidencia(
                    fonte="SIAFE pagamento × atesto",
                    trecho=(f"pago em {dp.isoformat()} ANTES do atesto em {da.isoformat()} "
                            f"(valor R$ {val:,.2f})"))

        # ── (c) SAZONALIDADE: % dos pagamentos (em valor) em dezembro ──
        total_valor = sum(float(p.get("valor") or 0) for p in pagamentos)
        valor_dezembro = 0.0
        for p in pagamentos:
            dp = _data(p.get("data_pagamento"))
            if dp and dp.month == 12:
                valor_dezembro += float(p.get("valor") or 0)
        pct_dezembro = (valor_dezembro / total_valor) if total_valor > 0 else None
        valores["pct_dezembro"] = round(pct_dezembro, 4) if pct_dezembro is not None else None
        if pct_dezembro is not None and pct_dezembro >= _LIMIAR_DEZEMBRO:
            # dezembro concentra pagamentos em TODO órgão; o que separa é o limiar + ausência de cronograma
            if tem_cronograma is False:
                score = max(score, ancora("forte"))
                razoes.append(
                    f"{pct_dezembro:.0%} dos pagamentos concentrados em DEZEMBRO (≥{_LIMIAR_DEZEMBRO:.0%}) E SEM "
                    "cronograma físico-financeiro — execução de fachada (forte)")
            else:
                score = max(score, ancora("medio"))
                razoes.append(
                    f"{pct_dezembro:.0%} dos pagamentos concentrados em DEZEMBRO (≥{_LIMIAR_DEZEMBRO:.0%}) — "
                    "sazonalidade anômala (médio; cronograma presente/desconhecido)")
            res.add_evidencia(
                fonte="SIAFE sazonalidade de pagamentos",
                trecho=(f"R$ {valor_dezembro:,.2f} de R$ {total_valor:,.2f} pagos em dezembro "
                        f"({pct_dezembro:.0%}); cronograma={tem_cronograma}"))

        # ── (d) INVERSÃO da ordem cronológica da fila (pago na frente de quem chegou antes) ──
        n_inversoes = self._contar_inversoes(contexto.get("fila_orgao"))
        valores["n_inversoes_fila"] = n_inversoes
        if n_inversoes is not None and n_inversoes >= _INVERSOES_RECORRENTES:
            score = max(score, ancora("forte"))
            razoes.append(
                f"{n_inversoes} inversão(ões) da ordem cronológica da fila de pagamentos (pago na frente de quem "
                "chegou antes), recorrente — favorecimento na fila")
            res.add_evidencia(
                fonte="fila de pagamentos do órgão",
                trecho=f"{n_inversoes} pagamento(s) fora da ordem de chegada (data_pago < data_pago de quem chegou antes)")

        if score <= 0:
            res.status = "descartado"
            res.motivo_refutacao = (
                "regras objetivas não acionaram: tríade não comprimida (ou pronto pagamento), sem pagamento antes "
                "do atesto, dezembro abaixo do limiar/com cronograma, sem inversão recorrente de fila")
            res.valores = valores
            res.explicacao_inocente = (
                "execução financeira regular: pagamentos no curso normal, atestados antes de pagar, sem concentração "
                "anômala em dezembro e em ordem cronológica de fila")
            return res

        # ── PARTE SUBJETIVA (LLM-opcional): justificativa de quebra da ordem cronológica (art. 141) ──
        quebra = self._avaliar_quebra_ordem(contexto)
        valores["justificativa_quebra_ordem"] = quebra["status"]
        if quebra["status"] in ("alegada_sem_documento", "inexistente"):
            score = max(score, ancora("forte"))
            razoes.append(
                f"rubrica art.141: justificativa de quebra da ordem '{quebra['status']}' → confirma a quebra (forte)")
        elif quebra["status"] == "justificativa_documentada":
            razoes.append(
                "rubrica art.141: quebra da ordem com justificativa legal documentada (registra; achado objetivo permanece)")

        res.score = round(score, 4)
        res.status = "confirmado"
        res.valores = valores
        res.motivo_refutacao = "; ".join(razoes)
        res.explicacao_inocente = (
            "FALSO POSITIVO a descartar (spec X3): contratos de PRONTO PAGAMENTO (fornecimento imediato) comprimem a "
            "tríade legitimamente — classificar o tipo de objeto antes de pontuar compressão. Dezembro concentra "
            "pagamentos em TODO órgão por dinâmica orçamentária; só o limiar de 40% E a ausência de cronograma "
            "separam o normal do anômalo. Verificar art.141 (quebra de ordem cronológica justificada).")
        return res

    # ───────────────────────────── helpers ─────────────────────────────
    def _contar_inversoes(self, fila) -> int | None:
        """Conta INVERSÕES da ordem cronológica da fila: pares (a, b) em que `a` chegou antes de `b`
        (data_chegada menor) mas foi pago DEPOIS (data_pago maior) → `b` furou a fila. Retorna None se a fila
        não tem dados utilizáveis (honesto: campo ausente ≠ 0 inversões)."""
        if not fila:
            return None
        itens = []
        for x in fila:
            if not isinstance(x, dict):
                continue
            dc, dpg = _data(x.get("data_chegada")), _data(x.get("data_pago"))
            if dc and dpg:
                itens.append((dc, dpg))
        if len(itens) < 2:
            return None
        inversoes = 0
        for i in range(len(itens)):
            for j in range(len(itens)):
                if i == j:
                    continue
                # i chegou ANTES de j, mas foi pago DEPOIS de j → j furou a fila à frente de i
                if itens[i][0] < itens[j][0] and itens[i][1] > itens[j][1]:
                    inversoes += 1
        return inversoes

    def _avaliar_quebra_ordem(self, contexto: dict) -> dict:
        """Rubrica fechada da justificativa de quebra da ordem cronológica (art. 141). Atalho de teste:
        `_rubrica_quebra` injetado no contexto (sem rede). Sem rubrica e sem LLM → nao_avaliavel honesto
        (não inventamos o juízo subjetivo; a inversão objetiva da fila, quando houver, permanece)."""
        pre = contexto.get("_rubrica_quebra")
        if pre is not None:
            nivel, _score, motivo = avaliar_rubrica(pre, _RUBRICA_QUEBRA_ORDEM)
            if nivel is None:
                return {"status": "nao_avaliavel", "motivo": motivo}
            return {"status": (pre.get("nivel") or pre.get("classificacao") or "").strip().lower(), "motivo": motivo}

        gerar = contexto.get("gerar")
        if gerar is None:
            return {"status": "nao_avaliavel", "motivo": "LLM ausente — justificativa de quebra não auditada (honesto)"}

        sistema = (
            "Você é auditor de controle externo avaliando QUEBRA DA ORDEM CRONOLÓGICA de pagamentos (art. 141, Lei "
            "14.133/2021). Classifique se a justificativa para o pagamento fora da ordem existe e está documentada "
            "(hipóteses legais presentes). Responda SOMENTE com JSON: "
            '{"nivel":"justificativa_documentada|alegada_sem_documento|inexistente",'
            '"trecho":"<citação literal do ato de quebra de ordem, ou da sua ausência no DO>"}. '
            "Sem trecho, não classifique.")
        prompt = (
            "Há ato/justificativa publicada de quebra da ordem cronológica para os pagamentos do contrato? "
            "Classifique conforme a rubrica.")
        try:
            raw = gerar(prompt, sistema)
        except Exception as ex:  # noqa: BLE001 — degrada honesto
            return {"status": "nao_avaliavel", "motivo": f"LLM indisponível ({str(ex)[:50]})"}
        from compliance_agent.detectores.base import _parse_json
        dados = _parse_json(raw)
        nivel, _score, motivo = avaliar_rubrica(dados, _RUBRICA_QUEBRA_ORDEM)
        if nivel is None or not isinstance(dados, dict):
            return {"status": "nao_avaliavel", "motivo": motivo}
        return {"status": (dados.get("nivel") or "").strip().lower(), "motivo": motivo}
