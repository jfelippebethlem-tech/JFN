# -*- coding: utf-8 -*-
"""Execução MEDIDA acima do valor do contrato antes do termo aditivo que daria cobertura (serviço feito sem contrato
que o cubra; o aditivo vem depois para regularizar).

ORIGEM (perícia integral 18/11/2026, conferida na fonte): FAETEC × Scalle (ex-Nolasco), SEI-260005/007167/2024 —
planilha "MEDIÇÃO CONSOLIDADA" (doc 18): "Total do Acum. (COM BDI)" de R$ 53.772.203,62 na 11ª medição (dez/23)
contra "Dá-se a este contrato o valor total de R$ 45.872.202,68" (doc 12); o 1º TA (acréscimo + prorrogação +
reajuste) só foi assinado em 24/01/2024 (extrato, doc 15). Também INEA × RJL2 (070002/017689/2024): medido acima do
saldo, retido e pago após o TA.

NORMA: L8 art. 60, parágrafo único (contrato verbal é nulo), art. 65 §1º; L4.320 art. 60 e 62 (despesa sem empenho e
liquidação do não contratado); L14.133 art. 95 §2º e 132 ("a formalização do termo aditivo é condição para a execução
das prestações determinadas pela Administração").

SINAL: (1) valor inicial do contrato (cláusula "Dá-se a este contrato o valor total de R$" / "O valor total do
presente Contrato é de R$") no contrato JUNTADO ao processo — um único valor; (2) datas dos termos aditivos do mesmo
contrato (corpo do termo ou extrato com "Termo Aditivo ao Contrato nº X" e "DATA DA ASSINATURA"); (3) série do
acumulado medido: planilha consolidada ("Período de Referência" × "Total do Acum.") ou tabela de medições (Nª, início,
fim, valores, acumulado). GRAU: forte = mês de referência ANTERIOR ao mês do 1º termo aditivo com acumulado > valor
inicial; medio = acumulado > valor vigente na data depois de termos cujo valor foi lido; fraco nunca.
EXPLICAÇÕES INOCENTES: planilha com reajuste embutido (o reajuste em si não exige aditivo — anotado se a planilha
cita reajuste); contrato juntado é outro (exigido: número do contrato da planilha/termo = o do contrato juntado
quando ambos legíveis); acumulado inclui itens de outro contrato (pasta contaminada — docs alheios excluídos).
"""
from __future__ import annotations

import re

from compliance_agent.padroes import _aditivos_comum as C

ID = "execucao_acima_do_valor_antes_do_aditivo"
TOLERANCIA = 0.001
_RE_VALOR_INICIAL = re.compile(
    r"(?:d[áa]-se\s+a(?:o)?\s+(?:este|presente)\s+contrato\s+o\s+valor\s+(?:total|global)?\s*de|"
    r"o\s+valor\s+(?:total|global)\s+do\s+presente\s+contrato\s+[ée]\s+de|"
    r"valor\s+(?:total|global)\s+(?:estimado\s+)?do\s+contrato\s*(?:[ée]\s+de|:))\s*R\$\s*([\d.]{1,15},\d{2})", re.I)
_RE_TIT_CONTRATO = re.compile(r"^\s*contrato\b", re.I)
_RE_TIT_NAO = re.compile(r"aditivo|apostil|consulta|minuta|publica|extrato|rescis|saldo", re.I)
_RE_TIT_MED = re.compile(r"medi[çc][ãa]o|boletim|planilha|parecer\s+t[ée]cnico|controle", re.I)
_MESES = {"jan": 1, "fev": 2, "mar": 3, "abr": 4, "mai": 5, "jun": 6, "jul": 7, "ago": 8, "set": 9, "out": 10,
          "nov": 11, "dez": 12}
_RE_PERIODOS = re.compile(r"Per[íi]odo\s+de\s+Refer[êe]ncia\s*:?\s*\n((?:\s*[a-zç]{3}/\d{2}\s*\n)+)", re.I)
_RE_TOTAL_ACUM = re.compile(r"Total\s+do\s+Acum[^\n]*\n((?:\s*(?:[\d.]+,\d{2}|-)\s*\n(?:\s*R\$[^\n]*\n)?)+)", re.I)
_RE_LINHA_B = re.compile(r"(?m)^\s*(\d{1,2})ª[^\n]{0,30}\n(?:[^\n]{0,40}\n)?\s*(\d{2}/\d{2}/\d{4})\s*\n\s*(\d{2}/\d{2}/\d{4})"
                         r"\s*\n((?:\s*(?:[\d.]+,\d{2}|-)\s*\n\s*R\$[^\n]*\n){1,4})")
