# -*- coding: utf-8 -*-
"""Fatos que a casa já tem sobre o alvo — o requerimento pede o que FALTA, nomeando o que existe.

Alvo aceito: nº de processo SEI (000700.007924/2026-97), nº Processo.rio (SME-PRO-2025/38233),
id de contrato CCON (2509437), CNPJ (14 dígitos) ou nome de fornecedor (busca por prefixo).
Tudo vem de pcrj.db (contasrio_contrato/fiscal, pcrj_processo, pcrj_sei_busca, pcrj_processo_doc).
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from compliance_agent.pcrj.db import DB_PATH

_RX_SEI = re.compile(r"^\d{6}\.\d{6}/20\d{2}-\d{2}$")
_RX_LEGADO = re.compile(r"^[A-Z]{2,5}-[A-Z]{3}-20\d{2}/\d{5}(?:\.\d+)?$", re.I)
_RX_CONTRATO = re.compile(r"^\d{6,12}$")


def classificar_alvo(alvo: str) -> tuple[str, str]:
    """→ (tipo, valor normalizado): processo_sei | processo_legado | contrato | cnpj | nome."""
    a = (alvo or "").strip()
    dig = re.sub(r"\D", "", a)
    if _RX_SEI.match(a):
        return "processo_sei", a
    if _RX_LEGADO.match(a):
        return "processo_legado", a.upper()
    if len(dig) == 14 and (len(a) <= 18):
        return "cnpj", dig
    if _RX_CONTRATO.match(a):
        return "contrato", a
    return "nome", a.upper()


def _con(db_path=None) -> sqlite3.Connection:
    p = Path(db_path or DB_PATH)
    con = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=30)
    con.row_factory = sqlite3.Row
    return con


def _tem(con, tabela: str) -> bool:
    return bool(con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (tabela,)).fetchone())


def _contratos(con, tipo: str, valor: str) -> list[dict]:
    if not _tem(con, "contasrio_contrato"):
        return []
    base = ("SELECT contrato, favorecido_doc, favorecido_nome, orgao, ug, ano, numero_instrumento, data_publicacao, "
            "objeto, situacao, vigencia_ini, vigencia_fim, processo, forma_contratacao, valor_atualizado, "
            "total_pago, url_ccon FROM contasrio_contrato WHERE ")
    if tipo in ("processo_sei", "processo_legado"):
        rows = con.execute(base + "upper(processo)=upper(?)", (valor,)).fetchall()
    elif tipo == "contrato":
        rows = con.execute(base + "contrato=?", (valor,)).fetchall()
    elif tipo == "cnpj":
        rows = con.execute(base + "favorecido_doc=? ORDER BY coalesce(total_pago,0) DESC LIMIT 40", (valor,)).fetchall()
    else:
        rows = con.execute(base + "upper(favorecido_nome) LIKE ? ORDER BY coalesce(total_pago,0) DESC LIMIT 40",
                           (valor + "%",)).fetchall()
    return [dict(r) for r in rows]


def _processo(con, numero: str) -> dict | None:
    if not _tem(con, "pcrj_processo"):
        return None
    r = con.execute("SELECT numero_processo, sistema, assunto, orgao, disponivel, coletado_em FROM pcrj_processo "
                    "WHERE upper(numero_processo)=upper(?)", (numero,)).fetchone()
    return dict(r) if r else None


def _documentos_vistos(con, numero: str) -> list[dict]:
    """Documentos que o SEI mostra mas não abre: a ÁRVORE capturada (todos os docs do processo, com tipo,
    unidade e data) unida ao que a busca livre enxergou. Chave = nº SEI do documento."""
    vistos: dict[str, dict] = {}
    if _tem(con, "pcrj_sei_arvore"):
        for r in con.execute("SELECT doc, tipo, unidade, data FROM pcrj_sei_arvore WHERE upper(numero)=upper(?) ORDER BY data",
                             (numero,)):
            vistos[r["doc"]] = {"prot": r["doc"], "titulo": r["tipo"] or "", "unidade": r["unidade"], "data": r["data"], "fonte": "arvore"}
    if _tem(con, "pcrj_sei_busca"):
        for r in con.execute("SELECT DISTINCT prot, titulo, unidade, data FROM pcrj_sei_busca WHERE upper(processo)=upper(?) "
                             "AND tipo_registro='documento' ORDER BY data", (numero,)):
            vistos.setdefault(r["prot"], {"prot": r["prot"], "titulo": r["titulo"], "unidade": r["unidade"], "data": r["data"], "fonte": "busca"})
    return list(vistos.values())


def _documentos_obtidos(con, numero: str) -> list[dict]:
    if not _tem(con, "pcrj_processo_doc"):
        return []
    rows = con.execute("SELECT seq, tipo, titulo, length(texto) AS n FROM pcrj_processo_doc WHERE upper(numero_processo)=upper(?) "
                       "ORDER BY seq", (numero,)).fetchall()
    return [dict(r) for r in rows]


def _assinantes(con, numero: str) -> list[dict]:
    """Quem assinou no processo: matrícula → nome/órgão pela folha (pcrj_sei_assinante). Sem nome = matrícula só."""
    if not _tem(con, "pcrj_sei_assinatura"):
        return []
    tem_nome = _tem(con, "pcrj_sei_assinante")
    sql = ("SELECT a.matricula, count(*) AS n, min(a.quando) AS primeira, max(a.quando) AS ultima"
           + (", s.nome, s.orgao, s.sigla_ua" if tem_nome else ", NULL AS nome, NULL AS orgao, NULL AS sigla_ua")
           + " FROM pcrj_sei_assinatura a"
           + (" LEFT JOIN pcrj_sei_assinante s ON s.matricula=a.matricula" if tem_nome else "")
           + " WHERE upper(a.numero)=upper(?) GROUP BY a.matricula ORDER BY n DESC")
    return [dict(r) for r in con.execute(sql, (numero,))]


def _fiscais(con, contratos: list[str]) -> list[dict]:
    if not contratos or not _tem(con, "contasrio_fiscal"):
        return []
    q = ",".join("?" * len(contratos))
    rows = con.execute(f"SELECT contrato, fiscal_nome, fiscal_doc FROM contasrio_fiscal WHERE contrato IN ({q})", contratos).fetchall()
    return [dict(r) for r in rows]


def fatos_do_alvo(alvo: str, db_path=None) -> dict:
    """Reúne processos, contratos, fiscais, documentos vistos e obtidos. Nunca inventa: o que não
    existe na base vem como lista vazia, e o requerimento pede a íntegra."""
    tipo, valor = classificar_alvo(alvo)
    con = _con(db_path)
    try:
        contratos = _contratos(con, tipo, valor)
        processos = sorted({c["processo"] for c in contratos if c.get("processo")})
        if tipo in ("processo_sei", "processo_legado") and valor not in processos:
            processos.insert(0, valor)
        detalhe = []
        for p in processos[:12]:
            detalhe.append({"numero": p, "catalogo": _processo(con, p),
                            "documentos_vistos": _documentos_vistos(con, p),
                            "documentos_obtidos": _documentos_obtidos(con, p),
                            "assinantes": _assinantes(con, p)})
        fiscais = _fiscais(con, [c["contrato"] for c in contratos][:40])
    finally:
        con.close()
    fornecedores = sorted({(c.get("favorecido_doc") or "", c.get("favorecido_nome") or "") for c in contratos})
    esfera = "prefeitura" if (contratos or tipo in ("processo_sei", "processo_legado")) else "estado"
    return {"alvo": alvo, "tipo_alvo": tipo, "valor": valor, "esfera_sugerida": esfera,
            "contratos": contratos, "processos": detalhe, "fiscais": fiscais, "fornecedores": fornecedores}
