# -*- coding: utf-8 -*-
"""Ingere as capturas do SEI-PCRJ (VM-2) no acervo do JFN.

A VM-2 varre o SEI da Prefeitura (prefeitura.sei.rio), captura os processos PÚBLICOS
(nº + Unidade + Data) e sincroniza o SQLite via Syncthing para
``~/shared-brain/sei_pcrj.db``. Este ingester fecha o wiring: lê esse banco e popula
``pcrj.db::pcrj_processo`` (tri-estado `disponivel`), tornando as capturas consultáveis
e cruzáveis com os atos do D.O. (``pcrj_doe_materia``). Idempotente (UPSERT por número).

    python -m tools.pcrj_sei_ingest            # ingere
    python -m tools.pcrj_sei_ingest --stats    # só mostra o que há para ingerir
"""
from __future__ import annotations

import argparse
import re
import sqlite3
from pathlib import Path

from compliance_agent.pcrj import db as pcrj_db

ORIGEM = Path.home() / "shared-brain" / "sei_pcrj.db"
_RE_UNIDADE = re.compile(r"Unidade:\s*([^\s|]+)")
_RE_DATA = re.compile(r"Data:\s*(\d{2}/\d{2}/\d{4})")


def _parse(texto: str) -> tuple[str | None, str | None]:
    """texto 'nº<proc> Unidade: X Data: Y' → (orgao, data). None se ausente."""
    u = _RE_UNIDADE.search(texto or "")
    d = _RE_DATA.search(texto or "")
    return (u.group(1) if u else None), (d.group(1) if d else None)


def ingerir(origem: Path | None = None, db_path=None) -> dict:
    origem = Path(origem or ORIGEM)
    if not origem.exists():
        return {"erro": f"origem não encontrada: {origem} (VM-2 já sincronizou?)"}
    pcrj_db.inicializar(db_path)
    con = pcrj_db.conectar(db_path)
    src = sqlite3.connect(f"file:{origem}?mode=ro", uri=True)
    ingeridos = publicos = 0
    try:
        rows = src.execute(
            "SELECT numero, disponivel, texto, capturado_em FROM sei_pcrj_processo").fetchall()
        for numero, disp, texto, em in rows:
            orgao, data = _parse(texto or "")
            con.execute(
                "INSERT INTO pcrj_processo (numero_processo, sistema, interessado, assunto, "
                "orgao, andamento_json, disponivel, coletado_em) VALUES (?,?,?,?,?,?,?,?) "
                "ON CONFLICT(numero_processo) DO UPDATE SET disponivel=excluded.disponivel, "
                "orgao=COALESCE(excluded.orgao, pcrj_processo.orgao), "
                "assunto=COALESCE(excluded.assunto, pcrj_processo.assunto), "
                "coletado_em=excluded.coletado_em",
                (numero, "SEI.RIO", None, (f"Data {data}" if data else None),
                 orgao, None, disp, em))
            ingeridos += 1
            publicos += 1 if disp else 0
        con.commit()
    finally:
        src.close()
        con.close()
    return {"origem": str(origem), "ingeridos": ingeridos, "publicos": publicos}


# SEI (000255.000010/2025-10) ou Processo.rio/SIGA (EIS-PRO-2023/06224): o documento diz de qual é
_RE_PROC_SEI = re.compile(r"\b(\d{6}\.\d{6}/20\d{2}-\d{2}|[A-Z]{2,5}-[A-Z]{3}-20\d{2}/\d{5})\b")
_URL_CONFERIR = ("https://prefeitura.sei.rio/sei/controlador_externo.php?acao=documento_conferir"
                 "&id_orgao_acesso_externo=0&codigo_verificador={v}&codigo_crc={c}")


def processo_do_documento(processo: str | None, texto: str | None, verificador: str) -> str:
    """Nº do processo a que o documento pertence: o que o D.O. deu; senão o 1º nº SEI no
    próprio texto; senão um balde nominal por documento (nunca inventar processo)."""
    if processo:
        return processo
    m = _RE_PROC_SEI.search(texto or "")
    return m.group(1) if m else f"SEI-DOC-{verificador}"


