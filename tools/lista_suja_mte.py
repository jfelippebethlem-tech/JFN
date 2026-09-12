#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""lista_suja_mte — Cadastro de Empregadores (trabalho análogo ao de escravo, MTE) × favorecidos do Estado.

Fonte pública, sem API (12/09/2026): PDF semestral do MTE
https://www.gov.br/trabalho-e-emprego/pt-br/assuntos/inspecao-do-trabalho/areas-de-atuacao/cadastro_de_empregadores.pdf
Cada linha: ano da ação fiscal, UF, empregador, CNPJ/CPF, estabelecimento, nº de trabalhadores, data de
inclusão. Materializa `lista_suja_mte` e cruza com `favorecido_resumo`/OBs do SIAFE/contratos TCE-RJ/TAC.
Primeira medição: 184 CNPJs na lista; 1 favorecido do Estado (VIABRAS ENGENHARIA, R$ 3,1 mi em 2023-24,
incluída em 09/04/2025 — pagamentos ANTERIORES à inclusão: monitorar, não acusar).

Uso: PYTHONPATH=. .venv/bin/python -m tools.lista_suja_mte   (cruzador, mensal)
"""
from __future__ import annotations

import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
DB = _REPO / "data" / "compliance.db"
URL = "https://www.gov.br/trabalho-e-emprego/pt-br/assuntos/inspecao-do-trabalho/areas-de-atuacao/cadastro_de_empregadores.pdf"
CACHE = _REPO / "data" / "cache" / "cadastro_de_empregadores.pdf"

_RE_CNPJ = re.compile(r"\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}")
_RE_DATA = re.compile(r"\d{2}/\d{2}/\d{4}")


def extrair(texto: str) -> list[dict]:
    """Uma entrada por CNPJ: nome = texto imediatamente antes do CNPJ na mesma linha; data de inclusão = a
    última data dd/mm/aaaa que aparece DEPOIS do CNPJ até a próxima entrada (o PDF traz 'inclusão' após o
    estabelecimento e a contagem de trabalhadores)."""
    out = []
    achados = list(_RE_CNPJ.finditer(texto))
    for i, m in enumerate(achados):
        ini = achados[i - 1].end() if i else 0
        fim = achados[i + 1].start() if i + 1 < len(achados) else len(texto)
        antes = texto[ini:m.start()]
        depois = texto[m.end():fim]
        nome = antes.strip().split("\n")[-1].strip()
        nome = re.sub(r"^\d{4}\s+[A-Z]{2}\s+", "", nome).strip()   # "2022 MG VIABRAS…" → nome
        datas = _RE_DATA.findall(depois)
        out.append({"cnpj": re.sub(r"\D", "", m.group(0)), "nome": nome[:160],
                    "inclusao": datas[-1] if datas else None})
    return out


def baixar() -> str:
    import fitz
    import httpx
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    r = httpx.get(URL, headers={"User-Agent": "Mozilla/5.0 (JFN fiscalizacao)"}, timeout=90, follow_redirects=True)
    r.raise_for_status()
    if not r.content.startswith(b"%PDF"):
        raise RuntimeError("resposta não é PDF (WAF/manutenção) — nada gravado")
    CACHE.write_bytes(r.content)
    return "".join(p.get_text() for p in fitz.open(str(CACHE)))


def materializar(texto: str | None = None) -> dict:
    texto = texto if texto is not None else baixar()
    itens = extrair(texto)
    con = sqlite3.connect(DB, timeout=120)
    con.execute("PRAGMA busy_timeout=120000")
    agora = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with con:
        con.execute("CREATE TABLE IF NOT EXISTS lista_suja_mte (cnpj TEXT PRIMARY KEY, nome TEXT, inclusao TEXT, visto_em TEXT)")
        con.execute("DELETE FROM lista_suja_mte")
        con.executemany("INSERT OR REPLACE INTO lista_suja_mte VALUES (?,?,?,?)",
                        [(i["cnpj"], i["nome"], i["inclusao"], agora) for i in itens])
    cruz = con.execute(
        "SELECT l.cnpj, l.nome, l.inclusao, f.favorecido_nome, f.total_pago FROM lista_suja_mte l "
        "JOIN favorecido_resumo f ON f.favorecido_cpf = l.cnpj").fetchall()
    con.close()
    return {"entradas": len(itens), "cruzados_favorecidos": [list(c) for c in cruz]}


def main() -> int:
    r = materializar()
    print(f"[lista-suja] {r['entradas']} empregadores; favorecidos do Estado na lista: {len(r['cruzados_favorecidos'])}")
    for c in r["cruzados_favorecidos"]:
        pago = f"{c[4]:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")   # padrão brasileiro
        print(f"   {c[0]} {c[1][:50]} inclusão {c[2]} | pago R$ {pago}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
