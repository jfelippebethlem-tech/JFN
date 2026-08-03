# -*- coding: utf-8 -*-
"""Olhar GLOBAL sobre o processo inteiro — map-reduce sobre todos os documentos.

O buraco que isto fecha. O 360 agrega SINAIS (detectores, lacunas, juízo por documento), mas
ninguém lia o CONJUNTO. Num processo de 484 documentos e 3 milhões de caracteres — a obra de
macrodrenagem do Jacarezinho, R$ 129.595.387,83 — a casa produzia uma lista de achados e nenhuma
narrativa: em que ordem as coisas aconteceram, quem decidiu o quê, onde os documentos se
contradizem, o que o processo diz de si mesmo.

Nenhum modelo lê 3 milhões de caracteres de uma vez, e a resposta não é ler menos: é ler em três
tempos.

  1. **MAPA** — uma ficha por documento (`fichas`): fase, tipo, data, quem assinou, valores,
     números de contrato citados e o juízo já pago em `doc_veredito`. Determinístico, sobre o
     texto INTEIRO (o corte de 20.000 caracteres morreu em 2026-08-03).
  2. **REDUÇÃO por fase** (`por_fase`) — o esqueleto do processo: quantos documentos, o intervalo
     de datas, quem assina, quanto se fala em dinheiro em cada etapa.
  3. **CONFRONTO entre documentos** (`contradicoes`) — o que só aparece olhando o conjunto: fase
     que termina depois da seguinte, valor que aparece com dois números, contrato de outro
     processo, assinante que decide em etapas incompatíveis.

O veredito final (`sintetizar`) usa as FICHAS, nunca o texto cru: é o que permite abarcar um
processo inteiro dentro de qualquer janela. A camada subjetiva é opcional e injetável; sem ela, a
síntese determinística sai igual — mais pobre em prosa, idêntica em fato.

HONESTIDADE: a síntese não inventa nexo. Onde falta documento (lacuna de captura declarada), ela
diz que a leitura é parcial; onde a data não existe, não se afirma ordem.
"""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import date

from compliance_agent.sei.instrumento_assinatura import assinaturas

_RE_VALOR = re.compile(r"R\$\s*([\d\.]{1,15},\d{2})")
_RE_CONTRATO = re.compile(r"contrato\s*(?:n?[ºo°.]?\s*)?(\d{1,4}\s*/\s*\d{4})", re.I)
_RE_DATA = re.compile(r"\b(\d{2})/(\d{2})/(\d{4})\b")

ORDEM_FASES = ("planejamento", "selecao", "contratacao", "execucao", "despesa",
               "controle", "tramitacao", "indefinida")


def _valor(txt: str) -> float | None:
    m = _RE_VALOR.search(txt or "")
    if not m:
        return None
    try:
        return float(m.group(1).replace(".", "").replace(",", "."))
    except ValueError:
        return None


def _data(txt: str) -> date | None:
    for d, mth, a in _RE_DATA.findall(txt or "")[:8]:
        try:
            return date(int(a), int(mth), int(d))
        except ValueError:
            continue
    return None


def _cmp(dstr: str) -> tuple:
    """Chave de ordenação de 'dd/mm/aaaa' — ANO primeiro. Usada na redução e no confronto."""
    try:
        d, m, a = (dstr or "01/01/1900").split("/")
    except ValueError:
        return ("1900", "01", "01")
    return (a, m, d)


def fichas(docs: list[dict], vereditos: dict[int, dict] | None = None) -> list[dict]:
    """MAPA: uma ficha compacta por documento. É o que a síntese lê no lugar do texto cru."""
    ver = vereditos or {}
    saida = []
    for d in docs or []:
        texto = d.get("texto") or ""
        ass = assinaturas(texto)
        i = d.get("i")
        try:
            i = int(i)
        except (TypeError, ValueError):
            i = -1
        v = ver.get(i) or {}
        saida.append({
            "i": i, "ref": d.get("ref") or d.get("titulo") or "", "tipo": d.get("tipo") or "",
            "fase": d.get("fase") or "indefinida", "chars": len(texto),
            "data": (ass[0]["data"] if ass else None),
            "assinantes": [a["nome"] for a in ass],
            "valor": _valor(texto),
            "contratos_citados": sorted({re.sub(r"\s+", "", m.group(1))
                                         for m in _RE_CONTRATO.finditer(texto)}),
            "escala": v.get("escala"),
            "juizo": (v.get("justificativa_curta") or "")[:200],
        })
    return saida


def por_fase(fs: list[dict]) -> dict[str, dict]:
    """REDUÇÃO: o esqueleto do processo, fase a fase — o que uma lista de achados não mostra."""
    grupos: dict[str, list[dict]] = defaultdict(list)
    for f in fs:
        grupos[f["fase"]].append(f)
    saida = {}
    for fase in ORDEM_FASES:
        g = grupos.get(fase)
        if not g:
            continue
        # ordena por ANO/mês/dia: 'dd/mm/aaaa' como texto ordena pelo DIA, e a fase saía
        # "de 08/12/2025 a 28/11/2025" — início depois do fim. Mesma armadilha já registrada no
        # acervo para o `data_emissao` do SIAFE.
        datas = sorted((x["data"] for x in g if x["data"]), key=_cmp)
        valores = [x["valor"] for x in g if x["valor"]]
        escalas = [x["escala"] for x in g if x["escala"]]
        assinantes: list[str] = []
        for x in g:
            assinantes += x["assinantes"]
        saida[fase] = {
            "n_docs": len(g), "chars": sum(x["chars"] for x in g),
            "de": datas[0] if datas else None, "ate": datas[-1] if datas else None,
            "maior_valor": max(valores) if valores else None,
            "assinantes": sorted(set(assinantes)),
            "julgados": len(escalas),
            "viciados": sum(1 for e in escalas if e == 3),
            "frageis": sum(1 for e in escalas if e == 2),
        }
    return saida


