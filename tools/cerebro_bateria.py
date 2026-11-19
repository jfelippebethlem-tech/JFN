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


_mcp = C.mcp      # chama o MCP como um agente chama — mede o caminho do Yoda e do Claude web


def _brain_mcp(q: str) -> list[str]:
    return _notas([r["path"] if r["source"] == "vault" else f"{r['source']}:{r['path']}"
                   for r in _mcp("brain_search", {"query": q, "k": 10})])


def _brain_entity(p: dict):
    """Cruzamento por entidade (`brain_entity` do MCP). Só se aplica a pergunta que declara `entidade`."""
    if not p.get("entidade"):
        return None
    r = _mcp("brain_entity", p["entidade"])
    if r.get("erro"):
        raise C.CerebroIndisponivel(r["erro"])
    return _notas([n["path"] for n in r["notas"]])


# Cada sistema: pergunta → até 10 notas distintas, em ordem.
SISTEMAS = {
    # como o agente recebe hoje: 10 TRECHOS do cérebro (várias vezes da mesma nota)
    "brain": lambda q: _brain(q, 10),
    # teto do cérebro como está: 40 trechos reduzidos a 10 notas
    "brain_k40": lambda q: _brain(q, 40),
    # o que o agente recebe pelo MCP (`brain_search`, k=10) — é o critério de pronto da fase 2
    "brain_mcp": _brain_mcp,
    "brain_entity": _brain_entity,          # recebe a pergunta inteira; None = não se aplica
    "khoj": lambda q: _notas([x["nota"] for x in B._perna_khoj(q)]),
    "local_bm25": lambda q: _notas([x["nota"] for x in B._perna_local(q)]),
    # fase 1: entidade + BM25 local dão a ordem; o cérebro resgata
    "fundido": lambda q: [f["nota"] for f in B.buscar_fundido(q, 10)["notas"]],
    "fundido_com_khoj": lambda q: [f["nota"] for f in B.buscar_fundido(q, 10, com=("khoj",))["notas"]],
}
PADRAO = ("brain_mcp", "brain_entity", "local_bm25", "fundido")


def _bateria() -> dict:
    return yaml.safe_load(BATERIA.read_text(encoding="utf-8"))


def carregar() -> list[dict]:
    return _bateria()["perguntas"]


def _ha_ob_paga(sp: dict) -> bool:
    """Existe OB PAGA (filtro da casa: cruzamentos_intel._ob_paga) para o credor — e a UG, se dada? Base ausente
    (máquina sem o compliance.db) não reprova o gabarito: devolve True e a conferência fica para onde a base existe."""
    import sqlite3
    db = C.DATA / "compliance.db"
    if not db.exists():
        return True
    from compliance_agent.cruzamentos_intel import _ob_paga
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=30)
    try:
        d = sp["credor"]
        sql = f"SELECT 1 FROM ob_orcamentaria_siafe WHERE credor IN (?,?) AND {_ob_paga(con)}"
        args = [d, B.F.grafias("cnpj", d)[1]]
        if sp.get("ug"):
            sql, args = sql + " AND ug_emitente=?", args + [sp["ug"]]
        return con.execute(sql + " LIMIT 1", args).fetchone() is not None
    finally:
        con.close()


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
        sp = p.get("sql_pago")
        if sp and not _ha_ob_paga(sp):
            erros.append(f"{p['id']}: não há mais OB paga no SIAFE para {sp} — a resposta esperada caducou")
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
    # cobertura: das notas esperadas, quantas vieram entre as 10 (importa no cruzamento, onde `ok` é a lista inteira)
    out["achadas"] = sum(m["achadas"] for m in medidas)
    out["esperadas"] = sum(m["esperadas"] for m in medidas)
    out["completas"] = sum(1 for m in medidas if m["achadas"] == min(m["esperadas"], 10))
    return out


