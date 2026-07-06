# -*- coding: utf-8 -*-
"""Perícia: SÓCIOS de empresas fornecedoras do Estado/Prefeitura que recebem (ou receberam)
benefício assistencial — BPC/LOAS, Bolsa Família, Auxílio Brasil, Auxílio Emergencial, Gás do
Povo — e QUANDO.

Sinal: quem é dono/sócio de empresa que fatura com o poder público e ao mesmo tempo recebe
benefício de renda mínima está, no mínimo, em situação de renda incompatível com o programa.

Vantagem de certeza sobre o cruzamento de servidores: o QSA da Receita traz o CPF MASCARADO do
sócio (***.XXX.XXX-**), cujos 6 dígitos do meio são o MESMO fragmento que o arquivo de benefício
expõe. Logo o casamento é por (nome + fragmento de CPF) — quando os dois batem, é praticamente a
mesma pessoa (não mero homônimo). Restringe-se ainda ao benefício pago no estado do Rio.

Fontes: socios_fornecedor (sócios das empresas favorecidas, compliance.db) × pcrj_beneficio
(benefícios já coletados por competência, UF=RJ). Relatório neutro (sem marca institucional).
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from compliance_agent.pcrj import db as _db

BENEF_DB = _db.DB_PATH.parent / "pcrj_benef.db"
COMPLIANCE_DB = _db.DB_PATH.parent / "compliance.db"
_REPORTS = Path(__file__).resolve().parents[2] / "reports"
_MESES = ["", "jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]


def _comp_legivel(ym: str) -> str:
    try:
        return f"{_MESES[int(ym[4:6])]}/{ym[:4]}"
    except Exception:
        return ym


def _frag6(doc: str | None) -> str:
    """Extrai os 6 dígitos do meio do CPF mascarado ('***240057**' -> '240057')."""
    d = "".join(re.findall(r"\d", doc or ""))
    return d[:6] if len(d) >= 6 else d


def _fmt_cnpj(c: str | None) -> str:
    c = re.sub(r"\D", "", c or "")
    return f"{c[:2]}.{c[2:5]}.{c[5:8]}/{c[8:12]}-{c[12:14]}" if len(c) == 14 else (c or "")


def analisar() -> dict:
    b = _db.sqlite3.connect(f"file:{BENEF_DB}?mode=ro", uri=True)
    b.row_factory = _db.sqlite3.Row
    comps = [r[0] for r in b.execute("SELECT DISTINCT competencia FROM pcrj_beneficio ORDER BY 1")]
    ultima = comps[-1] if comps else None
    anos = sorted({c[:4] for c in comps})

    # benefícios no Rio, agregados no SQL por (nome,frag,programa,ano) — evita carregar 7,3M linhas.
    ben: dict[tuple, dict] = {}
    frags_por_nome: dict[str, set] = {}
    for r in b.execute(
            "SELECT nome_norm, cpf_frag, beneficio, substr(competencia,1,4) AS ano, "
            "COUNT(DISTINCT competencia) AS n, MIN(competencia) AS cmin, MAX(competencia) AS cmax "
            "FROM pcrj_beneficio WHERE municipio='RIO DE JANEIRO' "
            "GROUP BY nome_norm, cpf_frag, beneficio, ano"):
        nn = r["nome_norm"]
        frag = (r["cpf_frag"] or "")[:6] or "?"
        frags_por_nome.setdefault(nn, set()).add(frag)
        e = ben.setdefault((nn, frag), {"prog": {}, "por_ano": {}, "cmin": r["cmin"], "cmax": r["cmax"]})
        pr = e["prog"].setdefault(r["beneficio"], {"cmin": r["cmin"], "cmax": r["cmax"], "n": 0})
        pr["cmin"] = min(pr["cmin"], r["cmin"]); pr["cmax"] = max(pr["cmax"], r["cmax"]); pr["n"] += r["n"]
        e["cmin"] = min(e["cmin"], r["cmin"]); e["cmax"] = max(e["cmax"], r["cmax"])
    for r in b.execute(
            "SELECT nome_norm, cpf_frag, substr(competencia,1,4) AS ano, "
            "COUNT(DISTINCT competencia) AS n FROM pcrj_beneficio WHERE municipio='RIO DE JANEIRO' "
            "GROUP BY nome_norm, cpf_frag, substr(competencia,1,4)"):
        e = ben.get((r["nome_norm"], (r["cpf_frag"] or "")[:6] or "?"))
        if e is not None:
            e["por_ano"][r["ano"]] = r["n"]
    b.close()

    # sócios de fornecedores (com CPF mascarado)
    cc = _db.sqlite3.connect(f"file:{COMPLIANCE_DB}?mode=ro", uri=True)
    cc.row_factory = _db.sqlite3.Row
    socios = cc.execute(
        "SELECT DISTINCT cnpj, razao, socio_nome, socio_nome_norm, socio_doc, qualificacao "
        "FROM socios_fornecedor WHERE socio_nome_norm<>''").fetchall()
    cc.close()

    registros = []
    for s in socios:
        nn = s["socio_nome_norm"]
        if nn not in frags_por_nome:
            continue                       # o sócio não aparece em benefício (no Rio) — sem sinal
        frag_socio = _frag6(s["socio_doc"])
        frags_ben = frags_por_nome[nn]
        # casamento por fragmento: se o fragmento do sócio está entre os do beneficiário homônimo
        if frag_socio and frag_socio in frags_ben:
            frag, certeza = frag_socio, "ALTA"          # nome + CPF batem: mesma pessoa
        elif len(frags_ben) == 1:
            frag = next(iter(frags_ben))
            certeza = "MÉDIA" if frag_socio else "MÉDIA"  # 1 beneficiário só, mas sem confirmar CPF
        else:
            continue                       # vários beneficiários homônimos e nenhum casa o CPF → fora
        e = ben[(nn, frag)]
        progs = []
        for prog, pr in sorted(e["prog"].items(), key=lambda kv: kv[1]["cmin"]):
            progs.append({"ben": prog, "desde": _comp_legivel(pr["cmin"]),
                          "ate": _comp_legivel(pr["cmax"]), "n": pr["n"]})
        registros.append({
            "socio": s["socio_nome"] or nn.title(),
            "empresa": s["razao"] or "", "cnpj": _fmt_cnpj(s["cnpj"]),
            "qualificacao": s["qualificacao"] or "",
            "cpf_frag": frag, "certeza": certeza,
            "programas": progs, "beneficios_str": ", ".join(p["ben"] for p in progs),
            "desde": _comp_legivel(e["cmin"]), "ate": _comp_legivel(e["cmax"]),
            "por_ano": {a: e["por_ano"].get(a, 0) for a in anos},
            "ainda_recebe": (e["cmax"] == ultima),
        })

    # dedup por (sócio, empresa) e ordena por certeza
    vistos, unicos = set(), []
    for r in sorted(registros, key=lambda x: (x["certeza"] != "ALTA", x["socio"])):
        k = (r["socio"], r["cnpj"], r["beneficios_str"])
        if k in vistos:
            continue
        vistos.add(k); unicos.append(r)

    por_emp: dict[str, list] = {}
    for r in unicos:
        por_emp.setdefault(f'{r["empresa"]} — {r["cnpj"]}', []).append(r)
    grupos = sorted(por_emp.items(), key=lambda kv: (-len(kv[1]), kv[0]))

    return {
        "competencias": comps, "anos": anos, "ultima": ultima,
        "registros": unicos, "grupos": grupos,
        "n_alta": sum(1 for x in unicos if x["certeza"] == "ALTA"),
        "n_media": sum(1 for x in unicos if x["certeza"] == "MÉDIA"),
        "n_ainda": sum(1 for x in unicos if x["ainda_recebe"]),
        "n_empresas": len(grupos),
    }


_TPL = """<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><style>
  @page { size: A4 landscape; margin: 12mm 10mm; }
  body { font-family:'Helvetica Neue',Arial,sans-serif; color:#1a1a1a; font-size:9.5px; line-height:1.45; }
  .capa { border-bottom:3px solid #1f4e5a; padding-bottom:9px; margin-bottom:12px; }
  .classif { color:#1f4e5a; font-weight:700; letter-spacing:1px; font-size:9.5px; }
  h1 { font-size:19px; color:#10303a; margin:4px 0; }
  .meta { color:#555; font-size:9px; }
  h2 { font-size:13px; color:#1f4e5a; border-bottom:1px solid #d3e0e0; padding-bottom:3px; margin-top:16px; }
  h3 { font-size:10.5px; color:#10303a; margin:12px 0 2px; background:#e9f1f2; padding:3px 7px; border-radius:4px; }
  .kpis { display:flex; gap:9px; margin:11px 0; flex-wrap:wrap; }
  .kpi { border:1px solid #d5e2e2; border-radius:8px; padding:9px 13px; background:#f7fbfb; min-width:120px; }
  .kpi .n { font-size:21px; font-weight:700; color:#1f4e5a; line-height:1; }
  .kpi .l { font-size:8.5px; color:#666; margin-top:3px; }
  table { width:100%; border-collapse:collapse; font-size:8.5px; margin:4px 0 10px; }
  th,td { text-align:left; padding:3px 5px; border-bottom:1px solid #eee; vertical-align:top; }
  th { background:#1f4e5a; color:#fff; }
  table tr:nth-child(even) td { background:#f0f6f6; }
  .tag { padding:1px 5px; border-radius:3px; font-size:8px; font-weight:600; }
  .alta { background:#fdecea; color:#c62828; } .media { background:#fff3e0; color:#e65100; }
  .nota { font-size:8.5px; color:#666; font-style:italic; }
  footer { margin-top:18px; border-top:1px solid #ddd; padding-top:6px; font-size:8px; color:#888; }
</style></head><body>
  <div class="capa">
    <div class="classif">CONFIDENCIAL — SUBSÍDIO PARA APURAÇÃO</div>
    <h1>{{ titulo }}</h1>
    <div class="meta">Emitido em {{ data }} · Sócios de fornecedores × benefício assistencial ·
    Casamento por nome + fragmento de CPF (QSA da Receita × arquivos de benefício) · Período: {{ periodo }}</div>
  </div>
  <div class="kpis">
    <div class="kpi"><div class="n">{{ total }}</div><div class="l">sócios de fornecedores com benefício (Rio)</div></div>
    <div class="kpi"><div class="n">{{ n_alta }}</div><div class="l">certeza ALTA (nome + CPF batem)</div></div>
    <div class="kpi"><div class="n">{{ n_ainda }}</div><div class="l">ainda recebendo em {{ ultima }}</div></div>
    <div class="kpi"><div class="n">{{ n_empresas }}</div><div class="l">empresas fornecedoras envolvidas</div></div>
  </div>

  <h2>1. Sócios de empresas fornecedoras recebendo benefício assistencial — por empresa</h2>
  <p class="nota">Certeza ALTA = o fragmento de CPF do sócio (QSA) coincide com o do beneficiário
  homônimo — praticamente a mesma pessoa. MÉDIA = há um único beneficiário com o nome, mas sem
  confirmar o CPF. Colunas de ano contam meses com benefício; "Programas" traz a trajetória.</p>
  {% for empresa, regs in grupos %}
  <h3>{{ empresa }} — {{ regs|length }} sócio(s)</h3>
  <table>
    <tr><th>Sócio</th><th>Certeza</th><th>CPF (frag.)</th><th>Qualificação</th><th>Programas (trajetória)</th>
        {% for a in anos %}<th>{{ a }}</th>{% endfor %}<th>Ainda?</th></tr>
    {% for r in regs %}
    <tr><td>{{ r.socio }}</td>
        <td><span class="tag {% if r.certeza=='ALTA' %}alta{% else %}media{% endif %}">{{ r.certeza }}</span></td>
        <td>…{{ r.cpf_frag }}…</td><td>{{ r.qualificacao }}</td>
        <td>{% for pr in r.programas %}{{ pr.ben }} ({{ pr.desde }}→{{ pr.ate }}, {{ pr.n }}m){% if not loop.last %}; {% endif %}{% endfor %}</td>
        {% for a in anos %}<td style="text-align:center">{{ r.por_ano[a] or '·' }}</td>{% endfor %}
        <td>{% if r.ainda_recebe %}<span class="tag alta">SIM</span>{% else %}não{% endif %}</td></tr>
    {% endfor %}
  </table>
  {% endfor %}

  <h2>2. Método e ressalvas</h2>
  <p>Sócios das empresas fornecedoras (quadro societário da Receita Federal) cruzados com os
  arquivos mensais oficiais dos programas assistenciais (BPC, Bolsa Família, Auxílio Brasil,
  Auxílio Emergencial, Gás do Povo), restritos ao estado do Rio. A identidade usa o fragmento
  público do CPF (6 dígitos do meio) presente nas duas bases: quando o fragmento do sócio bate com
  o do beneficiário de mesmo nome, a coincidência de nome + CPF torna a atribuição altamente
  provável — não é homônimo casual. Ainda assim, sem o CPF completo é <b>indício qualificado</b>
  para apuração, não acusação; a incompatibilidade de renda (ser sócio de empresa que fatura com o
  poder público e receber benefício de renda mínima) deve ser apurada pelos órgãos de controle e
  pelo Ministério Público, resguardada a presunção de legitimidade.</p>

  <footer>Peça de subsídio à apuração — indícios, não acusação. Fonte pública oficial (Receita
  Federal / Portal da Transparência). CPF de terceiros mascarado (LGPD).</footer>
</body></html>"""

_PROIBIDOS = ("jfn", "yoda", "hermes", "massare", "politimonitor", "gitnexus",
              "kroll", "deloitte", "mckinsey", "claude", "opus", "anthropic")


def _verificar_neutralidade() -> None:
    low = _TPL.lower()
    achados = [t for t in _PROIBIDOS if t in low]
    if achados:
        raise AssertionError(f"template contém termo(s) proibido(s): {achados}")


def render(dados: dict) -> str:
    from jinja2 import Template
    comps = dados["competencias"]
    periodo = f"{_comp_legivel(comps[0])} a {_comp_legivel(comps[-1])}" if comps else "—"
    return Template(_TPL).render(
        titulo="Perícia — Sócios de empresas fornecedoras do poder público recebendo benefício assistencial",
        data=datetime.now().strftime("%d/%m/%Y"), periodo=periodo,
        ultima=_comp_legivel(dados["ultima"]) if dados["ultima"] else "—",
        anos=dados["anos"], total=len(dados["registros"]),
        n_alta=dados["n_alta"], n_ainda=dados["n_ainda"], n_empresas=dados["n_empresas"],
        grupos=dados["grupos"],
    )


async def gerar_pdf() -> str:
    from compliance_agent.reporting.render_html import html_to_pdf
    _verificar_neutralidade()
    html = render(analisar())
    destino = str(_REPORTS / f"pericia_socios_fornecedores_beneficio_{datetime.now().date()}.pdf")
    await html_to_pdf(html, destino)
    return destino


if __name__ == "__main__":
    import asyncio
    import json
    d = analisar()
    print(json.dumps({k: v for k, v in d.items() if k not in ("registros", "grupos")},
                     ensure_ascii=False))
    print("registros:", len(d["registros"]), "| empresas:", d["n_empresas"])
    print(asyncio.run(gerar_pdf()))
