# -*- coding: utf-8 -*-
"""E3 · LOTE-PACOTE (agregação anticompetitiva) (spec V2 do dono, §3/E3).

Mecanismo: itens HETEROGÊNEOS são agrupados num lote único que só uma empresa "completa" consegue atender,
eliminando especialistas. O art. 40, §2º, da Lei 14.133/2021 impõe o PARCELAMENTO como regra; a não-divisão exige
justificativa técnica/econômica DEMONSTRADA (números, não adjetivos).

PARÂMETROS OBJETIVOS (no CÓDIGO — limiar nunca vai ao prompt do LLM, spec §1.3):
  • Nº de MERCADOS distintos (classes CATMAT/CATSER, ou prefixo de classe) por lote:
      – lote com ≥ 3 mercados distintos (heterogêneo) ................................. 'medio' (candidato)
      – lote com ≥ 5 mercados distintos (fortemente heterogêneo) ...................... 'forte'
  • Qualidade da justificativa de não-parcelamento (art. 40 §2º):
      – AUSENTE quando há lote heterogêneo ........................................... 'forte' (omissão do dever legal)
      – presente mas GENÉRICA (sem número/quantificação) ............................. 'medio'
  • Cruza com o RESULTADO: licitante(s) por lote ≤ 2 (efeito de eliminação de especialistas) ... reforça

PARTE SUBJETIVA (LLM-OPCIONAL, degrada honesto): por lote heterogêneo, rubrica fechada de INTERDEPENDÊNCIA técnica
real [integracao_necessaria / conveniencia]. 'conveniencia' + heterogeneidade → confirma; 'integracao_necessaria'
→ exculpa. Sem LLM → interdependência `nao_avaliavel` (não inventamos o juízo); o flag objetivo permanece.
A qualidade da justificativa textual também pode vir por rubrica [demonstrada/generica/ausente].

TESTE EXCULPATÓRIO (spec): INTEGRAÇÃO REAL (hardware + software + manutenção do MESMO sistema) justifica lote único
— a rubrica de interdependência decide; 'integracao_necessaria' rebaixa. Economia de escala DEMONSTRADA com números
nos autos é exculpatória válida ('demonstrada' exige quantificação, não adjetivo).

HONESTIDADE JFN: indício ≠ acusação; sem lotes, ou sem classificação CATMAT/CATSER dos itens → `nao_avaliavel`
(campo ausente ≠ 0 — não dá para contar mercados sem a classe); nunca inventa.
"""
from __future__ import annotations

from compliance_agent.detectores.base import (
    Detector,
    ResultadoDetector,
    ancora,
    avaliar_rubrica,
)

# Rubrica de interdependência técnica (spec E3).
_RUBRICA_INTERDEP = {
    "integracao_necessaria": "ausente",   # itens operam como sistema único → exculpa
    "conveniencia": "forte",              # itens independentes no uso → confirma (com heterogeneidade)
}
# Rubrica de qualidade da justificativa de não-parcelamento (spec E3).
_RUBRICA_JUSTIFICATIVA = {
    "demonstrada": "ausente",   # ganho logístico/integração QUANTIFICADO → exculpa
    "generica": "medio",        # 'eficiência administrativa' sem número
    "ausente": "forte",         # sem justificativa com lote heterogêneo → omissão do dever (art. 40 §2º)
}


def _classe_mercado(item: dict, catmat_por_item: dict | None) -> str | None:
    """Classe de MERCADO de um item: usa CATMAT/CATSER explícito (no item ou em `catmat_por_item`), reduzido ao
    PREFIXO de classe (4 primeiros dígitos = grupo de mercado). Sem classe → None (não inventamos o mercado)."""
    cod = item.get("catmat") or item.get("catser") or item.get("classe") or item.get("mercado")
    if not cod and catmat_por_item is not None:
        chave = item.get("id") or item.get("item") or item.get("codigo") or item.get("descricao")
        cod = catmat_por_item.get(chave) if chave is not None else None
    if not cod:
        return None
    s = str(cod).strip()
    digs = "".join(ch for ch in s if ch.isdigit())
    if len(digs) >= 4:
        return digs[:4]
    return s.lower()[:8]