_RE_EXTRATO_TA = re.compile(r"Termo\s+Aditivo\s+(?:\d+/\d{4}\s+)?ao\s+Contrato\s*(?:INEA\s*)?(?:n[º°o.]*\s*)?"
                            r"(\d{1,4}\s*/\s*\d{2,4})", re.I)
_RE_DATA_ASS_EXT = re.compile(r"DATA\s+D[AE]\s+ASSINATURA\s*:?\s*(" + C.DATA_PADRAO + ")", re.I)


def serie_consolidada(texto: str) -> list[tuple[str, float]]:
    """[(AAAA-MM, acumulado)] da planilha 'Período de Referência' × 'Total do Acum.'. Função pura."""
    mp = _RE_PERIODOS.search(texto)
    ma = _RE_TOTAL_ACUM.search(texto)
    if not mp or not ma:
        return []
    meses = []
    for s in re.findall(r"([a-zç]{3})/(\d{2})", mp.group(1), re.I):
        m = _MESES.get(s[0].lower())
        if not m:
            return []
        meses.append(f"20{s[1]}-{m:02d}")
    vals = [C.num_br(v) for v in re.findall(r"[\d.]+,\d{2}", ma.group(1))]
    n = min(len(meses), len(vals))
    serie = [(meses[i], vals[i]) for i in range(n) if vals[i]]
    # acumulado é não decrescente; série que não é = leitura errada de colunas
    if any(serie[i][1] < serie[i - 1][1] - 0.01 for i in range(1, len(serie))):
        return []
    return serie


def serie_tabela(texto: str) -> list[tuple[str, float]]:
    """[(AAAA-MM do fim do período, acumulado)] da tabela de medições (Nª, início, fim, valores). Função pura."""
    if not re.search(r"acumulado", texto, re.I):
        return []
    out = []
    for m in _RE_LINHA_B.finditer(texto):
        vals = [C.num_br(v) for v in re.findall(r"[\d.]+,\d{2}", m.group(4))]
        vals = [v for v in vals if v]
        if not vals:
            continue
        fim = C.data_br(m.group(3))
        out.append((fim[:7], max(vals)))
    return out


def valor_inicial(docs: list[dict]) -> tuple[float | None, dict | None, str | None, int]:
    """(valor, doc, nº do contrato, nº de valores distintos). Mais de um valor distinto = ambíguo (None)."""
    achados = {}
    for d in docs:
        if d.get("alheio") or not _RE_TIT_CONTRATO.search(d["titulo"] or "") or _RE_TIT_NAO.search(d["titulo"] or ""):
            continue
        t = C.sem_rodape(C.ler(d))
        m = _RE_VALOR_INICIAL.search(t)
        if not m or not C.no_corpo(t, m.start()):
            continue
        v = C.num_br(m.group(1))
        mc = C.RE_CONTRATO_NO.search(d["titulo"] + "\n" + t[:4000])
        if v:
            achados.setdefault(v, (d, C.norm_contrato(mc.group(1)) if mc else None, C.trecho(t, m.start(), m.end(), 20)))
    if len(achados) != 1:
        return None, None, None, len(achados)
    v, (d, num, tr) = next(iter(achados.items()))
    return v, {**d, "trecho": tr}, num, 1


def eventos_aditivo(docs: list[dict], contrato: str | None) -> list[dict]:
    """Termos aditivos do contrato com data: [{data, total, incremento, doc}] (corpo do termo ou extrato)."""
    ev = {}
    for d in docs:
        if d.get("alheio") or not re.search(r"aditiv", d["titulo"] or "", re.I):
            continue
        t = C.sem_rodape(C.ler(d))
        if not t:
            continue
        if C.eh_termo_aditivo(d):
            m = C.RE_VALOR_TERMO.search(t) or C.RE_VALOR_TOTAL.search(t)
            pos = m.start() if m else 0
            num = C.contrato_antes(t, pos, 8000) if m else None
            if contrato and num and num != contrato:
                continue
            data = C.data_assinatura_apos(t, pos, 60000)
            if data:
                mt = C.RE_VALOR_TOTAL.search(t, pos, pos + 3000) if m else None
                mv = C.RE_VALOR_TERMO.search(t, pos, pos + 3000) if m else None
                ev.setdefault(data, {"data": data, "total": C.num_br(mt.group(1)) if mt else None,
                                     "incremento": C.num_br(mv.group(1)) if mv else None, "doc": d["i"]})
        for m in _RE_EXTRATO_TA.finditer(t):
            if contrato and C.norm_contrato(m.group(1)) != contrato:
                continue
            md = _RE_DATA_ASS_EXT.search(t, m.end(), m.end() + 2500)
            if not md:
                continue
            data = C.data_br(md.group(1))
            bloco = t[m.start(): md.end()]
            mt, mv = C.RE_VALOR_TOTAL.search(bloco), C.RE_VALOR_TERMO.search(bloco)
            ev.setdefault(data, {"data": data, "total": C.num_br(mt.group(1)) if mt else None,
                                 "incremento": C.num_br(mv.group(1)) if mv else None, "doc": d["i"],
                                 "trecho": C.trecho(t, m.start(), md.end(), 0)[:400]})
    return sorted(ev.values(), key=lambda e: e["data"])


