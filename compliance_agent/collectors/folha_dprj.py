# -*- coding: utf-8 -*-
"""
folha_dprj — coletor da FOLHA de pagamento da Defensoria Pública do RJ (DPRJ).

Fonte BULK (sem CAPTCHA): o "Relatório Mensal de Remuneração" da DPRJ publica arquivos
CSV/XLSX diretos em https://transparencia.rj.def.br/gastos-com-pessoal/relatorio-mensal-de-remuneracao
(uploads/arquivos/*.csv). Formato (;, latin-1, decimal vírgula):
  NUMFUNC;NUMVINC;NUMPENS;MES_ANO_FOLHA;TIPO_FOLHA;CPF_DESCARACTERIZADO;NOME;SITUACAO;CARGO;
  REMUNERACAO;INDENIZACOES;VANTAGEM_EVENTUAL;VANTAGEM_PESSOAL;DEC_TERC_SALARIO;OUTROS_GANHOS;
  TOTAL_GANHOS;LIMITE_REMUN;PREV_OFICIAL;PREV_PRIVADA;IRRF;DESCONTOS_PESSOAL;OUTROS_DESCONTOS;
  TOTAL_DESCONTOS;VALOR_LIQUI

Grava em compliance.db/registros_folha (idempotente por fonte+competencia+cpf+nome).
"""
from __future__ import annotations

import csv
import io
import re
import sqlite3
from pathlib import Path

import httpx

_REPO = Path(__file__).resolve().parent.parent.parent
_DB = _REPO / "data" / "compliance.db"
_BASE = "https://transparencia.rj.def.br"
_PAGINA = f"{_BASE}/gastos-com-pessoal/relatorio-mensal-de-remuneracao"
_FONTE = "dprj_transparencia"
_ORGAO = ("DPRJ", "Defensoria Pública do Estado do RJ")


def _num(s) -> float:
    # pandas (XLSX) já entrega float/int — usar direto (NÃO transformar, senão corrompe o decimal)
    if isinstance(s, (int, float)):
        try:
            return float(s) if s == s else 0.0  # s==s descarta NaN
        except (ValueError, TypeError):
            return 0.0
    s = str(s or "").strip()
    if not s or s in ("-", "nan", "None"):
        return 0.0
    if "," in s:  # formato BR do CSV: "62.420,48" -> 62420.48
        s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def _competencia(mesano: str) -> str:
    """'10/2025' -> '2025-10'."""
    m = re.match(r"(\d{1,2})\D+(\d{4})", str(mesano or "").strip())
    return f"{m.group(2)}-{int(m.group(1)):02d}" if m else (mesano or "")


def parse_csv_bytes(data: bytes) -> list[dict]:
    """Decodifica (latin-1) e mapeia as linhas do CSV da DPRJ para registros_folha."""
    txt = data.decode("latin-1", errors="replace")
    rd = csv.DictReader(io.StringIO(txt), delimiter=";")
    out = []
    for r in rd:
        nome = (r.get("NOME") or "").strip()
        if not nome:
            continue
        out.append({
            "cpf": (r.get("CPF_DESCARACTERIZADO") or "").strip(),
            "nome": nome,
            "orgao_codigo": _ORGAO[0], "orgao_nome": _ORGAO[1],
            "cargo": (r.get("CARGO") or "").strip(),
            "vinculo": (r.get("SITUACAO") or r.get("TIPO_FOLHA") or "").strip(),
            "competencia": _competencia(r.get("MES_ANO_FOLHA")),
            "remuneracao_bruta": _num(r.get("TOTAL_GANHOS")),
            "remuneracao_liquida": _num(r.get("VALOR_LIQUIDO")),
            "abonos": _num(r.get("VANTAGEM_EVENTUAL")) + _num(r.get("VANTAGEM_PESSOAL")),
            "descontos": _num(r.get("TOTAL_DESCONTOS")),
            "fonte": _FONTE,
        })
    return out


_MESES = {"JANEIRO": 1, "FEVEREIRO": 2, "MARÇO": 3, "MARCO": 3, "ABRIL": 4, "MAIO": 5,
          "JUNHO": 6, "JULHO": 7, "AGOSTO": 8, "SETEMBRO": 9, "OUTUBRO": 10,
          "NOVEMBRO": 11, "DEZEMBRO": 12}


def _competencia_nome(s: str) -> str:
    """'Período: JANEIRO/2025' -> '2025-01'."""
    s = (s or "").upper()
    m = re.search(r"([A-ZÇ]+)\s*/\s*(\d{4})", s)
    if m and m.group(1) in _MESES:
        return f"{m.group(2)}-{_MESES[m.group(1)]:02d}"
    return ""


