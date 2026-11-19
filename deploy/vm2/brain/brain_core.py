"""Núcleo do Second Brain JFN: conexão, embeddings, busca por nota + resgate por vetor, memórias em duas linhas de tempo.

Versionado no JFN (deploy/vm2/brain/); a pasta ~/brain da VM-2 não é git — implantar com deploy/vm2/brain/implantar.sh."""
from __future__ import annotations

import hashlib
import re
import threading
from functools import lru_cache
from pathlib import Path

import numpy as np
from pgvector.psycopg import register_vector
from psycopg_pool import ConnectionPool

import brain_notas as N

HOME = Path.home()
BRAIN = HOME / "brain"
MODEL = "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"


def _env() -> dict[str, str]:
    out = {}
    for line in (BRAIN / ".env").read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


ENV = _env()
_pool: ConnectionPool | None = None
_lock = threading.Lock()


def pool() -> ConnectionPool:
    global _pool
    with _lock:
        if _pool is None:
            _pool = ConnectionPool(ENV["DATABASE_URL"], min_size=1, max_size=6,
                                   configure=register_vector, open=True)
    return _pool


@lru_cache(maxsize=1)
def _model():
    from fastembed import TextEmbedding
    return TextEmbedding(MODEL, cache_dir=str(BRAIN / "models"), threads=2)


def embed(texts: list[str], batch: int = 16) -> list[np.ndarray]:
    return [np.asarray(v, dtype=np.float32) for v in _model().embed(texts, batch_size=batch)]


def embed_one(text: str) -> np.ndarray:
    return embed([text])[0]


SLUG_RE = re.compile(r"[^\w\s\-./]", re.U)


def slugify(name: str) -> str:
    name = name.strip().split("|")[0].split("#")[0].strip()
    name = re.sub(r"\.md$", "", name)
    return name.split("/")[-1].strip().lower()


# ---------- busca híbrida (vetor + texto + título) com Reciprocal Rank Fusion ----------
HYBRID_SQL = """
WITH q AS (SELECT %(emb)s::vector AS e, websearch_to_tsquery('portuguese', f_unaccent(%(q)s)) AS t),
vec AS (
  SELECT c.id, row_number() OVER (ORDER BY c.emb <=> q.e) AS r
  FROM chunks c, q WHERE c.emb IS NOT NULL
  ORDER BY c.emb <=> q.e LIMIT 60
),
txt AS (
  SELECT c.id, row_number() OVER (ORDER BY ts_rank_cd(c.tsv, q.t) DESC) AS r
  FROM chunks c, q WHERE c.tsv @@ q.t
  ORDER BY ts_rank_cd(c.tsv, q.t) DESC LIMIT 60
),
fused AS (
  SELECT id, sum(1.0/(60+r)) AS score FROM (SELECT * FROM vec UNION ALL SELECT * FROM txt) u GROUP BY id
)
SELECT n.source, n.path, n.title, c.heading, c.content, f.score, n.id AS note_id
FROM fused f JOIN chunks c ON c.id=f.id JOIN notes n ON n.id=c.note_id
WHERE (%(source)s::text IS NULL OR n.source=%(source)s)
ORDER BY f.score DESC LIMIT %(k)s
"""

MEM_SQL = """
WITH q AS (SELECT %(emb)s::vector AS e, websearch_to_tsquery('portuguese', f_unaccent(%(q)s)) AS t),
vec AS (SELECT m.id, row_number() OVER (ORDER BY m.emb <=> q.e) r FROM memories m, q
        WHERE {vigente} ORDER BY m.emb <=> q.e LIMIT 40),
txt AS (SELECT m.id, row_number() OVER (ORDER BY ts_rank_cd(m.tsv,q.t) DESC) r FROM memories m, q
        WHERE {vigente} AND m.tsv @@ q.t LIMIT 40),
fused AS (SELECT id, sum(1.0/(60+r)) score FROM (SELECT * FROM vec UNION ALL SELECT * FROM txt) u GROUP BY id)
SELECT m.id, m.kind, m.subject, m.content, m.source, m.confidence, m.created_at, f.score,
       m.chave, m.valeu_de, m.valeu_ate, m.prova_doc
FROM fused f JOIN memories m ON m.id=f.id
WHERE (%(kind)s::text IS NULL OR m.kind=%(kind)s)
ORDER BY f.score DESC LIMIT %(k)s
"""


