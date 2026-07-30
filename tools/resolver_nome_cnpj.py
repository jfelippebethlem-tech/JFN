#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""resolver_nome_cnpj — razão social → CNPJ pelo catálogo NACIONAL da Receita.

O BLOQUEIO QUE ISTO ATACA. A API de dados abertos do TCE-RJ publica 82.941 perdedores de certame
municipal identificados por **NOME**, sem CNPJ. Sem CNPJ não há quadro societário, e sem QSA o E.3.2
(cruzamento vencedor × perdedoras) fica de fora — que é exatamente o eixo que o volume de coleta
existia para alimentar.

POR QUE NÃO É CASAMENTO APROXIMADO. A primeira medição foi contra os catálogos que a casa já tinha
(`empresas_min`, `endereco_fornecedor`, `socios_fornecedor` — 75.891 nomes normalizados) e deu
**13,9%** de acerto, com ambiguidade de 0,3%. O diagnóstico que esse par de números dá é claro:
quando o nome está no catálogo, ele resolve limpo; o problema é que **86% dos licitantes municipais
não estão no catálogo** — são empresas do interior que nunca venderam ao Estado. Não é caso de
biblioteca de record linkage: é caso de catálogo maior. O dump `Empresas*.zip` da Receita (1,3 GB,
todas as empresas do país) está em disco desde sempre.

COMO, sem estourar a VM. Mesma técnica do `socios_dump_sweep`: `unzip -p` num pipe, uma passada
linha a linha, e só as linhas cujo nome normalizado está no conjunto-alvo entram na memória. O
conjunto-alvo tem dezenas de milhares de nomes; o dump tem dezenas de milhões de linhas e nenhuma
delas é materializada.

A NORMALIZAÇÃO E O QUE ELA CUSTA. Tira acento, pontuação e os sufixos societários (LTDA, ME, EPP,
EIRELI, S/A) — sem isso "ALFA COMERCIO LTDA" e "ALFA COMERCIO LTDA." seriam empresas diferentes. Em
troca, ela **aumenta a colisão**: num catálogo nacional há muitas razões sociais idênticas em
municípios diferentes, e a maioria absoluta são MEIs com nome de pessoa. Por isso cada resolução
grava `n_candidatos`: nome que casa com mais de um CNPJ **não é resolvido** — vira ambíguo
declarado, nunca um chute com cara de fato.

Uso:
  PYTHONPATH=. .venv/bin/python -m tools.resolver_nome_cnpj --de tcerj
  PYTHONPATH=. .venv/bin/python -m tools.resolver_nome_cnpj --de tcerj --relatorio
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import subprocess
import sys
import unicodedata
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

_DUMP = _REPO / "data" / "receita_dump"
_DB = _REPO / "data" / "compliance.db"

DDL = """
CREATE TABLE IF NOT EXISTS nome_cnpj_resolvido (
  nome_norm     TEXT PRIMARY KEY,
  nome_original TEXT,
  cnpj_basico   TEXT,          -- NULL quando ambíguo: nome que casa com mais de uma empresa
  razao_social  TEXT,
  n_candidatos  INTEGER NOT NULL,
  origem        TEXT NOT NULL,
  resolvido_em  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_nome_cnpj_basico ON nome_cnpj_resolvido (cnpj_basico);
"""

# Sufixos societários e conectivos: sem removê-los, "ALFA LTDA" e "ALFA LTDA." seriam empresas
# diferentes. Removê-los aumenta a colisão, e é por isso que `n_candidatos` é gravado sempre.
_RE_SUFIXO = re.compile(
    r"\b(LTDA|ME|EPP|EIRELI|S A|SA|S S|SS|CIA|COMPANHIA|SOCIEDADE|EMPRESA|"
    r"DE|DA|DO|DOS|DAS|E|EM|COM)\b")
_RE_NAO_ALFA = re.compile(r"[^A-Z0-9 ]")


def normalizar(s: str) -> str:
    """Forma canônica do nome de empresa para comparação."""
    s = unicodedata.normalize("NFKD", (s or "").upper()).encode("ascii", "ignore").decode()
    s = _RE_NAO_ALFA.sub(" ", s)
    s = _RE_SUFIXO.sub(" ", s)
    return " ".join(s.split())


def _alvos_tcerj(con: sqlite3.Connection) -> dict[str, str]:
    """`{nome_normalizado: um_nome_original}` dos licitantes municipais ainda não resolvidos."""
    try:
        linhas = con.execute(
            "SELECT DISTINCT participante FROM tcerj_licitante "
            "WHERE COALESCE(participante,'') <> ''").fetchall()
    except sqlite3.OperationalError:
        return {}
    ja = {r[0] for r in con.execute("SELECT nome_norm FROM nome_cnpj_resolvido")} \
        if _tem_tabela(con, "nome_cnpj_resolvido") else set()
    out: dict[str, str] = {}
    for (p,) in linhas:
        n = normalizar(p)
        if n and n not in ja:
            out.setdefault(n, p)
    return out


def _tem_tabela(con: sqlite3.Connection, nome: str) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (nome,)).fetchone())


