"""Dados REAIS do site novo (jfn-site) — 27/11/2026. Cada número sai com fonte, recorte e estado
(VERIFICADO | INDISPONIVEL), regra 9 do CLAUDE.md: nada no painel sem proveniência.

Recortes (decididos pela medida de 27/11, não por suposição):
  • "pago" = OB paga do SIAFE pela regra única `cruzamentos_intel._ob_paga`;
  • "a fornecedores" = credor com CNPJ (14 dígitos). Credor genérico "CG…" (folha, tributos, consignações; R$ 245 bi)
    e credor = UG (transferências internas; R$ 43 bi) NÃO são fornecedores e ficam fora;
  • a data do SIAFE é TEXTO DD/MM/AAAA — convertida antes de comparar.
Empenho e liquidação por contrato: NE/NL ainda não coletadas → INDISPONIVEL (o site mostra assim, nunca zero).
Uso: python -m tools.site_dados <saida.json>"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

from compliance_agent import ug_nomes
from compliance_agent.entidades_gov import eh_administracao_publica, eh_nao_fornecedor
from compliance_agent.cruzamentos_intel import _ob_paga

CNPJ = "length(replace(replace(replace(credor,'.',''),'/',''),'-','')) = 14"
DATA_ISO = "substr(data_emissao,7,4)||'-'||substr(data_emissao,4,2)||'-'||substr(data_emissao,1,2)"
FONTE_OB = "SIAFE-Rio · Ordem Bancária paga (regra _ob_paga)"


def _n(valor, fonte: str, recorte: str, estado: str = "VERIFICADO") -> dict:
    return {"valor": valor, "fonte": fonte, "recorte": recorte, "estado": estado}


def gerar(con: sqlite3.Connection, vault: Path) -> dict:
    f = _ob_paga(con)
    # ente público NÃO é fornecedor (regra da casa): nome (entidades_gov.eh_nao_fornecedor — fundos, prefeituras, AAE,
    # tributos) OU natureza jurídica 1xxx da Receita (orgao_esfera). 27/11: sem isso o «maior fornecedor» do Fundo
    # Estadual de Saúde eram FUNDOS MUNICIPAIS DE SAÚDE (repasse a município).
    publicos = {c for c, nat in con.execute("SELECT cnpj, natureza FROM orgao_esfera") if eh_administracao_publica(nat)}
    def eh_fornecedor(credor, nome):
        return re.sub(r"\D", "", credor or "") not in publicos and not eh_nao_fornecedor(nome or "")
    por_credor = con.execute(f"SELECT credor, max(nome_credor), sum(valor), count(*), min(exercicio), max(exercicio) "
                             f"FROM ob_orcamentaria_siafe WHERE {f} AND {CNPJ} GROUP BY credor").fetchall()
    forn_all = [r for r in por_credor if eh_fornecedor(r[0], r[1])]
    tot = round(sum(r[2] for r in forn_all), 2); n = sum(r[3] for r in forn_all); nforn = len(forn_all)
    excl = round(sum(r[2] for r in por_credor) - tot, 2)
    ano_ini = min(r[4] for r in forn_all); ano_fim = max(r[5] for r in forn_all)
    ultima = con.execute(f"SELECT max({DATA_ISO}) FROM ob_orcamentaria_siafe WHERE {f} AND data_emissao GLOB '[0-3][0-9]/[01][0-9]/[12][0-9][0-9][0-9]'").fetchone()[0]
    recorte = f"credores com CNPJ que não são entes públicos, exercícios {ano_ini}–{ano_fim}"

    # órgão em destaque: a UG que mais pagou a FORNECEDORES no exercício mais recente
    por_ug = {}
    linhas = con.execute(f"SELECT ug_pagadora, credor, max(nome_credor), sum(valor), count(*) FROM ob_orcamentaria_siafe "
                         f"WHERE {f} AND {CNPJ} AND exercicio = ? GROUP BY ug_pagadora, credor", (ano_fim,)).fetchall()
    for u, c, nm, v, k in linhas:
        if eh_fornecedor(c, nm):
            por_ug.setdefault(u, []).append({"cnpj": c, "nome": (nm or "").strip(), "valor": round(v, 2), "obs": k})
    ug = max(por_ug, key=lambda u: sum(x["valor"] for x in por_ug[u]))
    ug_total = sum(x["valor"] for x in por_ug[ug])
    forn = sorted(por_ug[ug], key=lambda x: -x["valor"])[:24]
    casos = sorted(vault.glob("*.md"))
    return {
        "gerado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "inicio": {
            "pago_fornecedores": _n(tot, FONTE_OB, recorte),
            "ordens_bancarias": _n(n, FONTE_OB, recorte),
            "fornecedores": _n(nforn, FONTE_OB, recorte + " · CNPJs distintos"),
            "fora_por_ser_ente_publico": _n(excl, FONTE_OB, "OB a credores com CNPJ que são entes públicos (repasses), excluídas do total"),
            "casos_no_acervo": _n(len(casos), "Acervo de casos do JFN (vault/casos)", "todos os dossiês, abertos e fechados"),
            "siafe_ultima_ob": _n(ultima, FONTE_OB, "data de emissão mais recente na base"),
        },
        "orgao": {
            "ug": ug, "nome": ug_nomes.subordinacao(ug, ano_fim) or ug, "exercicio": ano_fim,
            "pago_fornecedores": _n(round(ug_total, 2), FONTE_OB, f"UG {ug}, exercício {ano_fim}, credores com CNPJ"),
            "fornecedores": forn,
            "nota": "altura do prédio = OB paga no exercício; indício não é marcado aqui (ver Casos)",
        },
        "dinheiro": {
            "empenhado": _n(None, "SIAFE-Rio · Nota de Empenho", "por contrato", "INDISPONIVEL"),
            "liquidado": _n(None, "SIAFE-Rio · Nota de Liquidação", "por contrato", "INDISPONIVEL"),
            "nota": "NE e NL por contrato ainda não coletadas (plano: coleta NE/NL por UG); o pago (OB) existe",
        },
    }


def main(argv: list[str]) -> int:
    con = sqlite3.connect("file:data/compliance.db?mode=ro", uri=True, timeout=60)
    d = gerar(con, Path.home() / "vault" / "casos")
    Path(argv[1]).write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    i = d["inicio"]
    print(f"site_dados: ok — pago a fornecedores R$ {i['pago_fornecedores']['valor']:,.2f} ({i['pago_fornecedores']['recorte']}); "
          f"órgão {d['orgao']['nome']} com {len(d['orgao']['fornecedores'])} fornecedores; última OB {i['siafe_ultima_ob']['valor']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
