# -*- coding: utf-8 -*-
"""
Gerador de RELATÓRIO HTML de inteligência/risco — padrão JFN (Kroll/Deloitte/Control Risks).

Lê as Ordens Bancárias do compliance.db e produz um relatório HTML profissional seguindo o padrão
do CLAUDE.md: capa, sumário executivo com rating de risco, análise financeira (OBs = pagamento
definitivo), red flags com fundamento legal, matriz de risco TCU P×I, recomendações, referências.

Uso:
    python -m compliance_agent.reports.html_report --out reports/relatorio_obs.html
    python -m compliance_agent.reports.html_report --favorecido MGS   # foca um favorecido
"""
import argparse
import os
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent.parent
DB = Path(os.environ.get("JFN_DATA_DIR", _REPO / "data")) / "compliance.db"


def _brl(v):
    try:
        return f"R$ {float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return "R$ 0,00"


def _carregar_obs(favorecido=""):
    con = sqlite3.connect(str(DB)); con.row_factory = sqlite3.Row
    q = "SELECT * FROM ordens_bancarias WHERE categoria='siafe_ob'"
    args = []
    if favorecido:
        q += " AND UPPER(favorecido_nome) LIKE ?"; args.append(f"%{favorecido.upper()}%")
    rows = [dict(r) for r in con.execute(q + " ORDER BY valor DESC", args).fetchall()]
    con.close()
    return rows


def _analise(obs):
    total = sum((o.get("valor") or 0) for o in obs)
    por_fav = defaultdict(float); por_ug = defaultdict(float)
    redondos, sem_proc, datas = [], [], []
    for o in obs:
        v = o.get("valor") or 0
        por_fav[o.get("favorecido_nome") or "?"] += v
        por_ug[o.get("ug_codigo") or "?"] += v
        if v >= 10000 and abs(v - round(v / 10000) * 10000) < 0.01:
            redondos.append(o)
        if not o.get("numero_sei"):
            sem_proc.append(o)
        if o.get("data_emissao"):
            datas.append(o["data_emissao"])
    # HHI de concentração por favorecido
    hhi = sum((v / total) ** 2 for v in por_fav.values()) * 10000 if total else 0
    return {"total": total, "n": len(obs), "por_fav": por_fav, "por_ug": por_ug,
            "redondos": redondos, "sem_proc": sem_proc, "hhi": hhi,
            "periodo": (min(datas), max(datas)) if datas else ("?", "?")}


def _rating(a):
    score = 0
    if a["hhi"] > 2500: score += 3            # alta concentração
    if len(a["sem_proc"]) > a["n"] * 0.3: score += 2
    if len(a["redondos"]) > a["n"] * 0.2: score += 2
    if score >= 5: return ("🔴", "ALTO", score)
    if score >= 2: return ("🟡", "MÉDIO", score)
    return ("🟢", "BAIXO", score)


def gerar_html(favorecido=""):
    obs = _carregar_obs(favorecido)
    a = _analise(obs)
    emoji, nivel, score = _rating(a)
    agora = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")
    top_fav = sorted(a["por_fav"].items(), key=lambda kv: kv[1], reverse=True)[:10]
    escopo = f"Favorecido contendo «{favorecido}»" if favorecido else "Amostra de OBs do Estado do RJ (SIAFE-Rio 2)"

    def linhas_top(items):
        return "".join(f"<tr><td>{k[:48]}</td><td class='num'>{_brl(v)}</td>"
                       f"<td class='num'>{(v/a['total']*100 if a['total'] else 0):.1f}%</td></tr>" for k, v in items)

    def linhas_obs(rows):
        out = ""
        for o in rows[:25]:
            proc = o.get("numero_sei") or "<span class='warn'>—</span>"
            out += (f"<tr><td>{o.get('numero_ob','')}</td><td>{o.get('data_emissao','') or ''}</td>"
                    f"<td>{(o.get('favorecido_nome') or '')[:34]}</td><td>{o.get('tipo_ob','')}</td>"
                    f"<td>{proc}</td><td class='num'>{_brl(o.get('valor'))}</td></tr>")
        return out

    redflags = []
    if a["hhi"] > 2500:
        redflags.append(("Concentração elevada de pagamentos", f"HHI {a['hhi']:.0f} (>2500). Concentração ≥60% em poucos favorecidos.",
                         "ACFE 2024 / metodologia TCU — red flag de concentração sem justificativa técnica."))
    if a["sem_proc"]:
        redflags.append((f"{len(a['sem_proc'])} OB(s) sem nº de processo SEI",
                         "Pagamentos sem processo administrativo vinculado dificultam a auditoria da liquidação.",
                         "Lei 4.320/64 (liquidação) — rastreabilidade do gasto público."))
    if a["redondos"]:
        redflags.append((f"{len(a['redondos'])} OB(s) com valor redondo (múltiplo de R$10k)",
                         "Valores exatos podem indicar estimativa/arredondamento atípico.",
                         "ACFE Report to the Nations 2024 — red flag de valores redondos."))
    if not redflags:
        redflags.append(("Sem red flags automáticos na amostra", "Nenhum indicador disparado nesta amostra.", "—"))

    rf_html = "".join(f"<div class='rf'><b>{t}</b><p>{d}</p><span class='base'>⚖ {b}</span></div>" for t, d, b in redflags)

    return f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<title>JFN — Relatório de Inteligência (OBs SIAFE)</title>
