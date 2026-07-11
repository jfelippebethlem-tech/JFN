# -*- coding: utf-8 -*-
"""
Gerador de RELATÓRIO HTML de inteligência/risco — padrão JFN ROBUSTO (Kroll/Control Risks/Deloitte).

Produz um relatório de due diligence/compliance de alto nível, data-driven a partir do compliance.db
(ordens_bancarias, contratos, empresas) + TFE (execução agregada). Seções: capa classificada, sumário
executivo com rating composto + tabela de exposição + alertas, perfil cadastral, carteira de contratos,
análise financeira (OB = pagamento definitivo; empenho = bruto), matriz de risco TCU P×I, red flags com
hipóteses e fundamento legal, concentração HHI, linha do tempo, recomendações por prazo, limitações,
referências. Estética profissional (CSS), indicadores 🔴🟡🟢, números BRL formatados.

Uso:
    python -m compliance_agent.reports.html_report --out reports/relatorio.html [--favorecido MGS] [--cnpj ...]
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
        return "R$ " + f"{float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return "R$ 0,00"


def _pct(v, t):
    return f"{(v / t * 100 if t else 0):.1f}%"


def _conn():
    con = sqlite3.connect(str(DB)); con.row_factory = sqlite3.Row
    return con


def coletar_dados(favorecido="", cnpj=""):
    con = _conn()
    d = {"obs": [], "contratos": [], "empresa": None}
    q = "SELECT * FROM ordens_bancarias WHERE 1=1"
    a = []
    if favorecido:
        q += " AND UPPER(favorecido_nome) LIKE ?"; a.append(f"%{favorecido.upper()}%")
    d["obs"] = [dict(r) for r in con.execute(q + " ORDER BY valor DESC", a).fetchall()]
    try:
        if cnpj:
            emp = con.execute("SELECT * FROM empresas WHERE cnpj=?", (cnpj,)).fetchone()
            if emp:
                d["empresa"] = dict(emp)
                d["contratos"] = [dict(r) for r in con.execute(
                    "SELECT * FROM contratos WHERE empresa_id=? ORDER BY valor_total DESC", (emp["id"],)).fetchall()]
        if not d["contratos"]:
            d["contratos"] = [dict(r) for r in con.execute(
                "SELECT * FROM contratos ORDER BY valor_total DESC LIMIT 50").fetchall()]
    except Exception:
        pass
    con.close()
    return d


def analisar(d):
    from compliance_agent.reports import categorizar as cat
    obs, contratos = d["obs"], d["contratos"]
    total_ob = sum((o.get("valor") or 0) for o in obs)
    total_ct = sum((c.get("valor_total") or 0) for c in contratos)
    por_fav = defaultdict(float); por_ug = defaultdict(float); por_org = defaultdict(float)
    por_area = defaultdict(float); por_orgao_pag = defaultdict(float)
    for o in obs:
        cat.enriquecer(o)  # adiciona o.area_objeto e o.orgao_pagador
        por_area[o["area_objeto"]] += (o.get("valor") or 0)
        por_orgao_pag[o["orgao_pagador"]] += (o.get("valor") or 0)
    redondos, sem_proc = [], []
    com_proc = 0
    datas = []
    for o in obs:
        v = o.get("valor") or 0
        por_fav[(o.get("favorecido_nome") or "?")[:50]] += v
        por_ug[o.get("ug_codigo") or "?"] += v
        if v >= 10000 and abs(v - round(v / 10000) * 10000) < 0.01:
            redondos.append(o)
        if o.get("numero_sei"):
            com_proc += 1
        else:
            sem_proc.append(o)
        if o.get("data_emissao"):
            datas.append(o["data_emissao"])
    for c in contratos:
        por_org[(c.get("orgao_contrat") or "?")[:50]] += (c.get("valor_total") or 0)
    hhi_fav = sum((v / total_ob) ** 2 for v in por_fav.values()) * 10000 if total_ob else 0
    hhi_org = sum((v / total_ct) ** 2 for v in por_org.values()) * 10000 if total_ct else 0
    # concentração top órgão de contratos
    top_org = sorted(por_org.items(), key=lambda kv: kv[1], reverse=True)
    conc_top_org = (top_org[0][1] / total_ct * 100) if total_ct and top_org else 0
    return {"total_ob": total_ob, "total_ct": total_ct, "n_ob": len(obs), "n_ct": len(contratos),
            "por_fav": por_fav, "por_ug": dict(por_ug), "por_org": por_org,
            "por_area": por_area, "por_orgao_pag": por_orgao_pag,
            "redondos": redondos, "sem_proc": sem_proc, "com_proc": com_proc,
            "hhi_fav": hhi_fav, "hhi_org": hhi_org, "conc_top_org": conc_top_org,
            "top_org": top_org, "periodo": (min(datas), max(datas)) if datas else ("—", "—")}


# --------------------------------------------------------------------- matriz de risco (regras)
def matriz_risco(an):
    R = []
    if an["conc_top_org"] > 40:
        R.append(("R01", f"Concentração em único órgão ({an['top_org'][0][0][:28]}: {an['conc_top_org']:.0f}%) — captura institucional", 5, 8))
    if an["hhi_org"] > 2500 or an["hhi_fav"] > 2500:
        R.append(("R02", f"Carteira altamente concentrada (HHI {max(an['hhi_org'],an['hhi_fav']):.0f} > 2500)", 5, 7))
    if an["sem_proc"]:
        frac = len(an["sem_proc"]) / max(an["n_ob"], 1)
        R.append(("R03", f"{len(an['sem_proc'])} OB(s) sem processo SEI ({frac*100:.0f}%) — rastreabilidade da liquidação", 4 if frac > 0.3 else 3, 6))
    if an["redondos"]:
        R.append(("R04", f"{len(an['redondos'])} OB(s) com valor redondo (múltiplo de R$10k) — padrão atípico", 4, 5))
    # aditivos em contratos
    # contratos sem coluna de aditivos confiável aqui — sem regra R de aditivo por ora
    if an["n_ct"] and an["total_ct"] > 50_000_000:
        R.append(("R05", "Exposição contratual elevada com o Estado (>R$50mi) — dependência de receita pública", 3, 6))
    if not R:
        R.append(("R01", "Sem riscos estruturais automáticos na amostra", 2, 3))
    # score e nível
    out = []
    for rid, desc, p, i in R:
        s = p * i
        nivel = "EXTREMO" if s >= 80 else ("ALTO" if s >= 40 else ("MÉDIO" if s >= 10 else "BAIXO"))
        out.append({"id": rid, "desc": desc, "p": p, "i": i, "score": s, "nivel": nivel})
    composto = min(10, round(sum(r["score"] for r in out) / (len(out) * 81) * 10 + max(r["score"] for r in out) / 81 * 5, 1))
    return out, composto


def red_flags(an):
    rf = []
    if an["conc_top_org"] > 40:
        rf.append(("RF-01", "ALTO", f"Concentração de contratos no órgão {an['top_org'][0][0][:30]} ({an['conc_top_org']:.0f}% do valor)",
                   ["Relacionamento com agentes públicos do órgão", "Especificações técnicas direcionadas",
                    "Verificar publicação no PNCP de todos os contratos"],
                   "Art. 3 Lei 8.666/93 (isonomia); Art. 37 CF/88 (impessoalidade); ACFE — vendor concentration."))
    if an["sem_proc"]:
        rf.append(("RF-02", "MÉDIO-ALTO", f"{len(an['sem_proc'])} OB(s) sem nº de processo SEI vinculado",
                   ["Pagamento sem processo administrativo rastreável", "Verificar liquidação correspondente",
                    "Cruzar com empenho/contrato"],
                   "Lei 4.320/64 (liquidação como pré-requisito do pagamento) — rastreabilidade do gasto."))
    if an["redondos"]:
        rf.append(("RF-03", "MÉDIO", f"{len(an['redondos'])} OB(s) com valor exato múltiplo de R$10.000",
                   ["Possível estimativa/arredondamento sem memória de cálculo", "Verificar nota fiscal/medição"],
                   "ACFE Report to the Nations 2024 — red flag de valores redondos."))
    if an["hhi_fav"] > 2500:
        rf.append(("RF-04", "MÉDIO-ALTO", f"Concentração de pagamentos por favorecido (HHI {an['hhi_fav']:.0f})",
                   ["Poucos favorecidos absorvem a maioria dos pagamentos", "Verificar natureza dos repasses"],
                   "Metodologia TCU; DOJ/FTC HHI (>2500 = alta concentração)."))
    if not rf:
        rf.append(("RF-00", "BAIXO", "Nenhum red flag automático disparado nesta amostra", ["—"], "—"))
    return rf


def _nivel_emoji(score10):
    if score10 >= 7: return ("🔴", "ALTO")
    if score10 >= 4: return ("🟡", "MÉDIO")
    return ("🟢", "BAIXO")


def gerar_html(favorecido="", cnpj=""):
    d = coletar_dados(favorecido, cnpj)
    an = analisar(d)
    riscos, composto = matriz_risco(an)
    rfs = red_flags(an)
    emoji, nivel = _nivel_emoji(composto)
    agora = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")
    sujeito = (d["empresa"] or {}).get("razao_social") if d["empresa"] else (favorecido or "Amostra SIAFE-Rio (Estado do RJ)")
    cnpj_txt = (d["empresa"] or {}).get("cnpj", cnpj or "—")

    top_fav = sorted(an["por_fav"].items(), key=lambda kv: kv[1], reverse=True)[:12]
    top_org = an["top_org"][:12]

    def tb(items, total):
        return "".join(f"<tr><td>{k}</td><td class='num'>{_brl(v)}</td><td class='num'>{_pct(v,total)}</td></tr>" for k, v in items)

    def tb_obs(rows):
        from compliance_agent.reports import categorizar as cat
        out = ""
        for o in rows[:30]:
            cat.enriquecer(o)
            proc = o.get("numero_sei") or "<span class='warn'>sem processo</span>"
            out += (f"<tr><td>{o.get('numero_ob','')}</td><td>{o.get('data_emissao') or '—'}</td>"
                    f"<td>{(o.get('favorecido_nome') or '')[:30]}</td><td><b>{o.get('area_objeto','')}</b></td>"
                    f"<td>{o.get('orgao_pagador','')[:28]}</td>"
                    f"<td>{proc}</td><td class='num'>{_brl(o.get('valor'))}</td></tr>")
        return out

    def tb_ct(rows):
        out = ""
        for c in rows[:15]:
            out += (f"<tr><td>{c.get('numero','')}</td><td>{(c.get('orgao_contrat') or '')[:36]}</td>"
                    f"<td>{c.get('status') or ''}</td><td class='num'>{_brl(c.get('valor_total'))}</td></tr>")
        return out

    risco_rows = "".join(
        f"<tr><td>{r['id']}</td><td>{r['desc']}</td><td class='num'>{r['p']}</td><td class='num'>{r['i']}</td>"
        f"<td class='num'><b>{r['score']}</b></td><td>{r['nivel']}</td></tr>" for r in riscos)

    rf_html = ""
    for rid, sev, desc, hips, base in rfs:
        hl = "".join(f"<li>{h}</li>" for h in hips)
        rf_html += (f"<div class='rf'><div class='rf-h'><b>{rid}</b> · <span class='sev'>{sev}</span> · {desc}</div>"
                    f"<div class='rf-b'><b>Hipóteses a investigar:</b><ul>{hl}</ul>"
                    f"<span class='base'>⚖ Fundamento: {base}</span></div></div>")

    alerta_rows = "".join(
        f"<tr><td>{i+1}</td><td>{r['desc']}</td><td><span class='badge {r['nivel'].lower()}'>{r['nivel']}</span></td></tr>"
        for i, r in enumerate(riscos))

    return f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>JFN — Relatório de Inteligência Financeira</title>
<style>
 :root{{--azul:#0b2545;--azul2:#13315c;--acc:#7fb3ff}}
 *{{box-sizing:border-box}} body{{font-family:'Segoe UI',Arial,sans-serif;color:#1a2332;margin:0;background:#eef1f5}}
 .wrap{{max-width:1000px;margin:0 auto;background:#fff;box-shadow:0 0 24px rgba(0,0,0,.1)}}
 .capa{{background:linear-gradient(135deg,var(--azul),var(--azul2));color:#fff;padding:54px 60px}}
 .capa .cls{{display:inline-block;border:1px solid var(--acc);color:var(--acc);font-size:11px;text-transform:uppercase;letter-spacing:2px;padding:4px 10px;border-radius:3px}}
 .capa h1{{margin:18px 0 6px;font-size:32px}} .capa h2{{margin:0;font-weight:400;font-size:17px;color:#cfe0ff}}
 .capa .meta{{margin-top:22px;font-size:13px;color:#cfe0ff;line-height:1.9;border-top:1px solid rgba(255,255,255,.2);padding-top:16px}}
 section{{padding:28px 60px;border-bottom:1px solid #eef1f5}}
 h2.sec{{font-size:19px;color:var(--azul);border-left:5px solid var(--azul2);padding-left:14px;margin:0 0 18px}}
 h3{{font-size:15px;color:var(--azul2);margin:18px 0 8px}}
 table{{width:100%;border-collapse:collapse;font-size:12.5px;margin:8px 0}}
 th,td{{padding:8px 11px;text-align:left;border-bottom:1px solid #eef1f5;vertical-align:top}}
 th{{background:var(--azul);color:#fff;font-weight:600}} td.num{{text-align:right;font-variant-numeric:tabular-nums}}
 tr:nth-child(even) td{{background:#f8fafc}}
 .rating{{font-size:38px;font-weight:800}} .kpi{{display:flex;gap:18px;flex-wrap:wrap;margin:12px 0}}
 .kpi div{{background:#f4f6f9;border-radius:10px;padding:16px 20px;min-width:160px;border:1px solid #e6ebf2}}
 .kpi small{{color:#6b7a90}} .kpi b{{font-size:21px;color:var(--azul);display:block;margin-top:4px}}
 .badge{{padding:2px 9px;border-radius:10px;font-size:11px;font-weight:700;color:#fff}}
 .badge.alto,.badge.extremo{{background:#c0392b}} .badge.médio,.badge.medio,.badge.médio-alto{{background:#e67e22}} .badge.baixo{{background:#27ae60}}
 .rf{{border:1px solid #f0d9d5;border-left:5px solid #c0392b;border-radius:6px;margin:12px 0;overflow:hidden}}
 .rf-h{{background:#fff7f6;padding:11px 16px;font-size:13.5px}} .rf-b{{padding:10px 16px;font-size:12.5px}}
 .rf .sev{{color:#c0392b;font-weight:700}} .rf ul{{margin:6px 0 8px 18px}} .base{{font-size:12px;color:#7a4a45}}
 .warn{{color:#c0392b;font-weight:600}}
 blockquote{{background:#eef4ff;border-left:4px solid var(--azul2);margin:8px 0;padding:12px 16px;font-size:13px}}
 .foot{{padding:22px 60px;font-size:11px;color:#7a8aa0;background:#fafbfc}}
 ul.rec{{font-size:13px;line-height:1.9}} .tl{{font-size:13px;line-height:1.8;border-left:2px solid #d6deea;padding-left:16px;margin-left:6px}}
</style></head><body><div class="wrap">

<div class="capa">
  <span class="cls">Confidencial · Due Diligence · Uso Interno</span>
  <h1>Relatório de Inteligência Financeira e Compliance</h1>
  <h2>{sujeito}</h2>
  <div class="meta">
    <b>CNPJ/Sujeito:</b> {cnpj_txt} &nbsp;·&nbsp; <b>Classificação:</b> Confidencial<br>
    <b>Fonte primária:</b> SIAFE-Rio 2 (Ordem Bancária = pagamento definitivo) + TFE/Dados Abertos RJ<br>
    <b>Período da amostra:</b> {an['periodo'][0]} a {an['periodo'][1]} &nbsp;·&nbsp; <b>OBs:</b> {an['n_ob']} &nbsp;·&nbsp; <b>Contratos:</b> {an['n_ct']}<br>
    <b>Emitido em:</b> {agora} &nbsp;·&nbsp; <b>Analista:</b> JFN Intelligence Engine &nbsp;·&nbsp; <b>Metodologia:</b> TCU P×I / ACFE / HHI
  </div>
</div>

<section>
  <h2 class="sec">Sumário Executivo</h2>
  <div class="kpi">
    <div><small>Rating de risco composto</small><span class="rating">{emoji} {composto}/10</span> <b>{nivel}</b></div>
    <div><small>Total pago (OBs)</small><b>{_brl(an['total_ob'])}</b></div>
    <div><small>Carteira de contratos</small><b>{_brl(an['total_ct'])}</b></div>
    <div><small>Concentração HHI</small><b>{max(an['hhi_org'],an['hhi_fav']):.0f}</b></div>
    <div><small>OBs c/ processo SEI</small><b>{an['com_proc']}/{an['n_ob']}</b></div>
  </div>
  <blockquote><b>Nota metodológica:</b> Ordem Bancária (OB) é o dado <b>definitivo</b> de pagamento público
  (saída de caixa, irreversível). Empenho ≠ pagamento — empenhos são valor bruto e podem ser cancelados.
  Esta análise prioriza OBs confirmadas; contratos e empenhos contextualizam a exposição.</blockquote>
  <h3>Alertas Prioritários</h3>
  <table><tr><th>#</th><th>Alerta</th><th>Nível</th></tr>{alerta_rows}</table>
</section>

<section>
  <h2 class="sec">1. Perfil Cadastral e Exposição</h2>
  <table><tr><th>Item</th><th>Valor</th></tr>
   <tr><td>Sujeito / Razão social</td><td>{sujeito}</td></tr>
   <tr><td>CNPJ</td><td>{cnpj_txt}</td></tr>
   <tr><td>Contratos mapeados</td><td>{an['n_ct']} — {_brl(an['total_ct'])}</td></tr>
   <tr><td>Ordens Bancárias (amostra)</td><td>{an['n_ob']} — {_brl(an['total_ob'])}</td></tr>
   <tr><td>Verificação CEIS/CNEP/CEPIM</td><td><span class="warn">Pendente</span> — cruzamento automático recomendado (Portal da Transparência)</td></tr>
  </table>
</section>

<section>
  <h2 class="sec">2. Carteira de Contratos — por Órgão</h2>
  <table><tr><th>Órgão contratante</th><th>Valor</th><th>% carteira</th></tr>{tb(top_org, an['total_ct'])}</table>
  <h3>Contratos de maior valor</h3>
  <table><tr><th>Número</th><th>Órgão</th><th>Situação</th><th>Valor</th></tr>{tb_ct(d['contratos'])}</table>
</section>

<section>
  <h2 class="sec">3. Análise Financeira — Maiores Favorecidos (OBs)</h2>
  <table><tr><th>Favorecido</th><th>Valor pago</th><th>% do total</th></tr>{tb(top_fav, an['total_ob'])}</table>
</section>

<section>
  <h2 class="sec">4. Distribuição por Área / Objeto do Gasto</h2>
  <p style="font-size:12.5px">Categorização inferida a partir do Nome do Favorecido, Tipo de OB e órgão pagador.
  O objeto contratual exato (ex.: "pavimentação", "insumos médicos") vem do contrato/processo SEI vinculado —
  aprofundamento por OB disponível via detalhe no SIAFE.</p>
  <table><tr><th>Área / Objeto</th><th>Valor pago</th><th>% do total</th></tr>
   {tb(sorted(an['por_area'].items(), key=lambda kv: kv[1], reverse=True), an['total_ob'])}</table>
  <h3>Órgãos pagadores (UG Pagadora → órgão)</h3>
  <table><tr><th>Órgão pagador</th><th>Valor pago</th><th>% do total</th></tr>
   {tb(sorted(an['por_orgao_pag'].items(), key=lambda kv: kv[1], reverse=True)[:12], an['total_ob'])}</table>
</section>

<section>
  <h2 class="sec">5. Detalhe das Ordens Bancárias (top 30 por valor)</h2>
  <table><tr><th>Número</th><th>Data</th><th>Favorecido</th><th>Área/Objeto</th><th>Órgão pagador</th><th>Processo SEI</th><th>Valor</th></tr>{tb_obs(d['obs'])}</table>
</section>

<section>
  <h2 class="sec">5. Matriz de Risco — Metodologia TCU (P×I)</h2>
  <p style="font-size:12.5px">Escala: Probabilidade (P) × Impacto (I), 1–9. Score = P×I. Faixas: Baixo 1–9 · Médio 10–39 · Alto 40–79 · Extremo 80–81.</p>
  <table><tr><th>#</th><th>Risco</th><th>P</th><th>I</th><th>Score</th><th>Nível</th></tr>{risco_rows}</table>
  <p style="margin-top:10px"><b>Rating composto JFN:</b> <span class="rating" style="font-size:22px">{emoji} {composto}/10 — {nivel}</span></p>
</section>

<section>
  <h2 class="sec">6. Red Flags de Compliance</h2>{rf_html}
</section>

<section>
  <h2 class="sec">7. Concentração — Indicador HHI</h2>
  <table><tr><th>Dimensão</th><th>HHI</th><th>Leitura</th></tr>
   <tr><td>Por órgão (contratos)</td><td class="num">{an['hhi_org']:.0f}</td><td>{'Alta concentração (>2500)' if an['hhi_org']>2500 else ('Moderada (1500–2500)' if an['hhi_org']>1500 else 'Baixa (<1500)')}</td></tr>
   <tr><td>Por favorecido (OBs)</td><td class="num">{an['hhi_fav']:.0f}</td><td>{'Alta concentração (>2500)' if an['hhi_fav']>2500 else ('Moderada (1500–2500)' if an['hhi_fav']>1500 else 'Baixa (<1500)')}</td></tr>
  </table>
  <blockquote>Referência DOJ/FTC: HHI &gt; 2500 indica mercado/carteira altamente concentrado — red flag de dependência e captura.</blockquote>
</section>

<section>
  <h2 class="sec">8. Recomendações</h2>
  <h3>Imediato (0–30 dias)</h3>
  <ul class="rec">
    <li>Rastrear no SEI as OBs com processo vinculado e revisar as OBs sem processo (rastreabilidade da liquidação).</li>
    <li>Cruzar todos os favorecidos/CNPJs contra CEIS/CNEP/CEPIM (sanções) — Portal da Transparência.</li>
  </ul>
  <h3>Curto prazo (30–90 dias)</h3>
  <ul class="rec">
    <li>Mapear contratos no PNCP por CNPJ (objeto, modalidade, aditivos) e verificar fracionamento.</li>
    <li>Validar a concentração por órgão com análise de objetos e modalidade licitatória.</li>
  </ul>
  <h3>Estrutural (90+ dias)</h3>
  <ul class="rec">
    <li>Coletar a série completa do exercício no SIAFE (além das OBs recentes) para análise de tendência e liquidações.</li>
    <li>Construir grafo de sócios (QSA via BrasilAPI/minha-receita) para detectar conluio entre licitantes.</li>
  </ul>
</section>

<section>
  <h2 class="sec">9. Limitações e Pendências</h2>
  <ul class="rec">
    <li>Amostra de OBs limitada às mais recentes do SIAFE (fetch do ADF = 50); série completa pendente.</li>
    <li>Verificação de sanções (CEIS/CNEP) e enriquecimento de CNPJ ainda não automatizados nesta versão.</li>
    <li>Empenhos são valor bruto (podem incluir cancelamentos); OBs são o dado definitivo.</li>
  </ul>
</section>

<section>
  <h2 class="sec">10. Referências e Fontes</h2>
  <p style="font-size:12px;color:#5a6b85;line-height:1.8">
   <b>Primárias:</b> SIAFE-Rio 2 (SEFAZ-RJ) · Portal de Dados Abertos RJ (TFE Despesa) · PNCP.<br>
   <b>Normativas:</b> Lei 4.320/64 · Lei 14.133/2021 · Lei 8.666/93 · CF/88 Art. 37.<br>
   <b>Controle:</b> TCU (matriz P×I) · TCE-RJ · CGU (CEIS/CNEP/CEPIM).<br>
   <b>Internacionais:</b> ACFE Report to the Nations 2024 · DOJ/FTC (HHI) · FATF/GAFI.</p>
</section>

<div class="foot">
  <b>JFN Intelligence Engine</b> — relatório gerado automaticamente a partir do compliance.db ({agora}).
  Documento confidencial de uso interno. OBs = pagamento definitivo (não inclui empenhos brutos).
  As hipóteses de red flags são indicativos a investigar, não conclusões de irregularidade.
</div>
</div></body></html>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(_REPO / "reports" / "relatorio_obs_siafe.html"))
    ap.add_argument("--favorecido", default="")
    ap.add_argument("--cnpj", default="")
    a = ap.parse_args()
    html = gerar_html(a.favorecido, a.cnpj)
    out = Path(a.out); out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"Relatório HTML robusto gerado: {out} ({len(html):,} bytes)")


if __name__ == "__main__":
    main()
