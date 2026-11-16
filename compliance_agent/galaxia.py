"""Galáxia dos casos — grafo de todos os dossiês do vault e das ligações entre eles.

Estrelas = casos (`casos_vault.listar`); planetas = CNPJs citados; satélites = processos SEI e sócios do QSA
público (`socios_fornecedor`). Dois casos se ligam quando compartilham CNPJ, processo SEI, sócio ou entidade.
Ligação = indício de relação a conferir, nunca prova. Sem CPF/documento na saída — só o nome do QSA público.
"""
from __future__ import annotations

import re
import sqlite3
from collections import defaultdict
from itertools import combinations

SOCIOS_POR_CNPJ = 4
_SEM_QSA = "(sem QSA público)"


def _dig(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def _socios(con: sqlite3.Connection | None, cnpjs: list[str]) -> tuple[dict, dict]:
    """{cnpj: [nome_norm,...]} e {cnpj: razão} a partir do QSA local; base ausente → vazio (indisponível ≠ 0)."""
    socios, razao = defaultdict(list), {}
    if con is None or not cnpjs:
        return socios, razao
    q = ",".join("?" * len(cnpjs))
    try:
        rows = con.execute(
            f"SELECT cnpj, MAX(razao), socio_nome_norm FROM socios_fornecedor WHERE cnpj IN ({q}) "
            f"GROUP BY cnpj, socio_nome_norm ORDER BY cnpj, socio_nome_norm", cnpjs).fetchall()
    except sqlite3.Error:
        return socios, razao
    for cnpj, rz, nome in rows:
        if rz:
            razao[cnpj] = rz
        if nome and nome != _SEM_QSA and len(socios[cnpj]) < SOCIOS_POR_CNPJ:
            socios[cnpj].append(nome)
    return socios, razao


def montar(casos: list[dict], con: sqlite3.Connection | None = None) -> dict:
    nos, arestas = {}, {}

    def no(i, **kw):
        nos.setdefault(i, {"id": i, **kw})

    def liga(a, b, tipo, peso=1.0):
        k = (a, b, tipo) if a < b else (b, a, tipo)
        if k in arestas:
            arestas[k]["peso"] += peso
        else:
            arestas[k] = {"source": k[0], "target": k[1], "tipo": tipo, "peso": peso}

    todos_cnpj = sorted({_dig(c) for caso in casos for c in caso.get("cnpjs", []) if len(_dig(c)) == 14})
    socios, razao = _socios(con, todos_cnpj)
    pertence = defaultdict(set)                          # chave compartilhável → casos
    for caso in casos:
        cid = f"caso:{caso['slug']}"
        no(cid, tipo="caso", label=caso.get("titulo") or caso["slug"], slug=caso["slug"],
           nivel=caso.get("nivel", 0), nivel_rotulo=caso.get("nivel_rotulo", ""),
           situacao=caso.get("situacao", ""), entidade=caso.get("entidade", ""))
        for c in caso.get("cnpjs", []):
            d = _dig(c)
            if len(d) != 14:
                continue
            nid = f"cnpj:{d}"
            no(nid, tipo="cnpj", label=razao.get(d) or c, cnpj=d)
            liga(cid, nid, "cita_cnpj")
            pertence[nid].add(cid)
            for s in socios.get(d, []):
                sid = f"socio:{s}"
                no(sid, tipo="socio", label=s)
                liga(nid, sid, "socio")
                pertence[sid].add(cid)
        for n in caso.get("sei", []):
            sid = f"sei:{n}"
            no(sid, tipo="sei", label=n)
            liga(cid, sid, "cita_sei")
            pertence[sid].add(cid)
        ent = (caso.get("entidade") or "").strip().lower()
        if ent:
            pertence[f"ent:{ent}"].add(cid)
    ponte = defaultdict(lambda: defaultdict(int))
    for chave, cs in pertence.items():
        for a, b in combinations(sorted(cs), 2):
            ponte[(a, b)][chave.split(":", 1)[0]] += 1
    for (a, b), motivos in ponte.items():
        liga(a, b, "caso_caso", float(sum(motivos.values())))
        arestas[(a, b, "caso_caso")]["motivos"] = dict(motivos)
    grau = defaultdict(int)
    for e in arestas.values():
        grau[e["source"]] += 1
        grau[e["target"]] += 1
    for n in nos.values():
        n["grau"] = grau[n["id"]]
    tipos = defaultdict(int)
    for n in nos.values():
        tipos[n["tipo"]] += 1
    return {"ok": True, "nos": list(nos.values()), "arestas": list(arestas.values()),
            "resumo": {"casos": tipos["caso"], "cnpjs": tipos["cnpj"], "socios": tipos["socio"],
                       "processos_sei": tipos["sei"], "arestas": len(arestas),
                       "pontes_entre_casos": sum(1 for e in arestas.values() if e["tipo"] == "caso_caso")},
            "aviso": "Ligação = indício de relação a conferir, nunca prova."}


def galaxia() -> dict:
    from compliance_agent.casos_vault import listar
    from compliance_agent.database.models import _resolver_db
    r = listar()
    if not r.get("ok"):
        return r
    try:
        con = sqlite3.connect(f"file:{_resolver_db()}?mode=ro", uri=True, timeout=10)
    except sqlite3.Error:
        con = None
    try:
        return montar(r["casos"], con)
    finally:
        if con is not None:
            con.close()
