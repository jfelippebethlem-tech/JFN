#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Um CONSÓRCIO por certame — o mesmo núcleo, veículos diferentes, e o teto por CNPJ não vê.

POR QUE EXISTE. A concentração por grupo (`osint/grupo_economico`) mede dentro de UMA unidade
gestora e por CNPJ colapsado. Ela viu que a UG 660100 tinha 57,5% em sete CNPJs, mas não explicava
**como**. A resposta apareceu no quadro societário: os "concorrentes" são **consórcios**, cada um
constituído para um certame, com o **mesmo par de empresas dentro** e o **mesmo administrador**.

Medido em 2026-08-09 sobre os 36 consórcios que receberam OB do Estado: **cinco pessoas administram
mais de um**, e a primeira responde por **R$ 417,9 milhões em seis veículos**, em três unidades
gestoras diferentes — o que o recorte por UG, sozinho, nunca mostraria.

O QUE ISTO NÃO AFIRMA:

  · **Consórcio é figura LÍCITA e comum em obra pública** (art. 15 da Lei 14.133): soma capacidade
    técnica e financeira, e é o caminho normal para obra grande. Administrar vários também não é
    vedado — construtora que trabalha em consórcio tende a repetir o arranjo.
  · O que o screen mede é a **repetição do veículo**: quantos consórcios distintos o mesmo
    administrador comanda, quanto eles receberam e em quantas unidades. Alto ali significa que a
    diversidade de CNPJs na disputa pode ser aparente — e é isso que se pede conferir nos autos.
  · **Membro comum é o outro eixo**: dois consórcios com administradores diferentes mas as MESMAS
    empresas dentro contam a mesma história. Por isso os membros saem na resposta.

    python -m tools.screen_consorcio_veiculo
    python -m tools.screen_consorcio_veiculo --md --gravar
