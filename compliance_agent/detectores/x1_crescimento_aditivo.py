# -*- coding: utf-8 -*-
"""X1 · CRESCIMENTO ADITIVO — contrato que engorda (spec V2 do dono, §X1). Primeiro detector da FASE DE EXECUÇÃO.

Mecanismo: vence-se BARATO (proposta agressiva) e recupera-se a margem por TERMOS ADITIVOS sucessivos. O padrão
fraudulento é um projeto deliberadamente INCOMPLETO seguido de aditivos rápidos que engordam o contrato até o teto.
O art. 125 da Lei 14.133/2021 limita os ACRÉSCIMOS a 25% do valor inicial atualizado do contrato (50% para REFORMA
de edifício ou de equipamento). Acréscimos e supressões são computados SEPARADAMENTE (não se compensam).

PARÂMETROS OBJETIVOS (no CÓDIGO — limiar nunca vai ao prompt do LLM, spec §1.3):
  • Atualiza o valor inicial pelo índice; soma os ACRÉSCIMOS de valor (ignora aditivos de só-prazo) e calcula a
    % sobre o valor inicial atualizado; supressões somadas à parte (não abatem o teto de acréscimo).
  • Acréscimo % > teto (25% normal / 50% reforma) → ESTOURO objetivo do art.125 ............... 'critico' (1.0)
  • Acréscimo % rente ao teto (≥20% normal / ≥45% reforma), sem estourar ...................... 'forte' (0.85)
  • Acréscimo % na metade do teto (≥12.5% normal / ≥25% reforma) ............................... 'medio' (0.6)
  • VELOCIDADE: poucos dias (< 90) do início da execução até o 1º aditivo de VALOR .............. agrava (+0.10)

PARTE SUBJETIVA (DUAS rubricas fechadas, LLM-OPCIONAL, degrada honesto):
  (1) JUSTIFICATIVA de cada aditivo [fato_superveniente_verificavel / falha_de_projeto_admitida / generica]:
      'falha_de_projeto_admitida' em aditivo PRECOCE confirma o desenho deliberado → 'forte'.
  (2) PERTINÊNCIA do objeto aditado [mesmo_objeto_detalhado / objeto_novo_disfarcado]: 'objeto_novo_disfarcado'
      (escopo que exigiria novo certame) → 'forte' (0.85) AUTÔNOMO.
  Sem LLM → a parte subjetiva fica nao_avaliavel (o cálculo objetivo do teto permanece).

TESTE EXCULPATÓRIO (spec): obras longas sofrem supervenientes REAIS (geologia, chuva, desapropriação). A rubrica
exige um evento DATADO e DOCUMENTADO (laudo/boletim de medição/decisão judicial); sem documento é 'generica'.
Aditivo de PRAZO sem valor NÃO consome o teto (tem outra análise — X2).

FAMÍLIA (nota do dono): X1 é da família 'execucao' (peso 0.8). Mas quando o teto do art.125 é OBJETIVAMENTE
estourado, marca-se score 'critico' (1.0) — o peso de violação legal é tratado pela convergência do orquestrador.

HONESTIDADE JFN: indício ≠ acusação; sem `valor_inicial` ou sem `aditivos` → nao_avaliavel (campo ausente ≠ 0);
aditivo de prazo sem valor não conta no teto; nunca inventa número. Valores em R$.
"""
from __future__ import annotations

from datetime import date, datetime

from compliance_agent.detectores.base import (
    Detector,
    ResultadoDetector,
    ancora,
    avaliar_rubrica,
)

# ───────────────────────────── Tetos do art. 125 (Lei 14.133/2021) ─────────────────────────────
_TETO_PADRAO = 0.25  # 25% — regra geral (acréscimos)
_TETO_REFORMA = 0.50  # 50% — reforma de edifício ou de equipamento