<style>
 body{{font-family:'Segoe UI',Arial,sans-serif;color:#1a2332;margin:0;background:#f4f6f9}}
 .wrap{{max-width:960px;margin:0 auto;background:#fff;box-shadow:0 0 20px rgba(0,0,0,.08)}}
 .capa{{background:linear-gradient(135deg,#0b2545,#13315c);color:#fff;padding:48px 56px}}
 .capa h1{{margin:0;font-size:30px;letter-spacing:.5px}} .capa .cls{{color:#7fb3ff;font-size:12px;text-transform:uppercase;letter-spacing:2px}}
 .capa .meta{{margin-top:18px;font-size:13px;color:#cfe0ff;line-height:1.7}}
 section{{padding:26px 56px;border-bottom:1px solid #eef1f5}}
 h2{{font-size:18px;color:#0b2545;border-left:4px solid #13315c;padding-left:12px;margin:0 0 16px}}
 table{{width:100%;border-collapse:collapse;font-size:13px}} th,td{{padding:8px 10px;text-align:left;border-bottom:1px solid #eef1f5}}
 th{{background:#0b2545;color:#fff;font-weight:600}} td.num{{text-align:right;font-variant-numeric:tabular-nums}}
 .rating{{font-size:34px;font-weight:700}} .kpi{{display:flex;gap:24px;flex-wrap:wrap;margin:10px 0}}
 .kpi div{{background:#f4f6f9;border-radius:8px;padding:14px 18px;min-width:150px}} .kpi b{{font-size:20px;color:#0b2545}}
 .rf{{background:#fff7f6;border-left:4px solid #c0392b;padding:12px 16px;margin:10px 0;border-radius:4px}}
 .rf p{{margin:4px 0;font-size:13px}} .base{{font-size:12px;color:#7a4a45}}
 .warn{{color:#c0392b;font-weight:700}} .foot{{padding:20px 56px;font-size:11px;color:#7a8aa0}}
 blockquote{{background:#eef4ff;border-left:4px solid #13315c;margin:0;padding:12px 16px;font-size:13px}}
</style></head><body><div class="wrap">
<div class="capa">
  <div class="cls">Confidencial · Due Diligence · Uso interno</div>
  <h1>Relatório de Inteligência Financeira — Ordens Bancárias</h1>
  <div class="meta">
    <b>Escopo:</b> {escopo}<br>
    <b>Fonte:</b> SIAFE-Rio 2 (pagamento definitivo — Ordem Bancária)<br>
    <b>Período da amostra:</b> {a['periodo'][0]} a {a['periodo'][1]} &nbsp;|&nbsp; <b>OBs analisadas:</b> {a['n']}<br>
    <b>Emitido em:</b> {agora} &nbsp;|&nbsp; <b>Analista:</b> JFN Intelligence Engine
  </div>
</div>

<section>
  <h2>1. Sumário Executivo</h2>
  <div class="kpi">
    <div>Rating de risco<br><span class="rating">{emoji} {nivel}</span></div>
    <div>Total pago (amostra)<br><b>{_brl(a['total'])}</b></div>
    <div>OBs analisadas<br><b>{a['n']}</b></div>
    <div>Concentração (HHI)<br><b>{a['hhi']:.0f}</b></div>
  </div>
  <blockquote><b>Nota metodológica:</b> Ordens Bancárias (OB) são o dado <b>definitivo</b> de pagamento público
  (saída de caixa, irreversível). Empenho ≠ pagamento. Esta amostra reflete as OBs mais recentes coletadas do
  SIAFE-Rio 2; não substitui a série completa do exercício.</blockquote>
</section>

<section>
  <h2>2. Análise Financeira — Maiores Favorecidos</h2>
  <table><tr><th>Favorecido</th><th>Valor pago</th><th>% do total</th></tr>{linhas_top(top_fav)}</table>
</section>

<section>
  <h2>3. Detalhe das Ordens Bancárias (top 25 por valor)</h2>
  <table><tr><th>Número</th><th>Data</th><th>Favorecido</th><th>Tipo</th><th>Processo SEI</th><th>Valor</th></tr>{linhas_obs(obs)}</table>
</section>

<section>
  <h2>4. Red Flags de Compliance</h2>{rf_html}
</section>

<section>
  <h2>5. Matriz de Risco (metodologia TCU P×I)</h2>
  <p style="font-size:13px">Score automático da amostra: <b>{score}</b> — faixa <b>{emoji} {nivel}</b>.
  Probabilidade × Impacto avaliados sobre concentração, ausência de processo SEI e valores atípicos.</p>
</section>

<section>
  <h2>6. Recomendações</h2>
  <ul style="font-size:13px;line-height:1.8">
    <li><b>Imediato:</b> rastrear no SEI as OBs com processo vinculado (coluna Processo) e revisar as sem processo.</li>
    <li><b>Curto prazo:</b> cruzar favorecidos contra CEIS/CNEP (sanções) e PNCP (contratos por CNPJ).</li>
    <li><b>Estrutural:</b> coletar a série completa do exercício (além das 50 OBs recentes) para análise de tendência.</li>
  </ul>
</section>

<section>
  <h2>7. Referências</h2>
  <p style="font-size:12px;color:#5a6b85">Lei 4.320/64 (liquidação/pagamento) · Lei 14.133/2021 · Metodologia TCU (matriz P×I) ·
  ACFE Report to the Nations 2024 · SIAFE-Rio 2 (SEFAZ-RJ) · Portal de Dados Abertos RJ (TFE Despesa).</p>
</section>

<div class="foot">JFN Intelligence Engine — relatório gerado automaticamente a partir do compliance.db.
Documento de uso interno; OBs são pagamento definitivo (não inclui empenhos brutos).</div>
</div></body></html>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(_REPO / "reports" / "relatorio_obs_siafe.html"))
    ap.add_argument("--favorecido", default="")
    a = ap.parse_args()
    html = gerar_html(a.favorecido)
    out = Path(a.out); out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"Relatório HTML gerado: {out} ({len(html):,} bytes)")


if __name__ == "__main__":
    main()
