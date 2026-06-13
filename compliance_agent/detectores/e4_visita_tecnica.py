# -*- coding: utf-8 -*-
"""E4 · VISITA TÉCNICA COMO FILTRO (spec V2 do dono, §3/E4).

Mecanismo: a visita técnica presencial OBRIGATÓRIA revela ao órgão (e ao cartel) QUEM pretende competir,
permitindo pressão sobre entrantes, além de criar custo de participação que filtra licitantes. A jurisprudência
consolidada (TCU/STJ) admite a SUBSTITUIÇÃO da visita presencial por DECLARAÇÃO de conhecimento do local — logo,
exigir visita presencial obrigatória SEM alternativa de declaração é o sinal central.

PARÂMETROS OBJETIVOS (no CÓDIGO — limiar nunca vai ao prompt do LLM, spec §1.3):
  • Visita OBRIGATÓRIA sem alternativa (declaração de conhecimento) ............... 'medio' (candidato)
  • + agendamento CONTROLADO / janela única estreita (≤ 2 dias) .................. agrava ('forte')
  • Se houver lista de visitantes: TAXA DE EVASÃO pós-visita
      (visitaram mas NÃO apresentaram proposta) — evasão alta (≥ 50%) ............ 'forte'
  • Cruzar evadidos com J1/J4 (mesmos CNPJs que 'desistem' em outros certames) ... agrava ('forte')

PARTE SUBJETIVA (LLM-OPCIONAL, degrada honesto): rubrica fechada de NECESSIDADE REAL da visita para formular
proposta [indispensavel / dispensavel]. 'indispensavel' = condições locais determinantes do preço (obra em terreno
específico) → exculpa. 'dispensavel' = objeto padronizado → 'dispensavel' + obrigatória CONFIRMA ('forte').
Evidência exigida: objeto + cláusula. Sem LLM/rubrica → necessidade `nao_avaliavel` (não inventamos o juízo); o
flag objetivo permanece.

TESTE EXCULPATÓRIO (spec): obras e serviços de ENGENHARIA em locais com condições PECULIARES legitimam a visita —
nesses casos só pontuam o agendamento controlado e a correlação de evasão (a obrigatoriedade em si não pontua).
A rubrica 'indispensavel' materializa essa exculpatória.

HONESTIDADE JFN: indício ≠ acusação; presunção de regularidade. SEM cláusula de visita no contexto → `nao_avaliavel`
(campo ausente ≠ 0 — não dá para avaliar uma cláusula que não temos); a taxa de evasão só é calculada quando há
lista de visitantes registrada nos autos — nunca inventamos número.
"""
from __future__ import annotations

from compliance_agent.detectores.base import (
    Detector,
    ResultadoDetector,
    ancora,
    avaliar_rubrica,
)

# Rubrica de necessidade real da visita para formular proposta (spec E4).
_RUBRICA_NECESSIDADE = {
    "indispensavel": "ausente",   # condições locais determinantes do preço (obra em terreno específico) → exculpa
    "dispensavel": "forte",       # objeto padronizado → visita obrigatória CONFIRMA
}

# Limiar objetivo de evasão pós-visita (no CÓDIGO, nunca no prompt).
_EVASAO_FORTE = 0.50            # ≥ 50% dos visitantes não viraram proponentes → forte
_JANELA_ESTREITA_DIAS = 2      # janela única ≤ 2 dias = agendamento de fato controlado


def _norm_cnpj(c) -> str:
    """Normaliza um CNPJ a só dígitos (compara CNPJs de listas heterogêneas sem inventar)."""
    return "".join(ch for ch in str(c) if ch.isdigit())


