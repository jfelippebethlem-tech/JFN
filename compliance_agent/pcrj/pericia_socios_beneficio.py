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


def _moeda(v: float) -> str:
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


# ── CONTROLE NEGATIVO DA FAIXA MÉDIA (2026-08-12) ───────────────────────────────────────────────
# A faixa `MÉDIA` casa por NOME sem confirmar o fragmento de CPF, e a própria lista prova que ela é
# ruído: restringindo aos fornecedores com contrato da Prefeitura do Rio, dos 125 casamentos com
# Bolsa Família/Auxílio Brasil apenas **3 são ALTA** — e entre os 122 restantes aparecem INFRAERO,
# Banco Bradesco, Concremat, Elevadores Atlas Schindler e Microsens S.A. Diretor de banco e de
# estatal não recebe Bolsa Família.
#
# O relatório já dizia que MÉDIA é "CPF não confirmado". Faltava o NÚMERO: sem medir quanto da
# faixa é implausível, "não confirmado" é lido como "provavelmente sim".
#
# A régua é DELIBERADAMENTE conservadora — S.A., banco, estatal e multinacional listada. Não
# pretende achar todo falso positivo; pretende provar que existem tantos que a faixa não é fila de
# trabalho. E não pode engolir o sinal: MEI, EPP e entidade sem fins lucrativos ficam de fora do
# filtro, porque é exatamente ali que o achado real mora.
_IMPLAUSIVEL = re.compile(
    r"\bS[/.]?A\b|\bS\.A\.|SOCIEDADE AN[ÔO]NIMA|\bBANCO\b|BRADESCO|ITA[ÚU]|SANTANDER"
    r"|EMPRESA BRASILEIRA DE|PETROBRAS|INFRAERO|CORREIOS|CAIXA ECON"
    r"|SCHINDLER|JANSSEN|AGILENT|SIEMENS|PHILIPS|GE HEALTHCARE|JOHNSON|ROCHE|PFIZER"
    r"|MICROSOFT|ORACLE|IBM\b|SAP\b|CONCREMAT|MESSER|WHITE MARTINS|LINDE\b",
    re.IGNORECASE)


def empresa_implausivel(nome: str | None) -> bool:
    """A empresa é grande/estatal a ponto de tornar implausível um sócio em renda mínima?

    Serve para MEDIR o ruído da faixa MÉDIA, nunca para descartar achado: quem é ALTA (nome +
    fragmento de CPF) segue valendo qualquer que seja a empresa.
    """
    return bool(_IMPLAUSIVEL.search(str(nome or "")))


