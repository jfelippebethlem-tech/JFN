#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""analitico_parquet — o analítico pesado em Parquet + DuckDB, FORA da VM-1 (O4.12 do plano mestre v2, ADR-001 D5).

POR QUE: o `compliance_analitico.db` (5,9 GB) é uma cópia SQLite inteira do `compliance.db`, refeita pelo cruzador das
23:00 na VM-1 e lida pelo DuckDB (`duckdb_util.conectar`) dentro do processo do painel — ~4 dias defasada no dia
24/11/2026 e DuckDB na VM-1, que a casa proíbe (já derrubou a VM). Aqui o analítico vira Parquet particionado por
exercício (zstd), lido pelo DuckDB só na VM-2 / it-campo; o painel recebe de volta arquivo PEQUENO com md5.

Subcomandos (todos menos `aplicar` usam DuckDB e RECUSAM rodar na VM-1):
  exportar     SQLite (snapshot, nunca o vivo) → <destino>/<tabela>/exercicio=AAAA/*.parquet + manifesto.json
               (linhas fonte × Parquet conferidas, sha256 por arquivo, schema por tabela, alembic).
  paridade     as 10 consultas pesadas no SQLite × no DuckDB-sobre-Parquet: resultado comparado e tempo medido.
  materializar visões pesadas do painel (DuckDB sobre Parquet) → envelopes JSON pequenos + .md5 (estágio E10).
  aplicar      (VM-1, sem DuckDB) confere o md5 do envelope e instala em data/analitico/ (estágio E15, idempotente).

Régua: pago = OB paga (`dominio.pagamento.ob_paga_sql`, o `_ob_paga` canônico); data do SIAFE é texto DD/MM/AAAA →
coluna `<col>_iso` com a MESMA expressão de `database/datas_iso.expr_iso` (fora do formato = NULL, nunca inventada).

Uso (VM-2): PYTHONPATH=. python -m tools.analitico_parquet exportar --fonte ~/analitico/snapshot-AAAAMMDD/compliance.db \
                --destino ~/analitico/parquet/snapshot-AAAAMMDD
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import socket
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from compliance_agent.database.datas_iso import expr_iso  # noqa: E402

VERSAO_MANIFESTO = 1
HOST_VM1 = "jfn-core"          # DuckDB nunca aqui (regra da casa; ADR-001 D5)
DISCO_MAX = 0.80               # o destino não passa de 80% de uso depois da exportação

# Tabelas que o analítico lê (grafo_cartel, rodizio_temporal, calibrar, eval_groundtruth, rede_societaria, cruzador,
# padroes/). `particao` = coluna do exercício; `iso` = colunas texto DD/MM/AAAA que ganham `<col>_iso`;
# `excluir` = colunas que nenhuma consulta analítica lê e só pesam (raw_json do espelho TFE).
TABELAS: dict[str, dict] = {
    "ob_orcamentaria_siafe": {"particao": "exercicio", "iso": ["data_emissao"]},
    "ordens_bancarias": {"particao": "exercicio", "excluir": ["raw_json"]},
    "ne_siafe": {"particao": "exercicio", "iso": ["data_emissao"]},
    "nl_siafe": {"particao": "exercicio", "iso": ["data_emissao"]},
    "ob_anomaly": {},
    "ob_reemitida": {},
    "penalidades_tcerj": {},
}


# ── guardas ─────────────────────────────────────────────────────────────────────────────────────────────────
def recusar_vm1(host: str | None = None) -> None:
    """DuckDB não roda na VM-1. `JFN_ANALITICO_HOST` só existe para teste."""
    h = host or os.environ.get("JFN_ANALITICO_HOST") or socket.gethostname()
    if h == HOST_VM1:
        raise SystemExit("analitico_parquet: DuckDB NÃO roda na VM-1 (jfn-core) — rode na VM-2 ou no it-campo")


def conferir_disco(destino: Path, estimativa_bytes: int, limite: float = DISCO_MAX) -> dict:
    """Recusa (SystemExit) se o disco do destino passaria de `limite` de uso com a estimativa somada."""
    alvo = destino
    while not alvo.exists():
        alvo = alvo.parent
    u = shutil.disk_usage(alvo)
    depois = (u.used + estimativa_bytes) / (u.used + u.free)    # a conta do `df` (sem o reservado do root)
    r = {"total": u.total, "usado": u.used, "estimativa": estimativa_bytes, "uso_depois": round(depois, 4)}
    if depois > limite:
        raise SystemExit(f"analitico_parquet: disco passaria de {limite:.0%} ({depois:.1%}) — {r}")
    return r


def _duck(threads: int = 2, memoria: str = "3GB", temp: Path | None = None):
    import duckdb
    con = duckdb.connect()
    con.execute(f"SET threads={int(threads)}")
    con.execute(f"SET memory_limit='{memoria}'")
    con.execute("SET preserve_insertion_order=false")
    if temp:
        temp.mkdir(parents=True, exist_ok=True)
        con.execute(f"SET temp_directory='{temp}'")
    return con


def sha256_arquivo(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for bloco in iter(lambda: f.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()


def _q(ident: str) -> str:
    return '"' + ident.replace('"', '""') + '"'


# ── exportar ────────────────────────────────────────────────────────────────────────────────────────────────
def _schema_sqlite(sq: sqlite3.Connection, tabela: str) -> tuple[str, list[tuple[str, str]]]:
    row = sq.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (tabela,)).fetchone()
    if not row:
        raise KeyError(tabela)
    # table_xinfo inclui colunas geradas (hidden 2/3): ficam de fora — a `<col>_iso` é recalculada aqui, não copiada
    cols = [(r[1], r[2]) for r in sq.execute(f"PRAGMA table_xinfo({_q(tabela)})") if r[6] == 0]
    return row[0], cols


def _alembic(sq: sqlite3.Connection) -> dict:
    versoes = sorted(p.stem for p in (RAIZ / "compliance_agent/database/alembic/versions").glob("[0-9]*.py"))
    try:
        aplicado = [r[0] for r in sq.execute("SELECT version_num FROM alembic_version")]
    except sqlite3.Error:
        aplicado = None
    return {"head_no_codigo": versoes[-1] if versoes else None,
            "aplicado_na_fonte": aplicado,   # None = a fonte não tem alembic_version (as colunas *_iso são calculadas aqui)
            "estado": "MEDIDO"}


def exportar(fonte: Path, destino: Path, tabelas: dict[str, dict] | None = None, *, threads: int = 2,
             memoria: str = "3GB", estimativa_bytes: int | None = None, md5_fonte: str | None = None) -> dict:
    """Exporta `tabelas` da fonte SQLite para Parquet zstd em `destino` (que não pode existir) + manifesto.json.
    Escreve em `<destino>.tmp-<pid>` e só troca de nome depois de conferir as contagens."""
    tabelas = TABELAS if tabelas is None else tabelas
    fonte, destino = Path(fonte).resolve(), Path(destino)
    if destino.exists():
        raise SystemExit(f"analitico_parquet: destino já existe ({destino}) — exportação é imutável, use outro rótulo")
    disco = conferir_disco(destino.parent, estimativa_bytes if estimativa_bytes is not None
                           else fonte.stat().st_size // 3)
    tmp = destino.with_name(destino.name + f".tmp-{os.getpid()}")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    sq = sqlite3.connect(f"file:{fonte}?mode=ro", uri=True)
    con = _duck(threads, memoria, tmp / "_duck_tmp")
    con.execute("INSTALL sqlite; LOAD sqlite;")
    con.execute(f"ATTACH '{fonte}' AS src (TYPE sqlite, READ_ONLY)")
    ok = False
    man: dict = {"versao_manifesto": VERSAO_MANIFESTO, "gerado_em": datetime.now(timezone.utc).isoformat(),
                 "host": socket.gethostname(),
                 "fonte": {"caminho": str(fonte), "bytes": fonte.stat().st_size, "md5": md5_fonte,
                           "mtime": datetime.fromtimestamp(fonte.stat().st_mtime, timezone.utc).isoformat()},
                 "schema": {"alembic": _alembic(sq)}, "disco": disco, "tabelas": {}}
    try:
        for t, cfg in tabelas.items():
            t0 = time.time()
            ddl, cols = _schema_sqlite(sq, t)
            excl = set(cfg.get("excluir", []))
            sel = [_q(c) for c, _ in cols if c not in excl]
            for c in cfg.get("iso", []):
                sel.append(f"({expr_iso(_q(c))}) AS {_q(c + '_iso')}")
            sql = f"SELECT {', '.join(sel)} FROM src.{_q(t)}"
            part = cfg.get("particao")
            if part:
                saida = tmp / t
                con.execute(f"COPY ({sql}) TO '{saida}' (FORMAT parquet, COMPRESSION zstd, "
                            f"PARTITION_BY ({_q(part)}), WRITE_PARTITION_COLUMNS true)")
            else:
                (tmp / t).mkdir()
                con.execute(f"COPY ({sql}) TO '{tmp / t / 'dados.parquet'}' (FORMAT parquet, COMPRESSION zstd)")
            linhas_fonte = sq.execute(f"SELECT COUNT(*) FROM {_q(t)}").fetchone()[0]
            arquivos = []
            for p in sorted((tmp / t).rglob("*.parquet")):
                n = con.execute(f"SELECT COUNT(*) FROM read_parquet('{p}')").fetchone()[0]   # metadado
                arquivos.append({"caminho": str(p.relative_to(tmp)), "linhas": int(n), "bytes": p.stat().st_size,
                                 "sha256": sha256_arquivo(p)})
            linhas_pq = sum(a["linhas"] for a in arquivos)
            if linhas_pq != linhas_fonte:
                raise RuntimeError(f"{t}: {linhas_fonte} linhas na fonte × {linhas_pq} no Parquet — exportação abortada")
            man["tabelas"][t] = {
                "linhas_fonte": linhas_fonte, "linhas_parquet": linhas_pq, "particao": part,
                "colunas": [c for c, _ in cols if c not in excl] + [c + "_iso" for c in cfg.get("iso", [])],
                "excluidas": sorted(excl), "ddl_sha256": hashlib.sha256(ddl.encode()).hexdigest(),
                "arquivos": arquivos, "bytes": sum(a["bytes"] for a in arquivos), "segundos": round(time.time() - t0, 1)}
            print(f"[analitico] {t}: {linhas_pq:,} linhas, {len(arquivos)} arquivo(s), "
                  f"{man['tabelas'][t]['bytes'] / 1e6:,.1f} MB em {man['tabelas'][t]['segundos']} s", flush=True)
        ok = True
    finally:
        con.close(); sq.close()
        if not ok:
            shutil.rmtree(tmp, ignore_errors=True)
    shutil.rmtree(tmp / "_duck_tmp", ignore_errors=True)
    man["bytes_total"] = sum(v["bytes"] for v in man["tabelas"].values())
    (tmp / "manifesto.json").write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, destino)
    return man


def conferir_manifesto(destino: Path) -> dict:
    """Recalcula o sha256 de cada arquivo do manifesto. {'ok': bool, 'divergentes': [...]}"""
    destino = Path(destino)
    man = json.loads((destino / "manifesto.json").read_text(encoding="utf-8"))
    div = [a["caminho"] for t in man["tabelas"].values() for a in t["arquivos"]
           if not (destino / a["caminho"]).exists() or sha256_arquivo(destino / a["caminho"]) != a["sha256"]]
    return {"ok": not div, "divergentes": div, "arquivos": sum(len(t["arquivos"]) for t in man["tabelas"].values())}


def conectar_parquet(destino: Path, *, threads: int = 2, memoria: str = "3GB"):
    """DuckDB com uma VIEW por tabela do manifesto, com o MESMO nome da tabela SQLite (o SQL é o mesmo dos dois lados)."""
    destino = Path(destino)
    man = json.loads((destino / "manifesto.json").read_text(encoding="utf-8"))
    con = _duck(threads, memoria)
    for t in man["tabelas"]:
        con.execute(f"CREATE VIEW {_q(t)} AS SELECT * FROM read_parquet('{destino / t}/**/*.parquet', "
                    f"hive_partitioning=false)")
    return con


