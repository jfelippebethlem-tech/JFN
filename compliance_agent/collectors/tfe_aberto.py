# -*- coding: utf-8 -*-
"""
Coletor TFE Despesa (dados abertos RJ) — espelho D-1 do SIAFE-Rio, SEM login/MFA, de qualquer IP.

Fonte: CKAN `dadosabertos.rj.gov.br`, dataset `tfe-despesa` (SEFAZ) — "espelho do SIAFE-Rio, um dia
de defasagem". CSVs anuais (despesa_genericaAAAA.csv), latin-1, separador ';'. Agregado por
classificação orçamentária (UG/órgão/elemento/fonte) — NÃO traz OB nominal nem CNPJ/credor (para isso,
SIAFE direto). Serve para varredura de anomalias de execução (empenho/liquidação/pago) sem o ADF do SIAFE.

Colunas-chave: Órgão, UG, Elemento de Despesa, Fonte, Valor Empenhado, Valor Liquidado, Valor Pago,
RP a Pagar, RP Pago, Valor Total Desembolsado.

Uso:
    python -m compliance_agent.collectors.tfe_aberto --ano 2025            # resumo
    python -m compliance_agent.collectors.tfe_aberto --ano 2025 --orgao "POLICIA"
"""
import argparse
import csv
import io
import os
from collections import defaultdict
from pathlib import Path

import httpx

CKAN = "https://dadosabertos.rj.gov.br/api/3/action/package_show?id=tfe-despesa"
UA = {"User-Agent": "Mozilla/5.0 (compatible; JFN-Auditor/1.0)"}
_REPO = Path(__file__).resolve().parent.parent.parent
CACHE = Path(os.environ.get("JFN_DATA_DIR", _REPO / "data")) / "tfe_cache"


def _money(s):
    s = (s or "").strip().replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def resource_url(ano):
    """URL do CSV do ano a partir do CKAN (pega o último recurso que casa o ano)."""
    d = httpx.get(CKAN, headers=UA, timeout=40, verify=False).json()["result"]
    cand = [r for r in d.get("resources", []) if str(ano) in (r.get("name") or "") and (r.get("format") or "").upper() == "CSV"]
    if not cand:
        raise RuntimeError(f"sem CSV para {ano}")
    return cand[-1]["url"]


def baixar_ano(ano, use_cache=True):
    """Baixa (e cacheia) o CSV do ano. Retorna o texto."""
    CACHE.mkdir(parents=True, exist_ok=True)
    fp = CACHE / f"tfe_despesa_{ano}.csv"
    if use_cache and fp.exists() and fp.stat().st_size > 1000:
        return fp.read_text(encoding="latin-1", errors="replace")
    url = resource_url(ano)
    txt = httpx.get(url, headers=UA, timeout=120, verify=False, follow_redirects=True).content.decode("latin-1", "replace")
    fp.write_text(txt, encoding="latin-1")
    return txt


def _rows(txt):
    """Pula as linhas de título e parseia a partir do cabeçalho ('Posição';...)."""
    lines = txt.splitlines()
    start = next((i for i, l in enumerate(lines) if l.replace('"', '').strip().startswith("Posição")), 0)
    return csv.DictReader(io.StringIO("\n".join(lines[start:])), delimiter=";")


def resumo(ano, orgao_filtro=""):
    txt = baixar_ano(ano)
    tot = defaultdict(float)
    por_orgao = defaultdict(lambda: defaultdict(float))
    n = 0
    for row in _rows(txt):
        org = (row.get("Nome Órgão") or row.get("Nome UO") or "?").strip()
        if orgao_filtro and orgao_filtro.upper() not in org.upper():
            continue
        emp = _money(row.get("Valor Empenhado")); liq = _money(row.get("Valor Liquidado")); pago = _money(row.get("Valor Pago"))
        tot["empenhado"] += emp; tot["liquidado"] += liq; tot["pago"] += pago
        por_orgao[org]["empenhado"] += emp; por_orgao[org]["pago"] += pago
        n += 1
    top = sorted(por_orgao.items(), key=lambda kv: kv[1]["pago"], reverse=True)[:12]
    return {"ano": ano, "linhas": n, "totais": dict(tot), "top_orgaos": [(o, v["pago"], v["empenhado"]) for o, v in top]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ano", type=int, default=2025)
    ap.add_argument("--orgao", default="")
    a = ap.parse_args()
    r = resumo(a.ano, a.orgao)
    print(f"== TFE Despesa {r['ano']} (espelho SIAFE D-1) — {r['linhas']:,} linhas ==")
    t = r["totais"]
    print(f"  Empenhado: R$ {t.get('empenhado',0):,.2f}")
    print(f"  Liquidado: R$ {t.get('liquidado',0):,.2f}")
    print(f"  PAGO:      R$ {t.get('pago',0):,.2f}")
    print("  Top órgãos por valor PAGO:")
    for o, pago, emp in r["top_orgaos"]:
        print(f"    R$ {pago:>18,.2f} | {o[:50]}")


if __name__ == "__main__":
    main()
