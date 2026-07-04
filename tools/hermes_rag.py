#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RAG do Hermes (it-campo/desktop) — "segundo cerebro" consultavel (Lei 14.133, sancoes, vault).

ADAPTADO DO ORIGINAL DA VM (jfn-core) para o desktop:
  - Embeddings: OLLAMA LOCAL `nomic-embed-text` (768d) em vez de Cohere — $0, sem rate-limit, offline.
  - Paths Windows (C:\\JFN\\jfn, C:\\Users\\iterj\\vault).
  - Resto (chunk, cosine numpy, tiers, corpus_hash/build_se_mudou) = igual ao da VM.
Vetor: matriz numpy + cosine (corpus pequeno -> brute-force instantaneo).

Uso:
  python tools/hermes_rag.py build              # (re)indexa o corpus -> data/rag/
  python tools/hermes_rag.py build --se-mudou   # rebuild so se o corpus mudou (p/ o ciclo diario)
  python tools/hermes_rag.py query "pergunta"   # top-k trechos relevantes
Import:
  from tools.hermes_rag import consultar, contexto
"""
from __future__ import annotations
import json
import os
import re
import sys
import glob
from pathlib import Path

REPO = Path(r"C:\JFN\jfn")
VAULT = Path(r"C:\Users\iterj\vault")
RAGDIR = REPO / "data" / "rag"
EMB = RAGDIR / "embeddings.npy"
CHUNKS = RAGDIR / "chunks.jsonl"
HASH = RAGDIR / "corpus_hash.txt"

# Embeddings LOCAIS via Ollama (GPU) — substitui Cohere (regra da VM: adaptar ao ambiente do desktop).
EMB_MODEL = os.environ.get("RAG_EMBED_MODEL", "nomic-embed-text")
OLLAMA_EMB = os.environ.get("OLLAMA_EMB_URL", "http://localhost:11434/api/embed")

# Fontes do corpus. Vault sincronizado = "segundo cerebro"; os VEREDITOS que a VM produz entram aqui.
FONTES = [
    str(REPO / "docs" / "lex_base" / "*.txt"),
    str(REPO / "docs" / "lex_base" / "*.md"),
    str(REPO / "docs" / "*.md"),
    str(VAULT / "**" / "*.md"),
]


def _embed(textos: list[str], input_type: str = "") -> list[list[float]]:
    """Embeddings via Ollama local (nomic-embed-text). input_type ignorado (era coisa da Cohere)."""
    import urllib.request
    out: list[list[float]] = []
    total = (len(textos) + 63) // 64
    for n, i in enumerate(range(0, len(textos), 64), 1):
        lote = textos[i:i + 64]
        data = json.dumps({"model": EMB_MODEL, "input": lote}).encode("utf-8")
        req = urllib.request.Request(OLLAMA_EMB, data=data, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                j = json.loads(r.read().decode("utf-8"))
            out.extend(j.get("embeddings", []))
        except Exception as e:
            raise SystemExit(f"Falha no embed local (Ollama {EMB_MODEL}): {e}. "
                             f"Rode: ollama pull {EMB_MODEL}  e confira o Ollama no ar.")
        if total > 1 and n % 20 == 0:
            print(f"  embed {n}/{total} lotes...", flush=True)
    return out


def _chunk(texto: str, alvo: int = 1100, overlap: int = 150) -> list[str]:
    paras = [p.strip() for p in re.split(r"\n\s*\n", texto) if p.strip()]
    chunks, buf = [], ""
    for p in paras:
        if len(buf) + len(p) + 2 <= alvo:
            buf = f"{buf}\n\n{p}" if buf else p
        else:
            if buf:
                chunks.append(buf)
            buf = (buf[-overlap:] + "\n\n" + p) if buf and len(p) < alvo else p
            while len(buf) > alvo:
                chunks.append(buf[:alvo]); buf = buf[alvo - overlap:]
    if buf:
        chunks.append(buf)
    return [c for c in chunks if len(c) > 60]


def _arquivos_corpus() -> list[str]:
    arquivos: list[str] = []
    for padrao in FONTES:
        arquivos.extend(glob.glob(padrao, recursive=True))
    return sorted(set(arquivos))


def corpus_hash() -> str:
    """Impressao digital barata do corpus (caminho+mtime+tamanho) — detecta mudanca sem ler conteudo."""
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
        fonte = fp.replace(str(VAULT), "vault").replace(str(REPO), "JFN")
        for j, ch in enumerate(_chunk(txt)):
            registros.append({"fonte": fonte, "i": j, "texto": ch})
    if not registros:
        print(f"Corpus vazio (0 arquivos em {[f for f in FONTES]}). Nada a indexar.")
        return
    print(f"{len(arquivos)} arquivos -> {len(registros)} chunks. Embeddando (Ollama {EMB_MODEL})...", flush=True)
    vecs = _embed([r["texto"] for r in registros], "search_document")
    arr = np.asarray(vecs, dtype="float32")
    arr /= (np.linalg.norm(arr, axis=1, keepdims=True) + 1e-9)
    np.save(EMB, arr)
    with open(CHUNKS, "w", encoding="utf-8") as f:
        for r in registros:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    HASH.write_text(corpus_hash())
    print(f"OK: {arr.shape[0]} vetores ({arr.shape[1]}d) -> {EMB}")


def build_se_mudou() -> bool:
    """Reindexa so se o corpus mudou. Retorna True se rebuildou (p/ o ciclo diario)."""
    if not corpus_mudou():
        print("RAG em dia — corpus nao mudou desde a ultima build.")
        return False
    build()
    return True


def consultar(pergunta: str, k: int = 6) -> list[dict]:
    import numpy as np
    if not EMB.exists():
        raise SystemExit("Indice ausente — rode: python tools/hermes_rag.py build")
    arr = np.load(EMB)
    regs = [json.loads(l) for l in open(CHUNKS, encoding="utf-8")]
    q = np.asarray(_embed([pergunta], "search_query")[0], dtype="float32")
    q /= (np.linalg.norm(q) + 1e-9)
    scores = arr @ q
    idx = np.argsort(-scores)[:k]
    return [{"score": float(scores[i]), "fonte": regs[i]["fonte"], "texto": regs[i]["texto"]} for i in idx]


def contexto(pergunta: str, k: int = 10, max_chars: int = 4000, *,
             k_full: int = 4, piso: float = 0.28, snippet_chars: int = 180) -> str:
    """String pronta p/ injetar no prompt — progressive disclosure (tiers). Identico a versao da VM."""
    hits = consultar(pergunta, k)
    if not hits:
        return ""
    fortes = [h for h in hits if h["score"] >= piso] or hits[:1]
    full, indice = fortes[:k_full], fortes[k_full:]
    full_budget = int(max_chars * 0.75)
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
        partes.append("OUTROS TRECHOS RELEVANTES (indice; aprofunde se a pergunta exigir):\n" + "\n".join(linhas))
    return "\n\n---\n\n".join(partes)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "build"
    if cmd == "build":
        build_se_mudou() if "--se-mudou" in sys.argv else build()
    elif cmd == "query":
        for h in consultar(" ".join(sys.argv[2:]) or "o que e repactuacao?", k=6):
            print(f"\n[{h['score']:.3f}] {h['fonte']}\n{h['texto'][:400]}...")
    else:
        print(__doc__)
