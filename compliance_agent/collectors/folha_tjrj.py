# -*- coding: utf-8 -*-
"""folha_tjrj — coletor da FOLHA do Tribunal de Justiça do RJ (Anexo VIII CNJ).

Fluxo (ASP.NET WebForms, reverse-engineering 2026-07-17):
  1. GET  https://www3.tjrj.jus.br/portalservidor/PortalCorpDetalheFolha.aspx  → __VIEWSTATE etc.
  2. POST (grConsulta=rbDetalhada + ddlMes + ddlAno + btnPesqGeral) → resposta traz
     <a id="ctl00_ConteudoPrincipal_lnkFile" href="…/GEDCacheWeb/…?GEDID=…"> (o ZIP do mês).
  3. GET do GEDID → ZIP com 1 HTML (Excel export) — tabela Anexo VIII: Nome | Lotação | Cargo | valores.

Sem CPF (o TJ não publica no Anexo VIII) — o cruzamento nomeados×candidatos é por NOME.
Grava direto em `registros_folha` (mesmo DB), órgão TJRJ. Certificado TLS incompleto → verify=False
(dado público, só-leitura; nenhuma credencial trafega).
"""
from __future__ import annotations

import io
import re
import sqlite3
import warnings
import zipfile
from datetime import date
from pathlib import Path

import httpx

warnings.filterwarnings("ignore")
_REPO = Path(__file__).resolve().parent.parent.parent
_DB = _REPO / "data" / "compliance.db"
_URL = "https://www3.tjrj.jus.br/portalservidor/PortalCorpDetalheFolha.aspx"
_H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
_FONTE = "tjrj_anexo8"
_ORGAO = ("TJRJ", "Tribunal de Justiça do Estado do RJ")


def _field(html: str, nome: str) -> str:
    m = re.search(rf'name="{re.escape(nome)}"[^>]*value="([^"]*)"', html)
    return m.group(1) if m else ""


def _cells(row: str) -> list[str]:
    return [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", x)).strip()
            for x in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S)]


def _num(s: str) -> float:
    s = (s or "").strip().replace(".", "").replace(",", ".")
    try:
        return float(s) if re.match(r"^-?\d+(\.\d+)?$", s) else 0.0
    except ValueError:
        return 0.0


def baixar_mes(ano: int, mes: int, cli: httpx.Client) -> list[dict]:
    """Baixa e parseia a folha (Anexo VIII) de um mês. [] se o mês não tem arquivo."""
    h = cli.get(_URL).text
    data = {
        "__EVENTTARGET": "", "__EVENTARGUMENT": "", "__LASTFOCUS": "",
        "__VIEWSTATE": _field(h, "__VIEWSTATE"), "__VIEWSTATEGENERATOR": _field(h, "__VIEWSTATEGENERATOR"),
        "__EVENTVALIDATION": _field(h, "__EVENTVALIDATION"),
        "ctl00$ConteudoPrincipal$grConsulta": "rbDetalhada",
        "ctl00$ConteudoPrincipal$ddlMes": str(mes), "ctl00$ConteudoPrincipal$ddlAno": str(ano),
        "ctl00$ConteudoPrincipal$btnPesqGeral": "Pesquisar",
    }
    h2 = cli.post(_URL, data=data).text
    m = re.search(r'id="ctl00_ConteudoPrincipal_lnkFile"[^>]*href="([^"]+)"', h2) \
        or re.search(r'href="([^"]+GEDID=[^"]+)"', h2)
    if not m:
        return []
    blob = cli.get(m.group(1)).content
    if blob[:2] != b"PK":
        return []
    zf = zipfile.ZipFile(io.BytesIO(blob))
    txt = zf.read(zf.namelist()[0]).decode("latin-1", errors="replace")
    comp = f"{ano}-{mes:02d}"
    out: list[dict] = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", txt, re.S):
        cs = _cells(row)
        # linha de servidor: nome (letras maiúsculas) + lotação + cargo + valores
        if len(cs) < 4 or not re.search(r"[A-ZÀ-Ú]{3,}", cs[0]) or "nome" in cs[0].lower():
            continue
        nome, lotacao, cargo = cs[0], cs[1], cs[2]
        if not nome or nome.lower() in ("nome", "total", "totais") or len(nome) < 4:
            continue
        # total de créditos = maior valor monetário da linha (proxy robusto do bruto)
        bruto = max((_num(x) for x in cs[3:] if "," in x), default=0.0)
        out.append({"nome": nome, "lotacao": lotacao, "cargo": cargo, "competencia": comp,
                    "bruto": bruto})
    return out


def ingerir(regs: list[dict]) -> int:
    """Dedup em memória (1 leitura) + INSERT em lote (executemany) — evita 21k queries sob lock."""
    if not regs:
        return 0
    con = sqlite3.connect(str(_DB), timeout=60)
    con.execute("PRAGMA busy_timeout=60000")
    try:
        existentes = {(n, c) for n, c in con.execute(
            "SELECT nome, cargo FROM registros_folha WHERE fonte=?", (_FONTE,))}
        novos = [r for r in regs if (r["nome"], r["cargo"]) not in existentes]
        # dedup interno do lote (o Anexo VIII repete nome em várias faixas)
        vistos: set = set()
        linhas = []
        for r in novos:
            k = (r["nome"], r["cargo"])
            if k in vistos:
                continue
            vistos.add(k)
            linhas.append(("", r["nome"], _ORGAO[0], _ORGAO[1], r["cargo"], r["lotacao"],
                           r["competencia"], r["bruto"], _FONTE))
        con.executemany(
            "INSERT INTO registros_folha (cpf,nome,orgao_codigo,orgao_nome,cargo,vinculo,competencia,"
            "remuneracao_bruta,remuneracao_liquida,abonos,descontos,fonte,created_at) "
            "VALUES (?,?,?,?,?,?,?,?,0,0,0,?,datetime('now'))", linhas)
        con.commit()
        return len(linhas)
    finally:
        con.close()


def coletar(meses_tentar: int = 4) -> dict:
    """Coleta a folha do TJRJ do mês mais recente disponível (a folha atual = todos os servidores).
    Tenta do mês corrente para trás até achar um arquivo. Idempotente (dedup fonte+nome+cargo)."""
    hoje = date.today()
    with httpx.Client(verify=False, timeout=40, headers=_H, follow_redirects=True) as cli:
        y, mth = hoje.year, hoje.month
        for _ in range(meses_tentar):
            regs = baixar_mes(y, mth, cli)
            if regs:
                ins = ingerir(regs)
                return {"ok": True, "competencia": f"{y}-{mth:02d}", "linhas": len(regs), "inseridas": ins}
            y, mth = (y - 1, 12) if mth == 1 else (y, mth - 1)
    return {"ok": False, "nota": "Nenhum mês recente retornou arquivo (portal fora do ar ou sem publicação)."}


if __name__ == "__main__":
    import json
    print(json.dumps(coletar(), ensure_ascii=False))
