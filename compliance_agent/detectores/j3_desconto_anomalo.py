# -*- coding: utf-8 -*-
"""J3 · DESCONTO ANÔMALO (spec V2 do dono, §4/J3).

Mecanismo: em competição real, o desconto sobre o valor estimado é substantivo; sob cartel ou direcionamento, o
vencedor fecha RENTE AO TETO (desconto irrisório). O desconto médio do órgão é um termômetro estrutural de
competição. Conluio quase nunca se prova num certame isolado — prova-se na SÉRIE (descontos baixos persistentes).

PARÂMETROS OBJETIVOS (no CÓDIGO — limiar nunca vai ao prompt do LLM, spec §1.3):
  • DESCONTO = (valor_estimado − valor_homologado) / valor_estimado.
      – desconto < 2% (rente ao teto) .................................. 'medio' (anomalia pontual, exige confirmação)
  • RECORRÊNCIA: desconto baixo PERSISTENTE exige SÉRIE ≥ 12 certames do órgão (spec §1.5). Sem série suficiente,
    o componente de recorrência é `nao_avaliavel` — 1 certame isolado NÃO sustenta 'recorrente'.
      – desconto baixo recorrente (≥ metade da série < 2%) ............. 'forte'
  • COMPARAÇÃO com baseline: `desconto_mercado_categoria` (ou `desconto_medio_orgao`) — o vencedor descontou
    MUITO menos que a categoria? ⇒ agrava (decil inferior estrutural).

TESTE EXCULPATÓRIO (spec): COMMODITY / preço TABELADO (combustível, medicamento CMED) → desconto naturalmente
baixo, LEGÍTIMO (margem fina). `item_preco_regulado=True` rebaixa. 1 certame isolado não sustenta recorrência —
estimativas bem-feitas e mercados de margem fina geram descontos baixos lícitos; comparar categoria contra
categoria, nunca contra um número mágico universal.

HONESTIDADE JFN: indício ≠ acusação; sem `valor_estimado` E `valor_homologado` → nao_avaliavel (campo ausente ≠ 0);
sem série ≥ 12 → recorrência nao_avaliavel (não inventamos persistência); nunca inventa número.
"""
from __future__ import annotations

from compliance_agent.detectores.base import Detector, ResultadoDetector, ancora

# Limiares (CÓDIGO, nunca no prompt — spec §1.3).
_DESCONTO_IRRISORIO = 0.02   # < 2% = rente ao teto
_SERIE_MIN_RECORRENCIA = 12  # série mínima p/ afirmar "recorrente" (spec §1.5: 12+ meses de base local)


def _num(v) -> float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    return None


def _desconto(estimado: float, homologado: float) -> float | None:
    if estimado is None or homologado is None or estimado <= 0:
        return None
    return (estimado - homologado) / estimado


