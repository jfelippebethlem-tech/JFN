# -*- coding: utf-8 -*-
"""Obra / serviço de engenharia de ESCOPO prorrogado como "serviço contínuo" (L8 art. 57, II) com valor cheio a cada
período.

ORIGEM (perícias integrais 18/11/2026, INEA): Geo Ambiental (SEI-070002/005897/2024: R$ 41,48 mi → R$ 132,70 mi),
Cobrape (004386/2024: 12 → 52 meses, NL "Natureza 449051 - Obras e Instalações"), RJL2 (023359/2024: Parecer
287/2023/INEA/GERCON — "a hipótese, aparentemente, não é de serviço contínuo"), Hydra (026015/2024), Lytoranea
(006459/2024), Via Expressa/Sudeste (003457/2024: 6 meses prorrogados 11 vezes, 3,8× o valor original pago).

POR QUE É VÍCIO. O art. 57, II, da Lei 8.666/93 (art. 106/107 da Lei 14.133/21) permite prorrogar por iguais períodos
só serviço CONTÍNUO; obra e serviço de engenharia de escopo têm prazo para entregar o objeto (art. 57, §1º) e se
prorrogam sem novo valor cheio. A própria despesa classificada como 4.4.90.51 (Obras e Instalações) contradiz o
rótulo "contínuo" do termo.

SINAL (determinístico), num termo aditivo próprio do processo:
  (a) prorrogação fundada no art. 57, II, ou "serviços contínuos"; e
  (b) "valor cheio": o valor do termo ≥ 80% do valor anterior do contrato (total − termo) — renovação do período
      inteiro, não acréscimo pontual;
  (c) despesa de OBRA: natureza 449051 / 4.4.90.51 / "Obras e Instalações" na NL/NE dos autos ou na NE do SIAFE.
GRAU: forte = (a)+(b)+(c); medio = (a)+(b) e objeto que se declara obra/engenharia ("execução de obra", "obras de",
"empreitada") sem a natureza 449051 nos autos; fraco = nunca emitido.
EXPLICAÇÕES INOCENTES: manutenção predial/conservação é contínua mesmo com natureza de obra em alguns entes
(registrada no achado se o objeto diz "manutenção"); erro de classificação orçamentária isolado.
"""
from __future__ import annotations

import re
import sqlite3

from compliance_agent.padroes import _aditivos_comum as C

ID = "obra_renovada_como_continuo"
RAZAO_VALOR_CHEIO = 0.80
_RE_57II = re.compile(r"art(?:igo)?\.?\s*57,?\s*(?:inciso\s+)?II\b|servi[çc]os?\s+(?:de\s+natureza\s+)?cont[íi]nu", re.I)
_RE_PRORROGA = re.compile(r"prorroga", re.I)
_RE_OBRA_NAT = re.compile(r"4\.?4\.?9\.?0\.?5\.?1|obras\s+e\s+instala[çc][õo]es", re.I)
_RE_OBRA_OBJ = re.compile(r"execu[çc][ãa]o\s+d[ae]\s+obras?|\bobras\s+de\b|empreitada|macrodrenagem|desassoreamento|"
                          r"canaliza[çc][ãa]o|pavimenta[çc][ãa]o|recupera[çc][ãa]o\s+ambiental", re.I)
_RE_MANUT = re.compile(r"manuten[çc][ãa]o|conserva[çc][ãa]o\s+predial", re.I)
_RE_TIT_NL_NE = re.compile(r"nota\s+de\s+(?:liquida|empenho)|\bNL\b|\bNE\b|empenho|liquida", re.I)


def renovacoes(texto: str) -> list[dict]:
    """Termos (no corpo) que prorrogam pelo art. 57 II com valor cheio. Função pura."""
    texto = C.sem_rodape(texto)
    out = []
    for m in C.RE_VALOR_TERMO.finditer(texto):
        if not C.no_corpo(texto, m.start()):
            continue
        janela = texto[max(0, m.start() - 6000): m.end() + 1500]
        if not (_RE_PRORROGA.search(janela) and _RE_57II.search(janela)):
            continue
        vt = C.num_br(m.group(1))
        mt = C.RE_VALOR_TOTAL.search(texto, m.end(), m.end() + 2500)
        tot = C.num_br(mt.group(1)) if mt else None
        if not vt or not tot or tot <= vt:
            continue
        anterior = tot - vt
        razao = vt / anterior
        if razao < RAZAO_VALOR_CHEIO:
            continue
        out.append({"valor_termo": vt, "valor_total": tot, "valor_anterior": round(anterior, 2), "razao": round(razao, 3),
                    "data": C.data_assinatura_apos(texto, m.end()), "contrato": C.contrato_antes(texto, m.start(), 8000),
                    "objeto_obra": bool(_RE_OBRA_OBJ.search(janela)), "manutencao": bool(_RE_MANUT.search(janela)),
                    "trecho": C.trecho(texto, m.start(), (mt.end() if mt else m.end()), 60)[:600]})
    return out


