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


# arquivos de teste que protegem cada detector (evita `pytest -k` coletar as 1700+; None = detector
# sem teste rotulado → o gate de testes é PULADO e a recomendação sai só pela conservação de achados)
_TEST_FILES = {
    "conluio_qsa": ["tests/test_conluio_qsa.py"],
    "comunidades": ["tests/test_grafo_comunidades.py"],
    "radar_risco": ["tests/test_conluio_qsa.py"],   # radar depende do conluio; sem teste próprio
}


def _testes_verdes(detector: str) -> bool | None:
    """Roda só os arquivos de teste que protegem o detector. None = não há teste rotulado
    (gate pulado). Coletar 1700+ testes por valor de grade era o gargalo — aqui vai direto."""
    arquivos = _TEST_FILES.get(detector)
    if not arquivos:
        return None
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--no-header", "-p", "no:cacheprovider", *arquivos],
        cwd=_REPO, capture_output=True, text=True, timeout=300)
    return r.returncode == 0


def sintonizar(detector: str, param: str, grade: list) -> dict:
    """Loop autoresearch determinístico: mede n_achados no DB real p/ toda a grade (barato) e roda
    os TESTES do detector UMA vez (gate de sanidade — o teste valida o comportamento commitado, não
    enxerga o valor da grade). Se o gate está verde (ou não há teste rotulado), recomenda o valor
    MAIS CONSERVADOR (menos achados = menos FP); se o gate está vermelho, não recomenda (a base de
    verdade está quebrada, não confiar). Não edita código — recomenda (autonomy slider)."""
    if detector not in _DETECTORES:
        return {"ok": False, "erro": f"detector desconhecido: {detector}"}
    fn, chave = _DETECTORES[detector][0], _DETECTORES[detector][1]
    experimentos = []
    for v in grade:
        try:
            n = len(_chamar(fn, **{param: v}).get(chave) or [])
            experimentos.append({"valor": v, "n_achados": n})
        except Exception as exc:  # noqa: BLE001
            experimentos.append({"valor": v, "erro": str(exc)[:80]})
    gate = _testes_verdes(detector)           # None = sem teste rotulado; True/False = suite do detector
    validos = [e for e in experimentos if "n_achados" in e]
    ns = {e["n_achados"] for e in validos}
    recomendado, motivo = None, None
    if gate is False:
        motivo = "suite do detector VERMELHA — não confiar em recomendação"
    elif len(ns) <= 1:
        # o parâmetro não muda o nº de achados nesta grade → sem sinal p/ sintonizar (não desempatar
        # por valor: a direção 'conservadora' depende da semântica de min_/max_, ambígua aqui)
        motivo = f"parâmetro não discrimina nesta grade (todos n={ns.pop() if ns else 0})"
    else:
        # há discriminação real: o mais conservador é o de MENOR nº de achados (menos FP)
        recomendado = min(validos, key=lambda e: e["n_achados"])
    return {"ok": True, "detector": detector, "param": param,
            "experimentos": experimentos, "testes_verdes": gate, "recomendado": recomendado,
            "motivo": motivo,
            "gate_de_testes": ("rotulado" if _TEST_FILES.get(detector) else "ausente (só conservação)"),
            "nota": ("Recomendação = valor de MENOR nº de achados (menos FP), quando o parâmetro "
                     "discrimina e a suite está verde. Aplicar é decisão humana (autonomy slider); "
                     "conferir que não perdeu detecção real antes.")}


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
            gate = {True: "✓ verde", False: "✗ VERMELHO", None: "— sem teste"}[r["testes_verdes"]]
            print(f"\n{r['detector']}.{r['param']}  (gate de testes: {gate})")
            for e in r["experimentos"]:
                print(f"   {e['valor']}: " + (e.get("erro") or f"n_achados={e['n_achados']}"))
            rec = r["recomendado"]
            print(f"   → recomendado: {rec['valor'] if rec else '—'} "
                  f"({r.get('motivo') or r['gate_de_testes']})")