class J3DescontoAnomalo(Detector):
    """Detector J3 — desconto anômalo / irrisório recorrente (screen estrutural de competição).

    `avaliar(contexto)` espera:
      contexto["processo"]: id do certame/processo.
      contexto["valor_estimado"]: teto/estimativa de referência (num > 0).
      contexto["valor_homologado"]: valor do vencedor homologado (num).
      contexto["desconto_medio_orgao"] (opcional): desconto médio histórico do órgão (baseline interno).
      contexto["desconto_mercado_categoria"] (opcional): desconto típico da CATEGORIA no mercado (baseline externo).
      contexto["serie_certames_orgao"] (opcional): list[dict] {valor_estimado, valor_homologado} — série do órgão
          p/ aferir RECORRÊNCIA (precisa ≥ 12 certames; senão o componente recorrência é nao_avaliavel).
      contexto["item_preco_regulado"] (opcional bool): commodity/preço tabelado → exculpatória (rebaixa).

    Honesto: sem valor_estimado>0 E valor_homologado → nao_avaliavel (campo ausente ≠ 0)."""

    id = "J3"
    nome = "Desconto anômalo / irrisório recorrente"
    familia = "conluio"  # J3 — peso 0.85 (conluio) na convergência §7.2

    def avaliar(self, contexto: dict) -> ResultadoDetector:
        processo = str(contexto.get("processo") or contexto.get("id") or "?")
        res = self._novo(processo, status="nao_avaliavel")

        estimado = _num(contexto.get("valor_estimado"))
        homologado = _num(contexto.get("valor_homologado"))
        desc = _desconto(estimado, homologado) if (estimado is not None and homologado is not None) else None

        if desc is None:
            res.motivo_refutacao = (
                "nao_avaliavel: faltam valor_estimado (>0) e/ou valor_homologado — sem base para o desconto "
                "(campo ausente ≠ 0); não inventamos número")
            res.valores = {"tem_estimado": estimado is not None and (estimado or 0) > 0,
                           "tem_homologado": homologado is not None}
            return res

        item_regulado = bool(contexto.get("item_preco_regulado"))
        desc_categoria = _num(contexto.get("desconto_mercado_categoria"))
        desc_orgao = _num(contexto.get("desconto_medio_orgao"))

        valores: dict = {
            "valor_estimado": round(estimado, 2),
            "valor_homologado": round(homologado, 2),
            "desconto": round(desc, 4),
            "desconto_pct": round(desc * 100, 2),
            "limiar_irrisorio_pct": _DESCONTO_IRRISORIO * 100,
            "desconto_mercado_categoria": desc_categoria,
            "desconto_medio_orgao": desc_orgao,
            "item_preco_regulado": item_regulado,
        }

        score = 0.0
        razoes: list[str] = []

        # ── REGRA OBJETIVA: desconto irrisório (rente ao teto) ──
        if desc < _DESCONTO_IRRISORIO and not item_regulado:
            score = max(score, ancora("medio"))
            razoes.append(f"desconto irrisório ({desc:.1%} < {_DESCONTO_IRRISORIO:.0%}) — vencedor fechou rente ao teto")
            res.add_evidencia(
                fonte="valores do certame (estimado × homologado)",
                trecho=(f"estimado={estimado:,.2f}, homologado={homologado:,.2f} ⇒ desconto {desc:.2%} "
                        f"(< {_DESCONTO_IRRISORIO:.0%}, rente ao teto)"))
        elif desc < _DESCONTO_IRRISORIO and item_regulado:
            razoes.append(f"desconto baixo ({desc:.1%}) MAS item de preço REGULADO/tabelado — exculpatória "
                          "(desconto naturalmente baixo, margem fina) — não pontua sozinho")

        # ── COMPARAÇÃO com baseline de categoria (agrava se muito abaixo da categoria) ──
        baseline = desc_categoria if desc_categoria is not None else desc_orgao
        if baseline is not None and baseline > 0 and desc < baseline * 0.5 and not item_regulado:
            score = min(1.0, max(score, ancora("medio")) + 0.10) if score > 0 else ancora("medio")
            razoes.append(f"desconto {desc:.1%} muito abaixo do baseline da categoria/órgão ({baseline:.1%}) — "
                          "decil inferior estrutural")

        # ── RECORRÊNCIA (precisa série ≥ 12; senão componente nao_avaliavel) ──
        rec = self._recorrencia(contexto.get("serie_certames_orgao") or [])
        valores["recorrencia"] = rec["resumo"]
        if rec["status"] == "recorrente":
            score = max(score, ancora("forte"))
            razoes.append(rec["motivo"])
            res.add_evidencia(fonte="série de certames do órgão", trecho=rec["motivo"])
        elif rec["status"] == "nao_avaliavel":
            razoes.append(rec["motivo"])  # série insuficiente — honesto, não inventa persistência

        if score <= 0:
            res.status = "descartado"
            res.motivo_refutacao = (
                f"desconto de {desc:.1%} compatível com competição/estimativa realista; sem recorrência de desconto "
                "irrisório nem distância anômala do baseline da categoria — sem indício")
            res.valores = valores
            res.explicacao_inocente = "desconto compatível com a categoria; estimativa de referência bem calibrada"
            return res

        res.score = round(score, 4)
        res.status = "confirmado"
        res.valores = valores
        res.motivo_refutacao = "; ".join(razoes)
        res.explicacao_inocente = (
            "FALSO POSITIVO a descartar (spec J3): COMMODITY / preço TABELADO (combustível, medicamento CMED) tem "
            "desconto naturalmente baixo e LÍCITO (margem fina); estimativas bem-feitas geram descontos baixos "
            "legítimos. Comparar categoria contra categoria, nunca número mágico universal; 1 certame isolado NÃO "
            "sustenta recorrência. Cruzar com P3 (o teto era inflado? desconto baixo sobre teto alto = sobrepreço duplo).")
        return res

    def _recorrencia(self, serie: list[dict]) -> dict:
        """Afere recorrência de desconto irrisório na série do órgão. EXIGE série ≥ 12 certames (spec §1.5) —
        sem isso, o componente é nao_avaliavel (honesto: não inventamos persistência). ≥ metade da série com
        desconto < 2% ⇒ 'recorrente'."""
        descontos = []
        for c in serie:
            if not isinstance(c, dict):
                continue
            e, h = _num(c.get("valor_estimado")), _num(c.get("valor_homologado"))
            d = _desconto(e, h) if (e is not None and h is not None) else None
            if d is not None:
                descontos.append(d)
        n = len(descontos)
        if n < _SERIE_MIN_RECORRENCIA:
            return {"status": "nao_avaliavel",
                    "resumo": {"n_serie": n, "minimo": _SERIE_MIN_RECORRENCIA},
                    "motivo": (f"recorrência nao_avaliavel: série de {n} certame(s) < {_SERIE_MIN_RECORRENCIA} "
                               "necessários (spec §1.5) — 1 certame isolado não sustenta 'recorrente' (honesto)")}
        n_irrisorios = sum(1 for d in descontos if d < _DESCONTO_IRRISORIO)
        frac = n_irrisorios / n
        if frac >= 0.5:
            return {"status": "recorrente",
                    "resumo": {"n_serie": n, "n_descontos_irrisorios": n_irrisorios, "fracao": round(frac, 3)},
                    "motivo": (f"desconto irrisório RECORRENTE: {n_irrisorios}/{n} certames ({frac:.0%}) com desconto "
                               f"< {_DESCONTO_IRRISORIO:.0%} — padrão estrutural de baixa competição")}
        return {"status": "ausente",
                "resumo": {"n_serie": n, "n_descontos_irrisorios": n_irrisorios, "fracao": round(frac, 3)},
                "motivo": f"sem recorrência: só {n_irrisorios}/{n} certames com desconto irrisório"}