# ── as 10 consultas pesadas ─────────────────────────────────────────────────────────────────────────────────
# Forma PORTÁVEL (mesmo texto nos dois motores; só os 3 marcadores abaixo mudam por dialeto). Determinística: sem
# ANY_VALUE/arg_max (cuja escolha de empate não é definida) — mede a mesma agregação que a rota de produção faz.
#   {paga}  = `ob_paga_sql` (régua canônica, montada contra a fonte; idêntica nos dois lados)
#   {terc}  = credor terceiro CNPJ/CPF só dígitos;  {pj} = CNPJ só dígitos;  {iso} = data_emissao em AAAA-MM-DD
DIALETO = {
    "sqlite": {"terc": "length(credor) IN (11, 14) AND credor NOT GLOB '*[^0-9]*'",
               "pj": "length(credor) = 14 AND credor NOT GLOB '*[^0-9]*'",
               "iso": expr_iso("data_emissao")},
    "duckdb": {"terc": "length(credor) IN (11, 14) AND regexp_full_match(credor, '[0-9]+')",
               "pj": "length(credor) = 14 AND regexp_full_match(credor, '[0-9]+')",
               "iso": "data_emissao_iso"},
}

CONSULTAS: dict[str, dict] = {
    "q01_captura_orgaos": {
        "origem": "grafo_cartel.captura_orgaos → /api/cartel, grafo_poder, cruzador", "sql": """
        WITH forn AS (SELECT ug_emitente ug, credor, SUM(valor) tot FROM ob_orcamentaria_siafe
                      WHERE {paga} AND valor > 0 AND {terc} GROUP BY ug_emitente, credor)
        SELECT ug, COUNT(*) n_forn, SUM(tot) total, MAX(tot) top_valor FROM forn GROUP BY ug
        HAVING COUNT(*) >= 5 AND SUM(tot) >= 1000000"""},
    "q02_dependencia_fornecedores": {
        "origem": "grafo_cartel.dependencia_fornecedores → /api/cartel?modo=dependencia", "sql": """
        WITH fu AS (SELECT credor, ug_emitente ug, SUM(valor) tot FROM ob_orcamentaria_siafe
                    WHERE {paga} AND valor > 0 AND {terc} GROUP BY credor, ug_emitente)
        SELECT credor, COUNT(*) n_ug, SUM(tot) total, MAX(tot) top_valor FROM fu GROUP BY credor
        HAVING SUM(tot) >= 1000000"""},
    "q03_footprint_credor": {
        "origem": "grafo_cartel.vizinhanca_cartel (foot) → /api/cartel?cnpj, Lex, rede_societaria", "sql": """
        SELECT credor, COUNT(DISTINCT ug_emitente) n_ug_total FROM ob_orcamentaria_siafe
        WHERE {paga} AND valor > 0 AND {terc} GROUP BY credor"""},
    "q04_rodizio_varredura": {
        "origem": "rodizio_temporal.rodizio_varredura → /api/rodizio", "sql": """
        SELECT ug_emitente, exercicio, credor, SUM(valor) tot, COUNT(*) n FROM ob_orcamentaria_siafe
        WHERE {paga} AND valor > 0 AND {pj} GROUP BY ug_emitente, exercicio, credor"""},
    "q05_anos_so_no_espelho": {
        "origem": "rodizio_temporal._anos_so_no_espelho (INDISPONÍVEL honesto)", "sql": """
        SELECT t.ug, t.ex FROM (SELECT DISTINCT ug_codigo ug, exercicio ex FROM ordens_bancarias
                                WHERE exercicio IS NOT NULL) t
        /* ob-qualquer-status: cobertura (UG × exercício existe no SIAFE em qualquer situação), não soma */
        LEFT JOIN (SELECT DISTINCT ug_emitente ug, exercicio ex FROM ob_orcamentaria_siafe) s
               ON s.ug = t.ug AND s.ex = t.ex
        WHERE s.ug IS NULL"""},
    "q06_eval_groundtruth_ugs": {
        "origem": "eval_groundtruth.avaliar (espelho TFE × ob_anomaly)", "sql": """
        WITH forn AS (SELECT ug_codigo, favorecido_cpf, SUM(valor) tot FROM ordens_bancarias WHERE valor > 0
                      GROUP BY ug_codigo, favorecido_cpf),
             cap AS (SELECT ug_codigo, SUM(tot) total, MAX(tot) topv, COUNT(*) nf FROM forn GROUP BY ug_codigo),
             sc AS (SELECT o.ug_codigo, AVG(a.score) score_medio, COUNT(*) n_ob,
                           SUM(a.score * o.valor) / NULLIF(SUM(o.valor), 0) score_ponderado
                    FROM ordens_bancarias o JOIN ob_anomaly a ON a.ob_id = o.id GROUP BY o.ug_codigo)
        SELECT cap.ug_codigo, cap.total, cap.topv, cap.nf, COALESCE(sc.score_medio, 0) score_medio,
               COALESCE(sc.score_ponderado, 0) score_ponderado
        FROM cap LEFT JOIN sc ON sc.ug_codigo = cap.ug_codigo WHERE cap.total > 0"""},
    "q07_calibrar_por_exercicio": {
        "origem": "calibrar (ob_anomaly × espelho TFE por exercício)", "sql": """
        SELECT o.exercicio, COUNT(*) n, AVG(a.score) media, SUM(CASE WHEN a.score >= 0.8 THEN 1 ELSE 0 END) altos
        FROM ob_anomaly a JOIN ordens_bancarias o ON o.id = a.ob_id
        WHERE o.exercicio IS NOT NULL GROUP BY o.exercicio"""},
    "q08_ranking_ugs_tfe": {
        "origem": "tools/cruzador.sh (60 maiores UGs para a concentração por grupo)", "sql": """
        SELECT ug_codigo, SUM(valor) total FROM ordens_bancarias WHERE valor > 0 AND ug_codigo IS NOT NULL
        GROUP BY ug_codigo"""},
    "q09_padroes_ob_por_processo": {
        "origem": "padroes/_aditivos_comum.ob_por_processo (família aditivos de padroes/)", "sql": """
        SELECT processo, credor, nome_credor, ug_emitente, SUM(valor) v, COUNT(*) n FROM ob_orcamentaria_siafe
        WHERE {paga} AND processo LIKE '%/%/%' GROUP BY 1, 2, 3, 4"""},
    "q10_serie_mensal_ob_paga": {
        "origem": "série mensal de OB paga pela data ISO (corrida de dezembro / painel; régua data-emissao-siafe-e-texto)",
        "sql": """
        SELECT exercicio, substr({iso}, 1, 7) mes, COUNT(*) n, SUM(valor) total FROM ob_orcamentaria_siafe
        WHERE {paga} GROUP BY exercicio, substr({iso}, 1, 7)"""},
}


