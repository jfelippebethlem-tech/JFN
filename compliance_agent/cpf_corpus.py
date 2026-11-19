# -*- coding: utf-8 -*-
"""Corpus de CPF COMPLETO de fonte pública legítima — camada 1 da resolução de CPF mascarado.

Pedido do dono (19/11/2026): "arranjar cpf ou descobrir homônimos ... pode ser por alguns dígitos do cpf".
A camada 1 (`resolucao_cpf.resolver_multi`) casa (nome + 6 dígitos do meio do QSA) contra CPFs completos
que a casa JÁ tem por fonte legítima. Até aqui eram três corpora: favorecidos PF das OB, doadores do TSE
(`doacoes_eleitorais`, só RJ e incompleto: 2016 ausente, 2020 parado em 72.000 linhas exatas) e `sei_cpf`.
Os dados abertos do TSE trazem muito mais, e todos PÚBLICOS por lei (Lei 9.504/97, art. 11 e 28; Res.
TSE 23.607/2019): o CPF de todo CANDIDATO do Brasil (2016–2022 e 2026 — em 2024 o TSE deixou de publicá-lo),
de todo DOADOR, doador originário e FORNECEDOR pessoa física das campanhas do RJ.

Esta tabela (`cpf_corpus`) guarda só pares (CPF, nome normalizado, fonte, ano, papel). Regras:

* CPF com dígito verificador inválido, sequência repetida ou máscara → descartado (lixo de digitação).
* Nome = o da Receita quando o TSE o traz (`NM_DOADOR_RFB`), senão o declarado.
* 2024: o arquivo de candidatos não traz CPF, mas traz o TÍTULO de eleitor; o CPF de 2024 vem do MESMO título
  com o MESMO nome em outro ano (ponte por documento, nunca por nome) — `ponte_titulo`.
* LGPD (art. 7º, II/III e 23 — controle externo): CPF completo é de uso INTERNO, só neste banco; nada aqui
  imprime, loga ou devolve CPF — só contagens. No produto o CPF sai mascarado.
"""
from __future__ import annotations

import re
import sqlite3
from collections.abc import Iterable
from pathlib import Path

from compliance_agent.resolucao_cpf import _digitos, _dv_cpf, _norm

_DB = Path("data") / "compliance.db"

DDL = (
    "CREATE TABLE IF NOT EXISTS cpf_corpus ("
    " cpf TEXT NOT NULL, nome_norm TEXT NOT NULL, middle6 TEXT NOT NULL,"
    " fonte TEXT NOT NULL, ano INTEGER NOT NULL DEFAULT 0, papel TEXT NOT NULL DEFAULT '',"
    " PRIMARY KEY (cpf, nome_norm, fonte, ano, papel)) WITHOUT ROWID",
    "CREATE INDEX IF NOT EXISTS ix_cpf_corpus_nome_m6 ON cpf_corpus(nome_norm, middle6)",
)

# (coluna do CPF, colunas de nome em ordem de preferência, papel) — layout 2018+ e layout 2016
MAPAS = (
    ("NR_CPF_CANDIDATO", ("NM_CANDIDATO",), "candidato"),
    ("NR_CPF_CNPJ_DOADOR", ("NM_DOADOR_RFB", "NM_DOADOR"), "doador"),
    ("NR_CPF_CNPJ_DOADOR_ORIGINARIO", ("NM_DOADOR_ORIGINARIO_RFB", "NM_DOADOR_ORIGINARIO"), "doador_originario"),
    ("NR_CPF_CNPJ_FORNECEDOR", ("NM_FORNECEDOR_RFB", "NM_FORNECEDOR"), "fornecedor"),
    ("CPF do candidato", ("Nome candidato",), "candidato"),
    ("CPF/CNPJ do doador", ("Nome do doador (Receita Federal)", "Nome do doador"), "doador"),
    ("CPF/CNPJ do doador originário", ("Nome do doador originário (Receita Federal)", "Nome do doador originário"),
     "doador_originario"),
    ("CPF/CNPJ do fornecedor", ("Nome do fornecedor (Receita Federal)", "Nome do fornecedor"), "fornecedor"),
)
_NULOS = {"", "#NULO", "#NULO#", "#NE", "#NE#", "NULO"}


def cpf_valido(s) -> str:
    """CPF de 11 dígitos com DV correto e não repetido → os 11 dígitos; qualquer outra coisa → ''."""
    raw = str(s or "").strip()
    if "*" in raw or "X" in raw.upper():   # máscara (QSA/folha) não é CPF completo
        return ""
    d = _digitos(raw)
    if len(d) != 11 or d == d[0] * 11:
        return ""
    return d if _dv_cpf(d[:9]) == d[9:] else ""


def _nome(row: dict, cols: tuple[str, ...]) -> str:
    for c in cols:
        v = (row.get(c) or "").strip()
        if v.upper() not in _NULOS:
            n = _norm(v)
            if len(n) >= 6:
                return n
    return ""


def pares_de_linhas(linhas: Iterable[dict]) -> Iterable[tuple[str, str, str]]:
    """Linhas de CSV do TSE (dict por cabeçalho) → (cpf, nome_norm, papel) de cada coluna de CPF reconhecida."""
    mapas = None
    for row in linhas:
        if mapas is None:
            mapas = [m for m in MAPAS if m[0] in row]
        for col_cpf, cols_nome, papel in mapas:
            cpf = cpf_valido(row.get(col_cpf))
            if not cpf:
                continue
            nome = _nome(row, cols_nome)
            if nome:
                yield cpf, nome, papel


