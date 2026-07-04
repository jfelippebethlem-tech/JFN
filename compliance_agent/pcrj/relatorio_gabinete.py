# -*- coding: utf-8 -*-
"""Relatório POR GABINETE — listagem de nomeados e seus vínculos na Prefeitura do Rio.

Gera um PDF PESQUISÁVEL (texto real, Ctrl+F) organizado por gabinete/vereador: um destaque
para um gabinete específico (com a listagem COMPLETA + os nomeados que estão/estiveram na
Prefeitura) e um índice geral por vereador (para buscar qualquer gabinete). Honesto: sem CPF,
o vínculo é INDÍCIO; "Requisitado"/"à disposição" indica cessão (vínculo único), não acúmulo.
"""
from __future__ import annotations

import html as _html
from datetime import datetime
from pathlib import Path

from compliance_agent.pcrj import db as _db
from compliance_agent.pcrj.relatorio import (
    _ativo,
    _cessao_provavel,
    _datas_pcrj,
    _vinculo_efetivo,
)


def _e(x) -> str:
    return _html.escape(str(x or ""))


def _vinculos_do_gabinete(con, gab: int) -> list[dict]:
    return [dict(r) for r in con.execute(
        """SELECT vc.*, (SELECT GROUP_CONCAT(DISTINCT s.vinculo) FROM pcrj_camara_servidores s
                  WHERE s.nome_norm=vc.nome_norm) vinculo_camara
           FROM pcrj_vinculo_cruzado vc
           JOIN (SELECT DISTINCT nome_norm FROM pcrj_camara_servidores WHERE gabinete_num=?) g
             ON g.nome_norm=vc.nome_norm
           WHERE vc.confianca='indicio_nome_unico' ORDER BY vc.nome_camara""", (gab,))]


def _situacao(v: dict) -> str:
    if _cessao_provavel(v):
        return "cessão/requisição (vínculo único)"
    return "ATIVO na Prefeitura (concomitante)" if _ativo(v) else "vínculo encerrado na Prefeitura"


def _tabela_vinculos_gab(vincs: list[dict]) -> str:
    if not vincs:
        return "<p class='nota'>Nenhum nomeado deste gabinete com vínculo identificado na Prefeitura.</p>"
    linhas = []
    for v in vincs:
        efet = ' <span class="flag">EFETIVO/CARREIRA</span>' if _vinculo_efetivo(v.get("cargo_pcrj")) else ""
        adm, exo, mat = _datas_pcrj(v)
        linhas.append(
            f"<tr><td>{_e(v['nome_camara'])}{efet}</td>"
            f"<td>{_e(v.get('cargos_camara'))}</td>"
            f"<td>{_e(v['cargo_pcrj'])} @ {_e(v['orgao_pcrj'])}</td>"
            f"<td>{_e(adm)}</td><td>{_e(exo)}</td>"
            f"<td>{_e(_situacao(v))}</td><td>{_e(mat)}</td></tr>")
    return ("<table><tr><th>Nome</th><th>Cargo na Câmara</th><th>Cargo/Órgão na Prefeitura</th>"
            "<th>Admissão PCRJ</th><th>Exoneração PCRJ</th><th>Situação</th><th>Matrícula</th></tr>"
            + "".join(linhas) + "</table>")


_LEGISLATURA_ATUAL = 2025  # posse dos eleitos em 2024