def medir(sistemas: tuple[str, ...], rotulo: str, grupos: tuple[str, ...] = ()) -> dict:
    erros = validar()
    if erros:
        raise SystemExit("GABARITO INVÁLIDO — conserte antes de medir:\n  " + "\n  ".join(erros))
    perguntas = [p for p in carregar() if not grupos or p["grupo"] in grupos]
    ignorar = set(_bateria().get("ignorar") or [])       # notas que transcrevem as perguntas (ver o yaml)
    B.indexar(forcar=True)
    linhas = []
    for p in perguntas:
        linha = {"id": p["id"], "grupo": p["grupo"], "pergunta": p["pergunta"], "ok": p["ok"]}
        for s in sistemas:
            t = time.time()
            try:
                bruto = SISTEMAS[s](p if s == "brain_entity" else p["pergunta"])
                if bruto is None:                       # sistema não se aplica a esta pergunta
                    continue
                notas = [n for n in bruto if n not in ignorar]
                pos = next((i + 1 for i, n in enumerate(notas) if n in p["ok"]), None)
                achadas = sum(1 for n in p["ok"] if n in notas)
                linha[s] = {"posicao": pos, "s": round(time.time() - t, 3), "top": notas[:5], "erro": None,
                            "achadas": achadas, "esperadas": len(p["ok"])}
            except C.CerebroIndisponivel as exc:
                linha[s] = {"posicao": None, "s": round(time.time() - t, 3), "top": [], "erro": str(exc)[:160]}
        linhas.append(linha)
    grupos = sorted({l["grupo"] for l in linhas})
    placar = {s: {g: m for g, m in (("total", _placar(linhas, s)),
                                    *((g, _placar([l for l in linhas if l["grupo"] == g], s)) for g in grupos))
                  if m["n"] or m["indisponivel"]} for s in sistemas}
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
           f"{'sistema':20s} {'grupo':10s} {'n':>3s} {'R@1':>5s} {'R@5':>5s} {'R@10':>5s} {'MRR@10':>7s} {'cobertura':>10s} {'med s':>6s}"]
    for s, por in res["placar"].items():
        for g, m in por.items():
            if not m["n"]:
                out.append(f"{s:20s} {g:10s}   0   INDISPONÍVEL ({m['indisponivel']} consultas sem resposta)")
                continue
            aviso = f"  ({m['indisponivel']} indisponíveis)" if m["indisponivel"] else ""
            out.append(f"{s:20s} {g:10s} {m['n']:3d} {m['recall1']:5d} {m['recall5']:5d} {m['recall10']:5d} "
                       f"{m['mrr10']:7.3f} {str(m['achadas']) + '/' + str(m['esperadas']):>10s} {m['mediana_s']:6.2f}{aviso}")
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Bateria de recall do segundo cérebro")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("validar")
    m = sub.add_parser("medir")
    m.add_argument("--sistemas", default=",".join(PADRAO))
    m.add_argument("--rotulo", default="rotina")
    m.add_argument("--grupos", default="", help="só estes grupos (dono,casos,cruzamento)")
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
        res = medir(sist, a.rotulo, tuple(g for g in a.grupos.split(",") if g))
        print(tabela(res))
        falhas = []
        for s in ("fundido", "brain_mcp"):           # catraca nas 56 perguntas de nota (grupos dono + casos)
            por = res["placar"].get(s)
            if a.minimo and por:
                r10 = sum(por.get(g, {}).get("recall10", 0) for g in ("dono", "casos"))
                if por["total"]["indisponivel"] or r10 < a.minimo:
                    falhas.append(f"{s}: recall@10 = {r10} (mínimo {a.minimo}; {por['total']['indisponivel']} sem resposta)")
        e = res["placar"].get("brain_entity", {}).get("cruzamento")
        if a.minimo and e and (e["indisponivel"] or e["achadas"] < 0.95 * e["esperadas"]):
            falhas.append(f"brain_entity: cobertura {e['achadas']}/{e['esperadas']} no cruzamento (mínimo 95%)")
        if falhas:
            print("CATRACA — a busca do cérebro piorou ou não respondeu: " + "; ".join(falhas), file=sys.stderr)
            return 1
        return 0
    print(tabela(json.loads((SAIDA / "ultimo.json").read_text(encoding="utf-8"))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
