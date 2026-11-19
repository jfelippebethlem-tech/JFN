# -*- coding: utf-8 -*-
"""O percentual que o termo DECLARA × o crescimento REAL do faturamento mensal pago (OB) depois dele.

ORIGEM (perícias integrais 18/11/2026): SEAP × Seleta, SEI-210108/000153/2023 — 5º TA "14,59%" que, medido pelo
objeto (refeições/mês), era +84%; Cassarotti (000163/2023) — 3º TA "25%" (R$ 4,84 mi) contra R$ 17,24 mi pagos às
unidades absorvidas em 11 meses; Qualybem (000158/2023) — faturamento do presídio absorvido acima do valor do termo.
Memória do laudo: "o percentual que o termo aditivo declara não basta: medir o acréscimo pelo OBJETO".

SINAL (determinístico): para cada termo que declara acréscimo de P% (assinado na data D), a mediana do pago mensal
(OB `_ob_paga`, por mês de emissão) nos 6 meses ANTES de D × a mediana nos meses 2 a 7 DEPOIS de D (o 1º mês após o
termo costuma pagar competência antiga). Crescimento g = depois/antes − 1.
GRAU: forte = g > teto (25%, ou 50% reforma) + 10 p.p. E g ≥ 2 × P; medio = g ≥ P + 20 p.p. e g > teto; fraco nunca.
Exige ≥ 3 meses com OB de cada lado (senão INDISPONÍVEL, contado na cobertura).
EXPLICAÇÕES INOCENTES (anotadas): reajuste/repactuação no mesmo período (o achado lista os termos de reajuste nos
autos); pagamento de competências atrasadas (mediana, não média); o processo de pagamento passou a concentrar OB de
outro processo (a soma por processo é PISO e a grafia é normalizada).
LIMITE CONHECIDO: "unidade nova nas NF sem aditivo" (Qualybem 000160/2023) não é coberta aqui — depende de cruzar a
lista de unidades do contrato com as NF por unidade, e o OCR das planilhas da SEAP é inutilizável (laudo 000153).
"""
from __future__ import annotations

import re
import statistics

from compliance_agent import limites_aditivo as L
from compliance_agent.padroes import _aditivos_comum as C

ID = "acrescimo_medido_pelo_objeto"
MESES_ANTES, PULA, MESES_DEPOIS, MIN_MESES = 6, 1, 6, 3
_RE_REAJ = re.compile(r"reajust|repactua|reequil[íi]brio|IPCA|INCC|IGP-?M", re.I)


def _mes(ym: str, delta: int) -> str:
    a, m = int(ym[:4]), int(ym[5:7])
    t = a * 12 + (m - 1) + delta
    return f"{t // 12:04d}-{t % 12 + 1:02d}"


def crescimento(mensal: dict[str, float], data: str) -> dict | None:
    """Mediana antes × depois de `data` ('AAAA-MM-DD'). Função pura."""
    ym = data[:7]
    antes = [mensal[k] for k in (_mes(ym, -i) for i in range(1, MESES_ANTES + 1)) if mensal.get(k, 0) > 0]
    depois = [mensal[k] for k in (_mes(ym, PULA + i) for i in range(1, MESES_DEPOIS + 1)) if mensal.get(k, 0) > 0]
    if len(antes) < MIN_MESES or len(depois) < MIN_MESES:
        return None
    a, d = statistics.median(antes), statistics.median(depois)
    if a <= 0:
        return None
    return {"mediana_antes": round(a, 2), "mediana_depois": round(d, 2), "g": round(d / a - 1, 4),
            "n_antes": len(antes), "n_depois": len(depois)}


def avaliar(pct: float, g: float, teto: float) -> str | None:
    p = pct / 100
    if g > teto + 0.10 and g >= 2 * p:
        return "forte"
    if g >= p + 0.20 and g > teto:
        return "medio"
    return None


def varrer(limite: int | None = None) -> dict:
    idx = C.indice(limite=limite)["processos"]
    funil = {"processos": len(idx), "com_declaracao_datada": 0, "com_ob": 0, "serie_suficiente": 0, "achados": 0}
    cob = {"sem_ob_no_siafe": 0, "serie_curta": 0, "nota": "OB por processo é PISO (grafias normalizadas)"}
    achados = []
    obp = C.ob_por_processo()
    for tag, p in idx.items():
        termos, _ = C.termos_do_processo(p)
        if not termos:
            continue
        decl = C.declaracoes_do_processo(termos)
        c = C.contrato_principal(decl)
        itens = [x for x in decl.get(c, []) if x["data"] and not _RE_REAJ.search(x["trecho"])] if c else []
        if not itens:
            continue
        funil["com_declaracao_datada"] += 1
        chave = C.chave_de_tag(tag)
        if chave not in obp:
            cob["sem_ob_no_siafe"] += 1
            continue
        funil["com_ob"] += 1
        mensal = C.ob_mensal(chave)
        objeto = " ".join(t[:6000] for _, t in termos[:3])
        teto = L.teto_acrescimo(L.tipo_objeto(objeto))
        reajustes = sorted({C.data_assinatura_apos(t, m.end()) or "?" for _, t in termos
                            for m in re.finditer(r"reajust|repactua", t[:20000], re.I)} - {"?"})
        melhor = None
        for x in itens:
            cr = crescimento(mensal, x["data"])
            if not cr:
                continue
            funil["serie_suficiente"] += 1
            g = avaliar(x["pct"], cr["g"], teto)
            if g and (melhor is None or cr["g"] - x["pct"] / 100 > melhor[2]["g"] - melhor[0]["pct"] / 100):
                melhor = (x, g, cr)
        if not itens or melhor is None:
            if itens and not any(crescimento(mensal, x["data"]) for x in itens):
                cob["serie_curta"] += 1
            continue
        x, g, cr = melhor
        funil["achados"] += 1
        perto = [r for r in reajustes if abs(int(r[:4]) * 12 + int(r[5:7]) - int(x["data"][:4]) * 12 - int(x["data"][5:7])) <= 7]
        achados.append(C.achado(
            chave, g,
            prova=(f"doc {x['doc']} — \"{x['trecho'][:220]}\" (assinado {x['data']}); SIAFE OB pagas: mediana mensal "
                   f"R$ {cr['mediana_antes']:,.2f} nos {cr['n_antes']} meses antes × R$ {cr['mediana_depois']:,.2f} "
                   f"nos meses 2–7 depois ({cr['n_depois']} meses)"),
            porque=(f"Termo declara acréscimo de {x['pct']:.2f}%; o pago mensal cresceu {cr['g']:.0%}"
                    f" (teto {teto:.0%}). "
                    + (f"Há termo de reajuste/repactuação a ≤7 meses ({', '.join(perto)}) — descontar antes de concluir. "
                       if perto else "Nenhum termo de reajuste nos autos a ≤7 meses. ")
                    + "Mediana afasta pagamento de atrasados; OB por processo é piso."),
            fonte="termo aditivo + SIAFE ob_orcamentaria_siafe (_ob_paga)", contrato=c, pct_declarado=x["pct"],
            crescimento_pago=cr["g"], reajustes_proximos=perto, **{k: cr[k] for k in ("mediana_antes", "mediana_depois")}))
    return C.resultado(ID, funil["com_declaracao_datada"], cob, achados, funil)
