# -*- coding: utf-8 -*-
"""Capítulos NOVOS do dossiê completo (pedido do dono, 2026-07-20): cláusulas restritivas na
ÍNTEGRA, veredito de fachada explícito, suspeitas registradas e árvore/íntegra SEI dos processos.

Cada função devolve uma SEÇÃO no contrato do render_html ({titulo, html}) ou None quando não há
matéria — o montador do dossiê só anexa o que existe (INDISPONÍVEL ≠ 0). Prosa explicando cada
achado + tabelas; datas sempre que o dado tiver. Nenhum termo interno (gate de neutralidade).

Fontes (compliance.db): edital_clausula/clausula_veredito (cláusulas + vereditos do colegiado),
pcrj_contratos/pncp_resultado (o que o fornecedor venceu), fantasma_score (fachada); SEI em disco
(data/sei_arquivo/<processo>/manifest.json — árvore + textos).
"""
from __future__ import annotations

import html
import json
import re
import sqlite3
from pathlib import Path

from compliance_agent.editais.flags import grau_flag
from compliance_agent.knowledge.jurisprudencia import obter_sumula

_REPO = Path(__file__).resolve().parent.parent.parent
_ARQUIVO_SEI = _REPO / "data" / "sei_arquivo"


def _esc(s) -> str:
    return html.escape(str(s if s is not None else "")).strip()


def _dig(s) -> str:
    return re.sub(r"\D", "", s or "")


def _certames_do_fornecedor(con: sqlite3.Connection, cnpj: str) -> list[str]:
    """Certames (nº de controle PNCP) que este fornecedor venceu — via contrato (numero_compra) e
    via resultado homologado. Dedup, ordem estável."""
    cnpj = _dig(cnpj)
    vistos: list[str] = []
    seen = set()
    for sql, params in (
        ("SELECT DISTINCT ed.numero_controle_pncp FROM pcrj_contratos pc "
         "JOIN edital_documento ed ON (ed.numero_controle_pncp=pc.numero_compra "
         "OR ed.numero_controle_pncp=pc.numero_controle_pncp) "
         "WHERE replace(replace(replace(pc.fornecedor_documento,'.',''),'/',''),'-','')=?", (cnpj,)),
        ("SELECT DISTINCT certame FROM pncp_resultado "
         "WHERE replace(replace(replace(fornecedor_cnpj,'.',''),'/',''),'-','')=? "
         "AND (ordem_classificacao=1 OR ordem_classificacao IS NULL)", (cnpj,)),
    ):
        try:
            for (c,) in con.execute(sql, params):
                if c and c not in seen:
                    seen.add(c)
                    vistos.append(c)
        except sqlite3.OperationalError:
            continue
    return vistos


