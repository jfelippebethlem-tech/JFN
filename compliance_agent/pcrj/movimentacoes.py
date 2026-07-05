# -*- coding: utf-8 -*-
"""MOVIMENTAÇÕES/trajetórias — Câmara ⇄ Prefeitura ⇄ candidatura, nos dois sentidos, com datas.

Detalhamento pedido pelo dono (indício, sem CPF):
  1. GABINETE → PREFEITURA: saiu de gabinete de vereador e foi à Prefeitura (com QUEM/QUANDO —
     data do ato no gabinete e admissão na Prefeitura posterior). Sinal principal.
  2. PREFEITURA → GABINETE: estava na Prefeitura e depois entrou em gabinete da Câmara.
  3. Interseções nos dois lados / ambos os sentidos (concomitância também).
  4. Candidato ANTES e DEPOIS da nomeação, nos dois sentidos (Câmara e Prefeitura).
  5. Multi-gabinete: pessoa que passou por 2+ gabinetes = 2 parlamentares distintos (troca de
     suplente↔titular tratada como gabinetes separados).
"""
from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path

from compliance_agent.pcrj import db as _db


def _e(x) -> str:
    import html
    return html.escape(str(x or ""))


def _d(s: str | None) -> date | None:
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})", (s or "").strip())
    return date(int(m.group(3)), int(m.group(2)), int(m.group(1))) if m else None


def _postos_pref(observacao: str) -> tuple[date | None, date | None, str]:
    m = re.search(r"admissao=(\S*)\s+exoneracao=(\S*)", observacao or "")
    if not m:
        return None, None, ""
    exo = m.group(2)
    return _d(m.group(1)), (_d(exo) if exo not in ("", "None") else None), m.group(1)


def _pessoas(con) -> list[dict]:
    """Agrega, por pessoa vinculada: gabinete+data do ato, postos PCRJ (datas), candidaturas."""
    base = con.execute("""
        SELECT vc.nome_norm, MIN(vc.nome_camara) nome,
          (SELECT MIN(s.data1) FROM pcrj_camara_servidores s
            WHERE s.nome_norm=vc.nome_norm AND s.gabinete_num IS NOT NULL) ato_gab,
          (SELECT MIN(s.data1) FROM pcrj_camara_servidores s WHERE s.nome_norm=vc.nome_norm) ato_qq,
          (SELECT GROUP_CONCAT(DISTINCT s.gabinete_num) FROM pcrj_camara_servidores s
            WHERE s.nome_norm=vc.nome_norm AND s.gabinete_num IS NOT NULL) gabs
        FROM pcrj_vinculo_cruzado vc WHERE vc.confianca='indicio_nome_unico'
        GROUP BY vc.nome_norm""").fetchall()
    ver = {r["gabinete_num"]: r["titular"] for r in con.execute(
        "SELECT gabinete_num, titular FROM pcrj_gabinetes")}
    out = []
    for b in base:
        postos = []
        for p in con.execute(
                "SELECT cargo_pcrj, orgao_pcrj, observacao FROM pcrj_vinculo_cruzado "
                "WHERE nome_norm=? AND confianca='indicio_nome_unico'", (b["nome_norm"],)):
            adm, exo, adm_s = _postos_pref(p["observacao"])
            postos.append({"cargo": p["cargo_pcrj"], "orgao": p["orgao_pcrj"],
                           "adm": adm, "exo": exo, "adm_s": adm_s})
        cands = [dict(c) for c in con.execute(
            "SELECT nome_tse, cargo, municipio, ano, outra_cidade FROM tse_candidatura "
            "WHERE nome_norm=? ORDER BY ano", (b["nome_norm"],))]
        gabs = [int(float(g)) for g in (b["gabs"].split(",") if b["gabs"] else []) if g]
        out.append({"nome": b["nome"], "ato_gab": _d(b["ato_gab"]), "ato_qq": _d(b["ato_qq"]),
                    "gabs": gabs, "gab_label": "; ".join(f"Gab {g} ({ver.get(g,'?')})" for g in gabs),
                    "postos": postos, "cands": cands, "nome_norm": b["nome_norm"]})
    return out


def _fmt(d: date | None) -> str:
    return d.strftime("%d/%m/%Y") if d else "—"


# ---- classificadores de trajetória ----
def _gab_para_pref(pz: dict) -> dict | None:
    """Saiu de gabinete e foi à Prefeitura: 1º posto PCRJ com admissão POSTERIOR ao ato no gabinete."""
    if not pz["ato_gab"] or not pz["gabs"]:
        return None
    posts = sorted((p for p in pz["postos"] if p["adm"]), key=lambda p: p["adm"])
    dep = next((p for p in posts if p["adm"] > pz["ato_gab"]), None)
    return {"posto": dep} if dep else None


