# -*- coding: utf-8 -*-
"""P3 · SOBREPREÇO NA ESTIMATIVA DE REFERÊNCIA (spec V2 do dono, §2/P3).

WRAPPER, não reimplementação. Reusa `precos_extract.sobrepreco_interno(registros)` — que compara o MESMO item
entre contratos/órgãos (chave = descrição normalizada) e flagga quando o maior preço unitário é ≥ 2× o menor
(a mesma coisa custou o dobro+ em outro lugar). A lógica de comparação/normalização fica no módulo reusado;
aqui só ADAPTAMOS ao schema fixo (spec §1.4), convertendo a MAGNITUDE do desvio em ÂNCORA (spec §1.2):

  REGRA DE ÂNCORA (código, nunca prompt) — por razão max/min do mesmo item:
    • razão ≥ 4.0 (o item custou 4×+ entre órgãos)   → 'forte'  (anomalia grave; explicação inocente improvável)
    • razão ≥ 3.0                                     → 'medio'  (anomalia clara; exige confirmação)
    • razão ≥ 2.0 (piso do detector reusado)          → 'fraco'  (compatível mas com explicações inocentes comuns)

  COERÊNCIA DE SINAIS (anti-outlier): `razao_max_min` (max/min) é frágil — um ÚNICO preço-outlier quase-zero
  (erro de unidade/digitação no MENOR preço) infla a razão para dezenas/centenas× e produz 'forte' FALSO, mesmo
  quando o maior preço mal supera a mediana (i.e., sem sobrepreço real). O sinal ROBUSTO é o desvio do MAIOR preço
  vs MEDIANA (`sobrepreco_pct_vs_mediana`), insensível a outlier baixo — alinhado à metodologia de preço de
  referência por mediana (IN SEGES/ME 65/2021, art. 6º, que afasta extremos). Por isso 'forte'/'medio' EXIGEM que
  o sinal robusto corrobore (mediana ≥ +100% p/ forte, ≥ +50% p/ medio); razão alta SEM desvio robusto → rebaixa
  p/ 'fraco' (indício de outlier baixo, não de sobrepreço — a exculpatória trata como erro de cadastro).

HONESTIDADE JFN (regra dura do spec P3): "Item inovador SEM referência → marcar 'sem_referencial', NÃO pontuar
sobrepreço sem base." Aqui: amostras insuficientes (`sobrepreco_interno` exige ≥ min_amostras p/ comparar) ⇒
`nao_avaliavel` honesto (campo ausente ≠ 0), e o detector NÃO inventa desvio. FALSOS POSITIVOS do spec: urgência
real / lote pequeno / logística difícil (interior, ilha) encarecem LEGITIMAMENTE — a exculpatória adversarial
recebe essas hipóteses; só sobrevive o que passa.

Família "preco" (peso 0.8, §7.2)."""
from __future__ import annotations

from compliance_agent.detectores.base import Detector, ResultadoDetector, ancora


def _nivel_por_razao(razao: float, pct_vs_mediana: float | None = None) -> str:
    """Nível por magnitude da razão max/min, EXIGINDO coerência do sinal robusto (desvio vs mediana).

    `pct_vs_mediana` ausente (None) ⇒ comportamento legado (só razão); presente ⇒ gate anti-outlier:
    'forte'/'medio' só se o maior preço também desviar da MEDIANA (robusto a outlier baixo). Razão alta
    sem desvio robusto = outlier no menor preço (erro de unidade), não sobrepreço → rebaixa p/ 'fraco'."""
    bruto = "forte" if razao >= 4.0 else "medio" if razao >= 3.0 else "fraco"  # >= 2.0 (piso do sobrepreco_interno)
    if pct_vs_mediana is None:
        return bruto
    if bruto == "forte" and pct_vs_mediana < 100.0:
        return "medio" if pct_vs_mediana >= 50.0 else "fraco"
    if bruto == "medio" and pct_vs_mediana < 50.0:
        return "fraco"
    return bruto