# Limiares de proximidade ao teto (CÓDIGO, nunca no prompt): fração do teto a partir da qual o acréscimo é grave.
_FRACAO_FORTE = 0.80  # ≥80% do teto (ex.: ≥20% no padrão / ≥45% na reforma) → forte
_FRACAO_MEDIO = 0.50  # ≥50% do teto (ex.: ≥12.5% no padrão / ≥25% na reforma) → medio

# VELOCIDADE: dias do início da execução até o 1º aditivo de valor abaixo dos quais o caso agrava.
_DIAS_ADITIVO_PRECOCE = 90


def teto_art125(tipo_objeto: str | None) -> float:
    """Teto de acréscimos do art.125: 50% para REFORMA de edifício/equipamento, 25% nos demais casos."""
    t = (tipo_objeto or "").strip().lower()
    return _TETO_REFORMA if t.startswith("reforma") else _TETO_PADRAO


# Rubrica (1): natureza da JUSTIFICATIVA de um aditivo. LLM-opcional; degrada honesto.
_RUBRICA_JUSTIFICATIVA = {
    "fato_superveniente_verificavel": "ausente",   # evento datado e documentado (laudo/boletim/decisão) → exculpa
    "falha_de_projeto_admitida": "forte",          # 'quantitativos subestimados' em aditivo precoce → desenho deliberado
    "generica": "medio",                           # justificativa vaga sem documento → anomalia a confirmar
}

# Rubrica (2): PERTINÊNCIA do objeto aditado frente ao objeto original. LLM-opcional; degrada honesto.
_RUBRICA_PERTINENCIA = {
    "mesmo_objeto_detalhado": "ausente",     # detalhamento/quantitativo do mesmo objeto → legítimo
    "objeto_novo_disfarcado": "forte",       # escopo novo que exigiria novo certame → forte AUTÔNOMO
}


def _data(v) -> date | None:
    """Parseia data tolerante a formatos comuns (ISO / br). Ausente/inválida → None (honesto)."""
    if isinstance(v, date) and not isinstance(v, datetime):
        return v
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, str):
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y-%m-%dT%H:%M:%S"):
            try:
                return datetime.strptime(v[:19] if "T" in v else v[:10], fmt).date()
            except ValueError:
                continue
    return None


def _tipo_aditivo(a: dict) -> str:
    """Tipo do aditivo: 'valor' | 'prazo' | 'objeto' | ''. Default infere por presença de valor."""
    t = str(a.get("tipo") or "").strip().lower()
    if t:
        return t
    return "valor" if a.get("valor") not in (None, 0, 0.0) else ""


def _valor_aditivo(a: dict) -> float:
    """Valor (acréscimo +, supressão -) de um aditivo. Não-numérico/ausente → 0.0 (não inventa)."""
    v = a.get("valor")
    try:
        return float(v) if v is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _conta_no_teto(a: dict) -> bool:
    """Um aditivo entra no cálculo do teto do art.125? SÓ se mexe em VALOR. Aditivo de só-prazo NÃO conta
    (tem outra análise — X2). Aditivo de objeto com valor conta pelo valor."""
    return _tipo_aditivo(a) in ("valor", "objeto") and _valor_aditivo(a) != 0.0