def parse_xlsx_bytes(data: bytes) -> list[dict]:
    """Folha histórica da DPRJ em XLSX: header na linha 7 (idx 7), período na linha 6 (idx 6),
    dados a partir da linha 8. Colunas: 0 CPF, 1 NOME, 2 SITUAÇÃO, 3 CARGO, 22 GANHO BRUTO,
    34 TOTAL DESCONTOS, 35 GANHO LÍQUIDO."""
    import pandas as pd
    df = pd.read_excel(io.BytesIO(data), header=None)
    comp = _competencia_nome(str(df.iloc[6, 0]) if len(df) > 6 else "")
    out = []
    for i in range(8, len(df)):
        row = df.iloc[i].tolist()
        cpf = str(row[0]).strip() if len(row) > 0 else ""
        nome = str(row[1]).strip() if len(row) > 1 else ""
        if not nome or nome.lower() == "nan" or not cpf or cpf.lower() == "nan":
            continue
        g = lambda j: _num(row[j]) if len(row) > j else 0.0
        out.append({
            "cpf": cpf, "nome": nome,
            "orgao_codigo": _ORGAO[0], "orgao_nome": _ORGAO[1],
            "cargo": str(row[3]).strip() if len(row) > 3 else "",
            "vinculo": str(row[2]).strip() if len(row) > 2 else "",
            "competencia": comp,
            "remuneracao_bruta": g(22), "remuneracao_liquida": g(35),
            "abonos": g(5) + g(6), "descontos": g(34),
            "fonte": _FONTE,
        })
    return out


def ingerir(regs: list[dict]) -> dict:
    """Insere em registros_folha, pulando duplicatas (fonte+competencia+cpf+nome)."""
    if not regs:
        return {"inseridas": 0, "puladas": 0}
    con = sqlite3.connect(str(_DB))
    try:
        con.execute("CREATE INDEX IF NOT EXISTS ix_folha_dedup ON registros_folha(fonte,competencia,cpf,nome)")
        ins = pul = 0
        for r in regs:
            ex = con.execute("SELECT 1 FROM registros_folha WHERE fonte=? AND competencia=? AND cpf=? AND nome=?",
                             (r["fonte"], r["competencia"], r["cpf"], r["nome"])).fetchone()
            if ex:
                pul += 1; continue
            con.execute("""INSERT INTO registros_folha
                (cpf,nome,orgao_codigo,orgao_nome,cargo,vinculo,competencia,
                 remuneracao_bruta,remuneracao_liquida,abonos,descontos,fonte,created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))""",
                (r["cpf"], r["nome"], r["orgao_codigo"], r["orgao_nome"], r["cargo"], r["vinculo"],
                 r["competencia"], r["remuneracao_bruta"], r["remuneracao_liquida"],
                 r["abonos"], r["descontos"], r["fonte"]))
            ins += 1
        con.commit()
        total = con.execute("SELECT COUNT(*) FROM registros_folha").fetchone()[0]
        return {"inseridas": ins, "puladas": pul, "total_tabela": total}
    finally:
        con.close()


def _links_arquivos() -> list[str]:
    """Extrai os links de CSV/XLSX da página do relatório mensal."""
    r = httpx.get(_PAGINA, verify=False, timeout=30, follow_redirects=True)
    hrefs = re.findall(r'href="(/uploads/arquivos/[^"]+\.(?:csv|xlsx))"', r.text, re.I)
    return [(_BASE + h) for h in dict.fromkeys(hrefs)]  # dedup preservando ordem


def coletar(apenas_csv: bool = False, max_arquivos: int = 0) -> dict:
    """Baixa os arquivos de folha da DPRJ (CSV atual + XLSX histórico) e ingere — cobre 2023→agora."""
    urls = _links_arquivos()
    if apenas_csv:
        urls = [u for u in urls if u.lower().endswith(".csv")]
    if max_arquivos:
        urls = urls[:max_arquivos]
    tot_ins = tot_pul = 0
    comps = set()
    for u in urls:
        try:
            data = httpx.get(u, verify=False, timeout=90, follow_redirects=True).content
            regs = parse_xlsx_bytes(data) if u.lower().endswith(".xlsx") else parse_csv_bytes(data)
            regs = [r for r in regs if r.get("competencia")]  # ignora arquivos sem competência (não-folha)
            res = ingerir(regs)
            tot_ins += res["inseridas"]; tot_pul += res["puladas"]
            comps.update(r["competencia"] for r in regs)
            print(f"  {u.split('/')[-1]}: {len(regs)} regs, +{res['inseridas']} ({sorted(set(r['competencia'] for r in regs))})")
        except Exception as e:
            print(f"  ERRO {u}: {type(e).__name__}: {str(e)[:80]}")
    return {"ok": True, "arquivos": len(urls), "inseridas": tot_ins, "puladas": tot_pul,
            "competencias": sorted(comps)}


if __name__ == "__main__":
    import json
    print(json.dumps(coletar(), ensure_ascii=False, indent=1))