class P3Sobrepreco(Detector):
    """Detector P3 — sobrepreço interno (mesmo item ≥2× entre órgãos), via `precos_extract.sobrepreco_interno`.

    `avaliar(contexto)` espera (entrada = item/contrato — um conjunto de registros do MESMO item entre órgãos):
      contexto["processo"] (ou ["item"], ["contrato"]): id do item/contrato avaliado.
      contexto["registros"]: list[dict] [{descricao, preco_unitario, ref, orgao?}] — os preços do item em
          vários contratos/órgãos (a base de comparação). É o que `sobrepreco_interno` consome.
      contexto["achados"] (opcional): retorno pré-computado de `sobrepreco_interno(registros)` (p/ teste/cache).
      contexto["min_amostras"] (opcional int, default 3): mínimo p/ comparar (sem isso → sem_referencial).

    Honesto: sem registros suficientes p/ comparar o mesmo item ⇒ `nao_avaliavel` ('sem_referencial'), nunca 0."""

    id = "P3"
    nome = "Sobrepreço na estimativa (interno, mesmo item entre órgãos)"
    familia = "preco"

    def avaliar(self, contexto: dict) -> ResultadoDetector:
        processo = str(contexto.get("processo") or contexto.get("item") or contexto.get("contrato")
                       or contexto.get("id") or "?")
        res = self._novo(processo, status="nao_avaliavel")
        min_amostras = int(contexto.get("min_amostras") or 3)

        achados = contexto.get("achados")
        if achados is None:
            registros = contexto.get("registros") or []
            if not registros:
                res.motivo_refutacao = ("nao_avaliavel: sem registros de preço p/ comparar (sem_referencial) — "
                                        "item sem referência NÃO pontua sobrepreço (regra dura do spec P3)")
                res.valores = {"n_registros": 0}
                return res
            try:
                from compliance_agent.precos_extract import sobrepreco_interno
                achados = sobrepreco_interno(registros, min_amostras=min_amostras)
            except Exception as e:  # noqa: BLE001 — módulo de preços indisponível: honesto, não 0
                res.motivo_refutacao = f"nao_avaliavel: sobrepreco_interno indisponível ({str(e)[:60]})"
                return res

        if not achados:
            # ou amostra < min_amostras (sem referencial), ou nenhum item com razão ≥ 2× → honestamente:
            # se havia registros mas nenhum item alcançou min_amostras, é sem_referencial (nao_avaliavel);
            # se havia comparação suficiente mas nada ≥2×, é descartado. Distinguimos pelo nº de registros.
            registros = contexto.get("registros") or []
            from collections import Counter
            from compliance_agent.precos_extract import _norm  # normalização do próprio módulo reusado
            cnt = Counter(_norm(r.get("descricao", "")) for r in registros if r.get("preco_unitario"))
            tem_item_comparavel = any(v >= min_amostras for v in cnt.values())
            if not tem_item_comparavel:
                res.status = "nao_avaliavel"
                res.motivo_refutacao = (f"nao_avaliavel: nenhum item com ≥ {min_amostras} amostras p/ comparar "
                                        "(sem_referencial) — não se pontua sobrepreço sem base (spec P3)")
            else:
                res.status = "descartado"
                res.motivo_refutacao = "itens comparados sem dispersão relevante (nenhum ≥ 2× entre órgãos)"
                res.explicacao_inocente = "preços do mesmo item homogêneos entre órgãos — sem indício de sobrepreço"
            res.valores = {"n_registros": len(registros), "itens_comparaveis": tem_item_comparavel}
            return res

        # achado principal = maior razão max/min (já vem ordenado desc por sobrepreco_interno)
        top = achados[0]
        razao = float(top.get("razao_max_min") or 0.0)
        pct_med = top.get("sobrepreco_pct_vs_mediana")
        nivel = _nivel_por_razao(razao, None if pct_med is None else float(pct_med))
        res.score = ancora(nivel)
        res.status = "confirmado"
        res.motivo_refutacao = f"sobrepreço interno: item custou {razao}× entre órgãos → âncora {nivel}"
        res.valores = {
            "n_itens_flagrados": len(achados),
            "item": top.get("item"),
            "razao_max_min": razao,
            "min": top.get("min"),
            "max": top.get("max"),
            "mediana": top.get("mediana"),
            "sobrepreco_pct_vs_mediana": top.get("sobrepreco_pct_vs_mediana"),
            "n_amostras": top.get("n"),
        }

        caro, barato = top.get("mais_caro") or {}, top.get("mais_barato") or {}
        res.add_evidencia(
            fonte="precos_extract.sobrepreco_interno",
            trecho=(f"item '{top.get('item')}' ({top.get('n')} amostras): R$ {top.get('min')} "
                    f"(órgão {barato.get('orgao') or '?'}, ref {barato.get('ref') or '?'}) vs "
                    f"R$ {top.get('max')} (órgão {caro.get('orgao') or '?'}, ref {caro.get('ref') or '?'}) "
                    f"= {razao}× (mediana R$ {top.get('mediana')}; "
                    f"+{top.get('sobrepreco_pct_vs_mediana')}% vs mediana)"),
        )
        res.explicacao_inocente = ("FALSOS POSITIVOS a descartar (spec P3): urgência real, lote pequeno ou "
                                   "logística difícil (interior, ilha) encarecem legitimamente — ajustar a "
                                   "referência por essas condições antes de imputar sobrepreço; inflação setorial "
                                   "aguda exige comparação no mesmo trimestre.")
        return res
