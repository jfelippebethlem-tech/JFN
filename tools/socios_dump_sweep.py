#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""socios_dump_sweep — indexa o QSA REAL dos NOSSOS fornecedores a partir do dump de Sócios da Receita
(Dados Abertos CNPJ), VM-safe por STREAMING (lê linha-a-linha do ZIP via `unzip -p`, NUNCA carrega tudo).

POR QUÊ (vs `enriquecer_socios_ob` que usa BrasilAPI por-CNPJ): o dump é a FONTE MAIS COMPLETA e oficial do
QSA, inclui DIRETORES/PRESIDENTES de associações (qualif. 16/10/05/49...) — que aqui NÃO são descartados. A
tabela `socios_fornecedor` (API) continua intacta (rede/grafo já a consomem); esta nova `socios_receita`
é a fonte preferencial do dump e habilita a REDE (pessoas ligando ≥2 fornecedores nossos).

Formato Socios CSV (`;`-delim, latin1, SEM header):
  col1=CNPJ_BÁSICO(8) col2=ident(1=PJ,2=PF,3=estrang) col3=NOME col4=CPF_CNPJ_SÓCIO(PF mascarado ***NNNNNN**)
  col5=QUALIF(cód: 16=Presidente,10=Diretor,05=Administrador,49=Sócio-Adm) col6=data_entrada col11=faixa_etária
LGPD: CPF de PF já vem MASCARADO no dump — mantemos assim, nunca desmascarar.

Uso:
  PYTHONPATH=. .venv/bin/python -m tools.socios_dump_sweep            # indexa todos os Socios*.zip
  PYTHONPATH=. .venv/bin/python -m tools.socios_dump_sweep --rede     # (re)materializa só o cruzamento
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import subprocess
import time
import unicodedata
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_DB = _REPO / "data" / "compliance.db"
_DUMP = _REPO / "data" / "receita_dump"
_RAIZES = _DUMP / "_nossas_raizes.txt"

# códigos de qualificação -> texto (subset relevante; resto vem do Qualificacoes.csv se disponível)
_QUALIF_FALLBACK = {
    "05": "Administrador", "08": "Conselheiro de Administração", "10": "Diretor",
    "16": "Presidente", "49": "Sócio-Administrador", "22": "Sócio", "65": "Titular Pessoa Física",
}


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().upper()
    return " ".join(s.split())


def _carregar_qualif() -> dict[str, str]:
    """Lê Qualificacoes.zip se existir (latin1, `cod;texto`); senão usa fallback."""
    m = dict(_QUALIF_FALLBACK)
    zq = _DUMP / "Qualificacoes.zip"
    if zq.exists():
        try:
            out = subprocess.run(["unzip", "-p", str(zq)], capture_output=True, timeout=30).stdout
            for ln in out.decode("latin1").splitlines():
                p = ln.replace('"', "").split(";")
                if len(p) >= 2 and p[0].strip().isdigit():
                    m[p[0].strip().zfill(2)] = p[1].strip()
        except Exception:
            pass
    return m


def _carregar_raizes() -> set[str]:
    if not _RAIZES.exists():
        raise SystemExit(f"raizes não geradas: {_RAIZES} (rode o passo de extração)")
    return {ln.strip() for ln in _RAIZES.read_text().splitlines() if ln.strip().isdigit()}


_DDL = """
CREATE TABLE IF NOT EXISTS socios_receita (
    cnpj_basico     TEXT NOT NULL,
    ident           TEXT,            -- 1=PJ 2=PF 3=estrangeiro
    nome_socio      TEXT,
    nome_norm       TEXT,
    doc_socio       TEXT,            -- PF mascarado ***NNNNNN** ; PJ = CNPJ completo
    qualificacao_cod TEXT,
    qualificacao_txt TEXT,
    data_entrada    TEXT,
    faixa_etaria    TEXT,
    fonte_mes       TEXT,
    PRIMARY KEY (cnpj_basico, nome_norm, doc_socio, qualificacao_cod)
)
"""
_IDX = [
    "CREATE INDEX IF NOT EXISTS ix_socrec_cnpj ON socios_receita(cnpj_basico)",
    "CREATE INDEX IF NOT EXISTS ix_socrec_nome ON socios_receita(nome_norm)",
    "CREATE INDEX IF NOT EXISTS ix_socrec_doc  ON socios_receita(doc_socio)",
]


