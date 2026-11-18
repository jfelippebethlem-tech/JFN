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

from compliance_agent.cruzamentos_intel import _ob_paga

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
                 # ob-qualquer-status: só casa OB → processo (metadado); não soma pagamento
                 con.execute("SELECT numero_ob, processo, ug_pagadora FROM ob_orcamentaria_siafe "
                             "WHERE processo IS NOT NULL AND processo!=''")]
        # UPDATE em lote (executemany) — antes era 1 execute() por par (N+1, ~65k chamadas). O ramo "com/sem
        # ug_codigo" foi unificado num só SQL via `(?='' OR ug_codigo=?)` p/ preservar a ORDEM exata da iteração
        # original (mesma semântica linha-a-linha). Mais rápido sem mudar resultado.
        params = [(sei, sei, obn, ugp, ugp) for sei, obn, ugp in pares]
        cur = con.executemany(
            "UPDATE ordens_bancarias SET numero_sei=?, numero_processo=COALESCE(NULLIF(numero_processo,''), ?) "
            "WHERE numero_ob=? AND (?='' OR ug_codigo=?)", params)
        atualizadas = cur.rowcount
        con.commit()
        com_sei = con.execute("SELECT COUNT(*) FROM ordens_bancarias WHERE numero_sei IS NOT NULL AND numero_sei!=''").fetchone()[0]
        n_proc = con.execute("SELECT COUNT(DISTINCT numero_sei) FROM ordens_bancarias WHERE numero_sei IS NOT NULL AND numero_sei!=''").fetchone()[0]
        return {"ok": True, "pares_siafe": len(pares), "linhas_atualizadas": atualizadas,
                "ordens_com_sei": com_sei, "processos_sei_distintos": n_proc}
    finally:
        con.close()


def variantes_sei(sei: str) -> list[str]:
    """As duas grafias do MESMO processo: com e sem o prefixo `SEI-`.

    O SIAFE grava o processo na notação oficial (`SEI-080001/001211/2024`) e é dela que
    `ordens_bancarias.numero_sei` é copiado — **84,3% das 212.994 linhas preenchidas trazem o
    prefixo**, contra 3,0% sem ele. Quem consulta, porém, costuma ter o número nu (é assim que ele
    aparece na pasta do arquivo do SEI e nos relatórios). O `WHERE numero_sei=?` casava, então, com
    3% do que existe — e devolvia lista vazia, que se lê como "processo sem pagamento" quando na
    verdade é "chave escrita de outro jeito".

    Não é dado corrompido e não pede migração: as duas grafias são legítimas. Pede normalização na
    consulta. (Há ainda 12,1% de processos com OUTRA numeração, não-SEI, que esta função não
    alcança por definição — e 0,6% de fato irregulares, como `-150157/001357/2023`.)
    """
    nu = re.sub(r"^SEI[-\s]?", "", (sei or "").strip(), flags=re.I)
    return [nu, f"SEI-{nu}"] if nu else []


def obs_por_processo(sei: str) -> list[dict]:
    """Todas as OBs (TFE) vinculadas a um processo SEI. Para o Lex saber o que o processo pagou."""
    if not _DB.exists():
        return []
    v = variantes_sei(sei)
    if not v:
        return []
    con = sqlite3.connect(_DB); con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            "SELECT numero_ob, data_pagamento, ug_codigo, ug_nome, favorecido_cpf, favorecido_nome, valor, exercicio "
            "FROM ordens_bancarias WHERE numero_sei IN (?,?) ORDER BY data_pagamento", tuple(v)).fetchall()
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
    """Processos SEI ligados a um CNPJ (via OBs), com nº de OBs e valor total. Insumo do Lex por
    fornecedor. UNIÃO das duas fontes (2026-07-22): `ob_orcamentaria_siafe.processo` (SIAFE = fonte
    de verdade, regra da casa) ∪ `ordens_bancarias.numero_sei` (espelho TFE) — antes só o TFE era
    lido e processos que SÓ a SIAFE conhece ficavam invisíveis p/ o Lex (caso CPASC: 1 de 2)."""
    if not _DB.exists():
        return []
    cnpj = re.sub(r"\D", "", cnpj or "")
    con = sqlite3.connect(_DB); con.row_factory = sqlite3.Row
    try:
        por_proc: dict[str, dict] = {}
        for sql, params in (
            ("SELECT numero_sei p, COUNT(*) n_obs, ROUND(SUM(valor),2) total, MIN(exercicio) ano "
             "FROM ordens_bancarias WHERE favorecido_cpf=? AND numero_sei IS NOT NULL AND numero_sei!='' "
             "GROUP BY numero_sei", (cnpj,)),
            ("SELECT processo p, COUNT(*) n_obs, ROUND(SUM(valor),2) total, MIN(exercicio) ano "
             f"FROM ob_orcamentaria_siafe WHERE {_ob_paga(con)} AND REPLACE(REPLACE(REPLACE(credor,'.',''),'/',''),'-','')=? "
             "AND processo IS NOT NULL AND processo!='' GROUP BY processo", (cnpj,)),
        ):
            try:
                for r in con.execute(sql, params):
                    d = por_proc.setdefault(r["p"], {"numero_sei": r["p"], "n_obs": 0,
                                                     "total": 0.0, "ano": r["ano"]})
                    # fontes se sobrepõem (mesma OB nas duas tabelas): fica o MAIOR, não a soma
                    d["n_obs"] = max(d["n_obs"], r["n_obs"] or 0)
                    d["total"] = max(d["total"], r["total"] or 0.0)
                    d["ano"] = min(d["ano"] or r["ano"], r["ano"]) if r["ano"] else d["ano"]
            except sqlite3.OperationalError:
                continue  # tabela ausente nesta base (ex.: base de teste) — segue com a outra fonte
        out = sorted(por_proc.values(), key=lambda d: -d["total"])[:limite]
        return out
    finally:
        con.close()


