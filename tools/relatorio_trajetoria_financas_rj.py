#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Trajetória das finanças e do orçamento do Estado do RJ (2016–último exercício publicado).

Fonte: Portal de Dados Abertos do RJ — TFE Despesa e TFE Receita (espelho do SIAFE-Rio), coletado por
tools/coletar_dadosabertos_rj.py em data/dadosabertos_rj.db (visões v_traj_*). Valores CONSOLIDADOS:
sem o intraorçamentário (o Estado pagando a si mesmo). Correção monetária pelo IPCA (BCB/SGS série 433),
a preços do último ano completo, por média anual do índice.

HONESTIDADE: empenho ≠ liquidação ≠ pagamento; "pago" aqui é o pago orçamentário agregado do TFE, não OB
a favorecido. O último exercício é PARCIAL (posição do arquivo) e vai marcado; nunca comparado como ano cheio.

    python tools/relatorio_trajetoria_financas_rj.py [--enviar]
"""
import argparse
import base64
import io
import re
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import httpx
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

REPO = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(REPO))
from compliance_agent.reporting.render_html import render_html  # noqa: E402

DB = REPO / "data" / "dadosabertos_rj.db"
RPT = REPO / "reports"
CHAT = "45338178"
B = 1e9
AZUL, CIANO, LARANJA, CINZA, VERM = "#0b3d91", "#0aa5c0", "#e07b00", "#8a94a6", "#b3261e"


def brl(x, casas=2):
    return f"R$ {x:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def bi(x):
    return brl((x or 0) / B) + " bi"


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def tabela(cab, linhas):
    h = "".join(f"<th>{esc(c)}</th>" for c in cab)
    b = "".join("<tr>" + "".join(f"<td>{esc(c)}</td>" for c in ln) + "</tr>" for ln in linhas)
    return f"<table><tr>{h}</tr>{b}</table>"


def png(fig):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    return f'<img style="width:100%;max-width:760px" src="data:image/png;base64,{base64.b64encode(buf.getvalue()).decode()}"/>'


def ipca_medio_anual() -> dict[int, float]:
    """Índice encadeado (base jan/2016=1) e média por ano. Sem rede → {} e o relatório declara nominal."""
    try:
        r = httpx.get("https://api.bcb.gov.br/dados/serie/bcdata.sgs.433/dados",
                      params={"formato": "json", "dataInicial": "01/01/2016"}, timeout=60)
        serie = r.json()
    except (httpx.HTTPError, ValueError, KeyError):  # sem IPCA o relatório sai em valores nominais, declarado
        return {}
    idx, acc, por_ano = 1.0, {}, {}
    for p in serie:
        idx *= 1 + float(p["valor"]) / 100
        por_ano.setdefault(int(p["data"][-4:]), []).append(idx)
    acc = {a: sum(v) / len(v) for a, v in por_ano.items()}
    return acc


def eixo(ax, titulo):
    ax.set_title(titulo, fontsize=11, loc="left", color="#1a1f2b")
    ax.grid(axis="y", color="#e3e7ee", linewidth=0.8)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.tick_params(labelsize=8)


def montar():
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    rec = {r[0]: r for r in c.execute("SELECT ano,posicao,previsao_inicial,previsao_atualizada,realizada_liquida,"
                                      "deducoes,realizada_bruta,intraorcamentaria FROM v_traj_receita_ano")}
    des = {r[0]: r for r in c.execute("SELECT ano,posicao,dotacao_inicial,dotacao_atual,empenhado,liquidado,pago,"
                                      "rp_pago,desembolsado,rp_a_pagar,empenhado_consolidado,pago_consolidado "
                                      "FROM v_traj_despesa_ano")}
    anos = sorted(set(rec) & set(des))
    parcial = {a for a in anos if not rec[a][1].startswith("12/") or not des[a][1].startswith("12/")}
    cheios = [a for a in anos if a not in parcial]
    ult = cheios[-1]
    ipca = ipca_medio_anual()
    real = bool(ipca) and all(a in ipca for a in anos)
    f = (lambda a, v: (v or 0) * ipca[ult] / ipca[a]) if real else (lambda a, v: v or 0)
    rot = f"R$ bi de {ult} (IPCA)" if real else "R$ bi nominais"

    sec = []
    # 1. quadro-síntese
    linhas = []
    for a in anos:
        r, d = rec[a], des[a]
        res = (r[4] or 0) - (d[10] or 0)
        linhas.append([f"{a}{' (parcial ' + r[1] + ')' if a in parcial else ''}", bi(r[2]), bi(r[4]), bi(d[3]),
                       bi(d[10]), bi(d[11]), bi(res), bi(d[9])])
    sec.append({"titulo": "2. Quadro-síntese anual (valores nominais, consolidados)", "html": tabela(
        ["Exercício", "Receita prevista (LOA)", "Receita realizada", "Dotação atualizada", "Despesa empenhada",
         "Despesa paga", "Resultado orçamentário¹", "Restos a pagar a pagar"], linhas)
        + "<p>¹ Receita realizada líquida (após deduções, sem intraorçamentária) menos despesa empenhada "
          "consolidada (sem modalidades intraorçamentárias 91/93–96). Dotação atualizada inclui intraorçamentária.</p>"})

    # 2. gráficos
    fig, ax = plt.subplots(figsize=(8, 3.6))
    ax.plot(cheios, [f(a, rec[a][4]) / B for a in cheios], marker="o", color=AZUL, label="Receita realizada")
    ax.plot(cheios, [f(a, des[a][10]) / B for a in cheios], marker="o", color=LARANJA, label="Despesa empenhada")
    ax.plot(cheios, [f(a, des[a][11]) / B for a in cheios], marker=".", ls="--", color=CINZA, label="Despesa paga")
    eixo(ax, f"Receita × despesa consolidadas — {rot}"); ax.legend(fontsize=8, frameon=False)
    g1 = png(fig)
    fig, ax = plt.subplots(figsize=(8, 3.0))
    vals = [f(a, (rec[a][4] or 0) - (des[a][10] or 0)) / B for a in cheios]
    ax.bar(cheios, vals, color=[CIANO if v >= 0 else VERM for v in vals])
    for x, v in zip(cheios, vals):
        ax.annotate(f"{v:+.1f}".replace(".", ","), (x, v), ha="center", va="bottom" if v >= 0 else "top", fontsize=8)
    ax.axhline(0, color="#1a1f2b", lw=0.8); eixo(ax, f"Resultado orçamentário — {rot}")
    g2 = png(fig)
    fig, ax = plt.subplots(figsize=(8, 3.0))
    ax.bar(cheios, [f(a, des[a][9]) / B for a in cheios], color=CINZA)
    eixo(ax, f"Restos a pagar ainda a pagar ao fim do exercício — {rot}")
    g3 = png(fig)
    sec.insert(0, {"titulo": "1. Trajetória em gráficos", "html": g1 + g2 + g3 + (
        f"<p>Valores corrigidos pelo IPCA médio anual a preços de {ult}. Anos parciais ficam fora dos gráficos.</p>"
        if real else "<p><b>IPCA indisponível nesta geração: valores NOMINAIS.</b></p>")})

    # 3. função
    top = [r[0] for r in c.execute(f"SELECT nome_funcao FROM v_traj_despesa_funcao WHERE ano={ult} "
                                   "ORDER BY empenhado DESC LIMIT 9")]
    fun = {}
    for a, nf, emp in c.execute("SELECT ano,nome_funcao,empenhado FROM v_traj_despesa_funcao"):
        fun[(a, nf)] = emp or 0
    fig, ax = plt.subplots(figsize=(8, 4.2))
    cores = plt.cm.tab10.colors
    for i, nf in enumerate(top):
        ax.plot(cheios, [f(a, fun.get((a, nf), 0)) / B for a in cheios], marker=".", color=cores[i % 10], label=nf)
    eixo(ax, f"Despesa empenhada por função — {rot}"); ax.legend(fontsize=7, frameon=False, ncol=3)
    a0 = cheios[0]
    lf = [[nf, bi(fun.get((a0, nf))), bi(fun.get((ult, nf))),
           (f"{(fun.get((ult, nf), 0) / f(a0, fun.get((a0, nf))) - 1) * 100:+.1f}%".replace(".", ",")
            if real and fun.get((a0, nf)) else "—")] for nf in top]
    sec.append({"titulo": "3. Para onde vai o dinheiro — função de governo", "html": png(fig) + tabela(
        ["Função", f"Empenhado {a0} (nominal)", f"Empenhado {ult} (nominal)", "Variação real"], lf)})

    # 3-A. grupo de natureza de despesa
    # o CSV traz o NOME do grupo trocado (grupo 1 sai como "OUTRAS DESPESAS CORRENTES"): nome oficial pelo código
    # (Portaria Interministerial STN/SOF 163/2001, art. 3º).
    NOMES_GRUPO = {"1": "Pessoal e Encargos Sociais", "2": "Juros e Encargos da Dívida", "3": "Outras Despesas Correntes",
                   "4": "Investimentos", "5": "Inversões Financeiras", "6": "Amortização da Dívida",
                   "9": "Reserva de Contingência"}
    gr = {}
    for a, g, ng, emp in c.execute("SELECT ano,grupo,nome_grupo,empenhado FROM v_traj_despesa_grupo"):
        gr.setdefault(g, [NOMES_GRUPO.get(g, ng), {}])[1][a] = emp or 0
    ordem = sorted(gr, key=lambda g: -gr[g][1].get(ult, 0))
    lg = []
    for g in ordem:
        v0, v1 = gr[g][1].get(a0, 0), gr[g][1].get(ult, 0)
        var = f"{(v1 / f(a0, v0) - 1) * 100:+.1f}%".replace(".", ",") if real and v0 else "—"
        lg.append([gr[g][0], bi(v0), bi(v1), var, f"{v1 / (des[ult][10] or 1) * 100:.1f}%".replace(".", ",")])
    sec.append({"titulo": "3-A. Natureza da despesa — pessoal, dívida, custeio e investimento", "html": tabela(
        ["Grupo", f"Empenhado {a0}", f"Empenhado {ult}", "Variação real", f"Peso em {ult}"], lg)
        + "<p>Série normalizada: em 2016 aposentadorias e pensões (elementos 01 e 03) foram classificadas como "
          "Outras Despesas Correntes; de 2017 em diante, como Pessoal. Aqui estão em Pessoal em todos os anos.</p>"})

    # 4. receita por origem
    ori = {}
    for a, o, no, v in c.execute("SELECT ano,origem,nome_origem,realizada FROM v_traj_receita_origem"):
        ori.setdefault(o, [no, {}])[1][a] = v or 0
    topo = sorted(ori, key=lambda o: -ori[o][1].get(ult, 0))[:6]
    fig, ax = plt.subplots(figsize=(8, 3.8))
    for i, o in enumerate(topo):
        ax.plot(cheios, [f(a, ori[o][1].get(a, 0)) / B for a in cheios], marker=".", color=cores[i], label=ori[o][0][:40])
    eixo(ax, f"Receita bruta por origem — {rot}"); ax.legend(fontsize=7, frameon=False)
    lo = [[ori[o][0], bi(ori[o][1].get(a0)), bi(ori[o][1].get(ult))] for o in topo]
    sec.append({"titulo": "4. De onde vem o dinheiro — origem da receita", "html": png(fig) + tabela(
        ["Origem", f"Realizado {a0} (nominal)", f"Realizado {ult} (nominal)"], lo)
        + "<p>Receita bruta antes das deduções (FUNDEB, cota-parte municipal). Receita patrimonial inclui royalties "
          "e participações do petróleo.</p>"})

    # 5. órgãos
    lo = [[r[0], r[1], bi(r[2]), bi(r[3])] for r in c.execute(
        f"""SELECT o.orgao, o.nome_orgao, (SELECT empenhado FROM v_traj_despesa_orgao p WHERE p.orgao=o.orgao AND p.ano={a0}),
            o.empenhado FROM v_traj_despesa_orgao o WHERE o.ano={ult} ORDER BY o.empenhado DESC LIMIT 15""")]
    sec.append({"titulo": "5. Maiores órgãos por despesa empenhada", "html": tabela(
        ["Órgão", "Nome", f"{a0} (nominal)", f"{ult} (nominal)"], lo)
        + "<p><b>Atenção:</b> a estrutura de órgãos muda no período (secretarias criadas, extintas e fundidas; "
          "códigos reaproveitados). Variação por órgão reflete reorganização tanto quanto gasto — a série estável "
          "é a por função (seção 3) e por grupo (seção 3-A).</p>"})

    # 6. execução e planejamento
    le = []
    for a in anos:
        d = des[a]
        le.append([f"{a}{'*' if a in parcial else ''}", bi(d[2]), bi(d[3]),
                   f"{(d[4] or 0) / (d[3] or 1) * 100:.1f}%".replace(".", ","), f"{(d[6] or 0) / (d[4] or 1) * 100:.1f}%".replace(".", ","), bi(d[7])])
    sec.append({"titulo": "6. Planejamento e execução da despesa (inclui intraorçamentária)", "html": tabela(
        ["Exercício", "Dotação inicial (LOA)", "Dotação atualizada", "Empenhado / dotação", "Pago / empenhado",
         "Restos a pagar pagos"], le) + "<p>* exercício parcial.</p>"})

    r_ult, d_ult = rec[ult], des[ult]
    res_ult = (r_ult[4] or 0) - (d_ult[10] or 0)
    pico_rp = max(cheios, key=lambda a: des[a][9] or 0)
    flags = [
        f"{ult}: receita realizada {bi(r_ult[4])} × despesa empenhada {bi(d_ult[10])} → resultado {bi(res_ult)}",
        f"Restos a pagar a pagar: {bi(des[pico_rp][9])} em {pico_rp} → {bi(d_ult[9])} em {ult}",
        f"Receita realizada {a0}→{ult}: {bi(rec[a0][4])} → {bi(r_ult[4])} (nominal)",
    ]
    if parcial:
        flags.append(f"{', '.join(map(str, sorted(parcial)))}: dado parcial — o portal não atualiza desde a posição do arquivo")
    reg = c.execute("SELECT MAX(modificado_portal) FROM da_recurso").fetchone()[0]
    return {
        "classificacao": "USO INTERNO — FISCALIZAÇÃO",
        "titulo": "Trajetória das finanças do Estado do Rio de Janeiro",
        "subtitulo": f"Receita, despesa, resultado e restos a pagar · {anos[0]}–{anos[-1]}",
        "data": datetime.now().strftime("%d/%m/%Y"), "analista": "JFN — Núcleo de Fiscalização (Yoda)",
        "metodologia": ("TFE Despesa/Receita do Portal de Dados Abertos do RJ (espelho do SIAFE-Rio) · consolidação sem "
                        "intraorçamentário · deduplicação do defeito do CSV de receita 2024+ · IPCA/BCB série 433"),
        "score": 0, "faixa": "BAIXO", "top_flags": flags, "secoes": sec,
        "proveniencia": [
            {"dado": "TFE Despesa 2016–2025 (11 arquivos; 2019 e 2021 publicados em duplicata, uma cópia descartada)",
             "estado": "REAL", "fonte": "dadosabertos.rj.gov.br/dataset/tfe-despesa", "data": str(reg)[:10]},
            {"dado": "TFE Receita 2016–2025 (2024+ deduplicado: 3.351 → 989 linhas em 2024)", "estado": "REAL",
             "fonte": "dadosabertos.rj.gov.br/dataset/tfe-receita", "data": str(reg)[:10]},
            {"dado": "IPCA mensal", "estado": "REAL" if real else "INDISPONIVEL", "fonte": "BCB/SGS 433",
             "data": datetime.now().strftime("%d/%m/%Y")},
        ],
        "ressalva": ("Empenho não é pagamento. Os valores são agregados orçamentários (não ordens bancárias a favorecido). "
                     "O CSV de receita de 2024 em diante repete linhas sob fontes distintas: o total foi deduplicado, mas a "
                     "classificação por fonte de recursos da receita nesses anos não é confiável. Exercício parcial não "
                     "é comparável a ano cheio."),
    }


def to_pdf(ctx, nome):
    hp, pp = RPT / f"{nome}.html", RPT / f"{nome}.pdf"
    hp.write_text(render_html(ctx))
    subprocess.run(["chromium", "--headless=new", "--no-sandbox", "--disable-gpu", "--no-pdf-header-footer",
                    f"--print-to-pdf={pp}", f"file://{hp}"], capture_output=True, timeout=240)
    return pp if pp.exists() and pp.stat().st_size > 0 else None


def enviar(pdf, legenda):
    m = re.search(r"^TELEGRAM_BOT_TOKEN=(.+)$", Path("/home/ubuntu/.hermes/.env").read_text(), re.M)
    if not m:
        raise SystemExit("TELEGRAM_BOT_TOKEN ausente em ~/.hermes/.env")
    with open(pdf, "rb") as fh:
        r = httpx.post(f"https://api.telegram.org/bot{m.group(1).strip().strip(chr(34))}/sendDocument",
                       data={"chat_id": CHAT, "caption": legenda},
                       files={"document": (pdf.name, fh, "application/pdf")}, timeout=120)
    print("Telegram:", r.status_code, r.json().get("ok"))
    return r.json().get("ok", False)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--enviar", action="store_true")
    a = ap.parse_args()
    pdf = to_pdf(montar(), f"trajetoria_financas_rj_{datetime.now().date()}")
    print("PDF:", pdf, pdf.stat().st_size if pdf else "FALHOU")
    if pdf and a.enviar:
        sys.exit(0 if enviar(pdf, "📊 Trajetória das finanças e do orçamento do Estado do RJ — 2016–2025 "
                                  "(Dados Abertos RJ/TFE, corrigido pelo IPCA)") else 1)
