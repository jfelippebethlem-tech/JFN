# -*- coding: utf-8 -*-
"""Prova do contrato único (O5.2) em SOMBRA: converte TODA a saída das três gerações num snapshot (só leitura),
grava uma amostra estratificada por regra num esquema PG TEMPORÁRIO e reproduz cada achado gravado.

    python tools/achados_sombra.py --compliance-db ~/snapshot-20261124/compliance.db \
        --achados-db ~/snapshot-20261124/achados.db --amostra 1000 [--manter] [--saida relatorio.json]

Nada do que as gerações gravam hoje (`alertas`, achados.db, caches) é tocado: os bancos abrem `mode=ro&immutable=1`.
O esquema temporário (`tmp_achados_<hex>`) é apagado ao fim, salvo `--manter`. A amostra é determinística
(semente fixa): por regra, ⌈amostra × participação⌉ com piso de 1 — toda regra com achado aparece.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sqlite3
import sys
import uuid
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from compliance_agent.adaptadores import achados as A  # noqa: E402

SEMENTE = 20261124


def _ro(p: Path) -> sqlite3.Connection:
    c = sqlite3.connect(f"file:{p}?mode=ro&immutable=1", uri=True)
    c.row_factory = sqlite3.Row
    return c


def converter(compliance_db: Path, achados_db: Path) -> tuple[list, Counter]:
    """Todos os achados convertidos + erros de conversão por tipo (o contrato recusa → conta, não esconde)."""
    out, erros = [], Counter()
    with _ro(compliance_db) as c:
        for r in c.execute(f"SELECT {','.join(A.COLS_ALERTA)} FROM alertas ORDER BY id"):
            try:
                out.append(A.de_alerta(dict(r)))
            except ValueError as e:                     # pydantic.ValidationError é ValueError
                erros[f"alertas: {type(e).__name__}: {str(e)[:120]}"] += 1
    with _ro(achados_db) as c:
        for t in A.TABELAS_DET:
            for r in c.execute(f"SELECT * FROM {t}"):
                try:
                    out.append(A.de_achado_db(t, dict(r)))
                except ValueError as e:
                    erros[f"{t}: {type(e).__name__}: {str(e)[:120]}"] += 1
    return out, erros


def amostrar(achados: list, n: int) -> list:
    por = defaultdict(list)
    for a in achados:
        por[a.execucao.regra_id].append(a)
    rnd = random.Random(SEMENTE)
    cotas = {r: max(1, math.ceil(n * len(v) / len(achados))) for r, v in por.items()}
    while sum(cotas.values()) > n:                      # corta do maior estrato até caber em n
        r = max(cotas, key=lambda k: cotas[k])
        cotas[r] -= 1
    return [a for r in sorted(por) for a in rnd.sample(por[r], min(cotas[r], len(por[r])))]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--compliance-db", type=Path, required=True)
    ap.add_argument("--achados-db", type=Path, required=True)
    ap.add_argument("--amostra", type=int, default=1000)
    ap.add_argument("--manter", action="store_true")
    ap.add_argument("--saida", type=Path)
    a = ap.parse_args(argv)
    import psycopg

    from compliance_agent.evidencias import dsn_vigente
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import reproduzir_achado as R

    todos, erros = converter(a.compliance_db, a.achados_db)
    amostra = amostrar(todos, a.amostra)
    esquema = f"tmp_achados_{uuid.uuid4().hex[:10]}"
    con = psycopg.connect(dsn_vigente(), autocommit=True)
    try:
        A.aplicar_schema(con, esquema)
        A.aplicar_schema(con, esquema)                  # idempotência: a 2ª aplicação não pode falhar nem duplicar
        g1 = A.gravar(con, esquema, amostra)
        g2 = A.gravar(con, esquema, amostra)            # 2ª carga: nada novo
        linhas = con.execute(
            f'SELECT a.id, e.origem, e.regra_id, e.regra_versao, e.entradas_hash, e.resultado, a.estado, a.status, '
            f'(SELECT count(*) FROM "{esquema}".achado_evidencia v WHERE v.achado_id = a.id) '
            f'FROM "{esquema}".achado a JOIN "{esquema}".execucao_regra e ON e.id = a.execucao_regra_id').fetchall()
        vered = Counter()
        exemplos = {}
        for aid, origem, rid, ver, h, res, est, st, nev in linhas:
            gravado = {"regra_id": rid, "regra_versao": ver, "entradas_hash": h, "resultado": res}
            v = R.comparar(gravado, R.ler_origem(origem, a.compliance_db, a.achados_db))["veredito"]
            vered[v] += 1
            exemplos.setdefault(v, aid)
        rel = {
            "esquema": esquema, "mantido": a.manter,
            "convertidos": len(todos), "erros_de_conversao": dict(erros),
            "por_regra": dict(Counter(x.execucao.regra_id for x in todos).most_common()),
            "por_estado": dict(Counter(f"{x.status.value}/{x.estado.value}" for x in todos).most_common()),
            "zumbis_titulo_sem_regra_atual": sum(1 for x in todos if x.execucao.resultado.get("titulo_sem_regra_atual")),
            "nao_registrados": dict(Counter(x.execucao.regra_id for x in todos
                                            if x.execucao.regra_id.startswith("nao_registrado"))),
            "amostra": len(amostra), "gravacao_1": g1, "gravacao_2_idempotente": g2,
            "linhas_pg": {t: con.execute(f'SELECT count(*) FROM "{esquema}".{t}').fetchone()[0]
                          for t in ("execucao_regra", "achado", "achado_evidencia", "decisao_humana")},
            "reproducao": dict(vered), "exemplo_por_veredito": exemplos,
            "amostra_por_regra": dict(Counter(x.execucao.regra_id for x in amostra).most_common()),
        }
    finally:
        if not a.manter:
            con.execute(f'DROP SCHEMA IF EXISTS "{esquema}" CASCADE')
        con.close()
    txt = json.dumps(rel, ensure_ascii=False, indent=1, default=str)
    if a.saida:
        a.saida.write_text(txt, encoding="utf-8")
    print(txt)
    return 0 if not erros and vered.get("REPRODUZIDO", 0) == len(linhas) else 1


if __name__ == "__main__":
    sys.exit(main())
