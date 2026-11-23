# -*- coding: utf-8 -*-
"""Plataforma de evidências — Fase 1 (fundação). Plano: docs/PLANO-PLATAFORMA-EVIDENCIAS.md.

Estado canônico em `data/evidencias.db` (SQLite WAL; SQL portável para PostgreSQL se um dia precisar):
  processos   um por processo SEI
  arvores     sha256 da lista ORDENADA dos ids da árvore, por captura (árvore igual ⇒ nada novo para baixar)
  documentos  identidade ESTÁVEL: (processo, doc_id) — doc_id = "sei:<número SEI do documento>" (99,2% dos
              518.756 documentos têm o número no título, medido em 23/11/2026) ou "pos:<i>" sem ele; número
              repetido no mesmo processo vira "sei:N#2" (2.576 casos) — nunca some
  versoes     sha256 do conteúdo por documento; conteúdo novo = versão nova, a antiga FICA (nada sobrescreve)
  jobs        fila com chave única (idempotência), reserva com prazo e ficha de posse crescente: o trabalhador
              cujo prazo venceu é recusado ao concluir (não grava resultado velho por cima do novo)

Uso:
    python -m compliance_agent.evidencias importar [--limite N]     # carga a partir de data/sei_arquivo/*/manifest.json
    python -m compliance_agent.evidencias resumo
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
DB = RAIZ / "data" / "evidencias.db"
ARQUIVO = RAIZ / "data" / "sei_arquivo"

_DDL = """
CREATE TABLE IF NOT EXISTS processos(processo TEXT PRIMARY KEY, tag TEXT NOT NULL, primeira_em TEXT NOT NULL,
  ultima_em TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS arvores(processo TEXT NOT NULL, hash TEXT NOT NULL, n_docs INTEGER NOT NULL,
  vista_em TEXT NOT NULL, origem TEXT, PRIMARY KEY(processo, hash));
CREATE TABLE IF NOT EXISTS documentos(processo TEXT NOT NULL, doc_id TEXT NOT NULL, posicao INTEGER, titulo TEXT,
  tipo TEXT, fase TEXT, visto_em TEXT NOT NULL, PRIMARY KEY(processo, doc_id));
CREATE TABLE IF NOT EXISTS versoes(processo TEXT NOT NULL, doc_id TEXT NOT NULL, sha256 TEXT NOT NULL,
  chars INTEGER NOT NULL, origem TEXT NOT NULL, ocr TEXT, vista_em TEXT NOT NULL,
  PRIMARY KEY(processo, doc_id, sha256));
CREATE TABLE IF NOT EXISTS jobs(id INTEGER PRIMARY KEY, tipo TEXT NOT NULL, chave TEXT NOT NULL,
  estado TEXT NOT NULL DEFAULT 'fila', dono TEXT, prazo REAL, ficha INTEGER NOT NULL DEFAULT 0,
  tentativas INTEGER NOT NULL DEFAULT 0, criado_em TEXT NOT NULL, concluido_em TEXT, UNIQUE(tipo, chave));
CREATE INDEX IF NOT EXISTS ix_jobs_fila ON jobs(tipo, estado);
"""

_RX_ID = re.compile(r"(?:^|[\s(])(\d{7,10})\)?\s*$")


def _agora() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def conectar(caminho: Path | str = DB) -> sqlite3.Connection:
    con = sqlite3.connect(caminho, timeout=60)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=60000")
    con.executescript(_DDL)
    return con


def id_sei(titulo: str) -> str | None:
    """Número SEI do documento no fim do título ('… (86490508)' ou '… 86490508'); None se não houver."""
    m = _RX_ID.search(str(titulo or "").strip())
    return m.group(1) if m else None


def hash_arvore(ids: list[str]) -> str:
    return hashlib.sha256(json.dumps(sorted(ids)).encode()).hexdigest()


def importar_pasta(con: sqlite3.Connection, pasta: Path, origem: str = "sei_arquivo") -> dict:
    """Registra um processo do acervo. Idempotente: rodar de novo sem mudança não cria nada."""
    from compliance_agent.sei import acervo_texto
    man = json.loads((pasta / "manifest.json").read_text(encoding="utf-8"))
    processo = str(man.get("processo") or pasta.name.replace("_", "/"))
    em = _agora()
    vistos: dict[str, int] = {}
    linhas_doc, linhas_ver = [], []
    for d in man.get("docs") or []:
        if not isinstance(d, dict):
            continue
        n = id_sei(d.get("titulo", ""))
        base = f"sei:{n}" if n else f"pos:{d.get('i')}"
        vistos[base] = vistos.get(base, 0) + 1
        doc_id = base if vistos[base] == 1 else f"{base}#{vistos[base]}"
        linhas_doc.append((processo, doc_id, d.get("i"), d.get("titulo"), d.get("tipo"), d.get("fase"), em))
        texto = acervo_texto.ler(pasta, d) if d.get("texto") else ""
        if texto:
            linhas_ver.append((processo, doc_id, hashlib.sha256(texto.encode("utf-8")).hexdigest(), len(texto),
                               origem, str(d.get("ocr_motor") or ("ocr" if d.get("ocr") else "nativo")), em))
    with con:
        con.execute("INSERT INTO processos VALUES(?,?,?,?) ON CONFLICT(processo) DO UPDATE SET ultima_em=excluded.ultima_em",
                    (processo, pasta.name, em, em))
        ids = [r[1].split("#")[0] for r in linhas_doc]
        con.execute("INSERT OR IGNORE INTO arvores VALUES(?,?,?,?,?)",
                    (processo, hash_arvore(ids), len(ids), em, origem))
        con.executemany("INSERT INTO documentos VALUES(?,?,?,?,?,?,?) ON CONFLICT(processo, doc_id) DO UPDATE SET "
                        "posicao=excluded.posicao, titulo=excluded.titulo, tipo=excluded.tipo, fase=excluded.fase",
                        linhas_doc)
        antes_ver = con.total_changes
        con.executemany("INSERT OR IGNORE INTO versoes VALUES(?,?,?,?,?,?,?)", linhas_ver)
        novas = con.total_changes - antes_ver
    return {"processo": processo, "documentos": len(linhas_doc), "versoes_novas": novas}


# ── fila com reserva e ficha de posse ─────────────────────────────────────────────────────────────────
def enfileirar(con: sqlite3.Connection, tipo: str, chave: str) -> bool:
    with con:
        cur = con.execute("INSERT OR IGNORE INTO jobs(tipo, chave, criado_em) VALUES(?,?,?)", (tipo, chave, _agora()))
    return cur.rowcount == 1


MAX_TENTATIVAS = 5      # reserva vencida N vezes (worker morreu em todas) ⇒ quarentena, nunca laço eterno


def reservar(con: sqlite3.Connection, tipo: str, dono: str, prazo_s: float, agora: float | None = None) -> dict | None:
    """Pega o próximo job em fila (ou com reserva vencida) numa operação ATÔMICA (revisão do plano, 23/11: o
    SELECT-depois-UPDATE entregaria o mesmo job a dois workers no PostgreSQL). A ficha cresce a cada reserva.
    No PostgreSQL o subselect ganha `FOR UPDATE SKIP LOCKED` e `agora` vira `now()` do servidor (relógio único)."""
    agora = time.time() if agora is None else agora
    with con:
        con.execute("UPDATE jobs SET estado='quarentena' WHERE tipo=? AND estado='reservado' AND prazo < ? "
                    "AND tentativas >= ?", (tipo, agora, MAX_TENTATIVAS))
        r = con.execute("UPDATE jobs SET estado='reservado', dono=?, prazo=?, ficha=ficha+1, tentativas=tentativas+1 "
                        "WHERE id=(SELECT id FROM jobs WHERE tipo=? AND (estado='fila' OR (estado='reservado' "
                        "AND prazo < ?)) AND tentativas < ? ORDER BY id LIMIT 1) RETURNING id, chave, ficha",
                        (dono, agora + prazo_s, tipo, agora, MAX_TENTATIVAS)).fetchone()
    return {"id": r[0], "chave": r[1], "ficha": r[2]} if r else None


def concluir(con: sqlite3.Connection, job_id: int, ficha: int) -> bool:
    """Só a reserva vigente (mesma ficha) conclui; trabalhador antigo é recusado."""
    with con:
        cur = con.execute("UPDATE jobs SET estado='feito', concluido_em=? WHERE id=? AND ficha=? AND estado='reservado'",
                          (_agora(), job_id, ficha))
    return cur.rowcount == 1


def falhar(con: sqlite3.Connection, job_id: int, ficha: int) -> bool:
    """Devolve o job à fila (ou à quarentena, se já gastou as tentativas). Só a reserva vigente devolve."""
    with con:
        cur = con.execute("UPDATE jobs SET estado=CASE WHEN tentativas >= ? THEN 'quarentena' ELSE 'fila' END, "
                          "prazo=NULL WHERE id=? AND ficha=? AND estado='reservado'", (MAX_TENTATIVAS, job_id, ficha))
    return cur.rowcount == 1


# ── CLI ───────────────────────────────────────────────────────────────────────────────────────────────
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Plataforma de evidências (Fase 1)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    imp = sub.add_parser("importar")
    imp.add_argument("--limite", type=int, default=0)
    sub.add_parser("resumo")
    a = ap.parse_args(argv)
    con = conectar()
    if a.cmd == "importar":
        pastas = sorted(p.parent for p in ARQUIVO.glob("*/manifest.json"))
        if a.limite:
            pastas = pastas[: a.limite]
        tot = {"processos": 0, "documentos": 0, "versoes_novas": 0, "erros": 0}
        for i, p in enumerate(pastas, 1):
            try:
                r = importar_pasta(con, p)
            except (OSError, ValueError) as exc:
                tot["erros"] += 1
                print(f"erro {p.name}: {exc}", file=sys.stderr)
                continue
            tot["processos"] += 1
            tot["documentos"] += r["documentos"]
            tot["versoes_novas"] += r["versoes_novas"]
            if i % 1000 == 0:
                print(f"{i}/{len(pastas)} {tot}", flush=True)
        print(json.dumps(tot, ensure_ascii=False))
    else:
        for t in ("processos", "arvores", "documentos", "versoes", "jobs"):
            print(t, con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0])
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