class X1CrescimentoAditivo(Detector):
    """Detector X1 — crescimento aditivo / contrato que engorda (art.125, Lei 14.133/2021).

    `avaliar(contexto)` espera:
      contexto["processo"]: id do contrato/processo.
      contexto["valor_inicial"]: float (ESSENCIAL) — valor inicial do contrato em R$.
      contexto["tipo_objeto"]: 'obra' | 'reforma' | 'servico' | ... — define o teto (reforma de edifício/
          equipamento = 50%; demais = 25%). Ausente → assume teto padrão de 25%.
      contexto["aditivos"]: list[dict] (ESSENCIAL), cada um com {data?, tipo('valor'|'prazo'|'objeto'),
          valor (acréscimo +, supressão -), justificativa?, descricao_objeto?, _rubrica_justificativa?}.
      contexto["data_inicio_execucao"]: opcional — data de início da execução (para a velocidade até o 1º aditivo).
      contexto["indice_atualizacao"]: opcional float (default 1.0) — índice de atualização do valor inicial.
      contexto["_rubricas_justificativa"]: opcional list[dict] — atalho de teste das rubricas por aditivo (sem rede).
      contexto["_rubrica_pertinencia"]: opcional dict — atalho de teste da rubrica de pertinência (sem rede).
      contexto["gerar"]: opcional callable (prompt, sistema)->str — motor LLM das duas rubricas; ausente → nao_avaliavel.

    Honesto: sem `valor_inicial` (>0) ou sem `aditivos` → nao_avaliavel (campo ausente ≠ 0)."""

    id = "X1"
    nome = "Crescimento aditivo (contrato que engorda)"
    familia = "execucao"  # X1 — peso 0.8 (execução); estouro do teto vira score crítico (violação art.125)

    def avaliar(self, contexto: dict) -> ResultadoDetector:
        processo = str(contexto.get("processo") or contexto.get("id") or "?")
        res = self._novo(processo, status="nao_avaliavel")

        # ── honestidade: campos essenciais ──
        try:
            valor_inicial = float(contexto.get("valor_inicial")) if contexto.get("valor_inicial") is not None else None
        except (TypeError, ValueError):
            valor_inicial = None
        if not valor_inicial or valor_inicial <= 0:
            res.motivo_refutacao = ("nao_avaliavel: valor_inicial ausente/inválido — sem o valor inicial do contrato "
                                    "não há base para o teto do art.125 (campo ausente ≠ 0)")
            res.valores = {"tem_valor_inicial": False}
            return res

        aditivos = contexto.get("aditivos")
        if not aditivos:
            res.motivo_refutacao = ("nao_avaliavel: sem aditivos no contexto — nada a aferir quanto ao crescimento "
                                    "aditivo (campo ausente ≠ 0)")
            res.valores = {"tem_valor_inicial": True, "n_aditivos": 0}
            return res
        aditivos = [a for a in aditivos if isinstance(a, dict)]

        tipo_objeto = contexto.get("tipo_objeto")
        teto = teto_art125(tipo_objeto)
        try:
            indice = float(contexto.get("indice_atualizacao") or 1.0)
        except (TypeError, ValueError):
            indice = 1.0
        if indice <= 0:
            indice = 1.0
        valor_atualizado = valor_inicial * indice

        # ── CÓDIGO: acréscimos e supressões SEPARADAMENTE (não se compensam) ──
        aditivos_valor = [a for a in aditivos if _conta_no_teto(a)]
        acrescimos = sum(v for v in (_valor_aditivo(a) for a in aditivos_valor) if v > 0)
        supressoes = sum(-v for v in (_valor_aditivo(a) for a in aditivos_valor) if v < 0)
        pct_acrescimo = acrescimos / valor_atualizado if valor_atualizado else 0.0
        pct_supressao = supressoes / valor_atualizado if valor_atualizado else 0.0

        valores: dict = {
            "valor_inicial": round(valor_inicial, 2),
            "indice_atualizacao": indice,
            "valor_inicial_atualizado": round(valor_atualizado, 2),
            "tipo_objeto": tipo_objeto,
            "teto_art125": teto,
            "n_aditivos": len(aditivos),
            "n_aditivos_de_valor": len(aditivos_valor),
            "acrescimos_total": round(acrescimos, 2),
            "supressoes_total": round(supressoes, 2),
            "pct_acrescimo": round(pct_acrescimo, 4),
            "pct_supressao": round(pct_supressao, 4),
            "estouro_teto": pct_acrescimo > teto,
        }

        score = 0.0
        razoes: list[str] = []
        estourou = pct_acrescimo > teto

        if estourou:
            score = ancora("critico")
            razoes.append(
                f"ESTOURO do teto do art.125: acréscimos somam R$ {acrescimos:,.2f} = {pct_acrescimo*100:.1f}% do "
                f"valor inicial atualizado (R$ {valor_atualizado:,.2f}), acima do teto de {teto*100:.0f}%")
            res.add_evidencia(
                fonte="cálculo do teto art.125 (Lei 14.133/2021)",
                trecho=(f"acréscimos=R$ {acrescimos:,.2f} ({pct_acrescimo*100:.1f}%) > teto {teto*100:.0f}% sobre "
                        f"valor inicial atualizado R$ {valor_atualizado:,.2f} (índice {indice})"))
        elif pct_acrescimo >= teto * _FRACAO_FORTE:
            score = max(score, ancora("forte"))
            razoes.append(
                f"acréscimo rente ao teto: {pct_acrescimo*100:.1f}% (teto {teto*100:.0f}%) — margem mínima ao limite")
            res.add_evidencia(
                fonte="cálculo do teto art.125",
                trecho=(f"acréscimos R$ {acrescimos:,.2f} = {pct_acrescimo*100:.1f}% do valor atualizado "
                        f"R$ {valor_atualizado:,.2f}; rente ao teto {teto*100:.0f}%"))
        elif pct_acrescimo >= teto * _FRACAO_MEDIO:
            score = max(score, ancora("medio"))
            razoes.append(f"acréscimo na metade do teto: {pct_acrescimo*100:.1f}% (teto {teto*100:.0f}%)")
            res.add_evidencia(
                fonte="cálculo do teto art.125",
                trecho=f"acréscimos {pct_acrescimo*100:.1f}% do valor atualizado (teto {teto*100:.0f}%)")

        # ── VELOCIDADE: dias do início da execução até o 1º aditivo de VALOR → agrava ──
        inicio = _data(contexto.get("data_inicio_execucao"))
        dias_ate_1o = None
        datas_valor = sorted(d for d in (_data(a.get("data")) for a in aditivos_valor) if d)
        if inicio and datas_valor:
            dias_ate_1o = (datas_valor[0] - inicio).days
            valores["dias_ate_1o_aditivo_valor"] = dias_ate_1o
            if 0 <= dias_ate_1o < _DIAS_ADITIVO_PRECOCE and score > 0:
                score = min(1.0, score + 0.10)
                razoes.append(
                    f"1º aditivo de valor PRECOCE: {dias_ate_1o} dias após o início da execução "
                    f"(< {_DIAS_ADITIVO_PRECOCE}) — sugere projeto deliberadamente incompleto")
                res.add_evidencia(
                    fonte="velocidade até o 1º aditivo de valor",
                    trecho=f"início={inicio.isoformat()} → 1º aditivo de valor={datas_valor[0].isoformat()} ({dias_ate_1o} dias)")

        # ── PARTE SUBJETIVA (LLM-opcional): rubrica (1) justificativa por aditivo + (2) pertinência ──
        rub_just = self._avaliar_justificativa(aditivos, contexto, dias_ate_1o=dias_ate_1o)
        valores["justificativas"] = [r["status"] for r in rub_just]
        for r in rub_just:
            if r["status"] == "falha_de_projeto_admitida":
                score = max(score, ancora("forte"))
                razoes.append(f"rubrica justificativa: falha de projeto admitida ('quantitativos subestimados') "
                              f"em aditivo {'precoce ' if r.get('precoce') else ''}— confirma desenho deliberado")
                if r.get("trecho"):
                    res.add_evidencia(fonte="justificativa do termo aditivo", trecho=str(r["trecho"])[:160])

        pert = self._avaliar_pertinencia(aditivos, contexto)
        valores["pertinencia"] = pert["status"]
        if pert["status"] == "objeto_novo_disfarcado":
            score = max(score, ancora("forte"))
            razoes.append("rubrica pertinência: objeto NOVO disfarçado de aditivo (escopo que exigiria novo certame) "
                          "— forte autônomo")
            if pert.get("trecho"):
                res.add_evidencia(fonte="descrição do acréscimo × objeto original", trecho=str(pert["trecho"])[:160])

        if score <= 0:
            res.status = "descartado"
            res.motivo_refutacao = (
                f"acréscimos sob controle: {pct_acrescimo*100:.1f}% do valor atualizado (teto {teto*100:.0f}%), "
                "sem rubrica de falha-de-projeto/objeto-novo — sem indício de crescimento aditivo abusivo")
            res.valores = valores
            res.explicacao_inocente = ("acréscimos dentro do limite legal e justificados por supervenientes "
                                       "documentados — aditivo é instrumento lícito de adequação contratual")
            return res

        res.score = round(score, 4)
        res.status = "confirmado"
        res.valores = valores
        res.motivo_refutacao = "; ".join(razoes)
        res.explicacao_inocente = (
            "FALSO POSITIVO a descartar (spec X1): obras longas sofrem supervenientes REAIS (geologia, chuva, "
            "desapropriação) — se houver evento DATADO e DOCUMENTADO (laudo/boletim/decisão judicial), o acréscimo "
            "pode ser legítimo. Aditivo de PRAZO sem valor não consome o teto (análise X2). Cruzar com a justificativa "
            "documental de cada termo antes de representar.")
        return res

    # ───────────────────────────── rubricas LLM-opcionais ─────────────────────────────
    def _avaliar_justificativa(self, aditivos: list[dict], contexto: dict, *, dias_ate_1o=None) -> list[dict]:
        """Rubrica (1) por aditivo: classifica a JUSTIFICATIVA. Atalhos de teste: rubrica pré-classificada em
        `contexto['_rubricas_justificativa']` (lista alinhada aos aditivos) ou em `a['_rubrica_justificativa']`.
        Sem rubrica e sem LLM → nao_avaliavel honesto (não inventa o juízo subjetivo)."""
        pre_lista = contexto.get("_rubricas_justificativa")
        resultados: list[dict] = []
        gerar = contexto.get("gerar")
        for i, a in enumerate(aditivos):
            pre = None
            if isinstance(pre_lista, (list, tuple)) and i < len(pre_lista):
                pre = pre_lista[i]
            if pre is None:
                pre = a.get("_rubrica_justificativa")
            # aditivo precoce: 1º aditivo de valor dentro da janela
            precoce = bool(dias_ate_1o is not None and 0 <= dias_ate_1o < _DIAS_ADITIVO_PRECOCE)
            if pre is not None:
                nivel, _score, motivo = avaliar_rubrica(pre, _RUBRICA_JUSTIFICATIVA)
                if nivel is None:
                    resultados.append({"status": "nao_avaliavel", "motivo": motivo, "precoce": precoce})
                else:
                    classe = (pre.get("nivel") or pre.get("classificacao") or "").strip().lower()
                    resultados.append({"status": classe, "motivo": motivo,
                                       "trecho": pre.get("trecho") or pre.get("citacao"), "precoce": precoce})
                continue
            if gerar is None:
                resultados.append({"status": "nao_avaliavel",
                                   "motivo": "LLM ausente — justificativa não auditada (honesto)", "precoce": precoce})
                continue
            sistema = (
                "Você é auditor de controle externo avaliando a JUSTIFICATIVA de um termo aditivo. Classifique-a "
                "conforme a rubrica fechada. Exige-se evento DATADO e DOCUMENTADO (laudo/boletim/decisão) para "
                "'fato_superveniente_verificavel'; 'quantitativos subestimados/erro de projeto' é "
                "'falha_de_projeto_admitida'; vago/sem documento é 'generica'. Responda SOMENTE com JSON: "
                '{"nivel":"fato_superveniente_verificavel|falha_de_projeto_admitida|generica",'
                '"trecho":"<citação literal da justificativa>"}. Sem trecho, não classifique.')
            just = str(a.get("justificativa") or "")[:1000]
            prompt = f"JUSTIFICATIVA DO TERMO ADITIVO:\n{just}\n\nClassifique a natureza da justificativa."
            try:
                raw = gerar(prompt, sistema)
            except Exception as ex:  # noqa: BLE001 — degrada honesto
                resultados.append({"status": "nao_avaliavel", "motivo": f"LLM indisponível ({str(ex)[:50]})",
                                   "precoce": precoce})
                continue
            from compliance_agent.detectores.base import _parse_json
            dados = _parse_json(raw)
            nivel, _score, motivo = avaliar_rubrica(dados, _RUBRICA_JUSTIFICATIVA)
            if nivel is None or not isinstance(dados, dict):
                resultados.append({"status": "nao_avaliavel", "motivo": motivo, "precoce": precoce})
            else:
                resultados.append({"status": (dados.get("nivel") or "").strip().lower(), "motivo": motivo,
                                   "trecho": dados.get("trecho"), "precoce": precoce})
        return resultados

    def _avaliar_pertinencia(self, aditivos: list[dict], contexto: dict) -> dict:
        """Rubrica (2): PERTINÊNCIA do objeto aditado frente ao objeto original. Atalho de teste:
        `contexto['_rubrica_pertinencia']`. Sem rubrica e sem LLM → nao_avaliavel honesto."""
        pre = contexto.get("_rubrica_pertinencia")
        if pre is not None:
            nivel, _score, motivo = avaliar_rubrica(pre, _RUBRICA_PERTINENCIA)
            if nivel is None:
                return {"status": "nao_avaliavel", "motivo": motivo}
            return {"status": (pre.get("nivel") or pre.get("classificacao") or "").strip().lower(),
                    "motivo": motivo, "trecho": pre.get("trecho") or pre.get("citacao")}
        gerar = contexto.get("gerar")
        if gerar is None:
            return {"status": "nao_avaliavel", "motivo": "LLM ausente — pertinência do objeto não auditada (honesto)"}
        objeto_original = str(contexto.get("objeto") or contexto.get("objeto_original") or "")[:300]
        descricoes = "\n".join(
            f"- {str(a.get('descricao_objeto') or '')[:160]}"
            for a in aditivos if a.get("descricao_objeto"))
        sistema = (
            "Você é auditor de controle externo avaliando a PERTINÊNCIA de objetos aditados frente ao objeto "
            "original do contrato. Classifique conforme a rubrica fechada: 'mesmo_objeto_detalhado' (detalhamento/"
            "quantitativo do mesmo objeto) ou 'objeto_novo_disfarcado' (escopo novo que exigiria NOVO certame). "
            "Responda SOMENTE com JSON: "
            '{"nivel":"mesmo_objeto_detalhado|objeto_novo_disfarcado","trecho":"<citação literal>"}. '
            "Sem trecho, não classifique.")
        prompt = (f"OBJETO ORIGINAL: {objeto_original}\n\nDESCRIÇÃO DOS ACRÉSCIMOS:\n{descricoes}\n\n"
                  "Os acréscimos são do mesmo objeto detalhado ou objeto novo disfarçado?")
        try:
            raw = gerar(prompt, sistema)
        except Exception as ex:  # noqa: BLE001 — degrada honesto
            return {"status": "nao_avaliavel", "motivo": f"LLM indisponível ({str(ex)[:50]})"}
        from compliance_agent.detectores.base import _parse_json
        dados = _parse_json(raw)
        nivel, _score, motivo = avaliar_rubrica(dados, _RUBRICA_PERTINENCIA)
        if nivel is None or not isinstance(dados, dict):
            return {"status": "nao_avaliavel", "motivo": motivo}
        return {"status": (dados.get("nivel") or "").strip().lower(), "motivo": motivo, "trecho": dados.get("trecho")}
