#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RAG do Hermes — "segundo cérebro" consultável (Lei 14.133, sanções, métodos de fraude, + vault).

Embeddings: Cohere REST (embed-multilingual-v3.0, 1024d) — chave em ~/.hermes/.env (NUNCA no código).
Vetor: matriz numpy + cosine (sem sqlite-vec/faiss; corpus pequeno → brute-force é instantâneo na VM).
Jina NÃO é usado (regra do dono: só com permissão explícita) — Cohere é o substituto.

Uso:
  python tools/hermes_rag.py build              # (re)indexa o corpus → data/rag/
  python tools/hermes_rag.py query "pergunta"   # top-k trechos relevantes
Import:
  from tools.hermes_rag import consultar; consultar("pergunta", k=6) -> list[dict]
"""
from __future__ import annotations
import json
import os
import re
import sys
import glob
from pathlib import Path

REPO = Path("/home/ubuntu/JFN")
RAGDIR = REPO / "data" / "rag"
EMB = RAGDIR / "embeddings.npy"
CHUNKS = RAGDIR / "chunks.jsonl"
MODEL = "embed-multilingual-v3.0"
COHERE = "https://api.cohere.com/v2/embed"

# Fontes do corpus (normas + conhecimento). Vault = "segundo cérebro" (dá ao Yoda leitura via RAG).
FONTES = [
    str(REPO / "docs/lex_base/*.txt"),
    str(REPO / "docs/lex_base/*.md"),
    str(REPO / "docs/*.md"),
    "/home/ubuntu/vault/**/*.md",
]


def _key() -> str:
    for env in (Path("/home/ubuntu/.hermes/.env"), REPO / ".env"):
        if env.exists():
            m = re.search(r"^COHERE_API_KEY=(.+)$", env.read_text(), re.M)
            if m:
                return m.group(1).strip().strip('"').strip("'")
    raise SystemExit("COHERE_API_KEY ausente (~/.hermes/.env)")


def _embed(textos: list[str], input_type: str) -> list[list[float]]:
    """Cohere embed em lotes de 96. Throttle + retry no 429 (chave trial tem limite/min)."""
    import httpx
    import time
    key = _key()
    out: list[list[float]] = []
    total = (len(textos) + 95) // 96
    for n, i in enumerate(range(0, len(textos), 96), 1):
        lote = textos[i:i + 96]
        for tent in range(6):
            r = httpx.post(COHERE, headers={"Authorization": f"Bearer {key}"},
                           json={"model": MODEL, "input_type": input_type,
                                 "embedding_types": ["float"], "texts": lote}, timeout=120)
            if r.status_code == 429:
                espera = min(60, 8 * (tent + 1))
                print(f"  lote {n}/{total}: 429, aguardando {espera}s…", flush=True)
                time.sleep(espera); continue
            r.raise_for_status()
            out.extend(r.json()["embeddings"]["float"])
            break
        else:
            raise SystemExit("Cohere 429 persistente — tente de novo mais tarde (limite da chave trial).")
        if total > 1:
            time.sleep(7)  # respeita o rate-limit/min da chave trial
    return out


def _chunk(texto: str, alvo: int = 1100, overlap: int = 150) -> list[str]:
    """Quebra por parágrafos, agregando até ~alvo chars; overlap p/ não cortar contexto."""
    paras = [p.strip() for p in re.split(r"\n\s*\n", texto) if p.strip()]
    chunks, buf = [], ""
    for p in paras:
        if len(buf) + len(p) + 2 <= alvo:
            buf = f"{buf}\n\n{p}" if buf else p
        else:
            if buf:
                chunks.append(buf)
            buf = (buf[-overlap:] + "\n\n" + p) if buf and len(p) < alvo else p
            while len(buf) > alvo:  # parágrafo gigante → fatia dura
                chunks.append(buf[:alvo]); buf = buf[alvo - overlap:]
    if buf:
        chunks.append(buf)
    return [c for c in chunks if len(c) > 60]


HASH = RAGDIR / "corpus_hash.txt"


def _arquivos_corpus() -> list[str]:
    arquivos: list[str] = []
    for padrao in FONTES:
        arquivos.extend(glob.glob(padrao, recursive=True))
    return sorted(set(arquivos))


def corpus_hash() -> str:
    """Impressão digital barata do corpus (caminho+mtime+tamanho) — detecta mudança sem ler conteúdo."""
    import hashlib
    h = hashlib.sha256()
    for fp in _arquivos_corpus():
        try:
            st = os.stat(fp)
            h.update(f"{fp}|{int(st.st_mtime)}|{st.st_size}\n".encode())
        except OSError:
            continue
    return h.hexdigest()


def corpus_mudou() -> bool:
    """True se o corpus mudou desde a última build (ou se nunca houve build)."""
    if not EMB.exists() or not HASH.exists():
        return True
    return HASH.read_text().strip() != corpus_hash()


def build() -> None:
    import numpy as np
    RAGDIR.mkdir(parents=True, exist_ok=True)
    arquivos = _arquivos_corpus()
    registros = []
    for fp in arquivos:
        try:
            txt = Path(fp).read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        fonte = fp.replace("/home/ubuntu/", "~/")
        for j, ch in enumerate(_chunk(txt)):
            registros.append({"fonte": fonte, "i": j, "texto": ch})
    print(f"{len(arquivos)} arquivos → {len(registros)} chunks. Embeddando (Cohere)…", flush=True)
    vecs = _embed([r["texto"] for r in registros], "search_document")
    arr = np.asarray(vecs, dtype="float32")
    arr /= (np.linalg.norm(arr, axis=1, keepdims=True) + 1e-9)  # normaliza p/ cosine = dot
    np.save(EMB, arr)
    with open(CHUNKS, "w", encoding="utf-8") as f:
        for r in registros:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    HASH.write_text(corpus_hash())
    print(f"OK: {arr.shape[0]} vetores ({arr.shape[1]}d) → {EMB}")


def build_se_mudou() -> bool:
    """Reindexa só se o corpus mudou. Retorna True se rebuildou (p/ o ciclo diário)."""
    if not corpus_mudou():
        print("RAG em dia — corpus não mudou desde a última build.")
        return False
    build()
    return True


def consultar(pergunta: str, k: int = 6) -> list[dict]:
    """Retorna os k trechos mais relevantes do corpus p/ a pergunta (com fonte e score)."""
    import numpy as np
    if not EMB.exists():
        raise SystemExit("Índice ausente — rode: python tools/hermes_rag.py build")
    arr = np.load(EMB)
    regs = [json.loads(l) for l in open(CHUNKS, encoding="utf-8")]
    q = np.asarray(_embed([pergunta], "search_query")[0], dtype="float32")
    q /= (np.linalg.norm(q) + 1e-9)
    scores = arr @ q
    idx = np.argsort(-scores)[:k]
    return [{"score": float(scores[i]), "fonte": regs[i]["fonte"], "texto": regs[i]["texto"]} for i in idx]


def contexto(pergunta: str, k: int = 10, max_chars: int = 4000, *,
             k_full: int = 4, piso: float = 0.28, snippet_chars: int = 180) -> str:
    """String pronta p/ injetar no prompt do Hermes — progressive disclosure (tiers).

    Retrieval é local (custo zero); o gasto real é char no prompt. Então: pool largo
    (k) → gate de relevância (piso de score, corta ruído) → tier FULL (top k_full, texto
    completo) + tier ÍNDICE (cauda relevante vira snippet barato). Mesmo teto (max_chars):
    o full leva o grosso, o índice estende a cobertura por pouco. Nugget do claude-mem.
    """
    hits = consultar(pergunta, k)
    if not hits:
        return ""
    fortes = [h for h in hits if h["score"] >= piso] or hits[:1]  # nunca vazio se há hit
    full, indice = fortes[:k_full], fortes[k_full:]
    full_budget = int(max_chars * 0.75)  # o grosso vai p/ o texto completo; o resto p/ o índice
    partes, total = [], 0
    for h in full:
        bloco = f"[FONTE: {h['fonte']} · score {h['score']:.2f}]\n{h['texto']}"
        if partes and total + len(bloco) > full_budget:
            break
        partes.append(bloco); total += len(bloco)
    linhas = []
    for h in indice:
        snip = " ".join(h["texto"][:snippet_chars].split())
        linha = f"• [{h['fonte']} · {h['score']:.2f}] {snip}…"
        if total + len(linha) > max_chars:
            break
        linhas.append(linha); total += len(linha)
    if linhas:
        partes.append("OUTROS TRECHOS RELEVANTES (índice; aprofunde se a pergunta exigir):\n"
                      + "\n".join(linhas))
    return "\n\n---\n\n".join(partes)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "build"
    if cmd == "build":
        build_se_mudou() if "--se-mudou" in sys.argv else build()
    elif cmd == "query":
        for h in consultar(" ".join(sys.argv[2:]) or "o que é repactuação?", k=6):
            print(f"\n[{h['score']:.3f}] {h['fonte']}\n{h['texto'][:400]}…")
    else:
        print(__doc__)
