#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sei_direcionamento_llm — avalia DIRECIONAMENTO pelo LLM (gemini) ON-DEMAND, só nos TOP-SCORE.

A varredura barata (`tools/sei_direcionamento_varre`) já ranqueia os fornecedores por um SCORE heurístico
(recorrência + valor + red_flags + risco) em `sei_direcionamento`. ESTE módulo pega os TOP-SCORE e roda o
"cérebro" caro (`direcionamento_cerebro.avaliar_direcionamento`, gemini — tier de PRODUTO, não o do sweep)
sobre o DOSSIÊ consolidado das árvores do fornecedor (`data/sei_trees/`), persistindo o parecer ao lado da
linha de score. Assim o Lex/`/relatorio` faz SURFACE do veredito sem re-rodar o LLM a cada documento.

Por que ON-DEMAND e não em massa: o LLM forte é caro/limitado (free-tier). Avaliamos os poucos que importam
(maior indício acumulado), com CACHE (não reavalia <30 dias salvo --forcar). Honesto: indício a verificar,
nunca acusação; sem dossiê/sem texto de edital → 'dados insuficientes' (o cérebro nunca fabrica).

Uso:
    PYTHONPATH=. .venv/bin/python -m tools.sei_direcionamento_llm --top 10
    PYTHONPATH=. .venv/bin/python -m tools.sei_direcionamento_llm --cnpj 12345678000190 --forcar
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DB = REPO / "data" / "compliance.db"

# colunas do parecer LLM anexadas à linha de score (migração aditiva, idempotente)
_COLS_LLM = ("llm_grau TEXT", "llm_resumo TEXT", "llm_raciocinio TEXT", "llm_json TEXT",
             "llm_modelo TEXT", "llm_em TEXT")
_REAVALIAR_DIAS = 30          # cache: não reavalia se o parecer tem < 30 dias (salvo --forcar)
_MAX_TXT_ARVORE = 8000        # teto de texto por dossiê
_MAX_TXT_TOTAL = 24000        # teto somado (cabe no budget do cérebro)


def _conectar() -> sqlite3.Connection:
    con = sqlite3.connect(DB, timeout=30)
    con.execute("PRAGMA busy_timeout=30000")
    # a tabela já é criada por sei_direcionamento_varre; aqui só garantimos as colunas do parecer
    if con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='sei_direcionamento'").fetchone():
        cols = {r[1] for r in con.execute("PRAGMA table_info(sei_direcionamento)")}
        for c in _COLS_LLM:
            if c.split()[0] not in cols:
                con.execute(f"ALTER TABLE sei_direcionamento ADD COLUMN {c}")
    return con


def _texto_das_arvores(con: sqlite3.Connection, arvores: list[str]) -> str:
    """Concatena os DOSSIÊS consolidados (`sei_arvore.txt_path`) das árvores do fornecedor — é o melhor texto
    disponível (objeto, documentos, red flags, análise, pagamentos) p/ o cérebro raciocinar. Bounded."""
    partes: list[str] = []
    total = 0
    for numero in arvores:
        row = con.execute("SELECT txt_path FROM sei_arvore WHERE numero_sei=?", (numero,)).fetchone()
        if not row or not row[0]:
            continue
        p = Path(row[0])
        if not p.exists():
            continue
        try:
            t = p.read_text(encoding="utf-8")[:_MAX_TXT_ARVORE]
        except Exception:  # noqa: BLE001
            continue
        if total + len(t) > _MAX_TXT_TOTAL:
            t = t[: _MAX_TXT_TOTAL - total]
        partes.append(t)
        total += len(t)
        if total >= _MAX_TXT_TOTAL:
            break
    return "\n\n===== PRÓXIMA ÁRVORE =====\n\n".join(partes)


async def avaliar_fornecedor(cnpj: str, nome: str, arvores: list[str], *, gerar=None,
                             con: sqlite3.Connection | None = None) -> dict:
    """Roda o cérebro de direcionamento sobre o dossiê consolidado das árvores do fornecedor. `gerar`
    injetável (async(messages)->str) p/ teste sem rede; default = gemini (tier produto). Honesto: sem
    dossiê → 'dados insuficientes' (o próprio cérebro decide; não fabricamos)."""
    from compliance_agent.direcionamento_cerebro import avaliar_direcionamento
    _con = con or _conectar()
    try:
        texto = _texto_das_arvores(_con, arvores)
    finally:
        if con is None:
            _con.close()
    if not texto.strip():
        return {"grau": "indeterminado", "dados_suficientes": False, "fonte": "direcionamento_cerebro",
                "resumo": "Sem dossiê consolidado para as árvores deste fornecedor (nada a avaliar).",
                "ressalva": "INDISPONÍVEL ≠ irregular — rodar o sweep/sei_arvore_build antes."}
    contexto = {"fornecedor": nome, "cnpj": cnpj, "n_arvores": len(arvores),
                "nota": "texto = DOSSIÊ consolidado das árvores SEI do fornecedor (não o edital cru)"}
    # ELO CROSS-FORNECEDOR: padrões já aprendidos de fornecedores LIGADOS (mesmos sócios/veículos), via SQL
    # puro sobre vereditos persistidos — custo LLM 0 (reusa o MESMO cérebro gemini, sem 2ª chamada). Honesto:
    # '' em erro/sem-irmão. Anti-viés: o cérebro o trata como contexto a corroborar/contrastar, não culpa.
    try:
        from tools.lex_aprendizado_cruzado import aprendizado_cruzado
        _c2 = con or _conectar()
        try:
            padroes = aprendizado_cruzado(cnpj, _c2)
        finally:
            if con is None:
                _c2.close()
        if padroes:
            contexto["padroes_ligados"] = padroes
    except Exception:  # noqa: BLE001
        pass
    return await avaliar_direcionamento(edital_txt=texto, contexto=contexto, gerar=gerar)


