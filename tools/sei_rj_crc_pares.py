# -*- coding: utf-8 -*-
"""Colhe do ACERVO SEI do Estado (`data/sei_arquivo/<pasta>/texto/*.txt`) os pares código verificador + CRC que
apontam para OUTRO processo — a chave da Conferência de Autenticidade (O3.8 rota d; `sei/conferencia_autenticidade`).
Marca os que apontam para processo RESTRITO (`data/sei_restritos.json`). Grava `data/sei_rj_crc_pares.json`
({verificador: {crc, processo, restrito, achado_em}}, gitignored). Só leitura do acervo; idempotente.
    python -m tools.sei_rj_crc_pares [--pg]     (--pg: carrega no crc_par do PG da captura)
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

RAIZ = Path("data/sei_arquivo")
RESTRITOS = Path("data/sei_restritos.json")
SAIDA = Path("data/sei_rj_crc_pares.json")


def colher(raiz: Path = RAIZ, restritos: set[str] | None = None) -> dict:
    from compliance_agent.sei.acervo_texto import pasta_para_numero
    from compliance_agent.sei.conferencia_autenticidade import extrair_pares
    restritos = restritos or set()
    out: dict[str, dict] = {}
    for pasta in sorted(p for p in raiz.iterdir() if p.is_dir()):
        dono = re.sub(r"^SEI-", "", pasta_para_numero(pasta.name))
        for t in sorted((pasta / "texto").glob("*.txt")):
            try:
                txt = t.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for par in extrair_pares(txt, dono):
                out.setdefault(par.verificador, {"crc": par.crc, "processo": par.processo,
                                                 "restrito": re.sub(r"\D", "", par.processo) in restritos,
                                                 "achado_em": f"{pasta.name}/texto/{t.name}"})
    return out


def carregar_pg(pares: dict) -> int:
    """Carrega no `crc_par` (captura_005) do PG da captura — o que os workers do E2/E3 leem. Idempotente."""
    from compliance_agent.aplicacao.estagios import arvore as A
    con = A.conectar(None, None)
    try:
        con.cursor().executemany(
            "INSERT INTO crc_par(verificador, crc, processo, restrito, achado_em) VALUES (%s,%s,%s,%s,%s) "
            "ON CONFLICT (verificador) DO UPDATE SET crc = excluded.crc, processo = excluded.processo, "
            "restrito = excluded.restrito, achado_em = excluded.achado_em",
            [(v, d["crc"], d["processo"], d["restrito"], d["achado_em"]) for v, d in pares.items()])
        n = con.execute("SELECT count(*) FROM crc_par").fetchone()[0]
    finally:
        con.close()
    print(f"sei_rj_crc_pares: crc_par no PG com {n} par(es)")
    return n


def main(argv: list[str] | None = None) -> int:
    rest = {k for k, v in json.loads(RESTRITOS.read_text(encoding="utf-8")).items()
            if isinstance(v, dict) and str(v.get("status") or "").startswith("RESTRITO")} if RESTRITOS.is_file() else set()
    pares = colher(RAIZ, rest)
    tmp = SAIDA.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(pares, ensure_ascii=False), encoding="utf-8")
    tmp.replace(SAIDA)
    if "--pg" in (argv if argv is not None else sys.argv[1:]):
        carregar_pg(pares)
    n_r = sum(1 for v in pares.values() if v["restrito"])
    print(f"sei_rj_crc_pares: {len(pares)} par(es) de outro processo; {n_r} apontam para processo restrito "
          f"({len({v['processo'] for v in pares.values() if v['restrito']})} processos)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
