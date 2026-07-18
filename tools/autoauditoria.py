#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""autoauditoria — harness de auto-melhoria dos detectores (adaptado de karpathy/autoresearch).

Filosofia autoresearch: 1 alvo mutável · 1 métrica única · orçamento FIXO · direção humana num
`program.md` (aqui `docs/PROGRAMA-AUTOAUDITORIA.md`) · histórico append-only. Aqui, seguindo o
princípio "jagged intelligence" do próprio Karpathy (LLM não faz otimização numérica), o loop
interno é DETERMINÍSTICO: varre uma grade de valores de UM parâmetro de UM detector e mede.

Dois modos:

  BASELINE (verificador barato, roda toda noite) — `fingerprint()` roda cada detector sobre o DB
  real e grava um retrato (n_achados, distribuição de score, top-CNPJs). Compara com a última
  execução e sinaliza DRIFT (um detector que muda de 40→400 achados = provável bug ou mudança de
  dado). É o "verificador é o gargalo" do Karpathy: barato, determinístico, pega regressão.

  SINTONIA (loop autoresearch) — `sintonizar(detector, param, grade)` varre a grade e, para cada
  valor, mede (a) os TESTES do detector continuam verdes? (b) quantos achados no DB real? Recomenda
  o valor MAIS CONSERVADOR (menos achados = menos FP) que ainda passa em TODOS os testes rotulados.
  Não edita código: recomenda; a aplicação é decisão humana/agente (autonomy slider).

Uso:
    python -m tools.autoauditoria baseline            # fingerprint + drift vs última noite
    python -m tools.autoauditoria sintonia            # roda as direções do program.md
    python -m tools.autoauditoria sintonia fracionamento min_colado 2 3 4 5