def garantir_tabela(con: sqlite3.Connection) -> None:
    for ddl in DDL:
        con.execute(ddl)


def gravar(con: sqlite3.Connection, pares: Iterable[tuple[str, str, str]], fonte: str, ano: int,
           lote: int = 20000) -> int:
    """Grava pares no corpus (idempotente: PK). Devolve quantos pares novos entraram."""
    garantir_tabela(con)
    antes = con.total_changes
    buf: list[tuple] = []
    for cpf, nome, papel in pares:
        buf.append((cpf, nome, cpf[3:9], fonte, int(ano), papel))
        if len(buf) >= lote:
            con.executemany("INSERT OR IGNORE INTO cpf_corpus VALUES (?,?,?,?,?,?)", buf)
            buf.clear()
    if buf:
        con.executemany("INSERT OR IGNORE INTO cpf_corpus VALUES (?,?,?,?,?,?)", buf)
    con.commit()
    return con.total_changes - antes


def ponte_titulo(linhas_sem_cpf: Iterable[dict], titulo_cpf: dict[str, set[tuple[str, str]]],
                 col_titulo: str = "NR_TITULO_ELEITORAL_CANDIDATO",
                 col_nome: str = "NM_CANDIDATO") -> Iterable[tuple[str, str, str]]:
    """Candidatos de um ano SEM CPF (2024) → CPF pelo MESMO título de eleitor em outro ano, exigindo também o
    MESMO nome. Título com mais de um CPF conhecido (erro de base) ou nome divergente → não liga (nunca chute)."""
    for row in linhas_sem_cpf:
        tit = _digitos(row.get(col_titulo))
        if len(tit) < 10 or set(tit) == {"0"}:
            continue
        nome = _norm(row.get(col_nome) or "")
        conhecidos = titulo_cpf.get(tit) or set()
        cpfs = {c for c, n in conhecidos}
        if len(cpfs) == 1 and nome and any(n == nome for _, n in conhecidos):
            yield next(iter(cpfs)), nome, "candidato_por_titulo"


def indexar_titulos(linhas: Iterable[dict], destino: dict[str, set[tuple[str, str]]],
                    col_titulo: str = "NR_TITULO_ELEITORAL_CANDIDATO", col_cpf: str = "NR_CPF_CANDIDATO",
                    col_nome: str = "NM_CANDIDATO") -> None:
    """Acumula {título → {(cpf, nome_norm)}} dos anos que publicam CPF (alimenta `ponte_titulo`)."""
    for row in linhas:
        tit = _digitos(row.get(col_titulo))
        cpf = cpf_valido(row.get(col_cpf))
        if len(tit) >= 10 and cpf:
            destino.setdefault(tit, set()).add((cpf, _norm(row.get(col_nome) or "")))


def carregar_indice(db_path: str | Path | None = None, fontes: Iterable[str] | None = None) -> dict:
    """Índice {(nome_norm, middle6) → set(cpf)} do corpus — mesmo formato de `resolucao_cpf.carregar_indice_*`,
    para `resolver_multi(corpus_idx=...)`. Tabela ausente → {} (honesto: sem corpus, nada resolve)."""
    idx: dict = {}
    p = Path(db_path or _DB)
    if not p.exists():
        return idx
    con = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=60)
    try:
        sql = "SELECT DISTINCT nome_norm, middle6, cpf FROM cpf_corpus"
        args: tuple = ()
        if fontes:
            fs = list(fontes)
            sql += f" WHERE fonte IN ({','.join('?' * len(fs))})"
            args = tuple(fs)
        for nome, m6, cpf in con.execute(sql, args):
            idx.setdefault((nome, m6), set()).add(cpf)
    except sqlite3.OperationalError as e:
        if "no such table" not in str(e):
            raise
    finally:
        con.close()
    return idx


def medir(con: sqlite3.Connection) -> dict:
    """Só contagens (nunca CPF): pares e CPFs distintos por fonte/ano/papel."""
    try:
        linhas = con.execute("SELECT fonte, ano, papel, COUNT(*), COUNT(DISTINCT cpf) FROM cpf_corpus "
                             "GROUP BY 1,2,3 ORDER BY 1,2,3").fetchall()
        total = con.execute("SELECT COUNT(*), COUNT(DISTINCT cpf) FROM cpf_corpus").fetchone()
    except sqlite3.OperationalError:
        return {"pares": 0, "cpfs": 0, "por_fonte": []}
    return {"pares": total[0], "cpfs": total[1],
            "por_fonte": [{"fonte": f, "ano": a, "papel": p, "pares": n, "cpfs": c} for f, a, p, n, c in linhas]}


_RX_CPF_LOG = re.compile(r"(?<!\d)\d{11}(?!\d)|\d{3}\.\d{3}\.\d{3}-\d{2}")


def sem_cpf(texto: str) -> str:
    """Rede de segurança para qualquer linha que vá a log/tela: CPF completo vira máscara da Receita."""
    def _m(m):
        d = _digitos(m.group(0))
        return f"***.{d[3:6]}.{d[6:9]}-**"
    return _RX_CPF_LOG.sub(_m, str(texto))
