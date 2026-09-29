# -*- coding: utf-8 -*-
"""Lista NOME A NOME de todos (com vínculo Câmara/Prefeitura) que já foram candidatos.

Reúne, por pessoa (sem CPF → indício por nome):
  - candidaturas de servidores da CÂMARA casados no TSE (`tse_candidatura`);
  - candidaturas de COMISSIONADOS da Prefeitura casados no TSE (`pcrj_comissionado_candidato`,
    cruzamento inverso all-RJ).
Cada pessoa: vínculo(s) + todas as candidaturas (ano, cidade, cargo, partido; flags de
outra cidade e antes/depois da nomeação). Ordem alfabética.

OSs (Organizações Sociais): NÃO entram — os RDP da CODESP são agregados, sem nomes de
empregados (ver `os_panorama.py` / memória). Impossível pela fonte pública.
"""
from __future__ import annotations

import html
import sqlite3
from datetime import datetime
from pathlib import Path

from compliance_agent.pcrj import db as _db


def _e(x) -> str:
    return html.escape(str(x or ""))


def _coletar(con) -> dict[str, dict]:
    pessoas: dict[str, dict] = {}

    def _get(nn, nome):
        p = pessoas.get(nn)
        if not p:
            p = {"nome": nome, "vinculos": set(), "cands": []}
            pessoas[nn] = p
        return p

    # ingresso na Câmara (p/ flag antes/depois)
    ingresso = {r["nome_norm"]: r["a"] for r in con.execute(
        "SELECT nome_norm, MIN(ano_ingresso) a FROM pcrj_camara_servidores GROUP BY nome_norm")}

    # A) candidatos com vínculo na CÂMARA
    for r in con.execute("SELECT * FROM tse_candidatura ORDER BY nome_tse, ano"):
        nn = r["nome_norm"]
        p = _get(nn, r["nome_tse"])
        gab = con.execute(
            "SELECT GROUP_CONCAT(DISTINCT gabinete_num) g FROM pcrj_camara_servidores "
            "WHERE nome_norm=? AND gabinete_num IS NOT NULL", (nn,)).fetchone()["g"]
        p["vinculos"].add(f"Câmara ({'gab ' + gab if gab else 'admin'})")
        if con.execute("SELECT 1 FROM pcrj_vinculo_cruzado WHERE nome_norm=? "
                       "AND confianca='indicio_nome_unico' LIMIT 1", (nn,)).fetchone():
            p["vinculos"].add("Prefeitura (vínculo)")
        p["cands"].append({"ano": r["ano"], "cidade": r["municipio"], "cargo": r["cargo"],
                           "partido": r["partido"], "outra": r["outra_cidade"],
                           "ref": ingresso.get(nn)})

    # B) candidatos que são COMISSIONADOS da Prefeitura (inverso all-RJ)
    try:
        for r in con.execute("SELECT * FROM pcrj_comissionado_candidato ORDER BY nome_pcrj"):
            nn = r["nome_norm"]
            p = _get(nn, r["nome_pcrj"])
            p["vinculos"].add(f"Prefeitura comissionado ({_e(r['cargo_pcrj'])})")
            if not any(c["ano"] == r["cand_ano"] and c["cidade"] == r["cand_cidade"]
                       for c in p["cands"]):
                p["cands"].append({"ano": r["cand_ano"], "cidade": r["cand_cidade"],
                                   "cargo": r["cand_cargo"], "partido": "",
                                   "outra": 1 if (r["cand_cidade"] or "").upper() != "RIO DE JANEIRO"
                                   else 0, "ref": None})
    except Exception:
        pass
    return pessoas


def _cand_txt(c: dict) -> str:
    q = ""
    if c.get("ref") and c["ano"]:
        q = " · antes da nomeação" if c["ano"] < c["ref"] else (
            " · depois da nomeação" if c["ano"] > c["ref"] else " · no ano da nomeação")
    fora = " [OUTRA CIDADE]" if c["outra"] else ""
    part = f", {c['partido']}" if c.get("partido") else ""
    return f"{_e((c['cargo'] or '').lower())} — {_e((c['cidade'] or '').title())} ({c['ano']}{part}){fora}{q}"


