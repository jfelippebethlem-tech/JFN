#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""registrar_vereditos_fachada — captura PASSIVA do veredito humano de fachada (zero conflito).

Lê o `state.db` do Hermes (onde toda mensagem do dono no Telegram é persistida), casa o código curto
impresso na legenda da dúvida e grava o veredito (fachada/real/pular) em `fachada_veredito`. NÃO usa
getUpdates → não compete com o gateway do Yoda (lição §9: 2º poller = conflito 409). Idempotente,
resumível por cursor (`data/.fachada_veredito_cursor`). Rode por cron junto dos sweeps.

Modo manual (sem depender da resposta no Telegram): registra direto um veredito.
    PYTHONPATH=. .venv/bin/python -m tools.registrar_vereditos_fachada            # varre o state.db
    PYTHONPATH=. .venv/bin/python -m tools.registrar_vereditos_fachada --listar   # pendências
    PYTHONPATH=. .venv/bin/python -m tools.registrar_vereditos_fachada --cnpj <cnpj> --status fachada
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from compliance_agent import fachada_doubt as fd  # noqa: E402

_VALIDOS = ("fachada", "real", "pular")


def _registrar_manual(con, cnpj: str, status: str) -> int:
    from compliance_agent.investigacao_dd import _digitos
    c = _digitos(cnpj)
    cur = con.execute(
        "UPDATE fachada_veredito SET status=?, veredito_em=?, veredito_raw=? WHERE cnpj=?",
        (status, dt.datetime.now().isoformat(timespec="seconds"), f"manual:{status}", c))
    con.commit()
    return cur.rowcount


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--listar", action="store_true", help="lista pendências e sai")
    ap.add_argument("--cnpj", default="", help="registro manual: CNPJ")
    ap.add_argument("--status", default="", choices=("", *_VALIDOS), help="registro manual: veredito")
    ap.add_argument("--state-db", default="", help="caminho do state.db do Hermes (override)")
    a = ap.parse_args()

    con = fd.conectar()
    fd.garantir_schema(con)

    if a.listar:
        rows = con.execute(
            "SELECT codigo, cnpj, razao, status, total_recebido, enviado_em "
            "FROM fachada_veredito ORDER BY status, total_recebido DESC").fetchall()
        if not rows:
            print("(nada enviado ainda)"); return 0
        for r in rows:
            print(f"  [{r['codigo']}] {r['status']:<8} {fd._moeda(r['total_recebido']):>16}  "
                  f"{r['cnpj']}  {r['razao'] or ''}")
        return 0

    if a.cnpj:
        if a.status not in _VALIDOS:
            print("ERRO: --status deve ser fachada|real|pular"); return 2
        n = _registrar_manual(con, a.cnpj, a.status)
        print(f"{'OK' if n else 'CNPJ não está em fachada_veredito'}: {a.cnpj} → {a.status} ({n} linha)")
        return 0 if n else 1

    state_db = Path(a.state_db) if a.state_db else None
    grav = fd.processar_respostas(con, state_db=state_db)
    if not grav:
        print("Sem vereditos novos.")
        return 0
    for g in grav:
        print(f"  ✓ {g['cnpj']} → {g['status']}   «{g['raw'][:70]}»")
    print(f"FIM: {len(grav)} veredito(s) registrado(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