def _persistir(con: sqlite3.Connection, cnpj: str, res: dict, modelo: str) -> None:
    con.execute(
        "UPDATE sei_direcionamento SET llm_grau=?, llm_resumo=?, llm_raciocinio=?, llm_json=?, "
        "llm_modelo=?, llm_em=datetime('now') WHERE fornecedor_cnpj=?",
        (str(res.get("grau") or ""), str(res.get("resumo") or ""), str(res.get("raciocinio") or ""),
         json.dumps(res, ensure_ascii=False), modelo, cnpj))
    con.commit()


def avaliar_top(top_n: int = 10, *, forcar: bool = False, min_score: int = 1, cnpj: str | None = None,
                gerar=None, modelo: str = "gemini") -> dict:
    """Seleciona os TOP-SCORE (ou um --cnpj) e roda o cérebro on-demand, persistindo o parecer. CACHE: pula
    quem tem parecer < 30 dias salvo `forcar`. Retorna {avaliados, pulados, top:[...]}."""
    if not DB.exists():
        return {"erro": "compliance.db ausente"}
    con = _conectar()
    if not con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='sei_direcionamento'").fetchone():
        con.close()
        return {"erro": "tabela sei_direcionamento ausente — rode sei_direcionamento_varre primeiro"}
    if cnpj:
        import re as _re
        cd = _re.sub(r"\D", "", cnpj)
        rows = con.execute(
            "SELECT fornecedor_cnpj, fornecedor_nome, arvores, score, llm_em FROM sei_direcionamento "
            "WHERE replace(replace(replace(fornecedor_cnpj,'.',''),'/',''),'-','')=?", (cd,)).fetchall()
    else:
        rows = con.execute(
            "SELECT fornecedor_cnpj, fornecedor_nome, arvores, score, llm_em FROM sei_direcionamento "
            "WHERE score>=? ORDER BY score DESC LIMIT ?", (min_score, top_n)).fetchall()
    avaliados = pulados = 0
    out: list[dict] = []
    import asyncio
    for fcnpj, fnome, arvjson, score, llm_em in rows:
        if llm_em and not forcar:
            try:
                from datetime import datetime
                if (datetime.now() - datetime.fromisoformat(llm_em.replace("Z", ""))).days < _REAVALIAR_DIAS:
                    pulados += 1
                    continue
            except (ValueError, TypeError):
                pass
        try:
            arvores = json.loads(arvjson or "[]")
        except Exception:  # noqa: BLE001
            arvores = []
        res = asyncio.run(avaliar_fornecedor(fcnpj, fnome or "", arvores, gerar=gerar, con=con))
        _persistir(con, fcnpj, res, modelo)
        avaliados += 1
        out.append({"cnpj": fcnpj, "nome": fnome, "score": score,
                    "grau": res.get("grau"), "resumo": (res.get("resumo") or "")[:160]})
    con.close()
    return {"avaliados": avaliados, "pulados": pulados, "top": out}


def parecer_fornecedor(cnpj: str) -> dict | None:
    """Lê o parecer LLM de direcionamento já persistido p/ o fornecedor (SURFACE no Lex/relatorio).
    Retorna None se não houver tabela/coluna/linha/parecer. Honesto: não dispara LLM aqui (só leitura)."""
    if not DB.exists():
        return None
    import re as _re
    cd = _re.sub(r"\D", "", cnpj or "")
    if not cd:
        return None
    con = sqlite3.connect(DB, timeout=30)
    con.execute("PRAGMA busy_timeout=30000")
    try:
        cols = {r[1] for r in con.execute("PRAGMA table_info(sei_direcionamento)")}
        if "llm_json" not in cols:
            return None
        row = con.execute(
            "SELECT fornecedor_nome, score, llm_grau, llm_resumo, llm_raciocinio, llm_json, llm_modelo, llm_em "
            "FROM sei_direcionamento WHERE replace(replace(replace(fornecedor_cnpj,'.',''),'/',''),'-','')=?",
            (cd,)).fetchone()
    except sqlite3.Error:
        return None
    finally:
        con.close()
    if not row or not row[5]:   # sem llm_json = ainda não avaliado on-demand
        return None
    try:
        detalhe = json.loads(row[5])
    except Exception:  # noqa: BLE001
        detalhe = {}
    return {"nome": row[0], "score": row[1], "grau": row[2] or detalhe.get("grau") or "",
            "resumo": row[3] or "", "raciocinio": row[4] or "", "detalhe": detalhe,
            "modelo": row[6] or "", "avaliado_em": row[7] or ""}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--top", type=int, default=10, help="quantos top-score avaliar")
    ap.add_argument("--min-score", type=int, default=1, help="score mínimo p/ entrar na avaliação")
    ap.add_argument("--cnpj", type=str, default=None, help="avalia só este fornecedor (ignora --top)")
    ap.add_argument("--forcar", action="store_true", help="reavalia mesmo com parecer recente (<30d)")
    a = ap.parse_args()
    r = avaliar_top(top_n=a.top, forcar=a.forcar, min_score=a.min_score, cnpj=a.cnpj)
    if r.get("erro"):
        print(f"[sei_direc_llm] ERRO: {r['erro']}")
        return 1
    print(f"[sei_direc_llm] avaliados={r['avaliados']} · pulados(cache)={r['pulados']}")
    for x in r.get("top", []):
        print(f"  grau={str(x['grau']).upper():<13} score={x['score']:>3} · {x['nome']} ({x['cnpj']})")
        if x.get("resumo"):
            print(f"      {x['resumo']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