def _pref_para_gab(pz: dict) -> dict | None:
    """Estava na Prefeitura e depois entrou em gabinete: admissão PCRJ ANTES do ato no gabinete."""
    if not pz["ato_gab"] or not pz["gabs"]:
        return None
    posts = sorted((p for p in pz["postos"] if p["adm"]), key=lambda p: p["adm"])
    ant = next((p for p in posts if p["adm"] < pz["ato_gab"]), None)
    return {"posto": ant} if ant else None


def _cand_flags(pz: dict) -> list[str]:
    """Candidato ANTES/DEPOIS da nomeação na Câmara (ato_qq) — nos dois sentidos."""
    flags = []
    ref = pz["ato_qq"]
    for c in pz["cands"]:
        if not ref or not c["ano"]:
            continue
        quando = "antes" if c["ano"] < ref.year else ("depois" if c["ano"] > ref.year else "no ano")
        fora = " [outra cidade]" if c["outra_cidade"] else ""
        flags.append(f"{c['municipio'].title()} {c['ano']} ({quando} da nomeação){fora}")
    return flags


# ---- tabelas ----
def _tab_gabpref(pessoas: list[dict]) -> tuple[str, int]:
    linhas = []
    for pz in sorted(pessoas, key=lambda x: x["nome"]):
        r = _gab_para_pref(pz)
        if not r:
            continue
        p = r["posto"]
        linhas.append(f"<tr><td>{_e(pz['nome'])}</td><td>{_e(pz['gab_label'])}</td>"
                      f"<td>{_fmt(pz['ato_gab'])}</td>"
                      f"<td>{_e(p['cargo'])} @ {_e(p['orgao'])}</td>"
                      f"<td>{_fmt(p['adm'])}</td><td>{_fmt(p['exo'])}</td></tr>")
    if not linhas:
        return "<p class='nota'>Nenhum caso identificado no acervo atual.</p>", 0
    return ("<table><tr><th>Nome</th><th>Gabinete de origem</th><th>Data do ato (Câmara)</th>"
            "<th>Cargo/Órgão Prefeitura</th><th>Admissão Prefeitura</th><th>Saída</th></tr>"
            + "".join(linhas) + "</table>", len(linhas))


def _tab_prefgab(pessoas: list[dict]) -> tuple[str, int]:
    linhas = []
    for pz in sorted(pessoas, key=lambda x: x["nome"]):
        r = _pref_para_gab(pz)
        if not r:
            continue
        p = r["posto"]
        linhas.append(f"<tr><td>{_e(pz['nome'])}</td>"
                      f"<td>{_e(p['cargo'])} @ {_e(p['orgao'])}</td><td>{_fmt(p['adm'])}</td>"
                      f"<td>{_e(pz['gab_label'])}</td><td>{_fmt(pz['ato_gab'])}</td></tr>")
    if not linhas:
        return "<p class='nota'>Nenhum caso identificado no acervo atual.</p>", 0
    return ("<table><tr><th>Nome</th><th>Cargo/Órgão Prefeitura (origem)</th>"
            "<th>Admissão Prefeitura</th><th>Gabinete (destino)</th><th>Data do ato</th></tr>"
            + "".join(linhas) + "</table>", len(linhas))


def _tab_cands(pessoas: list[dict]) -> tuple[str, int]:
    linhas = []
    for pz in sorted(pessoas, key=lambda x: x["nome"]):
        fl = _cand_flags(pz)
        if not fl:
            continue
        linhas.append(f"<tr><td>{_e(pz['nome'])}</td><td>{_e(pz['gab_label'] or '—')}</td>"
                      f"<td>{_e('; '.join(fl))}</td></tr>")
    if not linhas:
        return "<p class='nota'>Nenhum caso.</p>", 0
    return ("<table><tr><th>Nome</th><th>Vínculo Câmara</th>"
            "<th>Candidatura(s) — cidade, ano, antes/depois da nomeação</th></tr>"
            + "".join(linhas) + "</table>", len(linhas))


def _tab_multigab(con) -> tuple[str, int]:
    rows = con.execute("""
        SELECT nome_norm, MIN(nome) nome, COUNT(DISTINCT gabinete_num) ng
        FROM pcrj_camara_servidores WHERE gabinete_num IS NOT NULL
        GROUP BY nome_norm HAVING ng>=2 ORDER BY ng DESC, nome""").fetchall()
    ver = {r["gabinete_num"]: r["titular"] for r in con.execute(
        "SELECT gabinete_num, titular FROM pcrj_gabinetes")}
    linhas = []
    for r in rows:
        det = con.execute(
            "SELECT gabinete_num, data1, cargo FROM pcrj_camara_servidores "
            "WHERE nome_norm=? AND gabinete_num IS NOT NULL ORDER BY data1", (r["nome_norm"],)).fetchall()
        seq = " → ".join(f"Gab {x['gabinete_num']} ({ver.get(x['gabinete_num'],'?')}, {x['data1']})"
                         for x in det)
        linhas.append(f"<tr><td>{_e(r['nome'])}</td><td>{r['ng']}</td><td>{_e(seq)}</td></tr>")
    if not linhas:
        return "<p class='nota'>Nenhuma pessoa em 2+ gabinetes.</p>", 0
    return ("<p>Cada gabinete = um parlamentar distinto (troca suplente↔titular tratada como "
            "gabinetes separados). Sequência por data do ato:</p>"
            "<table><tr><th>Nome</th><th>Nº gabinetes</th><th>Trajetória (gabinete/vereador/data)</th>"
            "</tr>" + "".join(linhas) + "</table>", len(linhas))


