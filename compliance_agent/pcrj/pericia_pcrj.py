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


# ── template comum (neutro) ───────────────────────────────────────────────────────────
_CSS = """
  @page { size: A4 landscape; margin: 12mm 10mm; }
  body { font-family:'Helvetica Neue',Arial,sans-serif; color:#1a1a1a; font-size:9px; line-height:1.4; }
  .capa { border-bottom:3px solid #7a1f1f; padding-bottom:9px; margin-bottom:12px; }
  .classif { color:#7a1f1f; font-weight:700; letter-spacing:1px; font-size:9px; }
  h1 { font-size:19px; color:#3a1010; margin:4px 0; } .meta { color:#555; font-size:9px; }
  h2 { font-size:13px; color:#7a1f1f; border-bottom:1px solid #e0d3d3; padding-bottom:3px; margin-top:16px; }
  h3 { font-size:10.5px; color:#3a1010; margin:11px 0 2px; background:#f2e9e9; padding:3px 7px; border-radius:4px; }
  .kpis { display:flex; gap:9px; margin:10px 0; flex-wrap:wrap; }
  .kpi { border:1px solid #e2d5d5; border-radius:8px; padding:8px 12px; background:#fbf7f7; min-width:110px; }
  .kpi .n { font-size:20px; font-weight:700; color:#7a1f1f; line-height:1; } .kpi .l { font-size:8px; color:#666; margin-top:3px; }
  table { width:100%; border-collapse:collapse; font-size:8px; margin:4px 0 10px; }
  th,td { text-align:left; padding:3px 5px; border-bottom:1px solid #eee; vertical-align:top; }
  th { background:#7a1f1f; color:#fff; } table tr:nth-child(even) td { background:#f7f0f0; }
  .tag { padding:1px 5px; border-radius:3px; font-size:7.5px; font-weight:600; }
  .alta { background:#fdecea; color:#c62828; } .conv { background:#ede7f6; color:#4527a0; } .rio { background:#fff3e0; color:#e65100; }
  .part { background:#e8eef7; color:#1f4e79; padding:1px 4px; border-radius:3px; font-size:7.5px; }
  .nota { font-size:8px; color:#666; font-style:italic; }
  footer { margin-top:16px; border-top:1px solid #ddd; padding-top:6px; font-size:7.5px; color:#888; }
"""


def _tabela_regs(regs, anos, convergencia_flag=False):
    linhas = []
    for r in regs:
        prog = "; ".join(f"{p['ben']} ({p['desde']}→{p['ate']})" for p in r["programas"])
        anosc = "".join(f"<td style='text-align:center'>{r['por_ano'].get(a, 0) or '·'}</td>" for a in anos)
        conv = "<span class='tag conv'>Câmara+Pref.</span>" if (convergencia_flag and r["poder"] == "Câmara + Prefeitura") else ""
        linhas.append(
            f"<tr><td>{r['nome']}</td><td><span class='tag alta'>{r['certeza']}</span> {conv}</td>"
            f"<td>…{r['cpf_frag']}…</td><td>{r.get('cargo', '')}</td>"
            f"<td>{r.get('vinculos', '')}</td>"
            f"<td><span class='part'>{r['partido']}</span></td><td>{prog}</td>{anosc}"
            f"<td>{'<span class=\"tag alta\">SIM</span>' if r['ainda_recebe'] else 'não'}</td></tr>")
    cab = ("<tr><th>Nome</th><th>Certeza</th><th>CPF</th><th>Cargo</th>"
           "<th>Vínculo(s) público(s) — nomeação→saída</th>"
           "<th>Partido</th><th>Benefício DURANTE o vínculo (trajetória)</th>" +
           "".join(f"<th>{a}</th>" for a in anos) + "<th>Ainda?</th></tr>")
    return f"<table>{cab}{''.join(linhas)}</table>"


