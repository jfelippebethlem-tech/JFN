# -*- coding: utf-8 -*-
"""
TCE-RJ Dados Abertos — coletor (Onda 2).

A API pública do TCE-RJ (https://dados.tcerj.tc.br/api/v1/) responde da VM (HTTP 200, sem auth) e traz o
**número do processo SEI como chave** nos contratos/compras — o que permite correlacionar OB↔contrato↔processo
**SEM scrapear o sei.rj.gov.br** (bloqueado por WAF). Resposta é JSON com BOM (decodificar utf-8-sig).

Ingere:
  - contratos_estado            -> contratos_tcerj      (Processo SEI, CNPJ, objeto, modalidade, valores)
  - compras_diretas_estado      -> compras_diretas_tcerj (dispensa/inexigibilidade + EnquadramentoLegal)
  - penalidades_ressarcimento_estado -> penalidades_tcerj (multas/condenações TCE-RJ)

E correlaciona o nº SEI dos contratos com `ordens_bancarias.numero_sei` e `ob_orcamentaria_siafe.processo`.

CLI:
    python -m compliance_agent.collectors.tcerj_aberto --ingerir          # baixa as 3 bases
    python -m compliance_agent.collectors.tcerj_aberto --correlacionar    # liga OB<->contrato pelo SEI
    python -m compliance_agent.collectors.tcerj_aberto --stats
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import time
from datetime import datetime

import httpx

_BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_DB = os.environ.get("JFN_DB", os.path.join(_BASE, "data", "compliance.db"))
API = "https://dados.tcerj.tc.br/api/v1"
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; JFN-auditor/1.0)"}

_DDL = {
    "contratos_tcerj": """
        CREATE TABLE IF NOT EXISTS contratos_tcerj (
            id TEXT PRIMARY KEY, processo TEXT, sei_norm TEXT, ano_processo INTEGER,
            data_contratacao TEXT, valor_contrato REAL, status TEXT, unidade TEXT, objeto TEXT,
            fornecedor TEXT, cnpj TEXT, vig_inicio TEXT, vig_fim TEXT, criterio_julgamento TEXT,
            num_contratacao TEXT, valor_empenhado REAL, valor_liquidado REAL, valor_pago REAL, ingerido_em TEXT
        )""",
    "compras_diretas_tcerj": """
        CREATE TABLE IF NOT EXISTS compras_diretas_tcerj (
            id TEXT PRIMARY KEY, processo TEXT, sei_norm TEXT, ano_processo INTEGER, valor REAL,
            objeto TEXT, afastamento TEXT, enquadramento_legal TEXT, unidade TEXT, fornecedor TEXT,
            item TEXT, quantidade TEXT, valor_unitario REAL, ingerido_em TEXT
        )""",
    "penalidades_tcerj": """
        CREATE TABLE IF NOT EXISTS penalidades_tcerj (
            id TEXT PRIMARY KEY, processo TEXT, ano_condenacao INTEGER, tipo TEXT, valor REAL,
            condenacao TEXT, tipo_ente TEXT, orgao TEXT, grupo_natureza TEXT, data_sessao TEXT, ingerido_em TEXT
        )""",
}


def _con():
    return sqlite3.connect(_DB)


def _ddl(con):
    for sql in _DDL.values():
        con.execute(sql)
    con.execute("CREATE INDEX IF NOT EXISTS ix_contr_sei ON contratos_tcerj(sei_norm)")
    con.execute("CREATE INDEX IF NOT EXISTS ix_contr_cnpj ON contratos_tcerj(cnpj)")
    con.execute("CREATE INDEX IF NOT EXISTS ix_compra_sei ON compras_diretas_tcerj(sei_norm)")
    con.commit()


def sei_norm(s: str) -> str:
    """Canoniza o nº de processo p/ casar entre fontes: tira BOM/asteriscos, mantém só dígitos."""
    s = (s or "").strip().lstrip("*").strip()
    return re.sub(r"\D", "", s)


def _hid(*parts) -> str:
    return hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:20]


def _fnum(v):
    """Converte número da API p/ float. Aceita float/int e o formato BR em string ('7.188,00')."""
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    # formato BR: ponto = milhar, vírgula = decimal  ->  remove pontos, troca vírgula por ponto
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def _fetch(endpoint: str, inicio: int, limite: int, tentativas: int = 4) -> list:
    """GET paginado com BOM-aware decode + backoff."""
    url = f"{API}/{endpoint}?inicio={inicio}&limite={limite}&jsonfull=true"
    for t in range(1, tentativas + 1):
        try:
            with httpx.Client(timeout=60, headers=_HEADERS, follow_redirects=True) as c:
                r = c.get(url)
                r.raise_for_status()
                data = json.loads(r.content.decode("utf-8-sig"))
                return data if isinstance(data, list) else []
        except Exception as exc:  # noqa: BLE001
            if t == tentativas:
                print(f"  [TCE-RJ] falha {endpoint} inicio={inicio}: {str(exc)[:90]}")
                return []
            time.sleep(2 * t)
    return []


def _ingerir_paginado(endpoint: str, tabela: str, mapper, limite: int = 1000, maxreg: int | None = None) -> int:
    con = _con(); _ddl(con)
    agora = datetime.now().isoformat(timespec="seconds")
    inicio, total = 0, 0
    while True:
        lote = _fetch(endpoint, inicio, limite)
        if not lote:
            break
        rows = [mapper(r, agora) for r in lote]
        cols = len(rows[0])
        con.executemany(f"INSERT OR REPLACE INTO {tabela} VALUES ({','.join('?'*cols)})", rows)
        con.commit()
        total += len(lote)
        print(f"  [{tabela}] {total} ingeridos...")
        if len(lote) < limite or (maxreg and total >= maxreg):
            break
        inicio += limite
    con.close()
    return total


def ingerir_contratos(maxreg=None) -> int:
    def m(r, agora):
        proc = r.get("Processo", "")
        return (_hid(proc, r.get("CPFCNPJ"), r.get("Objeto"), r.get("DataContratacao")),
                proc, sei_norm(proc), r.get("AnoProcesso"), r.get("DataContratacao"),
                _fnum(r.get("ValorTotalContrato")), r.get("StatusContratacao"), r.get("Unidade"),
                r.get("Objeto"), r.get("Fornecedor"), re.sub(r"\D", "", r.get("CPFCNPJ") or ""),
                r.get("DataInicioVigencia"), r.get("DataFimVigencia"), r.get("CriterioJulgamento"),
                r.get("Contratacao"), _fnum(r.get("ValorTotalEmpenhado")), _fnum(r.get("ValorTotalLiquidado")),
                _fnum(r.get("ValorTotalPago")), agora)
    return _ingerir_paginado("contratos_estado", "contratos_tcerj", m, maxreg=maxreg)


def ingerir_compras_diretas(maxreg=None) -> int:
    def m(r, agora):
        proc = r.get("Processo", "")
        return (_hid(proc, r.get("Item"), r.get("Objeto")), proc, sei_norm(proc), r.get("AnoProcesso"),
                _fnum(r.get("ValorProcesso")), r.get("Objeto"), r.get("Afastamento"),
                r.get("EnquadramentoLegal"), r.get("Unidade"), r.get("FornecedorVencedor"),
                r.get("Item"), str(r.get("Quantidade")), _fnum(r.get("ValorUnitario")), agora)
    return _ingerir_paginado("compras_diretas_estado", "compras_diretas_tcerj", m, maxreg=maxreg)


def ingerir_penalidades(maxreg=None) -> int:
    def m(r, agora):
        proc = r.get("Processo", "")
        return (_hid(proc, r.get("Condenacao"), r.get("Tipo")), proc, r.get("AnoCondenacao"),
                r.get("Tipo"), _fnum(r.get("ValorPenalidade")), r.get("Condenacao"), r.get("TipoEnte"),
                r.get("NomeOrgao"), r.get("GrupoNatureza"), r.get("DataSessao"), agora)
    return _ingerir_paginado("penalidades_ressarcimento_estado", "penalidades_tcerj", m, maxreg=maxreg)


_SEI_OB = "REPLACE(REPLACE(REPLACE(REPLACE(COALESCE(numero_sei,''),'SEI-',''),'-',''),'/',''),'.','')"
_SEI_PROC = "REPLACE(REPLACE(REPLACE(REPLACE(COALESCE(processo,''),'SEI-',''),'-',''),'/',''),'.','')"


def correlacionar() -> dict:
    """Correlaciona contratos TCE-RJ às OBs por (1) nº SEI [preciso] e (2) CNPJ [alta cobertura — enriquece o
    fornecedor com objeto/modalidade/EnquadramentoLegal do contrato]."""
    con = _con(); _ddl(con)
    # (1) link preciso por SEI: ordens_bancarias.numero_sei OU ob_orcamentaria_siafe.processo
    con.execute("DROP TABLE IF EXISTS ob_contrato_tcerj")
    con.execute(f"""CREATE TABLE ob_contrato_tcerj AS
        SELECT o.id AS ob_id, o.numero_ob, o.valor AS valor_ob, c.processo, c.objeto,
               c.criterio_julgamento, c.valor_contrato, c.valor_pago, c.fornecedor, c.cnpj AS cnpj_contrato, 'SEI' AS via
        FROM ordens_bancarias o JOIN contratos_tcerj c
          ON c.sei_norm != '' AND c.sei_norm = {_SEI_OB.replace('numero_sei','o.numero_sei')}""")
    con.commit()
    n_sei = con.execute("SELECT COUNT(*) FROM ob_contrato_tcerj").fetchone()[0]
    n_siafe = con.execute(f"""SELECT COUNT(*) FROM ob_orcamentaria_siafe s JOIN contratos_tcerj c
        ON c.sei_norm!='' AND c.sei_norm = {_SEI_PROC.replace('processo','s.processo')}""").fetchone()[0]
    # (2) cobertura por CNPJ (enriquecimento do fornecedor)
    cnpjs = con.execute("""SELECT COUNT(DISTINCT o.favorecido_cpf) FROM ordens_bancarias o
        JOIN contratos_tcerj c ON c.cnpj!='' AND c.cnpj=o.favorecido_cpf""").fetchone()[0]
    obs_cnpj = con.execute("""SELECT COUNT(*) FROM ordens_bancarias o WHERE EXISTS
        (SELECT 1 FROM contratos_tcerj c WHERE c.cnpj=o.favorecido_cpf AND c.cnpj!='')""").fetchone()[0]
    con.close()
    return {"ok": True, "link_sei_ordens": n_sei, "link_sei_siafe": n_siafe,
            "cnpjs_em_comum": cnpjs, "obs_com_fornecedor_contratado": obs_cnpj}


def contratos_de_fornecedor(cnpj: str, limite: int = 100) -> list[dict]:
    """Contratos + compras diretas do TCE-RJ de um CNPJ — insumo do Lex (objeto, critério, valores, dispensa/
    EnquadramentoLegal). Casa compras diretas pelo NOME do fornecedor (a base não traz CNPJ na compra direta)."""
    cnpj = re.sub(r"\D", "", cnpj or "")
    con = _con(); _ddl(con); con.row_factory = sqlite3.Row
    try:
        ctr = [dict(r) for r in con.execute(
            "SELECT processo, ano_processo, objeto, criterio_julgamento, valor_contrato, valor_empenhado, "
            "valor_liquidado, valor_pago, unidade, status, vig_inicio, vig_fim "
            "FROM contratos_tcerj WHERE cnpj=? ORDER BY valor_contrato DESC LIMIT ?", (cnpj, limite))]
        nome = con.execute("SELECT fornecedor FROM contratos_tcerj WHERE cnpj=? LIMIT 1", (cnpj,)).fetchone()
        cmp = []
        if nome and nome[0]:
            cmp = [dict(r) for r in con.execute(
                "SELECT processo, ano_processo, objeto, afastamento, enquadramento_legal, valor, unidade "
                "FROM compras_diretas_tcerj WHERE fornecedor LIKE ? ORDER BY valor DESC LIMIT ?",
                (f"%{nome[0]}%", limite))]
    finally:
        con.close()
    return [{"_tipo": "contrato", **c} for c in ctr] + [{"_tipo": "compra_direta", **c} for c in cmp]


def stats() -> dict:
    con = _con(); _ddl(con)
    def cnt(t):
        try:
            return con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        except Exception:
            return 0
    out = {t: cnt(t) for t in ["contratos_tcerj", "compras_diretas_tcerj", "penalidades_tcerj"]}
    out["contratos_com_sei"] = con.execute("SELECT COUNT(*) FROM contratos_tcerj WHERE sei_norm!=''").fetchone()[0]
    con.close()
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Coletor TCE-RJ Dados Abertos (Onda 2).")
    ap.add_argument("--ingerir", action="store_true", help="baixa contratos + compras diretas + penalidades")
    ap.add_argument("--correlacionar", action="store_true", help="liga OB<->contrato pelo nº SEI")
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--max", type=int, default=None, help="máx. de registros por base (teste)")
    a = ap.parse_args()
    if a.ingerir:
        print(json.dumps({"contratos": ingerir_contratos(a.max),
                          "compras_diretas": ingerir_compras_diretas(a.max),
                          "penalidades": ingerir_penalidades(a.max)}, ensure_ascii=False, indent=2))
    if a.correlacionar:
        print(json.dumps(correlacionar(), ensure_ascii=False, indent=2))
    if a.stats:
        print(json.dumps(stats(), ensure_ascii=False, indent=2))
