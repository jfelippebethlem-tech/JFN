# -*- coding: utf-8 -*-
"""
folha_mprj — coletor da FOLHA do Ministério Público do RJ (MPRJ) via API CNMP115.

Reverse-engineering (2026-06-07): o portal (Liferay) proxeia para uma API REST WSO2:
  Gateway:  https://api-transparencia.mprj.mp.br:8280/cnmp115/1.0.0
  OAuth:    POST https://api-transparencia.mprj.mp.br:8280/token  (Basic <client>, client_credentials)
  Endpoints (achados no JS da página): /anos, /meses, /servidores/
Padrão CNMP Resolução 115 (remuneração de membros/servidores).

STATUS (reverendo 2026-07-16): token OK; `/anos` OK; `/meses/{ano}` OK (retorna ano_mes="MMAAAA",
ex. "062025"). Config da página traz **tipoFunc="MATIV"** (Membros ATIVos; servidores usa outro tipo).
MAS o endpoint de DADOS `/servidores/...` devolve 404 em TODO formato testado (ano/mes, MMAAAA, com/sem
tipoFunc, com/sem paginação, GET e POST). A montagem exata da URL está no main.js do tema (Liferay,
não-fetchável).

TENTATIVA 2026-07-17 (Playwright headless): a página tem BANNER DE COOKIES bloqueando + os dropdowns
de ano/mês só renderizam via JS após aceitar; o clique automatizado em 'pesquisar' deu timeout e NENHUM
XHR a /servidores foi disparado. Precisa de uma sessão de browser INTERATIVA (real ou com scripting
cuidadoso do consent+dropdowns+submit) para capturar a chamada. Fica como PRÓXIMO PASSO dedicado —
TJRJ e Câmara já cobrem o cruzamento nomeados×candidatos enquanto isso.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import httpx

_REPO = Path(__file__).resolve().parent.parent.parent
_DB = _REPO / "data" / "compliance.db"
_GW = "https://api-transparencia.mprj.mp.br:8280"
_BASE = f"{_GW}/cnmp115/1.0.0"
_BASIC = "cERmaFZtNUpOS1VfSjFCcUNSak1IMGN6dGpVYTpwb2dVS2Fta2kzZjN3UXZWWjJXdmtpSXRYazhh"
_FONTE = "mprj_cnmp115"
_ORGAO = ("MPRJ", "Ministério Público do Estado do RJ")

# nomes de campo prováveis no JSON CNMP (ajustar após 1º fetch real)
_MAP = {
    "cpf": ("cpf", "cpfDescaracterizado", "cpf_mascarado"),
    "nome": ("nome", "servidor", "nomeServidor"),
    "cargo": ("cargo", "cargoEfetivo", "denominacaoCargo"),
    "vinculo": ("situacao", "tipoVinculo", "vinculo", "categoria"),
    "bruto": ("remuneracaoBruta", "totalGanhos", "remuneracao", "totalRemuneracao", "ganhoBruto"),
    "liquido": ("remuneracaoLiquida", "valorLiquido", "liquido", "ganhoLiquido"),
    "descontos": ("totalDescontos", "descontos", "totalDeducoes"),
}


def _g(rec: dict, chaves) -> object:
    for k in chaves:
        if k in rec and rec[k] not in (None, ""):
            return rec[k]
    return None


def _num(v) -> float:
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v or "").strip().replace(".", "").replace(",", ".") if "," in str(v or "") else str(v or "").strip()
    try:
        return float(s) if s else 0.0
    except ValueError:
        return 0.0


def get_token() -> str:
    r = httpx.post(f"{_GW}/token", headers={"Authorization": f"Basic {_BASIC}"},
                   data={"grant_type": "client_credentials"}, verify=False, timeout=25)
    r.raise_for_status()
    return r.json()["access_token"]


def _try_paths(tok: str, ano: int, mes: int) -> list[dict] | None:
    """Tenta os formatos de path conhecidos do /servidores até um responder JSON-lista."""
    h = {"Authorization": f"Bearer {tok}"}
    for path in (f"/servidores/{ano}/{mes}", f"/servidores/{ano}/{mes:02d}",
                 f"/servidores/{ano}/{mes}/1/1000", f"/servidores/?ano={ano}&mes={mes}"):
        try:
            r = httpx.get(_BASE + path, headers=h, verify=False, timeout=40)
            if r.status_code == 200 and r.text.strip().startswith(("[", "{")):
                j = r.json()
                return j if isinstance(j, list) else j.get("dados") or j.get("servidores") or j.get("content") or []
        except Exception:
            continue
    return None


def parse(records: list[dict], ano: int, mes: int) -> list[dict]:
    out = []
    comp = f"{ano}-{mes:02d}"
    for rec in records or []:
        nome = _g(rec, _MAP["nome"])
        if not nome:
            continue
        out.append({
            "cpf": str(_g(rec, _MAP["cpf"]) or "").strip(), "nome": str(nome).strip(),
            "orgao_codigo": _ORGAO[0], "orgao_nome": _ORGAO[1],
            "cargo": str(_g(rec, _MAP["cargo"]) or "").strip(),
            "vinculo": str(_g(rec, _MAP["vinculo"]) or "").strip(),
            "competencia": comp,
            "remuneracao_bruta": _num(_g(rec, _MAP["bruto"])),
            "remuneracao_liquida": _num(_g(rec, _MAP["liquido"])),
            "abonos": 0.0, "descontos": _num(_g(rec, _MAP["descontos"])),
            "fonte": _FONTE,
        })
    return out


def ingerir(regs: list[dict]) -> dict:
    if not regs:
        return {"inseridas": 0}
    con = sqlite3.connect(str(_DB))
    try:
        ins = 0
        for r in regs:
            if con.execute("SELECT 1 FROM registros_folha WHERE fonte=? AND competencia=? AND cpf=? AND nome=?",
                           (r["fonte"], r["competencia"], r["cpf"], r["nome"])).fetchone():
                continue
            con.execute("""INSERT INTO registros_folha
                (cpf,nome,orgao_codigo,orgao_nome,cargo,vinculo,competencia,
                 remuneracao_bruta,remuneracao_liquida,abonos,descontos,fonte,created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))""",
                (r["cpf"], r["nome"], r["orgao_codigo"], r["orgao_nome"], r["cargo"], r["vinculo"],
                 r["competencia"], r["remuneracao_bruta"], r["remuneracao_liquida"], r["abonos"],
                 r["descontos"], r["fonte"]))
            ins += 1
        con.commit()
        return {"inseridas": ins}
    finally:
        con.close()


def coletar(anos=range(2023, 2027), meses=range(1, 13)) -> dict:
    tok = get_token()
    tot = 0; ok_comps = []
    for ano in anos:
        for mes in meses:
            recs = _try_paths(tok, ano, mes)
            if recs is None:
                continue
            regs = parse(recs, ano, mes)
            res = ingerir(regs)
            tot += res["inseridas"]; ok_comps.append(f"{ano}-{mes:02d}")
            print(f"  {ano}-{mes:02d}: {len(regs)} regs, +{res['inseridas']}", flush=True)
    return {"ok": bool(ok_comps), "inseridas": tot, "competencias": ok_comps,
            "nota": "" if ok_comps else "Nenhuma competência respondeu — backend CNMP115 provavelmente fora do ar (404/transport)."}


if __name__ == "__main__":
    import json
    print(json.dumps(coletar(), ensure_ascii=False, indent=1))