def secao_clausulas_restritivas(con: sqlite3.Connection, cnpj: str) -> dict | None:
    """Capítulo: a ÍNTEGRA de cada cláusula restritiva dos certames vencidos pelo fornecedor, com
    fundamento (súmula verbatim), grau de flag e o veredito do colegiado quando houver."""
    certames = _certames_do_fornecedor(con, cnpj)
    if not certames:
        return None
    marks = ",".join("?" for _ in certames)
    linhas = con.execute(
        f"SELECT ec.numero_controle_pncp, ec.subtipo, ec.eixo, ec.texto, ec.trecho_fonte, "
        f"cv.score_final, cv.veredito, cv.sumula, cv.raridade "
        f"FROM edital_clausula ec "
        f"LEFT JOIN clausula_veredito cv ON cv.clausula_id = ec.id "
        f"WHERE ec.numero_controle_pncp IN ({marks}) AND ec.texto IS NOT NULL "
        f"ORDER BY COALESCE(cv.score_final,0) DESC, ec.numero_controle_pncp", certames).fetchall()
    if not linhas:
        return None

    blocos = ["<p>Este capítulo transcreve, <b>na íntegra</b>, as cláusulas de habilitação e "
              "julgamento que restringem a competição nos certames vencidos por este fornecedor. "
              "Cada cláusula vem com seu fundamento normativo (súmula transcrita literalmente), o "
              "grau de certeza do indício e, quando o colegiado analítico já se pronunciou, o "
              "veredito e o escore. <b>Indício não é acusação</b>: presume-se a legitimidade dos atos.</p>"]
    n_viciada = 0
    for r in linhas:
        subtipo, eixo, texto, fonte = r[1], r[2], r[3], r[4]
        score, veredito, sumula_nome, raridade = r[5], r[6], r[7], r[8]
        # grau de flag: com veredito do colegiado (LLM) vira suspeito/forte; determinístico se score alto
        origem = "llm" if score is not None else "deterministico"
        gf = grau_flag(origem=origem, score=(score / 10.0 if score is not None else None),
                       familias_convergentes=1 if (raridade or 0) >= 0.7 else 0)
        if gf["grau"] in ("A", "B"):
            n_viciada += 1
        sm = obter_sumula(sumula_nome or "")
        fund = (f"<div class='fund'><b>Fundamento:</b> {_esc(sm['numero'])} — “{_esc(sm['texto'])}” "
                f"({_esc(sm['orgao'])})</div>" if sm else
                (f"<div class='fund'><b>Fundamento:</b> {_esc(sumula_nome)}</div>" if sumula_nome else ""))
        vered = (f" · veredito do colegiado: <b>{_esc(veredito)}</b> ({score}/10)"
                 if score is not None else "")
        rar = (f" · rara entre os pares ({int(raridade * 100)}% dos editais do mesmo objeto NÃO a exigem)"
               if raridade is not None else "")
        blocos.append(
            f"<div class='clausula'>"
            f"<div class='chd'>{gf['emoji']} <b>{_esc(gf['rotulo'])}</b> — {_esc(subtipo)} "
            f"<span class='dim'>({_esc(eixo)}; certame {_esc(r[0])}{rar}{vered})</span></div>"
            f"<blockquote>{_esc(texto)}</blockquote>"
            + (f"<div class='fonte dim'>Trecho do documento: “{_esc(fonte)}”</div>" if fonte else "")
            + fund + "</div>")
    cabecalho = (f"<p><b>{len(linhas)}</b> cláusula(s) restritiva(s) transcrita(s); "
                 f"<b>{n_viciada}</b> com grau CERTO/FORTE (podem fundamentar peça).</p>")
    return {"titulo": "Cláusulas restritivas — íntegra e fundamento",
            "html": cabecalho + "\n".join(blocos)}


def secao_veredito_fachada(d: dict) -> dict | None:
    """Veredito EXPLÍCITO de empresa-fachada, a partir dos red flags já coletados pelo dossiê 360
    (d['red_flags']/d['fantasma']). Diz claramente se há perfil de fachada e por quê."""
    fant = d.get("fantasma") or {}
    flags = d.get("red_flags") or d.get("flags") or []
    score = fant.get("score")
    sinais = fant.get("sinais") or fant.get("sinais_json") or []
    if isinstance(sinais, str):
        try:
            sinais = json.loads(sinais)
        except (ValueError, TypeError):
            sinais = [sinais]
    if score is None and not sinais and not flags:
        return {"titulo": "Veredito de empresa-fachada",
                "html": "<p class='indisp'>INDISPONÍVEL — sem sinais cadastrais suficientes para o "
                        "juízo de fachada (INDISPONÍVEL ≠ ausência de risco). Nada foi fabricado.</p>"}
    classe = (fant.get("classificacao")
              or ("FORTE" if (score or 0) >= 70 else "MODERADO" if (score or 0) >= 40 else "FRACO"))
    itens = "".join(f"<li>{_esc(s)}</li>" for s in sinais[:12]) or "<li>—</li>"
    prosa = (f"<p>O perfil cadastral e financeiro deste fornecedor foi submetido a oito sinais "
             f"objetivos de empresa-fachada (situação na Receita, capital frente ao recebido, "
             f"endereço, idade do CNPJ, quadro societário, CNAE, sanções). O escore consolidado é "
             f"<b>{score if score is not None else 'INDISPONÍVEL'}/100</b> — perfil de fachada "
             f"<b>{_esc(classe)}</b>. Os sinais acesos:</p><ul>{itens}</ul>"
             "<p>Escore alto é <b>indício de interposição/laranja</b> a confirmar (endereço real, "
             "capacidade operacional, QSA), não prova. Escore baixo não inocenta — apenas não acende.</p>")
    return {"titulo": "Veredito de empresa-fachada", "html": prosa}


