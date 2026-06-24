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


def _resources():
    return httpx.get(CKAN, headers=UA, timeout=40, verify=False).json()["result"].get("resources", [])


def anos_disponiveis():
    """Anos com CSV publicado no CKAN (ordenado). O dataset é anual: 2026 só aparece após o SIAFE 2 (D+1)."""
    import re
    anos = set()
    for r in _resources():
        if (r.get("format") or "").upper() == "CSV":
            m = re.search(r"(20\d\d)", r.get("name") or "")
            if m:
                anos.add(int(m.group(1)))
    return sorted(anos)


def latest_ano():
    """Ano mais recente DISPONÍVEL na fonte (resolve o sweep p/ nunca falhar num ano futuro)."""
    a = anos_disponiveis()
    if not a:
        raise RuntimeError("CKAN sem nenhum CSV de despesa")
    return a[-1]


def resource_url(ano):
    """URL do CSV do ano a partir do CKAN (pega o último recurso que casa o ano)."""
    cand = [r for r in _resources() if str(ano) in (r.get("name") or "") and (r.get("format") or "").upper() == "CSV"]
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


def ingest_db(ano):
    """Ingere a despesa COMPLETA (todos os elementos: folha, previdência, dívida, serviços...) numa
    tabela despesa_execucao — o quadro financeiro total (≠ só fornecedores). Idempotente por ano."""
    import sqlite3
    db = Path(os.environ.get("JFN_DATA_DIR", _REPO / "data")) / "compliance.db"
    con = sqlite3.connect(str(db))
    con.execute("""CREATE TABLE IF NOT EXISTS despesa_execucao(
        exercicio TEXT, posicao TEXT, orgao TEXT, ug TEXT, nome_ug TEXT, fonte TEXT,
        funcao TEXT, subfuncao TEXT, elemento TEXT, empenhado REAL, liquidado REAL, pago REAL)""")
    con.execute("CREATE INDEX IF NOT EXISTS ix_desp_ex ON despesa_execucao(exercicio)")
    con.execute("DELETE FROM despesa_execucao WHERE exercicio=?", (str(ano),))
    txt = baixar_ano(ano)
    rows, n = [], 0
    for r in _rows(txt):
        rows.append((str(ano), (r.get("Posição") or "").strip(), (r.get("Nome Órgão") or "").strip(),
                     (r.get("UG") or "").strip(), (r.get("Nome UG") or "").strip(), (r.get("Nome Fonte") or "").strip(),
                     (r.get("Nome Função") or "").strip(), (r.get("Nome Sub Função") or "").strip(),
                     (r.get("Nome Elemento de Despesa") or "").strip(),
                     _money(r.get("Valor Empenhado")), _money(r.get("Valor Liquidado")), _money(r.get("Valor Pago"))))
        n += 1
        if len(rows) >= 5000:
            con.executemany("INSERT INTO despesa_execucao VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", rows); rows = []
    if rows:
        con.executemany("INSERT INTO despesa_execucao VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    pago = con.execute("SELECT SUM(pago) FROM despesa_execucao WHERE exercicio=?", (str(ano),)).fetchone()[0] or 0
    con.commit(); con.close()
    return n, pago


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ano", type=int, default=2025)
    ap.add_argument("--latest", action="store_true", help="usa o ano mais recente DISPONÍVEL no CKAN (auto-atualiza)")
    ap.add_argument("--orgao", default="")
    ap.add_argument("--ingest", action="store_true")
    a = ap.parse_args()
    # --latest: mira o ano mais novo publicado (o dataset TFE é anual e sai D+1 após o SIAFE 2;
    # assim o sweep nunca falha num ano futuro e sempre pega o dado mais recente).
    if a.latest:
        a.ano = latest_ano()
        print(f"[TFE] ano mais recente disponível = {a.ano} (de {anos_disponiveis()})")
    # Degradação graciosa: ano ainda não publicado NÃO é erro — avisa e sai 0 p/ não derrubar o serviço.
    try:
        resource_url(a.ano)
    except RuntimeError as e:
        print(f"⚠ TFE: {e} (ano ainda não publicado na fonte aberta) — pulando, sem falha.")
        return
    if a.ingest:
        n, pago = ingest_db(a.ano)
        print(f"despesa_execucao {a.ano}: {n:,} linhas | PAGO TOTAL R$ {pago:,.2f}")
        return
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
