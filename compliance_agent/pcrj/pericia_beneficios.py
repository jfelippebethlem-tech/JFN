# -*- coding: utf-8 -*-
"""Perícia: nomeados (Câmara + Prefeitura do Rio) que recebem benefício assistencial
DURANTE a nomeação — com a SÉRIE TEMPORAL (de quando até quando) e o ÓRGÃO de lotação.

Fonte: folha de pessoal PCRJ/CMRJ (nomeados vigentes) × arquivos mensais públicos do Portal da
Transparência (Bolsa Família / BPC). Cruzamento por NOME normalizado, desambiguado pelo fragmento
público do CPF mascarado (pessoas distintas por nome → separa homônimo de sinal defensável).

Relatório sem marca institucional (entregável neutro). Honesto: indício, nunca acusação — sem o
CPF completo do servidor não se PROVA identidade; benefício assistencial pressupõe baixa renda, o
que é incompatível com cargo comissionado, mas a apuração formal é da Controladoria/Ministério
Público.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from compliance_agent.pcrj import db as _db
from compliance_agent.pcrj.orgaos_siglas import decodificar

BENEF_DB = _db.DB_PATH.parent / "pcrj_benef.db"
_REPORTS = Path(__file__).resolve().parents[2] / "reports"


def _comp_legivel(ym: str) -> str:
    """'202605' -> 'mai/2026'."""
    meses = ["", "jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
    try:
        return f"{meses[int(ym[4:6])]}/{ym[:4]}"
    except Exception:
        return ym


def _orgaos_do_nome(con, nome_norm: str) -> tuple[str, str, str, str]:
    """Devolve (poder, orgao_legivel, cargo, ingresso) para um nome. Pode estar nos dois poderes;
    prioriza a informação mais rica. Câmara traz data de ingresso; Prefeitura traz sigla de órgão."""
    poder, orgao, cargo, ingresso = "", "", "", ""
    cam = con.execute(
        "SELECT lotacao, cargo, data1 FROM pcrj_camara_servidores WHERE nome_norm=? LIMIT 1",
        (nome_norm,)).fetchone()
    if cam:
        poder = "Câmara Municipal"
        orgao = cam["lotacao"] or "(lotação não informada)"
        cargo = cam["cargo"] or ""
        ingresso = cam["data1"] or ""
    prefs = con.execute(
        "SELECT orgao, cargo FROM pcrj_prefeitura_consulta WHERE nome_norm=? AND encontrado=1",
        (nome_norm,)).fetchall()
    if prefs:
        orgs = sorted({decodificar(r["orgao"]) for r in prefs if r["orgao"]})
        if orgs:
            pref_org = " ; ".join(orgs)
            if poder:  # está nos DOIS poderes
                poder = "Câmara + Prefeitura"
                orgao = f"{orgao} | {pref_org}"
            else:
                poder = "Prefeitura"
                orgao = pref_org
                cargo = prefs[0]["cargo"] or ""
    return poder or "(poder não identificado)", orgao or "(órgão não informado)", cargo, ingresso


def analisar() -> dict:
    """Monta o dataset da perícia a partir do que foi coletado em pcrj_beneficio."""
    b = _db.sqlite3.connect(f"file:{BENEF_DB}?mode=ro", uri=True)
    b.row_factory = _db.sqlite3.Row
    p = _db.conectar()

    comps = [r[0] for r in b.execute("SELECT DISTINCT competencia FROM pcrj_beneficio ORDER BY 1")]
    ultima = comps[-1] if comps else None

    # Por (nome, benefício): série temporal + desambiguação por fragmento de CPF.
    linhas = b.execute("""
        SELECT nome_norm, nome, beneficio,
               COUNT(DISTINCT competencia)  AS n_meses,
               MIN(competencia)             AS desde,
               MAX(competencia)             AS ate,
               COUNT(DISTINCT cpf_frag)     AS n_frags,
               MAX(CASE WHEN municipio LIKE '%RIO DE JANEIRO%' THEN 1 ELSE 0 END) AS rio,
               MAX(competencia)             AS ultima_vista,
               (SELECT valor FROM pcrj_beneficio x
                 WHERE x.nome_norm=pcrj_beneficio.nome_norm AND x.beneficio=pcrj_beneficio.beneficio
                 ORDER BY competencia DESC LIMIT 1) AS valor_atual
        FROM pcrj_beneficio
        GROUP BY nome_norm, beneficio
    """).fetchall()

    registros, homonimos = [], 0
    for r in linhas:
        if r["n_frags"] != 1:          # provável homônimo — fora do sinal defensável
            homonimos += 1
            continue
        poder, orgao, cargo, ingresso = _orgaos_do_nome(p, r["nome_norm"])
        registros.append({
            "nome": r["nome"] or r["nome_norm"].title(),
            "poder": poder, "orgao": orgao, "cargo": cargo, "ingresso": ingresso,
            "beneficio": r["beneficio"],
            "desde": _comp_legivel(r["desde"]), "ate": _comp_legivel(r["ate"]),
            "n_meses": r["n_meses"],
            "ainda_recebe": (r["ate"] == ultima),
            "rio": bool(r["rio"]),
            "valor": r["valor_atual"] or "",
            "_desde_raw": r["desde"],
        })
    b.close(); p.close()

    # ordena: quem ainda recebe primeiro, depois por nº de meses (persistência), Rio antes
    registros.sort(key=lambda x: (not x["ainda_recebe"], not x["rio"], -x["n_meses"], x["nome"]))
    return {
        "competencias": comps, "ultima": ultima,
        "registros": registros, "homonimos": homonimos,
        "n_bpc": sum(1 for x in registros if x["beneficio"] == "BPC"),
        "n_bf": sum(1 for x in registros if x["beneficio"].startswith("Bolsa")),
        "n_rio": sum(1 for x in registros if x["rio"]),
        "n_ainda": sum(1 for x in registros if x["ainda_recebe"]),
    }


# ── template NEUTRO (sem qualquer marca institucional/agente/produto) ─────────────────
_TPL = """<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><style>
  @page { size: A4; margin: 16mm 14mm; }
  body { font-family: 'Helvetica Neue', Arial, sans-serif; color:#1a1a1a; font-size:10.5px; line-height:1.5; }
  .capa { border-bottom:3px solid #7a1f1f; padding-bottom:10px; margin-bottom:14px; }
  .classif { color:#7a1f1f; font-weight:700; letter-spacing:1px; font-size:10px; }
  h1 { font-size:20px; color:#3a1010; margin:4px 0; }
  .meta { color:#555; font-size:9.5px; }
  h2 { font-size:13px; color:#7a1f1f; border-bottom:1px solid #e0d3d3; padding-bottom:3px; margin-top:18px; }
  .kpis { display:flex; gap:10px; margin:12px 0; flex-wrap:wrap; }
  .kpi { border:1px solid #e2d5d5; border-radius:8px; padding:10px 14px; background:#fbf7f7; min-width:120px; }
  .kpi .n { font-size:22px; font-weight:700; color:#7a1f1f; line-height:1; }
  .kpi .l { font-size:9px; color:#666; margin-top:3px; }
  table { width:100%; border-collapse:collapse; font-size:9px; margin:6px 0; }
  th,td { text-align:left; padding:4px 5px; border-bottom:1px solid #eee; vertical-align:top; }
  th { background:#7a1f1f; color:#fff; }
  table tr:nth-child(even) td { background:#f7f0f0; }
  .tag { padding:1px 5px; border-radius:3px; font-size:8px; font-weight:600; }
  .sim { background:#fdecea; color:#c62828; }
  .rio { background:#fff3e0; color:#e65100; }
  .nota { font-size:9px; color:#666; font-style:italic; }
  footer { margin-top:22px; border-top:1px solid #ddd; padding-top:6px; font-size:8px; color:#888; }
</style></head><body>
  <div class="capa">
    <div class="classif">CONFIDENCIAL — SUBSÍDIO PARA APURAÇÃO</div>
    <h1>{{ titulo }}</h1>
    <div class="meta">Emitido em {{ data }} · Metodologia: cruzamento nominal com desambiguação por
    fragmento de CPF · Período coberto: {{ periodo }}</div>
  </div>

  <div class="kpis">
    <div class="kpi"><div class="n">{{ total }}</div><div class="l">nomeados com indício defensável</div></div>
    <div class="kpi"><div class="n">{{ n_ainda }}</div><div class="l">ainda recebendo em {{ ultima }}</div></div>
    <div class="kpi"><div class="n">{{ n_bpc }}</div><div class="l">no BPC/LOAS</div></div>
    <div class="kpi"><div class="n">{{ n_bf }}</div><div class="l">no Bolsa Família</div></div>
    <div class="kpi"><div class="n">{{ n_rio }}</div><div class="l">benefício no Rio (sinal forte)</div></div>
  </div>

  <p>Foram cruzados os nomeados vigentes da Câmara Municipal e da Prefeitura do Rio de Janeiro
  contra os beneficiários dos programas assistenciais federais, competência a competência. A tabela
  abaixo lista, para cada pessoa cujo nome corresponde a <b>um único beneficiário</b> (afastados os
  homônimos: {{ homonimos }} nomes descartados por baterem com mais de uma pessoa), o órgão em que
  está nomeada, o benefício, e a <b>janela em que o recebeu</b> — evidenciando a sobreposição com o
  vínculo público.</p>

  <h2>1. Nomeados recebendo benefício assistencial durante a nomeação</h2>
  <table>
    <tr><th>#</th><th>Nome</th><th>Poder</th><th>Órgão de lotação</th><th>Cargo</th>
        <th>Ingresso</th><th>Benefício</th><th>Recebeu de</th><th>até</th><th>Meses</th>
        <th>Ainda recebe?</th><th>Sinal</th></tr>
    {% for r in registros %}
    <tr><td>{{ loop.index }}</td><td>{{ r.nome }}</td><td>{{ r.poder }}</td><td>{{ r.orgao }}</td>
        <td>{{ r.cargo }}</td><td>{{ r.ingresso }}</td><td>{{ r.beneficio }}</td>
        <td>{{ r.desde }}</td><td>{{ r.ate }}</td><td style="text-align:center">{{ r.n_meses }}</td>
        <td>{% if r.ainda_recebe %}<span class="tag sim">SIM ({{ ultima }})</span>{% else %}não{% endif %}</td>
        <td>{% if r.rio %}<span class="tag rio">Rio</span>{% endif %}</td></tr>
    {% endfor %}
  </table>
  <p class="nota">"Recebeu de/até" reflete a primeira e a última competência com o benefício dentro
  do período coberto ({{ periodo }}); uma janela que começa no início do período pode ter iniciado
  antes. "Ainda recebe" = presente na competência mais recente disponível.</p>

  <h2>2. Método e ressalvas</h2>
  <p>Cruzamento por nome normalizado (sem acento/caixa) contra os arquivos mensais oficiais de
  Bolsa Família e BPC. Como um nome comum bate com várias pessoas, capturou-se o fragmento público
  de CPF do arquivo (dígitos visíveis do CPF mascarado) e contaram-se pessoas distintas por nome —
  <b>só entram no relatório os nomes que correspondem a exatamente uma pessoa</b>. Mesmo assim, sem
  o CPF completo do servidor não se comprova em definitivo que o nomeado e o beneficiário são a
  mesma pessoa: trata-se de <b>indício qualificado</b> para apuração, não de acusação. Benefício
  assistencial pressupõe baixa renda (BPC: renda familiar per capita inferior a ¼ do salário
  mínimo; Bolsa Família: linha de pobreza), condição em tensão com o exercício de cargo remunerado
  — cuja apuração formal compete aos órgãos de controle e ao Ministério Público.</p>

  <footer>Peça de subsídio à apuração — indícios, não acusação; presunção de legitimidade dos atos
  administrativos preservada. Dados de fonte pública oficial. CPF de terceiros mascarado (LGPD).</footer>
</body></html>"""


def render(dados: dict) -> str:
    from jinja2 import Template
    comps = dados["competencias"]
    periodo = f"{_comp_legivel(comps[0])} a {_comp_legivel(comps[-1])}" if comps else "—"
    return Template(_TPL).render(
        titulo="Perícia — Nomeados da Câmara e da Prefeitura do Rio recebendo benefício assistencial",
        data=datetime.now().strftime("%d/%m/%Y"),
        periodo=periodo, ultima=_comp_legivel(dados["ultima"]) if dados["ultima"] else "—",
        total=len(dados["registros"]), n_ainda=dados["n_ainda"],
        n_bpc=dados["n_bpc"], n_bf=dados["n_bf"], n_rio=dados["n_rio"],
        homonimos=dados["homonimos"], registros=dados["registros"],
    )


async def gerar_pdf() -> str:
    from compliance_agent.reporting.render_html import html_to_pdf
    dados = analisar()
    html = render(dados)
    destino = str(_REPORTS / f"pericia_beneficios_nomeados_{datetime.now().date()}.pdf")
    await html_to_pdf(html, destino)
    return destino


if __name__ == "__main__":
    import asyncio
    import json
    d = analisar()
    print(json.dumps({k: v for k, v in d.items() if k != "registros"}, ensure_ascii=False, indent=1))
    print("registros:", len(d["registros"]))
    print(asyncio.run(gerar_pdf()))
