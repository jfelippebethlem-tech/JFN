# -*- coding: utf-8 -*-
"""E1 · BARREIRA DE ENTRADA (qualificação desproporcional) (spec V2 do dono, §3/E1).

Mecanismo: exigências de habilitação técnica e econômico-financeira calibradas não para garantir capacidade, mas
para EXCLUIR todos menos o fornecedor desejado. O efeito é mensurável: menos licitantes, menos desconto. A Lei
14.133/2021 (art. 62/67) admite exigências de qualificação proporcionais ao OBJETO e ao RISCO de inexecução.

PARÂMETROS OBJETIVOS (no CÓDIGO — limiar nunca vai ao prompt do LLM, spec §1.3):
  • Razões sobre quantitativo/valor estimado:
      – atestado de capacidade técnica exigindo quantitativo > 50% do quantitativo licitado .......... 'forte'
        (Súmula TCU 263: exigência de quantidades mínimas razoáveis; acima de ~50% é tido por restritivo)
      – exigência de quantitativo > 100% do licitado .................................................. 'critico'
      – capital social/patrimônio líquido exigido > 10% do valor estimado (art. 69 §3º teto legal) .... 'forte'
        (a lei limita capital/PL a 10% do valor estimado; acima disso é exigência ilegal objetiva)
  • Exigências que SÓ este órgão pede (vs `editais_analogos` para o MESMO objeto) ................. agravante
      – exigência presente neste edital e AUSENTE em ≥ metade dos análogos ................. 'medio' (candidata a "sob medida")
  • Cruza com o RESULTADO: nº de licitantes baixo (≤2) E inabilitações fundadas nessas exigências .. reforça (sobe nível)

PARTE SUBJETIVA (LLM-OPCIONAL, degrada honesto): por exigência divergente, rubrica fechada de pertinência ao
risco real [proporcional_ao_risco / excessiva_mas_defensavel / sem_relacao_com_capacidade]. 'sem_relacao' →
forte. Sem LLM → a pertinência fica `nao_avaliavel` (não inventamos o juízo); o flag objetivo permanece.

TESTE EXCULPATÓRIO (spec): OBJETO CRÍTICO (UTI, segurança, dados sensíveis) justifica exigências acima do usual —
`objeto_critico=True` rebaixa o score. PRAXE de TODOS os órgãos ≠ direcionamento — por isso o baseline de
`editais_analogos` é obrigatório: exigência igual à praxe (presente na maioria dos análogos) NÃO é candidata.

HONESTIDADE JFN: indício ≠ acusação; sem exigências de habilitação, ou sem valor estimado/quantitativo para as
razões objetivas → `nao_avaliavel` (campo ausente ≠ 0); nunca inventa número.
"""
from __future__ import annotations

from compliance_agent.detectores.base import (
    Detector,
    ResultadoDetector,
    ancora,
    avaliar_rubrica,
)

# tipos de exigência que disparam razões objetivas (chaves canônicas)
_TIPO_ATESTADO = ("atestado", "capacidade_tecnica", "qualificacao_tecnica")
_TIPO_CAPITAL = ("capital_social", "patrimonio_liquido", "capital", "patrimonio")

# Rubrica fechada de pertinência ao risco (spec E1).
_RUBRICA_PERTINENCIA = {
    "proporcional_ao_risco": "ausente",          # exigência justificada → não pontua
    "excessiva_mas_defensavel": "medio",         # zona cinzenta → médio
    "sem_relacao_com_capacidade": "forte",       # restritiva sem nexo → forte
}


def _texto_exig(e: dict) -> str:
    return str(e.get("texto") or e.get("descricao") or e.get("exigencia") or e.get("tipo") or "")


def _chave_exig(e: dict) -> str:
    """Chave canônica de uma exigência para comparar entre editais análogos (tipo + parâmetro normalizado)."""
    tipo = str(e.get("tipo") or "").strip().lower()
    if tipo:
        return tipo
    t = _texto_exig(e).lower()
    t = (t.replace("ã", "a").replace("á", "a").replace("é", "e").replace("í", "i").replace("ó", "o").replace("ç", "c"))
    import re
    toks = [w for w in re.sub(r"[^a-z0-9 ]+", " ", t).split() if len(w) > 3]
    return " ".join(sorted(set(toks))[:6])