def _render(titulo, subtitulo, kpis, corpo_html) -> str:
    kpi_html = "".join(f"<div class='kpi'><div class='n'>{v}</div><div class='l'>{l}</div></div>" for v, l in kpis)
    return (f"<!doctype html><html lang='pt-BR'><head><meta charset='utf-8'><style>{_CSS}</style></head><body>"
            f"<div class='capa'><div class='classif'>CONFIDENCIAL — SUBSÍDIO PARA APURAÇÃO</div>"
            f"<h1>{titulo}</h1><div class='meta'>{subtitulo}</div></div>"
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
    corpo = ["<h2>1. Nomeados da Câmara recebendo benefício assistencial — por órgão (gabinete/vereador)</h2><p class='nota'>⚖️ <b>Justiça:</b> só entram benefícios recebidos <b>DURANTE</b> um vínculo público (cruzamento benefício×janela de nomeação). Quem recebeu entre empregos foi excluído — não é irregularidade.</p>",
             "<p class='nota'>Só os casos de certeza ALTA (um beneficiário, um servidor, CPF legível). "
             "Nomeação/exoneração para conferência — só há incompatibilidade se o benefício foi recebido "
             "DURANTE o vínculo. Auxílio Emergencial (2020–21) teve elegibilidade ampla (sinal mais fraco).</p>"]
    for org, regs in _agrupar(alta):
        corpo.append(f"<h3>{org} — {len(regs)} nomeado(s)</h3>{_tabela_regs(regs, anos)}")

    corpo.append("<h2>2. Convergência Câmara ↔ Prefeitura (o legislativo ligado ao executivo)</h2>")
    corpo.append("<p class='nota'>Nomeados da Câmara que TAMBÉM constam na folha da Prefeitura (acúmulo "
                 "de vínculo). É o cruzamento que interessa: quem transita entre os dois poderes.</p>")
    corpo.append(_tabela_regs(convergencia, anos, convergencia_flag=True) if convergencia
                 else "<p class='nota'>Nenhum caso de convergência com certeza no recorte atual.</p>")

    corpo.append("<h2>3. Gabinetes sob suplência — equipe do titular sobrevivente</h2>")
    for g in d["gabs_suplencia"]:
        sob = g["sobreviventes"]
        det = ("".join(f"<tr><td>{s['nome']}</td><td>{'livre nomeação' if s.get('eh_livre') else s.get('vinculo', '')}</td>"
                       f"<td>{s['cargo']}</td><td>{s['ingresso']}</td></tr>" for s in sob))
        corpo.append(f"<h3>Gabinete Nº {g['gabinete']} — titular {g['titular']} · suplente {g['suplente']} (posse {g['posse']})</h3>")
        corpo.append(f"<table><tr><th>Sobrevivente</th><th>Vínculo</th><th>Cargo</th><th>Ingresso</th></tr>{det}</table>"
                     if sob else "<p class='nota'>Sem sobrevivente (suplente montou a própria equipe).</p>")

    corpo.append("<h2>4. Servidores da Câmara que recebem benefício em OUTRA cidade (moram fora do Rio)</h2>")
    corpo.append(_secao_fora_rio(camara, fora))

    kpis = [(len(alta), "nomeados da Câmara (certeza ALTA)"), (len(convergencia), "convergência com a Prefeitura"),
            (len(d["gabs_suplencia"]), "gabinetes sob suplência"),
            (sum(1 for r in camara if r["nome_norm"] in fora), "recebem fora do Rio")]
    html = _render("Perícia — Câmara Municipal do Rio: nomeados × benefício assistencial",
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
    corpo = ["<h2>1. Servidores da Prefeitura recebendo benefício assistencial — por órgão</h2><p class='nota'>⚖️ <b>Justiça:</b> só entram benefícios recebidos <b>DURANTE</b> um vínculo público (cruzamento benefício×janela de nomeação). Quem recebeu entre empregos foi excluído — não é irregularidade.</p>",
             "<p class='nota'>Certeza ALTA (um beneficiário, um servidor, CPF legível). Nomeação/"
             "exoneração = faixa de presença na folha (por mês, conforme a folha carregada) — só há "
             "incompatibilidade se recebido DURANTE o vínculo. Ativo/aposentado separados na situação.</p>"]
    for org, regs in _agrupar(alta):
        corpo.append(f"<h3>{org} — {len(regs)} servidor(es)</h3>{_tabela_regs(regs, anos)}")
    corpo.append("<h2>2. Servidores da Prefeitura que recebem benefício em OUTRA cidade (moram fora do Rio)</h2>")
    corpo.append(_secao_fora_rio(prefeitura, fora))
    kpis = [(len(alta), "servidores da Prefeitura (certeza ALTA)"),
            (len(prefeitura), "total no Rio (ALTA+MÉDIA)"),
            (sum(1 for r in prefeitura if r["nome_norm"] in fora), "recebem fora do Rio")]
    html = _render("Perícia — Prefeitura do Rio: servidores × benefício assistencial",
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
