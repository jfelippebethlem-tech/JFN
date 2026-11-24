# -*- coding: utf-8 -*-
"""Carga da IDENTIDADE dos manifests do acervo no PostgreSQL da plataforma (plano mestre v2 §3.1/§3.8, O3.1 + O3.2).

Para cada `data/sei_arquivo/<pasta>/manifest.json`:
  processos   chave canônica de `dominio.processo_id.chave_processo` (do campo `processo`, ou da pasta sem ele)
  arvores     `evidencias.hash_arvore` dos ids sem o `#k` — a mesma conta do `evidencias.importar_pasta`
  documentos  id de `dominio.documento_id.ids_documentos` (`sei:<nº>` / `pos:<i>` / `#2`); posição, tipo e fase do
              manifest NORMALIZADO por `sei/manifesto_norm.normalizar` (vocabulário fino de `sei/fases.py`)
  versoes     `evidencias.versao_texto` (sha256 do texto sem a etiqueta nossa), `hash_de='texto'`,
              `aquisicao_id='legado'`. Nenhum manifest aponta para o binário do documento (o acervo guarda texto
              e fotos; os PDFs de `data/sei_cache/docs_*` são nomeados pelo título, sem vínculo provado com o doc),
              então nenhuma versão do legado tem `hash_de='binario'` — casar por nome seria palpite.

Idempotente (ON CONFLICT; documento só é reescrito se mudou) e retomável: o processo cuja árvore (processo, hash)
já está no banco é pulado sem ler os textos — cada lote é UMA transação, então árvore gravada ⇒ processo inteiro
gravado. Lotes pequenos, `lock_timeout` curto e pausa entre lotes: o servidor é o mesmo do jfn-brain.
Roda com nice 15 / ionice ociosa (aplicados a si mesmo no início).

Uso (DSN do ambiente ou de ~/.config/jfn/pg_evidencias.env; nunca impresso):
    .venv/bin/python tools/evidencias_carga_manifestos.py carregar --esquema tmp_carga_x [--limite N] [--lote 40]
    .venv/bin/python tools/evidencias_carga_manifestos.py carregar --esquema public
    .venv/bin/python tools/evidencias_carga_manifestos.py paridade --esquema public [--json saida.json]
    .venv/bin/python tools/evidencias_carga_manifestos.py apagar-esquema --esquema tmp_carga_x
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from compliance_agent import evidencias as E                        # noqa: E402
from compliance_agent.dominio import documento_id, processo_id     # noqa: E402
from compliance_agent.fluxo.schema import renderizar, validar_esquema  # noqa: E402
from compliance_agent.sei import acervo_texto, manifesto_norm       # noqa: E402

RAIZ = Path(__file__).resolve().parents[1]
MIGRACAO = RAIZ / "deploy" / "vm2" / "postgres" / "evidencias_001.sql"
ORIGEM = "sei_arquivo"
AQUISICAO = "legado"
HASH_DE = "texto"
LOTE = 40                  # processos por transação (~1.400 documentos na média do acervo)
PAUSA_S = 0.05


# ── conexão ───────────────────────────────────────────────────────────────────────────────────────────
def dsn_no_esquema(dsn: str, esquema: str) -> str:
    """DSN com `search_path` no esquema (o padrão de tests/test_evidencias_pg.py): evidencias.conectar cria e usa
    as tabelas lá."""
    validar_esquema(esquema)
    return dsn + ("&" if "?" in dsn else "?") + f"options=-csearch_path%3D{esquema}"


def preparar(dsn: str, esquema: str):
    """Esquema + tabelas do evidencias.py + migração O3.2. Devolve a conexão `evidencias._Pg` no esquema."""
    import psycopg
    validar_esquema(esquema)
    with psycopg.connect(dsn, autocommit=True) as c:
        c.execute(f'CREATE SCHEMA IF NOT EXISTS "{esquema}"')
    con = E.conectar(dsn_no_esquema(dsn, esquema))
    with psycopg.connect(dsn, autocommit=True) as c:
        c.execute(renderizar(MIGRACAO.read_text(encoding="utf-8"), esquema))
    con.execute("SET lock_timeout = '5s'")
    con.execute("SET statement_timeout = '120s'")
    return con


def baixar_prioridade() -> None:
    os.nice(15)
    subprocess.run(["ionice", "-c3", "-p", str(os.getpid())], check=False, capture_output=True)


# ── um manifest → linhas ──────────────────────────────────────────────────────────────────────────────
def _sem_nul(v):
    return v.replace("\x00", "") if isinstance(v, str) else v


def ler_processo(pasta: Path) -> dict:
    """Cabeçalho barato (sem ler os textos): chave, hash da árvore e linhas de `documentos`.
    `{"erro": motivo}` quando o manifest não serve (ilegível ou sem número de processo completo)."""
    man = acervo_texto.manifesto(pasta)
    if man is None:
        return {"pasta": pasta.name, "erro": "manifest ilegível"}
    bruto = man.get("processo") or pasta.name
    chave = processo_id.chave_processo(bruto)
    if not chave:
        return {"pasta": pasta.name, "erro": "sem número de processo completo", "processo_bruto": str(bruto)}
    docs = [d for d in (man.get("docs") or []) if isinstance(d, dict)]
    ids = documento_id.ids_documentos(docs)
    norm = manifesto_norm.normalizar(man)["docs"]          # mesma ordem e mesmo filtro (só dicts)
    if len(norm) != len(docs):                              # paridade com manifesto_norm: não pode divergir
        raise ValueError(f"{pasta.name}: manifesto_norm devolveu {len(norm)} docs, o manifest tem {len(docs)}")
    linhas_doc = []
    for doc_id, n in zip(ids, norm):
        pos = n["i"] if n["i"] >= 0 else None
        linhas_doc.append((chave, doc_id, pos, _sem_nul(n.get("titulo")), n.get("tipo"), n.get("fase")))
    return {"pasta": pasta.name, "processo": chave, "docs": docs, "ids": ids, "linhas_doc": linhas_doc,
            "hash": E.hash_arvore([documento_id.sem_repeticao(i) for i in ids]),
            "pasta_diverge": processo_id.chave_processo(pasta.name) not in (None, chave)}


def linhas_versao(pasta: Path, p: dict) -> list[tuple]:
    out = []
    for doc_id, d in zip(p["ids"], p["docs"]):
        v = E.versao_texto(pasta, d)
        if v:
            out.append((p["processo"], doc_id, v[0], v[1], ORIGEM, v[2], HASH_DE, AQUISICAO))
    return out


# ── carga ─────────────────────────────────────────────────────────────────────────────────────────────
_INS_PROC = ("INSERT INTO processos(processo, tag, primeira_em, ultima_em) VALUES(?,?,?,?) "
             "ON CONFLICT(processo) DO UPDATE SET ultima_em=excluded.ultima_em")
_INS_ARV = ("INSERT INTO arvores(processo, hash, n_docs, vista_em, origem) VALUES(?,?,?,?,?) "
            "ON CONFLICT DO NOTHING")
_INS_DOC = ("INSERT INTO documentos(processo, doc_id, posicao, titulo, tipo, fase, visto_em) VALUES(?,?,?,?,?,?,?) "
            "ON CONFLICT(processo, doc_id) DO UPDATE SET posicao=excluded.posicao, titulo=excluded.titulo, "
            "tipo=excluded.tipo, fase=excluded.fase WHERE (documentos.posicao, documentos.titulo, documentos.tipo, "
            "documentos.fase) IS DISTINCT FROM (excluded.posicao, excluded.titulo, excluded.tipo, excluded.fase)")
_INS_VER = ("INSERT INTO versoes(processo, doc_id, sha256, chars, origem, ocr, vista_em, hash_de, aquisicao_id) "
            "VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING")


def pastas_do_acervo(raiz: Path) -> list[Path]:
    return sorted(p.parent for p in raiz.glob("*/manifest.json"))


def carregar(con, pastas: list[Path], lote: int = LOTE, forcar: bool = False, pausa: float = PAUSA_S,
             saida=sys.stdout) -> dict:
    tot = Counter()
    erros: list[dict] = []
    t0 = time.time()
    for k in range(0, len(pastas), lote):
        grupo = pastas[k:k + lote]
        procs = []
        for pasta in grupo:
            p = ler_processo(pasta)
            if "erro" in p:
                erros.append(p)
                continue
            procs.append((pasta, p))
        if not procs:
            continue
        ja = set()
        if not forcar:
            ja = {tuple(r) for r in con.execute("SELECT processo, hash FROM arvores WHERE processo = ANY(?)",
                                                ([p["processo"] for _, p in procs],)).fetchall()}
        em = E._agora()
        l_proc, l_arv, l_doc, l_ver = [], [], [], []
        for pasta, p in procs:
            if (p["processo"], p["hash"]) in ja:
                tot["pulados_ja_carregados"] += 1
                continue
            l_proc.append((p["processo"], p["pasta"], em, em))
            l_arv.append((p["processo"], p["hash"], len(p["ids"]), em, ORIGEM))
            l_doc += [r + (em,) for r in p["linhas_doc"]]
            l_ver += [r[:6] + (em,) + r[6:] for r in linhas_versao(pasta, p)]
            if p["pasta_diverge"]:
                tot["pasta_diverge_do_campo"] += 1
        if l_proc:
            with con:
                con.executemany(_INS_PROC, l_proc)
                con.executemany(_INS_ARV, l_arv)
                con.executemany(_INS_DOC, l_doc)
                if l_ver:
                    con.executemany(_INS_VER, l_ver)
            tot["processos"] += len(l_proc)
            tot["documentos"] += len(l_doc)
            tot["versoes"] += len(l_ver)
            time.sleep(pausa)
        feitos = min(k + lote, len(pastas))
        if feitos % (lote * 25) < lote or feitos == len(pastas):
            print(f"{feitos}/{len(pastas)} {dict(tot)} erros={len(erros)} {time.time() - t0:.0f}s",
                  file=saida, flush=True)
    return {"totais": dict(tot), "erros": erros, "segundos": round(time.time() - t0, 1)}


# ── paridade ──────────────────────────────────────────────────────────────────────────────────────────
def esperado_dos_manifests(pastas: list[Path]) -> dict:
    """O que a carga DEVERIA ter gravado, recontado dos manifests (lê os textos de novo)."""
    por_proc: dict[str, dict] = {}
    sem_chave, dup = [], []
    docs_brutos = 0
    for pasta in pastas:
        p = ler_processo(pasta)
        if "erro" in p:
            man = acervo_texto.manifesto(pasta) or {}
            n = len([d for d in (man.get("docs") or []) if isinstance(d, dict)])
            docs_brutos += n
            sem_chave.append({**p, "docs": n})
            continue
        docs_brutos += len(p["ids"])
        if p["processo"] in por_proc:
            dup.append({"processo": p["processo"], "pastas": [por_proc[p["processo"]]["pasta"], p["pasta"]]})
        vers = linhas_versao(pasta, p)
        por_proc[p["processo"]] = {"pasta": p["pasta"], "hash": p["hash"], "docs": len(p["ids"]),
                                   "versoes": len({(r[1], r[2]) for r in vers}),
                                   "sem_texto": len(p["ids"]) - len(vers)}
    return {"por_proc": por_proc, "sem_chave": sem_chave, "duplicados": dup, "manifests": len(pastas),
            "docs_brutos": docs_brutos}


def paridade(con, pastas: list[Path]) -> dict:
    esp = esperado_dos_manifests(pastas)
    pp = esp["por_proc"]

    def grupo(sql):
        return {r[0]: r[1] for r in con.execute(sql).fetchall()}

    pg_proc = {r[0] for r in con.execute("SELECT processo FROM processos").fetchall()}
    pg_arv = {(r[0], r[1]) for r in con.execute("SELECT processo, hash FROM arvores").fetchall()}
    pg_doc = grupo("SELECT processo, COUNT(*) FROM documentos GROUP BY processo")
    pg_ver = grupo("SELECT processo, COUNT(*) FROM versoes GROUP BY processo")
    pg_ver_leg = con.execute("SELECT COUNT(*) FROM versoes WHERE aquisicao_id = 'legado' AND hash_de = 'texto'"
                             ).fetchone()[0]
    dif = {"processo_faltando": sorted(set(pp) - pg_proc), "processo_sobrando": sorted(pg_proc - set(pp)),
           "arvore_faltando": sorted(k for k, v in pp.items() if (k, v["hash"]) not in pg_arv),
           "documentos_divergem": {k: [v["docs"], pg_doc.get(k, 0)] for k, v in pp.items()
                                   if v["docs"] != pg_doc.get(k, 0)},
           "versoes_divergem": {k: [v["versoes"], pg_ver.get(k, 0)] for k, v in pp.items()
                                if v["versoes"] != pg_ver.get(k, 0)}}
    contagem = {
        "manifests": esp["manifests"],
        "manifests_sem_chave": len(esp["sem_chave"]),
        "processos_distintos": {"manifests": len(pp), "pg": len(pg_proc)},
        "arvores": {"manifests": len(pp), "pg": con.execute("SELECT COUNT(*) FROM arvores").fetchone()[0]},
        "documentos": {"manifests": sum(v["docs"] for v in pp.values()),
                       "pg": con.execute("SELECT COUNT(*) FROM documentos").fetchone()[0],
                       "manifests_incl_sem_chave": esp["docs_brutos"]},
        "versoes": {"manifests": sum(v["versoes"] for v in pp.values()),
                    "pg": con.execute("SELECT COUNT(*) FROM versoes").fetchone()[0], "pg_legado_texto": pg_ver_leg},
        "documentos_sem_texto": sum(v["sem_texto"] for v in pp.values()),
    }
    # cruzamento com o que a leitura integral já gravou (mesmo banco): o par (processo, doc_id) e o sha batem?
    cruz = None
    if con.execute("SELECT to_regclass('docs_lidos')").fetchone()[0]:
        r = con.execute("SELECT COUNT(*), COUNT(d.doc_id), COUNT(v.sha256) FROM (SELECT DISTINCT processo, doc_id, "
                        "sha FROM docs_lidos) l LEFT JOIN documentos d ON d.processo=l.processo AND "
                        "d.doc_id=l.doc_id LEFT JOIN versoes v ON v.processo=l.processo AND v.doc_id=l.doc_id AND "
                        "v.sha256=l.sha").fetchone()
        cruz = {"docs_lidos_distintos": r[0], "com_documento": r[1], "com_mesma_versao_sha": r[2]}
    bate = not any(dif[k] for k in dif) and not esp["duplicados"]
    return {"contagem": contagem, "diferencas": dif, "sem_chave": esp["sem_chave"], "duplicados": esp["duplicados"],
            "cruzamento_docs_lidos": cruz, "bate_100": bate}


# ── CLI ───────────────────────────────────────────────────────────────────────────────────────────────
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Carga da identidade dos manifests no PG (O3.1/O3.2)")
    ap.add_argument("acao", choices=("carregar", "paridade", "apagar-esquema"))
    ap.add_argument("--esquema", required=True, help="'public' = produção; outro = esquema de teste")
    ap.add_argument("--raiz", default=str(acervo_texto.RAIZ))
    ap.add_argument("--limite", type=int, default=0)
    ap.add_argument("--lote", type=int, default=LOTE)
    ap.add_argument("--forcar", action="store_true", help="não pula processo com árvore já gravada")
    ap.add_argument("--json", default="", help="grava o resultado completo neste arquivo")
    a = ap.parse_args(argv)
    validar_esquema(a.esquema)
    dsn = E.dsn_vigente()
    if not dsn.startswith(("postgresql://", "postgres://")):
        print(f"{E.ENV_DSN} ausente", file=sys.stderr)
        return 2
    if a.acao == "apagar-esquema":
        if a.esquema in ("public", "fluxo"):
            print("recusado: esquema de produção", file=sys.stderr)
            return 2
        import psycopg
        with psycopg.connect(dsn, autocommit=True) as c:
            c.execute(f'DROP SCHEMA IF EXISTS "{a.esquema}" CASCADE')
        print(f"esquema {a.esquema} apagado")
        return 0
    baixar_prioridade()
    pastas = pastas_do_acervo(Path(a.raiz))
    if a.limite:
        pastas = pastas[:a.limite]
    con = preparar(dsn, a.esquema)
    try:
        if a.acao == "carregar":
            r = carregar(con, pastas, a.lote, a.forcar)
        else:
            r = paridade(con, pastas)
    finally:
        con.close()
    if a.json:
        Path(a.json).write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
    resumo = {k: v for k, v in r.items() if k not in ("diferencas",)}
    if "diferencas" in r:
        resumo["diferencas"] = {k: (len(v), list(v)[:10]) for k, v in r["diferencas"].items()}
    print(json.dumps(resumo, ensure_ascii=False, indent=1))
    return 0 if r.get("bate_100", True) else 1


if __name__ == "__main__":
    sys.exit(main())
