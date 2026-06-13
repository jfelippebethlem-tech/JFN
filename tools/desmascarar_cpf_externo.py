#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""desmascarar_cpf_externo — DORMENTE/GATED: desmasca o CPF de sócio(s) de um ALVO via fonte externa.

Disparado pelo dono, por alvo (não é sweep). Default = **dry-run** (mostra os candidatos e o plano, SEM
nenhuma consulta externa). `--executar` consulta a fonte de fato (volume baixo, com pausa, honesto).

Usa o estreitamento da fusão folha×QSA (`cpf_pos3a9`) quando existe → ~100 candidatos em vez de 1.000.
LGPD: CPF resolvido é uso INTERNO; ToS: respeitar o termo da fonte. Sem rede/captcha → INDISPONÍVEL.

Uso:
  # alvo por CNPJ (resolve os sócios mascarados ainda não resolvidos daquela empresa)
  PYTHONPATH=. .venv/bin/python -m tools.desmascarar_cpf_externo --cnpj 05707413000124 [--executar] [--max 120]
  # alvo avulso (nome + máscara)
  PYTHONPATH=. .venv/bin/python -m tools.desmascarar_cpf_externo --nome "FULANO" --doc "***550179**" [--executar]
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from compliance_agent import cpf_externo as ce  # noqa: E402
from compliance_agent.resolucao_cpf import _digitos  # noqa: E402

_DB = Path("data") / "compliance.db"


def _socios_do_cnpj(cnpj: str) -> list[dict]:
    if not _DB.exists():
        return []
    con = sqlite3.connect(f"file:{_DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        cols = {c[1] for c in con.execute("PRAGMA table_info(socios_fornecedor)")}
        pos = "cpf_pos3a9" if "cpf_pos3a9" in cols else "NULL AS cpf_pos3a9"
        resolv = "cpf_resolvido" if "cpf_resolvido" in cols else "NULL AS cpf_resolvido"
        rows = con.execute(
            f"SELECT socio_nome, socio_doc, {pos}, {resolv} FROM socios_fornecedor "
            f"WHERE cnpj=? AND socio_doc LIKE '%*%'", (_digitos(cnpj),)).fetchall()
    finally:
        con.close()
    return [dict(r) for r in rows]


def _resolver_um(nome: str, doc: str, pos3a9: str | None, executar: bool, maxc: int, pausa: float) -> None:
    cands = ce.candidatos_estreitados(doc, pos3a9)
    estreitado = bool(pos3a9 and _digitos(pos3a9) and len(_digitos(pos3a9)) == 7)
    print(f"\n• {nome}  [{doc}]  → {len(cands)} candidatos válidos"
          f"{' (ESTREITADO p/ ~100 pela fusão folha×QSA)' if estreitado else ''}")
    if not executar:
        print(f"  DRY-RUN: 1º candidato {cands[0] if cands else '—'} … (use --executar p/ consultar a fonte)")
        return
    prov = ce.ProviderSituacaoCadastral()
    res = ce.desmascarar_cpf_nome(nome, doc, prov, cpf_pos3a9=pos3a9,
                                  max_consultas=maxc, pausa=pausa, log=print)
    if res.resolvido:
        print(f"  ✅ RESOLVIDO: CPF ***{res.cpf[3:9]}** confirmado ({res.fonte}, {res.consultas} consultas) "
              f"[completo gravável internamente]")
    else:
        print(f"  ⌀ INDISPONÍVEL: {res.motivo} ({res.consultas} consultas)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cnpj", default="", help="alvo: resolve os sócios mascarados desta empresa")
    ap.add_argument("--nome", default="", help="alvo avulso: nome do sócio")
    ap.add_argument("--doc", default="", help="alvo avulso: máscara do QSA, ex. ***550179**")
    ap.add_argument("--pos3a9", default="", help="alvo avulso: 7 díg conhecidos (pos.3-9) da fusão, opcional")
    ap.add_argument("--executar", action="store_true", help="consulta a fonte externa de fato (default: dry-run)")
    ap.add_argument("--max", type=int, default=120, help="teto de consultas por sócio (default 120)")
    ap.add_argument("--pausa", type=float, default=1.5, help="pausa entre consultas (s)")
    a = ap.parse_args()

    if not a.executar:
        print("⚠ DRY-RUN (nenhuma consulta externa). Use --executar para consultar a fonte.\n")

    if a.cnpj:
        socios = _socios_do_cnpj(a.cnpj)
        pend = [s for s in socios if not (s.get("cpf_resolvido") or "").strip()]
        print(f"CNPJ {a.cnpj}: {len(socios)} sócio(s) mascarado(s), {len(pend)} ainda não resolvido(s) "
              "internamente (alvos da fonte externa).")
        for s in pend:
            _resolver_um(s["socio_nome"], s["socio_doc"], s.get("cpf_pos3a9"), a.executar, a.max, a.pausa)
        return 0

    if a.nome and a.doc:
        _resolver_um(a.nome, a.doc, a.pos3a9 or None, a.executar, a.max, a.pausa)
        return 0

    ap.error("informe --cnpj OU (--nome e --doc)")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
