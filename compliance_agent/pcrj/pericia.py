# -*- coding: utf-8 -*-
"""PERÍCIA completa — vínculos Câmara×Prefeitura do Rio: direção temporal, datas e geografia.

Consolida, com honestidade (sem CPF → indício por nome, homônimo possível):
  - TODOS que já tiveram vínculo Câmara↔Prefeitura (a qualquer tempo);
  - DIREÇÃO: quem estava na Prefeitura ANTES de ir à Câmara × quem estava na Câmara
    ANTES de ir à Prefeitura (pela ordem das datas), com flag de concomitância;
  - DATAS de entrada/saída dos dois lados (ato na Câmara; admissão/exoneração na Prefeitura);
  - quem está na folha da Prefeitura E foi candidato / tem domicílio eleitoral em OUTRA cidade.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path

from compliance_agent.pcrj import db as _db
from compliance_agent.pcrj.relatorio import _cessao_provavel, _e, _vinculo_efetivo

_HOJE = None  # injetável em teste; senão date.today() no uso


def _hoje() -> date:
    return _HOJE or date.today()


def _d(s: str | None) -> date | None:
    s = (s or "").strip()
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})", s)
    if m:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    return date(int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def _posts_pref(observacao: str) -> tuple[date | None, date | None]:
    """(admissão, exoneração|None) de um vínculo, a partir da observação."""
    m = re.search(r"admissao=(\S*)\s+exoneracao=(\S*)", observacao or "")
    if not m:
        return None, None
    exo = m.group(2)
    return _d(m.group(1)), (_d(exo) if exo not in ("", "None") else None)


def _pessoas(con) -> list[dict]:
    """Agrega por pessoa: dados da Câmara + lista de postos na Prefeitura + candidaturas."""
    base = con.execute("""
        SELECT vc.nome_norm, MIN(vc.nome_camara) nome,
               (SELECT MIN(substr(s.data1,7,4)||'-'||substr(s.data1,4,2)||'-'||substr(s.data1,1,2))
                  FROM pcrj_camara_servidores s
                  WHERE s.nome_norm=vc.nome_norm AND s.data1 LIKE '__/__/____') ato,
               (SELECT MIN(s.ano_ingresso) FROM pcrj_camara_servidores s WHERE s.nome_norm=vc.nome_norm) ingr,
               (SELECT GROUP_CONCAT(DISTINCT s.gabinete_num) FROM pcrj_camara_servidores s
                 WHERE s.nome_norm=vc.nome_norm AND s.gabinete_num IS NOT NULL) gabs,
               (SELECT GROUP_CONCAT(DISTINCT s.cargo) FROM pcrj_camara_servidores s
                 WHERE s.nome_norm=vc.nome_norm) cargos_cam
        FROM pcrj_vinculo_cruzado vc WHERE vc.confianca='indicio_nome_unico'
        GROUP BY vc.nome_norm""").fetchall()
    ver = {r["gabinete_num"]: r["titular"] for r in con.execute(
        "SELECT gabinete_num, titular FROM pcrj_gabinetes")}
    out = []
    for b in base:
        cam_ato = _d(b["ato"]) or (date(b["ingr"], 1, 1) if b["ingr"] else None)
        postos = []
        for p in con.execute(
                "SELECT cargo_pcrj, orgao_pcrj, observacao FROM pcrj_vinculo_cruzado "
                "WHERE nome_norm=? AND confianca='indicio_nome_unico'", (b["nome_norm"],)):
            adm, exo = _posts_pref(p["observacao"])
            postos.append({"cargo": p["cargo_pcrj"], "orgao": p["orgao_pcrj"],
                           "adm": adm, "exo": exo, "cessao": _cessao_provavel(dict(p)),
                           "efetivo": _vinculo_efetivo(p["cargo_pcrj"])})
        cands = con.execute(
            "SELECT nome_tse, cargo, municipio, ano, partido, outra_cidade FROM tse_candidatura "
            "WHERE nome_norm=? ORDER BY ano", (b["nome_norm"],)).fetchall()
        gabs = [g for g in (b["gabs"].split(",") if b["gabs"] else []) if g]
        out.append({
            "nome": b["nome"], "cam_ato": cam_ato, "ingresso": b["ingr"],
            "gabinetes": "; ".join(f"Gab {g} ({ver.get(int(float(g)), '?')})" for g in gabs) or "admin/—",
            "cargos_cam": b["cargos_cam"], "postos": postos,
            "candidaturas": [dict(c) for c in cands],
        })
    return out


def _direcao(pessoa: dict) -> str:
    """Trajetória pela ORDEM das datas: 'pref_antes' (Prefeitura→Câmara) / 'camara_antes'
    (Câmara→Prefeitura) / 'indef'. Concomitância é tratada como flag à parte."""
    adms = [p["adm"] for p in pessoa["postos"] if p["adm"]]
    if not adms or not pessoa["cam_ato"]:
        return "indef"
    return "pref_antes" if min(adms) < pessoa["cam_ato"] else "camara_antes"


def _concomitante(pessoa: dict) -> bool:
    """Algum posto na Prefeitura se sobrepõe ao período na Câmara (ato → hoje)?"""
    if not pessoa["cam_ato"]:
        return False
    for p in pessoa["postos"]:
        if not p["adm"]:
            continue
        fim = p["exo"] or _hoje()
        if fim >= pessoa["cam_ato"]:
            return True
    return False


def _fmt(d: date | None) -> str:
    return d.strftime("%d/%m/%Y") if d else "—"


def _linha_pessoa(pz: dict) -> str:
    postos = "<br>".join(
        f"{_e(p['cargo'])} @ {_e(p['orgao'])} — entrada {_fmt(p['adm'])}, saída {_fmt(p['exo'])}"
        + (" <i>(cessão)</i>" if p["cessao"] else (" <b>(efetivo)</b>" if p["efetivo"] else ""))
        for p in pz["postos"])
    concom = ' <span class="flag">CONCOMITANTE</span>' if _concomitante(pz) else ""
    return (f"<tr><td>{_e(pz['nome'])}{concom}</td>"
            f"<td>{_e(pz['gabinetes'])}<br><span class='nota'>ato {_fmt(pz['cam_ato'])} "
            f"(ingresso {pz['ingresso'] or '?'})</span></td>"
            f"<td>{postos}</td></tr>")


def _tabela(pessoas: list[dict]) -> str:
    if not pessoas:
        return "<p class='nota'>Nenhum registro nesta categoria.</p>"
    corpo = "".join(_linha_pessoa(p) for p in sorted(pessoas, key=lambda x: x["nome"]))
    return ("<table><tr><th>Nome</th><th>Câmara (gabinete · data do ato)</th>"
            "<th>Prefeitura — postos com entrada/saída</th></tr>" + corpo + "</table>")


def _tabela_geo(pessoas: list[dict]) -> str:
    linhas = []
    for pz in pessoas:
        fora = [c for c in pz["candidaturas"] if c["outra_cidade"]]
        if not fora:
            continue
        cids = "; ".join(f"{_e(c['municipio'].title())} ({c['cargo'].lower()}, {c['ano']})" for c in fora)
        ativo = any(not p["exo"] for p in pz["postos"])
        linhas.append(f"<tr><td>{_e(pz['nome'])}</td>"
                      f"<td>{'na folha atual' if ativo else 'já esteve'} na Prefeitura</td>"
                      f"<td>{cids}</td></tr>")
    if not linhas:
        return "<p class='nota'>Nenhum caso.</p>"
    return ("<table><tr><th>Nome</th><th>Vínculo Prefeitura</th>"
            "<th>Candidatura / domicílio eleitoral em outra cidade</th></tr>"
            + "".join(linhas) + "</table>")


def _tabela_comissionados_cand(con) -> tuple[str, int]:
    """Comissionados da Prefeitura (2021+) que já foram candidatos (cruzamento inverso)."""
    try:
        rows = con.execute("""
            SELECT nome_pcrj, cargo_pcrj, orgao_pcrj, admissao, exoneracao,
                   cand_cidade, cand_ano, cand_cargo,
                   (SELECT COUNT(DISTINCT c2.cand_cidade) FROM pcrj_comissionado_candidato c2
                     WHERE c2.nome_norm=c.nome_norm) n_cid
            FROM pcrj_comissionado_candidato c
            GROUP BY nome_norm, orgao_pcrj, cargo_pcrj
            ORDER BY nome_pcrj, admissao""").fetchall()
    except Exception:
        return "<p class='nota'>Cruzamento inverso ainda não coletado.</p>", 0
    if not rows:
        return "<p class='nota'>Nenhum comissionado-candidato identificado no escopo coletado.</p>", 0
    linhas, pessoas = [], set()
    for r in rows:
        pessoas.add(r["nome_pcrj"])
        homon = " <span class='flag' style='background:#eee;color:#777'>homônimo provável</span>" \
            if r["n_cid"] and r["n_cid"] >= 3 else ""
        fora = " <span class='flag'>OUTRA CIDADE</span>" if (r["cand_cidade"] or "").upper() \
            not in ("RIO DE JANEIRO", "") else ""
        linhas.append(
            f"<tr><td>{_e(r['nome_pcrj'])}{homon}</td>"
            f"<td>{_e(r['cargo_pcrj'])} @ {_e(r['orgao_pcrj'])}</td>"
            f"<td>entrada {_e(r['admissao'])}, saída {_e(r['exoneracao'] or '—')}</td>"
            f"<td>{_e((r['cand_cargo'] or '').lower())} — {_e((r['cand_cidade'] or '').title())} "
            f"({r['cand_ano']}){fora}</td></tr>")
    tab = ("<table><tr><th>Nome (Prefeitura)</th><th>Cargo comissionado/Órgão</th>"
           "<th>Entrada/Saída</th><th>Candidatura anterior</th></tr>" + "".join(linhas) + "</table>")
    return tab, len(pessoas)


def montar_ctx(db_path=None) -> dict:
    con = _db.conectar(db_path)
    try:
        pessoas = _pessoas(con)
        pref_antes = [p for p in pessoas if _direcao(p) == "pref_antes"]
        camara_antes = [p for p in pessoas if _direcao(p) == "camara_antes"]
        concom = [p for p in pessoas if _concomitante(p)]
        geo = [p for p in pessoas if any(c["outra_cidade"] for c in p["candidaturas"])]
        total = len(pessoas)
        tab_com, n_com = _tabela_comissionados_cand(con)

        sumario = (
            f"<table>"
            f"<tr><td><b>Total que já tiveram vínculo Câmara↔Prefeitura</b> (a qualquer tempo)</td>"
            f"<td style='text-align:right'><b>{total}</b></td></tr>"
            f"<tr><td>Estavam na <b>Prefeitura ANTES</b> de ir à Câmara (Prefeitura→Câmara)</td>"
            f"<td style='text-align:right'>{len(pref_antes)}</td></tr>"
            f"<tr><td>Estavam na <b>Câmara ANTES</b> de ir à Prefeitura (Câmara→Prefeitura)</td>"
            f"<td style='text-align:right'>{len(camara_antes)}</td></tr>"
            f"<tr><td>Com vínculo <b>concomitante</b> (os dois ao mesmo tempo)</td>"
            f"<td style='text-align:right'>{len(concom)}</td></tr>"
            f"<tr><td>Na Prefeitura E candidato/domicílio em <b>outra cidade</b></td>"
            f"<td style='text-align:right'>{len(geo)}</td></tr>"
            f"<tr><td><b>Comissionados da Prefeitura (2021+) que já foram candidatos</b> (inverso)</td>"
            f"<td style='text-align:right'><b>{n_com}</b></td></tr>"
            f"</table>")

        janela = con.execute(
            "SELECT MAX(substr(coletado_em,1,10)) FROM pcrj_camara_servidores").fetchone()[0] or "?"
        consulta = con.execute(
            "SELECT MAX(substr(consultado_em,1,10)) FROM pcrj_prefeitura_consulta").fetchone()[0] or "?"
        nota_temporal = (
            f"<p class='nota'><b>Janela temporal e premissas (leia antes das tabelas):</b> "
            f"lado Câmara = <b>relação atual de servidores</b> do portal de dados abertos (coletada em {janela}); "
            f"quem já saiu da Câmara não consta — logo, constar da lista foi tratado como vínculo vigente. "
            f"Lado Prefeitura = consulta ao contracheque em {consulta}; <b>ativo</b> significa sem data de "
            f"exoneração <i>nessa consulta</i>, não em data posterior. Datas da Câmara: data do ATO de ingresso "
            f"(fallback: 1º de janeiro do ano de ingresso, marcado como aproximação). Direção temporal comparada "
            f"por datas reais (ordem cronológica), nunca por texto. Nome idêntico sem CPF = indício, não prova.</p>")

        secoes = [
            {"titulo": "I. Sumário da perícia", "html": nota_temporal + sumario},
            {"titulo": f"II. Prefeitura → Câmara: estavam na Prefeitura ANTES ({len(pref_antes)})",
             "html": _tabela(pref_antes)},
            {"titulo": f"III. Câmara → Prefeitura: estavam na Câmara ANTES ({len(camara_antes)})",
             "html": _tabela(camara_antes)},
            {"titulo": f"IV. Vínculo concomitante — Câmara e Prefeitura ao mesmo tempo ({len(concom)})",
             "html": _tabela(concom)},
            {"titulo": f"V. Na Prefeitura E candidato/domicílio em outra cidade ({len(geo)})",
             "html": _tabela_geo(geo)},
            {"titulo": f"VI. Comissionados da Prefeitura (2021+) que já foram candidatos ({n_com})",
             "html": ("<p>Cruzamento inverso: candidatos do TSE (município do Rio) que ocupam/"
                      "ocuparam <b>cargo comissionado</b> (ESPECIAL/DAS/DAI) na Prefeitura a partir "
                      "de 2021. Efetivos e aposentados fora do escopo.</p>" + tab_com)},
            {"titulo": "VII. Cobertura e limitações (honestidade)", "html":
             "<p>Sem CPF em nenhuma base pública → casamento por <b>nome</b> é indício, não prova "
             "(homônimo possível; nome em ≥3 municípios sinalizado). Direção pela ordem das datas "
             "(ato na Câmara × admissão na Prefeitura). 'Domicílio em outra cidade' = município da "
             "candidatura no TSE (domicílio eleitoral obrigatório), proxy de residência.</p>"
             "<p><b>Câmara:</b> quadro vigente (relação de servidores). Os 3.053 ex-servidores de "
             "livre nomeação que já saíram só têm nome+data de exoneração publicados (sem gabinete/"
             "cargo) — entram como 'já foi da Câmara' mas não são atribuíveis a gabinete. "
             "<b>Prefeitura:</b> competências-amostra 06/2021–06/2025 + gestão atual (pente fino "
             "temporal amplo, não mês a mês). <b>Gabinetes por período histórico</b> de suplente/"
             "titular: a fonte só publica o mapa atual; ingresso anterior a 2025 pertence a "
             "legislatura(s) passada(s) e não é atribuível ao parlamentar atual.</p>"},
        ]
        return {
            "classificacao": "CONFIDENCIAL — CONTROLE EXTERNO",
            "titulo": "Perícia — vínculos Câmara × Prefeitura do Rio (direção, datas e geografia)",
            "subtitulo": f"{total} pessoas com vínculo nas duas casas — Módulo PCRJ",
            "metodologia": "Cruzamento nominal + análise temporal e geográfica (indício; verificar por CPF)",
            "score": total, "faixa": "ALTO",
            "top_flags": [f"{len(pref_antes)} pref→câmara", f"{len(camara_antes)} câmara→pref",
                          f"{len(geo)} outra cidade"],
            "secoes": secoes,
            "proveniencia": [
                {"dado": "Servidores Câmara", "estado": "REAL",
                 "fonte": "transparencia.camara.rj.gov.br", "data": datetime.now().strftime("%d/%m/%Y")},
                {"dado": "Remuneração Prefeitura", "estado": "REAL",
                 "fonte": "contrachequeapi.rio.gov.br", "data": datetime.now().strftime("%d/%m/%Y")},
                {"dado": "Candidaturas/domicílio", "estado": "REAL",
                 "fonte": "TSE dados abertos (RJ)", "data": datetime.now().strftime("%d/%m/%Y")}],
            "ressalva": "Indícios para apuração por CPF no RH. Cessão/requisição não é acúmulo.",
        }
    finally:
        con.close()


async def gerar(db_path=None) -> dict:
    from compliance_agent.reporting.render_html import html_to_pdf, render_html
    ctx = montar_ctx(db_path)
    html = render_html(ctx)
    base = Path(__file__).resolve().parents[2] / "reports"
    base.mkdir(exist_ok=True)
    pdf = str(base / f"pcrj_pericia_{datetime.now().date()}.pdf")
    await html_to_pdf(html, pdf)
    return {"pdf": pdf, "total": ctx["score"]}


if __name__ == "__main__":
    import asyncio
    print(asyncio.run(gerar()))