def varrer_dump(alvos: dict[str, str]) -> dict[str, list[tuple[str, str]]]:
    """Uma passada pelos `Empresas*.zip`, guardando só o que casa com o conjunto-alvo.

    Devolve `{nome_norm: [(cnpj_basico, razao_social), ...]}`. A lista tem mais de um item quando o
    nome existe em mais de uma empresa — e é essa contagem que impede o chute.
    """
    achados: dict[str, list[tuple[str, str]]] = {}
    zips = sorted(_DUMP.glob("Empresas*.zip"))
    if not zips:
        return achados
    for zf in zips:
        proc = subprocess.Popen(["unzip", "-p", str(zf)], stdout=subprocess.PIPE, bufsize=1 << 20)
        try:
            for raw in proc.stdout:
                # layout: "cnpj_basico";"razao_social";"natureza";"qualif";"capital";"porte";"ente"
                if raw[:1] != b'"':
                    continue
                partes = raw.decode("latin1", "ignore").rstrip("\r\n").split('";"')
                if len(partes) < 2:
                    continue
                razao = partes[1]
                n = normalizar(razao)
                if n in alvos:
                    achados.setdefault(n, []).append((partes[0].lstrip('"'), razao))
        finally:
            proc.stdout.close()
            proc.wait()
        print(f"[resolver] {zf.name}: {len(achados)} nome(s) do alvo já vistos", flush=True)
    return achados


def gravar(con: sqlite3.Connection, alvos: dict[str, str],
           achados: dict[str, list[tuple[str, str]]], *, origem: str) -> dict:
    """Grava resolvido e ambíguo. Ambíguo entra com `cnpj_basico` NULO — declarado, não descartado."""
    from datetime import datetime

    con.executescript(DDL)
    agora = datetime.now().isoformat(timespec="seconds")
    n_res = n_amb = n_nao = 0
    linhas = []
    for norm, original in alvos.items():
        cands = achados.get(norm, [])
        unicos = {c for c, _ in cands}
        if len(unicos) == 1:
            cnpj, razao = cands[0]
            n_res += 1
        elif len(unicos) > 1:
            cnpj, razao = None, cands[0][1]
            n_amb += 1
        else:
            cnpj, razao = None, None
            n_nao += 1
        linhas.append((norm, original, cnpj, razao, len(unicos), origem, agora))
    con.executemany(
        "INSERT OR REPLACE INTO nome_cnpj_resolvido VALUES (?,?,?,?,?,?,?)", linhas)
    con.commit()
    return {"alvos": len(alvos), "resolvidos": n_res, "ambiguos": n_amb, "nao_encontrados": n_nao,
            "pct_resolvido": round(100.0 * n_res / len(alvos), 1) if alvos else 0.0}


def relatorio(con: sqlite3.Connection) -> dict:
    """Estado da resolução — o denominador de qualquer cruzamento que dependa dela."""
    if not _tem_tabela(con, "nome_cnpj_resolvido"):
        return {"ok": False, "motivo": "nenhuma resolução gravada ainda"}
    tot = con.execute("SELECT COUNT(*) FROM nome_cnpj_resolvido").fetchone()[0]
    res = con.execute(
        "SELECT COUNT(*) FROM nome_cnpj_resolvido WHERE cnpj_basico IS NOT NULL").fetchone()[0]
    amb = con.execute(
        "SELECT COUNT(*) FROM nome_cnpj_resolvido WHERE cnpj_basico IS NULL "
        "AND n_candidatos > 1").fetchone()[0]
    nao = con.execute(
        "SELECT COUNT(*) FROM nome_cnpj_resolvido WHERE n_candidatos = 0").fetchone()[0]
    return {
        "ok": True, "nomes": tot, "resolvidos": res, "ambiguos": amb, "nao_encontrados": nao,
        "pct_resolvido": round(100.0 * res / tot, 1) if tot else 0.0,
        "nota": ("Nome que casa com mais de uma empresa fica com `cnpj_basico` NULO — ambíguo "
                 "declarado, nunca um chute. Nome não encontrado no catálogo nacional não é empresa "
                 "inexistente: pode ser grafia divergente do registro, e a resolução por semelhança "
                 "segue pendente."),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--de", default="tcerj", choices=("tcerj",), help="fonte dos nomes a resolver")
    ap.add_argument("--relatorio", action="store_true", help="só mostra o estado e sai")
    a = ap.parse_args(argv)

    con = sqlite3.connect(str(_DB), timeout=60)
    con.execute("PRAGMA busy_timeout=60000")
    try:
        con.executescript(DDL)
        if a.relatorio:
            print(relatorio(con))
            return 0
        alvos = _alvos_tcerj(con)
        print(f"[resolver] {len(alvos)} nome(s) a resolver contra o catálogo nacional", flush=True)
        if not alvos:
            print(relatorio(con))
            return 0
        achados = varrer_dump(alvos)
        print("[resolver]", gravar(con, alvos, achados, origem=f"dump-empresas/{a.de}"), flush=True)
        print("[resolver]", relatorio(con), flush=True)
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
