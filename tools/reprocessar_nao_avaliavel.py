#!/usr/bin/env python3
"""Reprocessa SÓ as unidades com `nao_avaliavel` resolvível com dado em casa.

Por que existe: as varreduras de rotina não alcançam esses itens. `varredura_execucao --limite
120` pega os 120 maiores contratos (os 1.082 X7 "não se aplica" estão espalhados), e a varredura
por UG escolhe os N maiores credores do exercício — o fornecedor afetado pode não estar entre
eles. Aqui a fila sai do próprio `achados.db`: cada (UG, CNPJ), certame ou contrato que tem um
detector da lista em `nao_avaliavel` é reavaliado inteiro (INSERT OR REPLACE, idempotente).

    .venv/bin/python tools/reprocessar_nao_avaliavel.py              # simula: lê, não grava
    .venv/bin/python tools/reprocessar_nao_avaliavel.py --gravar     # grava em data/achados.db

Lê a produção em SÓ-LEITURA. Sem LLM (gerar=None). Uma unidade por vez — a VM tem 2 vCPU.
"""
from __future__ import annotations

import argparse
import collections
import pathlib
import sqlite3
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from compliance_agent import varredura_certames as VC  # noqa: E402
from compliance_agent import varredura_execucao as VE  # noqa: E402
from compliance_agent import varredura_orgaos as V  # noqa: E402
from compliance_agent.detectores import rodar_fornecedor  # noqa: E402

# detector → (tabela, colunas-chave). Só os que o conserto de 11/11/2026 resolve em casa.
ALVOS = {
    "ug": ("achado_detector", ("C6", "C7", "C8", "C9")),
    "certame": ("achado_certame", ("J3",)),
    "execucao": ("achado_execucao", ("X7",)),
}


def fila(ach: sqlite3.Connection, escopo: str) -> list[tuple]:
    tab, dets = ALVOS[escopo]
    marcas = ",".join("?" * len(dets))
    chave = {"ug": "ug, processo", "certame": "certame", "execucao": "contrato"}[escopo]
    return [tuple(r) for r in ach.execute(
        f"SELECT DISTINCT {chave} FROM {tab} "  # noqa: S608 — nomes vêm de ALVOS
        f"WHERE status='nao_avaliavel' AND detector IN ({marcas})", dets)]


def reprocessar(ro: sqlite3.Connection, ach: sqlite3.Connection, *, escopos=tuple(ALVOS),
                gravar: bool = False, log=print) -> collections.Counter:
    """Devolve a contagem (detector, status_novo) dos detectores-alvo. Só grava com `gravar`."""
    conta: collections.Counter = collections.Counter()
    destino = ach if gravar else None
    for escopo in escopos:
        _, dets = ALVOS[escopo]
        itens = fila(ach, escopo)
        log(f"{escopo}: {len(itens)} unidade(s)")
        for i, chave in enumerate(itens, 1):
            if escopo == "ug":
                ug, cnpj = chave
                res = rodar_fornecedor(cnpj, contexto=V.contexto_fornecedor(ro, cnpj, ug))
                if destino is not None:
                    V._persistir(destino, ug, "ug", res)
                    destino.commit()
            elif escopo == "certame":
                res = VC.varrer_certame(ro, chave[0], con_achados=destino)["todos"]
            else:
                res = VE.varrer_contrato(ro, chave[0], con_achados=destino)["todos"]
            for r in res:
                if r.detector in dets:
                    conta[(r.detector, r.status)] += 1
            if i % 100 == 0:
                log(f"  [{i}/{len(itens)}]")
    return conta


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--gravar", action="store_true", help="persiste em data/achados.db")
    ap.add_argument("--escopo", choices=sorted(ALVOS), action="append")
    a = ap.parse_args(argv)
    ro = V.abrir_leitura()
    ro.row_factory = sqlite3.Row
    ach = (V.abrir_achados() if a.gravar else
           sqlite3.connect(f"file:{V.DB_ACHADOS}?mode=ro", uri=True, timeout=30))
    t0 = time.time()
    conta = reprocessar(ro, ach, escopos=tuple(a.escopo or ALVOS), gravar=a.gravar)
    for (det, st), n in sorted(conta.items()):
        print(f"{det:4} {st:14} {n:6}")
    print(f"{'gravado' if a.gravar else 'SIMULADO (nada gravado)'} em {time.time() - t0:.0f}s")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
