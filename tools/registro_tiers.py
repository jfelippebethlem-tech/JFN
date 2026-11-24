# -*- coding: utf-8 -*-
"""Grava (ou confere) o tier de cada entrada de `config/qualidade_detectores.yaml` — O5.1 do plano mestre v2 (§5).

Os campos `tier`, `tier_motivo`, `fp_ic95` e `manchete_efetiva` são CALCULADOS por
`compliance_agent.qualidade.detectores.campos_calculados` (régua única) e gravados no YAML para quem lê o arquivo
sem importar o pacote (painel na O7.3, relatórios). A gravação é por TEXTO, entrada a entrada: os comentários e a
ordem do registro (curado à mão) ficam intactos; só as linhas desses quatro campos são trocadas. Depois de gravar,
o arquivo é relido e comparado com o calculado — divergência aborta sem gravar.

    python tools/registro_tiers.py --conferir     # sai 1 se algum gravado difere do calculado hoje
    python tools/registro_tiers.py --gravar       # recalcula e grava
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from compliance_agent.qualidade import detectores as D  # noqa: E402

_RX_ENTRADA = re.compile(r"^  ([^\s#][^:]*?):\s*(#.*)?$")


def blocos(linhas: list[str]) -> dict[str, tuple[int, int]]:
    """id → (início, fim exclusivo) das linhas de cada entrada sob `detectores:` (indentação de 2 espaços)."""
    ini = next(i for i, ln in enumerate(linhas) if ln.rstrip() == "detectores:") + 1
    marcas = [(i, _RX_ENTRADA.match(ln).group(1).strip("'\"")) for i, ln in enumerate(linhas[ini:], ini)
              if _RX_ENTRADA.match(ln)]
    out = {}
    for j, (i, did) in enumerate(marcas):
        fim = marcas[j + 1][0] if j + 1 < len(marcas) else len(linhas)
        while fim - 1 > i and (not linhas[fim - 1].strip() or linhas[fim - 1].lstrip().startswith("#")):
            fim -= 1                                  # comentário/linha vazia antes da próxima entrada fica com ela
        out[did] = (i, fim)
    return out


def _linha(campo: str, valor) -> str:
    v = yaml.safe_dump(valor, allow_unicode=True, default_flow_style=True, width=10**6).strip()
    return f"{campo}: {v.removesuffix('...').strip()}"


def aplicar_campos(texto: str, campos: dict[str, dict], gerenciados: tuple[str, ...]) -> str:
    """Troca, em cada entrada de `campos`, as linhas de primeiro nível dos `gerenciados` pelos valores dados
    (um campo por linha, ao fim da entrada). Entradas fora de `campos` ficam como estão."""
    linhas = texto.split("\n")
    rx = re.compile(r"^    (" + "|".join(map(re.escape, gerenciados)) + r"):")
    for did, (i, fim) in sorted(blocos(linhas).items(), key=lambda kv: -kv[1][0]):
        if did not in campos:
            continue
        corpo = [ln for ln in linhas[i + 1:fim] if not rx.match(ln)]
        novos = ["    " + _linha(c, v) for c, v in campos[did].items()]
        linhas[i + 1:fim] = corpo + novos
    return "\n".join(linhas)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--gravar", action="store_true")
    g.add_argument("--conferir", action="store_true")
    ap.add_argument("--arq", type=Path, default=D.ARQ)
    a = ap.parse_args(argv)
    hoje = date.today()
    if a.conferir:
        dif = D.tiers_desatualizados(a.arq, hoje)
        print("\n".join(dif) if dif else "tiers em dia")
        return 1 if dif else 0
    reg = D.carregar(a.arq)
    calc = {did: D.campos_calculados(e, hoje) for did, e in reg.items()}
    novo = aplicar_campos(a.arq.read_text(encoding="utf-8"), calc, D.CAMPOS_CALCULADOS)
    relido = yaml.safe_load(novo)["detectores"]
    erro = [did for did in reg if {c: relido[did].get(c) for c in D.CAMPOS_CALCULADOS} != calc[did]
            or {k: v for k, v in relido[did].items() if k not in D.CAMPOS_CALCULADOS}
            != {k: v for k, v in reg[did].items() if k not in D.CAMPOS_CALCULADOS}]
    if erro or set(relido) != set(reg):
        print(f"ABORTADO — a regravação mudaria o que não devia: {erro[:5]}", file=sys.stderr)
        return 2
    a.arq.write_text(novo, encoding="utf-8")
    por = {t: sum(c["tier"] == t for c in calc.values()) for t in (1, 2, 3)}
    print(f"{len(calc)} entradas — tier 1: {por[1]} · tier 2: {por[2]} · tier 3: {por[3]} · "
          f"manchete efetiva: {sum(c['manchete_efetiva'] for c in calc.values())}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