def _tabela_listagem(con, gab: int) -> str:
    rows = con.execute(
        """SELECT DISTINCT nome, cargo, simbolo, vinculo, ano_ingresso, data1, data2
           FROM pcrj_camara_servidores WHERE gabinete_num=? ORDER BY ano_ingresso DESC, nome""",
        (gab,)).fetchall()
    linhas = []
    for r in rows:
        atual = (r["ano_ingresso"] or 0) >= _LEGISLATURA_ATUAL
        leg = ("atual" if atual
               else "<span style='color:#b26a00'>anterior*</span>")
        linhas.append(
            f"<tr><td>{_e(r['nome'])}</td><td>{_e(r['cargo'])}</td><td>{_e(r['simbolo'])}</td>"
            f"<td>{_e(r['vinculo'])}</td><td>{_e(r['data1'])}</td>"
            f"<td style='text-align:right'>{_e(r['ano_ingresso'])}</td><td>{leg}</td></tr>")
    return ("<table><tr><th>Nome</th><th>Cargo</th><th>Símbolo</th><th>Vínculo</th>"
            "<th>Data do ato</th><th>Ingresso</th><th>Legislatura</th></tr>"
            + "".join(linhas) + "</table>"
            "<p class='nota'>* ingresso anterior a 2025: o número do gabinete pertenceu a "
            "vereador(es) de legislatura(s) anterior(es); a atribuição ao parlamentar atual é "
            "apenas indicativa (a fonte pública só publica o mapa vigente).</p>")


def _candidaturas_gab(con, gab: int) -> str:
    """Candidaturas eleitorais dos nomeados DESTE gabinete (cidade, ano, partido; flag anterior)."""
    rows = con.execute("""
        SELECT tc.nome_tse, tc.cargo, tc.municipio, tc.ano, tc.partido, tc.outra_cidade,
               (SELECT MIN(s2.ano_ingresso) FROM pcrj_camara_servidores s2
                 WHERE s2.nome_norm=tc.nome_norm) ingresso,
               (SELECT COUNT(DISTINCT t2.municipio) FROM tse_candidatura t2
                 WHERE t2.nome_norm=tc.nome_norm) n_munic
        FROM tse_candidatura tc
        WHERE tc.nome_norm IN (SELECT nome_norm FROM pcrj_camara_servidores WHERE gabinete_num=?)
        ORDER BY tc.nome_tse, tc.ano DESC""", (gab,)).fetchall()
    if not rows:
        return ""
    linhas = []
    for r in rows:
        s = []
        if r["outra_cidade"]:
            s.append('<span class="flag">OUTRA CIDADE</span>')
        if r["ingresso"] and r["ano"] < r["ingresso"]:
            s.append('<span class="flag" style="background:#fff3e0;color:#e65100">ANTERIOR À NOMEAÇÃO</span>')
        if r["n_munic"] >= 3:
            s.append('<span class="flag" style="background:#eee;color:#777">homônimo provável</span>')
        linhas.append(f"<tr><td>{_e(r['nome_tse'])}</td>"
                      f"<td>{_e(r['cargo'])} — {_e(r['municipio'])} ({r['ano']}, {_e(r['partido'])})</td>"
                      f"<td>{' '.join(s)}</td></tr>")
    return ("<p class='nota'>Candidaturas eleitorais (TSE/RJ) de nomeados deste gabinete:</p>"
            "<table><tr><th>Nome (TSE)</th><th>Candidatura</th><th>Sinais</th></tr>"
            + "".join(linhas) + "</table>")


def _indice_geral(con) -> str:
    """Um bloco por gabinete com nomeados que têm vínculo na Prefeitura — busca por vereador."""
    gabs = con.execute("""
        SELECT g.gabinete_num, g.vereador, COUNT(DISTINCT vc.nome_norm) n
        FROM pcrj_gabinetes g
        JOIN pcrj_camara_servidores s ON s.gabinete_num=g.gabinete_num
        JOIN pcrj_vinculo_cruzado vc ON vc.nome_norm=s.nome_norm AND vc.confianca='indicio_nome_unico'
        GROUP BY g.gabinete_num ORDER BY n DESC, g.gabinete_num""").fetchall()
    partes = []
    for row in gabs:
        vincs = _vinculos_do_gabinete(con, row["gabinete_num"])
        nomes = "; ".join(
            f"{_e(v['nome_camara'])} → {_e(v['cargo_pcrj'])} ({_situacao(v).split('(')[0].strip()})"
            for v in vincs)
        partes.append(
            f"<p><b>Gabinete {row['gabinete_num']:02d} — {_e(row['vereador'])}</b> "
            f"({row['n']}): {nomes}</p>")
    return "".join(partes) or "<p class='nota'>Sem vínculos.</p>"