def _num(v) -> float | None:
    try:
        if v is None or v == "":
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


class E1Barreira(Detector):
    """Detector E1 — barreira de entrada / qualificação desproporcional (art. 62/67/69, Lei 14.133/2021).

    `avaliar(contexto)` espera:
      contexto["processo"]: id do certame.
      contexto["exigencias_habilitacao"]: list[dict], cada uma com pelo menos {texto|descricao} e idealmente
          {tipo, parametro, valor, unidade}. Para as razões objetivas:
            – atestado: {tipo:'atestado', quantitativo_exigido: float} (compara com `quantitativos`)
            – capital:  {tipo:'capital_social'|'patrimonio_liquido', valor: float} (compara com valor estimado)
      contexto["valor_estimado"] (opcional float): para a razão capital/PL ≤ 10% (art. 69 §3º).
      contexto["quantitativos"] (opcional float|dict): quantitativo total licitado (para a razão do atestado).
      contexto["editais_analogos"] (opcional): list[dict] {exigencias:[...]} de outros órgãos p/ baseline.
      contexto["resultado"] (opcional): {licitantes:int, inabilitados:int, motivos:[...]} p/ corroboração.
      contexto["objeto_critico"] (opcional bool): exculpatória — objeto crítico justifica exigência alta.
      contexto["gerar"] (opcional): callable p/ a rubrica de pertinência (LLM-opcional, degrada honesto).

    Honesto: sem exigências, ou sem base numérica/análogos para qualquer regra → nao_avaliavel."""

    id = "E1"
    nome = "Barreira de entrada (qualificação desproporcional)"
    familia = "desenho_certame"  # E1–E6 (peso 0.6 na convergência §7.2)

    def avaliar(self, contexto: dict) -> ResultadoDetector:
        processo = str(contexto.get("processo") or contexto.get("id") or "?")
        res = self._novo(processo, status="nao_avaliavel")

        exigencias = contexto.get("exigencias_habilitacao") or []
        if not exigencias:
            res.motivo_refutacao = "nao_avaliavel: sem seção de habilitação no contexto (campo ausente ≠ 0)"
            res.valores = {"n_exigencias": 0}
            return res

        valor_estimado = _num(contexto.get("valor_estimado"))
        quant_lic = self._quantitativo_total(contexto.get("quantitativos"))
        analogos = contexto.get("editais_analogos") or []
        resultado = contexto.get("resultado") or {}
        objeto_critico = bool(contexto.get("objeto_critico"))

        valores: dict = {
            "n_exigencias": len(exigencias),
            "valor_estimado": valor_estimado,
            "quantitativo_licitado": quant_lic,
            "n_editais_analogos": len(analogos),
            "objeto_critico": objeto_critico,
        }
        # se NENHUMA base objetiva nem análogos existem, não há como avaliar → nao_avaliavel honesto
        if valor_estimado is None and quant_lic is None and not analogos:
            res.motivo_refutacao = ("nao_avaliavel: sem valor estimado, sem quantitativo e sem editais análogos — "
                                    "nenhuma base para as razões objetivas (campo ausente ≠ 0)")
            res.valores = valores
            return res

        score = 0.0
        razoes: list[str] = []
        exig_suspeitas: list[dict] = []

        # ── REGRAS OBJETIVAS (código, nunca prompt) ──
        for e in exigencias:
            tipo = str(e.get("tipo") or "").strip().lower()
            texto = _texto_exig(e)

            # 1) atestado: quantitativo exigido vs quantitativo licitado
            if quant_lic and (tipo in _TIPO_ATESTADO or any(t in texto.lower() for t in ("atestado", "capacidade técnica"))):
                qexig = _num(e.get("quantitativo_exigido") or e.get("valor"))
                if qexig and quant_lic > 0:
                    razao = qexig / quant_lic
                    if razao > 1.0:
                        score = max(score, ancora("critico"))
                        razoes.append(f"atestado exige {razao:.0%} do quantitativo licitado (>100% — violação objetiva)")
                        exig_suspeitas.append(e)
                        res.add_evidencia(fonte="exigência de habilitação (atestado)",
                                          trecho=f"{texto[:80]} — exige {qexig} de {quant_lic} licitado ({razao:.0%})")
                    elif razao > 0.5:
                        score = max(score, ancora("forte"))
                        razoes.append(f"atestado exige {razao:.0%} do quantitativo licitado (>50% — restritivo, Súmula TCU 263)")
                        exig_suspeitas.append(e)
                        res.add_evidencia(fonte="exigência de habilitação (atestado)",
                                          trecho=f"{texto[:80]} — exige {qexig} de {quant_lic} licitado ({razao:.0%})")

            # 2) capital social / PL vs 10% do valor estimado (art. 69 §3º — teto legal)
            if valor_estimado and (tipo in _TIPO_CAPITAL or any(t in texto.lower() for t in ("capital social", "patrimônio líquido", "patrimonio liquido"))):
                vexig = _num(e.get("valor"))
                if vexig and valor_estimado > 0:
                    pct = vexig / valor_estimado
                    if pct > 0.10:
                        score = max(score, ancora("forte"))
                        razoes.append(f"capital/PL exigido = {pct:.1%} do valor estimado (>10% — teto do art. 69 §3º)")
                        exig_suspeitas.append(e)
                        res.add_evidencia(fonte="exigência de habilitação (capital/PL)",
                                          trecho=f"{texto[:80]} — exige R$ {vexig:,.2f} = {pct:.1%} do estimado")

        # 3) exigências que SÓ este órgão pede (vs análogos) — candidatas a "sob medida"
        sob_medida = self._exigencias_sob_medida(exigencias, analogos)
        valores["exigencias_sob_medida"] = [s["chave"] for s in sob_medida]
        if sob_medida:
            score = max(score, ancora("medio"))
            for s in sob_medida[:5]:
                razoes.append(f"exigência ausente em ≥metade dos análogos: '{s['chave'][:50]}' (candidata a sob medida)")
                res.add_evidencia(fonte="baseline de editais análogos",
                                  trecho=f"exigência '{_texto_exig(s['exig'])[:80]}' não consta em {s['ausente_em']}/{s['n_analogos']} análogos")
                exig_suspeitas.append(s["exig"])

        # 4) corroboração pelo resultado: poucos licitantes + inabilitações
        n_licitantes = resultado.get("licitantes")
        n_inab = resultado.get("inabilitados")
        valores["resultado_licitantes"] = n_licitantes
        valores["resultado_inabilitados"] = n_inab
        corrobora = isinstance(n_licitantes, int) and n_licitantes <= 2 and score > 0
        if corrobora:
            # poucos licitantes confirma o EFEITO mensurável da barreira → sobe um nível (teto forte)
            score = max(score, ancora("forte"))
            razoes.append(f"resultado corrobora: apenas {n_licitantes} licitante(s) (efeito mensurável da barreira)")
            if isinstance(n_inab, int) and n_inab > 0:
                razoes.append(f"{n_inab} inabilitado(s) — verificar se fundados nas exigências restritivas")

        if score <= 0:
            res.status = "descartado"
            res.motivo_refutacao = ("exigências dentro dos limites legais e compatíveis com a praxe dos análogos — "
                                    "sem indício de barreira de entrada")
            res.valores = valores
            res.explicacao_inocente = "qualificação proporcional ao objeto e ao risco; praxe do setor"
            return res

        # ── PARTE SUBJETIVA (LLM-opcional): pertinência ao risco da exigência mais suspeita ──
        pert = self._avaliar_pertinencia(exig_suspeitas, gerar=contexto.get("gerar"))
        valores["pertinencia"] = pert["status"]
        if pert["status"] == "proporcional_ao_risco":
            # o LLM diz que a exigência É proporcional → exculpatória: rebaixa ao máximo 'fraco'
            score = min(score, ancora("fraco"))
            razoes.append("rubrica pertinência: exigência proporcional ao risco — exculpatória (score rebaixado)")

        # exculpatória estrutural do spec: objeto crítico justifica exigência alta → rebaixa
        if objeto_critico:
            score = min(score, ancora("medio"))
            razoes.append("objeto crítico (UTI/segurança/dados sensíveis) justifica exigência acima do usual — rebaixado")

        res.score = round(score, 4)
        res.status = "confirmado"
        res.valores = valores
        res.motivo_refutacao = "; ".join(razoes)
        res.explicacao_inocente = ("FALSO POSITIVO a descartar (spec E1): objeto crítico (UTI, segurança, dados "
                                   "sensíveis) justifica exigências acima do usual; exigência alta mas IGUAL à praxe "
                                   "de todos os órgãos para o objeto NÃO é direcionamento — por isso o baseline de "
                                   "editais análogos é obrigatório antes de pontuar.")
        return res

    @staticmethod
    def _quantitativo_total(q) -> float | None:
        if q is None:
            return None
        if isinstance(q, (int, float)):
            return float(q)
        if isinstance(q, dict):
            tot = sum(_num(v) or 0 for v in q.values())
            return tot or None
        if isinstance(q, (list, tuple)):
            tot = sum(_num(x) or 0 for x in q)
            return tot or None
        return _num(q)

    def _exigencias_sob_medida(self, exigencias: list[dict], analogos: list[dict]) -> list[dict]:
        """Exigências deste edital AUSENTES em ≥ metade dos editais análogos → candidatas a 'sob medida'.
        Sem análogos → lista vazia (não acusa por falta de baseline — exculpatória 'praxe do setor')."""
        if not analogos:
            return []
        chaves_analogos: list[set[str]] = []
        for a in analogos:
            ch = {_chave_exig(e) for e in (a.get("exigencias") or a.get("exigencias_habilitacao") or [])}
            chaves_analogos.append(ch)
        n = len(chaves_analogos)
        out: list[dict] = []
        for e in exigencias:
            k = _chave_exig(e)
            if not k:
                continue
            ausente_em = sum(1 for ch in chaves_analogos if k not in ch)
            if ausente_em >= (n + 1) // 2:  # ausente em ≥ metade (arredonda p/ cima)
                out.append({"chave": k, "exig": e, "ausente_em": ausente_em, "n_analogos": n})
        return out

    def _avaliar_pertinencia(self, exig_suspeitas: list[dict], *, gerar=None) -> dict:
        """Rubrica fechada de pertinência ao risco, sobre a 1ª exigência suspeita. Atalho de teste:
        `_rubrica_pertinencia` injetado na exigência. Sem rubrica e sem LLM → nao_avaliavel honesto."""
        pre = None
        for e in exig_suspeitas:
            if e.get("_rubrica_pertinencia"):
                pre = e["_rubrica_pertinencia"]
                break
        if pre is not None:
            nivel, _score, motivo = avaliar_rubrica(pre, _RUBRICA_PERTINENCIA)
            if nivel is None:
                return {"status": "nao_avaliavel", "motivo": motivo}
            return {"status": (pre.get("nivel") or pre.get("classificacao") or "").strip().lower(), "motivo": motivo}
        if gerar is None or not exig_suspeitas:
            return {"status": "nao_avaliavel", "motivo": "LLM ausente — pertinência não auditada (honesto)"}
        e = exig_suspeitas[0]
        sistema = (
            "Você é auditor de controle externo. Classifique a PERTINÊNCIA da exigência de habilitação ao RISCO "
            "real de inexecução do objeto. Responda SOMENTE com JSON: "
            '{"nivel":"proporcional_ao_risco|excessiva_mas_defensavel|sem_relacao_com_capacidade",'
            '"trecho":"<citação literal da exigência>"}. Sem trecho, não classifique.'
        )
        prompt = f"EXIGÊNCIA: {_texto_exig(e)[:400]}\n\nClassifique a pertinência ao risco de inexecução."
        try:
            raw = gerar(prompt, sistema)
        except Exception as ex:  # noqa: BLE001 — degrada honesto
            return {"status": "nao_avaliavel", "motivo": f"LLM indisponível ({str(ex)[:50]})"}
        from compliance_agent.detectores.base import _parse_json
        dados = _parse_json(raw)
        nivel, _score, motivo = avaliar_rubrica(dados, _RUBRICA_PERTINENCIA)
        if nivel is None or not isinstance(dados, dict):
            return {"status": "nao_avaliavel", "motivo": motivo}
        return {"status": (dados.get("nivel") or "").strip().lower(), "motivo": motivo}