def _search_trechos(q: str, k: int = 8, source: str | None = None) -> list[dict]:
    """Busca antiga: trechos por vetor + texto (RRF). Hoje só RESGATA o que a busca por nota não trouxe."""
    emb = embed_one(q)
    with pool().connection() as c:
        rows = c.execute(HYBRID_SQL, {"emb": emb, "q": q, "k": k, "source": source}).fetchall()
    return [{"source": src, "path": path, "title": title, "heading": heading, "snippet": content[:700],
             "score": round(float(score), 4), "note_id": nid} for src, path, title, heading, content, score, nid in rows]


RESGATE = 2      # lugares que o vetor pode ocupar no fim da lista


def search(q: str, k: int = 8, source: str | None = None) -> list[dict]:
    """Uma linha por NOTA. Ordem: notas que citam o identificador da pergunta (CNPJ, processo, UG, OB) → BM25 por nota
    inteira com peso no título e no nome do arquivo → até RESGATE notas que só o vetor achou. Medido em 19/11/2026
    (JFN config/cerebro_bateria.yaml): recall@10 de 33 para 56 em 56. Voltar à busca antiga: BRAIN_BUSCA=antiga no .env."""
    if ENV.get("BRAIN_BUSCA") == "antiga":
        return _search_trechos(q, k, source)
    base: list[dict] = []
    with pool().connection() as c:
        for tipo, chave in N.F.entidades(q):
            for (ref,) in c.execute("SELECT origem_ref FROM entidade_mencao WHERE tipo=%s AND chave=%s AND origem_ref "
                                    "LIKE 'nota:%%' ORDER BY (papel='caso') DESC, origem_ref LIMIT 20", (tipo, chave)):
                base.append({"nota": ref[5:], "trecho": f"cita {tipo} {chave}", "via": "entidade"})
    base += [{**n, "via": "bm25"} for n in N.notas(q, 40)]
    vistos, ordem = set(), []
    for n in base:
        fonte, _, caminho = n["nota"].partition(":") if ":" in n["nota"].split("/")[0] else ("vault", "", n["nota"])
        if n["nota"] in vistos or (source and fonte != source):
            continue
        vistos.add(n["nota"])
        ordem.append({"source": fonte, "path": caminho, "snippet": (n.get("trecho") or "")[:700], "via": n["via"]})
    resg = []
    for r in _search_trechos(q, 25, source):
        chave = N.chave_nota(r["source"], r["path"])
        if chave not in vistos:
            vistos.add(chave)
            resg.append({**r, "via": "vetor"})
    resg = resg[:max(RESGATE, k - len(ordem))]
    ordem = ordem[:k - min(len(resg), RESGATE)]
    with pool().connection() as c:
        meta = {(s, p): (i, t) for i, s, p, t in c.execute(
            "SELECT id, source, path, title FROM notes WHERE path = ANY(%s)", ([o["path"] for o in ordem],))}
    out = []
    for o in ordem:
        nid, titulo = meta.get((o["source"], o["path"]), (None, None))
        out.append({"source": o["source"], "path": o["path"], "title": titulo, "heading": None, "snippet": o["snippet"],
                    "score": 0.0, "note_id": nid, "via": o["via"]})
    out = (out + resg)[:k]
    for pos, o in enumerate(out, 1):
        o["score"] = round(1.0 / (60 + pos), 4)
    return out


_VIGENTE_HOJE = "m.status='ativa'"
# como o cérebro estava numa data: gravada até lá e ainda não substituída nem revogada naquela data (proposta fica fora)
_VIGENTE_EM = ("m.status<>'proposta' AND m.created_at <= %(em)s::timestamptz "
               "AND (m.substituida_em IS NULL OR m.substituida_em > %(em)s::timestamptz)")