def montar_sql(nome: str, dialeto: str, paga: str) -> str:
    return CONSULTAS[nome]["sql"].format(paga=paga, **DIALETO[dialeto])


def _chave(v):
    return (0, "") if v is None else (1, f"{v:.6f}") if isinstance(v, float) else (1, str(v))


def _norm(linhas) -> list[tuple]:
    return sorted((tuple(r) for r in linhas), key=lambda r: tuple(_chave(v) for v in r))


def comparar(a: list, b: list, rel: float = 1e-9, absol: float = 1e-6) -> dict:
    """Compara dois resultados (ordem ignorada). Número: igual ou dentro de tolerância de ponto flutuante (a ordem da
    soma difere entre motores); texto/NULL: igualdade exata. Devolve contagens e até 5 exemplos de divergência."""
    na, nb = _norm(a), _norm(b)
    out = {"linhas_sqlite": len(na), "linhas_duckdb": len(nb), "iguais": 0, "flutuante": 0, "divergentes": 0,
           "max_dif_abs": 0.0, "exemplos": []}
    if len(na) != len(nb):
        out["divergentes"] = abs(len(na) - len(nb))
    for ra, rb in zip(na, nb):
        exato, perto = True, True
        for x, y in zip(ra, rb):
            if x == y:
                continue
            exato = False
            if isinstance(x, (int, float)) and isinstance(y, (int, float)) and not isinstance(x, bool) \
                    and math.isclose(x, y, rel_tol=rel, abs_tol=absol):
                out["max_dif_abs"] = max(out["max_dif_abs"], abs(x - y))
                continue
            perto = False
        if exato:
            out["iguais"] += 1
        elif perto:
            out["flutuante"] += 1
        else:
            out["divergentes"] += 1
            if len(out["exemplos"]) < 5:
                out["exemplos"].append({"sqlite": [str(v) for v in ra], "duckdb": [str(v) for v in rb]})
    out["veredito"] = ("IGUAL" if out["divergentes"] == 0 and out["flutuante"] == 0 else
                       "IGUAL_TOLERANCIA_FLUTUANTE" if out["divergentes"] == 0 else "DIVERGE")
    return out