def _situacao_por_matricula(con, ultima: str | None) -> dict[str, dict]:
    """{nome_norm: situação} para os comissionados cruzados, pela MATRÍCULA (exata) — uma varredura só da folha.
    28/09/2026: por nome, "Rogério da Silva Ferreira" (matrícula 0562504) casava com um homônimo de matrícula
    2817179 — 1.228 dos 3.718 nomes têm 2+ matrículas na folha; atribuir situação por nome seria inventar."""
    mats: dict[str, str] = {}
    for nn, m in con.execute("SELECT nome_norm, matricula FROM pcrj_comissionado_candidato WHERE matricula IS NOT NULL"):
        mats[str(m).lstrip("0")] = nn
    if not mats:
        return {}
    num = "CAST(replace(replace(remun_bruta,'.',''),',','.') AS REAL)"
    por: dict[str, dict] = {}
    for mat, comp, orgao, sigla, bruto in con.execute(
            f"SELECT ltrim(matricula,'0'), competencia, orgao, sigla_ua, {num} FROM pcrj_folha_pref "
            f"WHERE ltrim(matricula,'0') IN ({','.join('?' * len(mats))})", list(mats)):
        nn = mats.get(mat)
        d = por.setdefault(nn, {"primeira": comp, "ultima": comp, "orgao": None, "bruto": 0.0, "fonte": "matrícula"})
        d["primeira"] = min(d["primeira"], comp)
        if comp > d["ultima"]:
            d["ultima"], d["orgao"], d["bruto"] = comp, orgao or sigla, bruto or 0.0
        elif comp == d["ultima"]:
            d["orgao"] = d["orgao"] or orgao or sigla
            d["bruto"] = (d["bruto"] or 0.0) + (bruto or 0.0)
    for d in por.values():
        d["ativo"] = d["ultima"] == ultima
    return por


def _situacao_folha(con, nn: str, ultima: str | None) -> dict | None:
    """Situação na folha em BLOCO da Prefeitura (pcrj_folha_pref): 1ª/última competência, órgão e bruto na última.
    O cruzamento com o TSE parou no tempo; a folha é mensal — é ela que diz se a pessoa AINDA está lá."""
    # por NOME só quando o nome é ÚNICO na folha (uma matrícula) — senão é homônimo e a situação não se atribui
    if con.execute("SELECT count(DISTINCT matricula) FROM pcrj_folha_pref WHERE nome_norm=?", (nn,)).fetchone()[0] != 1:
        return {"homonimo": True}
    r = con.execute("SELECT MIN(competencia), MAX(competencia) FROM pcrj_folha_pref WHERE nome_norm=?", (nn,)).fetchone()
    if not r or not r[1]:
        return None
    # remun_bruta é TEXTO pt-BR ("1897,94"): ordenar/somar só convertido
    num = "CAST(replace(replace(remun_bruta,'.',''),',','.') AS REAL)"
    u = con.execute(f"SELECT orgao, sigla_ua, SUM({num}) FROM pcrj_folha_pref WHERE nome_norm=? AND competencia=? "
                    "GROUP BY orgao, sigla_ua ORDER BY 3 DESC LIMIT 1", (nn, r[1])).fetchone()
    return {"primeira": r[0], "ultima": r[1], "ativo": r[1] == ultima, "orgao": (u[0] or u[1]) if u else None,
            "bruto": u[2] if u else None, "fonte": "nome único na folha"}


_PARTICULAS = {"da", "de", "do", "dos", "das", "e", "d"}


def _comp(c: str | None) -> str:
    return f"{c[4:6]}/{c[:4]}" if c and len(c) == 6 else "—"