class E3LotePacote(Detector):
    """Detector E3 — lote-pacote / agregação anticompetitiva (art. 40 §2º, Lei 14.133/2021).

    `avaliar(contexto)` espera:
      contexto["processo"]: id do certame.
      contexto["lotes"]: list[dict], cada lote {id?, itens: [ {descricao, catmat|catser|classe?, id?}, ... ]}.
      contexto["catmat_por_item"] (opcional dict): mapa {item_id|descricao: codigo CATMAT/CATSER} quando a classe
          não vier embutida no item.
      contexto["justificativa_nao_parcelamento"] (opcional str): texto da justificativa nos autos.
      contexto["resultado"] (opcional): {licitantes_por_lote: {lote_id: int}} ou {licitantes: int} p/ corroboração.
      contexto["gerar"] (opcional): callable p/ as rubricas (interdependência/justificativa) — LLM-opcional.
      contexto["_rubrica_interdep"] / contexto["_rubrica_justificativa"] (opcional): rubricas pré-classificadas (teste).

    Honesto: sem lotes, ou nenhum item com classe CATMAT/CATSER → nao_avaliavel (não dá p/ contar mercados)."""

    id = "E3"
    nome = "Lote-pacote (agregação anticompetitiva)"
    familia = "desenho_certame"  # E1–E6 (peso 0.6 na convergência §7.2)

    def avaliar(self, contexto: dict) -> ResultadoDetector:
        processo = str(contexto.get("processo") or contexto.get("id") or "?")
        res = self._novo(processo, status="nao_avaliavel")

        lotes = contexto.get("lotes") or []
        if not lotes:
            res.motivo_refutacao = "nao_avaliavel: sem estrutura de lotes no contexto (campo ausente ≠ 0)"
            res.valores = {"n_lotes": 0}
            return res

        catmat_por_item = contexto.get("catmat_por_item")

        # conta mercados distintos por lote; precisamos de pelo menos UM item classificado para avaliar
        lotes_info: list[dict] = []
        algum_classificado = False
        for li, lote in enumerate(lotes):
            itens = lote.get("itens") or []
            classes = []
            for it in itens:
                cls = _classe_mercado(it, catmat_por_item)
                if cls:
                    classes.append(cls)
                    algum_classificado = True
            mercados = sorted(set(classes))
            lotes_info.append({
                "id": lote.get("id") or f"lote_{li + 1}",
                "n_itens": len(itens),
                "n_itens_classificados": len(classes),
                "n_mercados": len(mercados),
                "mercados": mercados,
            })

        if not algum_classificado:
            res.motivo_refutacao = ("nao_avaliavel: nenhum item com classe CATMAT/CATSER — não é possível contar "
                                    "mercados por lote (campo ausente ≠ 0)")
            res.valores = {"n_lotes": len(lotes), "lotes": lotes_info}
            return res

        # lote mais heterogêneo é o achado principal
        pior = max(lotes_info, key=lambda x: x["n_mercados"])
        n_merc = pior["n_mercados"]

        valores: dict = {
            "n_lotes": len(lotes),
            "lote_mais_heterogeneo": pior["id"],
            "n_mercados_no_lote": n_merc,
            "mercados_no_lote": pior["mercados"],
            "lotes": lotes_info,
        }

        score = 0.0
        razoes: list[str] = []

        # ── REGRA OBJETIVA: nº de mercados distintos no lote ──
        heterogeneo = n_merc >= 3
        if n_merc >= 5:
            score = max(score, ancora("forte"))
            razoes.append(f"lote '{pior['id']}' agrega {n_merc} mercados distintos (fortemente heterogêneo)")
        elif n_merc >= 3:
            score = max(score, ancora("medio"))
            razoes.append(f"lote '{pior['id']}' agrega {n_merc} mercados distintos (heterogêneo — candidato a lote-pacote)")

        if heterogeneo:
            res.add_evidencia(
                fonte=f"estrutura do lote '{pior['id']}'",
                trecho=f"{pior['n_itens']} itens cobrindo {n_merc} classes de mercado distintas: {', '.join(pior['mercados'][:10])}",
            )

        # ── justificativa de não-parcelamento (art. 40 §2º) ──
        justif_txt = contexto.get("justificativa_nao_parcelamento")
        justif = self._avaliar_justificativa(justif_txt, contexto, heterogeneo)
        valores["justificativa_status"] = justif["status"]
        if heterogeneo:
            if justif["status"] == "ausente":
                score = max(score, ancora("forte"))
                razoes.append("justificativa de não-parcelamento AUSENTE com lote heterogêneo (omissão do dever, art. 40 §2º)")
                res.add_evidencia(fonte="autos — art. 40 §2º",
                                  trecho="lote heterogêneo SEM justificativa de não-parcelamento nos autos")
            elif justif["status"] == "generica":
                score = max(score, ancora("medio"))
                razoes.append("justificativa de não-parcelamento GENÉRICA (sem quantificação) — art. 40 §2º exige demonstração")
                if justif_txt:
                    res.add_evidencia(fonte="autos — justificativa de não-parcelamento",
                                      trecho=str(justif_txt)[:120])

        # ── corroboração pelo resultado ──
        n_lic = self._licitantes_pior_lote(contexto.get("resultado") or {}, pior["id"])
        valores["licitantes_no_lote"] = n_lic
        if isinstance(n_lic, int) and n_lic <= 2 and score > 0:
            score = max(score, ancora("forte"))
            razoes.append(f"resultado corrobora: apenas {n_lic} licitante(s) no lote (especialistas eliminados)")

        if score <= 0:
            res.status = "descartado"
            res.motivo_refutacao = ("lotes homogêneos (≤2 mercados) ou justificativa demonstrada — sem indício de "
                                    "agregação anticompetitiva")
            res.valores = valores
            res.explicacao_inocente = "lote coeso (itens do mesmo mercado) ou não-parcelamento demonstrado com números"
            return res

        # ── PARTE SUBJETIVA (LLM-opcional): interdependência técnica do lote heterogêneo ──
        interdep = self._avaliar_interdependencia(pior, contexto)
        valores["interdependencia"] = interdep["status"]
        if interdep["status"] == "integracao_necessaria":
            # itens operam como sistema único → exculpatória do spec: rebaixa ao máximo 'fraco'
            score = min(score, ancora("fraco"))
            razoes.append("rubrica interdependência: integração técnica real (sistema único) — exculpatória (rebaixado)")
        elif justif["status"] == "demonstrada":
            # economia de escala demonstrada com números → exculpatória válida
            score = min(score, ancora("fraco"))
            razoes.append("justificativa DEMONSTRADA com quantificação — exculpatória do spec (rebaixado)")

        res.score = round(score, 4)
        res.status = "confirmado"
        res.valores = valores
        res.motivo_refutacao = "; ".join(razoes)
        res.explicacao_inocente = ("FALSO POSITIVO a descartar (spec E3): integração real (ex.: hardware + software "
                                   "+ manutenção do MESMO sistema) justifica lote único — a rubrica de "
                                   "interdependência decide; economia de escala DEMONSTRADA com números nos autos é "
                                   "exculpatória válida ('demonstrada' exige quantificação, não adjetivo).")
        return res

    @staticmethod
    def _licitantes_pior_lote(resultado: dict, lote_id) -> int | None:
        por_lote = resultado.get("licitantes_por_lote")
        if isinstance(por_lote, dict):
            v = por_lote.get(lote_id)
            if v is None and len(por_lote) == 1:
                v = next(iter(por_lote.values()))
            if isinstance(v, int):
                return v
        v = resultado.get("licitantes")
        return v if isinstance(v, int) else None

    def _avaliar_justificativa(self, texto, contexto: dict, heterogeneo: bool) -> dict:
        """Qualidade da justificativa de não-parcelamento. Atalho de teste: `_rubrica_justificativa` no contexto.
        Sem rubrica/LLM: se NÃO há texto → 'ausente' (fato objetivo, não juízo); se HÁ texto mas sem LLM →
        nao_avaliavel honesto (não classificamos a qualidade sem auditoria)."""
        pre = contexto.get("_rubrica_justificativa")
        if pre is not None:
            nivel, _score, motivo = avaliar_rubrica(pre, _RUBRICA_JUSTIFICATIVA)
            if nivel is None:
                return {"status": "nao_avaliavel", "motivo": motivo}
            return {"status": (pre.get("nivel") or pre.get("classificacao") or "").strip().lower(), "motivo": motivo}
        if not texto:
            # INDISPONÍVEL ≠ 0: só é "ausente dos AUTOS" (fato objetivo, omissão do dever) quando o
            # coletor afirma que pesquisou a íntegra; campo não ingerido é indisponibilidade nossa.
            if contexto.get("justificativa_pesquisada_nos_autos") is True:
                return {"status": "ausente", "motivo": "nenhuma justificativa de não-parcelamento nos autos"}
            return {"status": "nao_avaliavel",
                    "motivo": "justificativa não ingerida no contexto (indisponível ≠ ausente dos autos)"}
        gerar = contexto.get("gerar")
        if gerar is None:
            return {"status": "nao_avaliavel", "motivo": "LLM ausente — qualidade da justificativa não auditada"}
        sistema = (
            "Você é auditor de controle externo. Classifique a QUALIDADE da justificativa de NÃO-PARCELAMENTO "
            "(art. 40 §2º). Responda SOMENTE com JSON: "
            '{"nivel":"demonstrada|generica|ausente","trecho":"<citação literal>"}. '
            "'demonstrada' exige ganho logístico/integração QUANTIFICADO (números). Sem trecho, não classifique."
        )
        prompt = f"JUSTIFICATIVA DE NÃO-PARCELAMENTO:\n{str(texto)[:600]}\n\nClassifique a qualidade."
        try:
            raw = gerar(prompt, sistema)
        except Exception as e:  # noqa: BLE001 — degrada honesto
            return {"status": "nao_avaliavel", "motivo": f"LLM indisponível ({str(e)[:50]})"}
        from compliance_agent.detectores.base import _parse_json
        dados = _parse_json(raw)
        nivel, _score, motivo = avaliar_rubrica(dados, _RUBRICA_JUSTIFICATIVA)
        if nivel is None or not isinstance(dados, dict):
            return {"status": "nao_avaliavel", "motivo": motivo}
        return {"status": (dados.get("nivel") or "").strip().lower(), "motivo": motivo}

    def _avaliar_interdependencia(self, pior_lote: dict, contexto: dict) -> dict:
        """Rubrica de interdependência técnica do lote. Atalho de teste: `_rubrica_interdep` no contexto.
        Sem rubrica/LLM → nao_avaliavel honesto."""
        pre = contexto.get("_rubrica_interdep")
        if pre is not None:
            nivel, _score, motivo = avaliar_rubrica(pre, _RUBRICA_INTERDEP)
            if nivel is None:
                return {"status": "nao_avaliavel", "motivo": motivo}
            return {"status": (pre.get("nivel") or pre.get("classificacao") or "").strip().lower(), "motivo": motivo}
        gerar = contexto.get("gerar")
        if gerar is None:
            return {"status": "nao_avaliavel", "motivo": "LLM ausente — interdependência não auditada (honesto)"}
        sistema = (
            "Você é auditor de controle externo. Os itens deste lote têm INTERDEPENDÊNCIA técnica real (operam como "
            "sistema único) ou só foram agrupados por conveniência? Responda SOMENTE com JSON: "
            '{"nivel":"integracao_necessaria|conveniencia","trecho":"<citação literal da descrição dos itens>"}. '
            "Sem trecho, não classifique."
        )
        prompt = (f"LOTE com {pior_lote['n_mercados']} mercados distintos: {', '.join(pior_lote['mercados'][:10])}\n\n"
                  "Há integração técnica necessária entre os itens?")
        try:
            raw = gerar(prompt, sistema)
        except Exception as e:  # noqa: BLE001 — degrada honesto
            return {"status": "nao_avaliavel", "motivo": f"LLM indisponível ({str(e)[:50]})"}
        from compliance_agent.detectores.base import _parse_json
        dados = _parse_json(raw)
        nivel, _score, motivo = avaliar_rubrica(dados, _RUBRICA_INTERDEP)
        if nivel is None or not isinstance(dados, dict):
            return {"status": "nao_avaliavel", "motivo": motivo}
        return {"status": (dados.get("nivel") or "").strip().lower(), "motivo": motivo}