def _conectar() -> sqlite3.Connection:
    con = sqlite3.connect(str(_DB), timeout=60)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=60000")
    con.execute("PRAGMA synchronous=NORMAL")
    return con


def _guarda_recursos() -> None:
    try:
        load = float(open("/proc/loadavg").read().split()[0])
        free_mb = int(subprocess.run(["free", "-m"], capture_output=True).stdout.decode()
                      .splitlines()[1].split()[6])
        while load >= 4 or free_mb < 800:
            print(f"[socrec] pausa: load={load:.1f} free={free_mb}MB", flush=True)
            time.sleep(20)
            load = float(open("/proc/loadavg").read().split()[0])
            free_mb = int(subprocess.run(["free", "-m"], capture_output=True).stdout.decode()
                          .splitlines()[1].split()[6])
    except Exception:
        pass


def indexar(mes: str = "2026-05") -> None:
    raizes = _carregar_raizes()
    qualif = _carregar_qualif()
    con = _conectar()
    con.execute(_DDL)
    for ddl in _IDX:
        con.execute(ddl)
    con.commit()

    zips = sorted(_DUMP.glob("Socios*.zip"))
    if not zips:
        raise SystemExit(f"nenhum Socios*.zip em {_DUMP}")
    print(f"[socrec] {len(zips)} zips | {len(raizes)} raízes nossas", flush=True)

    t0 = time.time()
    total_lidas = 0
    total_match = 0
    for zf in zips:
        if not _zip_ok(zf):
            print(f"[socrec] PULA {zf.name} (zip incompleto/inválido — download em curso?)", flush=True)
            continue
        _guarda_recursos()
        lidas, match = _stream_zip(zf, raizes, qualif, con, mes)
        total_lidas += lidas
        total_match += match
        print(f"[socrec] {zf.name}: lidas={lidas:,} match={match:,} "
              f"| acum match={total_match:,} | {time.time()-t0:.0f}s", flush=True)
    con.commit()
    n = con.execute("SELECT COUNT(*) FROM socios_receita").fetchone()[0]
    nf = con.execute("SELECT COUNT(DISTINCT cnpj_basico) FROM socios_receita").fetchone()[0]
    print(f"[socrec] CONCLUÍDO: {total_lidas:,} linhas lidas | {n:,} sócios | "
          f"{nf:,} fornecedores nossos c/ QSA | {time.time()-t0:.0f}s", flush=True)
    con.close()


def _zip_ok(zf: Path) -> bool:
    try:
        return subprocess.run(["unzip", "-l", str(zf)], capture_output=True, timeout=30).returncode == 0
    except Exception:
        return False


def _stream_zip(zf: Path, raizes: set[str], qualif: dict, con: sqlite3.Connection, mes: str):
    """Stream linha-a-linha do ZIP; insere só linhas cujo CNPJ_BÁSICO ∈ raízes nossas."""
    proc = subprocess.Popen(["unzip", "-p", str(zf)], stdout=subprocess.PIPE, bufsize=1 << 20)
    lidas = match = 0
    buf = []
    BATCH = 5000
    sql = ("INSERT OR IGNORE INTO socios_receita(cnpj_basico,ident,nome_socio,nome_norm,doc_socio,"
           "qualificacao_cod,qualificacao_txt,data_entrada,faixa_etaria,fonte_mes) "
           "VALUES (?,?,?,?,?,?,?,?,?,?)")
    try:
        for raw in proc.stdout:
            lidas += 1
            # raiz são os 8 primeiros chars úteis; checa barato antes de decodificar tudo
            # linha começa com  "12345678";...  -> raiz nos chars 1..9
            if raw[:1] != b'"':
                continue
            raiz = raw[1:9].decode("latin1", "ignore")
            if raiz not in raizes:
                continue
            ln = raw.decode("latin1", "ignore").rstrip("\r\n")
            p = [c.strip('"') for c in ln.split(";")]
            if len(p) < 6:
                continue
            cod = (p[4] or "").zfill(2) if p[4] else ""
            buf.append((
                p[0], p[1], p[2], _norm(p[2]), p[3], cod, qualif.get(cod, ""),
                p[5], p[10] if len(p) > 10 else "", mes,
            ))
            match += 1
            if len(buf) >= BATCH:
                con.executemany(sql, buf)
                con.commit()
                buf.clear()
        if buf:
            con.executemany(sql, buf)
            con.commit()
    finally:
        proc.stdout.close()
        proc.wait()
    return lidas, match