def _secoes_por_parlamentar(con) -> list[dict]:
    """Uma seção por PARLAMENTAR (ordenado pelo titular) — pesquisável por vereador.
    Título pelo vereador titular; suplente em exercício explicitado; contagem separando
    a legislatura atual (atribuição segura) das anteriores (atribuição histórica incerta)."""
    gabs = con.execute(
        "SELECT gabinete_num, titular, suplente FROM pcrj_gabinetes "
        "ORDER BY titular, gabinete_num").fetchall()
    secoes = []
    for g in gabs:
        gab = g["gabinete_num"]
        total = con.execute(
            "SELECT COUNT(DISTINCT nome_norm) n FROM pcrj_camara_servidores WHERE gabinete_num=?",
            (gab,)).fetchone()["n"]
        if not total:
            continue
        atual = con.execute(
            "SELECT COUNT(DISTINCT nome_norm) n FROM pcrj_camara_servidores "
            "WHERE gabinete_num=? AND ano_ingresso>=?", (gab, _LEGISLATURA_ATUAL)).fetchone()["n"]
        vincs = _vinculos_do_gabinete(con, gab)
        titulo = f"{g['titular'] or 'Gabinete'} — Gabinete {gab:02d}"
        sup = (f"<p><b>Suplente em exercício:</b> {_e(g['suplente'])}.</p>" if g["suplente"] else "")
        corpo = (sup + f"<p>{total} nomeados no gabinete ({atual} na legislatura atual · "
                 f"{total - atual} de ingresso anterior). <b>{len(vincs)}</b> com indício de "
                 "vínculo na Prefeitura.</p>"
                 + _tabela_vinculos_gab(vincs) + _candidaturas_gab(con, gab)
                 + "<p class='nota'>Listagem completa do gabinete:</p>" + _tabela_listagem(con, gab))
        secoes.append({"titulo": titulo, "html": corpo})
    return secoes


def _secao_admin(con) -> dict:
    """Estrutura administrativa da Câmara (não-gabinete): quem já esteve/está na Prefeitura."""
    rows = con.execute("""
        SELECT vc.nome_camara, vc.cargo_pcrj, vc.orgao_pcrj, vc.observacao,
               (SELECT GROUP_CONCAT(DISTINCT s.lotacao) FROM pcrj_camara_servidores s
                 WHERE s.nome_norm=vc.nome_norm AND s.tipo_lotacao<>'gabinete_parlamentar') lot,
               (SELECT GROUP_CONCAT(DISTINCT s2.vinculo) FROM pcrj_camara_servidores s2
                 WHERE s2.nome_norm=vc.nome_norm) vinculo_camara
        FROM pcrj_vinculo_cruzado vc WHERE vc.confianca='indicio_nome_unico'
          AND EXISTS(SELECT 1 FROM pcrj_camara_servidores s3 WHERE s3.nome_norm=vc.nome_norm
                     AND s3.tipo_lotacao<>'gabinete_parlamentar')
          AND NOT EXISTS(SELECT 1 FROM pcrj_camara_servidores s4 WHERE s4.nome_norm=vc.nome_norm
                     AND s4.tipo_lotacao='gabinete_parlamentar')
        ORDER BY lot, vc.nome_camara""").fetchall()
    if not rows:
        return {"titulo": "Estrutura administrativa da Câmara", "html": "<p class='nota'>Sem vínculos.</p>"}
    linhas = [f"<tr><td>{_e(r['nome_camara'])}</td><td>{_e(r['lot'])}</td>"
              f"<td>{_e(r['cargo_pcrj'])} @ {_e(r['orgao_pcrj'])}</td>"
              f"<td>{_e(_situacao(dict(r)))}</td></tr>" for r in rows]
    tab = ("<table><tr><th>Nome</th><th>Lotação na Câmara</th>"
           "<th>Cargo/Órgão na Prefeitura</th><th>Situação</th></tr>" + "".join(linhas) + "</table>")
    return {"titulo": "Estrutura administrativa da Câmara — nomeados que estão/estiveram na Prefeitura",
            "html": tab}


