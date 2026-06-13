# -*- coding: utf-8 -*-
"""E6 · PONTUAÇÃO TÉCNICA DIRIGIDA (spec V2 do dono, §3/E6).

Mecanismo: em julgamento por 'técnica e preço', a MATRIZ de pontuação é desenhada para que SÓ UM proponente
alcance a nota máxima — experiência com o PRÓPRIO órgão contratante, certificações raras, equipe com perfis
ultraespecíficos — tornando o PREÇO irrelevante. O direcionamento se esconde em critérios subjetivos-puros
('qualidade da metodologia' sem métrica) e em barreiras a entrantes (atributos que só o incumbente detém).

PARÂMETROS OBJETIVOS (no CÓDIGO — limiar nunca vai ao prompt do LLM, spec §1.3):
  • % dos pontos em critérios SUBJETIVOS-PUROS:
      – ≥ 40% dos pontos em subjetivo_puro ............................................ 'medio' (matriz frouxa)
  • Critério que exige EXPERIÊNCIA COM O PRÓPRIO ÓRGÃO contratante .................... agrava (barreira a entrantes)
  • SIMULAÇÃO de troca de vencedor: recalcula o resultado ZERANDO os critérios monopolizados/subjetivos —
      se o VENCEDOR MUDA, o(s) critério(s) foi(ram) DECISIVO(s) → 'forte' (a pontuação dirigida elegeu o vencedor).

PARTE SUBJETIVA (DUAS rubricas fechadas, LLM-OPCIONAL, degrada honesto):
  (1) "Objetividade de cada critério" [objetivo_verificavel / semiobjetivo / subjetivo_puro] — alimenta o % acima
      quando o campo `subjetividade` não vier no edital. Evidência: texto do critério.
  (2) "Consistência da atribuição de notas" (comparar atas) [notas_fundamentadas / fundamentacao_generica /
      notas_sem_fundamentacao]. Subjetivo-puro + notas SEM fundamentação → 'forte'. Evidência: trecho da ata.

TESTE EXCULPATÓRIO (spec): serviços predominantemente INTELECTUAIS (projetos, consultoria especializada) LEGITIMAM
peso técnico alto — a análise migra para a OBJETIVIDADE dos critérios, NÃO para o peso em si. Logo `servico_intelectual`
não zera o achado: ele NEUTRALIZA o mero peso técnico alto, mas a matriz frouxa/subjetiva-decisiva permanece.

HONESTIDADE JFN: indício ≠ acusação; sem MATRIZ de pontuação → `nao_avaliavel` (campo ausente ≠ 0 — não dá para
medir % de subjetividade sem a matriz); nunca inventa número.
"""
from __future__ import annotations

from compliance_agent.detectores.base import (
    Detector,
    ResultadoDetector,
    ancora,
    avaliar_rubrica,
)

# Rubrica (1) — objetividade de UM critério (spec E6). Mapeia o nível → âncora só p/ validar a citação;
# o efeito de pontuação fica no CÓDIGO (soma de % em subjetivo_puro).
_RUBRICA_OBJETIVIDADE = {
    "objetivo_verificavel": "ausente",  # documento comprova (atestado, diploma) → não dirige
    "semiobjetivo": "fraco",            # depende de juízo mas com baliza
    "subjetivo_puro": "medio",          # 'qualidade da metodologia' sem métrica → vetor de direcionamento
}
# Rubrica (2) — consistência da atribuição de notas, comparando atas (spec E6).
_RUBRICA_CONSISTENCIA = {
    "notas_fundamentadas": "ausente",      # cada nota justificada com critério objetivo
    "fundamentacao_generica": "medio",     # 'boa metodologia' sem ancorar no quê
    "notas_sem_fundamentacao": "forte",    # notas atribuídas sem motivar → arbítrio
}

_LIMIAR_SUBJETIVO = 0.40  # ≥40% dos pontos em subjetivo_puro → matriz frouxa (spec E6)