def secao_suspeitas(con: sqlite3.Connection, cnpj: str, d: dict) -> dict | None:
    """Registra as SUSPEITAS (grau SUSPEITO / indícios que não fecham) — o dono pediu que suspeita
    também tenha registro, não só o que é certo."""
    itens: list[str] = []
    # cláusulas de grau suspeito (colegiado <7 ou determinístico isolado)
    certames = _certames_do_fornecedor(con, cnpj)
    if certames:
        marks = ",".join("?" for _ in certames)
        for r in con.execute(
                f"SELECT ec.subtipo, cv.score_final, ec.numero_controle_pncp FROM edital_clausula ec "
                f"JOIN clausula_veredito cv ON cv.clausula_id=ec.id "
                f"WHERE ec.numero_controle_pncp IN ({marks}) AND cv.score_final BETWEEN 1 AND 6",
                certames).fetchall():
            itens.append(f"Cláusula <b>{_esc(r[0])}</b> no certame {_esc(r[2])}: colegiado {r[1]}/10 — "
                         "abaixo do limiar de direcionamento, mas fora do padrão (acompanhar).")
    # red flags de gravidade média do dossiê
    for f in (d.get("red_flags") or [])[:8]:
        obs = f.get("obs") if isinstance(f, dict) else str(f)
        grav = f.get("grav") if isinstance(f, dict) else None
        if grav is not None and grav <= 2 and obs:
            itens.append(_esc(obs)[:400])
    if not itens:
        return None
    return {"titulo": "Suspeitas registradas (indícios que ainda não fecham)",
            "html": ("<p>Nem todo indício alcança o grau de certeza para fundamentar uma peça. Os "
                     "pontos abaixo <b>não são acusação</b> — ficam registrados para diligência e "
                     "acompanhamento, porque o padrão pode se confirmar com novos dados.</p><ul>"
                     + "".join(f"<li>{i}</li>" for i in itens) + "</ul>")}


def _slug_processo(numero: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in (numero or "").replace("SEI-", "")).strip("_")


def secao_sei_arvore(processos_sei: list[str], max_docs_por_processo: int = 40,
                     max_recorte_chars: int = 1200) -> dict | None:
    """Capítulo: a ÁRVORE do SEI (lista de documentos por processo, com fase/tipo/datas) e RECORTES
    da íntegra dos documentos-chave (parecer, ata, edital, despacho decisório). Lê o arquivo compacto
    em data/sei_arquivo (regra da casa: arquivo antes de browser). Sem arquivo → None (honesto)."""
    blocos: list[str] = []
    tipos_chave = {"parecer", "julgamento", "edital", "despacho", "homologacao", "orgao_controle"}
    for numero in processos_sei:
        pdir = _ARQUIVO_SEI / _slug_processo(numero)
        man = pdir / "manifest.json"
        if not man.exists():
            continue
        try:
            j = json.loads(man.read_text())
        except (ValueError, OSError):
            continue
        docs = j.get("docs") or []
        if not docs:
            continue
        arvore = ["<table class='tabela'><tr><th>#</th><th>Documento</th><th>Fase</th><th>Tipo</th></tr>"]
        recortes = []
        for i, doc in enumerate(docs[:max_docs_por_processo]):
            arvore.append(f"<tr><td>{doc.get('i', i)}</td><td>{_esc(doc.get('titulo'))}</td>"
                          f"<td>{_esc(doc.get('fase'))}</td><td>{_esc(doc.get('tipo'))}</td></tr>")
            if doc.get("tipo") in tipos_chave and doc.get("texto"):
                f = pdir / doc["texto"]
                if f.exists():
                    try:
                        txt = html.unescape(f.read_text(errors="replace")).strip()
                    except OSError:
                        continue
                    if txt:
                        recortes.append(
                            f"<div class='recorte'><b>{_esc(doc.get('titulo'))}</b> "
                            f"<span class='dim'>({_esc(doc.get('tipo'))})</span>"
                            f"<blockquote>{_esc(txt[:max_recorte_chars])}"
                            + ("…" if len(txt) > max_recorte_chars else "") + "</blockquote></div>")
        arvore.append("</table>")
        blocos.append(f"<h3>Processo {_esc(numero)}</h3>"
                      f"<p class='dim'>{len(docs)} documento(s) na árvore.</p>"
                      + "\n".join(arvore)
                      + ("<h4>Recortes da íntegra (documentos-chave)</h4>" + "\n".join(recortes)
                         if recortes else ""))
    if not blocos:
        return None
    return {"titulo": "Processos administrativos — árvore do SEI e recortes da íntegra",
            "html": ("<p>Abaixo, a <b>árvore documental</b> de cada processo administrativo ligado ao "
                     "fornecedor (a sequência de peças, com fase e tipo) e, na sequência, <b>recortes "
                     "da íntegra</b> dos documentos-chave — parecer jurídico, ata de julgamento, edital, "
                     "despacho decisório. A leitura vem do arquivo documental; o texto é transcrito "
                     "como está no processo.</p>" + "\n".join(blocos))}
