# -*- coding: utf-8 -*-
"""restauracao_semanal — E17 `manter:restauracao_semanal` (plano mestre v2 §9 O8.2, §14 regra 3-2-1-1-0: o "0" é
ZERO erro na restauração conferida). Backup que nunca foi restaurado não é backup.

O que faz, numa pasta de backup com `MD5SUMS` (o snapshot do HD do it-campo, camada morna):
  1. confere o md5 de cada artefato contra o `MD5SUMS` ANTES de usar (hash conferido, nunca o nome);
  2. PG: sobe um PostgreSQL TEMPORÁRIO (initdb num diretório 700, só socket unix, sem rede, sem arquivar WAL),
     `pg_restore` do dump, conta as linhas de cada tabela da origem e derruba/apaga a instância;
  3. SQLite: copia o banco para o disco de trabalho, confere o md5 da CÓPIA, roda `PRAGMA quick_check` e conta as
     tabelas-chave;
  4. compara as contagens com as da ORIGEM, que viajam com o backup (`contagens*.json|txt` da pasta, ou arquivo
     passado à mão): igualdade EXATA — o backup é uma foto, não um piso;
  5. `gravar`: escreve `backup.restauracao_ok` (1/0) e `backup.restauracao_quando` (epoch) em `fluxo.metricas` e
     reconta as linhas pela etiqueta da execução. A última linha impressa é o efeito (`config/fluxo.yaml`).

`executar` só usa a biblioteca padrão (roda no it-campo sem venv nem DSN, por stdin se preciso); `gravar` precisa do
DSN do PostgreSQL (resolvido por `compliance_agent.evidencias.dsn_vigente`, nunca impresso). `semanal` = os dois.

    python -m tools.restauracao_semanal executar --pasta /mnt/d/JFN-Frio/snapshot-AAAAMMDD \\
        --pg-bin ~/jfn-restauro/pg/usr/lib/postgresql/18/bin [--pg-origem origem_pg.json] [--saida r.json]
    python -m tools.restauracao_semanal gravar --resultado r.json --no itcampo
    python -m tools.restauracao_semanal semanal --raiz /mnt/d/JFN-Frio --no itcampo     # a rotina (O9.0)
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

PORTA_TEMP = 55433
DUMP_PG = "jfn_evidencias.dump"
SQLITE_PRINCIPAL = "compliance.db"
TABELAS_SQLITE = ("alertas", "ordens_bancarias", "sei_fila_captura", "pericia_integral", "lex_execucao")
_RX_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)?$")


def _pg_bin_padrao() -> str | None:
    """Binários do PG extraídos sem root no nó (it-campo, 24/11/2026: `dpkg -x` em ~/jfn-restauro/pg)."""
    for v in ("18", "17", "16"):
        for base in (Path.home() / "jfn-restauro" / "pg" / "usr", Path("/usr")):
            b = base / "lib" / "postgresql" / v / "bin"
            if (b / "pg_restore").exists():
                return str(b)
    return None


# ── puras ─────────────────────────────────────────────────────────────────────────────────────────────────────────
def ler_md5sums(texto: str) -> dict[str, str]:
    """Saída do `md5sum` → {arquivo: md5}. Linha malformada levanta (MD5SUMS ilegível não confere nada)."""
    out: dict[str, str] = {}
    for ln in texto.splitlines():
        if not ln.strip():
            continue
        m = re.match(r"^([0-9a-f]{32}) [ *](.+)$", ln.strip())
        if not m:
            raise ValueError(f"linha do MD5SUMS ilegível: {ln[:80]!r}")
        out[m.group(2)] = m.group(1)
    return out


def ler_contagens(texto: str) -> dict[str, int]:
    """Contagens da origem: JSON ou literal Python (o snapshot de 24/11 gravou `{'alertas': 63182, ...}`).
    Só aceita {tabela: inteiro ≥ 0} — qualquer outra coisa levanta (contagem ambígua não serve de régua)."""
    t = texto.strip().splitlines()[0] if texto.strip() else ""
    try:
        d = json.loads(t)
    except ValueError:
        d = ast.literal_eval(t)
    if not isinstance(d, dict) or not d:
        raise ValueError("contagens da origem vazias ou não são um dicionário")
    for k, v in d.items():
        if not isinstance(k, str) or not _RX_IDENT.match(k) or isinstance(v, bool) or not isinstance(v, int) or v < 0:
            raise ValueError(f"contagem inválida: {k!r}={v!r}")
    return dict(d)


def conferir_contagens(origem: dict[str, int], restaurado: dict[str, int | None]) -> dict:
    """Igualdade EXATA por tabela da origem. Tabela ausente/ilegível no restaurado (None) é divergência; origem vazia
    NÃO é ok (nada foi conferido — ausência não vira sucesso)."""
    div = {t: {"origem": n, "restaurado": restaurado.get(t)} for t, n in origem.items() if restaurado.get(t) != n}
    return {"ok": bool(origem) and not div, "conferidas": len(origem) - len(div), "tabelas": len(origem),
            "divergencias": div}


def veredito(partes: dict[str, dict]) -> dict:
    """Junta as partes (pg, sqlite): ok só se TODA parte declarada está ok e há ao menos uma."""
    falhas = sorted(k for k, v in partes.items() if not v.get("ok"))
    return {"ok": bool(partes) and not falhas, "falhas": falhas}


def md5_arquivo(p: Path, bloco: int = 1 << 22) -> str:
    h = hashlib.md5()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(bloco), b""):
            h.update(b)
    return h.hexdigest()


def achar_contagens(pasta: Path) -> Path | None:
    """O arquivo de contagens da origem mais recente da pasta (`contagens*.json` antes de `contagens*.txt`)."""
    cands = sorted(pasta.glob("contagens*.json")) or sorted(pasta.glob("contagens*.txt"))
    return cands[-1] if cands else None


def ultima_pasta(raiz: Path) -> Path | None:
    """O snapshot mais novo da raiz (nome `snapshot-AAAAMMDD*` com MD5SUMS)."""
    ps = sorted(p for p in raiz.glob("snapshot-*") if (p / "MD5SUMS").is_file())
    return ps[-1] if ps else None


# ── restauração (efeitos no disco de trabalho, nunca na origem) ──────────────────────────────────────────────────
def _conferir_md5(arq: Path, esperado: str) -> dict:
    obtido = md5_arquivo(arq)
    return {"arquivo": arq.name, "md5_esperado": esperado, "md5_obtido": obtido, "ok": obtido == esperado}


def restaurar_pg(dump: Path, pg_bin: Path, trabalho: Path, origem: dict[str, int]) -> dict:
    """PostgreSQL temporário → pg_restore → contagens. A instância nunca escuta TCP e nunca arquiva WAL."""
    for t in origem:
        if not _RX_IDENT.match(t):
            raise ValueError(f"nome de tabela inválido: {t!r}")
    d = Path(tempfile.mkdtemp(prefix="pg-", dir=trabalho))
    dados, sock = d / "dados", d / "sock"
    sock.mkdir(mode=0o700)
    env = dict(os.environ, LC_ALL="C.UTF-8")
    bib = pg_bin.parents[3] / "lib" / "x86_64-linux-gnu"     # binários extraídos sem root (dpkg -x): libs ao lado
    if bib.is_dir():
        env["LD_LIBRARY_PATH"] = f"{bib}:{env.get('LD_LIBRARY_PATH', '')}".rstrip(":")
    run = lambda *a, **k: subprocess.run([str(x) for x in a], env=env, capture_output=True, text=True, **k)  # noqa
    t0 = time.time()
    try:
        r = run(pg_bin / "initdb", "-D", dados, "-U", "postgres", "-A", "trust", "-E", "UTF8", "--locale=C.UTF-8",
                "--no-sync", timeout=300)
        if r.returncode:
            return {"ok": False, "erro": f"initdb: {r.stderr[-300:]}"}
        (dados / "postgresql.auto.conf").write_text(
            f"listen_addresses = ''\nport = {PORTA_TEMP}\nunix_socket_directories = '{sock}'\narchive_mode = off\n"
            "fsync = off\nmax_connections = 10\n", encoding="utf-8")
        r = run(pg_bin / "pg_ctl", "-D", dados, "-l", d / "pg.log", "-w", "-t", "120", "start", timeout=180)
        if r.returncode:
            return {"ok": False, "erro": f"pg_ctl start: {r.stderr[-300:]}"}
        con = ["-h", sock, "-p", PORTA_TEMP, "-U", "postgres"]
        run(pg_bin / "createdb", *con, "jfn_restauro", timeout=60)
        r = run(pg_bin / "pg_restore", *con, "-d", "jfn_restauro", "--no-owner", "--no-acl", "--exit-on-error",
                "-j", "4", dump, timeout=7200)
        if r.returncode:
            return {"ok": False, "erro": f"pg_restore rc={r.returncode}: {r.stderr[-400:]}"}
        contagens: dict[str, int | None] = {}
        for t in origem:
            q = run(pg_bin / "psql", *con, "-d", "jfn_restauro", "-qAtX", "-v", "ON_ERROR_STOP=1",
                    "-c", f"SELECT count(*) FROM {t if '.' in t else 'public.' + t}", timeout=600)
            contagens[t] = int(q.stdout.strip()) if q.returncode == 0 and q.stdout.strip().isdigit() else None
        ver = run(pg_bin / "postgres", "--version", timeout=30).stdout.strip()
        conf = conferir_contagens(origem, contagens)
        return {**conf, "restaurado": contagens, "origem": origem, "servidor": ver, "duracao_s": round(time.time() - t0, 1)}
    finally:
        if (dados / "postmaster.pid").exists():
            run(pg_bin / "pg_ctl", "-D", dados, "-m", "immediate", "stop", timeout=120)
        shutil.rmtree(d, ignore_errors=True)


def restaurar_sqlite(db: Path, md5_esperado: str, trabalho: Path, origem: dict[str, int]) -> dict:
    """Cópia no disco de trabalho → md5 da cópia → quick_check → contagens. A cópia é apagada no fim."""
    for t in origem:
        if not _RX_IDENT.match(t) or "." in t:
            raise ValueError(f"nome de tabela inválido: {t!r}")
    d = Path(tempfile.mkdtemp(prefix="sqlite-", dir=trabalho))
    alvo = d / db.name
    t0 = time.time()
    try:
        shutil.copyfile(db, alvo)
        md5_copia = md5_arquivo(alvo)
        if md5_copia != md5_esperado:
            return {"ok": False, "erro": "md5 da cópia restaurada difere do MD5SUMS", "md5_obtido": md5_copia}
        con = sqlite3.connect(f"file:{alvo}?mode=ro", uri=True)
        try:
            qc = con.execute("PRAGMA quick_check(1)").fetchone()[0]
            contagens: dict[str, int | None] = {}
            for t in origem:
                try:
                    contagens[t] = int(con.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0])
                except sqlite3.Error:
                    contagens[t] = None
        finally:
            con.close()
        conf = conferir_contagens(origem, contagens)
        return {**conf, "ok": conf["ok"] and qc == "ok", "quick_check": qc, "restaurado": contagens,
                "origem": origem, "md5_copia": md5_copia, "duracao_s": round(time.time() - t0, 1)}
    finally:
        shutil.rmtree(d, ignore_errors=True)


def executar(pasta: Path, pg_bin: Path | None, trabalho: Path, pg_origem: dict | None,
             sqlite_origem: dict | None) -> dict:
    md5s = ler_md5sums((pasta / "MD5SUMS").read_text(encoding="utf-8"))
    res: dict = {"pasta": str(pasta), "inicio": time.strftime("%Y-%m-%d %H:%M:%S%z"), "host": os.uname().nodename,
                 "md5": {}, "partes": {}}
    trabalho.mkdir(parents=True, exist_ok=True)
    if sqlite_origem is None:
        p = achar_contagens(pasta)
        sqlite_origem = ler_contagens(p.read_text(encoding="utf-8")) if p else None
    alvos = [(SQLITE_PRINCIPAL, "sqlite", sqlite_origem)]
    if pg_bin is not None:
        alvos.append((DUMP_PG, "pg", pg_origem))
    for nome, parte, origem in alvos:
        arq = pasta / nome
        if nome not in md5s or not arq.is_file():
            res["partes"][parte] = {"ok": False, "erro": f"{nome} ausente da pasta ou do MD5SUMS"}
            continue
        if not origem:
            res["partes"][parte] = {"ok": False, "erro": f"sem contagens da origem para {nome}"}
            continue
        c = _conferir_md5(arq, md5s[nome])
        res["md5"][nome] = c
        if not c["ok"]:
            res["partes"][parte] = {"ok": False, "erro": f"md5 de {nome} na origem do backup não confere"}
            continue
        res["partes"][parte] = (restaurar_sqlite(arq, md5s[nome], trabalho, origem) if parte == "sqlite"
                                else restaurar_pg(arq, pg_bin, trabalho, origem))
    res.update(veredito(res["partes"]))
    res["fim"] = time.strftime("%Y-%m-%d %H:%M:%S%z")
    res["quando_epoch"] = time.time()
    return res


# ── métrica (fluxo.metricas) ─────────────────────────────────────────────────────────────────────────────────────
def linhas_metricas(res: dict, no: str, execucao: str) -> list[tuple]:
    """As duas linhas da métrica. `ok` é 1.0 só com o veredito ok; `quando` é o fim da restauração (epoch)."""
    rot = {"execucao": execucao, "pasta": res.get("pasta"), "host": res.get("host"), "falhas": res.get("falhas"),
           "partes": {k: {kk: v.get(kk) for kk in ("ok", "conferidas", "tabelas", "quick_check", "divergencias",
                                                   "erro", "duracao_s")}
                      for k, v in (res.get("partes") or {}).items()}}
    j = json.dumps(rot, ensure_ascii=False, default=str)
    return [(no, "backup.restauracao_ok", 1.0 if res.get("ok") else 0.0, j),
            (no, "backup.restauracao_quando", float(res["quando_epoch"]), j)]


def gravar(res: dict, no: str, con) -> dict:
    execucao = uuid.uuid4().hex[:12]
    linhas = linhas_metricas(res, no, execucao)
    with con.cursor() as cur:
        cur.executemany("INSERT INTO metricas(no, nome, valor, rotulos) VALUES (%s, %s, %s, %s::jsonb)", linhas)
    n = int(con.execute("SELECT count(*) FROM metricas WHERE rotulos->>'execucao' = %s", (execucao,)).fetchone()[0])
    return {"execucao": execucao, "gravadas": len(linhas), "conferidas": n}


def _conectar():
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from compliance_agent.fluxo import fila
    return fila.conectar()


def _gravar_e_relatar(res: dict, no: str) -> int:
    con = _conectar()
    try:
        g = gravar(res, no, con)
    finally:
        con.close()
    print(json.dumps(g))
    if g["conferidas"] != g["gravadas"]:
        print("restauracao_semanal: métrica NÃO conferida", file=sys.stderr)
        return 1
    if not res.get("ok"):
        print(f"restauracao_semanal: FALHOU ({', '.join(res.get('falhas') or [])}) — métrica ok=0 gravada "
              f"(execucao {g['execucao']})", file=sys.stderr)
        return 1
    tot = sum(int(p.get("tabelas") or 0) for p in res["partes"].values())
    print(f"restauracao_semanal: conferida {tot}/{tot} tabelas, métrica gravada execucao={g['execucao']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tools.restauracao_semanal")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for nome in ("executar", "semanal"):
        p = sub.add_parser(nome)
        if nome == "executar":
            p.add_argument("--pasta", required=True, type=Path)
        else:
            p.add_argument("--raiz", type=Path, default=Path(os.environ.get("JFN_RESTAURO_FONTE", "/mnt/d/JFN-Frio")))
            p.add_argument("--no", required=True, choices=("vm1", "vm2", "itcampo"))
        p.add_argument("--pg-bin", type=Path, default=os.environ.get("JFN_RESTAURO_PG_BIN") or _pg_bin_padrao())
        p.add_argument("--trabalho", type=Path, default=Path(os.environ.get(
            "JFN_RESTAURO_DIR", str(Path.home() / "jfn-restauro" / "trabalho"))))
        p.add_argument("--pg-origem", type=Path, help="JSON {tabela: n}; padrão: pg_contagens.json da pasta")
        p.add_argument("--sqlite-origem", type=Path, help="contagens do compliance.db; padrão: contagens* da pasta")
        p.add_argument("--saida", type=Path)
    p = sub.add_parser("gravar")
    p.add_argument("--resultado", required=True, type=Path)
    p.add_argument("--no", required=True, choices=("vm1", "vm2", "itcampo"))
    a = ap.parse_args(argv)

    if a.cmd == "gravar":
        return _gravar_e_relatar(json.loads(a.resultado.read_text(encoding="utf-8")), a.no)
    pasta = a.pasta if a.cmd == "executar" else ultima_pasta(a.raiz)
    if pasta is None:
        print(f"restauracao_semanal: nenhum snapshot com MD5SUMS em {a.raiz}", file=sys.stderr)
        return 1
    pg_o = a.pg_origem or (pasta / "pg_contagens.json")
    pg_origem = ler_contagens(pg_o.read_text(encoding="utf-8")) if pg_o.is_file() else None
    sq_origem = ler_contagens(a.sqlite_origem.read_text(encoding="utf-8")) if a.sqlite_origem else None
    try:
        os.nice(10)
    except OSError:
        pass
    res = executar(pasta, Path(a.pg_bin).expanduser() if a.pg_bin else None, a.trabalho, pg_origem, sq_origem)
    texto = json.dumps(res, ensure_ascii=False, indent=1, default=str)
    if a.saida:
        a.saida.write_text(texto, encoding="utf-8")
    print(texto)
    if a.cmd == "semanal":
        return _gravar_e_relatar(res, a.no)
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