class E6PontuacaoDirigida(Detector):
    """Detector E6 — pontuação técnica dirigida (julgamento 'técnica e preço', Lei 14.133/2021 art. 36/37).

    `avaliar(contexto)` espera:
      contexto["processo"]: id do certame.
      contexto["matriz_pontuacao"]: list[dict] — ESSENCIAL. Cada critério:
          {criterio, pontos, forma_comprovacao?,
           exige_experiencia_proprio_orgao?: bool,
           subjetividade?: 'objetivo_verificavel'|'semiobjetivo'|'subjetivo_puro'  (se ausente → rubrica LLM)}.
      contexto["propostas_tecnicas"] (opcional): list[dict] {cnpj, notas: {criterio: nota}} p/ a SIMULAÇÃO.
      contexto["vencedor_cnpj"] (opcional): vencedor declarado (necessário p/ a simulação de troca).
      contexto["atas"] (opcional): list/str — atas de julgamento p/ a rubrica de consistência.
      contexto["servico_intelectual"] (opcional bool): exculpatória — peso técnico alto é legítimo (a análise
          migra p/ a objetividade dos critérios, não p/ o peso).
      contexto["gerar"] (opcional): callable p/ as rubricas (objetividade/consistência) — LLM-opcional.
      contexto["_rubricas_objetividade"] (opcional list): rubricas pré-classificadas por critério (teste), na
          MESMA ordem de `matriz_pontuacao`.
      contexto["_rubrica_consistencia"] (opcional dict): rubrica de consistência pré-classificada (teste).

    Honesto: sem `matriz_pontuacao` → nao_avaliavel (não dá p/ medir % de subjetividade sem a matriz)."""

    id = "E6"
    nome = "Pontuação técnica dirigida"
    familia = "desenho_certame"  # E1–E6 (peso 0.6 na convergência §7.2)

    def avaliar(self, contexto: dict) -> ResultadoDetector:
        processo = str(contexto.get("processo") or contexto.get("id") or "?")
        res = self._novo(processo, status="nao_avaliavel")

        matriz = contexto.get("matriz_pontuacao") or []
        if not matriz:
            res.motivo_refutacao = "nao_avaliavel: sem matriz de pontuação técnica no contexto (campo ausente ≠ 0)"
            res.valores = {"n_criterios": 0}
            return res

        total_pontos = sum(self._pontos(c) for c in matriz)
        if total_pontos <= 0:
            res.motivo_refutacao = ("nao_avaliavel: matriz sem pontos atribuídos aos critérios — não é possível "
                                    "medir % de subjetividade (campo ausente ≠ 0)")
            res.valores = {"n_criterios": len(matriz), "total_pontos": total_pontos}
            return res

        # ── classifica a objetividade de cada critério (campo direto OU rubrica LLM-opcional) ──
        rubricas_obj = self._rubricas_objetividade(matriz, contexto)
        criterios_info: list[dict] = []
        pontos_subjetivos = 0.0
        criterios_subjetivos: list[dict] = []
        criterios_proprio_orgao: list[dict] = []

        for idx, c in enumerate(matriz):
            nome = str(c.get("criterio") or c.get("nome") or f"criterio_{idx + 1}")
            pts = self._pontos(c)
            subj = self._subjetividade(c, rubricas_obj[idx] if idx < len(rubricas_obj) else None)
            proprio_orgao = bool(c.get("exige_experiencia_proprio_orgao"))
            info = {
                "criterio": nome,
                "pontos": pts,
                "subjetividade": subj,
                "exige_experiencia_proprio_orgao": proprio_orgao,
            }
            criterios_info.append(info)
            if subj == "subjetivo_puro":
                pontos_subjetivos += pts
                criterios_subjetivos.append(info)
            if proprio_orgao:
                criterios_proprio_orgao.append(info)

        pct_subjetivo = pontos_subjetivos / total_pontos

        servico_intelectual = bool(contexto.get("servico_intelectual"))
        valores: dict = {
            "n_criterios": len(matriz),
            "total_pontos": total_pontos,
            "pontos_subjetivos": round(pontos_subjetivos, 4),
            "pct_subjetivo": round(pct_subjetivo, 4),
            "criterios_subjetivos": [c["criterio"] for c in criterios_subjetivos],
            "criterios_proprio_orgao": [c["criterio"] for c in criterios_proprio_orgao],
            "criterios": criterios_info,
            "servico_intelectual": servico_intelectual,
        }

        score = 0.0
        razoes: list[str] = []

        # ── REGRA OBJETIVA: % de pontos em subjetivo_puro ──
        if pct_subjetivo >= _LIMIAR_SUBJETIVO:
            score = max(score, ancora("medio"))
            razoes.append(
                f"{pct_subjetivo:.0%} dos pontos em critérios subjetivo-puros (≥40% — matriz frouxa)")
            res.add_evidencia(
                fonte="matriz de pontuação técnica",
                trecho=("critérios subjetivo-puros concentram "
                        f"{pontos_pct(pontos_subjetivos, total_pontos)} dos pontos: "
                        + ", ".join(c["criterio"] for c in criterios_subjetivos[:10])),
            )

        # ── critérios que exigem experiência com o PRÓPRIO órgão (barreira a entrantes) ──
        if criterios_proprio_orgao:
            score = max(score, ancora("medio"))
            razoes.append("critério(s) exigem experiência com o PRÓPRIO órgão contratante (barreira a entrantes)")
            for c in criterios_proprio_orgao:
                res.add_evidencia(
                    fonte="matriz de pontuação técnica",
                    trecho=(f"critério '{c['criterio']}' ({c['pontos']} pts) pontua experiência com o próprio "
                            "órgão contratante — agrava (incumbente já a detém)"))

        # ── SIMULAÇÃO: zerar critérios subjetivos/monopolizados e ver se o vencedor MUDA ──
        criterios_zerar = {c["criterio"] for c in criterios_subjetivos}
        criterios_zerar |= {c["criterio"] for c in criterios_proprio_orgao}
        sim = self._simular_troca_vencedor(contexto, criterios_zerar)
        valores["simulacao"] = sim
        if sim.get("vencedor_muda"):
            score = max(score, ancora("forte"))
            razoes.append(
                f"SIMULAÇÃO: zerando os critérios subjetivos/monopolizados o vencedor MUDA de "
                f"{sim.get('vencedor_original')!r} para {sim.get('vencedor_sem')!r} — os critérios foram DECISIVOS")
            res.add_evidencia(
                fonte="simulação de troca de vencedor",
                trecho=(f"recalculando sem {sorted(criterios_zerar)}: vencedor passa de "
                        f"{sim.get('vencedor_original')} para {sim.get('vencedor_sem')} (critério decisivo)"))

        # ── rubrica (2): consistência da atribuição de notas (atas) ──
        consist = self._avaliar_consistencia(contexto)
        valores["consistencia_notas"] = consist["status"]
        if criterios_subjetivos and consist["status"] == "notas_sem_fundamentacao":
            score = max(score, ancora("forte"))
            razoes.append("subjetivo-puro + notas SEM fundamentação na ata → arbítrio (forte)")
            if consist.get("trecho"):
                res.add_evidencia(fonte="ata de julgamento", trecho=str(consist["trecho"])[:200])
        elif criterios_subjetivos and consist["status"] == "fundamentacao_generica":
            score = max(score, ancora("medio"))
            razoes.append("subjetivo-puro + fundamentação genérica na ata")

        if score <= 0:
            res.status = "descartado"
            res.motivo_refutacao = ("matriz predominantemente objetiva (<40% subjetivo-puro), sem critério de "
                                    "próprio-órgão e sem troca de vencedor na simulação — sem indício de pontuação dirigida")
            res.valores = valores
            res.explicacao_inocente = ("critérios objetivos-verificáveis (atestados/diplomas) e notas fundamentadas; "
                                       "peso técnico justificado pela natureza do objeto")
            return res

        # ── EXCULPATÓRIA: serviço intelectual legitima PESO técnico alto, não a SUBJETIVIDADE dos critérios ──
        if servico_intelectual:
            # peso técnico alto deixa de ser indício; o achado SÓ sobrevive se houver objetividade ruim
            # (subjetivo decisivo) ou notas sem fundamentação. Se o único motor era um peso técnico genérico
            # (sem critério subjetivo-puro, sem próprio-órgão, sem simulação decisiva), descarta.
            achado_objetivo = (
                bool(criterios_subjetivos)
                or bool(criterios_proprio_orgao)
                or bool(sim.get("vencedor_muda"))
            )
            if not achado_objetivo:
                res.status = "descartado"
                res.valores = valores
                res.motivo_refutacao = ("serviço predominantemente INTELECTUAL legitima peso técnico alto e os "
                                        "critérios são objetivos — exculpatória do spec (descartado)")
                res.explicacao_inocente = ("serviço intelectual (projeto/consultoria) justifica peso técnico; a "
                                           "matriz é objetiva-verificável — sem direcionamento")
                return res
            razoes.append("serviço intelectual legitima o PESO técnico, mas a OBJETIVIDADE dos critérios não se "
                          "sustenta (o achado migra para a subjetividade/decisividade, não para o peso)")

        res.score = round(score, 4)
        res.status = "confirmado"
        res.valores = valores
        res.motivo_refutacao = "; ".join(razoes)
        res.explicacao_inocente = ("FALSO POSITIVO a descartar (spec E6): serviços predominantemente INTELECTUAIS "
                                   "(projetos, consultoria especializada) legitimam peso técnico alto — a análise "
                                   "migra para a OBJETIVIDADE dos critérios, não para o peso em si.")
        return res

    # ───────────────────────────── helpers ─────────────────────────────
    @staticmethod
    def _pontos(criterio: dict) -> float:
        v = criterio.get("pontos")
        if v is None:
            v = criterio.get("peso") or criterio.get("pontuacao")
        try:
            return max(0.0, float(v))
        except (TypeError, ValueError):
            return 0.0

    def _subjetividade(self, criterio: dict, rubrica_pre: dict | None) -> str:
        """Nível de objetividade de UM critério: usa o campo `subjetividade` direto do edital quando presente;
        senão, a rubrica (LLM-opcional). Sem nenhum dos dois → 'nao_avaliavel' (não inventamos a classe)."""
        direto = (criterio.get("subjetividade") or criterio.get("objetividade") or "").strip().lower()
        if direto in _RUBRICA_OBJETIVIDADE:
            return direto
        if rubrica_pre is not None:
            nivel, _score, _motivo = avaliar_rubrica(rubrica_pre, _RUBRICA_OBJETIVIDADE)
            if nivel is not None:
                return (rubrica_pre.get("nivel") or rubrica_pre.get("classificacao") or "").strip().lower()
        return "nao_avaliavel"

    def _rubricas_objetividade(self, matriz: list, contexto: dict) -> list:
        """Lista de rubricas de objetividade por critério (atalho de teste `_rubricas_objetividade`; senão LLM
        por critério SEM campo `subjetividade`). LLM-opcional: ausente → lista de None (degrada honesto)."""
        pre = contexto.get("_rubricas_objetividade")
        if pre is not None:
            return list(pre)
        gerar = contexto.get("gerar")
        if gerar is None:
            return [None] * len(matriz)
        from compliance_agent.detectores.base import _parse_json
        sistema = (
            "Você é auditor de controle externo. Classifique a OBJETIVIDADE de UM critério de pontuação técnica. "
            "Responda SOMENTE com JSON: "
            '{"nivel":"objetivo_verificavel|semiobjetivo|subjetivo_puro","trecho":"<citação literal do critério>"}. '
            "'objetivo_verificavel' = documento comprova (atestado/diploma); 'subjetivo_puro' = 'qualidade da "
            "metodologia' sem métrica. Sem trecho, não classifique."
        )
        out: list = []
        for c in matriz:
            if (c.get("subjetividade") or "").strip().lower() in _RUBRICA_OBJETIVIDADE:
                out.append(None)  # já vem classificado no edital → não gasta LLM
                continue
            nome = str(c.get("criterio") or c.get("nome") or "")
            prompt = f"CRITÉRIO DE PONTUAÇÃO TÉCNICA:\n{nome}\nforma de comprovação: {c.get('forma_comprovacao') or '(não informada)'}"
            try:
                raw = gerar(prompt, sistema)
            except Exception:  # noqa: BLE001 — degrada honesto
                out.append(None)
                continue
            out.append(_parse_json(raw))
        return out

    def _avaliar_consistencia(self, contexto: dict) -> dict:
        """Rubrica (2): consistência da atribuição de notas comparando atas. Atalho de teste `_rubrica_consistencia`;
        senão LLM sobre as atas. Sem rubrica/LLM/atas → nao_avaliavel honesto."""
        pre = contexto.get("_rubrica_consistencia")
        if pre is not None:
            nivel, _score, motivo = avaliar_rubrica(pre, _RUBRICA_CONSISTENCIA)
            if nivel is None:
                return {"status": "nao_avaliavel", "motivo": motivo}
            return {
                "status": (pre.get("nivel") or pre.get("classificacao") or "").strip().lower(),
                "trecho": pre.get("trecho") or pre.get("citacao"),
                "motivo": motivo,
            }
        atas = contexto.get("atas")
        if not atas:
            return {"status": "nao_avaliavel", "motivo": "sem atas de julgamento — consistência não auditada"}
        gerar = contexto.get("gerar")
        if gerar is None:
            return {"status": "nao_avaliavel", "motivo": "LLM ausente — consistência das notas não auditada (honesto)"}
        from compliance_agent.detectores.base import _parse_json
        sistema = (
            "Você é auditor de controle externo. Avalie a CONSISTÊNCIA da atribuição de notas na ata de julgamento. "
            "Responda SOMENTE com JSON: "
            '{"nivel":"notas_fundamentadas|fundamentacao_generica|notas_sem_fundamentacao","trecho":"<citação literal da ata>"}. '
            "'notas_sem_fundamentacao' = notas atribuídas sem motivar. Sem trecho, não classifique."
        )
        ata_txt = atas if isinstance(atas, str) else "\n".join(str(a) for a in atas)
        prompt = f"ATA(S) DE JULGAMENTO:\n{ata_txt[:1500]}\n\nAs notas estão fundamentadas?"
        try:
            raw = gerar(prompt, sistema)
        except Exception as e:  # noqa: BLE001 — degrada honesto
            return {"status": "nao_avaliavel", "motivo": f"LLM indisponível ({str(e)[:50]})"}
        dados = _parse_json(raw)
        nivel, _score, motivo = avaliar_rubrica(dados, _RUBRICA_CONSISTENCIA)
        if nivel is None or not isinstance(dados, dict):
            return {"status": "nao_avaliavel", "motivo": motivo}
        return {"status": (dados.get("nivel") or "").strip().lower(), "trecho": dados.get("trecho"), "motivo": motivo}

    def _simular_troca_vencedor(self, contexto: dict, criterios_zerar: set) -> dict:
        """SIMULAÇÃO determinística (código puro): recalcula a nota total de cada proposta ZERANDO os critérios
        subjetivos/monopolizados; se o argmax (vencedor) MUDA face ao vencedor declarado, o critério foi decisivo.

        Honesto: sem propostas+notas, ou sem critérios a zerar → não simula (vencedor_muda=False, motivo)."""
        propostas = contexto.get("propostas_tecnicas") or []
        vencedor_decl = contexto.get("vencedor_cnpj")
        if not propostas or not criterios_zerar:
            return {"vencedor_muda": False, "motivo": "simulação não aplicável (sem propostas/notas ou sem critérios a zerar)"}

        def total(notas: dict, excluir: set | None = None) -> float:
            s = 0.0
            for crit, nota in (notas or {}).items():
                if excluir and crit in excluir:
                    continue
                try:
                    s += float(nota)
                except (TypeError, ValueError):
                    continue
            return s

        # vencedor pela matriz COMPLETA (usa o declarado se houver; senão o argmax atual)
        def argmax(excluir: set | None) -> str | None:
            melhor_cnpj, melhor_nota = None, None
            for p in propostas:
                cnpj = p.get("cnpj") or p.get("licitante_cnpj")
                nota = total(p.get("notas") or {}, excluir)
                if melhor_nota is None or nota > melhor_nota:
                    melhor_cnpj, melhor_nota = cnpj, nota
            return melhor_cnpj

        vencedor_completo = vencedor_decl or argmax(None)
        vencedor_sem = argmax(criterios_zerar)
        muda = (
            vencedor_completo is not None
            and vencedor_sem is not None
            and vencedor_sem != vencedor_completo
        )
        return {
            "vencedor_muda": muda,
            "vencedor_original": vencedor_completo,
            "vencedor_sem": vencedor_sem,
            "criterios_zerados": sorted(criterios_zerar),
        }


def pontos_pct(parte: float, total: float) -> str:
    """% formatado dos pontos (string p/ evidência)."""
    if total <= 0:
        return "0%"
    return f"{parte / total:.0%}"