def classificar_casamento(frag_socio: str, frags_ben: set) -> tuple[str, str]:
    """(estado, fragmento) do casamento sócio × beneficiário homônimo.

    TRÊS ESTADOS, porque o antigo par ALTA/MÉDIA misturava coisas opostas — e o caro era o segundo:

    · **ALTA** — o fragmento do QSA está entre os do beneficiário: praticamente a mesma pessoa.
    · **DESCARTADO** — o fragmento EXISTE dos dois lados e DISCORDA. Isso é prova de que são
      pessoas diferentes, e mesmo assim saía como "MÉDIA" no relatório: 25 casos, todos em
      Associações de Apoio à Escola, apresentados como indício.
    · **SEM_FRAGMENTO** — não há o que comparar. Medido na base do Rio: **BPC, Auxílio Emergencial
      e Gás do Povo não trazem fragmento em NENHUMA linha** (0,0%), enquanto Bolsa Família traz em
      77,3% e Auxílio Brasil em 84,7%. Casamento nesses três é por NOME, e nome brasileiro comum
      casa com muita gente — era o que enchia a lista com diretores de Bradesco, INFRAERO e Atlas
      Schindler. Inverificável por construção NÃO é indício fraco: é ausência de verificação.
    """
    fb = set(frags_ben or ())
    if frag_socio and frag_socio in fb:
        return "ALTA", frag_socio
    reais = {f for f in fb if f and f != "?"}
    if not frag_socio or not reais:
        return "SEM_FRAGMENTO", (next(iter(fb)) if len(fb) == 1 else "?")
    return "DESCARTADO", ""


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

    # sócios de fornecedores (com CPF mascarado) + quanto cada empresa RECEBEU do Estado.
    # Pagamento = OB SIAFE 'Contabilizado' (regra da casa: só a Ordem Bancária é pago; Anulado/
    # Excluído fora) — dá a dimensão do sinal: sócio de empresa que fatura X com o poder público.
    cc = _db.sqlite3.connect(f"file:{COMPLIANCE_DB}?mode=ro", uri=True)
    cc.row_factory = _db.sqlite3.Row
    socios = cc.execute(
        "SELECT DISTINCT cnpj, razao, socio_nome, socio_nome_norm, socio_doc, qualificacao "
        "FROM socios_fornecedor WHERE socio_nome_norm<>''").fetchall()
    pagos = {}
    try:
        pagos = {r["credor"]: {"total": r["total"] or 0.0, "n": r["n"],
                               "ini": r["ini"], "fim": r["fim"]}
                 for r in cc.execute(
                     "SELECT credor, SUM(valor) AS total, COUNT(*) AS n, MIN(exercicio) AS ini, "
                     "MAX(exercicio) AS fim FROM ob_orcamentaria_siafe "
                     "WHERE status='Contabilizado' AND length(credor)=14 GROUP BY credor")}
    except Exception:  # noqa: BLE001 — banco parcial segue sem o contexto de pagamento
        pagos = {}
    cc.close()

    registros = []
    for s in socios:
        nn = s["socio_nome_norm"]
        if nn not in frags_por_nome:
            continue                       # o sócio não aparece em benefício (no Rio) — sem sinal
        frag_socio = _frag6(s["socio_doc"])
        frags_ben = frags_por_nome[nn]
        # casamento por fragmento: se o fragmento do sócio está entre os do beneficiário homônimo
        certeza, frag = classificar_casamento(frag_socio, frags_ben)
        if certeza == "DESCARTADO":
            continue                       # fragmentos discordam, ou vários homônimos e nenhum casa
        if (nn, frag) not in ben:
            continue                       # sem registro do beneficiário para esse fragmento
        e = ben[(nn, frag)]
        progs = []
        for prog, pr in sorted(e["prog"].items(), key=lambda kv: kv[1]["cmin"]):
            progs.append({"ben": prog, "desde": _comp_legivel(pr["cmin"]),
                          "ate": _comp_legivel(pr["cmax"]), "n": pr["n"]})
        registros.append({
            "socio": s["socio_nome"] or nn.title(),
            "empresa": s["razao"] or "", "cnpj": _fmt_cnpj(s["cnpj"]),
            "cnpj_raw": re.sub(r"\D", "", s["cnpj"] or ""),
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
    grupos = []
    for titulo, regs in sorted(por_emp.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        pg = pagos.get(regs[0]["cnpj_raw"])
        contexto = (f"recebeu do Estado R$ {_moeda(pg['total'])} em {pg['n']} OB(s) "
                    f"({pg['ini']}–{pg['fim']})" if pg else
                    "sem OB estadual na base (fornecedor municipal/federal ou fora da cobertura)")
        grupos.append({"titulo": titulo, "contexto": contexto, "regs": regs})

    _med = [x for x in unicos if x["certeza"] != "ALTA"]
    _fp = [x for x in _med if empresa_implausivel(x.get("empresa"))]
    return {
        "controle_negativo": {
            "n_media": len(_med), "n_implausivel": len(_fp),
            "pct": round(100.0 * len(_fp) / len(_med), 1) if _med else 0.0,
            "amostra": [f'{x["socio"]} — {x["empresa"]}' for x in _fp[:8]],
            "leitura": ("MÉDIA casa por NOME sem confirmar o fragmento de CPF. Estes são "
                        "casamentos em sociedade anônima, banco, estatal ou multinacional — "
                        "implausíveis por construção, e por isso servem de CONTROLE NEGATIVO da "
                        "faixa. A régua é conservadora: o número é PISO do ruído, não o total."),
        },
        "competencias": comps, "anos": anos, "ultima": ultima,
        "registros": unicos, "grupos": grupos,
        "n_alta": sum(1 for x in unicos if x["certeza"] == "ALTA"),
        "n_media": sum(1 for x in unicos if x["certeza"] == "SEM_FRAGMENTO"),
        "n_sem_fragmento": sum(1 for x in unicos if x["certeza"] == "SEM_FRAGMENTO"),
        "n_ainda": sum(1 for x in unicos if x["ainda_recebe"]),
        "n_empresas": len(grupos),
    }


_TPL = """<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><style>
  @page { size: A4 landscape; margin: 12mm 10mm; }
  body { font-family:Georgia,'Times New Roman',serif; color:#1a1a1a; font-size:9.5px; line-height:1.5; }
  .capa { border-bottom:3px double #1f4e5a; padding-bottom:10px; margin-bottom:12px; }
  .classif { color:#1f4e5a; font-weight:700; letter-spacing:2px; font-size:9px; font-family:'Helvetica Neue',Arial,sans-serif; }
  h1 { font-size:20px; color:#0b2228; margin:5px 0 3px; letter-spacing:.2px; }
  .meta { color:#555; font-size:9px; }
  h2 { font-size:13.5px; color:#1f4e5a; border-bottom:1px solid #d3e0e0; padding-bottom:3px; margin-top:17px; }
  h3 { font-size:10.5px; color:#10303a; margin:12px 0 2px; background:#eaf2f3; padding:4px 8px; border-left:3px solid #1f4e5a; }
  h3 .ctx { font-weight:400; color:#456; font-size:9px; }
  .kpis { display:flex; gap:8px; margin:11px 0; flex-wrap:wrap; }
  .kpi { border:1px solid #d5e2e2; border-radius:7px; padding:8px 12px; background:#f7fbfb; min-width:112px; }
  .kpi .n { font-size:21px; font-weight:700; color:#1f4e5a; line-height:1; font-family:'Helvetica Neue',Arial,sans-serif; }
  .kpi .l { font-size:8px; color:#666; margin-top:3px; font-family:'Helvetica Neue',Arial,sans-serif; }
  table { width:100%; border-collapse:collapse; font-size:8.4px; margin:4px 0 10px; font-family:'Helvetica Neue',Arial,sans-serif; }
  th,td { text-align:left; padding:3px 5px; border-bottom:1px solid #eee; vertical-align:top; }
  th { background:#1f4e5a; color:#fff; font-weight:600; }
  table tr:nth-child(even) td { background:#f2f7f7; }
  .tag { padding:1px 5px; border-radius:3px; font-size:8px; font-weight:700; font-family:'Helvetica Neue',Arial,sans-serif; }
  .alta { background:#fdecea; color:#c62828; } .media { background:#fff3e0; color:#e65100; }
  .nota { font-size:8.6px; color:#555; font-style:italic; }
  footer { margin-top:18px; border-top:1px solid #ddd; padding-top:6px; font-size:8px; color:#888; }
</style></head><body>
  <div class="capa">
    <div class="classif">CONFIDENCIAL — SUBSÍDIO PARA APURAÇÃO</div>
    <h1>{{ titulo }}</h1>
    <div class="meta">Emitido em {{ data }} · Sócios de fornecedores × benefício assistencial ·
    Casamento por nome + fragmento de CPF (QSA da Receita × arquivos de benefício) · Período: {{ periodo }} ·
    Pagamentos ao fornecedor: OB SIAFE contabilizada (só Ordem Bancária é pagamento; empenho não)</div>
  </div>
  <div class="kpis">
    <div class="kpi"><div class="n">{{ total }}</div><div class="l">sócios de fornecedores com benefício (Rio)</div></div>
    <div class="kpi"><div class="n">{{ n_alta }}</div><div class="l">certeza ALTA (nome + CPF batem)</div></div>
    <div class="kpi"><div class="n">{{ n_media }}</div><div class="l">SEM FRAGMENTO — casamento só por nome, inverificável</div></div>
    <div class="kpi"><div class="n">{{ cn.pct }}%</div><div class="l">dos sem-fragmento é implausível (controle negativo)</div></div>
    <div class="kpi"><div class="n">{{ n_ainda }}</div><div class="l">ainda recebendo em {{ ultima }}</div></div>
    <div class="kpi"><div class="n">{{ n_empresas }}</div><div class="l">empresas fornecedoras envolvidas</div></div>
  </div>

  <h2>1. Sócios de empresas fornecedoras recebendo benefício assistencial — por empresa</h2>
  <p class="nota">Certeza ALTA = o fragmento de CPF do sócio (QSA) coincide com o do beneficiário
  homônimo — praticamente a mesma pessoa. SEM FRAGMENTO = a fonte não expõe o fragmento nesse
  registro (BPC, Auxílio Emergencial e Gás do Povo não o expõem em NENHUMA linha; Bolsa Família o
  traz em 77,3% e Auxílio Brasil em 84,7%), então o casamento é só por nome — inverificável por
  construção, e NÃO é indício fraco: é ausência de verificação. Fragmento que DISCORDA sai da
  lista, porque prova pessoa diferente. Antes
  confirmar o CPF. Colunas de ano contam meses com benefício; "Programas" traz a trajetória. O
  subtítulo de cada empresa traz quanto ela <b>recebeu do Estado</b> (soma das OBs contabilizadas
  do SIAFE) — a dimensão do sinal: quanto maior o faturamento público, mais incompatível o
  benefício de renda mínima do sócio.</p>
  {% for g in grupos %}
  <h3>{{ g.titulo }} — {{ g.regs|length }} sócio(s) · <span class="ctx">{{ g.contexto }}</span></h3>
  <table>
    <tr><th>Sócio</th><th>Certeza</th><th>CPF (frag.)</th><th>Qualificação</th><th>Programas (trajetória)</th>
        {% for a in anos %}<th>{{ a }}</th>{% endfor %}<th>Ainda?</th></tr>
    {% for r in g.regs %}
    <tr><td><b>{{ r.socio }}</b></td>
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
  <p><b>Pagamentos ao fornecedor.</b> O valor "recebeu do Estado" de cada empresa é a soma das
  Ordens Bancárias <b>contabilizadas</b> do SIAFE estadual (OBs anuladas/excluídas fora) — pela
  regra de ouro orçamentária, só a OB é pagamento; empenho e liquidação não entram. Empresa "sem OB
  estadual na base" pode ser fornecedora municipal/federal ou estar fora da janela de cobertura da
  coleta — ausência declarada, não zero.</p>

  <footer>Peça de subsídio à apuração — indícios, não acusação. Fonte pública oficial (Receita
  Federal / Portal da Transparência / SIAFE-RJ). CPF de terceiros mascarado (LGPD).</footer>
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
        cn=dados.get("controle_negativo", {"pct": 0, "n_implausivel": 0, "leitura": ""}),
        n_alta=dados["n_alta"], n_media=dados["n_media"], n_ainda=dados["n_ainda"],
        n_empresas=dados["n_empresas"], grupos=dados["grupos"],
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