"""
from __future__ import annotations

import argparse
import collections
import sqlite3
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parent.parent
MIN_CONSORCIOS = 2
MIN_VALOR = 1_000_000.0
# Como o nome do consórcio se apresenta na OB. Não é heurística frágil: no acervo, todo credor
# consorciado traz a palavra no nome empresarial (é exigência de registro).
PREFIXOS = ("CONSORCIO%", "CONSÓRCIO%")


def medir(db: str = "", min_consorcios: int = MIN_CONSORCIOS,
          min_valor: float = MIN_VALOR) -> list[dict[str, Any]]:
    from compliance_agent.reporting.intel_base import _DB

    con = sqlite3.connect(f"file:{db or _DB}?mode=ro", uri=True, timeout=60)
    try:
        ors = " OR ".join(["UPPER(nome_credor) LIKE ?"] * len(PREFIXOS))
        try:
            consorcios = {r[0]: r[1] for r in con.execute(
                f"SELECT substr(credor,1,8), MIN(nome_credor) FROM ob_orcamentaria_siafe "
                f"WHERE {ors} GROUP BY 1", [p.upper() for p in PREFIXOS])}
        except sqlite3.OperationalError:
            return []
        if not consorcios:
            return []

        marcas = ",".join("?" * len(consorcios))
        adm: dict[str, set[str]] = collections.defaultdict(set)
        membros: dict[str, list[str]] = collections.defaultdict(list)
        try:
            for rz, nome, qual in con.execute(
                    f"SELECT cnpj_basico, nome_socio, COALESCE(qualificacao_txt,'') "
                    f"FROM socios_receita WHERE cnpj_basico IN ({marcas})", sorted(consorcios)):
                if "dministrador" in qual or "residente" in qual:
                    adm[str(nome or "").strip()].add(rz)
                else:
                    membros[rz].append(str(nome or "").strip())
        except sqlite3.OperationalError:
            return []

        # EMPRESAS DIRETAS do mesmo administrador — o consórcio é o veículo, mas a exposição da
        # pessoa inclui o que ela administra fora dele: quem lidera a lista administra seis
        # consórcios E uma prestadora com 719 OBs.
        # SÓ as pessoas que já administram consórcio entram na consulta. Varrer todo o QSA de
        # administradores para depois filtrar levou esta função de segundos para mais de dez
        # minutos — duas vezes. O universo de interesse é minúsculo; a base, não.
        diretas: dict[str, list[dict]] = collections.defaultdict(list)
        interessados = sorted(p for p, r in adm.items() if p and len(r) >= min_consorcios)
        if interessados:
            try:
                mp = ",".join("?" * len(interessados))
                for pessoa, rz in con.execute(
                        f"SELECT nome_socio, cnpj_basico FROM socios_receita "
                        f"WHERE nome_socio IN ({mp}) "
                        f"AND (qualificacao_txt LIKE '%dministrador%' "
                        f"     OR qualificacao_txt LIKE '%residente%')", interessados):
                    if rz in consorcios:
                        continue
                    r = con.execute(
                        "SELECT MIN(nome_credor), COALESCE(SUM(valor),0), COUNT(*) "
                        "FROM ob_orcamentaria_siafe WHERE substr(credor,1,8)=? "
                        "AND status='Contabilizado'", (rz,)).fetchone()
                    if r and (r[1] or 0) > 0:
                        diretas[str(pessoa).strip()].append(
                            {"cnpj": rz, "nome": r[0] or "", "pago": round(float(r[1]), 2),
                             "obs": int(r[2] or 0)})
            except sqlite3.OperationalError:
                diretas = collections.defaultdict(list)

        pago: dict[str, tuple] = {}
        for rz in consorcios:
            r = con.execute(
                "SELECT COALESCE(SUM(valor),0), COUNT(*), GROUP_CONCAT(DISTINCT ug_emitente) "
                "FROM ob_orcamentaria_siafe WHERE substr(credor,1,8)=? AND status='Contabilizado'",
                (rz,)).fetchone()
            pago[rz] = (float(r[0] or 0), int(r[1] or 0),
                        sorted({u for u in (r[2] or "").split(",") if u}))
    finally:
        con.close()

    fora = []
    for pessoa, rzs in adm.items():
        if not pessoa or len(rzs) < min_consorcios:
            continue
        total = sum(pago.get(rz, (0, 0, []))[0] for rz in rzs)
        if total < min_valor:
            continue
        ugs = sorted({u for rz in rzs for u in pago.get(rz, (0, 0, []))[2]})
        veiculos = sorted(
            ({"cnpj": rz, "nome": consorcios.get(rz, ""), "pago": round(pago.get(rz, (0,))[0], 2),
              "obs": pago.get(rz, (0, 0))[1], "ugs": pago.get(rz, (0, 0, []))[2],
              "membros": sorted(set(membros.get(rz, [])))[:4]} for rz in rzs),
            key=lambda d: -d["pago"])
        # o NÚCLEO: empresas presentes em TODOS os veículos — é o que revela "um por certame"
        conjuntos = [set(v["membros"]) for v in veiculos if v["membros"]]
        nucleo = sorted(set.intersection(*conjuntos)) if conjuntos else []
        dir_ = sorted(diretas.get(pessoa, []), key=lambda d: -d["pago"])[:5]
        fora.append({
            "administrador": pessoa, "n_consorcios": len(rzs), "total": round(total, 2),
            "n_ugs": len(ugs), "ugs": ugs, "nucleo_comum": nucleo, "veiculos": veiculos,
            "empresas_diretas": dir_,
            "total_com_diretas": round(total + sum(d["pago"] for d in dir_), 2),
        })
    fora.sort(key=lambda d: (-d["n_consorcios"], -d["total"]))
    return fora


RESSALVA = (
    "Consórcio é figura LÍCITA e comum em obra pública (art. 15 da Lei 14.133): soma capacidade "
    "técnica e financeira. Administrar vários também não é vedado — quem trabalha em consórcio "
    "tende a repetir o arranjo. O que se mede é a REPETIÇÃO do veículo: quantos consórcios "
    "distintos o mesmo administrador comanda, com que núcleo de empresas dentro e em quantas "
    "unidades. Alto aqui significa que a diversidade de CNPJs na disputa pode ser APARENTE — e é "
    "isso que se pede conferir nos autos, nunca uma afirmação de arranjo."
)


def markdown(itens: list[dict]) -> str:
    from compliance_agent.reporting.intel_base import moeda
    L = ["# Um consórcio por certame — administrador com múltiplos veículos", "",
         f"> {RESSALVA}", "",
         "| Administrador | Consórcios | Pago (OB) | UGs | Núcleo comum |", "|---|---:|---:|---:|---|"]
    for x in itens:
        L.append(f"| {x['administrador'][:38]} | {x['n_consorcios']} | R$ {moeda(x['total'])} | "
                 f"{x['n_ugs']} | {'; '.join(n[:26] for n in x['nucleo_comum']) or '—'} |")
    return "\n".join(L) + "\n"


def main(argv: list[str] | None = None) -> int:  # pragma: no cover
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-consorcios", type=int, default=MIN_CONSORCIOS)
    ap.add_argument("--min-valor", type=float, default=MIN_VALOR)
    ap.add_argument("--top", type=int, default=20)
    ap.add_argument("--md", action="store_true")
    ap.add_argument("--gravar", action="store_true")
    a = ap.parse_args(argv)
    itens = medir(min_consorcios=a.min_consorcios, min_valor=a.min_valor)[: a.top]
    if a.md or a.gravar:
        texto = markdown(itens)
        print(texto)
        if a.gravar:
            alvo = _REPO / "data" / "consorcio_veiculo.md"
            alvo.write_text(texto, encoding="utf-8")
            print(f"gravado: {alvo}")
    else:
        print(f"{len(itens)} administrador(es) com {a.min_consorcios}+ consórcios:")
        for x in itens:
            print(f"   {x['administrador'][:36]:36} {x['n_consorcios']} veículos · "
                  f"R$ {x['total']:>14,.2f} · {x['n_ugs']} UG(s)")
            if x["nucleo_comum"]:
                print(f"        núcleo em todos: {'; '.join(n[:30] for n in x['nucleo_comum'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