def contradicoes(fs: list[dict]) -> list[dict]:
    """CONFRONTO: o que só aparece olhando o conjunto. Cada item cita os documentos envolvidos."""
    achados: list[dict] = []

    # 1) fase que TERMINA depois do início da seguinte — a ordem dos atos é o esqueleto do controle
    fases_com_data = {}
    for fase, r in por_fase(fs).items():
        if r["de"] and r["ate"]:
            fases_com_data[fase] = (r["de"], r["ate"])
    seq = [f for f in ORDEM_FASES if f in fases_com_data and f not in ("tramitacao", "indefinida")]
    for a, b in zip(seq, seq[1:]):
        fim_a, ini_b = fases_com_data[a][1], fases_com_data[b][0]
        if _cmp(fim_a) > _cmp(ini_b):
            achados.append({
                "codigo": "G1_FASES_SOBREPOSTAS",
                "diz": (f"a fase de {a} só termina em {fim_a}, depois de {b} começar em {ini_b} — "
                        "as etapas do processo se sobrepõem no tempo"),
                "evidencia": f"{a}: até {fim_a} · {b}: desde {ini_b}"})

    # 2) o MESMO documento citando contrato diferente do que o processo discute
    todos = [c for f in fs for c in f["contratos_citados"]]
    if todos:
        principal = max(set(todos), key=todos.count)
        for f in fs:
            alheios = [c for c in f["contratos_citados"] if c != principal]
            if alheios and principal not in f["contratos_citados"]:
                achados.append({
                    "codigo": "G2_CONTRATO_ALHEIO_NO_DOCUMENTO",
                    "diz": (f"o documento cita o contrato {', '.join(alheios)} enquanto o processo "
                            f"discute o {principal}"),
                    "evidencia": f["ref"][:90]})

    # 3) quem assina em fases que não deveriam ser da mesma pessoa (controle × decisão)
    de_controle = {n for f in fs if f["fase"] == "controle" for n in f["assinantes"]}
    de_decisao = {n for f in fs if f["fase"] in ("contratacao", "despesa")
                  for n in f["assinantes"]}
    for nome in sorted(de_controle & de_decisao):
        achados.append({
            "codigo": "G3_MESMA_PESSOA_CONTROLA_E_DECIDE",
            "diz": (f"{nome} assina tanto peça de CONTROLE quanto ato de decisão/despesa — "
                    "o controle prévio perde independência quando quem opina é quem decide"),
            "evidencia": nome})
    return achados


def sintetizar(fs: list[dict], *, lacunas_captura: int = 0, gerar=None) -> dict:
    """Veredito do CONJUNTO. Determinístico sempre; `gerar` (LLM) acrescenta a leitura em prosa."""
    fases = por_fase(fs)
    contr = contradicoes(fs)
    julgados = sum(r["julgados"] for r in fases.values())
    viciados = sum(r["viciados"] for r in fases.values())
    chars = sum(f["chars"] for f in fs)
    linha = [f"{fase}: {r['n_docs']} doc(s)"
             + (f", de {r['de']} a {r['ate']}" if r["de"] else "")
             + (f", {r['viciados']} viciado(s)" if r["viciados"] else "")
             for fase, r in fases.items()]
    leitura = (f"Processo com {len(fs)} documentos e {chars:,} caracteres lidos. "
               f"Esqueleto: {' · '.join(linha)}. "
               f"{julgados} documento(s) com juízo, {viciados} em escala de vício. "
               + (f"{len(contr)} contradição(ões) entre documentos. " if contr else
                  "Nenhuma contradição entre documentos pela leitura do conjunto. ")
               + ("LEITURA PARCIAL: há documento citado nos autos que não foi capturado — o que "
                  "depender dele fica INDISPONÍVEL." if lacunas_captura else
                  "Cobertura: todos os documentos citados foram capturados."))
    saida = {"n_docs": len(fs), "chars": chars, "fases": fases,
             "contradicoes": contr, "julgados": julgados, "viciados": viciados,
             "leitura": leitura, "fonte": "sintese_global (determinística)"}
    if gerar is not None:
        saida["prosa"] = _prosa(saida, gerar)
    return saida


_SYS = (
    "Você é AUDITOR DE CONTROLE EXTERNO (TCE-RJ) escrevendo a leitura de CONJUNTO de um processo "
    "administrativo. Recebe o ESQUELETO do processo (fases, datas, assinantes, juízo por "
    "documento) e as contradições já apuradas — NÃO o texto dos documentos. Escreva 3 a 6 frases "
    "sobre o que o CONJUNTO mostra: a ordem dos atos, quem decidiu, onde a instrução falha. "
    "REGRAS: indício ≠ acusação (presunção de legitimidade); não invente fato, número ou "
    "documento que não esteja no esqueleto; se o esqueleto disser que a leitura é parcial, diga "
    "isso na sua conclusão. Responda em prosa corrida, sem markdown."
)


def _prosa(sintese: dict, gerar) -> str:
    import json
    resumo = {k: sintese[k] for k in ("n_docs", "chars", "fases", "contradicoes",
                                      "julgados", "viciados")}
    try:
        return str(gerar(json.dumps(resumo, ensure_ascii=False, default=str)[:12000], _SYS)).strip()
    except Exception as e:  # noqa: BLE001 — fronteira de LLM: a síntese determinística fica de pé
        return f"(leitura em prosa indisponível: {type(e).__name__})"