def paridade(fonte: Path, parquet: Path, nomes: list[str] | None = None, *, threads: int = 2,
             memoria: str = "3GB") -> dict:
    """Roda cada consulta no SQLite (fonte) e no DuckDB sobre o Parquet; compara e mede o tempo das duas."""
    from compliance_agent.dominio.pagamento import ob_paga_sql
    sq = sqlite3.connect(f"file:{Path(fonte).resolve()}?mode=ro", uri=True)
    paga = ob_paga_sql(sq)          # a régua é montada contra a FONTE; o Parquet tem as mesmas colunas/tabelas
    dk = conectar_parquet(parquet, threads=threads, memoria=memoria)
    res = {"fonte": str(fonte), "parquet": str(parquet), "regua_ob_paga": paga, "host": socket.gethostname(),
           "em": datetime.now(timezone.utc).isoformat(), "consultas": {}}
    try:
        for nome in nomes or list(CONSULTAS):
            t0 = time.time()
            a = sq.execute(montar_sql(nome, "sqlite", paga)).fetchall()
            ts = time.time() - t0
            t0 = time.time()
            b = dk.execute(montar_sql(nome, "duckdb", paga)).fetchall()
            td = time.time() - t0
            c = comparar(a, b)
            c.update({"origem": CONSULTAS[nome]["origem"], "segundos_sqlite": round(ts, 2),
                      "segundos_duckdb": round(td, 2), "aceleracao": round(ts / td, 1) if td > 0 else None})
            res["consultas"][nome] = c
            print(f"[paridade] {nome}: {c['veredito']} ({c['linhas_sqlite']:,}×{c['linhas_duckdb']:,} linhas) "
                  f"SQLite {ts:.1f} s × DuckDB {td:.1f} s", flush=True)
    finally:
        sq.close(); dk.close()
    return res