class E4VisitaTecnica(Detector):
    """Detector E4 — visita técnica presencial obrigatória como filtro anticompetitivo.

    `avaliar(contexto)` espera:
      contexto["processo"]: id do certame.
      contexto["visita"]: dict da cláusula de visita do edital, OU None/ausente → nao_avaliavel.
          {obrigatoria: bool,
           alternativa_declaracao: bool,          # admite declaração de conhecimento do local? (jurisprudência)
           agendamento_controlado: bool?,         # agendamento individual/controlado pelo órgão
           janela_dias: int?}                     # nº de dias da janela de visita (≤2 = janela estreita)
      contexto["visitantes"]: list[cnpj] (opcional) — quem registrou visita nos autos.
      contexto["licitantes"]: list[cnpj] (opcional) — quem apresentou proposta.
      contexto["evadidos_em_outros_certames"]: list[cnpj] (opcional) — CNPJs que 'desistem' em outros certames (J1/J4).
      contexto["objeto"]: str (opcional) — descrição do objeto (vai como evidência da rubrica).
      contexto["gerar"] (opcional): callable p/ a rubrica de necessidade — LLM-opcional.
      contexto["_rubrica_necessidade"] (opcional): rubrica pré-classificada (atalho de teste, sem rede).

    Honesto: sem `visita` → nao_avaliavel (campo ausente ≠ 0); taxa de evasão só com lista de visitantes."""

    id = "E4"
    nome = "Visita técnica como filtro"
    familia = "desenho_certame"  # E1–E6 (peso 0.6 na convergência §7.2)

    def avaliar(self, contexto: dict) -> ResultadoDetector:
        processo = str(contexto.get("processo") or contexto.get("id") or "?")
        res = self._novo(processo, status="nao_avaliavel")

        visita = contexto.get("visita")
        if not isinstance(visita, dict):
            res.motivo_refutacao = "nao_avaliavel: sem cláusula de visita técnica no contexto (campo ausente ≠ 0)"
            res.valores = {"tem_clausula_visita": False}
            return res

        obrigatoria = bool(visita.get("obrigatoria"))
        alternativa = bool(visita.get("alternativa_declaracao"))
        agendamento = bool(visita.get("agendamento_controlado"))
        janela = visita.get("janela_dias")
        janela_estreita = isinstance(janela, int) and janela <= _JANELA_ESTREITA_DIAS

        objeto = contexto.get("objeto")

        # ── taxa de evasão pós-visita (CÓDIGO) — só quando há lista de visitantes registrada ──
        evasao = self._taxa_evasao(contexto.get("visitantes"), contexto.get("licitantes"))

        # ── correlação de evasão com J1/J4 (mesmos CNPJs desistem em outros certames) ──
        evadidos = evasao["evadidos"] if evasao else []
        outros = {_norm_cnpj(c) for c in (contexto.get("evadidos_em_outros_certames") or []) if _norm_cnpj(c)}
        evadidos_recorrentes = [c for c in evadidos if c in outros]

        valores: dict = {
            "tem_clausula_visita": True,
            "obrigatoria": obrigatoria,
            "alternativa_declaracao": alternativa,
            "agendamento_controlado": agendamento,
            "janela_dias": janela if isinstance(janela, int) else None,
            "janela_estreita": janela_estreita,
            "taxa_evasao": (evasao["taxa"] if evasao else None),
            "n_visitantes": (evasao["n_visitantes"] if evasao else None),
            "n_evadidos": (evasao["n_evadidos"] if evasao else None),
            "evadidos_recorrentes": evadidos_recorrentes,
        }

        score = 0.0
        razoes: list[str] = []

        # ── REGRA OBJETIVA 1: visita obrigatória SEM alternativa de declaração ──
        visita_filtro = obrigatoria and not alternativa
        if visita_filtro:
            score = max(score, ancora("medio"))
            razoes.append("visita presencial OBRIGATÓRIA sem alternativa de declaração de conhecimento do local "
                          "(jurisprudência admite a substituição)")
            res.add_evidencia(
                fonte="edital — cláusula de visita técnica",
                trecho=("visita técnica presencial obrigatória; janela "
                        f"{janela if isinstance(janela, int) else '?'} dia(s); "
                        f"agendamento {'controlado' if agendamento else 'livre'}; "
                        "sem alternativa de declaração de conhecimento do local"),
            )

        # ── REGRA OBJETIVA 2: agendamento controlado / janela única estreita agrava ──
        if visita_filtro and (agendamento or janela_estreita):
            score = max(score, ancora("forte"))
            detalhe = []
            if agendamento:
                detalhe.append("agendamento controlado pelo órgão")
            if janela_estreita:
                detalhe.append(f"janela única estreita ({janela} dia(s))")
            razoes.append("agrava: " + " + ".join(detalhe) + " (controla/expõe quem pretende competir)")

        # ── REGRA OBJETIVA 3: taxa de evasão pós-visita alta ──
        if evasao and evasao["taxa"] is not None and evasao["taxa"] >= _EVASAO_FORTE and evasao["n_visitantes"] >= 2:
            score = max(score, ancora("forte"))
            razoes.append(f"evasão pós-visita de {evasao['taxa']:.0%}: {evasao['n_evadidos']} de "
                          f"{evasao['n_visitantes']} visitantes NÃO apresentaram proposta")
            res.add_evidencia(
                fonte="autos — lista de visitantes × proponentes",
                trecho=(f"{evasao['n_evadidos']} de {evasao['n_visitantes']} visitantes não apresentaram proposta "
                        f"(evasão {evasao['taxa']:.0%}); evadidos: {', '.join(evadidos[:10])}"),
            )

        # ── REGRA OBJETIVA 4: evadidos recorrentes (correlação J1/J4) agrava ──
        if evadidos_recorrentes:
            score = max(score, ancora("forte"))
            razoes.append(f"{len(evadidos_recorrentes)} evadido(s) também 'desistem' em outros certames do órgão "
                          "(correlação com rodízio/supressão — J1/J4)")
            res.add_evidencia(
                fonte="cruzamento com J1/J4",
                trecho=("CNPJs que visitaram, evadiram e reincidem em desistência em outros certames: "
                        + ", ".join(evadidos_recorrentes[:10])),
            )

        if score <= 0:
            res.status = "descartado"
            res.motivo_refutacao = ("visita não-obrigatória ou com alternativa de declaração de conhecimento do local; "
                                    "sem evasão anômala — sem indício de uso da visita como filtro")
            res.valores = valores
            res.explicacao_inocente = ("visita facultativa, ou substituível por declaração de conhecimento do local, "
                                       "sem evasão pós-visita relevante")
            return res

        # ── PARTE SUBJETIVA (LLM-opcional): necessidade real da visita ──
        necessidade = self._avaliar_necessidade(objeto, visita, contexto)
        valores["necessidade"] = necessidade["status"]

        if necessidade["status"] == "indispensavel":
            # condições locais determinantes do preço (obra peculiar) → exculpatória do spec.
            # Nesses casos SÓ pontuam o agendamento controlado e a correlação de evasão; a obrigatoriedade
            # em si não pontua. Rebaixa o achado; agravantes objetivos persistem como 'fraco'.
            score = min(score, ancora("fraco"))
            razoes.append("rubrica necessidade: visita INDISPENSÁVEL (condições locais determinantes do preço — "
                          "obra/engenharia peculiar) — exculpatória do spec (rebaixado; só agendamento/evasão pontuam)")
        elif necessidade["status"] == "dispensavel":
            # objeto padronizado + visita obrigatória → confirma forte (spec).
            score = max(score, ancora("forte"))
            razoes.append("rubrica necessidade: visita DISPENSÁVEL (objeto padronizado) + obrigatória → confirma")

        res.score = round(score, 4)
        res.status = "confirmado"
        res.valores = valores
        res.motivo_refutacao = "; ".join(razoes)
        res.explicacao_inocente = ("FALSO POSITIVO a descartar (spec E4): obras e serviços de ENGENHARIA em locais "
                                   "com condições PECULIARES legitimam a visita — a rubrica de necessidade decide; "
                                   "nesses casos só pontuam o agendamento controlado e a correlação de evasão.")
        return res

    # ───────────────────────────── helpers ─────────────────────────────
    @staticmethod
    def _taxa_evasao(visitantes, licitantes) -> dict | None:
        """Calcula a taxa de EVASÃO pós-visita = visitantes que NÃO viraram licitante / visitantes.
        Só computável com lista de visitantes registrada (autos). Sem ela → None (não inventamos número)."""
        if not visitantes:
            return None
        vset = [_norm_cnpj(c) for c in visitantes if _norm_cnpj(c)]
        if not vset:
            return None
        # dedup preservando ordem
        seen: list[str] = []
        for c in vset:
            if c not in seen:
                seen.append(c)
        lic = {_norm_cnpj(c) for c in (licitantes or []) if _norm_cnpj(c)}
        evadidos = [c for c in seen if c not in lic]
        n_vis = len(seen)
        n_ev = len(evadidos)
        taxa = (n_ev / n_vis) if n_vis else None
        return {"taxa": taxa, "n_visitantes": n_vis, "n_evadidos": n_ev, "evadidos": evadidos}

    def _avaliar_necessidade(self, objeto, visita: dict, contexto: dict) -> dict:
        """Rubrica de NECESSIDADE real da visita. Atalho de teste: `_rubrica_necessidade` no contexto.
        Sem rubrica/LLM → nao_avaliavel honesto (não classificamos a necessidade sem auditoria)."""
        pre = contexto.get("_rubrica_necessidade")
        if pre is not None:
            nivel, _score, motivo = avaliar_rubrica(pre, _RUBRICA_NECESSIDADE)
            if nivel is None:
                return {"status": "nao_avaliavel", "motivo": motivo}
            return {"status": (pre.get("nivel") or pre.get("classificacao") or "").strip().lower(), "motivo": motivo}
        gerar = contexto.get("gerar")
        if gerar is None:
            return {"status": "nao_avaliavel", "motivo": "LLM ausente — necessidade da visita não auditada (honesto)"}
        sistema = (
            "Você é auditor de controle externo. A VISITA TÉCNICA é realmente INDISPENSÁVEL para formular a "
            "proposta, ou o objeto é padronizado e a visita é dispensável? Responda SOMENTE com JSON: "
            '{"nivel":"indispensavel|dispensavel","trecho":"<citação literal do objeto/cláusula>"}. '
            "'indispensavel' = condições locais determinantes do preço (obra em terreno específico). "
            "Sem trecho, não classifique."
        )
        prompt = (f"OBJETO: {str(objeto or '(não informado)')[:400]}\n\n"
                  f"CLÁUSULA DE VISITA: {str(visita)[:400]}\n\n"
                  "A visita é indispensável para formular a proposta?")
        try:
            raw = gerar(prompt, sistema)
        except Exception as e:  # noqa: BLE001 — degrada honesto
            return {"status": "nao_avaliavel", "motivo": f"LLM indisponível ({str(e)[:50]})"}
        from compliance_agent.detectores.base import _parse_json
        dados = _parse_json(raw)
        nivel, _score, motivo = avaliar_rubrica(dados, _RUBRICA_NECESSIDADE)
        if nivel is None or not isinstance(dados, dict):
            return {"status": "nao_avaliavel", "motivo": motivo}
        return {"status": (dados.get("nivel") or "").strip().lower(), "motivo": motivo}
