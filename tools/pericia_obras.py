#!/usr/bin/env python3
"""Perícia de OBRAS — due diligence de execução físico-financeira (contratos_tcerj + SEI).

Para cada contrato de obra: valor do contrato, % executado (pago/empenhado/liquidado), fase
(não iniciada / em andamento / concluída / PARADA-suspeita / cancelada) inferida de status +
vigência + execução, e enriquecimento de fase pela perícia SEI quando há ficha.

RED FLAG central (art. 37 CF, Lei 14.133): obra com **vigência VENCIDA** e execução baixa = possível
**obra parada/abandonada** após receber recursos. Honestidade: indício de perícia, não acusação;
INDISPONÍVEL≠0 (TCE-RJ às vezes não traz o pago — anota).

Uso: python -m tools.pericia_obras [--hoje AAAA-MM-DD] [--top N] [--md saida.md]
"""
import argparse, datetime, json, os, sqlite3

DB = os.environ.get("JFN_DB") or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "compliance.db")
OBRA = ("(LOWER(objeto) LIKE '%obra%' OR LOWER(objeto) LIKE '%constru%' OR LOWER(objeto) LIKE '%reforma%' "
        "OR LOWER(objeto) LIKE '%pavimenta%' OR LOWER(objeto) LIKE '%edifica%' OR LOWER(objeto) LIKE '%drenagem%')")


def _data(s):
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime((s or "").strip()[:10], fmt).date()
        except Exception:
            pass
    return None


def classificar(r, hoje):
    vc = r["valor_contrato"] or 0
    pago = r["valor_pago"] or 0
    liq = r["valor_liquidado"] or 0
    emp = r["valor_empenhado"] or 0
    st = (r["status"] or "").lower()
    pct = (pago / vc * 100) if vc else None
    vfim = _data(r["vig_fim"])
    vencida = bool(vfim and vfim < hoje)
    if "cancel" in st:
        fase, flag = "CANCELADA", ""
    elif pct is not None and pct >= 95:
        fase, flag = "CONCLUIDA (financeiro)", ""
    elif vencida and (pct is None or pct < 90):
        fase, flag = "PARADA/VENCIDA-SUSPEITA", "🔴 vigência vencida com execução baixa — possível obra parada"
    elif (pago or liq or emp) and (pct is None or pct < 95):
        fase, flag = "EM ANDAMENTO", ""
    else:
        fase, flag = "NÃO INICIADA", ("🟡 contratada mas R$0 executado" if vc else "")
    return pct, fase, flag, vencida


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hoje", default="2026-06-24")
    ap.add_argument("--top", type=int, default=40)
    ap.add_argument("--md", default="reports/pericia_obras_2026-06-24.md")
    a = ap.parse_args()
    hoje = _data(a.hoje)
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True); con.row_factory = sqlite3.Row
    rows = con.execute(
        f"SELECT processo, objeto, fornecedor, cnpj, unidade, valor_contrato, valor_empenhado, "
        f"valor_liquidado, valor_pago, vig_inicio, vig_fim, status FROM contratos_tcerj "
        f"WHERE {OBRA} AND COALESCE(valor_contrato,0) > 0 ORDER BY valor_contrato DESC").fetchall()
    # fases SEI por CNPJ (enriquecimento, quando há ficha de obra)
    sei = {}
    for s in con.execute("SELECT cnpjs, situacao, nivel_risco, resumo FROM sei_ficha "
                          "WHERE LOWER(objeto) LIKE '%obra%' OR LOWER(objeto) LIKE '%constru%'"):
        for cn in (s["cnpjs"] or "").replace(";", ",").split(","):
            cn = "".join(ch for ch in cn if ch.isdigit())
            if len(cn) == 14:
                sei.setdefault(cn, (s["situacao"], s["nivel_risco"], (s["resumo"] or "")[:120]))
    con.close()

    peritadas = []
    for r in rows:
        pct, fase, flag, venc = classificar(r, hoje)
        cnpj = "".join(ch for ch in (r["cnpj"] or "") if ch.isdigit())
        peritadas.append({
            "objeto": (r["objeto"] or "")[:80], "fornecedor": r["fornecedor"], "cnpj": cnpj,
            "unidade": r["unidade"], "valor_contrato": r["valor_contrato"], "valor_pago": r["valor_pago"],
            "valor_empenhado": r["valor_empenhado"], "valor_liquidado": r["valor_liquidado"],
            "pct_pago": round(pct, 1) if pct is not None else None, "vig_fim": r["vig_fim"],
            "vencida": venc, "fase": fase, "flag": flag, "sei": sei.get(cnpj),
        })

    from collections import Counter
    dist = Counter(p["fase"] for p in peritadas)
    paradas = [p for p in peritadas if "PARADA" in p["fase"]]
    json.dump(peritadas, open(a.md.replace(".md", ".json"), "w"), ensure_ascii=False, indent=2)

    L = [f"# Perícia de Obras — execução físico-financeira ({a.hoje})\n",
         f"Fonte: contratos_tcerj (TCE-RJ) + perícia SEI. {len(peritadas)} contratos de obra · "
         f"R$ {sum(p['valor_contrato'] or 0 for p in peritadas):,.2f} contratado. **Indício de perícia, não acusação.**\n",
         "## Distribuição por fase"]
    for f, n in dist.most_common():
        L.append(f"- **{f}**: {n}")
    L.append(f"\n## 🔴 OBRAS PARADAS/VENCIDAS-SUSPEITAS ({len(paradas)}) — vigência vencida, execução baixa\n")
    L.append("| R$ contrato | % pago | Vig. fim | Objeto | Fornecedor |\n|---:|---:|---|---|---|")
    for p in sorted(paradas, key=lambda x: -(x["valor_contrato"] or 0))[:a.top]:
        L.append(f"| {p['valor_contrato']:,.2f} | {p['pct_pago'] if p['pct_pago'] is not None else 'n/d'}% | "
                 f"{p['vig_fim'] or '—'} | {p['objeto'][:42]} | {(p['fornecedor'] or '')[:26]} |")
    open(a.md, "w").write("\n".join(L))
    print(f"[perícia obras] {len(peritadas)} obras | distribuição: {dict(dist)}")
    print(f"[perícia obras] 🔴 PARADAS/VENCIDAS-SUSPEITAS: {len(paradas)} (R$ {sum(p['valor_contrato'] or 0 for p in paradas):,.2f} contratado)")
    print(f"[perícia obras] relatório: {a.md} / .json")


if __name__ == "__main__":
    main()
