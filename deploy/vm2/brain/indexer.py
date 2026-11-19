"""Indexador incremental: vault (Obsidian), shared-brain e relatório do graphify."""
from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from datetime import datetime, timezone
import yaml

import brain_notas as N
from brain_core import HOME, embed, pool, slugify

SOURCES = {
    "vault": HOME / "sync" / "vault",
    "shared": HOME / "shared-brain",
    "graphify": HOME / "brain" / "inputs",
}
SKIP_DIRS = {".obsidian", ".trash", ".stfolder", ".stversions", ".git", "node_modules", "_handoff"}
MAX_CHARS, OVERLAP = 1400, 160

FM_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.S)
LINK_RE = re.compile(r"\[\[([^\]\n]+?)\]\]")
TAG_RE = re.compile(r"(?<![\w/#])#([A-Za-zÀ-ÿ][\w\-/À-ÿ]{1,40})")
HEAD_RE = re.compile(r"^(#{1,4})\s+(.+)$", re.M)


def iter_files():
    for src, root in SOURCES.items():
        if not root.exists():
            continue
        for p in root.rglob("*.md"):
            if any(part in SKIP_DIRS for part in p.parts) or ".sync-conflict" in p.name:
                continue
            yield src, root, p


def parse(text: str) -> tuple[dict, str]:
    m = FM_RE.match(text)
    if not m:
        return {}, text
    try:
        fm = yaml.safe_load(m.group(1)) or {}
        if not isinstance(fm, dict):
            fm = {}
    except yaml.YAMLError:
        fm = {}
    return fm, text[m.end():]


