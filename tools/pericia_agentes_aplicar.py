"""Aplica no compliance.db as perícias integrais feitas por agente (data/pericia_agentes/<tag>.json).

Dono, 18/11/2026: "perícias detalhistas e completíssimas por todos os ângulos" — agentes Opus leram cada processo
inteiro (protocolo em data/pericia_agentes/PROTOCOLO.md). Os laudos ficam em arquivo até a sessão principal os
aplicar aqui, com a regra da casa: 🔴 (grau 3 / nota ≥ 7) só com conferência na fonte primária registrada em
`conferencia_principal.veredito == "confirmado"`; sem ela o teto é 🟡 (grau 2 / nota 6) e o motivo fica escrito.

    .venv/bin/python -m tools.pericia_agentes_aplicar            # simula (não grava)
    .venv/bin/python -m tools.pericia_agentes_aplicar --aplicar  # grava pericia_integral + lex_execucao
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
PASTA = RAIZ / "data" / "pericia_agentes"
REGISTRO = PASTA / "_aplicados.json"
MODELO = "agente Claude Code (Opus 5.5, leitura integral 18/11/2026)"
NOTA_TETO_SEM_CONFERENCIA = 6
GRAU_TETO_SEM_CONFERENCIA = 2


def conferido(d: dict) -> bool:
    return (d.get("conferencia_principal") or {}).get("veredito") == "confirmado"


def eixos_com_teto(d: dict, nomes: tuple[str, ...]) -> dict:
    """Eixos no formato de `pericia_integral.gravar`; grau 3 sem conferência na fonte cai para 2 com o motivo."""
    ok = conferido(d)
    out = {}
    for n in nomes:
        e = dict((d.get("eixos") or {}).get(n) or {})
        g = e.get("grau") if isinstance(e.get("grau"), int) else None
        if g is not None and g > GRAU_TETO_SEM_CONFERENCIA and not ok:
            e["grau_agente"] = g
            g = GRAU_TETO_SEM_CONFERENCIA
            e["teto"] = "grau 3 aguarda conferência na fonte primária pela sessão principal"
        e["grau"] = g
        e.setdefault("achados", [])
        e.setdefault("descartados", [])
        out[n] = e
    return out


def lex_com_teto(d: dict) -> dict | None:
    lx = dict(d.get("lex") or {})
    if not lx.get("execucao_comprovada"):
        return None
    nota = lx.get("nota_risco_execucao")
    if isinstance(nota, (int, float)) and nota > NOTA_TETO_SEM_CONFERENCIA and not conferido(d):
        lx["nota_risco_execucao"] = NOTA_TETO_SEM_CONFERENCIA
        lx.setdefault("duvidas", []).append(f"nota {nota} do agente limitada a {NOTA_TETO_SEM_CONFERENCIA} até a "
                                            "conferência na fonte primária")
    return lx


def _impressao(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16]


def aplicar(gravar: bool) -> dict:
    from compliance_agent import pericia_integral as P
    from tools import lex_execucao as L
    reg = json.loads(REGISTRO.read_text()) if REGISTRO.exists() else {}
    res = {"lidos": 0, "invalidos": [], "ja_aplicados": 0, "integral": 0, "lex": 0, "lex_sem_linha": 0,
           "rebaixados": 0, "conferidos": 0}
    con = P._con_escrita() if gravar else None
    try:
        for f in sorted(PASTA.glob("*.json")):
            if f.name.startswith(("lote_", "_")):
                continue
            res["lidos"] += 1
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
                processo = d["processo"]
            except (OSError, ValueError, KeyError) as e:
                res["invalidos"].append(f"{f.name}: {type(e).__name__}")
                continue
            imp = _impressao(f)
            if reg.get(f.name) == imp:
                res["ja_aplicados"] += 1
                continue
            eixos = eixos_com_teto(d, P.NOMES_EIXOS)
            res["rebaixados"] += any("teto" in e for e in eixos.values())
            res["conferidos"] += conferido(d)
            pago = (d.get("pago_ob") or {}).get("total")
            glob = {"fonte": f"data/pericia_agentes/{f.name}", "agente": d.get("agente"),
                    "conferencia_principal": d.get("conferencia_principal"),
                    "achados_principais": d.get("achados_principais"), "lacunas": d.get("lacunas"),
                    "aprendizado": d.get("aprendizado")}
            lx = lex_com_teto(d)
            if gravar:
                P.gravar(processo, eixos, modelo=MODELO, provedor="assinatura", conferido_opus=int(conferido(d)),
                         valor_pago=pago if isinstance(pago, (int, float)) else None, extra_global=glob, con=con)
                res["integral"] += 1
                if lx is not None:
                    if L.aplicar_conferencia("sei:" + processo, json.dumps(lx, ensure_ascii=False), MODELO, None,
                                             con=con):
                        res["lex"] += 1
                    else:
                        res["lex_sem_linha"] += 1
                reg[f.name] = imp
                REGISTRO.write_text(json.dumps(reg, ensure_ascii=False, indent=0), encoding="utf-8")
            else:
                res["integral"] += 1
                res["lex"] += lx is not None
    finally:
        if con is not None:
            con.close()
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--aplicar", action="store_true")
    a = ap.parse_args(argv)
    print(json.dumps(aplicar(a.aplicar), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