def _brl(v) -> str:
    return "R$ " + f"{float(v or 0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def montar_ctx(db_path=None) -> dict:
    con = _db.conectar(db_path)
    try:
        pessoas = _coletar(con)
        try:
            ultima = con.execute("SELECT MAX(competencia) FROM pcrj_folha_pref").fetchone()[0]
            por_mat = _situacao_por_matricula(con, ultima)
            # palavras mais comuns dos nomes da folha (distintos, competência mais recente): "ANTONIO CARLOS DA SILVA"
            # tem 3 palavras significativas, todas entre as mais frequentes — não distingue ninguém
            from collections import Counter
            cont = Counter(w for (n,) in con.execute("SELECT DISTINCT nome_norm FROM pcrj_folha_pref WHERE competencia=?",
                                                     (ultima,)) for w in set((n or "").split()) if w.lower() not in _PARTICULAS)
            freq_top = {w for w, _ in cont.most_common(200)}
            situ = {nn: por_mat.get(nn) or _situacao_folha(con, nn, ultima) for nn in pessoas}
        except sqlite3.Error:                              # sem a folha em bloco: coluna declara INDISPONÍVEL
            ultima, situ, freq_top = None, {}, set()
        eleitos = {r[0] for r in con.execute("SELECT nome_norm FROM tse_candidatura WHERE eleito=1 OR "
                                             "upper(resultado) LIKE 'ELEITO%'")} if pessoas else set()
    finally:
        con.close()
    linhas = []
    n_fora = n_ativos = n_eleitos = 0
    confianca = {"ALTA": 0, "MÉDIA": 0, "BAIXA": 0}
    n_fora_baixa = 0
    por_cidade: dict[str, list[str]] = {}
    for nn in sorted(pessoas, key=lambda k: pessoas[k]["nome"]):
        p = pessoas[nn]
        cands = sorted(p["cands"], key=lambda c: (c["ano"] or 0))
        sf = situ.get(nn)
        # confiança = a MENOR entre (i) identificar a pessoa na Prefeitura e (ii) o nome distinguir entre candidatos do TSE
        # (sem o universo do TSE, a medida objetiva é o nº de palavras SIGNIFICATIVAS: "Antonio Carlos da Silva" = 3)
        n_sig = len([w for w in nn.split() if w.lower() not in _PARTICULAS])
        c_pref = 2 if sf and sf.get("fonte") == "matrícula" else 1 if sf and sf.get("fonte") == "nome único na folha" else 0
        comuns = sum(1 for w in nn.split() if w.lower() not in _PARTICULAS and w in freq_top)
        c_nome = 2 if n_sig >= 4 else 1 if (n_sig == 3 and comuns < 2) else 0
        conf = ("BAIXA", "MÉDIA", "ALTA")[min(c_pref, c_nome)]
        confianca[conf] += 1
        if any(c["outra"] for c in cands):
            if conf == "BAIXA":
                n_fora_baixa += 1
            else:
                n_fora += 1
                for c in cands:
                    if c["outra"]:
                        por_cidade.setdefault((c["cidade"] or "?").title(), []).append(p["nome"])
        if nn in eleitos:
            n_eleitos += 1
        if sf and sf.get("ativo") and conf != "BAIXA":
            n_ativos += 1
        if not situ:
            folha = "<span class='dim'>INDISPONÍVEL</span>"
        elif not sf:
            folha = "<span class='dim'>não localizado na folha em bloco</span>"
        elif sf.get("homonimo"):
            folha = "<span class='dim'>nome com 2+ matrículas na folha — situação NÃO atribuída (homônimo)</span>"
        else:
            folha = (f"<b>{'na folha em ' + _comp(sf['ultima']) if sf['ativo'] else 'saiu — última ' + _comp(sf['ultima'])}</b>"
                     f"<br>{_e(sf['orgao'] or '')}<br>{_brl(sf['bruto'])} bruto · desde {_comp(sf['primeira'])}"
                     f"<br><span class='dim'>por {_e(sf['fonte'])}</span>")
        folha += f"<br><span class='flag' style='background:#eee;color:#555'>confiança {conf}</span>"
        homon = " <span class='flag' style='background:#eee;color:#777'>homônimo provável</span>" \
            if len({c["cidade"] for c in cands}) >= 3 else ""
        eleito = " <span class='flag'>eleito</span>" if nn in eleitos else ""
        linhas.append((("ALTA", "MÉDIA", "BAIXA").index(conf), p["nome"],
            f"<tr><td>{_e(p['nome'])}{homon}{eleito}</td>"
            f"<td>{_e('; '.join(sorted(p['vinculos'])))}</td>"
            f"<td>{folha}</td>"
            f"<td>{'<br>'.join(_cand_txt(c) for c in cands)}</td></tr>"))
    linhas.sort(key=lambda x: (x[0], x[1]))            # ALTA → MÉDIA → BAIXA, alfabética dentro de cada faixa
    tabela = ("<table><tr><th>Nome</th><th>Vínculo(s)</th><th>Folha da Prefeitura (situação atual)</th>"
              "<th>Candidatura(s) — cargo, cidade (ano, partido), antes/depois</th></tr>"
              + "".join(x[2] for x in linhas) + "</table>")
    sumario = (f"<table><tr><td><b>Total nome a nome (com vínculo Câmara/Prefeitura)</b></td>"
               f"<td style='text-align:right'><b>{len(pessoas)}</b></td></tr>"
               f"<tr><td>confiança ALTA (matrícula + nome de 4+ palavras) · MÉDIA · BAIXA (homônimo possível)</td>"
               f"<td style='text-align:right'>{confianca['ALTA']} · {confianca['MÉDIA']} · {confianca['BAIXA']}</td></tr>"
               f"<tr><td>ainda na folha da Prefeitura em {_comp(ultima)} (confiança ALTA/MÉDIA)</td>"
               f"<td style='text-align:right'>{n_ativos}</td></tr>"
               f"<tr><td>candidatos em OUTRA cidade do RJ (confiança ALTA/MÉDIA · BAIXA fora da seção 2)</td>"
               f"<td style='text-align:right'>{n_fora} · {n_fora_baixa}</td></tr>"
               f"<tr><td>eleitos em alguma candidatura</td><td style='text-align:right'>{n_eleitos}</td></tr></table>")
    cidades = ("<table><tr><th>Cidade da candidatura</th><th style='text-align:right'>Pessoas</th><th>Nomes</th></tr>"
               + "".join(f"<tr><td>{_e(c)}</td><td style='text-align:right'>{len(set(ns))}</td>"
                         f"<td>{_e('; '.join(sorted(set(ns))))}</td></tr>"
                         for c, ns in sorted(por_cidade.items(), key=lambda x: -len(set(x[1]))))
               + "</table>")
    return {
        "classificacao": "CONFIDENCIAL — CONTROLE EXTERNO",
        "titulo": "Nome a nome — vinculados à Câmara/Prefeitura que já foram candidatos",
        "subtitulo": "Todas as candidaturas por pessoa (TSE-RJ) — Módulo PCRJ",
        "metodologia": "Cruzamento nominal Câmara/Prefeitura × TSE (indício; verificar por CPF)",
        # o score do modelo é 0–100: era len(pessoas) e a capa dizia "3718/100 (ALTO)" (28/09/2026)
        "score": round(100 * (confianca["ALTA"] + confianca["MÉDIA"]) / max(1, len(pessoas))),
        "rotulo_score": "Nomes com identificação confiável (% alta+média)",
        "total_pessoas": len(pessoas), "confianca": confianca, "fora_alta_media": n_fora,
        "faixa": "MÉDIO",
        "top_flags": [f"{len(pessoas)} pessoas", f"{confianca['ALTA']} por matrícula", f"{n_fora} outra cidade (alta/média)"],
        "secoes": [
            {"titulo": "1. Sumário", "html": sumario},
            {"titulo": f"2. Cruzamento com outras cidades ({len(por_cidade)} cidades)", "html": cidades},
            {"titulo": f"3. Lista nome a nome ({len(pessoas)}) — por confiança, depois alfabética", "html": tabela},
            {"titulo": "4. Método, cobertura e limitações", "html":
             "<p>Sem CPF → casamento por nome é indício (homônimo em ≥3 cidades sinalizado). "
             "Fontes: servidores da Câmara e comissionados da Prefeitura casados nas candidaturas "
             "do TSE (RJ, 2012-2024). A <b>situação atual</b> vem da folha mensal em bloco da Prefeitura "
             f"(contrachequedoc.rio.gov.br), competência mais recente {_comp(ultima)}.</p>"
             "<p><b>Cobertura do cruzamento:</b> candidatos de TODO o RJ (51.755, eleições 2016-2024) × comissionados "
             "na competência mais recente disponível em jul/2026 e em jun/2024 e jun/2022; candidatos do município do Rio × folha MÊS A MÊS "
             "de 01/2021 a 12/2023. <b>De 01/2024 a 09/2026 o cruzamento mês a mês não rodou</b>: desde set/2026 o TSE "
             "recusa (403, Akamai) o download para os servidores em nuvem da casa, e o coletor, sem avisar, marcava os "
             "meses como feitos com zero candidatos — corrigido; os meses voltaram à fila. As candidaturas de "
             "<b>2026</b> (eleição geral em curso) ainda NÃO estão cruzadas pela mesma razão.</p>"
             "<p><b>OSs (Organizações Sociais) NÃO entram nominalmente</b>: os relatórios da CODESP são agregados, "
             "sem nomes de empregados — impossível pela fonte pública.</p>"}],
        "proveniencia": [{"dado": "Câmara/Prefeitura×TSE", "estado": "REAL",
                          "fonte": "transparencia.camara / contrachequeapi / TSE (RJ)",
                          "data": datetime.now().strftime("%d/%m/%Y")}],
        "ressalva": "Indícios por nome para apuração por CPF. OSs não disponíveis nominalmente.",
    }


async def gerar(db_path=None) -> dict:
    from compliance_agent.reporting.render_html import html_to_pdf, render_html
    ctx = montar_ctx(db_path)
    h = render_html(ctx)
    base = Path(__file__).resolve().parents[2] / "reports"
    base.mkdir(exist_ok=True)
    pdf = str(base / f"pcrj_candidatos_nominais_{datetime.now().date()}.pdf")
    await html_to_pdf(h, pdf)
    return {"pdf": pdf, "total": ctx["total_pessoas"], "confianca": ctx["confianca"], "fora": ctx["fora_alta_media"]}


if __name__ == "__main__":
    import asyncio
    print(asyncio.run(gerar()))
