"""Folha da Prefeitura do Rio sempre em dia, desde 2020 (dono 27/11/2026: «de tempos em tempos atualizar essas folhas
todas, inclusive da pcrj» · «faz isso desde 2020»). Fonte: contrachequedoc.rio.gov.br (CSV mensal em bloco), coletor
da casa `compliance_agent.pcrj.folha_pref.coletar` (idempotente por competência; falha = rollback, o mês já guardado
fica intacto).

O site mantém só uma janela recente de meses: o que já temos NUNCA é apagado por mês que sumiu de lá. Cada chamada:
  1. coleta toda competência de 2020-01 até o mês corrente que ainda não está no banco;
  2. recoleta as 2 competências mais recentes já guardadas (a Prefeitura corrige a folha publicada);
  3. competência que o site não tem e o banco também não = INDISPONÍVEL declarado (nunca zero).
Uso: python -m tools.folha_pcrj_mensal [--de 202001]"""
from __future__ import annotations

import argparse
import sqlite3
import json
from datetime import date

from compliance_agent.pcrj import db as _db
from compliance_agent.pcrj import folha_pref as FP


def competencias(de: str, ate: str) -> list[str]:
    a, m, out = int(de[:4]), int(de[4:]), []
    while f"{a:04d}{m:02d}" <= ate:
        out.append(f"{a:04d}{m:02d}")
        a, m = (a + 1, 1) if m == 12 else (a, m + 1)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--de", default="202001")
    a = ap.parse_args(argv)
    hoje = date.today()
    alvo = competencias(a.de, f"{hoje.year:04d}{hoje.month:02d}")
    _db.inicializar()
    con = _db.conectar()
    try:
        tem = {r[0] for r in con.execute("SELECT DISTINCT competencia FROM pcrj_folha_pref")}
    except sqlite3.OperationalError:          # tabela ainda não existe: tudo falta
        tem = set()
    con.close()
    faltam = [c for c in alvo if c not in tem]
    recoleta = sorted(tem)[-2:]
    res = {"coletadas": [], "indisponiveis": [], "erros": []}
    for c in faltam + [c for c in recoleta if c not in faltam]:
        r = FP.coletar(c)
        if "erro" not in r and r.get("servidores"):
            res["coletadas"].append(f"{c}:{r['servidores']}")
        elif c in tem:
            res["erros"].append(f"{c}: recoleta falhou, mantida a versão guardada ({r.get('erro')})")
        else:
            res["indisponiveis"].append(c)
    con = _db.conectar()
    meses_banco = con.execute("SELECT COUNT(DISTINCT competencia), MIN(competencia), MAX(competencia) FROM pcrj_folha_pref").fetchone()
    con.close()
    print(json.dumps(res, ensure_ascii=False))
    print(f"folha_pcrj_mensal: ok — {meses_banco[0]} competências no banco ({meses_banco[1]}–{meses_banco[2]}); "
          f"coletadas {len(res['coletadas'])}, indisponíveis no site {len(res['indisponiveis'])}, erros {len(res['erros'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