def estado_do_laudo(modelo: str | None) -> tuple[str, str]:
    """Estado do laudo de execução pela proveniência (regra 9). 18/11/2026: 92% dos 7.919 laudos eram de outro modelo
    sem conferência do Claude, e o Opus rebaixou o risco em 39 dos 43 'risco alto' que conferiu — laudo sem a
    conferência é PENDENTE, nunca conclusão."""
    m = str(modelo or "").strip()
    if "claude" in m.lower():
        return "VERIFICADO", "conferido/feito pelo Claude"
    if m.startswith("regra:"):
        return "REGRA", "regra determinística (sem documento de execução nos autos capturados)"
    return "PENDENTE", f"laudo de {m.split(' ')[0] or 'modelo desconhecido'} sem conferência do Opus"


def execucao_de_fornecedor(cnpj: str, limite: int = 200) -> list[dict]:
    """Cruza os processos SEI pagos do fornecedor com a perícia de EXECUÇÃO (lex_execucao): contratos pagos cuja
    entrega/execução NÃO foi comprovada nos autos. Indício, não prova.

    Pago = OB do SIAFE (`ob_orcamentaria_siafe`, Contabilizada e não devolvida — `_ob_paga`), nunca o espelho TFE
    (18/11/2026: lia `ordens_bancarias`). O nº do processo vem em grafias diferentes nas duas pontas
    ('SEI-330002/031566/24' × '330002/031566/2024'): o casamento é pela chave de `lex_execucao._chave_processo`."""
    if not _DB.exists():
        return []
    from tools.lex_execucao import _chave_processo
    cnpj = re.sub(r"\D", "", cnpj or "")
    con = sqlite3.connect(_DB); con.row_factory = sqlite3.Row
    try:
        por: dict[str, dict] = {}
        for r in con.execute(f"SELECT processo, COUNT(*) n, SUM(valor) v FROM ob_orcamentaria_siafe "
                             f"WHERE credor=? AND {_ob_paga(con)} AND processo LIKE '%/%' GROUP BY processo", (cnpj,)):
            k = _chave_processo(r["processo"])
            if not k:
                continue
            a = por.setdefault(k, {"numero_sei": r["processo"], "n_obs": 0, "total": 0.0})
            a["n_obs"] += r["n"]
            a["total"] += r["v"] or 0.0
        if not por:
            return []
        laudos = {}
        for r in con.execute("SELECT numero_sei, execucao_comprovada AS exec, nota_risco AS nota, resumo, indicios, "
                             "em AS avaliado_em, modelo FROM lex_execucao"):
            k = _chave_processo(r["numero_sei"])
            if k in por:
                laudos[k] = dict(r)
        out = []
        for k, a in sorted(por.items(), key=lambda kv: -kv[1]["total"])[:limite]:
            x = {**a, "total": round(a["total"], 2), "fonte_pago": "SIAFE (OB Contabilizada, sem devolvida)",
                 "exec": None, "nota": None, "resumo": None, "indicios": None, "avaliado_em": None, "modelo": None}
            if k in laudos:
                x.update({c: laudos[k][c] for c in ("exec", "nota", "resumo", "indicios", "avaliado_em", "modelo")})
                x["numero_sei"] = laudos[k]["numero_sei"] or a["numero_sei"]
                x["estado"], x["estado_motivo"] = estado_do_laudo(x.get("modelo"))
            out.append(x)
        return out
    except sqlite3.OperationalError:
        return []                                  # base sem SIAFE/laudos: o relatório declara INDISPONÍVEL
    finally:
        con.close()


def processos_risco_de_orgao(ug: str, limite: int = 30) -> list[dict]:
    """Processos SEI de RISCO (sei_ficha nivel_risco alto/médio) PAGOS por uma UG, com OB total. Insumo do /orgao:
    prioriza a apuração por onde o dinheiro andou. Trata o split de acento em nivel_risco (medio/médio)."""
    if not _DB.exists():
        return []
    con = sqlite3.connect(_DB); con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            "SELECT f.numero_sei, f.nivel_risco, f.objeto, f.red_flags, COUNT(*) n_obs, ROUND(SUM(o.valor),2) total "
            "FROM sei_ficha f JOIN ordens_bancarias o ON o.numero_sei=f.numero_sei "
            "WHERE o.ug_codigo=? AND o.numero_sei IS NOT NULL AND o.numero_sei!='' "
            "AND lower(f.nivel_risco) IN ('alto','medio','médio') "
            "GROUP BY f.numero_sei ORDER BY total DESC LIMIT ?", (str(ug), limite)).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


if __name__ == "__main__":
    import json
    print(json.dumps(correlacionar(), ensure_ascii=False, indent=1))
