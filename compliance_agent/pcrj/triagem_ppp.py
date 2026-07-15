# -*- coding: utf-8 -*-
"""Triagem EM LOTE de PPPs/concessões municipais captadas, pela lente PPP.

Roda ``lente_ppp`` sobre cada projeto de PPP captado (CCPAR) — preferindo o edital
completo ingerido, senão o corpus do D.O. — e devolve uma lista **rankeada** por
gravidade. Cresce sozinha conforme mais PPPs entram na base. Determinístico e rápido
(sem rede): serve de triagem síncrona no menu (`/api/lista`).

Honestidade: indício ≠ acusação; cada item traz os flags com base legal (via
``lente_ppp``); projeto sem texto suficiente vira ``sem_dados`` (nunca 0 forçado).
"""
from __future__ import annotations

from . import db
from . import lente_ppp

_PESO = {"🔴 alto": 3, "🟡 médio": 2, "🟢 baixo": 1, "sem_dados": 0}


def _corpus_do_projeto(con, nome: str, slug: str) -> tuple[str, str]:
    """Retorna (corpus, fonte). Prefere o edital CCPAR ingerido; senão, atos do D.O."""
    eds = con.execute(
        "SELECT texto FROM pcrj_processo_doc WHERE numero_processo=? AND tipo='edital_ccpar' "
        "ORDER BY seq", (slug,)).fetchall()
    corpus_ed = "\n\n".join(r["texto"] for r in eds if r["texto"])
    if corpus_ed.strip():
        # sem cap: a lente é regex (barata) e cláusulas-chave (garantia FNS) ficam no fim da minuta
        return corpus_ed, "edital+anexos CCPAR (completo)"
    termos = [t for t in (nome, "Smart Hospital") if t]
    qs = " OR ".join("termo_busca LIKE ?" for _ in termos) or "1=0"
    rows = con.execute(
        f"SELECT texto FROM pcrj_doe_materia WHERE ({qs}) AND tipo IN ('ppp','edital','extrato_contrato')",
        [f"%{t}%" for t in termos]).fetchall()
    corpus = "\n\n".join(r["texto"] for r in rows if r["texto"])[:120_000]
    return corpus, "atos do D.O. Rio"


def triar_lote(db_path=None) -> dict:
    """Rankeia os projetos de PPP captados pela lente PPP. Retorna {itens, resumo, texto}."""
    db.inicializar(db_path)
    con = db.conectar(db_path)
    itens = []
    try:
        projetos = con.execute(
            "SELECT slug, nome, fase, valor_investimento FROM pcrj_ppp").fetchall()
        for p in projetos:
            corpus, fonte = _corpus_do_projeto(con, p["nome"], p["slug"])
            if not corpus.strip():
                itens.append({"slug": p["slug"], "nome": p["nome"], "fase": p["fase"],
                              "grau": "sem_dados", "n_flags": 0, "n_altas": 0,
                              "flags": [], "fonte": "sem texto captado"})
                continue
            lente = lente_ppp.analisar_ppp(corpus)
            itens.append({
                "slug": p["slug"], "nome": p["nome"], "fase": p["fase"],
                "grau": lente["grau"], "n_flags": lente["n_flags"], "n_altas": lente["n_altas"],
                "flags": [f["tipo"] for f in lente["flags"]], "fonte": fonte,
            })
        n_ppp_doe = con.execute(
            "SELECT COUNT(*) FROM pcrj_doe_materia WHERE tipo='ppp'").fetchone()[0]
    finally:
        con.close()

    itens.sort(key=lambda x: (_PESO.get(x["grau"], 0), x["n_altas"], x["n_flags"]), reverse=True)
    resumo = {"projetos": len(itens),
              "alto": sum(1 for i in itens if i["grau"] == "🔴 alto"),
              "medio": sum(1 for i in itens if i["grau"] == "🟡 médio"),
              "cobertura_doe_ppp": n_ppp_doe}

    linhas = [f"🏥 *Triagem de PPPs/concessões — Prefeitura do Rio* "
              f"({resumo['projetos']} projeto(s); {resumo['alto']} 🔴, {resumo['medio']} 🟡)"]
    for i in itens:
        flags = (", ".join(i["flags"][:4]) + ("…" if len(i["flags"]) > 4 else "")) or "—"
        linhas.append(f"{i['grau']}  *{i['nome']}* — {i['n_altas']} alta(s)/{i['n_flags']} flags "
                      f"[{flags}] · {i['fase'] or '?'} · fonte: {i['fonte']}")
    linhas.append("_Indício ≠ acusação; base legal por flag na lente. Dossiê completo: /ppp <projeto>._")

    return {"ok": True, "itens": itens, "resumo": resumo, "texto": "\n".join(linhas)}
