# -*- coding: utf-8 -*-
"""Orquestra os documentos SEPARADOS da perícia PCRJ (ordem do dono):

  • DOCUMENTO DA CÂMARA — servidores/nomeados da Câmara recebendo benefício, POR ÓRGÃO, com datas de
    nomeação/exoneração; inclui a CONVERGÊNCIA com a Prefeitura (quem é dos dois — o que interessa é
    o legislativo se ligando ao executivo), os gabinetes sob suplência e quem recebe benefício fora
    do município do Rio (mora em outra cidade).
  • DOCUMENTO DA PREFEITURA — servidores da Prefeitura recebendo benefício, por órgão, com nomeação/
    exoneração e quem mora fora do Rio.

Reusa a análise deduplicada de `pericia_beneficios` (identidade por nome+fragmento de CPF, município
do Rio, níveis de certeza) e apenas recorta por poder + monta as seções. Relatórios NEUTROS (sem
marca institucional; trava `_verificar`). Indício, nunca acusação; datas p/ não cometer injustiça.
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

from compliance_agent.pcrj import db as _db
from compliance_agent.pcrj import pericia_beneficios as _pb

_REPORTS = Path(__file__).resolve().parents[2] / "reports"
BENEF_DB = _db.DB_PATH.parent / "pcrj_benef.db"
_PROIBIDOS = ("jfn", "yoda", "hermes", "massare", "politimonitor", "gitnexus",
              "kroll", "deloitte", "mckinsey", "claude", "opus", "anthropic")


def _fora_do_rio(nome_norms: set[str]) -> dict[str, dict]:
    """Para os nomes dados, benefício pago FORA do município do Rio (mora em outra cidade). Agrega
    o município mais frequente + programas. Uma varredura no banco de benefícios."""
    b = _db.sqlite3.connect(f"file:{BENEF_DB}?mode=ro", uri=True)
    out: dict[str, dict] = {}
    for nn, mun, ben, cmin, cmax, n in b.execute(
            "SELECT nome_norm, municipio, beneficio, MIN(competencia), MAX(competencia), "
            "COUNT(DISTINCT competencia) FROM pcrj_beneficio "
            "WHERE municipio<>'RIO DE JANEIRO' AND municipio<>'' "
            "GROUP BY nome_norm, municipio, beneficio"):
        if nn not in nome_norms:
            continue
        e = out.setdefault(nn, {"municipios": {}, "programas": {}})
        e["municipios"][mun] = e["municipios"].get(mun, 0) + n
        e["programas"][ben] = (_pb._comp_legivel(cmin), _pb._comp_legivel(cmax))
    b.close()
    return out


def _dados_camara_prefeitura():
    d = _pb.analisar()
    regs = d["registros"]
    camara = [r for r in regs if r["poder"].startswith("Câmara")]           # inclui 'Câmara + Prefeitura'
    convergencia = [r for r in regs if r["poder"] == "Câmara + Prefeitura"]  # nos DOIS poderes
    prefeitura = [r for r in regs if r["poder"] == "Prefeitura"]             # só Prefeitura
    # "mora em outra cidade": benefício fora do Rio, por poder (nomes do quadro de cada poder)
    nn_cam = {r["nome_norm"] for r in camara}
    nn_pref = {r["nome_norm"] for r in prefeitura}
    return d, camara, convergencia, prefeitura, _fora_do_rio(nn_cam | nn_pref)


def _agrupar(regs, so_alta=True):
    por: dict[str, list] = {}
    for r in regs:
        if so_alta and r["certeza"] != "ALTA":
            continue
        por.setdefault(r["_orgao_topo"], []).append(r)
    return sorted(por.items(), key=lambda kv: (-len(kv[1]), kv[0]))


def _secao_media(regs, anos, papel: str) -> str:
    """Certeza MÉDIA em seção própria (indício mais fraco — não some, mas não se mistura com a ALTA).
    Diretriz 2026-07-11: o relatório carrega TODAS as informações; a força de cada indício fica explícita."""
    media = [r for r in regs if r["certeza"] == "MÉDIA"]
    if not media:
        return "<p class='nota'>Sem casos de certeza MÉDIA no recorte.</p>"
    partes = ["<p class='nota'>⚠️ <b>Certeza MÉDIA</b> — indício mais fraco que a seção principal: pode haver "
              "homônimo, CPF parcial ou janela de vínculo imprecisa. Requer conferência antes de qualquer juízo. "
              f"São {len(media)} {papel}(s).</p>"]
    for org, grp in _agrupar(media, so_alta=False):
        partes.append(f"<h3>{org} — {len(grp)} {papel}(s) [MÉDIA]</h3>{_tabela_regs(grp, anos)}")
    return "".join(partes)


# ── template comum (neutro) ───────────────────────────────────────────────────────────
_CSS = """
  @page { size: A4 landscape; margin: 12mm 10mm; }
  body { font-family:Georgia,'Times New Roman',serif; color:#1a1a1a; font-size:9px; line-height:1.5; }
  .capa { border-bottom:3px double #7a1f1f; padding-bottom:10px; margin-bottom:12px; }
  .classif { color:#7a1f1f; font-weight:700; letter-spacing:2px; font-size:8.5px; font-family:'Helvetica Neue',Arial,sans-serif; }
  h1 { font-size:19px; color:#2b0d0d; margin:5px 0 3px; letter-spacing:.2px; } .meta { color:#555; font-size:9px; }
  h2 { font-size:13px; color:#7a1f1f; border-bottom:1px solid #e0d3d3; padding-bottom:3px; margin-top:17px; }
  h3 { font-size:10.5px; color:#3a1010; margin:11px 0 2px; background:#f5eded; padding:4px 8px; border-left:3px solid #7a1f1f; }
  .kpis { display:flex; gap:8px; margin:10px 0; flex-wrap:wrap; }
  .kpi { border:1px solid #e2d5d5; border-radius:7px; padding:8px 12px; background:#fbf7f7; min-width:104px; }
  .kpi .n { font-size:20px; font-weight:700; color:#7a1f1f; line-height:1; font-family:'Helvetica Neue',Arial,sans-serif; }
  .kpi .l { font-size:8px; color:#666; margin-top:3px; font-family:'Helvetica Neue',Arial,sans-serif; }
  table { width:100%; border-collapse:collapse; font-size:8px; margin:4px 0 10px; font-family:'Helvetica Neue',Arial,sans-serif; }
  th,td { text-align:left; padding:3px 5px; border-bottom:1px solid #eee; vertical-align:top; }
  th { background:#7a1f1f; color:#fff; font-weight:600; } table tr:nth-child(even) td { background:#f9f4f4; }
  .tag { padding:1px 5px; border-radius:3px; font-size:7.5px; font-weight:700; white-space:nowrap;
         font-family:'Helvetica Neue',Arial,sans-serif; }
  .alta { background:#fdecea; color:#c62828; } .conv { background:#ede7f6; color:#4527a0; } .rio { background:#fff3e0; color:#e65100; }
  .nomeado { background:#7a1f1f; color:#fff; } .efetivo { background:#e3ecf7; color:#1f4e79; }
  .requisitado { background:#ede7f6; color:#4527a0; } .inativo { background:#eceff1; color:#455a64; }
  .estagio { background:#e0f2f1; color:#00695c; } .indet { background:#fff8e1; color:#a06a00; border:1px dashed #d3a94a; }
  .det { color:#777; font-size:7.4px; font-weight:400; white-space:normal; margin-top:1px; font-family:'Helvetica Neue',Arial,sans-serif; }
  .part { background:#e8eef7; color:#1f4e79; padding:1px 4px; border-radius:3px; font-size:7.5px; }
  .nota { font-size:8.2px; color:#555; font-style:italic; }
  .legenda { font-size:8.2px; color:#444; margin:7px 0 0; font-family:'Helvetica Neue',Arial,sans-serif; }
  .legenda .tag { margin-right:3px; }
  .ficha { border:1px solid #e0d3d3; border-left:4px solid #7a1f1f; border-radius:6px; background:#fdfbfb;
           padding:8px 11px; margin:7px 0; page-break-inside:avoid; }
  .ficha .ft { font-size:11px; font-weight:700; color:#2b0d0d; margin-bottom:4px; }
  .ficha .grade { display:flex; flex-wrap:wrap; gap:4px 18px; font-size:8.3px; font-family:'Helvetica Neue',Arial,sans-serif; }
  .ficha .grade b { color:#7a1f1f; }
  .ficha .leitura { font-size:8.3px; color:#333; margin-top:5px; border-top:1px dotted #d8c8c8; padding-top:4px; }
  footer { margin-top:16px; border-top:1px solid #ddd; padding-top:6px; font-size:7.5px; color:#888; }
"""

# Legenda fixa da natureza do vínculo (a clareza pedida pelo dono 2026-07-11: o relatório diz,
# pessoa a pessoa, quem é NOMEADO — e declara quando a fonte não informa).
_LEGENDA_NATUREZA = (
    "<div class='legenda'><b>Natureza do vínculo</b> (classificada pessoa a pessoa, pela fonte): "
    "<span class='tag nomeado'>NOMEADO</span>cargo em comissão (livre nomeação) — confirmado · "
    "<span class='tag efetivo'>EFETIVO</span>carreira/concurso · "
    "<span class='tag requisitado'>REQUISITADO</span>cedido de outro órgão · "
    "<span class='tag inativo'>APOSENT./PENSÃO</span>folha previdenciária · "
    "<span class='tag estagio'>ESTÁGIO/BOLSA</span>sem vínculo efetivo · "
    "<span class='tag indet'>NÃO INFORMADO</span>a fonte não publica a forma de provimento — não se presume.</div>")

_NOTA_NATUREZA = (
    "<p class='nota'><b>Como se classificou a natureza do vínculo:</b> Câmara — o campo \"vínculo\" da "
    "relação oficial decide sozinho (Livre Nomeação e Exoneração = nomeado; Requisitados = cedido; demais "
    "= carreiras efetivas). Prefeitura — a folha em bloco não publica cargo/forma de provimento; o tipo de "
    "folha separa previdência (PREV*/APA) e estágio/bolsa (TSVE), e o cargo, quando alguma consulta nominal "
    "ao portal de remuneração já o trouxe, distingue comissão (ESPECIAL/DAS/DAI/assessoria) de carreira. "
    "Sem cargo conhecido, o rótulo é <b>NÃO INFORMADO</b> — ausência de informação declarada, nunca "
    "convertida em suspeita ou absolvição.</p>")

_NAT_CLASSE = (("APOSENT", "inativo"), ("REQUISITADO", "requisitado"), ("ESTÁGIO", "estagio"))


def _nat_html(r) -> str:
    """Tag + detalhe da natureza do vínculo (campos gerados em pericia_beneficios._classificar_vinculo)."""
    if r.get("eh_nomeado") is True:
        cls = "nomeado"
    elif r.get("eh_nomeado") is None:
        cls = "indet"
    else:
        cls = next((c for k, c in _NAT_CLASSE if k in (r.get("natureza") or "")), "efetivo")
    return (f"<span class='tag {cls}'>{r.get('natureza') or '—'}</span>"
            f"<div class='det'>{r.get('natureza_detalhe', '')}</div>")


def _tabela_regs(regs, anos, convergencia_flag=False):
    linhas = []
    for r in regs:
        prog = "; ".join(f"{p['ben']} ({p['desde']}→{p['ate']})" for p in r["programas"])
        anosc = "".join(f"<td style='text-align:center'>{r['por_ano'].get(a, 0) or '·'}</td>" for a in anos)
        conv = "<span class='tag conv'>Câmara+Pref.</span>" if (convergencia_flag and r["poder"] == "Câmara + Prefeitura") else ""
        certeza_cls = "alta" if r["certeza"] == "ALTA" else "rio"
        linhas.append(
            f"<tr><td><b>{r['nome']}</b></td><td><span class='tag {certeza_cls}'>{r['certeza']}</span> {conv}</td>"
            f"<td>…{r['cpf_frag']}…</td><td>{_nat_html(r)}</td><td>{r.get('cargo', '')}</td>"
            f"<td>{r.get('vinculos', '')}</td>"
            f"<td><span class='part'>{r['partido']}</span></td><td>{prog}</td>{anosc}"
            f"<td>{'<span class=\"tag alta\">SIM</span>' if r['ainda_recebe'] else 'não'}</td></tr>")
    cab = ("<tr><th>Nome</th><th>Certeza</th><th>CPF</th><th>Natureza do vínculo</th><th>Cargo/função</th>"
           "<th>Vínculo(s) público(s) — nomeação→saída</th>"
           "<th>Partido</th><th>Benefício DURANTE o vínculo (trajetória)</th>" +
           "".join(f"<th>{a}</th>" for a in anos) + "<th>Ainda?</th></tr>")
    return f"<table>{cab}{''.join(linhas)}</table>"


def _ficha(r, anos) -> str:
    """Ficha individual (detalhamento sem limite de páginas — diretriz 2026-07-11) para os casos
    mais graves: NOMEADO confirmado, certeza ALTA. Tudo que a base sabe da pessoa, num bloco só."""
    progs = "".join(
        f"<tr><td>{p['ben']}</td><td>{p['desde']}</td><td>{p['ate']}</td>"
        f"<td style='text-align:center'>{p['n']}</td></tr>" for p in r["programas"])
    por_ano = " · ".join(f"{a}: <b>{r['por_ano'].get(a, 0) or 0}</b>m" for a in anos
                         if r["por_ano"].get(a))
    gab = f" · <b>Gabinete/titular:</b> {r['gab_titular']}" if r.get("gab_titular") else ""
    ainda = ("<span class='tag alta'>AINDA RECEBE</span>" if r["ainda_recebe"]
             else "não recebe na última competência da base")
    return (
        "<div class='ficha'>"
        f"<div class='ft'>{r['nome']} &nbsp;{_nat_html(r)}</div>"
        "<div class='grade'>"
        f"<span><b>CPF (frag.):</b> …{r['cpf_frag']}…</span>"
        f"<span><b>Certeza da identidade:</b> {r['certeza']}</span>"
        f"<span><b>Poder:</b> {r['poder']}</span>"
        f"<span><b>Órgão(s):</b> {r['orgao']}</span>"
        f"<span><b>Cargo/função:</b> {r.get('cargo') or 'n/d'}</span>"
        f"<span><b>Partido (TSE 2018):</b> {r['partido']}</span>"
        f"<span><b>Vínculo(s) — janela:</b> {r.get('vinculos', '')}{gab}</span>"
        f"<span><b>Situação:</b> {r['situacao']} · {ainda}</span>"
        "</div>"
        "<table style='margin-top:5px'><tr><th>Programa</th><th>Primeiro mês</th><th>Último mês</th>"
        f"<th>Meses</th></tr>{progs}</table>"
        f"<div class='grade'><span><b>Meses com benefício por ano:</b> {por_ano or '—'}</span></div>"
        "<div class='leitura'><b>Leitura:</b> benefício assistencial pressupõe renda baixa (BPC: renda "
        "per capita &lt; ¼ do salário mínimo; Bolsa Família/Auxílio Brasil: linha de pobreza) — em tensão "
        "direta com a remuneração de cargo em comissão recebida no mesmo período. <b>Verificação "
        "sugerida:</b> requisição formal do CPF completo (órgão de controle) e confronto com o CadÚnico/"
        "folha do programa; só isso fecha a identidade com prova. Indício qualificado, não acusação.</div>"
        "</div>")


def _render(titulo, subtitulo, kpis, corpo_html) -> str:
    kpi_html = "".join(f"<div class='kpi'><div class='n'>{v}</div><div class='l'>{l}</div></div>" for v, l in kpis)
    return (f"<!doctype html><html lang='pt-BR'><head><meta charset='utf-8'><style>{_CSS}</style></head><body>"
            f"<div class='capa'><div class='classif'>CONFIDENCIAL — SUBSÍDIO PARA APURAÇÃO</div>"
            f"<h1>{titulo}</h1><div class='meta'>{subtitulo}</div>{_LEGENDA_NATUREZA}</div>"
            f"<div class='kpis'>{kpi_html}</div>{corpo_html}"
            f"<footer>Peça de subsídio à apuração — indícios, não acusação; presunção de legitimidade "
            f"preservada. Identidade por nome + fragmento de CPF, benefício no município do Rio. Datas "
            f"de nomeação/exoneração para verificação (evitar injustiça). Fonte pública oficial. "
            f"CPF de terceiros mascarado (LGPD).</footer></body></html>")


def _secao_fora_rio(regs, fora):
    linhas = []
    for r in regs:
        f = fora.get(r["nome_norm"])
        if not f:
            continue
        mun = max(f["municipios"], key=f["municipios"].get)
        prog = "; ".join(f"{b} ({d[0]}→{d[1]})" for b, d in f["programas"].items())
        linhas.append(f"<tr><td>{r['nome']}</td><td>{r.get('cargo', '')}</td><td>{mun.title()}</td><td>{prog}</td></tr>")
    if not linhas:
        return "<p class='nota'>Nenhum servidor deste poder com benefício pago fora do município do Rio na base atual.</p>"
    return ("<table><tr><th>Nome</th><th>Cargo</th><th>Recebe benefício em (outra cidade)</th>"
            f"<th>Programas</th></tr>{''.join(linhas)}</table>")


def _verificar(html, origem=""):
    low = html.lower()
    bad = [t for t in _PROIBIDOS if t in low]
    # nomes de cidadãos podem conter os termos; checa só fora de conteúdo de dados não é trivial —
    # o template é construído aqui sem marca, então um hit costuma ser DADO (nome/município) — avisa
    # p/ revisão humana em vez de bloquear a emissão.
    if bad:
        print(f"⚠️ trava de marca ({origem}): termos proibidos no HTML: {bad} — revisar antes de entregar",
              file=sys.stderr)
    return bad


def gerar_camara(dados=None) -> str:
    d, camara, convergencia, prefeitura, fora = dados or _dados_camara_prefeitura()
    anos = d["anos"]
    alta = [r for r in camara if r["certeza"] == "ALTA"]
    nomeados = [r for r in alta if r["eh_nomeado"] is True]
    demais = [r for r in alta if r["eh_nomeado"] is not True]

    corpo = ["<h2>1. NOMEADOS em cargo em comissão (livre nomeação) × benefício assistencial — fichas individuais</h2>",
             "<p class='nota'>⚖️ <b>Justiça:</b> só entram benefícios recebidos <b>DURANTE</b> um vínculo público "
             "(cruzamento benefício×janela de nomeação). Quem recebeu entre empregos foi excluído — não é "
             "irregularidade. Só casos de certeza ALTA (um beneficiário, um servidor, CPF legível). "
             "Auxílio Emergencial (2020–21) teve elegibilidade ampla (sinal mais fraco).</p>",
             _NOTA_NATUREZA]
    if nomeados:
        corpo.extend(_ficha(r, anos) for r in nomeados)
        corpo.append("<h3>Consolidado dos nomeados — por órgão</h3>")
        for org, regs in _agrupar(nomeados):
            corpo.append(f"<h3>{org} — {len(regs)} nomeado(s) confirmado(s)</h3>{_tabela_regs(regs, anos)}")
    else:
        corpo.append("<p class='nota'>Nenhum nomeado (comissionado confirmado) com benefício e certeza ALTA no recorte atual.</p>")

    corpo.append("<h2>2. Demais vínculos da Câmara (efetivos, requisitados) × benefício — por órgão</h2>")
    corpo.append("<p class='nota'>Servidores que NÃO são nomeados em comissão — efetivos de carreira e "
                 "requisitados/cedidos. Constam para o quadro ficar completo, mas a leitura é distinta: "
                 "efetivo com benefício é incompatibilidade de renda, não apadrinhamento político.</p>")
    if demais:
        for org, regs in _agrupar(demais):
            corpo.append(f"<h3>{org} — {len(regs)} servidor(es)</h3>{_tabela_regs(regs, anos)}")
    else:
        corpo.append("<p class='nota'>Nenhum caso.</p>")

    corpo.append("<h2>3. Convergência Câmara ↔ Prefeitura (o legislativo ligado ao executivo)</h2>")
    corpo.append("<p class='nota'>Pessoas do quadro da Câmara que TAMBÉM constam na folha da Prefeitura (acúmulo "
                 "de vínculo). É o cruzamento que interessa: quem transita entre os dois poderes. A coluna "
                 "de natureza mostra a condição em CADA poder.</p>")
    corpo.append(_tabela_regs(convergencia, anos, convergencia_flag=True) if convergencia
                 else "<p class='nota'>Nenhum caso de convergência com certeza no recorte atual.</p>")

    corpo.append("<h2>4. Gabinetes sob suplência — equipe do titular sobrevivente</h2>")
    for g in d["gabs_suplencia"]:
        sob = g["sobreviventes"]
        det = ("".join(f"<tr><td>{s['nome']}</td><td>{'<span class=\"tag nomeado\">livre nomeação</span>' if s.get('eh_livre') else s.get('vinculo', '')}</td>"
                       f"<td>{s['cargo']}</td><td>{s['ingresso']}</td></tr>" for s in sob))
        corpo.append(f"<h3>Gabinete Nº {g['gabinete']} — titular {g['titular']} · suplente {g['suplente']} (posse {g['posse']})</h3>")
        corpo.append(f"<table><tr><th>Sobrevivente</th><th>Vínculo</th><th>Cargo</th><th>Ingresso</th></tr>{det}</table>"
                     if sob else "<p class='nota'>Sem sobrevivente (suplente montou a própria equipe).</p>")

    corpo.append("<h2>5. Servidores da Câmara que recebem benefício em OUTRA cidade (moram fora do Rio)</h2>")
    corpo.append(_secao_fora_rio(camara, fora))

    corpo.append("<h2>6. Anexo — casos de certeza MÉDIA (indício mais fraco, a conferir)</h2>")
    corpo.append(_secao_media(camara, anos, "servidor"))

    kpis = [(len(nomeados), "NOMEADOS confirmados (comissão) × benefício"),
            (len(demais), "efetivos/requisitados × benefício (ALTA)"),
            (len(convergencia), "convergência com a Prefeitura"),
            (len(d["gabs_suplencia"]), "gabinetes sob suplência"),
            (sum(1 for r in camara if r["nome_norm"] in fora), "recebem fora do Rio"),
            (sum(1 for r in camara if r["certeza"] == "MÉDIA"), "certeza MÉDIA (anexo)")]
    html = _render("Perícia — Câmara Municipal do Rio: nomeados e servidores × benefício assistencial",
                   f"Emitido em {datetime.now():%d/%m/%Y} · Período {_pb._comp_legivel(d['competencias'][0])}–{_pb._comp_legivel(d['ultima'])} · "
                   "Câmara + convergência com a Prefeitura", kpis, "".join(corpo))
    _verificar(html, "camara")
    dest = str(_REPORTS / f"pericia_camara_{datetime.now().date()}.html")
    Path(dest).write_text(html, encoding="utf-8")
    return dest


def gerar_prefeitura(dados=None) -> str:
    d, camara, convergencia, prefeitura, fora = dados or _dados_camara_prefeitura()
    anos = d["anos"]
    alta = [r for r in prefeitura if r["certeza"] == "ALTA"]
    nomeados = [r for r in alta if r["eh_nomeado"] is True]
    inativos = [r for r in alta if r["eh_nomeado"] is not True and "APOSENT" in (r["natureza"] or "")]
    demais = [r for r in alta if r not in nomeados and r not in inativos]
    indet = [r for r in demais if r["eh_nomeado"] is None]

    corpo = ["<h2>1. NOMEADOS confirmados (cargo em comissão) × benefício assistencial — fichas individuais</h2>",
             "<p class='nota'>⚖️ <b>Justiça:</b> só entram benefícios recebidos <b>DURANTE</b> um vínculo "
             "público (cruzamento benefício×janela, mês a mês, contra a faixa de presença na folha). Quem "
             "recebeu entre empregos foi excluído — não é irregularidade. Só certeza ALTA (um beneficiário, "
             "um servidor, CPF legível).</p>",
             _NOTA_NATUREZA]
    if nomeados:
        corpo.extend(_ficha(r, anos) for r in nomeados)
        corpo.append("<h3>Consolidado dos nomeados — por órgão</h3>")
        for org, regs in _agrupar(nomeados):
            corpo.append(f"<h3>{org} — {len(regs)} nomeado(s) confirmado(s)</h3>{_tabela_regs(regs, anos)}")
    else:
        corpo.append("<p class='nota'>Nenhum nomeado (comissionado confirmado pelo cargo) com benefício e "
                     "certeza ALTA no recorte atual. Atenção: a folha em bloco não publica o cargo — casos "
                     "de natureza NÃO INFORMADA (seção 3) podem conter comissionados ainda não confirmados "
                     "pela consulta nominal ao portal de remuneração.</p>")

    corpo.append("<h2>2. Aposentados e pensionistas × benefício — por órgão</h2>")
    corpo.append("<p class='nota'>Folha previdenciária (PREV*/APA). A leitura é de renda: proventos + "
                 "benefício assistencial de renda mínima no mesmo período. BPC, em particular, é "
                 "inacumulável com provento acima do teto de renda per capita.</p>")
    if inativos:
        for org, regs in _agrupar(inativos):
            corpo.append(f"<h3>{org} — {len(regs)} inativo(s)</h3>{_tabela_regs(regs, anos)}")
    else:
        corpo.append("<p class='nota'>Nenhum caso.</p>")

    corpo.append("<h2>3. Demais servidores da folha (efetivos, estágio/bolsa e natureza não informada) — por órgão</h2>")
    corpo.append(f"<p class='nota'>Inclui os <b>{len(indet)}</b> casos de natureza <b>NÃO INFORMADA</b>: a "
                 "folha em bloco da Prefeitura não publica cargo/forma de provimento, e nenhuma consulta "
                 "nominal ao portal de remuneração trouxe o cargo dessas pessoas ainda. Não se presume "
                 "comissionamento — a confirmação individual (consulta nominal ao contracheque) é a "
                 "providência sugerida para os casos relevantes.</p>")
    if demais:
        for org, regs in _agrupar(demais):
            corpo.append(f"<h3>{org} — {len(regs)} servidor(es)</h3>{_tabela_regs(regs, anos)}")
    else:
        corpo.append("<p class='nota'>Nenhum caso.</p>")

    corpo.append("<h2>4. Servidores da Prefeitura que recebem benefício em OUTRA cidade (moram fora do Rio)</h2>")
    corpo.append(_secao_fora_rio(prefeitura, fora))
    corpo.append("<h2>5. Anexo — casos de certeza MÉDIA (indício mais fraco, a conferir)</h2>")
    corpo.append(_secao_media(prefeitura, anos, "servidor"))

    kpis = [(len(nomeados), "NOMEADOS confirmados (comissão) × benefício"),
            (len(inativos), "aposentados/pensionistas × benefício"),
            (len(demais) - len(indet), "efetivos/estágio × benefício (ALTA)"),
            (len(indet), "natureza não informada pela fonte (ALTA)"),
            (len(prefeitura), "total no Rio (ALTA+MÉDIA)"),
            (sum(1 for r in prefeitura if r["nome_norm"] in fora), "recebem fora do Rio")]
    html = _render("Perícia — Prefeitura do Rio: nomeados, servidores e pensionistas × benefício assistencial",
                   f"Emitido em {datetime.now():%d/%m/%Y} · Período {_pb._comp_legivel(d['competencias'][0])}–{_pb._comp_legivel(d['ultima'])} · "
                   "folha completa por órgão", kpis, "".join(corpo))
    _verificar(html, "prefeitura")
    dest = str(_REPORTS / f"pericia_prefeitura_{datetime.now().date()}.html")
    Path(dest).write_text(html, encoding="utf-8")
    return dest


async def gerar_pdfs() -> dict:
    """Gera os dois PDFs (Câmara e Prefeitura) a partir de UMA análise."""
    from compliance_agent.reporting.render_html import html_to_pdf
    dados = _dados_camara_prefeitura()
    out = {}
    for nome, fn in (("camara", gerar_camara), ("prefeitura", gerar_prefeitura)):
        html_path = fn(dados)
        html = Path(html_path).read_text(encoding="utf-8")
        pdf = str(_REPORTS / f"pericia_{nome}_{datetime.now().date()}.pdf")
        await html_to_pdf(html, pdf)
        out[nome] = pdf
    return out


if __name__ == "__main__":
    import asyncio
    import json
    print(json.dumps(asyncio.run(gerar_pdfs()), ensure_ascii=False))
