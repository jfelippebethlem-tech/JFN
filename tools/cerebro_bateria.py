# -*- coding: utf-8 -*-
"""Bateria de RECALL do segundo cérebro — mede se a nota certa volta quando se pergunta como o dono pergunta.

Fonte das perguntas: config/cerebro_bateria.yaml (20 literais do dono, gabarito pré-registrado em 14/11/2026, +
perguntas sobre notas de ~/vault/casos com trecho literal esperado). Desenho e critérios de pronto por fase:
docs/ARQUITETURA-SEGUNDO-CEREBRO-ALVO.md §7.

Medida: posição da primeira nota do gabarito entre as NOTAS distintas devolvidas → recall@1/5/10 e MRR@10, por
sistema e por grupo. Sistema fora do ar aparece como INDISPONÍVEL (nunca como recall 0).

    python tools/cerebro_bateria.py validar            # o gabarito existe e contém o trecho esperado?
    python tools/cerebro_bateria.py medir [--sistemas brain,khoj,fundido] [--rotulo base] [--minimo 53]
    python tools/cerebro_bateria.py ultimo             # tabela da última medição

Saída: data/cerebro_bateria/ultimo.json (regravado a cada medição — é o `efeito` do derivado na propagação) e
data/cerebro_bateria/historico.jsonl (uma linha por medição, só os placares). Sem LLM, sem API paga, só leitura.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from compliance_agent import cerebro_busca as B          # noqa: E402
from compliance_agent import cerebro_compartilhado as C  # noqa: E402

BATERIA = RAIZ / "config" / "cerebro_bateria.yaml"
SAIDA = C.DATA / "cerebro_bateria"
KS = (1, 5, 10)


def _notas(itens: list[str], n: int = 10) -> list[str]:
    out: list[str] = []
    for x in itens:
        if x and x not in out:
            out.append(x)
    return out[:n]


def _brain(q: str, k: int) -> list[str]:
    return _notas([r["path"] if r["source"] == "vault" else f"{r['source']}:{r['path']}" for r in C.buscar(q, k=k)])


def _mcp(ferramenta: str, argumentos: dict):
    """Chama o MCP do jfn-brain como um agente chama (JSON-RPC em /mcp/) — mede o caminho do Yoda e do Claude web."""
    import urllib.error
    import urllib.request
    req = urllib.request.Request(
        C.URL + "/mcp/", method="POST",
        data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                         "params": {"name": ferramenta, "arguments": argumentos}}).encode(),
        headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream"})
    try:
        with urllib.request.urlopen(req, timeout=C.TETO_S) as r:
            res = json.loads(r.read().decode("utf-8"))["result"]
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, KeyError) as exc:
        raise C.CerebroIndisponivel(f"mcp: {type(exc).__name__}: {exc}") from exc
    if res.get("isError"):
        raise C.CerebroIndisponivel(f"mcp {ferramenta}: {str(res.get('content'))[:120]}")
    sc = res.get("structuredContent")
    return sc.get("result", sc) if isinstance(sc, dict) else sc


def _brain_mcp(q: str) -> list[str]:
    return _notas([r["path"] if r["source"] == "vault" else f"{r['source']}:{r['path']}"
                   for r in _mcp("brain_search", {"query": q, "k": 10})])


# Cada sistema: pergunta → até 10 notas distintas, em ordem.
SISTEMAS = {
    # como o agente recebe hoje: 10 TRECHOS do cérebro (várias vezes da mesma nota)
    "brain": lambda q: _brain(q, 10),
    # teto do cérebro como está: 40 trechos reduzidos a 10 notas
    "brain_k40": lambda q: _brain(q, 40),
    # o que o agente recebe pelo MCP (`brain_search`, k=10) — é o critério de pronto da fase 2
    "brain_mcp": _brain_mcp,
    "khoj": lambda q: _notas([x["nota"] for x in B._perna_khoj(q)]),
    "local_bm25": lambda q: _notas([x["nota"] for x in B._perna_local(q)]),
    # fase 1: entidade + BM25 local dão a ordem; o cérebro resgata
    "fundido": lambda q: [f["nota"] for f in B.buscar_fundido(q, 10)["notas"]],
    "fundido_com_khoj": lambda q: [f["nota"] for f in B.buscar_fundido(q, 10, com=("khoj",))["notas"]],
}
PADRAO = ("brain", "brain_mcp", "local_bm25", "fundido")


def _bateria() -> dict:
    return yaml.safe_load(BATERIA.read_text(encoding="utf-8"))


def carregar() -> list[dict]:
    return _bateria()["perguntas"]


def validar() -> list[str]:
    """Problemas do GABARITO (não do buscador): nota que não existe, trecho esperado que não está na nota."""
    erros, ids = [], set()
    for p in carregar():
        if p["id"] in ids:
            erros.append(f"{p['id']}: id repetido")
        ids.add(p["id"])
        existentes = [B.VAULT / n for n in p["ok"] if (B.VAULT / n).is_file()]
        if not existentes:
            erros.append(f"{p['id']}: nenhuma nota do gabarito existe no vault ({p['ok']})")
            continue
        lit = p.get("contem")
        if lit and not any(lit in a.read_text(encoding="utf-8", errors="replace") for a in existentes):
            erros.append(f"{p['id']}: trecho esperado {lit!r} não está em {p['ok']}")
    return erros


def _placar(linhas: list[dict], sistema: str) -> dict:
    medidas = [l[sistema] for l in linhas if sistema in l and l[sistema].get("erro") is None]
    falhas = sum(1 for l in linhas if sistema in l and l[sistema].get("erro") is not None)
    n = len(medidas)
    if not n:
        return {"n": 0, "indisponivel": falhas}
    pos = [m["posicao"] for m in medidas]
    tempos = sorted(m["s"] for m in medidas)
    out = {"n": n, "indisponivel": falhas,
           "mrr10": round(sum(1 / p for p in pos if p) / n, 3),
           "mediana_s": round(statistics.median(tempos), 2), "max_s": round(tempos[-1], 2)}
    for k in KS:
        out[f"recall{k}"] = sum(1 for p in pos if p and p <= k)
    return out


def medir(sistemas: tuple[str, ...], rotulo: str) -> dict:
    erros = validar()
    if erros:
        raise SystemExit("GABARITO INVÁLIDO — conserte antes de medir:\n  " + "\n  ".join(erros))
    perguntas = carregar()
    ignorar = set(_bateria().get("ignorar") or [])       # notas que transcrevem as perguntas (ver o yaml)
    B.indexar(forcar=True)
    linhas = []
    for p in perguntas:
        linha = {"id": p["id"], "grupo": p["grupo"], "pergunta": p["pergunta"], "ok": p["ok"]}
        for s in sistemas:
            t = time.time()
            try:
                notas = [n for n in SISTEMAS[s](p["pergunta"]) if n not in ignorar]
                pos = next((i + 1 for i, n in enumerate(notas) if n in p["ok"]), None)
                linha[s] = {"posicao": pos, "s": round(time.time() - t, 3), "top": notas[:5], "erro": None}
            except C.CerebroIndisponivel as exc:
                linha[s] = {"posicao": None, "s": round(time.time() - t, 3), "top": [], "erro": str(exc)[:160]}
        linhas.append(linha)
    grupos = sorted({l["grupo"] for l in linhas})
    placar = {s: {"total": _placar(linhas, s), **{g: _placar([l for l in linhas if l["grupo"] == g], s) for g in grupos}}
              for s in sistemas}
    res = {"rotulo": rotulo, "medido_em": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "perguntas": len(linhas),
           "estado": "VERIFICADO" if all(placar[s]["total"]["indisponivel"] == 0 for s in sistemas) else "PARCIAL",
           "placar": placar, "linhas": linhas}
    SAIDA.mkdir(parents=True, exist_ok=True)
    (SAIDA / "ultimo.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    with (SAIDA / "historico.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({k: res[k] for k in ("rotulo", "medido_em", "perguntas", "estado", "placar")},
                           ensure_ascii=False) + "\n")
    return res


def tabela(res: dict) -> str:
    out = [f"Bateria do segundo cérebro — {res['perguntas']} perguntas · {res['medido_em']} · {res['rotulo']} · "
           f"{res['estado']}", "",
           f"{'sistema':20s} {'grupo':6s} {'n':>3s} {'R@1':>5s} {'R@5':>5s} {'R@10':>5s} {'MRR@10':>7s} {'med s':>6s} {'máx s':>6s}"]
    for s, por in res["placar"].items():
        for g, m in por.items():
            if not m["n"]:
                out.append(f"{s:20s} {g:6s}   0   INDISPONÍVEL ({m['indisponivel']} consultas sem resposta)")
                continue
            aviso = f"  ({m['indisponivel']} indisponíveis)" if m["indisponivel"] else ""
            out.append(f"{s:20s} {g:6s} {m['n']:3d} {m['recall1']:5d} {m['recall5']:5d} {m['recall10']:5d} "
                       f"{m['mrr10']:7.3f} {m['mediana_s']:6.2f} {m['max_s']:6.2f}{aviso}")
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Bateria de recall do segundo cérebro")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("validar")
    m = sub.add_parser("medir")
    m.add_argument("--sistemas", default=",".join(PADRAO))
    m.add_argument("--rotulo", default="rotina")
    m.add_argument("--minimo", type=int, default=0,
                   help="catraca: sai com erro se o recall@10 do `fundido` ficar abaixo deste nº de perguntas")
    sub.add_parser("ultimo")
    a = ap.parse_args(argv)
    if a.cmd == "validar":
        erros = validar()
        print("\n".join(erros) if erros else f"gabarito ok — {len(carregar())} perguntas")
        return 1 if erros else 0
    if a.cmd == "medir":
        sist = tuple(s for s in a.sistemas.split(",") if s)
        desconhecidos = [s for s in sist if s not in SISTEMAS]
        if desconhecidos:
            ap.error(f"sistema desconhecido: {desconhecidos} (há: {', '.join(SISTEMAS)})")
        res = medir(sist, a.rotulo)
        print(tabela(res))
        f = res["placar"].get("fundido", {}).get("total", {})
        if a.minimo and (not f.get("n") or f["indisponivel"] or f["recall10"] < a.minimo):
            print(f"CATRACA: recall@10 do fundido = {f.get('recall10', 'INDISPONÍVEL')} de {res['perguntas']} "
                  f"(mínimo {a.minimo}) — a busca do cérebro piorou ou não respondeu.", file=sys.stderr)
            return 1
        return 0
    print(tabela(json.loads((SAIDA / "ultimo.json").read_text(encoding="utf-8"))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
