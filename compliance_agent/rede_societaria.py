# -*- coding: utf-8 -*-
"""
Onda 4 — Rede societária: cruzamento de fornecedores por SÓCIO em comum (QSA da Receita via BrasilAPI).

Por que importa: dois fornecedores que **co-ocorrem nos mesmos órgãos** (grafo_cartel) E **compartilham um sócio**
são um indício MUITO mais forte de cartel/laranja/conluio do que a co-ocorrência sozinha. Sócio comum também
revela "empresas-irmãs" disputando a mesma licitação (frustração do caráter competitivo, art. 337-F CP).

Fonte: BrasilAPI (`brasilapi.com.br/api/cnpj`) → campo `qsa` (sócios). Ingestão é por SUBCONJUNTO de alto valor
(top fornecedores + candidatos de cartel) — varrer 73k CNPJs seria inviável/limitado por rate-limit.

Tabela: `socios_fornecedor(cnpj, razao, socio_nome, socio_nome_norm, socio_doc, qualificacao, ingerido_em)`.

CLI:
    python -m compliance_agent.rede_societaria --ingerir-top 300     # ingere QSA dos 300 maiores fornecedores
    python -m compliance_agent.rede_societaria --ingerir 19088605000104 33200056000123
    python -m compliance_agent.rede_societaria --rede 19088605000104   # fornecedores com sócio em comum
    python -m compliance_agent.rede_societaria --cartel 19088605000104  # co-ocorrência + sócio comum (forte)
    python -m compliance_agent.rede_societaria --stats
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sqlite3
import unicodedata
from datetime import datetime

_BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_DB = os.environ.get("JFN_DB", os.path.join(_BASE, "data", "compliance.db"))

_DDL = """
CREATE TABLE IF NOT EXISTS socios_fornecedor (
    cnpj TEXT, razao TEXT, socio_nome TEXT, socio_nome_norm TEXT, socio_doc TEXT,
    qualificacao TEXT, ingerido_em TEXT,
    PRIMARY KEY (cnpj, socio_nome_norm)
)
"""

# tabela leve de endereço por CNPJ (1 linha/empresa) — alimenta o cruzamento sócio×endereço sem
# inchar socios_fornecedor (que é 1 linha/sócio). Idempotente.
_DDL_END = """
CREATE TABLE IF NOT EXISTS endereco_fornecedor (
    cnpj TEXT PRIMARY KEY, razao TEXT, endereco TEXT, endereco_norm TEXT,
    municipio TEXT, uf TEXT, cep TEXT, atualizado_em TEXT
)
"""


def _con():
    c = sqlite3.connect(_DB)
    c.execute(_DDL)
    c.execute(_DDL_END)
    c.execute("CREATE INDEX IF NOT EXISTS ix_socio_norm ON socios_fornecedor(socio_nome_norm)")
    c.execute("CREATE INDEX IF NOT EXISTS ix_socio_cnpj ON socios_fornecedor(cnpj)")
    c.execute("CREATE INDEX IF NOT EXISTS ix_end_norm ON endereco_fornecedor(endereco_norm)")
    return c


def _montar_endereco(raw: dict) -> str:
    """Endereço completo a partir do JSON cru da BrasilAPI (logradouro..CEP)."""
    partes = [raw.get("descricao_tipo_de_logradouro") or "", raw.get("logradouro") or "",
              raw.get("numero") or "", raw.get("complemento") or "", raw.get("bairro") or "",
              raw.get("municipio") or "", raw.get("uf") or "", raw.get("cep") or ""]
    return ", ".join(str(p).strip() for p in partes if str(p).strip())


def _norm_end(s: str) -> str:
    """Canoniza endereço p/ comparar 'mesma sede' (tira acento/pontuação/espaços)."""
    s = (s or "").upper()
    s = "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
    s = re.sub(r"[^A-Z0-9]", "", s)
    return s


def _gravar_endereco(con, cnpj: str, dados: dict, agora: str) -> None:
    """Persiste o endereço da empresa em endereco_fornecedor (best-effort, idempotente)."""
    raw = dados.get("raw") or {}
    end = _montar_endereco(raw)
    if not end:
        return
    con.execute(
        "INSERT OR REPLACE INTO endereco_fornecedor VALUES (?,?,?,?,?,?,?,?)",
        (cnpj, dados.get("razao_social") or dados.get("nome") or "", end, _norm_end(end),
         dados.get("municipio") or raw.get("municipio") or "", dados.get("uf") or raw.get("uf") or "",
         dados.get("cep") or raw.get("cep") or "", agora),
    )


def endereco_de(cnpj: str) -> dict:
    """Endereço armazenado de um CNPJ (ou {} se ainda não ingerido). Não faz rede."""
    cnpj = re.sub(r"\D", "", cnpj or "")
    con = _con()
    try:
        r = con.execute(
            "SELECT cnpj, razao, endereco, endereco_norm, municipio, uf, cep FROM endereco_fornecedor WHERE cnpj=?",
            (cnpj,)).fetchone()
    finally:
        con.close()
    if not r:
        return {}
    return {"cnpj": r[0], "razao": r[1], "endereco": r[2], "endereco_norm": r[3],
            "municipio": r[4], "uf": r[5], "cep": r[6]}


def _norm_nome(s: str) -> str:
    s = (s or "").upper()
    s = "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
    s = re.sub(r"[^A-Z ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def cnpjs_top(limite: int = 300) -> list[str]:
    """Maiores fornecedores por valor pago (seed da ingestão de sócios)."""
    from compliance_agent.duckdb_util import conectar
    con = conectar()
    try:
        rows = con.execute("""
            SELECT favorecido_cpf FROM db.ordens_bancarias
            WHERE valor>0 AND favorecido_cpf IS NOT NULL AND length(favorecido_cpf)=14
            GROUP BY favorecido_cpf ORDER BY SUM(valor) DESC LIMIT ?
        """, [limite]).fetchall()
        return [r[0] for r in rows]
    finally:
        con.close()


async def ingerir(cnpjs: list[str], delay: float = 0.5) -> dict:
    """Busca o QSA (sócios) de cada CNPJ na BrasilAPI e grava em socios_fornecedor. Idempotente."""
    from compliance_agent.collectors.cnpj import buscar_cnpj
    import httpx
    con = _con()
    agora = datetime.now().isoformat(timespec="seconds")
    ok = falha = n_socios = 0
    pendentes = [re.sub(r"\D", "", c) for c in cnpjs if len(re.sub(r"\D", "", c)) == 14]
    # pula quem já tem sócio ingerido
    ja = {r[0] for r in con.execute("SELECT DISTINCT cnpj FROM socios_fornecedor")}
    pendentes = [c for c in pendentes if c not in ja]
    async with httpx.AsyncClient(timeout=15, headers={"User-Agent": "JFN-Compliance/1.0"}) as client:
        for cnpj in pendentes:
            try:
                r = await buscar_cnpj(cnpj, client=client)
                socios = r.get("socios", []) or []
                _gravar_endereco(con, cnpj, r, agora)  # endereço p/ cruzamento sócio×sede
                rows = []
                for s in socios:
                    nome = s.get("nome", "") or ""
                    if not nome:
                        continue
                    rows.append((cnpj, r.get("razao_social") or r.get("nome") or "", nome, _norm_nome(nome),
                                 s.get("cpf_cnpj", "") or "", s.get("qualificacao", "") or "", agora))
                if rows:
                    con.executemany("INSERT OR REPLACE INTO socios_fornecedor VALUES (?,?,?,?,?,?,?)", rows)
                    con.commit()
                    n_socios += len(rows)
                else:
                    # marca CNPJ sem QSA (evita re-buscar) com linha-sentinela
                    con.execute("INSERT OR REPLACE INTO socios_fornecedor VALUES (?,?,?,?,?,?,?)",
                                (cnpj, r.get("razao_social") or "", "", "", "", "(sem QSA público)", agora))
                    con.commit()
                ok += 1
            except Exception:
                falha += 1
            await asyncio.sleep(delay)
    con.close()
    return {"ok": True, "consultados": len(pendentes), "sucesso": ok, "falha": falha, "socios_gravados": n_socios}


def rede_por_socio(cnpj: str) -> dict:
    """Outros fornecedores que compartilham ao menos um sócio (por nome normalizado) com o CNPJ dado."""
    cnpj = re.sub(r"\D", "", cnpj or "")
    con = _con()
    try:
        meus = [r[0] for r in con.execute(
            "SELECT socio_nome_norm FROM socios_fornecedor WHERE cnpj=? AND socio_nome_norm!=''", (cnpj,))]
        if not meus:
            return {"cnpj": cnpj, "socios": [], "relacionados": [], "_nota": "sem QSA ingerido p/ este CNPJ"}
        ph = ",".join("?" * len(meus))
        rel = con.execute(f"""
            SELECT cnpj, MAX(razao) razao, GROUP_CONCAT(DISTINCT socio_nome) socios_comuns
            FROM socios_fornecedor
            WHERE socio_nome_norm IN ({ph}) AND cnpj!=? GROUP BY cnpj
        """, meus + [cnpj]).fetchall()
        nomes = [r[0] for r in con.execute(
            "SELECT DISTINCT socio_nome FROM socios_fornecedor WHERE cnpj=? AND socio_nome!=''", (cnpj,))]
        return {"cnpj": cnpj, "socios": nomes,
                "relacionados": [{"cnpj": c, "razao": rz, "socios_comuns": sc} for c, rz, sc in rel]}
    finally:
        con.close()


def cruzar_cartel(cnpj: str) -> dict:
    """Indício FORTE: fornecedores que (a) co-ocorrem nos mesmos órgãos E (b) compartilham sócio com o alvo."""
    from compliance_agent.grafo_cartel import vizinhanca_cartel
    viz = vizinhanca_cartel(cnpj, limite=50)
    rede = rede_por_socio(cnpj)
    rel_cnpjs = {r["cnpj"] for r in rede.get("relacionados", [])}
    fortes = []
    for v in viz.get("vizinhos", []):
        if v.get("cnpj") in rel_cnpjs:
            comuns = next((r["socios_comuns"] for r in rede["relacionados"] if r["cnpj"] == v["cnpj"]), "")
            fortes.append({**v, "socios_comuns": comuns})
    return {"cnpj": cnpj, "n_orgaos": viz.get("n_orgaos", 0),
            "co_ocorrencia_com_socio_comum": fortes,
            "_nota": ("Co-ocorrência nos mesmos órgãos + sócio em comum = indício forte de cartel/laranja a "
                      "verificar (art. 337-F CP; art. 36 Lei 12.529). Requer QSA ingerido dos dois lados.")}


def stats() -> dict:
    con = _con()
    try:
        n = con.execute("SELECT COUNT(DISTINCT cnpj) FROM socios_fornecedor").fetchone()[0]
        ns = con.execute("SELECT COUNT(*) FROM socios_fornecedor WHERE socio_nome_norm!=''").fetchone()[0]
        comp = con.execute("""SELECT COUNT(*) FROM (
            SELECT socio_nome_norm FROM socios_fornecedor WHERE socio_nome_norm!=''
            GROUP BY socio_nome_norm HAVING COUNT(DISTINCT cnpj)>=2)""").fetchone()[0]
        return {"cnpjs_com_qsa": n, "socios": ns, "socios_compartilhados_por_2+_empresas": comp}
    finally:
        con.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Rede societária — cruzamento por sócio (Onda 4).")
    ap.add_argument("--ingerir-top", type=int, metavar="N", help="ingere QSA dos N maiores fornecedores")
    ap.add_argument("--ingerir", nargs="*", help="ingere QSA de CNPJs específicos")
    ap.add_argument("--rede", type=str, metavar="CNPJ", help="fornecedores com sócio em comum")
    ap.add_argument("--cartel", type=str, metavar="CNPJ", help="co-ocorrência + sócio comum (indício forte)")
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--delay", type=float, default=0.5)
    a = ap.parse_args()
    if a.ingerir_top:
        print(json.dumps(asyncio.run(ingerir(cnpjs_top(a.ingerir_top), a.delay)), ensure_ascii=False, indent=2))
    if a.ingerir:
        print(json.dumps(asyncio.run(ingerir(a.ingerir, a.delay)), ensure_ascii=False, indent=2))
    if a.rede:
        print(json.dumps(rede_por_socio(a.rede), ensure_ascii=False, indent=2, default=str))
    if a.cartel:
        print(json.dumps(cruzar_cartel(a.cartel), ensure_ascii=False, indent=2, default=str))
    if a.stats:
        print(json.dumps(stats(), ensure_ascii=False, indent=2))
