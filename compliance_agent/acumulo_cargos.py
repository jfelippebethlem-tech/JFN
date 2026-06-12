# -*- coding: utf-8 -*-
"""Acúmulo de cargos — servidor da folha da ALERJ que TAMBÉM está na folha do Estado (e vice-versa).

Pedido do dono: cruzar os funcionários de gabinete dos deputados (folha ALERJ, `alerj_folha`) com os nomeados no
governo do Estado (`registros_folha`, 257k) — nos dois sentidos (quem foi do Estado→ALERJ ou ALERJ→Estado; a
`competencia` indica direção/simultaneidade). Pessoa nas DUAS folhas = **indício de acúmulo de cargos** (CF art.
37, XVI/XVII — vedação salvo exceções; acúmulo remunerado simultâneo é o alvo).

Cruzamento por NOME normalizado (a folha ALERJ não traz CPF; `registros_folha` traz CPF mascarado + nome). Honesto:
homônimo é possível → é **indício** (corroborar por CPF/data), nunca prova. Disponível a QUALQUER MOMENTO (consulta).
"""
from __future__ import annotations

import re
import sqlite3
import unicodedata
from pathlib import Path

_DB = Path("data") / "compliance.db"


def _norm(s: str) -> str:
    s = (s or "").upper().strip()
    s = "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", s)


def _con(db_path, ro=True):
    p = Path(db_path or _DB)
    if ro:
        return sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    c = sqlite3.connect(str(p), timeout=30)
    c.execute("PRAGMA busy_timeout=30000")
    return c


_DDL = """CREATE TABLE IF NOT EXISTS alerj_folha (
    nome TEXT, nome_norm TEXT, cargo TEXT, mes_ano TEXT, ingerido_em TEXT,
    PRIMARY KEY (nome_norm, mes_ano))"""


def ingerir_folha(itens: list[dict], mes_ano: str, db_path=None) -> int:
    """Grava os servidores da folha ALERJ (idempotente por nome_norm+mes_ano)."""
    from datetime import datetime
    con = _con(db_path, ro=False)
    try:
        con.execute(_DDL)
        con.execute("CREATE INDEX IF NOT EXISTS ix_alerj_folha_norm ON alerj_folha(nome_norm)")
        ts = datetime.now().isoformat(timespec="seconds")
        n = 0
        for it in itens:
            nn = _norm(it.get("nome", ""))
            if len(nn.split()) < 2:
                continue
            con.execute("INSERT OR REPLACE INTO alerj_folha (nome,nome_norm,cargo,mes_ano,ingerido_em) VALUES (?,?,?,?,?)",
                        (it.get("nome"), nn, it.get("cargo"), mes_ano, ts))
            n += 1
        con.commit()
        return n
    finally:
        con.close()


def cruzar(db_path=None, limite: int = 200) -> dict:
    """Pessoas na folha da ALERJ **e** na do Estado (registros_folha) — indício de acúmulo. Por NOME normalizado."""
    try:
        con = _con(db_path)
        try:
            # índice de nomes do Estado (normalizado em SQL via não temos — normalizamos em Python sobre DISTINCT)
            estado = {}
            for nome, orgao, cargo, comp, rem in con.execute(
                    "SELECT nome, orgao_nome, cargo, competencia, remuneracao_bruta FROM registros_folha "
                    "WHERE nome IS NOT NULL AND nome<>''"):
                nn = _norm(nome)
                # guarda o registro de MAIOR remuneração por pessoa (mais relevante)
                if nn not in estado or (rem or 0) > (estado[nn].get("rem") or 0):
                    estado[nn] = {"orgao": orgao, "cargo": cargo, "competencia": comp, "rem": rem or 0}
            achados = []
            for nome, nome_norm, cargo_alerj, mes in con.execute(
                    "SELECT nome, nome_norm, cargo, mes_ano FROM alerj_folha"):
                e = estado.get(nome_norm)
                if not e:
                    continue
                achados.append({"nome": nome, "cargo_alerj": cargo_alerj, "mes_alerj": mes,
                                "orgao_estado": e["orgao"], "cargo_estado": e["cargo"],
                                "competencia_estado": e["competencia"], "remuneracao_estado": e["rem"]})
            achados.sort(key=lambda a: -(a["remuneracao_estado"] or 0))
            n_alerj = con.execute("SELECT COUNT(DISTINCT nome_norm) FROM alerj_folha").fetchone()[0]
            return {"ok": True, "n_alerj": n_alerj, "n_acumulo": len(achados),
                    "achados": achados[:limite], "leitura": _leitura(achados, n_alerj)}
        finally:
            con.close()
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "_nota": f"INDISPONÍVEL: {str(exc)[:160]}"}


def _leitura(achados: list, n_alerj: int) -> str:
    if not n_alerj:
        return "Folha da ALERJ ainda não ingerida (INDISPONÍVEL — rodar o coletor `alerj_transparencia`)."
    if not achados:
        return (f"Dos **{n_alerj}** servidores da ALERJ, **nenhum** consta também na folha do Estado "
                "(`registros_folha`) — acúmulo **AFASTADO** para os cobertos (a base do Estado pode estar parcial).")
    return (f"**Indício de acúmulo de cargos:** **{len(achados)}** servidor(es) da folha da ALERJ constam **também** "
            f"na folha do Estado (de {n_alerj} ALERJ verificados). Estar nas duas folhas é indício (CF art. 37, "
            "XVI/XVII) — corroborar por **CPF e competência** (mesmo período = acúmulo simultâneo; homônimo é possível). "
            "Nome é dado público; CPF do Estado vem mascarado (LGPD).")


if __name__ == "__main__":  # pragma: no cover
    r = cruzar()
    print(r.get("leitura"))
    for a in (r.get("achados") or [])[:20]:
        print(f"  {a['nome'][:32]:32} | ALERJ: {a['cargo_alerj'][:20]:20} | Estado: {a['orgao_estado']} / {a['cargo_estado']} (R$ {a['remuneracao_estado']:,.0f})")