def ingerir_documentos(origem: Path | None = None, db_path=None) -> dict:
    """``sei_pcrj_documento`` (íntegras baixadas pela conferência de autenticidade na VM-2)
    → ``pcrj_processo_doc``. seq = código verificador (único no SEI)."""
    origem = Path(origem or ORIGEM)
    if not origem.exists():
        return {"erro": f"origem não encontrada: {origem}"}
    src = sqlite3.connect(f"file:{origem}?mode=ro", uri=True)
    try:
        if not src.execute("SELECT 1 FROM sqlite_master WHERE name='sei_pcrj_documento'").fetchone():
            return {"documentos": 0, "motivo": "VM-2 ainda não produziu sei_pcrj_documento"}
        rows = src.execute(
            "SELECT verificador, crc, processo, arquivo, texto, assinantes, capturado_em "
            "FROM sei_pcrj_documento WHERE erro IS NULL AND texto IS NOT NULL AND length(texto) > 0").fetchall()
    finally:
        src.close()
    pcrj_db.inicializar(db_path)
    con = pcrj_db.conectar(db_path)
    n = 0
    try:
        for v, c, proc, arq, texto, assin, em in rows:
            numero = processo_do_documento(proc, texto, v)
            titulo = (arq or f"documento {v}") + (f" · assinantes: {assin}" if assin and assin != "[]" else "")
            # o nº do processo pode melhorar entre ingestões (balde → nº real): não deixar a cópia velha
            con.execute("DELETE FROM pcrj_processo_doc WHERE tipo='sei_conferencia' AND seq=? AND numero_processo<>?",
                        (int(v), numero))
            con.execute(
                "INSERT INTO pcrj_processo_doc (numero_processo, seq, tipo, titulo, texto, url, coletado_em) "
                "VALUES (?,?,?,?,?,?,?) ON CONFLICT(numero_processo, seq) DO UPDATE SET "
                "texto=excluded.texto, titulo=excluded.titulo, coletado_em=excluded.coletado_em",
                (numero, int(v), "sei_conferencia", titulo[:400], texto,
                 _URL_CONFERIR.format(v=v, c=c), em))
            n += 1
        con.commit()
    finally:
        con.close()
    return {"documentos": n}


def ingerir_busca(origem: Path | None = None, db_path=None) -> dict:
    """``sei_pcrj_busca`` (busca livre no Solr público do SEI, VM-2) → ``pcrj.db::pcrj_sei_busca``:
    para cada termo (fornecedor/expressão), os processos e documentos que o SEI municipal devolve."""
    origem = Path(origem or ORIGEM)
    if not origem.exists():
        return {"busca": 0, "motivo": f"origem não encontrada: {origem}"}
    src = sqlite3.connect(f"file:{origem}?mode=ro", uri=True)
    try:
        if not src.execute("SELECT 1 FROM sqlite_master WHERE name='sei_pcrj_busca'").fetchone():
            return {"busca": 0, "motivo": "VM-2 ainda não produziu sei_pcrj_busca"}
        rows = src.execute("SELECT termo, prot, processo, titulo, tipo_registro, unidade, data, snippet, capturado_em "
                           "FROM sei_pcrj_busca").fetchall()
    finally:
        src.close()
    pcrj_db.inicializar(db_path)
    con = pcrj_db.conectar(db_path)
    con.executescript("""CREATE TABLE IF NOT EXISTS pcrj_sei_busca (
        termo TEXT NOT NULL, prot TEXT NOT NULL, processo TEXT, titulo TEXT, tipo_registro TEXT, unidade TEXT,
        data TEXT, snippet TEXT, capturado_em TEXT, PRIMARY KEY (termo, prot));
        CREATE INDEX IF NOT EXISTS ix_pcrj_sei_busca_proc ON pcrj_sei_busca(processo);""")
    try:
        con.executemany("INSERT OR REPLACE INTO pcrj_sei_busca VALUES (?,?,?,?,?,?,?,?,?)", rows)
        con.commit()
        total = con.execute("SELECT count(*), count(DISTINCT processo) FROM pcrj_sei_busca").fetchone()
    finally:
        con.close()
    return {"busca": len(rows), "total": total[0], "processos_distintos": total[1]}