# ── E10 materializar (VM-2) → E15 aplicar (VM-1) ────────────────────────────────────────────────────────────
# Visões pesadas do painel, prontas em envelope pequeno. Forma de PRODUÇÃO (DuckDB só: arg_max/ANY_VALUE ok aqui).
VISOES: dict[str, str] = {
    "captura_orgaos": """
        WITH forn AS (SELECT ug_emitente ug, credor, ANY_VALUE(nome_credor) nome, SUM(valor) tot
                      FROM ob_orcamentaria_siafe WHERE {paga} AND valor > 0 AND {terc} GROUP BY ug_emitente, credor),
             ag AS (SELECT ug, COUNT(*) n_forn, SUM(tot) total, MAX(tot) top_valor,
                           arg_max(nome, tot) top_nome, arg_max(credor, tot) top_doc FROM forn GROUP BY ug)
        SELECT ug, n_forn, total, top_valor, top_nome, top_doc FROM ag WHERE n_forn >= 5 AND total >= 1000000
        ORDER BY top_valor / total DESC, total DESC LIMIT 100""",
    "dependencia_fornecedores": """
        WITH fu AS (SELECT credor, ANY_VALUE(nome_credor) nome, ug_emitente ug, SUM(valor) tot
                    FROM ob_orcamentaria_siafe WHERE {paga} AND valor > 0 AND {terc} GROUP BY credor, ug_emitente),
             ag AS (SELECT credor, ANY_VALUE(nome) nome, COUNT(*) n_ug, SUM(tot) total, MAX(tot) top_valor,
                           arg_max(ug, tot) top_ug FROM fu GROUP BY credor)
        SELECT credor top_doc, nome top_nome, n_ug, total, top_valor, top_ug FROM ag WHERE total >= 1000000
        ORDER BY top_valor / total DESC, total DESC LIMIT 100""",
    "calibrar_por_exercicio": CONSULTAS["q07_calibrar_por_exercicio"]["sql"] + " ORDER BY 1",
    "ranking_ugs_tfe": CONSULTAS["q08_ranking_ugs_tfe"]["sql"] + " ORDER BY total DESC LIMIT 60",
}