"""
from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_DB = str(_REPO / "data" / "compliance.db")
_HIST = _REPO / "data" / "autoauditoria"
_PROGRAMA = _REPO / "docs" / "PROGRAMA-AUTOAUDITORIA.md"

# detector → (função importável, chave da lista de achados, campo de score p/ histograma)
_DETECTORES = {
    "fracionamento": ("fracionamento", "grupos", "concentracao"),
    "sobrepreco": ("sobrepreco", "achados", "razao"),
    "socio_oculto": ("socio_oculto", "achados", "n_empresas"),
    "nepotismo": ("nepotismo", "achados", "n_membros"),
    "fornecedor_dependente": ("fornecedor_dependente", "achados", "share"),
    "corrida_dezembro": ("corrida_dezembro", "achados", "share"),
    "empresa_fenix": ("empresa_fenix", "achados", None),
    "porta_giratoria": ("porta_giratoria", "achados", None),
    "conluio_qsa": ("conluio_qsa", "pares", None),
    "radar_risco": ("radar_risco", "achados", "score"),
    "comunidades": ("comunidades", "comunidades", "score"),
}

# id p/ o top-N estável do fingerprint (o que muda entre noites)
_ID_KEYS = ("cnpj", "vencedor", "socio", "id", "certame")


def _chamar(nome: str, **kw):
    import compliance_agent.cruzamentos_intel as CI
    if nome == "comunidades":
        from compliance_agent.grafo_comunidades import detectar_comunidades
        return detectar_comunidades(incluir_grafo_d3=False, **kw)
    return getattr(CI, nome)(**kw)


def _id_de(item: dict) -> str:
    for k in _ID_KEYS:
        v = item.get(k)
        if isinstance(v, dict):
            v = v.get("cnpj")
        if v:
            return str(v)
    return json.dumps(item, sort_keys=True)[:40]


def fingerprint(db_path: str | None = None) -> dict:
    """Retrato determinístico de cada detector sobre o DB real (n, score, top-ids)."""
    out: dict[str, dict] = {}
    for nome, (fn, chave, campo) in _DETECTORES.items():
        try:
            d = _chamar(fn, db_path=db_path) if fn != "comunidades" else _chamar(fn, db_path=db_path)
        except TypeError:
            d = _chamar(fn)
        except Exception as exc:  # noqa: BLE001 — retrato honesto: erro é um estado
            out[nome] = {"erro": str(exc)[:80]}
            continue
        itens = d.get(chave) or []
        scores = [i.get(campo) for i in itens if campo and isinstance(i.get(campo), (int, float))]
        out[nome] = {
            "n": len(itens),
            "score_mediana": round(statistics.median(scores), 3) if scores else None,
            "score_max": round(max(scores), 3) if scores else None,
            "top": [_id_de(i) for i in itens[:10]],
        }
    return out


def _drift(antes: dict, agora: dict) -> list[dict]:
    """Compara dois fingerprints e lista mudanças materiais (por detector)."""
    alertas = []
    for nome, at in agora.items():
        an = antes.get(nome)
        if not an or "erro" in at or "erro" in an:
            if "erro" in at:
                alertas.append({"detector": nome, "tipo": "erro", "detalhe": at["erro"]})
            continue
        n0, n1 = an.get("n", 0), at.get("n", 0)
        if n0 == 0 and n1 == 0:
            continue
        var = (n1 - n0) / max(n0, 1)
        if abs(var) >= 0.5 and abs(n1 - n0) >= 5:      # ±50% E ≥5 achados = material
            alertas.append({"detector": nome, "tipo": "volume",
                            "detalhe": f"{n0}→{n1} ({var:+.0%})"})
        saiu = set(an.get("top", [])) - set(at.get("top", []))
        if len(saiu) >= 5:                              # metade do top-10 trocou
            alertas.append({"detector": nome, "tipo": "top_instavel",
                            "detalhe": f"{len(saiu)}/10 do topo saíram"})
    return alertas


def baseline(db_path: str | None = None, registrar: bool = True) -> dict:
    """Fingerprint atual + drift vs a última execução gravada. Grava no histórico append-only."""
    _HIST.mkdir(parents=True, exist_ok=True)
    atual = fingerprint(db_path)
    ultimo = None
    hist = sorted(_HIST.glob("fingerprint_*.json"))
    if hist:
        try:
            ultimo = json.loads(hist[-1].read_text())["fingerprint"]
        except (OSError, ValueError, KeyError):
            ultimo = None
    alertas = _drift(ultimo, atual) if ultimo else []
    reg = {"quando": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "fingerprint": atual, "drift": alertas,
           "comparado_com": hist[-1].name if hist else None}
    if registrar:
        stamp = reg["quando"].replace(":", "").replace("-", "")[:15]
        alvo = _HIST / f"fingerprint_{stamp}.json"
        i = 1
        while alvo.exists():                    # 2 execuções no mesmo segundo não se sobrescrevem
            alvo = _HIST / f"fingerprint_{stamp}_{i}.json"
            i += 1
        alvo.write_text(json.dumps(reg, ensure_ascii=False, indent=1))
    return reg


def _testes_verdes(expr: str) -> bool:
    """Roda `pytest -k <expr>` e devolve True se passou (nenhuma falha)."""
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-k", expr, "--no-header", "-p", "no:cacheprovider"],
        cwd=_REPO, capture_output=True, text=True, timeout=600)
    return r.returncode == 0


def sintonizar(detector: str, param: str, grade: list, testes_k: str | None = None) -> dict:
    """Loop autoresearch determinístico: varre a grade de `param`, mede n_achados no DB real e se
    os testes seguem verdes. Recomenda o valor MAIS CONSERVADOR (menos achados) que passa nos testes.
    Orçamento = len(grade) experimentos. Não edita código — recomenda (autonomy slider)."""
    if detector not in _DETECTORES:
        return {"ok": False, "erro": f"detector desconhecido: {detector}"}
    fn = _DETECTORES[detector][0]
    chave = _DETECTORES[detector][1]
    testes_k = testes_k or detector
    experimentos = []
    for v in grade:
        try:
            d = _chamar(fn, **{param: v})
            n = len(d.get(chave) or [])
        except Exception as exc:  # noqa: BLE001
            experimentos.append({"valor": v, "erro": str(exc)[:80]})
            continue
        verde = _testes_verdes(testes_k)
        experimentos.append({"valor": v, "n_achados": n, "testes_verdes": verde})
    validos = [e for e in experimentos if e.get("testes_verdes")]
    # mais conservador entre os que passam nos testes = menos achados (menos FP), desempata pelo
    # valor de threshold mais alto (mais exigente)
    recomendado = min(validos, key=lambda e: (e["n_achados"], -_num(e["valor"]))) if validos else None
    return {"ok": True, "detector": detector, "param": param,
            "experimentos": experimentos, "recomendado": recomendado,
            "nota": ("Recomendação = valor mais conservador que mantém TODOS os testes verdes. "
                     "Aplicar é decisão humana (autonomy slider). Menos achados ≠ sempre melhor: "
                     "conferir que não perdeu detecção real antes de aplicar.")}


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _ler_programa() -> list[dict]:
    """Direções de sintonia declaradas pelo humano em docs/PROGRAMA-AUTOAUDITORIA.md.
    Linhas: `- sintonia: <detector> <param> <v1> <v2> ...` (o resto é prosa p/ o humano)."""
    if not _PROGRAMA.exists():
        return []
    dirs = []
    for ln in _PROGRAMA.read_text().splitlines():
        ln = ln.strip()
        if ln.startswith("- sintonia:"):
            toks = ln.split(":", 1)[1].split()
            if len(toks) >= 3:
                dirs.append({"detector": toks[0], "param": toks[1],
                             "grade": [_int_ou_float(x) for x in toks[2:]]})
    return dirs


def _int_ou_float(s: str):
    try:
        return int(s)
    except ValueError:
        return float(s)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("modo", choices=["baseline", "sintonia"])
    ap.add_argument("resto", nargs="*")
    a = ap.parse_args()
    if a.modo == "baseline":
        r = baseline()
        print(f"fingerprint gravado. drift: {len(r['drift'])} alerta(s)")
        for al in r["drift"]:
            print(f"  ⚠️ {al['detector']}: {al['tipo']} — {al['detalhe']}")
    else:
        if len(a.resto) >= 3:
            det, par, *grade = a.resto
            res = [sintonizar(det, par, [_int_ou_float(x) for x in grade])]
        else:
            res = [sintonizar(d["detector"], d["param"], d["grade"]) for d in _ler_programa()]
        for r in res:
            if not r.get("ok"):
                print(r.get("erro"))
                continue
            print(f"\n{r['detector']}.{r['param']}:")
            for e in r["experimentos"]:
                print(f"   {e['valor']}: " + (e.get("erro") or
                      f"n={e['n_achados']} testes={'✓' if e['testes_verdes'] else '✗'}"))
            rec = r["recomendado"]
            print(f"   → recomendado: {rec['valor'] if rec else 'nenhum passa nos testes'}")
