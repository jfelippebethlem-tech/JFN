# -*- coding: utf-8 -*-
"""P5 · EMERGÊNCIA FABRICADA (spec V2 do dono, §2/P5).

Mecanismo: a administração deixa a situação se deteriorar (ou simplesmente alega urgência) para contratar
diretamente por dispensa emergencial (art. 75, VIII), escolhendo o fornecedor sem competição. A "emergência
ficta" decorrente de DESÍDIA é a forma mais comum.

PARÂMETROS OBJETIVOS (no CÓDIGO — limiar nunca vai ao prompt do LLM, spec §1.3):
  • INÉRCIA: vencimento de contrato anterior CONHECIDO × data da dispensa — quanto antes o órgão sabia, mais
    desídia. Dispensa aberta depois (ou às vésperas) de um vencimento conhecido ................... 'forte'
      – dispensa aberta APÓS o vencimento (serviço já interrompido por inércia) ................. 'forte'
      – dispensa aberta < 30 dias antes de um vencimento conhecido com meses de antecedência .... 'medio'
  • PRÉ-ESCOLHA: data da proposta do contratado ANTERIOR à abertura do processo (fornecedor já escolhido) .. 'forte'
  • RECORRÊNCIA: ≥3 dispensas emergenciais do órgão nos últimos 24 meses ........................... 'medio'

PARTE SUBJETIVA (LLM-OPCIONAL, degrada honesto), duas rubricas fechadas:
  • NEXO da justificativa com risco concreto [risco_concreto_documentado / risco_generico / sem_nexo].
    'sem_nexo'/'risco_generico' + inércia objetiva → confirma. Sem LLM → nao_avaliavel.
  • PREVISIBILIDADE do evento [imprevisivel_genuino / previsivel]. 'previsivel' → confirma a inércia.

TESTE EXCULPATÓRIO (spec): DESASTRE real (enchente/incêndio/rompimento — verificar Defesa Civil/imprensa) legitima
a dispensa mesmo com preço acima do usual (só permanece o componente de preço); CERTAME anterior FRACASSADO/deserto
documentado é exculpatória parcial da inércia (o órgão tentou) — verificar se o fracasso não foi induzido (E1/E2).

HONESTIDADE JFN: indício ≠ acusação; sem datas do processo → `nao_avaliavel` (campo ausente ≠ 0); nunca inventa data.
"""
from __future__ import annotations

from datetime import date, datetime

from compliance_agent.detectores.base import (
    Detector,
    ResultadoDetector,
    ancora,
    avaliar_rubrica,
)

# Rubrica fechada de nexo justificativa × risco concreto (spec P5).
_RUBRICA_NEXO = {
    "risco_concreto_documentado": "ausente",   # risco real documentado → não pontua
    "risco_generico": "medio",                  # risco genérico alegado → médio
    "sem_nexo": "forte",                        # sem nexo com risco concreto → forte
}

# Rubrica fechada de previsibilidade do evento (spec P5).
_RUBRICA_PREVISIBILIDADE = {
    "imprevisivel_genuino": "ausente",   # desastre/falha súbita → não pontua
    "previsivel": "forte",               # vencimento/desgaste conhecido → confirma inércia
}


def _to_date(v) -> date | None:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, str):
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y %H:%M", "%d/%m/%Y"):
            try:
                return datetime.strptime(v.strip()[:len(fmt) + 2], fmt).date()
            except ValueError:
                continue
        for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
            try:
                return datetime.strptime(v.strip()[:10], fmt).date()
            except ValueError:
                continue
    return None


def _delta_dias(a: date | None, b: date | None) -> int | None:
    """Dias de `a` até `b` (b - a). None se faltar alguma data."""
    if a is None or b is None:
        return None
    return (b - a).days


