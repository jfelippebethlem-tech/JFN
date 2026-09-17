# -*- coding: utf-8 -*-
"""Emergência à INCUMBENTE na Prefeitura do Rio — leitura estruturada × ContasRio, sem ler à mão.

O padrão que a AGILE × SME mostrou (SME-PRO-2025/38233): dispensa por emergência (art. 75, VIII)
para quem já era contratado do mesmo órgão, nascida de um certame travado, e prorrogada até o teto.
Aqui isso vira sinal automático para toda dispensa 2024+ cujos autos já foram lidos:

  fundamento (pcrj_doc_campos)  → é emergência? (art. 75, VIII / art. 24, IV)
  contasrio_contrato            → o fornecedor já contratava com o MESMO órgão antes? (incumbência)
  pregao (pcrj_doc_campos)      → os autos citam um certame? (emergência nascida de licitação travada)
  termo_aditivo (pcrj_doc_campos) → a emergência foi prorrogada?

Grau: 🔴 emergência + incumbente + (certame citado ou prorrogada) · 🟡 emergência + incumbente ·
⚪ emergência sem incumbência (contexto). Nunca acusação: a emergência pode ser legítima — o sinal
diz ONDE ler a justificativa. Tabela: pcrj_emergencia_sinal.

    python -m tools.pcrj_emergencia_incumbente          # recalcula
    python -m tools.pcrj_emergencia_incumbente --top 20
"""
from __future__ import annotations

import argparse
import re
import sqlite3
from datetime import datetime

from compliance_agent.pcrj import db as pcrj_db

_RX_EMERG = re.compile(r"art\.?\s*75,?\s*(?:inciso\s+)?VIII\b|art\.?\s*24,?\s*(?:inciso\s+)?IV\b", re.I)
JANELA_INCUMBENCIA_DIAS = 730

DDL = """CREATE TABLE IF NOT EXISTS pcrj_emergencia_sinal (
    contrato TEXT PRIMARY KEY, processo TEXT, favorecido_doc TEXT, favorecido_nome TEXT, orgao TEXT, ano INTEGER,
    valor_atualizado REAL, total_pago REAL, vigencia_ini TEXT, vigencia_fim TEXT, fundamento TEXT,
    incumbente_contrato TEXT, incumbente_desde TEXT, certame_citado TEXT, prorrogada INTEGER, grau TEXT,
    detalhe TEXT, gerado_em TEXT);"""


def _data(s: str | None):
    try:
        return datetime.strptime((s or "").strip(), "%d/%m/%Y").date()
    except ValueError:
        return None


def _codigo_orgao(orgao: str | None) -> str:
    return (orgao or "").split(" - ")[0].strip()


def eh_emergencia(fundamentos: list[str]) -> str | None:
    """Devolve o fundamento que caracteriza emergência (75, VIII / 24, IV) ou None."""
    for f in fundamentos:
        if _RX_EMERG.search(f or ""):
            return f
    return None


def incumbencia(anteriores: list[dict], vigencia_ini: str | None, janela_dias: int = JANELA_INCUMBENCIA_DIAS) -> dict | None:
    """Contrato anterior do MESMO fornecedor no MESMO órgão cuja vigência terminou até `janela` dias antes
    do início da emergência (ou ainda vigia). anteriores: [{contrato, vigencia_ini, vigencia_fim}]."""
    ini = _data(vigencia_ini)
    if not ini:
        return None
    melhor = None
    for a in anteriores:
        a_ini, a_fim = _data(a.get("vigencia_ini")), _data(a.get("vigencia_fim"))
        if not a_ini or a_ini >= ini:
            continue
        if a_fim and (ini - a_fim).days > janela_dias:
            continue
        if melhor is None or a_ini < _data(melhor["vigencia_ini"]):
            melhor = a
    return melhor


def graduar(emergencia: str | None, incumbente: dict | None, certame: str | None, prorrogada: bool) -> str | None:
    if not emergencia:
        return None
    if incumbente and (certame or prorrogada):
        return "🔴"
    if incumbente:
        return "🟡"
    return "⚪"