def montar_ctx(db_path=None) -> dict:
    con = _db.conectar(db_path)
    try:
        pessoas = _pessoas(con)
        t_gp, n_gp = _tab_gabpref(pessoas)
        t_pg, n_pg = _tab_prefgab(pessoas)
        t_ca, n_ca = _tab_cands(pessoas)
        t_mg, n_mg = _tab_multigab(con)
        sumario = (f"<table>"
                   f"<tr><td>Saíram de gabinete → Prefeitura (admissão posterior ao ato)</td>"
                   f"<td style='text-align:right'><b>{n_gp}</b></td></tr>"
                   f"<tr><td>Prefeitura → gabinete (admissão anterior ao ato)</td>"
                   f"<td style='text-align:right'>{n_pg}</td></tr>"
                   f"<tr><td>Vinculados que foram candidatos (antes/depois da nomeação)</td>"
                   f"<td style='text-align:right'>{n_ca}</td></tr>"
                   f"<tr><td>Pessoas em 2+ gabinetes (parlamentares distintos)</td>"
                   f"<td style='text-align:right'>{n_mg}</td></tr></table>")
        secoes = [
            {"titulo": "I. Sumário das movimentações", "html": sumario},
            {"titulo": f"II. 🚩 Gabinete de vereador → Prefeitura ({n_gp}) — quem e quando", "html": t_gp},
            {"titulo": f"III. Prefeitura → gabinete de vereador ({n_pg})", "html": t_pg},
            {"titulo": f"IV. Candidatos (antes/depois da nomeação, dois sentidos) ({n_ca})", "html": t_ca},
            {"titulo": f"V. Trajetória entre gabinetes — suplente↔titular = 2 parlamentares ({n_mg})",
             "html": t_mg},
            {"titulo": "VI. Método e limitações (honestidade)", "html":
             "<p>Sem CPF → indício por nome. 'Gabinete→Prefeitura' compara a data do ato no gabinete "
             "com a admissão na Prefeitura; captura quem AINDA consta na Câmara (quadro vigente). "
             "Quem já <b>saiu</b> da Câmara está entre os 3.053 ex-servidores de livre nomeação "
             "(só nome+data de exoneração, sem gabinete) — não atribuível a gabinete. Datas dia/mês/"
             "ano preservadas. Cada gabinete = 1 parlamentar (suplente e titular são pessoas/períodos "
             "distintos).</p>"},
        ]
        return {
            "classificacao": "CONFIDENCIAL — CONTROLE EXTERNO",
            "titulo": "Movimentações Câmara ⇄ Prefeitura ⇄ candidaturas (Rio de Janeiro)",
            "subtitulo": "Trajetórias nos dois sentidos, com datas — Módulo PCRJ",
            "metodologia": "Análise temporal de trajetórias (indício; verificar por CPF)",
            "score": n_gp + n_pg, "faixa": "ALTO" if n_gp else "MÉDIO",
            "top_flags": [f"{n_gp} gab→pref", f"{n_pg} pref→gab", f"{n_mg} multi-gabinete"],
            "secoes": secoes,
            "proveniencia": [
                {"dado": "Câmara", "estado": "REAL", "fonte": "transparencia.camara.rj.gov.br",
                 "data": datetime.now().strftime("%d/%m/%Y")},
                {"dado": "Prefeitura", "estado": "REAL", "fonte": "contrachequeapi.rio.gov.br",
                 "data": datetime.now().strftime("%d/%m/%Y")},
                {"dado": "Candidaturas", "estado": "REAL", "fonte": "TSE (RJ)",
                 "data": datetime.now().strftime("%d/%m/%Y")}],
            "ressalva": "Indícios por nome para apuração por CPF no RH.",
        }
    finally:
        con.close()


async def gerar(db_path=None) -> dict:
    from compliance_agent.reporting.render_html import html_to_pdf, render_html
    ctx = montar_ctx(db_path)
    html = render_html(ctx)
    base = Path(__file__).resolve().parents[2] / "reports"
    base.mkdir(exist_ok=True)
    pdf = str(base / f"pcrj_movimentacoes_{datetime.now().date()}.pdf")
    await html_to_pdf(html, pdf)
    return {"pdf": pdf}


if __name__ == "__main__":
    import asyncio
    print(asyncio.run(gerar()))