def recall(q: str, k: int = 8, kind: str | None = None, em: str | None = None) -> list[dict]:
    """Memórias vigentes. `em` (data ISO) = o que o cérebro SABIA naquela data (linha de tempo do registro)."""
    emb = embed_one(q)
    sql = MEM_SQL.format(vigente=_VIGENTE_EM if em else _VIGENTE_HOJE)
    with pool().connection() as c:
        rows = c.execute(sql, {"emb": emb, "q": q, "k": k, "kind": kind, "em": em}).fetchall()
    return [{"id": r[0], "kind": r[1], "subject": r[2], "content": r[3], "source": r[4],
             "confidence": r[5], "created_at": r[6].isoformat(), "score": round(float(r[7]), 4),
             "chave": r[8], "valeu_de": r[9].isoformat() if r[9] else None,
             "valeu_ate": r[10].isoformat() if r[10] else None, "prova_doc": r[11]}
            for r in rows]


KINDS = ("episodica", "semantica", "procedural", "decisoria", "experiencial", "identidade")


def _numeros(texto: str) -> frozenset:
    import re as _re
    return frozenset(_re.findall(r"\d+", (texto or "").replace(".", "").replace(",", "")))


def remember(content: str, kind: str = "semantica", subject: str | None = None,
             source: str = "desconhecido", confidence: float = 0.8,
             supersedes: int | None = None, tags: list[str] | None = None, *,
             chave: str | None = None, valeu_de: str | None = None, valeu_ate: str | None = None,
             prova_doc: str | None = None, prova_trecho: str | None = None, proposta: bool = False) -> dict:
    """Grava um fato. `chave` estável: mesma chave + texto novo SUBSTITUI a versão ativa (a antiga fica, com a data em
    que deixou de valer no registro). `valeu_de/valeu_ate`: quando o fato valeu NO MUNDO. `prova_doc` + `prova_trecho`:
    documento primário e trecho literal (o hash do trecho é calculado aqui). `proposta`: entra na fila de revisão
    (status 'proposta'), fora do recall, e não substitui nada."""
    if kind not in KINDS:
        raise ValueError(f"kind deve ser um de {KINDS}")
    emb = embed_one(f"{subject or ''} {content}")
    prova_hash = hashlib.sha256(prova_trecho.encode()).hexdigest() if prova_trecho else None
    with pool().connection() as c, c.transaction():
        if chave and not proposta:
            ant = c.execute("SELECT id, content FROM memories WHERE chave=%s AND status='ativa'", (chave,)).fetchone()
            if ant and " ".join(ant[1].split()) == " ".join(content.split()):
                return {"status": "duplicada", "id": ant[0], "existente": ant[1]}
            if ant:
                supersedes = ant[0]
        # 14/11/2026: semelhança alta não basta — fatos estruturados (fornecedor/CNPJ/valor/processo) têm texto quase
        # igual e números diferentes; fundi-los fazia a correção de um substituir a memória do outro. Duplicada só se
        # os números dos dois textos forem os mesmos. Com `chave`, quem decide é a chave (acima), não a semelhança.
        if not chave and not proposta:
            dups = c.execute(
                "SELECT id, content FROM memories WHERE status='ativa' AND 1-(emb <=> %s) > 0.96 "
                "ORDER BY emb <=> %s LIMIT 5", (emb, emb)).fetchall()
            dup = next((d for d in dups if _numeros(d[1]) == _numeros(content)), None)
            if dup and not supersedes:
                return {"status": "duplicada", "id": dup[0], "existente": dup[1]}
        if supersedes and not proposta:      # antes do INSERT: o índice único permite uma só versão ativa por chave
            c.execute("UPDATE memories SET status='substituida', valid_to=now(), substituida_em=now() WHERE id=%s",
                      (supersedes,))
        mid = c.execute(
            "INSERT INTO memories(kind,subject,content,source,confidence,supersedes,tags,emb,status,chave,valeu_de,"
            "valeu_ate,prova_doc,prova_trecho,prova_hash) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
            (kind, subject, content, source, confidence, supersedes, tags or [], emb,
             "proposta" if proposta else "ativa", None if proposta else chave, valeu_de, valeu_ate,
             prova_doc, prova_trecho, prova_hash)).fetchone()[0]
        if subject:
            c.execute("INSERT INTO edges(src,dst,rel,origin) VALUES (%s,%s,'memoria','memory') "
                      "ON CONFLICT DO NOTHING", (subject.lower(), f"mem:{mid}"))
        if not proposta:
            N.gravar_mencoes(c, f"mem:{mid}", f"{subject or ''} {content}")
        c.execute("INSERT INTO events(actor,action,detail) VALUES (%s,'remember',%s::jsonb)",
                  (source, f'{{"id": {mid}, "kind": "{kind}"}}'))
    return {"status": "proposta" if proposta else "gravada", "id": mid, "substituiu": None if proposta else supersedes}


