# -*- coding: utf-8 -*-
"""orgao_fonte — o ÓRGÃO (UG do SIAFE) de um processo SEI, de um CNPJ ou de uma nota, só por dado real.

Pedido do dono (19/11/2026): os baldes "Sem órgão identificado na base" e "Dossiês do vault sem órgão mapeado" da
galáxia, e as ~86 notas do vault marcadas `orgao/indeterminado`, se resolvem NA FONTE — nunca por chute:

  1. processo SEI → a UG que emitiu a maioria ESTRITA das OB pagas DAQUELE processo (`ob_orcamentaria_siafe.processo`);
  2. processo SEI → o PREFIXO de 6 dígitos (unidade SEI) → a UG que emitiu a maioria estrita das OB pagas de TODOS
     os processos com esse prefixo, com ≥ `MIN_OB_PREFIXO` OB (o mesmo aprendizado de `tools/sei_busca_credor.
     prefixos_por_ug`, invertido). Prefixo dividido entre UGs sem maioria fica de fora;
  3. CNPJ citado → a UG que mais PAGOU o CNPJ (OB paga no SIAFE, `cruzamentos_intel._ob_paga`).

OB paga = o filtro único da casa (`_ob_paga`: contabilizada, não devolvida, com número). O que não resolve volta com o
MOTIVO medido (nota sem SEI nem CNPJ, prefixo sem UG no índice, CNPJ sem OB no SIAFE, esfera fora do Estado…).

O índice de prefixos custa uma varredura da tabela de OB (~7 s com a VM carregada): fica em
`data/cache/sei_prefixo_ug.json` por `TTL_S`; a galáxia e o marcador do vault leem a cópia.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from collections import Counter, defaultdict
from pathlib import Path

from compliance_agent.cruzamentos_intel import _ob_paga

MIN_OB_PREFIXO = 3
TTL_S = 24 * 3600
_REPO = Path(__file__).resolve().parent.parent
CACHE = Path(os.environ.get("JFN_DATA_DIR") or (_REPO / "data")) / "cache" / "sei_prefixo_ug.json"
_SEI = re.compile(r"SEI-(\d{6})/\d{6}/\d{4}")

MOTIVOS_CASO = {
    "esfera": "esfera fora do Estado — órgão não está no SIAFE estadual",
    "sem_sei_cnpj": "nota sem SEI nem CNPJ completo",
    "sei_sem_ug": "processo SEI com prefixo sem UG no índice e sem OB no SIAFE",
    "cnpj_sem_ob": "CNPJ citado sem OB paga no SIAFE",
    "sei_e_cnpj": "SEI sem UG no índice e CNPJ sem OB paga no SIAFE",
    "ambiguo": "SEI/CNPJ citados apontam UGs diferentes, sem maioria",
}


def _maioria(c: Counter, minimo: int = 1) -> str | None:
    tot = sum(c.values())
    if not c or tot < minimo:
        return None
    ug, n = c.most_common(1)[0]
    return ug if 2 * n > tot else None


def mapa_prefixos(con: sqlite3.Connection, ttl_s: float = TTL_S, cache: Path | None = None) -> dict[str, dict[str, int]]:
    """{prefixo SEI de 6 dígitos: {UG: nº de OB pagas}} — da cópia em disco enquanto tiver menos de `ttl_s`."""
    if con is None:
        raise sqlite3.OperationalError("sem base")
    arq = cache or CACHE
    db = next((r[2] for r in con.execute("PRAGMA database_list") if r[1] == "main"), "") or ""
    try:
        d = json.loads(arq.read_text(encoding="utf-8"))
        if db and d.get("db") == db and time.time() - float(d.get("gerado_ts", 0)) < ttl_s:
            return d["prefixos"]
    except (OSError, ValueError, KeyError, TypeError):
        pass
    pref: dict[str, dict[str, int]] = defaultdict(dict)
    for p, ug, n in con.execute("SELECT substr(processo, 5, 6), ug_emitente, COUNT(*) FROM ob_orcamentaria_siafe "
                                "WHERE processo LIKE 'SEI-______/%' AND " + _ob_paga(con) + " GROUP BY 1, 2"):
        if ug and re.fullmatch(r"\d{6}", p or ""):
            pref[p][str(ug)] = n
    try:
        arq.parent.mkdir(parents=True, exist_ok=True)
        tmp = arq.with_suffix(".tmp")
        if not db:                                         # base em memória (teste): nada em disco
            return dict(pref)
        tmp.write_text(json.dumps({"db": db, "gerado_ts": time.time(), "gerado_em": time.strftime("%Y-%m-%d %H:%M"),
                                   "fonte": "ob_orcamentaria_siafe (OB paga)", "prefixos": pref},
                                  ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        tmp.replace(arq)
    except OSError:
        pass                                               # sem cache em disco: só recalcula na próxima vez
    return dict(pref)


def ug_do_prefixo(numero: str, prefixos: dict) -> str | None:
    m = _SEI.search(numero or "")
    return _maioria(Counter(prefixos.get(m.group(1)) or {}), MIN_OB_PREFIXO) if m else None


def ugs_dos_processos(con: sqlite3.Connection, numeros: list[str]) -> dict[str, Counter]:
    """{SEI-…: Counter(UG → nº de OB pagas do processo)} — só os processos que têm OB."""
    out: dict[str, Counter] = defaultdict(Counter)
    ns = sorted({n for n in numeros if n})
    paga = _ob_paga(con)
    for i in range(0, len(ns), 400):
        lote = ns[i:i + 400]
        for proc, ug, n in con.execute("SELECT processo, ug_emitente, COUNT(*) FROM ob_orcamentaria_siafe WHERE processo IN "
                                       f"({','.join('?' * len(lote))}) AND {paga} GROUP BY 1, 2", lote):
            if ug:
                out[proc][str(ug)] += n
    return dict(out)


def ugs_pagadoras(con: sqlite3.Connection, cnpjs: list[str]) -> dict[str, Counter]:
    """{CNPJ: Counter(UG → R$ pago em OB no SIAFE)}."""
    out: dict[str, Counter] = defaultdict(Counter)
    cs = sorted({c for c in cnpjs if c})
    paga = _ob_paga(con)
    for i in range(0, len(cs), 400):
        lote = cs[i:i + 400]
        for c, ug, v in con.execute("SELECT credor, ug_emitente, SUM(valor) FROM ob_orcamentaria_siafe WHERE credor IN "
                                    f"({','.join('?' * len(lote))}) AND {paga} GROUP BY 1, 2", lote):
            if ug and (v or 0) > 0:
                out[c][str(ug)] += float(v)
    return dict(out)


def esfera_de(esfera: str, tags=(), *textos: str) -> str:
    """Esfera do caso: a declarada; sem ela, "municipal" quando a tag `pcrj` ou a entidade/órgão do frontmatter diz
    Prefeitura/Municipal (nota da Prefeitura não ganha UG do Estado pelo CNPJ que o Estado também pagou), e
    "federal"/"outro-estado" quando o nome é de órgão federal ou de outra UF (fonte única `esfera_orgao`, regra de
    nome: federal antes de estadual; estadual só com marca do RJ). "Municípios do ERJ" (programa estadual) não conta."""
    from compliance_agent import esfera_orgao as eo
    e = str(esfera or "").strip().lower()
    if e:
        return e
    if any(str(t).strip().lower() == "pcrj" for t in tags or ()) or any(eo.RX_MUNICIPAL.search(t or "") for t in textos):
        return "municipal"
    for t in textos:
        c = eo.classificar("", t or "", fatos={})["esfera"] if t else ""
        if c in ("federal", "outro-estado"):
            return c
    return ""


def resolver(seis: list[str], cnpjs: list[str], prefixos: dict, por_processo: dict, por_cnpj: dict,
             esfera: str = "") -> dict:
    """UG de um caso/nota. Ordem: OB do próprio processo → prefixo SEI → quem mais pagou o CNPJ citado.
    Nota de esfera municipal/federal não ganha UG do Estado (o CNPJ pode ter OB estadual sem que o caso seja dela).
    Devolve {ug, via, det} ou {ug: "", motivo: <chave de MOTIVOS_CASO>}."""
    if str(esfera or "").strip().lower() in ("municipal", "federal", "outro-estado"):
        return {"ug": "", "motivo": "esfera"}
    votos = Counter(u for u in (_maioria(por_processo.get(s) or Counter()) for s in seis) if u)
    if votos:
        ug = _maioria(votos)
        if ug:
            return {"ug": ug, "via": "OB do processo",
                    "det": f"{votos[ug]} de {sum(votos.values())} processo(s) SEI com OB paga emitida pela UG {ug}"}
    votos_p = Counter(u for u in (ug_do_prefixo(s, prefixos) for s in seis) if u)
    if votos_p:
        ug = _maioria(votos_p)
        if ug:
            return {"ug": ug, "via": "prefixo SEI",
                    "det": f"{votos_p[ug]} de {sum(votos_p.values())} processo(s) SEI com prefixo da UG {ug} no índice de OB"}
    # CNPJ: só quando UMA UG pagou a maioria estrita do R$ de cada CNPJ E essa UG é a maioria estrita entre os CNPJs
    # citados — fornecedor pago por vários órgãos, ou nota agregada com CNPJs de órgãos diferentes, não decide nada
    votos_c = Counter(u for u in (_maioria(Counter(por_cnpj.get(c) or {})) for c in cnpjs) if u)
    if votos_c:
        ug = _maioria(votos_c)
        if ug:
            return {"ug": ug, "via": "OB do CNPJ",
                    "det": f"{votos_c[ug]} de {sum(votos_c.values())} CNPJ citado(s) pago(s) na maior parte pela UG {ug}"}
    if votos or votos_p or votos_c or any(por_cnpj.get(c) for c in cnpjs):
        return {"ug": "", "motivo": "ambiguo"}
    if not seis and not cnpjs:
        return {"ug": "", "motivo": "sem_sei_cnpj"}
    if seis and cnpjs:
        return {"ug": "", "motivo": "sei_e_cnpj"}
    return {"ug": "", "motivo": "sei_sem_ug" if seis else "cnpj_sem_ob"}


_SEI_NUM = re.compile(r"SEI-\d{6}/\d{6}/\d{4}")
_STEM_SEI = re.compile(r"^(\d{6})_(\d{6})_(\d{4})$")
_CNPJ_FMT = re.compile(r"\b\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\b")


def citados(stem: str, texto: str) -> tuple[list[str], list[str], str]:
    """(SEIs, CNPJs, esfera) de uma nota: SEI no formato SEI-XXXXXX/XXXXXX/AAAA (e o nome do arquivo, nas notas de
    processo `XXXXXX_XXXXXX_AAAA`), CNPJ só completo e formatado (o mesmo critério de `casos_vault`)."""
    seis = set(_SEI_NUM.findall(texto))
    m = _STEM_SEI.match(stem or "")
    if m:
        seis.add(f"SEI-{m[1]}/{m[2]}/{m[3]}")
    cnpjs = {re.sub(r"\D", "", c) for c in _CNPJ_FMT.findall(texto)}
    fm = re.match(r"\A---\n(.*?\n)---\n", texto, re.S)
    fm = fm.group(1) if fm else ""
    campo = {k: v.strip().strip("\"'") for k, v in re.findall(r"^(esfera|entidade|orgao|tags):[ \t]*(.*)$", fm, re.M)}
    tags = [t.strip() for t in campo.get("tags", "").strip("[]").split(",")]
    return sorted(seis), sorted(cnpjs), esfera_de(campo.get("esfera", ""), tags, campo.get("entidade", ""), campo.get("orgao", ""))


def ug_declarada(texto: str) -> str:
    """UG que o AUTOR escreveu na entidade/órgão do frontmatter ("… × INEA (UG 243200)") — a mesma leitura da galáxia."""
    fm = re.match(r"\A---\n(.*?\n)---\n", texto, re.S)
    m = re.search(r"^(?:entidade|orgao):.*?\bUG\s*(\d{6})\b", fm.group(1) if fm else "", re.M)
    return m.group(1) if m else ""


def resolver_notas(notas: dict[str, str], db: Path | None = None) -> dict[str, dict]:
    """{nome do arquivo: resultado de `resolver`} para as notas dadas ({stem: texto}). Abre a base só se alguma nota
    cita SEI ou CNPJ; base ausente → {} (a nota segue como estava)."""
    out = {s: {"ug": u, "via": "UG declarada", "det": "UG escrita na entidade/órgão da nota"}
           for s, u in ((s, ug_declarada(t)) for s, t in notas.items()) if u}
    cit = {s: citados(s, t) for s, t in notas.items() if s not in out}
    seis = sorted({x for a, _, _ in cit.values() for x in a})
    cnpjs = sorted({x for _, b, _ in cit.values() for x in b})
    out.update({s: resolver(a, b, {}, {}, {}, e) for s, (a, b, e) in cit.items() if not a and not b})
    if not seis and not cnpjs:
        return out
    db = db or Path(os.environ.get("JFN_DATA_DIR") or _REPO / "data") / "compliance.db"
    if not db.exists():
        return out
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=30)
    try:
        pref = mapa_prefixos(con) if seis else {}
        proc = ugs_dos_processos(con, seis) if seis else {}
        pago = ugs_pagadoras(con, cnpjs) if cnpjs else {}
    finally:
        con.close()
    for s, (a, b, e) in cit.items():
        out[s] = resolver(a, b, pref, proc, pago, e)
    return out