def montar_ctx_completo(db_path=None) -> dict:
    """Documento completo, pesquisável por gabinete/vereador + estrutura administrativa."""
    con = _db.conectar(db_path)
    try:
        n_gab = con.execute("SELECT COUNT(*) n FROM pcrj_gabinetes").fetchone()["n"]
        n_vinc = con.execute(
            "SELECT COUNT(DISTINCT nome_norm) n FROM pcrj_vinculo_cruzado "
            "WHERE confianca='indicio_nome_unico'").fetchone()["n"]
        n_atual = con.execute(
            "SELECT COUNT(DISTINCT nome_norm) n FROM pcrj_camara_servidores "
            "WHERE ano_ingresso>=?", (_LEGISLATURA_ATUAL,)).fetchone()["n"]
        intro = {"titulo": "Como usar e cobertura", "html":
                 "<p>Documento <b>pesquisável</b> (Ctrl+F): busque o nome do vereador (ex.: "
                 "'Pedro Duarte', 'Carlo Caiado'). <b>Agregado por parlamentar</b> (titular; "
                 "suplente em exercício explicitado). Cada seção traz os nomeados com vínculo na "
                 "Prefeitura, as candidaturas eleitorais e a listagem completa.</p>"
                 "<p><b>Atribuição histórica (limitação):</b> a fonte pública só publica o mapa "
                 f"<b>atual</b> de gabinetes. Só há atribuição segura ao parlamentar para o "
                 f"ingresso na legislatura atual (≥{_LEGISLATURA_ATUAL}); nomeados de ingresso "
                 "anterior aparecem sob o número do gabinete, mas pertenceram a vereador(es) de "
                 "legislatura(s) anterior(es) (marcados 'anterior*').</p>"
                 "<p><b>Cobertura das bases:</b> Câmara = quadro vigente (relação de servidores; "
                 "os 3.053 ex-servidores de livre nomeação que já saíram não têm gabinete "
                 "publicado, logo não são atribuíveis). Prefeitura = competências-amostra "
                 "(gestão atual + 06/2021–06/2025); vínculo por nome é <b>indício</b>, não prova; "
                 "'Requisitado'/'à disposição' = cessão (vínculo único), não acúmulo.</p>"}
        secoes = [intro] + _secoes_por_parlamentar(con) + [_secao_admin(con)]
        return {
            "classificacao": "CONFIDENCIAL — CONTROLE EXTERNO",
            "titulo": "Câmara Municipal do Rio — nomeados por parlamentar e vínculos na Prefeitura",
            "subtitulo": f"{n_gab} gabinetes · {n_atual} nomeados na legislatura atual · por parlamentar — Módulo PCRJ",
            "metodologia": "Cruzamento nominal Câmara×Prefeitura (indício; verificar por CPF)",
            "score": n_vinc, "faixa": "ALTO",
            "top_flags": [f"{n_gab} gabinetes", f"{n_vinc} vínculos Prefeitura"],
            "secoes": secoes,
            "proveniencia": [
                {"dado": "Servidores Câmara", "estado": "REAL",
                 "fonte": "transparencia.camara.rj.gov.br", "data": datetime.now().strftime("%d/%m/%Y")},
                {"dado": "Remuneração Prefeitura", "estado": "REAL",
                 "fonte": "contrachequeapi.rio.gov.br", "data": datetime.now().strftime("%d/%m/%Y")}],
            "ressalva": "Indícios por nome para apuração por CPF no RH. Cessão/requisição não é acúmulo.",
        }
    finally:
        con.close()