def historico(ref: str) -> list[dict]:
    """Todas as versões de um fato, da mais nova à mais antiga. `ref` = chave ou id de qualquer versão."""
    with pool().connection() as c:
        if ref.isdigit():
            ids = [int(ref)]
        else:
            ids = [r[0] for r in c.execute("SELECT id FROM memories WHERE chave=%s ORDER BY id DESC LIMIT 1", (ref,))]
        rows = c.execute("""
          WITH RECURSIVE v(id) AS (
            SELECT unnest(%(ids)s::bigint[])
            UNION SELECT m.supersedes FROM memories m JOIN v ON m.id=v.id WHERE m.supersedes IS NOT NULL
            UNION SELECT m.id FROM memories m JOIN v ON m.supersedes=v.id)
          SELECT m.id, m.status, m.content, m.source, m.created_at, m.substituida_em, m.valeu_de, m.valeu_ate,
                 m.chave, m.prova_doc, m.prova_trecho, m.supersedes
          FROM memories m JOIN v ON v.id=m.id ORDER BY m.id DESC""", {"ids": ids}).fetchall()
    iso = lambda d: d.isoformat() if d else None  # noqa: E731
    return [{"id": r[0], "status": r[1], "content": r[2], "source": r[3], "registrado_de": iso(r[4]),
             "registrado_ate": iso(r[5]), "valeu_de": iso(r[6]), "valeu_ate": iso(r[7]), "chave": r[8],
             "prova_doc": r[9], "prova_trecho": r[10], "supersedes": r[11]} for r in rows]


def entity(ref: str, com: str | None = None, tipo: str | None = None) -> dict:
    with pool().connection() as c:
        return N.entidade(c, ref, com=com, tipo=tipo)


# memórias geradas em série (uma por processo/alerta/commit): texto parecido e números diferentes POR DESENHO —
# compará-las entre si só gera par falso
_SERIE = "^(pericia-agente|licao-pericia|alerta|conferencia-opus|commit|couto|emenda|sobrepreco|derivado):"


def similar_pairs(minimo: float = 0.90, limite: int = 200) -> list[dict]:
    """Pares de memórias ATIVAS muito parecidas (fora das séries) — insumo da consolidação: mesmo fato dito duas vezes,
    ou o mesmo fato com número diferente. Só lista; ninguém é fundido aqui."""
    with pool().connection() as c:
        rows = c.execute("""
          WITH m AS (SELECT id, kind, subject, content, chave, source, created_at, emb FROM memories
                     WHERE status='ativa' AND emb IS NOT NULL AND (chave IS NULL OR chave !~ %(serie)s))
          SELECT a.id, b.id, 1-(a.emb <=> b.emb) AS sim, a.kind, a.subject, a.content, a.chave, a.created_at,
                 b.kind, b.subject, b.content, b.chave, b.created_at
          FROM m a JOIN m b ON a.id < b.id
          WHERE 1-(a.emb <=> b.emb) >= %(min)s ORDER BY sim DESC LIMIT %(lim)s""",
                         {"serie": _SERIE, "min": minimo, "lim": limite}).fetchall()
    lado = lambda r, i: {"id": r[0 if i == 3 else 1], "kind": r[i], "subject": r[i + 1], "content": r[i + 2],  # noqa: E731
                         "chave": r[i + 3], "created_at": r[i + 4].isoformat()}
    return [{"sim": round(float(r[2]), 4), "a": lado(r, 3), "b": lado(r, 8)} for r in rows]