def ingerir_enum(origem: Path | None = None, db_path=None) -> dict:
    """``sei_pcrj_enum`` (catálogo dia a dia de TODOS os processos públicos do SEI municipal, VM-2)
    → ``pcrj_processo`` (assunto = tipo do processo, orgao = unidade geradora; disponivel fica como está)."""
    origem = Path(origem or ORIGEM)
    if not origem.exists():
        return {"enum": 0, "motivo": f"origem não encontrada: {origem}"}
    src = sqlite3.connect(f"file:{origem}?mode=ro", uri=True)
    try:
        if not src.execute("SELECT 1 FROM sqlite_master WHERE name='sei_pcrj_enum'").fetchone():
            return {"enum": 0, "motivo": "VM-2 ainda não produziu sei_pcrj_enum"}
        rows = src.execute("SELECT processo, tipo, unidade, data, capturado_em FROM sei_pcrj_enum").fetchall()
    finally:
        src.close()
    pcrj_db.inicializar(db_path)
    con = pcrj_db.conectar(db_path)
    try:
        con.executemany(
            "INSERT INTO pcrj_processo (numero_processo, sistema, interessado, assunto, orgao, andamento_json, "
            "disponivel, coletado_em) VALUES (?,'SEI.RIO',NULL,?,?,NULL,NULL,?) "
            "ON CONFLICT(numero_processo) DO UPDATE SET assunto=COALESCE(pcrj_processo.assunto, excluded.assunto), "
            "orgao=COALESCE(pcrj_processo.orgao, excluded.orgao)",
            [(p, (f"{t} · gerado {d}" if t else (f"gerado {d}" if d else None)), u, em) for p, t, u, d, em in rows])
        con.commit()
        total = con.execute("SELECT count(*) FROM pcrj_processo WHERE sistema='SEI.RIO'").fetchone()[0]
    finally:
        con.close()
    return {"enum": len(rows), "pcrj_processo_sei": total}


def ingerir_arvore(origem: Path | None = None, db_path=None) -> dict:
    """Árvore (documentos), andamentos e assinaturas dos processos capturados na VM-2 → pcrj.db
    (pcrj_sei_arvore / pcrj_sei_andamento / pcrj_sei_assinatura). A assinatura vem por MATRÍCULA —
    o nome é resolvido depois contra a folha (pcrj_folha_pref)."""
    origem = Path(origem or ORIGEM)
    if not origem.exists():
        return {"arvore": 0, "motivo": f"origem não encontrada: {origem}"}
    src = sqlite3.connect(f"file:{origem}?mode=ro", uri=True)
    try:
        if not src.execute("SELECT 1 FROM sqlite_master WHERE name='sei_pcrj_arvore'").fetchone():
            return {"arvore": 0, "motivo": "VM-2 ainda não produziu sei_pcrj_arvore"}
        arv = src.execute("SELECT numero, doc, tipo, data, inclusao, unidade FROM sei_pcrj_arvore").fetchall()
        and_ = src.execute("SELECT numero, quando, unidade, descricao FROM sei_pcrj_andamento WHERE quando <> 'Data/Hora'").fetchall()
        ass = src.execute("SELECT numero, documento, tipo, matricula, quando, unidade FROM sei_pcrj_assinatura").fetchall()
    finally:
        src.close()
    pcrj_db.inicializar(db_path)
    con = pcrj_db.conectar(db_path)
    con.executescript("""
        CREATE TABLE IF NOT EXISTS pcrj_sei_arvore (numero TEXT NOT NULL, doc TEXT NOT NULL, tipo TEXT, data TEXT,
            inclusao TEXT, unidade TEXT, PRIMARY KEY (numero, doc));
        CREATE TABLE IF NOT EXISTS pcrj_sei_andamento (numero TEXT NOT NULL, quando TEXT, unidade TEXT, descricao TEXT,
            PRIMARY KEY (numero, quando, descricao));
        CREATE TABLE IF NOT EXISTS pcrj_sei_assinatura (numero TEXT NOT NULL, documento TEXT NOT NULL, tipo TEXT,
            matricula TEXT NOT NULL, quando TEXT, unidade TEXT, PRIMARY KEY (numero, documento, matricula));
        CREATE INDEX IF NOT EXISTS ix_pcrj_sei_assinatura_mat ON pcrj_sei_assinatura(matricula);""")
    try:
        con.executemany("INSERT OR IGNORE INTO pcrj_sei_arvore VALUES (?,?,?,?,?,?)", arv)
        con.executemany("INSERT OR IGNORE INTO pcrj_sei_andamento VALUES (?,?,?,?)", and_)
        con.executemany("INSERT OR IGNORE INTO pcrj_sei_assinatura VALUES (?,?,?,?,?,?)", ass)
        con.commit()
        tot = con.execute("SELECT (SELECT count(*) FROM pcrj_sei_arvore), (SELECT count(*) FROM pcrj_sei_assinatura), "
                          "(SELECT count(DISTINCT numero) FROM pcrj_sei_arvore)").fetchone()
    finally:
        con.close()
    return {"arvore": len(arv), "andamentos": len(and_), "assinaturas": len(ass),
            "total_arvore": tot[0], "total_assinaturas": tot[1], "processos_com_arvore": tot[2]}