def calcular(db_path=None) -> dict:
    pcrj_db.inicializar(db_path)
    con = pcrj_db.conectar(db_path)
    con.row_factory = sqlite3.Row
    con.executescript(DDL)
    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    n = {"🔴": 0, "🟡": 0, "⚪": 0}
    try:
        if not con.execute("SELECT 1 FROM sqlite_master WHERE name='pcrj_doc_campos'").fetchone():
            return {"erro": "pcrj_doc_campos ausente — rode compliance_agent.pcrj.leitura_campos"}
        dispensas = con.execute(
            "SELECT contrato, processo, favorecido_doc, favorecido_nome, orgao, ano, valor_atualizado, total_pago, "
            "vigencia_ini, vigencia_fim FROM contasrio_contrato WHERE forma_contratacao LIKE 'Contratação Direta%' "
            "AND processo IS NOT NULL AND processo <> ''").fetchall()
        con.execute("DELETE FROM pcrj_emergencia_sinal")
        for d in dispensas:
            campos = con.execute("SELECT campo, valor FROM pcrj_doc_campos WHERE upper(numero_processo)=upper(?) "
                                 "AND campo IN ('fundamento','pregao','termo_aditivo')", (d["processo"],)).fetchall()
            if not campos:
                continue
            fund = eh_emergencia([c["valor"] for c in campos if c["campo"] == "fundamento"])
            if not fund:
                continue
            certame = next((c["valor"] for c in campos if c["campo"] == "pregao"), None)
            prorrogada = any(c["campo"] == "termo_aditivo" for c in campos)
            anteriores = [dict(r) for r in con.execute(
                "SELECT contrato, vigencia_ini, vigencia_fim FROM contasrio_contrato WHERE favorecido_doc=? AND contrato<>? "
                "AND substr(orgao,1,4)=?", (d["favorecido_doc"], d["contrato"], _codigo_orgao(d["orgao"])))]
            inc = incumbencia(anteriores, d["vigencia_ini"])
            grau = graduar(fund, inc, certame, prorrogada)
            n[grau] += 1
            detalhe = (f"emergência ({fund}); " + (f"incumbente desde {inc['vigencia_ini']} (contrato {inc['contrato']}); " if inc else "sem contrato anterior no órgão; ")
                       + (f"autos citam pregão {certame}; " if certame else "") + ("prorrogada por termo aditivo" if prorrogada else "sem aditivo lido"))
            con.execute("INSERT OR REPLACE INTO pcrj_emergencia_sinal VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (d["contrato"], d["processo"], d["favorecido_doc"], d["favorecido_nome"], d["orgao"], d["ano"],
                         d["valor_atualizado"], d["total_pago"], d["vigencia_ini"], d["vigencia_fim"], fund,
                         inc["contrato"] if inc else None, inc["vigencia_ini"] if inc else None, certame, int(prorrogada),
                         grau, detalhe, agora))
        con.commit()
    finally:
        con.close()
    return {"dispensas": len(dispensas), "sinais": n}


def listar(top: int = 20, db_path=None) -> list[dict]:
    con = pcrj_db.conectar(db_path)
    con.row_factory = sqlite3.Row
    try:
        if not con.execute("SELECT 1 FROM sqlite_master WHERE name='pcrj_emergencia_sinal'").fetchone():
            return []
        return [dict(r) for r in con.execute(
            "SELECT * FROM pcrj_emergencia_sinal ORDER BY CASE grau WHEN '🔴' THEN 0 WHEN '🟡' THEN 1 ELSE 2 END, "
            "coalesce(total_pago,0) DESC LIMIT ?", (top,))]
    finally:
        con.close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--top", type=int, default=0)
    a = ap.parse_args()
    import json
    if a.top:
        for r in listar(a.top):
            pago = f"{r['total_pago'] or 0:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            print(f"{r['grau']} {r['favorecido_nome'][:38]:38} {r['orgao'][:30]:30} {r['processo']:24} pago R$ {pago:>16}  {r['detalhe'][:110]}")
        return
    print(json.dumps(calcular(), ensure_ascii=False))


if __name__ == "__main__":
    main()