def materializar_rede(con: sqlite3.Connection | None = None) -> None:
    """rede_socios_fornecedores: pessoas (nome+doc) que aparecem em ≥2 fornecedores NOSSOS.
    Casa por nome_norm + doc_socio (doc mascarado já desambigua homônimo pelos 6 díg do CPF)."""
    own = con is None
    if con is None:
        con = _conectar()
    # o objeto pode existir como VIEW ou TABLE (estados históricos do DB);
    # DROP do tipo errado é OperationalError no SQLite — tentar ambos
    for _stmt in ("DROP VIEW IF EXISTS rede_socios_fornecedores",
                  "DROP TABLE IF EXISTS rede_socios_fornecedores"):
        try:
            con.execute(_stmt)
        except sqlite3.OperationalError:
            pass
    con.execute("DROP TABLE IF EXISTS _receb_raiz")
    con.execute("DROP TABLE IF EXISTS _pessoa_raiz")
    # total recebido por raiz (das nossas OB) — materializado p/ join eficiente (sem LIKE correlato)
    con.execute("""
        CREATE TEMP TABLE _receb_raiz AS
        SELECT substr(favorecido_cpf,1,8) AS raiz, SUM(valor) AS total
        FROM ordens_bancarias WHERE length(favorecido_cpf)=14
        GROUP BY substr(favorecido_cpf,1,8)
    """)
    con.execute("CREATE INDEX _ix_receb ON _receb_raiz(raiz)")
    # junção pessoa×raiz só para pessoas que ligam ≥2 fornecedores (filtro 1º, barato)
    con.execute("""
        CREATE TEMP TABLE _pessoa_raiz AS
        SELECT s.nome_norm, s.doc_socio, s.cnpj_basico
        FROM socios_receita s
        JOIN (
            SELECT nome_norm, doc_socio
            FROM socios_receita
            WHERE nome_norm <> '' AND doc_socio <> ''
            GROUP BY nome_norm, doc_socio
            HAVING COUNT(DISTINCT cnpj_basico) >= 2
        ) f ON f.nome_norm = s.nome_norm AND f.doc_socio = s.doc_socio
        GROUP BY s.nome_norm, s.doc_socio, s.cnpj_basico
    """)
    # _pessoa_raiz já é 1 linha por (pessoa, raiz distinta) → soma direta do receb sem dupla contagem
    con.execute("""
        CREATE TABLE rede_socios_fornecedores AS
        SELECT
            (SELECT MAX(s.nome_socio) FROM socios_receita s
               WHERE s.nome_norm = pr.nome_norm AND s.doc_socio = pr.doc_socio) AS nome_socio,
            pr.nome_norm,
            pr.doc_socio,
            COUNT(DISTINCT pr.cnpj_basico)        AS n_fornecedores,
            GROUP_CONCAT(DISTINCT pr.cnpj_basico) AS cnpjs_basicos,
            (SELECT GROUP_CONCAT(DISTINCT s.qualificacao_txt) FROM socios_receita s
               WHERE s.nome_norm = pr.nome_norm AND s.doc_socio = pr.doc_socio) AS qualificacoes,
            COALESCE(SUM(r.total), 0)             AS total_recebido
        FROM _pessoa_raiz pr
        LEFT JOIN _receb_raiz r ON r.raiz = pr.cnpj_basico
        GROUP BY pr.nome_norm, pr.doc_socio
    """)
    con.execute("DROP TABLE IF EXISTS _receb_raiz")
    con.execute("DROP TABLE IF EXISTS _pessoa_raiz")
    con.execute("CREATE INDEX IF NOT EXISTS ix_rede_doc ON rede_socios_fornecedores(doc_socio)")
    con.execute("CREATE INDEX IF NOT EXISTS ix_rede_nome ON rede_socios_fornecedores(nome_norm)")
    con.commit()
    n = con.execute("SELECT COUNT(*) FROM rede_socios_fornecedores").fetchone()[0]
    print(f"[rede] rede_socios_fornecedores: {n:,} pessoas ligando ≥2 fornecedores nossos", flush=True)
    if own:
        con.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--rede", action="store_true", help="só (re)materializa o cruzamento")
    ap.add_argument("--mes", default="2026-05")
    args = ap.parse_args()
    os.nice(10)
    if args.rede:
        materializar_rede()
    else:
        indexar(args.mes)
        materializar_rede()
