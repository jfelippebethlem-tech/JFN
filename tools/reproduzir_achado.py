# -*- coding: utf-8 -*-
"""Reproduz um achado do contrato único (O5.2): relê a FONTE do achado, reexecuta a parte determinística (a
conversão pelo adaptador e o sha256 das entradas) e compara com o que foi gravado.

    python tools/reproduzir_achado.py <id> --esquema achados        # achado gravado no PG (JFN_EVIDENCIAS_DSN)
    python tools/reproduzir_achado.py --origem alertas:133528       # sem PG: só mostra a execução da fonte

Veredito:
  REPRODUZIDO    mesma regra, mesma versão do código e mesmo hash de entradas e resultado
  VERSAO_MUDOU   entradas iguais, mas o código da regra mudou desde a gravação (rodar a regra de novo para saber
                 se o resultado se mantém — o legado não guardou o insumo completo para reexecutá-la aqui)
  DIVERGE        a fonte hoje registra outra coisa (lista dos campos)
  FONTE_AUSENTE  a linha de origem não existe mais (apagada pela poda do gravador ou banco diferente)

LIMITE declarado: as três gerações legadas gravam o RESULTADO, não o insumo inteiro; "reexecutar" aqui é reler a
linha e refazer a conversão e o hash. Reexecutar a lógica da regra fica para o E10 (O5.3), quando a execução passar
a gravar as entradas pelo `execucao_regra`.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from compliance_agent.adaptadores import achados as A  # noqa: E402

RAIZ = Path(__file__).resolve().parents[1]


def _ro(caminho: Path) -> sqlite3.Connection:
    c = sqlite3.connect(f"file:{caminho}?mode=ro", uri=True, timeout=30)
    c.row_factory = sqlite3.Row
    return c


def ler_origem(origem: str, compliance_db: Path, achados_db: Path):
    """Relê a linha de origem e devolve o Achado reconvertido (None se a linha não existe)."""
    fonte, _, chave = origem.partition(":")
    if fonte == "alertas":
        with _ro(compliance_db) as c:
            r = c.execute(f"SELECT {','.join(A.COLS_ALERTA)} FROM alertas WHERE id=?", (int(chave),)).fetchone()
        return A.de_alerta(dict(r)) if r else None
    if fonte in A.TABELAS_DET:
        partes = chave.split("|")
        chaves = (A.TABELAS_DET[fonte][0], "detector") + (("processo",) if fonte == "achado_detector" else ())
        where = " AND ".join(f"{k}=?" for k in chaves)
        with _ro(achados_db) as c:
            r = c.execute(f"SELECT * FROM {fonte} WHERE {where}", partes).fetchone()
        return A.de_achado_db(fonte, dict(r)) if r else None
    raise ValueError(f"origem não reproduzível por este utilitário: {origem!r}")


def comparar(gravado: dict, atual) -> dict:
    """`gravado`: regra_id, regra_versao, entradas_hash, resultado (como no PG). `atual`: Achado reconvertido."""
    if atual is None:
        return {"veredito": "FONTE_AUSENTE", "diferencas": []}
    e = atual.execucao
    dif = [c for c, a, b in (("regra_id", gravado["regra_id"], e.regra_id),
                             ("entradas_hash", gravado["entradas_hash"].strip(), e.entradas_hash),
                             ("resultado", gravado["resultado"], e.resultado)) if a != b]
    if dif:
        return {"veredito": "DIVERGE", "diferencas": dif}
    if gravado["regra_versao"] != e.versao:
        return {"veredito": "VERSAO_MUDOU", "diferencas": ["regra_versao"],
                "versao_gravada": gravado["regra_versao"], "versao_atual": e.versao}
    return {"veredito": "REPRODUZIDO", "diferencas": []}


def ler_gravado(achado_id: int, esquema: str) -> dict | None:
    import psycopg

    from compliance_agent.evidencias import dsn_vigente
    from compliance_agent.fluxo.schema import validar_esquema
    s = validar_esquema(esquema)
    with psycopg.connect(dsn_vigente()) as con:
        r = con.execute(f'SELECT e.origem, e.regra_id, e.regra_versao, e.entradas_hash, e.resultado '
                        f'FROM "{s}".achado a JOIN "{s}".execucao_regra e ON e.id = a.execucao_regra_id '
                        f'WHERE a.id = %s', (achado_id,)).fetchone()
    return dict(zip(("origem", "regra_id", "regra_versao", "entradas_hash", "resultado"), r)) if r else None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("id", nargs="?", type=int, help="id do achado no PG")
    ap.add_argument("--esquema", default="achados")
    ap.add_argument("--origem", help="reproduzir direto da origem (sem PG)")
    ap.add_argument("--compliance-db", type=Path, default=RAIZ / "data" / "compliance.db")
    ap.add_argument("--achados-db", type=Path, default=RAIZ / "data" / "achados.db")
    a = ap.parse_args(argv)
    if a.origem:
        atual = ler_origem(a.origem, a.compliance_db, a.achados_db)
        print(json.dumps(atual.execucao.model_dump(mode="json") if atual else {"veredito": "FONTE_AUSENTE"},
                         ensure_ascii=False, indent=1))
        return 0 if atual else 1
    if a.id is None:
        ap.error("informe o id do achado ou --origem")
    gravado = ler_gravado(a.id, a.esquema)
    if gravado is None:
        print(f"achado {a.id} não existe no esquema {a.esquema}")
        return 2
    r = comparar(gravado, ler_origem(gravado["origem"], a.compliance_db, a.achados_db))
    print(json.dumps({"achado": a.id, "origem": gravado["origem"], **r}, ensure_ascii=False, indent=1))
    return 0 if r["veredito"] == "REPRODUZIDO" else 1


if __name__ == "__main__":
    sys.exit(main())