def avaliar(v0: float, eventos: list[dict], serie: list[tuple[str, float]]) -> dict | None:
    """Primeiro mês com acumulado acima da cobertura. Função pura."""
    if not eventos:
        return None
    primeiro = eventos[0]["data"][:7]
    for mes, acum in serie:
        if mes < primeiro and acum > v0 * (1 + TOLERANCIA):
            return {"grau": "forte", "mes": mes, "acumulado": acum, "cobertura": v0, "primeiro_aditivo": eventos[0]}
    v, i = v0, 0
    for mes, acum in serie:
        while i < len(eventos) and eventos[i]["data"][:7] <= mes:
            e = eventos[i]
            if e["total"]:
                v = e["total"]
            elif e["incremento"]:
                v = v + e["incremento"]
            else:
                return None
            i += 1
        if i and acum > v * (1 + TOLERANCIA):
            return {"grau": "medio", "mes": mes, "acumulado": acum, "cobertura": v, "primeiro_aditivo": eventos[0]}
    return None


def varrer(limite: int | None = None) -> dict:
    idx = C.indice(limite=limite)["processos"]
    funil = {"processos": len(idx), "com_planilha_de_medicao_legivel": 0, "com_valor_inicial": 0,
             "com_aditivo_datado": 0, "achados": 0}
    cob = {"valor_inicial_ambiguo": 0, "sem_contrato_juntado": 0, "sem_aditivo_datado": 0}
    achados = []
    for tag, p in idx.items():
        series = []
        for d in p["docs"]:
            if d.get("alheio") or not _RE_TIT_MED.search(d["titulo"] or ""):
                continue
            t = C.ler(d)
            s = serie_consolidada(t) or serie_tabela(t)
            if s:
                series.append((d, s))
        if not series:
            continue
        funil["com_planilha_de_medicao_legivel"] += 1
        v0, dc, num, n = valor_inicial(p["docs"])
        if v0 is None:
            cob["valor_inicial_ambiguo" if n > 1 else "sem_contrato_juntado"] += 1
            continue
        funil["com_valor_inicial"] += 1
        ev = eventos_aditivo(p["docs"], num)
        if not ev:
            cob["sem_aditivo_datado"] += 1
            continue
        funil["com_aditivo_datado"] += 1
        melhor = None
        for d, s in series:
            r = avaliar(v0, ev, s)
            if r and (melhor is None or (r["grau"], r["mes"]) < (melhor[1]["grau"], melhor[1]["mes"])):
                melhor = (d, r)
        if not melhor:
            continue
        funil["achados"] += 1
        d, r = melhor
        e = r["primeiro_aditivo"]
        achados.append(C.achado(
            C.chave_de_tag(tag), r["grau"],
            prova=(f"doc {dc['i']} ({dc['titulo'][:50]}) — \"{dc['trecho']}\"; doc {d['i']} ({d['titulo'][:60]}) — "
                   f"acumulado medido R$ {r['acumulado']:,.2f} no mês {r['mes']}; 1º termo aditivo do contrato "
                   f"assinado em {e['data']} (doc {e['doc']})"),
            porque=(f"Acumulado medido em {r['mes']} (R$ {r['acumulado']:,.2f}) excede a cobertura contratual vigente "
                    f"(R$ {r['cobertura']:,.2f}) " + ("ANTES do 1º termo aditivo" if r["grau"] == "forte" else
                                                         "mesmo após os termos lidos")
                    + f" — {r['acumulado'] / r['cobertura'] - 1:.1%} acima. Execução sem cobertura; conferir se a "
                      "planilha embute reajuste (que não exige aditivo) antes de concluir."),
            fonte=f"contrato + planilha de medição + termo/extrato ({p['fonte']})", contrato=num, valor_inicial=v0,
            mes=r["mes"], acumulado=r["acumulado"], cobertura=r["cobertura"], aditivo_data=e["data"]))
    return C.resultado(ID, funil["com_planilha_de_medicao_legivel"], cob, achados, funil)
