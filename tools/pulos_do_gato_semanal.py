#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Rotina semanal dos detectores dos "pulos do gato" do orçamento (Comissão de Orçamento da ALERJ).

Roda `compliance_agent.pulos_do_gato.rodar()` (somente leitura nas bases) e grava `data/pulos_do_gato.json`, que a
rota `/api/comissao/pulos` serve à sub-aba Estado › Comissão de Orçamento › Pulos do gato. Depois do coletor SICONFI
(terça 05:40), porque cinco detectores leem o RREO/RGF:

    30 7 * * 2 cd /home/ubuntu/JFN && flock -n /tmp/pulos_do_gato.lock timeout 1800 nice -n 12 \
        .venv/bin/python tools/pulos_do_gato_semanal.py >> data/comissao_orcamento.log 2>&1

Sai com código 1 se algum detector ficar sem fonte ou quebrar, ou se o manual não for lido — rotina que falha calada
já custou caro nesta casa.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from compliance_agent import pulos_do_gato as P  # noqa: E402


def main() -> int:
    painel = P.rodar()
    destino = P.gravar(painel)
    ruim = []
    for d in painel["detectores"]:
        pv = d["prevalencia"]
        taxa = "—" if pv["taxa"] is None else P.pct(pv["taxa"])
        print(f"{d['id']} {d['titulo'][:60]:60} base {pv['base']:>7} acionados {pv['acionados']:>5} ({taxa}) "
              f"achados {len(d['achados']):>4} {d['estados']}")
        if any(a["titulo"] in ("Detector falhou", "Fonte indisponível") for a in d["achados"]):
            ruim.append(d["id"])
    print(f"{painel['gerado_em']} → {destino} · manual lido: {painel['manual_lido']}")
    if ruim or not painel["manual_lido"]:
        print(f"ATENÇÃO: detectores sem fonte ou com erro: {ruim or '—'}; manual lido: {painel['manual_lido']}",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