def resolver_assinantes(db_path=None) -> dict:
    """Matrícula do assinante no SEI (8 dígitos com zeros à esquerda) = matrícula da folha municipal
    (pcrj_folha_pref) como inteiro: 3.207 de 3.828 casaram (84%, 15/09/2026). Materializa
    pcrj_sei_assinante (matricula, nome, orgao, sigla_ua, competencia) — quem assina cada documento.
    UMA varredura da folha (12,6 mi linhas) para uma tabela temporária; nunca um SELECT por matrícula."""
    pcrj_db.inicializar(db_path)
    con = pcrj_db.conectar(db_path)
    try:
        if not con.execute("SELECT 1 FROM sqlite_master WHERE name='pcrj_folha_pref'").fetchone():
            return {"assinantes": 0, "motivo": "pcrj_folha_pref ausente"}
        con.executescript("""CREATE TABLE IF NOT EXISTS pcrj_sei_assinante (
            matricula TEXT PRIMARY KEY, matricula_int INTEGER, nome TEXT, orgao TEXT, sigla_ua TEXT, competencia TEXT);
            CREATE TEMP TABLE _mats AS SELECT DISTINCT matricula, CAST(matricula AS INTEGER) AS m
                FROM pcrj_sei_assinatura WHERE matricula GLOB '[0-9]*';
            CREATE INDEX ix__mats_m ON _mats(m);""")
        # incremental: sem matrícula nova, não varre a folha (o scan agrupado custa ~14 min)
        novas = con.execute("SELECT count(*) FROM _mats WHERE matricula NOT IN (SELECT matricula FROM pcrj_sei_assinante)").fetchone()[0]
        if not novas:
            tot = con.execute("SELECT count(*) FROM pcrj_sei_assinante").fetchone()[0]
            return {"assinantes": 0, "total": tot, "matriculas": con.execute("SELECT count(*) FROM _mats").fetchone()[0], "motivo": "nada novo"}
        # 1 scan agrupado da folha (12,6 mi linhas → ~310 mil matrículas, última competência), depois o join
        con.execute("""CREATE TEMP TABLE _f AS
            SELECT matricula, max(competencia) AS competencia, max(nome) AS nome, max(orgao) AS orgao, max(sigla_ua) AS sigla_ua
            FROM pcrj_folha_pref WHERE matricula GLOB '[0-9]*' GROUP BY matricula""")
        con.execute("CREATE INDEX ix__f_m ON _f(CAST(matricula AS INTEGER))")
        cur = con.execute("""INSERT OR REPLACE INTO pcrj_sei_assinante (matricula, matricula_int, nome, orgao, sigla_ua, competencia)
            SELECT x.matricula, x.m, f.nome, f.orgao, f.sigla_ua, f.competencia FROM _mats x
            JOIN _f f ON CAST(f.matricula AS INTEGER) = x.m""")
        con.commit()
        tot = con.execute("SELECT count(*) FROM pcrj_sei_assinante").fetchone()[0]
        n_mats = con.execute("SELECT count(*) FROM _mats").fetchone()[0]
    finally:
        con.close()
    return {"assinantes": cur.rowcount, "total": tot, "matriculas": n_mats}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--db", default=None)
    a = ap.parse_args()
    if a.stats:
        if not ORIGEM.exists():
            print(f"origem ausente: {ORIGEM}")
            return
        c = sqlite3.connect(f"file:{ORIGEM}?mode=ro", uri=True)
        n, pub = c.execute(
            "SELECT count(*), coalesce(sum(disponivel),0) FROM sei_pcrj_processo").fetchone()
        print(f"a ingerir: {n} processos ({pub} públicos) de {ORIGEM}")
        return
    import json
    print(json.dumps(ingerir(db_path=a.db), ensure_ascii=False, indent=2))
    print(json.dumps(ingerir_documentos(db_path=a.db), ensure_ascii=False, indent=2))
    print(json.dumps(ingerir_busca(db_path=a.db), ensure_ascii=False, indent=2))
    print(json.dumps(ingerir_enum(db_path=a.db), ensure_ascii=False, indent=2))
    print(json.dumps(ingerir_arvore(db_path=a.db), ensure_ascii=False, indent=2))
    print(json.dumps(resolver_assinantes(db_path=a.db), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