def _ne_obra_siafe() -> set[str]:
    try:
        con = C._con()
        try:
            return {k for (p,) in con.execute("SELECT DISTINCT processo FROM ne_siafe WHERE natureza LIKE '449051%'")
                    if (k := C.chave_processo(p))}
        finally:
            con.close()
    except sqlite3.Error:
        return set()


def varrer(limite: int | None = None) -> dict:
    idx = C.indice(limite=limite)["processos"]
    ne_obra = _ne_obra_siafe()
    funil = {"processos": len(idx), "com_termo_aditivo": 0, "renovacao_57II_valor_cheio": 0, "com_natureza_obra": 0}
    cob = {"termos_sem_texto": 0, "termos_alheios": 0,
           "nota": "NE do SIAFE só tem 2025 nesta base (ne_siafe); natureza também lida nas NL/NE dos autos"}
    achados = []
    for tag, p in idx.items():
        termos, fora = C.termos_do_processo(p)
        cob["termos_sem_texto"] += fora["sem_texto"]
        cob["termos_alheios"] += fora["alheios"]
        if not termos:
            continue
        funil["com_termo_aditivo"] += 1
        ren, vistos = [], set()
        for d, t in termos:
            for r in renovacoes(t):
                k = (r["valor_termo"], r["valor_total"])
                if k not in vistos:
                    vistos.add(k)
                    ren.append({**r, "doc": d["i"], "titulo": d["titulo"]})
        if not ren:
            continue
        funil["renovacao_57II_valor_cheio"] += 1
        chave = C.chave_de_tag(tag)
        prova_nat = None
        if chave in ne_obra:
            prova_nat = "SIAFE ne_siafe — natureza 449051 (Obras e Instalações) em NE deste processo"
        else:
            for d in p["docs"]:
                if d.get("alheio") or not _RE_TIT_NL_NE.search(d["titulo"] or ""):
                    continue
                t = C.ler(d)
                m = _RE_OBRA_NAT.search(t)
                if m:
                    prova_nat = f"doc {d['i']} ({d['titulo'][:60]}) — \"{C.trecho(t, m.start(), m.end(), 60)}\""
                    break
        if prova_nat:
            funil["com_natureza_obra"] += 1
        obra_obj = any(r["objeto_obra"] for r in ren)
        if prova_nat:
            g = "forte"
        elif obra_obj:
            g = "medio"
        else:
            continue
        ren.sort(key=lambda r: r["data"] or "")
        maior = max(r["valor_total"] for r in ren)
        primeiro_ant = min(r["valor_anterior"] for r in ren)
        prova = "; ".join(f"doc {r['doc']} — \"{r['trecho'][:300]}\"" for r in ren[:3])
        if prova_nat:
            prova += f"; natureza de obra: {prova_nat}"
        achados.append(C.achado(
            chave, g, prova=prova,
            porque=(f"{len(ren)} renovação(ões) pelo art. 57, II, com valor cheio (termo ≥ {RAZAO_VALOR_CHEIO:.0%} do "
                    f"valor anterior); contrato chega a R$ {maior:,.2f} (menor valor anterior lido R$ {primeiro_ant:,.2f})"
                    + ("; despesa classificada como OBRA (449051)" if prova_nat else "; objeto se declara obra/engenharia")
                    + (". Objeto cita manutenção — avaliar se é de fato contínuo" if any(r["manutencao"] for r in ren) else "")
                    + ". Obra/engenharia de escopo não se prorroga com novo valor cheio (L8 art. 57 §1º; L14.133 art. 111)."),
            fonte=f"termos aditivos ({termos[0][0]['fonte']}) + NL/NE", renovacoes=[{k: r[k] for k in (
                "doc", "valor_termo", "valor_total", "razao", "data", "contrato")} for r in ren]))
    return C.resultado(ID, funil["com_termo_aditivo"], cob, achados, funil)