class P5EmergenciaFabricada(Detector):
    """Detector P5 — emergência fabricada (dispensa emergencial, art. 75, VIII, Lei 14.133/2021).

    `avaliar(contexto)` espera:
      contexto["processo"]: id do processo.
      contexto["data_abertura_processo"]: data de abertura do processo de dispensa (str ISO/BR, date, datetime).
      contexto["data_contrato"] (opcional): data do contrato emergencial.
      contexto["vigencia"] (opcional): vigência do contrato.
      contexto["fato_gerador"] (opcional): {descricao, data} do evento alegado como emergência.
      contexto["contratado"] (opcional): identificação do contratado.
      contexto["data_proposta"] (opcional): data da proposta do contratado (pré-escolha se < abertura).
      contexto["contrato_anterior"] (opcional): {vencimento} do contrato anterior do mesmo objeto.
      contexto["emergencias_orgao_24m"] (opcional int|list): nº (ou lista) de dispensas emergenciais do órgão/24m.
      contexto["desastre_confirmado"] (opcional bool): exculpatória — desastre real (Defesa Civil/imprensa).
      contexto["certame_anterior_fracassado"] (opcional bool): exculpatória parcial da inércia (o órgão tentou).
      contexto["gerar"] (opcional): callable p/ as rubricas (LLM-opcional, degrada honesto).

    Honesto: sem data de abertura do processo → nao_avaliavel (campo ausente ≠ 0); nunca inventa data."""

    id = "P5"
    nome = "Emergência fabricada"
    familia = "desenho_certame"  # dispensa direta na fase de planejamento (peso 0.6 na convergência §7.2)

    def avaliar(self, contexto: dict) -> ResultadoDetector:
        processo = str(contexto.get("processo") or contexto.get("id") or "?")
        res = self._novo(processo, status="nao_avaliavel")

        dt_abertura = _to_date(contexto.get("data_abertura_processo"))
        if dt_abertura is None:
            res.motivo_refutacao = ("nao_avaliavel: sem data de abertura do processo de dispensa "
                                    "(campo ausente ≠ 0) — sem base para os deltas temporais")
            res.valores = {"tem_abertura": False}
            return res

        dt_proposta = _to_date(contexto.get("data_proposta"))
        contrato_ant = contexto.get("contrato_anterior") or {}
        dt_venc_ant = _to_date(contrato_ant.get("vencimento"))
        emerg = contexto.get("emergencias_orgao_24m")
        n_emerg = emerg if isinstance(emerg, int) else (len(emerg) if isinstance(emerg, (list, tuple)) else None)
        desastre = bool(contexto.get("desastre_confirmado"))
        certame_fracassado = bool(contexto.get("certame_anterior_fracassado"))

        valores: dict = {
            "data_abertura_processo": dt_abertura.isoformat(),
            "vencimento_anterior": dt_venc_ant.isoformat() if dt_venc_ant else None,
            "data_proposta": dt_proposta.isoformat() if dt_proposta else None,
            "emergencias_orgao_24m": n_emerg,
            "desastre_confirmado": desastre,
        }

        score = 0.0
        razoes: list[str] = []
        tem_inercia = False

        # ── REGRA OBJETIVA 1: inércia (vencimento conhecido × abertura da dispensa) ──
        delta_venc = _delta_dias(dt_venc_ant, dt_abertura)  # >0 = abriu APÓS o vencimento
        valores["delta_vencimento_abertura_dias"] = delta_venc
        if delta_venc is not None:
            if delta_venc >= 0:
                tem_inercia = True
                score = max(score, ancora("forte"))
                razoes.append(f"dispensa aberta {delta_venc} dia(s) APÓS o vencimento conhecido do contrato anterior "
                              "(serviço deixado deteriorar — inércia/desídia)")
                res.add_evidencia(fonte="linha do tempo do objeto",
                                  trecho=f"vencimento anterior {dt_venc_ant.isoformat()} × abertura dispensa "
                                         f"{dt_abertura.isoformat()} (Δ={delta_venc}d, abertura após vencimento)")
            elif -30 <= delta_venc < 0:
                tem_inercia = True
                score = max(score, ancora("medio"))
                razoes.append(f"dispensa aberta só {-delta_venc} dia(s) antes de um vencimento conhecido — inércia "
                              "(deixou para a última hora)")
                res.add_evidencia(fonte="linha do tempo do objeto",
                                  trecho=f"vencimento anterior {dt_venc_ant.isoformat()} × abertura "
                                         f"{dt_abertura.isoformat()} (Δ={delta_venc}d, às vésperas)")

        # ── REGRA OBJETIVA 2: pré-escolha (proposta antes da abertura do processo) ──
        delta_prop = _delta_dias(dt_proposta, dt_abertura)  # >0 = proposta ANTES da abertura
        valores["delta_proposta_abertura_dias"] = delta_prop
        if delta_prop is not None and delta_prop > 0:
            score = max(score, ancora("forte"))
            razoes.append(f"proposta do contratado é {delta_prop} dia(s) ANTERIOR à abertura do processo "
                          "(fornecedor pré-escolhido)")
            res.add_evidencia(fonte="proposta × processo",
                              trecho=f"proposta {dt_proposta.isoformat()} anterior à abertura {dt_abertura.isoformat()} "
                                     f"(Δ={delta_prop}d — pré-escolha)")

        # ── REGRA OBJETIVA 3: recorrência de emergências (24m) ──
        if isinstance(n_emerg, int) and n_emerg >= 3:
            score = max(score, ancora("medio"))
            razoes.append(f"{n_emerg} dispensas emergenciais do órgão em 24 meses — recorrência (emergência como rotina)")
            res.add_evidencia(fonte="histórico do órgão (24m)",
                              trecho=f"{n_emerg} dispensas emergenciais nos últimos 24 meses")

        if score <= 0:
            res.status = "descartado"
            res.motivo_refutacao = ("sem inércia objetiva (vencimento × abertura), sem pré-escolha (proposta posterior "
                                    "à abertura) e sem recorrência — emergência aparentemente legítima")
            res.valores = valores
            res.explicacao_inocente = "dispensa emergencial tempestiva, sem indício de desídia ou pré-escolha"
            return res

        # ── PARTE SUBJETIVA (LLM-opcional): nexo do risco + previsibilidade ──
        nexo = self._avaliar_rubrica(contexto, "_rubrica_nexo", _RUBRICA_NEXO,
                                     self._prompt_nexo(contexto))
        valores["nexo_risco"] = nexo["status"]
        if nexo["status"] == "risco_concreto_documentado":
            score = min(score, ancora("fraco"))
            razoes.append("rubrica nexo: risco concreto documentado — exculpatória (rebaixado)")
        elif nexo["status"] == "sem_nexo" and tem_inercia:
            score = max(score, ancora("forte"))
            razoes.append("rubrica nexo: sem nexo com risco concreto + inércia objetiva — confirma")

        prev = self._avaliar_rubrica(contexto, "_rubrica_previsibilidade", _RUBRICA_PREVISIBILIDADE,
                                     self._prompt_previsibilidade(contexto))
        valores["previsibilidade"] = prev["status"]
        if prev["status"] == "previsivel" and tem_inercia:
            score = max(score, ancora("forte"))
            razoes.append("rubrica previsibilidade: evento previsível (vencimento/desgaste) + inércia — confirma")
        elif prev["status"] == "imprevisivel_genuino":
            score = min(score, ancora("medio"))
            razoes.append("rubrica previsibilidade: evento imprevisível genuíno — exculpatória parcial (rebaixado)")

        # ── EXCULPATÓRIAS estruturais do spec ──
        if desastre:
            # desastre real legitima a dispensa; só permanece o componente de preço (P3) → rebaixa forte
            score = min(score, ancora("fraco"))
            razoes.append("DESASTRE real confirmado (Defesa Civil/imprensa) — legitima a dispensa; só resta o "
                          "componente de preço (P3) — rebaixado")
        if certame_fracassado:
            # certame anterior fracassado/deserto documentado é exculpatória parcial da inércia
            score = min(score, ancora("medio"))
            razoes.append("certame anterior FRACASSADO/deserto documentado — exculpatória parcial da inércia "
                          "(o órgão tentou; verificar se o fracasso não foi induzido por E1/E2)")

        res.score = round(score, 4)
        res.status = "confirmado"
        res.valores = valores
        res.motivo_refutacao = "; ".join(razoes)
        res.explicacao_inocente = ("FALSO POSITIVO a descartar (spec P5): DESASTRE/fato súbito real (enchente, "
                                   "incêndio, rompimento) legitima a dispensa mesmo com preço acima do usual — "
                                   "verificar Defesa Civil/imprensa; CERTAME anterior fracassado/deserto documentado "
                                   "é exculpatória parcial da inércia (verificar se o fracasso não foi induzido).")
        return res

    @staticmethod
    def _prompt_nexo(contexto: dict) -> str:
        fg = contexto.get("fato_gerador") or {}
        return (f"FATO GERADOR alegado: {str(fg.get('descricao') or '')[:400]}\n\n"
                "Classifique o NEXO entre a justificativa e um risco concreto a pessoas/serviço essencial.")

    @staticmethod
    def _prompt_previsibilidade(contexto: dict) -> str:
        fg = contexto.get("fato_gerador") or {}
        return (f"FATO GERADOR alegado: {str(fg.get('descricao') or '')[:400]}\n\n"
                "Classifique a PREVISIBILIDADE do evento (vencimento/desgaste conhecido = previsível).")

    def _avaliar_rubrica(self, contexto: dict, chave_pre: str, escala: dict, prompt_user: str) -> dict:
        """Rubrica fechada (nexo ou previsibilidade). Atalho de teste: `chave_pre` injetado no contexto.
        Sem rubrica e sem LLM → nao_avaliavel honesto."""
        pre = contexto.get(chave_pre)
        if pre is not None:
            nivel, _score, motivo = avaliar_rubrica(pre, escala)
            if nivel is None:
                return {"status": "nao_avaliavel", "motivo": motivo}
            return {"status": (pre.get("nivel") or pre.get("classificacao") or "").strip().lower(), "motivo": motivo}
        gerar = contexto.get("gerar")
        if gerar is None:
            return {"status": "nao_avaliavel", "motivo": "LLM ausente — rubrica não auditada (honesto)"}
        sistema = (
            "Você é auditor de controle externo. Classifique conforme a rubrica fechada. Responda SOMENTE com JSON: "
            '{"nivel":"<um nível da escala>","trecho":"<citação literal dos autos>"}. Sem trecho, não classifique.'
        )
        try:
            raw = gerar(prompt_user, sistema)
        except Exception as ex:  # noqa: BLE001 — degrada honesto
            return {"status": "nao_avaliavel", "motivo": f"LLM indisponível ({str(ex)[:50]})"}
        from compliance_agent.detectores.base import _parse_json
        dados = _parse_json(raw)
        nivel, _score, motivo = avaliar_rubrica(dados, escala)
        if nivel is None or not isinstance(dados, dict):
            return {"status": "nao_avaliavel", "motivo": motivo}
        return {"status": (dados.get("nivel") or "").strip().lower(), "motivo": motivo}
