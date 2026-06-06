# -*- coding: utf-8 -*-
"""
Correlação OB ↔ Processo SEI.

O SIAFE (tela OB Orçamentária, tabela `ob_orcamentaria_siafe`) traz, para cada Ordem Bancária, o **número do
processo SEI** que a originou (campo `processo`, ex.: `SEI-040009/002078/2025`). A base TFE
(`ordens_bancarias`) tem o favorecido (CNPJ) mas **não** o SEI. Este módulo casa as duas pelo `numero_ob` e
preenche `ordens_bancarias.numero_sei`/`numero_processo` com o SEI do SIAFE (**SIAFE prepondera**).

Resultado: cada OB passa a ter quem recebeu (TFE) E o processo SEI de origem (SIAFE) — base para o agente
jurídico **Lex** puxar o processo inteiro (edital, contrato, pagamento) e emitir parecer.

USO:
    cd ~/JFN && .venv/bin/python -m compliance_agent.correlacao_sei            # correlaciona e mostra stats
    from compliance_agent.correlacao_sei import correlacionar, obs_por_processo, processo_de_ob
"""
from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_DB = Path(os.environ.get("JFN_DATA_DIR", _REPO / "data")) / "compliance.db"

_SEI_RE = re.compile(r"SEI[-\s]?\d{6}/\d{6}/\d{4}", re.I)


def _norm_ob(x: str) -> str:
    """Normaliza o nº da OB (o SIAFE às vezes põe sufixo 'P', ex.: 2025OB03447P)."""
    return re.sub(r"P$", "", (x or "").strip())


def correlacionar() -> dict:
    """Preenche `ordens_bancarias.numero_sei`/`numero_processo` a partir do SIAFE (prepondera). Retorna stats."""
    if not _DB.exists():
        return {"ok": False, "erro": "compliance.db ausente"}
    con = sqlite3.connect(str(_DB))
    try:
        tem = con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='ob_orcamentaria_siafe'").fetchone()
        if not tem:
            return {"ok": False, "erro": "Sem dados SIAFE ainda — rode a coleta (/siafe <ano>)."}
        # índice p/ o update ser rápido
        con.execute("CREATE INDEX IF NOT EXISTS ix_ob_numero ON ordens_bancarias(numero_ob)")
        # casa por numero_ob + UG Pagadora (o numero_ob NÃO é único entre UGs; casar só por OB sobrecola).
        pares = [(p.strip(), _norm_ob(ob), (ugp or "").strip()) for ob, p, ugp in
                 con.execute("SELECT numero_ob, processo, ug_pagadora FROM ob_orcamentaria_siafe "
                             "WHERE processo IS NOT NULL AND processo!=''")]
        atualizadas = 0
        for sei, obn, ugp in pares:
            if ugp:
                cur = con.execute(
                    "UPDATE ordens_bancarias SET numero_sei=?, numero_processo=COALESCE(NULLIF(numero_processo,''), ?) "
                    "WHERE numero_ob=? AND ug_codigo=?", (sei, sei, obn, ugp))
            else:
                cur = con.execute(
                    "UPDATE ordens_bancarias SET numero_sei=?, numero_processo=COALESCE(NULLIF(numero_processo,''), ?) "
                    "WHERE numero_ob=?", (sei, sei, obn))
            atualizadas += cur.rowcount
        con.commit()
        com_sei = con.execute("SELECT COUNT(*) FROM ordens_bancarias WHERE numero_sei IS NOT NULL AND numero_sei!=''").fetchone()[0]
        n_proc = con.execute("SELECT COUNT(DISTINCT numero_sei) FROM ordens_bancarias WHERE numero_sei IS NOT NULL AND numero_sei!=''").fetchone()[0]
        return {"ok": True, "pares_siafe": len(pares), "linhas_atualizadas": atualizadas,
                "ordens_com_sei": com_sei, "processos_sei_distintos": n_proc}
    finally:
        con.close()


def obs_por_processo(sei: str) -> list[dict]:
    """Todas as OBs (TFE) vinculadas a um processo SEI. Para o Lex saber o que o processo pagou."""
    if not _DB.exists():
        return []
    con = sqlite3.connect(_DB); con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            "SELECT numero_ob, data_pagamento, ug_codigo, ug_nome, favorecido_cpf, favorecido_nome, valor, exercicio "
            "FROM ordens_bancarias WHERE numero_sei=? ORDER BY data_pagamento", (sei.strip(),)).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


def processo_de_ob(numero_ob: str) -> str:
    """O processo SEI de uma OB (ou '')."""
    if not _DB.exists():
        return ""
    con = sqlite3.connect(_DB)
    try:
        r = con.execute("SELECT numero_sei FROM ordens_bancarias WHERE numero_ob=? AND numero_sei IS NOT NULL AND numero_sei!='' LIMIT 1",
                        (_norm_ob(numero_ob),)).fetchone()
        return r[0] if r else ""
    finally:
        con.close()


def processos_de_fornecedor(cnpj: str, limite: int = 200) -> list[dict]:
    """Processos SEI ligados a um CNPJ (via OBs), com nº de OBs e valor total. Insumo do Lex por fornecedor."""
    if not _DB.exists():
        return []
    cnpj = re.sub(r"\D", "", cnpj or "")
    con = sqlite3.connect(_DB); con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            "SELECT numero_sei, COUNT(*) n_obs, ROUND(SUM(valor),2) total, MIN(exercicio) ano "
            "FROM ordens_bancarias WHERE favorecido_cpf=? AND numero_sei IS NOT NULL AND numero_sei!='' "
            "GROUP BY numero_sei ORDER BY total DESC LIMIT ?", (cnpj, limite)).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


if __name__ == "__main__":
    import json
    print(json.dumps(correlacionar(), ensure_ascii=False, indent=1))
