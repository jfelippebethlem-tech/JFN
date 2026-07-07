# -*- coding: utf-8 -*-
"""Sweep GLOBAL de fracionamento de despesa sobre compras_diretas_tcerj (art. 75 §1º, Lei 14.133/2021).

Alimenta o detector P4 (compliance_agent/detectores/p4_fracionamento.py) em LOTE: agrupa as compras
diretas do TCE-RJ por (unidade, exercício) e roda o card em cada grupo — antes deste sweep, o P4 só
recebia contexto injetado pontualmente (bombeiros); as 97 unidades nunca tinham sido varridas.

HONESTIDADE (regras do projeto):
  • Reusa o card P4 inteiro — limiares, âncoras e degradação honesta ficam LÁ, não aqui.
  • Sem LLM (`gerar` ausente): só o flag OBJETIVO — indício, nunca acusação.
  • A tabela não tem data por contratação → sinais temporais do P4 ficam de fora (o card degrada sozinho).
  • Dispensas enquadradas na Lei 8.666 (transição até 2023) são medidas contra o limite MAIOR da 14.133
    (tabela do P4) — critério CONSERVADOR: nunca infla achado, pode subestimar.
  • `valor` repete por linha de item → dedupe por processo (MAX = total; verificado: 1 valor distinto/processo).

Uso:
    .venv/bin/python -m tools.sweep_fracionamento_tcerj [--ano 2024] [--unidade FSERJ] [--min-soma 0]
Saída: tabela no stdout + JSON em output/sweep_fracionamento_tcerj.json
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

import re

from compliance_agent.detectores.p4_fracionamento import P4Fracionamento, limite_dispensa

DB = Path(__file__).resolve().parent.parent / "data" / "compliance.db"
OUT = Path(__file__).resolve().parent.parent / "output" / "sweep_fracionamento_tcerj.json"

# palavras que indicam obra/engenharia → limite do art. 75, I (maior); o resto cai em 'compras' (II).
_KW_OBRAS = ("obra", "engenharia", "reforma predial", "construcao", "construção", "pavimenta")

# quantos clusters extrair por (unidade, exercício): o P4 devolve só o MELHOR cluster; removemos as
# contratações do achado e re-rodamos até descartar/esgotar (cap de segurança).
_MAX_CLUSTERS_POR_GRUPO = 10


def _tipo_obj(objeto: str | None) -> str:
    t = (objeto or "").lower()
    return "obras" if any(k in t for k in _KW_OBRAS) else "compras"


# Fracionamento por VALOR só faz sentido em dispensa POR VALOR: Lei 14.133 art. 75 I/II ·
# Lei 8.666 art. 24 I/II · Lei 13.303 art. 29 I/II. Dispensa por OUTRO fundamento (emergência
# art. 75 VIII / 24 IV, locação, etc.) não é "fuga do teto" — é matéria do R5 (enquadramento),
# não do P4. Sem esse filtro, o smoke da FSERJ agrupava dispensas emergenciais de R$ 60M+.
_INCISOS_VALOR = {"I", "II", "1", "2"}


def _inciso_valor(enquadramento: str | None) -> bool | None:
    """True se o enquadramento cita inciso de dispensa POR VALOR (75/24/29, I ou II); False se cita
    outro inciso; None se não parseável (texto livre do TCE-RJ é sujo)."""
    t = re.sub(r"[\s.ºo°]+", "", (enquadramento or "").upper())
    if not t:
        return None
    m = re.search(r"INC(?:ISO)?([IVX]+|\d+),?D?O?ART(?:IGO)?(?:75|24|29)", t)
    if not m:
        m = re.search(r"ART(?:IGO)?(?:75|24|29)[^A-Z0-9]{0,3}(?:INC(?:ISO)?)?([IVX]+|\d+)", t)
    if not m:
        return None
    return m.group(1) in _INCISOS_VALOR


def _dispensa_por_valor(afastamento: str | None, enquadramento: str | None,
                        valor: float, exercicio: int, tipo_obj: str) -> bool:
    """A contratação conta como DISPENSA por valor p/ o P4? Inexigibilidade → False; 'Pequenas
    Compras' → True (por definição); inciso citado decide; sem inciso parseável, heurística
    conservadora: só é candidata a fuga-de-teto se o valor CABE no teto vigente (dispensa por
    valor acima do próprio teto é impossível — seria outro fundamento)."""
    a = (afastamento or "").lower()
    if "dispensa" not in a:
        return False
    if "pequenas compras" in a:
        return True
    iv = _inciso_valor(enquadramento)
    if iv is not None:
        return iv
    limite = limite_dispensa(exercicio, tipo_obj)
    return limite is not None and valor <= limite


def carregar_grupos(db_path: Path = DB, ano: int | None = None,
                    unidade_like: str | None = None) -> dict[tuple[str, int], list[dict]]:
    """Lê compras_diretas_tcerj (read-only), 1 linha por processo, agrupado por (unidade, exercício)."""
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    sql = """
        SELECT processo, unidade, ano_processo,
               MAX(valor) AS valor, MIN(objeto) AS objeto,
               MIN(afastamento) AS afastamento, MIN(enquadramento_legal) AS enquadramento,
               MIN(fornecedor) AS fornecedor
        FROM compras_diretas_tcerj
        WHERE processo IS NOT NULL AND unidade IS NOT NULL AND ano_processo IS NOT NULL
        GROUP BY processo, unidade, ano_processo
    """
    grupos: dict[tuple[str, int], list[dict]] = {}
    for r in con.execute(sql):
        if ano and int(r["ano_processo"]) != ano:
            continue
        if unidade_like and unidade_like.lower() not in (r["unidade"] or "").lower():
            continue
        chave = (r["unidade"], int(r["ano_processo"]))
        valor = float(r["valor"] or 0)
        tipo_obj = _tipo_obj(r["objeto"])
        grupos.setdefault(chave, []).append({
            "processo": r["processo"],
            "objeto": r["objeto"],
            "valor": valor,
            "modalidade": r["afastamento"],
            # flag EXPLÍCITA p/ o _is_dispensa do P4: só dispensa POR VALOR conta p/ fracionamento
            "dispensa": _dispensa_por_valor(r["afastamento"], r["enquadramento"], valor,
                                            int(r["ano_processo"]), tipo_obj),
            "exercicio": int(r["ano_processo"]),
            "fornecedor": r["fornecedor"],
            "tipo_obj": tipo_obj,
        })
    con.close()
    return grupos


def rodar_sweep(grupos: dict[tuple[str, int], list[dict]]) -> list[dict]:
    """Roda o P4 por grupo, extraindo TODOS os clusters confirmados (o card devolve 1 por chamada:
    remove as contratações do achado e re-roda). Retorna achados ordenados por soma do cluster."""
    det = P4Fracionamento()
    achados: list[dict] = []
    for (unidade, exercicio), contratacoes in sorted(grupos.items()):
        restantes = list(contratacoes)
        for _ in range(_MAX_CLUSTERS_POR_GRUPO):
            if len(restantes) < 2:
                break
            res = det.avaliar({"processo": f"{unidade} · {exercicio}", "contratacoes": restantes})
            if res.status != "confirmado" or res.score <= 0:
                break
            d = res.to_dict()
            d["unidade"], d["exercicio"] = unidade, exercicio
            achados.append(d)
            # remove o cluster achado (registrado pelo P4 em valores.processos_cluster) e re-roda
            procs = set(d.get("valores", {}).get("processos_cluster") or [])
            antes = len(restantes)
            restantes = [c for c in restantes if str(c["processo"]) not in procs]
            if len(restantes) == antes:  # sem processos mapeáveis → não dá p/ iterar com segurança
                break
    achados.sort(key=lambda d: d.get("valores", {}).get("soma_cluster", 0), reverse=True)
    return achados


def main() -> None:
    ap = argparse.ArgumentParser(description="Sweep de fracionamento (P4) sobre compras_diretas_tcerj")
    ap.add_argument("--ano", type=int, default=None, help="filtrar exercício")
    ap.add_argument("--unidade", default=None, help="filtrar unidade (substring, case-insensitive)")
    ap.add_argument("--min-soma", type=float, default=0.0, help="soma mínima do cluster p/ listar")
    ap.add_argument("--top", type=int, default=40, help="máx. de achados na tabela do stdout")
    args = ap.parse_args()

    grupos = carregar_grupos(ano=args.ano, unidade_like=args.unidade)
    n_proc = sum(len(v) for v in grupos.values())
    print(f"Grupos (unidade × exercício): {len(grupos)} · processos únicos: {n_proc:,}".replace(",", "."))

    achados = [a for a in rodar_sweep(grupos)
               if a.get("valores", {}).get("soma_cluster", 0) >= args.min_soma]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(achados, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(f"Achados confirmados (indício objetivo, sem juízo LLM): {len(achados)} → {OUT}\n")

    fmt_moeda = lambda v: f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    for a in achados[: args.top]:
        v = a.get("valores", {})
        print(f"  [{a['score']:.2f}] {a['unidade'][:52]} · {a['exercicio']}"
              f" · {v.get('n_dispensas_cluster')} dispensas · soma {fmt_moeda(v.get('soma_cluster', 0))}"
              f" (limite {fmt_moeda(v.get('limite_dispensa_vigente') or 0)})")
        for p in a.get("processos_cluster", [])[:6]:
            print(f"       · {p}")


if __name__ == "__main__":
    main()