def _lgpd(linha: dict) -> dict:
    """Documento de pessoa física mascarado e nome omitido (ADR-011 / LGPD) — o envelope vai para o painel."""
    from compliance_agent.padroes._comum import credor_publico, documento_publico, eh_pessoa_fisica
    if "top_doc" in linha:
        doc = linha["top_doc"]
        if "top_nome" in linha:
            linha["top_nome"] = credor_publico(doc, linha["top_nome"])
        linha["top_doc"] = documento_publico(doc) if eh_pessoa_fisica(doc) else doc
    return linha


def envelope(visao: str, colunas: list[str], linhas: list, manifesto_sha256: str) -> bytes:
    dados = [_lgpd(dict(zip(colunas, [float(v) if isinstance(v, float) else v for v in r]))) for r in linhas]
    corpo = {"visao": visao, "gerado_em": datetime.now(timezone.utc).isoformat(), "host": socket.gethostname(),
             "fonte": {"manifesto_sha256": manifesto_sha256, "regua": "OB paga (dominio.pagamento.ob_paga_sql)"},
             "estado": "VERIFICADO" if dados else "AUSENTE", "linhas": len(dados), "colunas": colunas, "dados": dados}
    return json.dumps(corpo, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")


def _gravar_atomico(p: Path, b: bytes) -> None:
    tmp = p.with_name(p.name + f".tmp-{os.getpid()}")
    tmp.write_bytes(b)
    os.replace(tmp, p)


def materializar(parquet: Path, saida: Path, visoes: list[str] | None = None) -> dict:
    """E10 (VM-2): cada visão → `<saida>/<visao>.json` + `<visao>.json.md5`. A régua OB paga é montada contra as
    colunas do Parquet (sem tocar SQLite)."""
    parquet, saida = Path(parquet), Path(saida)
    saida.mkdir(parents=True, exist_ok=True)
    man_sha = sha256_arquivo(parquet / "manifesto.json")
    dk = conectar_parquet(parquet)
    out = {}
    try:
        paga = regua_ob_paga_duck(dk)
        for v in visoes or list(VISOES):
            t0 = time.time()
            cur = dk.execute(VISOES[v].format(paga=paga, **DIALETO["duckdb"]))
            cols = [d[0] for d in cur.description]
            b = envelope(v, cols, cur.fetchall(), man_sha)
            md5 = hashlib.md5(b).hexdigest()
            _gravar_atomico(saida / f"{v}.json", b)
            _gravar_atomico(saida / f"{v}.json.md5", f"{md5}  {v}.json\n".encode())
            out[v] = {"md5": md5, "bytes": len(b), "segundos": round(time.time() - t0, 2)}
    finally:
        dk.close()
    return out


def regua_ob_paga_duck(dk) -> str:
    """`_ob_paga` exige uma conexão sqlite3 (PRAGMA/sqlite_master). Reproduz a régua contra o schema do Parquet
    numa base sqlite3 em memória com as MESMAS colunas/tabelas — o texto sai da função canônica, não é reescrito."""
    from compliance_agent.dominio.pagamento import ob_paga_sql
    views = {r[0] for r in dk.execute("SELECT view_name FROM duckdb_views() WHERE NOT internal").fetchall()}
    mem = sqlite3.connect(":memory:")
    try:
        for t in ("ob_orcamentaria_siafe", "ob_reemitida"):
            if t not in views:          # fora do manifesto = ausente para a régua (cai na regra antiga, como no SQLite)
                continue
            cols = [r[0] for r in dk.execute(f"DESCRIBE {_q(t)}").fetchall()]
            mem.execute(f"CREATE TABLE {_q(t)} ({', '.join(_q(c) for c in cols)})")
        return ob_paga_sql(mem)
    finally:
        mem.close()


def aplicar(envelope_json: Path, destino: Path) -> dict:
    """E15 (VM-1, sem DuckDB): confere o md5 do envelope contra o `.md5` ao lado e instala em `destino` (atômico).
    Mesmo md5 já instalado → 'inalterado' (idempotente). md5 divergente → recusa e NÃO toca o instalado."""
    envelope_json, destino = Path(envelope_json), Path(destino)
    b = envelope_json.read_bytes()
    esperado = envelope_json.with_name(envelope_json.name + ".md5").read_text(encoding="utf-8").split()[0]
    md5 = hashlib.md5(b).hexdigest()
    if md5 != esperado:
        return {"estado": "RECUSADO", "motivo": f"md5 {md5} ≠ {esperado}", "arquivo": envelope_json.name}
    json.loads(b)                                        # envelope ilegível não entra
    destino.mkdir(parents=True, exist_ok=True)
    alvo = destino / envelope_json.name
    if alvo.exists() and hashlib.md5(alvo.read_bytes()).hexdigest() == md5:
        return {"estado": "INALTERADO", "md5": md5, "arquivo": alvo.name}
    _gravar_atomico(alvo, b)
    _gravar_atomico(destino / (envelope_json.name + ".md5"), f"{md5}  {envelope_json.name}\n".encode())
    return {"estado": "APLICADO", "md5": md5, "arquivo": alvo.name, "bytes": len(b)}


# ── CLI ─────────────────────────────────────────────────────────────────────────────────────────────────────
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("exportar"); e.add_argument("--fonte", required=True, type=Path)
    e.add_argument("--destino", required=True, type=Path); e.add_argument("--md5-fonte")
    e.add_argument("--threads", type=int, default=2); e.add_argument("--memoria", default="3GB")
    c = sub.add_parser("conferir"); c.add_argument("--parquet", required=True, type=Path)
    p = sub.add_parser("paridade"); p.add_argument("--fonte", required=True, type=Path)
    p.add_argument("--parquet", required=True, type=Path); p.add_argument("--saida", type=Path)
    p.add_argument("--consulta", action="append")
    m = sub.add_parser("materializar"); m.add_argument("--parquet", required=True, type=Path)
    m.add_argument("--saida", required=True, type=Path)
    a = sub.add_parser("aplicar"); a.add_argument("--origem", required=True, type=Path)
    a.add_argument("--destino", type=Path, default=RAIZ / "data" / "analitico")
    ns = ap.parse_args(argv)
    if ns.cmd == "aplicar":
        rs = [aplicar(f, ns.destino) for f in sorted(ns.origem.glob("*.json"))]
        for r in rs:
            print(f"analitico aplicar: {r['estado']} {r.get('arquivo')} {r.get('md5', r.get('motivo', ''))}")
        return 1 if any(r["estado"] == "RECUSADO" for r in rs) or not rs else 0
    recusar_vm1()
    if ns.cmd == "exportar":
        man = exportar(ns.fonte, ns.destino, threads=ns.threads, memoria=ns.memoria, md5_fonte=ns.md5_fonte)
        print(f"analitico exportar: {len(man['tabelas'])} tabela(s), {man['bytes_total'] / 1e6:,.1f} MB → {ns.destino}")
    elif ns.cmd == "conferir":
        r = conferir_manifesto(ns.parquet)
        print(f"analitico conferir: {'ok' if r['ok'] else 'DIVERGE'} ({r['arquivos']} arquivos) {r['divergentes'][:5]}")
        return 0 if r["ok"] else 1
    elif ns.cmd == "paridade":
        r = paridade(ns.fonte, ns.parquet, ns.consulta)
        if ns.saida:
            ns.saida.write_text(json.dumps(r, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        return 1 if any(c["veredito"] == "DIVERGE" for c in r["consultas"].values()) else 0
    elif ns.cmd == "materializar":
        for v, r in materializar(ns.parquet, ns.saida).items():
            print(f"analitico materializar: {v} md5 {r['md5']} {r['bytes']} bytes em {r['segundos']} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