def chunk(title: str, body: str) -> list[tuple[str | None, str]]:
    """Divide por cabeçalhos; seções longas viram janelas com sobreposição."""
    parts, last, heading = [], 0, None
    for m in HEAD_RE.finditer(body):
        if body[last:m.start()].strip():
            parts.append((heading, body[last:m.start()].strip()))
        heading, last = m.group(2).strip(), m.end()
    if body[last:].strip():
        parts.append((heading, body[last:].strip()))
    out = []
    for h, txt in parts or [(None, body.strip())]:
        if len(txt) <= MAX_CHARS:
            out.append((h, txt))
            continue
        i = 0
        while i < len(txt):
            j = min(len(txt), i + MAX_CHARS)
            cut = txt.rfind("\n", i + MAX_CHARS // 2, j)
            j = cut if cut > 0 and j < len(txt) else j
            out.append((h, txt[i:j].strip()))
            if j >= len(txt):
                break
            i = max(j - OVERLAP, i + 1)
    return [(h, t) for h, t in out if len(t) > 20]


def tags_of(fm: dict, body: str) -> list[str]:
    t = fm.get("tags") or []
    if isinstance(t, str):
        t = [x.strip() for x in re.split(r"[,\s]+", t) if x.strip()]
    return sorted({str(x).lstrip("#").lower() for x in t} | {x.lower() for x in TAG_RE.findall(body)})


def run(full: bool = False) -> dict:
    t0 = time.time()
    stats = {"novas": 0, "alteradas": 0, "removidas": 0, "trechos": 0}
    with pool().connection() as c:
        c.autocommit = True
        known = {(s, p): (i, sha) for i, s, p, sha in c.execute("SELECT id,source,path,sha FROM notes")}
        seen = set()
        for src, root, p in iter_files():
            rel = str(p.relative_to(root))
            seen.add((src, rel))
            raw = p.read_text(encoding="utf-8", errors="replace")
            sha = hashlib.sha1(raw.encode()).hexdigest()
            prev = known.get((src, rel))
            if prev and prev[1] == sha and not full:
                continue
            fm, body = parse(raw)
            title = str(fm.get("title") or fm.get("name") or p.stem)
            slug = slugify(p.stem)
            tags = tags_of(fm, body)
            pieces = chunk(title, body)
            vecs = embed([f"{title} — {h or ''}\n{t}" for h, t in pieces]) if pieces else []
            mtime = datetime.fromtimestamp(p.stat().st_mtime, timezone.utc)
            with c.transaction():
                if prev:
                    c.execute("DELETE FROM notes WHERE id=%s", (prev[0],))
                    c.execute("DELETE FROM edges WHERE lower(src)=%s AND origin=%s", (slug, src))
                nid = c.execute(
                    "INSERT INTO notes(source,path,title,slug,tags,frontmatter,body,sha,mtime) "
                    "VALUES (%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s) RETURNING id",
                    (src, rel, title, slug, tags, json.dumps(fm, default=str, ensure_ascii=False),
                     body, sha, mtime)).fetchone()[0]
                with c.cursor() as cur:
                    cur.executemany(
                        "INSERT INTO chunks(note_id,ord,heading,content,emb) VALUES (%s,%s,%s,%s,%s)",
                        [(nid, i, h, t, v) for i, ((h, t), v) in enumerate(zip(pieces, vecs))])
                    links = {slugify(l) for l in LINK_RE.findall(body)} - {"", slug}
                    rows = [(slug, l, "link", src) for l in links] + [(slug, f"#{t}", "tag", src) for t in tags]
                    if rows:
                        cur.executemany("INSERT INTO edges(src,dst,rel,origin) VALUES (%s,%s,%s,%s) "
                                        "ON CONFLICT DO NOTHING", rows)
                N.gravar_mencoes(c, "nota:" + N.chave_nota(src, rel), f"{title}\n{raw}", N.papel_da_nota(rel))
            stats["alteradas" if prev else "novas"] += 1
            stats["trechos"] += len(pieces)
            print(f"[{src}] {rel} ({len(pieces)})", flush=True)
        for key, (nid, _) in known.items():
            if key not in seen:
                with c.transaction():
                    slug = c.execute("SELECT slug FROM notes WHERE id=%s", (nid,)).fetchone()[0]
                    c.execute("DELETE FROM notes WHERE id=%s", (nid,))
                    c.execute("DELETE FROM edges WHERE lower(src)=%s AND origin=%s", (slug, key[0]))
                    c.execute("DELETE FROM entidade_mencao WHERE origem_ref=%s", ("nota:" + N.chave_nota(*key),))
                stats["removidas"] += 1
        stats.update(N.sincronizar(iter_files()))          # índice BM25 por nota (busca do brain_search)
        c.execute("INSERT INTO events(actor,action,detail) VALUES ('indexer','run',%s::jsonb)",
                  (json.dumps({**stats, "segundos": round(time.time() - t0, 1)}),))
    stats["segundos"] = round(time.time() - t0, 1)
    return stats


def entidades_completo() -> dict:
    """Carga inicial (ou refazer) do índice de entidades: todas as notas e todas as memórias ativas. Idempotente."""
    n = m = 0
    with pool().connection() as c, c.transaction():
        cores = N.carregar_cores(c)
        for src, path, title, body, fm in c.execute("SELECT source, path, title, body, frontmatter::text FROM notes").fetchall():
            n += bool(N.gravar_mencoes(c, "nota:" + N.chave_nota(src, path), f"{title}\n{fm}\n{body}",
                                       N.papel_da_nota(path) if src == "vault" else "citada"))
        for mid, subject, content in c.execute("SELECT id, subject, content FROM memories WHERE status='ativa'").fetchall():
            m += bool(N.gravar_mencoes(c, f"mem:{mid}", f"{subject or ''} {content}"))
        tot = c.execute("SELECT count(*), count(DISTINCT (tipo, chave)) FROM entidade_mencao").fetchone()
    return {"notas_com_entidade": n, "memorias_com_entidade": m, "mencoes": tot[0], "entidades": tot[1], "ugs_com_cor": cores}


if __name__ == "__main__":
    if "--entidades" in sys.argv:
        print(json.dumps(entidades_completo(), ensure_ascii=False))
        sys.exit(0)
    if "--fts" in sys.argv:
        print(json.dumps(N.sincronizar(iter_files()), ensure_ascii=False))
        sys.exit(0)
    print(json.dumps(run(full="--full" in sys.argv), ensure_ascii=False))