def proposals(limit: int = 50) -> list[dict]:
    """Fila de revisão: o que a consolidação PROPÔS e ninguém aceitou ainda."""
    with pool().connection() as c:
        rows = c.execute("SELECT id, kind, subject, content, source, created_at FROM memories WHERE status='proposta' "
                         "ORDER BY id DESC LIMIT %s", (limit,)).fetchall()
    return [{"id": r[0], "kind": r[1], "subject": r[2], "content": r[3], "source": r[4],
             "created_at": r[5].isoformat()} for r in rows]


def forget(mem_id: int, source: str = "desconhecido") -> dict:
    with pool().connection() as c:
        n = c.execute("UPDATE memories SET status='revogada', valid_to=now(), substituida_em=now() "
                      "WHERE id=%s AND status<>'revogada'",
                      (mem_id,)).rowcount
        c.execute("INSERT INTO events(actor,action,detail) VALUES (%s,'forget',%s::jsonb)",
                  (source, f'{{"id": {mem_id}}}'))
    return {"revogadas": n}


def get_note(ref: str) -> dict | None:
    with pool().connection() as c:
        r = c.execute(
            "SELECT id,source,path,title,tags,frontmatter,body,mtime FROM notes "
            "WHERE path=%s OR lower(slug)=lower(%s) OR lower(title)=lower(%s) "
            "ORDER BY (path=%s) DESC, source='vault' DESC LIMIT 1", (ref, ref, ref, ref)).fetchone()
        if not r:
            r = c.execute(
                "SELECT id,source,path,title,tags,frontmatter,body,mtime FROM notes "
                "ORDER BY similarity(f_unaccent(lower(title)), f_unaccent(lower(%s))) DESC LIMIT 1",
                (ref,)).fetchone()
    if not r:
        return None
    return {"id": r[0], "source": r[1], "path": r[2], "title": r[3], "tags": r[4],
            "frontmatter": r[5], "body": r[6], "mtime": r[7].isoformat() if r[7] else None}


def neighbors(ref: str, depth: int = 1, limit: int = 60) -> dict:
    root = slugify(ref)
    with pool().connection() as c:
        rows = c.execute("""
          WITH RECURSIVE walk(node, d) AS (
            SELECT %(r)s::text, 0
            UNION
            SELECT CASE WHEN lower(e.src)=w.node THEN lower(e.dst) ELSE lower(e.src) END, w.d+1
            FROM edges e JOIN walk w ON lower(e.src)=w.node OR lower(e.dst)=w.node
            WHERE w.d < %(d)s
          )
          SELECT DISTINCT e.src, e.dst, e.rel FROM edges e
          WHERE lower(e.src) IN (SELECT node FROM walk) OR lower(e.dst) IN (SELECT node FROM walk)
          LIMIT %(l)s""", {"r": root, "d": max(1, min(depth, 3)), "l": limit}).fetchall()
    return {"root": root, "edges": [{"src": a, "dst": b, "rel": r} for a, b, r in rows]}


def stats() -> dict:
    with pool().connection() as c:
        row = c.execute("""SELECT
          (SELECT count(*) FROM notes), (SELECT count(*) FROM chunks),
          (SELECT count(*) FROM chunks WHERE emb IS NULL), (SELECT count(*) FROM edges),
          (SELECT count(*) FROM memories WHERE status='ativa'),
          (SELECT max(indexed_at) FROM notes)""").fetchone()
        by = c.execute("SELECT source, count(*) FROM notes GROUP BY 1 ORDER BY 2 DESC").fetchall()
    return {"notas": row[0], "trechos": row[1], "sem_embedding": row[2], "arestas": row[3],
            "memorias_ativas": row[4], "ultima_indexacao": row[5].isoformat() if row[5] else None,
            "por_fonte": dict(by)}
