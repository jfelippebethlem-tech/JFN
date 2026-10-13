# -*- coding: utf-8 -*-
"""Lista de termos para a busca livre no SEI municipal (VM-2 `sei_pcrj_busca.py`), regenerada por cron.

Fontes: fornecedores do ContasRio por pago (2023+), fornecedores de TAC do Estado, expressões fixas.
Termos já buscados continuam na lista (a VM-2 pula os feitos); o que muda é a entrada de fornecedor
novo. Sem esta regeneração a busca "parava" por falta de trabalho e o laudo de saúde acusava frescor.

    python -m tools.pcrj_sei_busca_termos       # grava ~/shared-brain/sei_pcrj_busca_termos.txt
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from compliance_agent.pcrj.db import DB_PATH

SAIDA = Path.home() / "shared-brain" / "sei_pcrj_busca_termos.txt"
COMPLIANCE_DB = Path(__file__).resolve().parents[1] / "data" / "compliance.db"
STOP = {"LTDA", "LTDA.", "S/A", "S.A.", "SA", "ME", "EPP", "EIRELI", "E", "DE", "DO", "DA", "DOS", "DAS", "-", "COMERCIO",
        "SERVICOS", "SERVIÇOS", "EMPRESA", "CIA", "COMPANHIA", "INDUSTRIA", "INDÚSTRIA", "BRASIL", "RIO", "JANEIRO",
        "MUNICIPAL", "MUNICIPIO", "MUNICÍPIO", "SECRETARIA", "FUNDACAO", "FUNDAÇÃO", "INSTITUTO", "ASSOCIACAO", "ASSOCIAÇÃO",
        "SOCIEDADE", "EMPREENDIMENTOS", "PARTICIPACOES", "PARTICIPAÇÕES", "GRUPO", "CONSULTORIA", "ENGENHARIA", "CONSTRUCOES",
        "CONSTRUÇÕES", "MEDICA", "MÉDICA", "HOSPITALAR", "LOCACAO", "LOCAÇÃO", "TRANSPORTES"}
EXPRESSOES = ["dispensa emergencial", "inexigibilidade", "termo de ajuste de contas", "reconhecimento de dívida", "indenização",
              "aditivo prorrogação", "registro de preços", "OSCIP", "organização social", "contrato de gestão"]


def chave(nome: str | None) -> str | None:
    toks = [t for t in re.split(r"[\s,/]+", (nome or "").upper()) if t and t not in STOP and not t.isdigit() and len(t) > 2]
    return " ".join(toks[:2]) if toks else None


def gerar(db_path=None, compliance_db=None, limite_fornecedores: int = 600) -> dict:
    termos: dict[str, tuple[str, int]] = {}
    con = sqlite3.connect(f"file:{db_path or DB_PATH}?mode=ro", uri=True)
    try:
        for nome, pago in con.execute("SELECT favorecido_nome, sum(coalesce(total_pago,0)) FROM contasrio_contrato "
                                      "WHERE ano>=2023 AND favorecido_doc IS NOT NULL GROUP BY favorecido_doc ORDER BY 2 DESC LIMIT ?",
                                      (limite_fornecedores,)):
            k = chave(nome)
            if k and k not in termos:
                termos[k] = ("contasrio", int(pago or 0))
    finally:
        con.close()
    cdb = Path(compliance_db or COMPLIANCE_DB)
    if cdb.exists():
        c2 = sqlite3.connect(f"file:{cdb}?mode=ro", uri=True)
        try:
            if c2.execute("SELECT 1 FROM sqlite_master WHERE name='doerj_tac_sinal'").fetchone():
                for forn, soma in c2.execute("SELECT fornecedor, soma_tac FROM doerj_tac_sinal ORDER BY soma_tac DESC"):
                    k = chave(forn)
                    if k and k not in termos:
                        termos[k] = ("tac", int(soma or 0))
        finally:
            c2.close()
    for e in EXPRESSOES:
        termos.setdefault(e, ("termo", 0))
    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    SAIDA.write_text("".join(f"{k}\t{o}\t{v}\n" for k, (o, v) in termos.items()), encoding="utf-8")
    return {"termos": len(termos), "saida": str(SAIDA)}


if __name__ == "__main__":
    import json
    print(json.dumps(gerar(), ensure_ascii=False))