async def gerar_completo(db_path=None) -> dict:
    from compliance_agent.reporting.render_html import render_html, html_to_pdf
    ctx = montar_ctx_completo(db_path)
    html = render_html(ctx)
    base = Path(__file__).resolve().parents[2] / "reports"
    base.mkdir(exist_ok=True)
    pdf = str(base / f"pcrj_gabinetes_completo_{datetime.now().date()}.pdf")
    await html_to_pdf(html, pdf)
    return {"pdf": pdf, "gabinetes": len(ctx["secoes"]) - 2}


def montar_ctx(gab: int, db_path=None) -> dict:
    con = _db.conectar(db_path)
    try:
        ver = con.execute("SELECT vereador FROM pcrj_gabinetes WHERE gabinete_num=?", (gab,)).fetchone()
        vereador = ver["vereador"] if ver else f"Gabinete {gab}"
        total = con.execute(
            "SELECT COUNT(DISTINCT nome_norm) n FROM pcrj_camara_servidores WHERE gabinete_num=?",
            (gab,)).fetchone()["n"]
        vincs = _vinculos_do_gabinete(con, gab)
        secoes = [
            {"titulo": f"1. Gabinete {gab:02d} — {vereador}: nomeados que estão/estiveram na Prefeitura do Rio",
             "html": (f"<p>{len(vincs)} de {total} nomeados do gabinete têm indício de vínculo na "
                      f"Prefeitura (por nome; sem CPF é indício, não prova). "
                      f"'Requisitado'/'à disposição' = cessão (vínculo único), não acúmulo.</p>"
                      + _tabela_vinculos_gab(vincs) + _candidaturas_gab(con, gab))},
            {"titulo": f"2. Listagem completa do gabinete {gab:02d} ({total} nomeados)",
             "html": _tabela_listagem(con, gab)},
            {"titulo": "3. Índice por gabinete/vereador (nomeados com vínculo na Prefeitura)",
             "html": _indice_geral(con)},
        ]
        return {
            "classificacao": "CONFIDENCIAL — CONTROLE EXTERNO",
            "titulo": f"Gabinete {gab:02d} — Vereador {vereador}",
            "subtitulo": "Nomeados do gabinete e vínculos na Prefeitura do Rio — Módulo PCRJ",
            "metodologia": "Cruzamento nominal Câmara×Prefeitura (indício; verificar por CPF)",
            "score": len(vincs), "faixa": "ALTO" if len(vincs) >= 3 else "MÉDIO" if vincs else "BAIXO",
            "top_flags": [f"{total} nomeados", f"{len(vincs)} na Prefeitura"],
            "secoes": secoes,
            "proveniencia": [
                {"dado": "Servidores Câmara", "estado": "REAL",
                 "fonte": "transparencia.camara.rj.gov.br", "data": datetime.now().strftime("%d/%m/%Y")},
                {"dado": "Remuneração Prefeitura", "estado": "REAL",
                 "fonte": "contrachequeapi.rio.gov.br", "data": datetime.now().strftime("%d/%m/%Y")},
            ],
            "ressalva": "Indícios por nome para apuração por CPF no RH. Cessão/requisição não é "
                        "acúmulo. INDISPONÍVEL não é ausência de vínculo.",
        }
    finally:
        con.close()


async def gerar(gab: int, db_path=None) -> dict:
    from compliance_agent.reporting.render_html import render_html, html_to_pdf
    ctx = montar_ctx(gab, db_path)
    html = render_html(ctx)
    base = Path(__file__).resolve().parents[2] / "reports"
    base.mkdir(exist_ok=True)
    pdf = str(base / f"pcrj_gabinete_{gab:02d}_{datetime.now().date()}.pdf")
    await html_to_pdf(html, pdf)
    return {"pdf": pdf, "vereador": ctx["titulo"], "vinculos": ctx["score"]}


if __name__ == "__main__":
    import asyncio
    import sys
    g = int(sys.argv[1]) if len(sys.argv) > 1 else 32
    print(asyncio.run(gerar(g)))
