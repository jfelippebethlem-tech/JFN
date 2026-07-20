# -*- coding: utf-8 -*-
"""Dossiê 360 — perfil 1-comando. Perfil 1-comando agregando todas as fontes reais.

Une, sobre um alvo (CNPJ): cadastro (BrasilAPI), sanções (CEIS/CNEP), rede (Grafo de Poder),
OB/contratos, conflito doador↔contrato (TSE), e o score de convergência decomponível.
Gera um PDF compacto. Honesto: cada fonte que falhar vira INDISPONÍVEL — nunca fabrica.

Invariante: indícios para apuração; presunção de legitimidade; CPF mascarado (LGPD).
"""
from __future__ import annotations

import logging
import re
import sqlite3
from datetime import datetime
from pathlib import Path

from fpdf.enums import XPos, YPos

from compliance_agent.database.models import _resolver_db

logger = logging.getLogger(__name__)

_REPORTS = Path(__file__).resolve().parent.parent / "reports"


def _digits(s) -> str:
    return re.sub(r"\D", "", str(s or ""))


def _resumo_ob(cnpj: str) -> dict:
    """Total pago, nº de OBs e concentração por UG (OB = pagamento)."""
    _DB = _resolver_db()
    if not _DB.exists():
        return {"_nota": "INDISPONÍVEL: compliance.db ausente"}
    con = sqlite3.connect(str(_DB))
    try:
        rows = con.execute(
            "SELECT ug_codigo, MAX(ug_nome), SUM(valor), COUNT(*) FROM ordens_bancarias "
            "WHERE REPLACE(REPLACE(REPLACE(favorecido_cpf,'.',''),'/',''),'-','')=? "
            "GROUP BY ug_codigo ORDER BY SUM(valor) DESC", (cnpj,)).fetchall()
    finally:
        con.close()
    if not rows:
        return {"total_ob": 0.0, "n_ob": 0, "ugs": [], "concentracao_top_ug": None}
    total = sum(r[2] or 0 for r in rows)
    top = (rows[0][2] or 0) / total if total else 0
    from compliance_agent import ugs as _ugs  # nome canônico da UG (ITERJ p/ 133100), igual aos relatórios
    return {
        "total_ob": round(total, 2),
        "n_ob": sum(r[3] for r in rows),
        "n_ugs": len(rows),
        "concentracao_top_ug": round(top, 3),
        "ugs": [{"ug": r[0], "nome": _ugs.nome_canonico(str(r[0]), fallback="") or r[1],
                 "total": round(r[2] or 0, 2)} for r in rows[:5]],
    }


def _red_flags_estruturais(cnpj: str, cadastro: dict) -> list[dict]:
    """Sinais estruturais de fachada/laranja que o dossiê passa a convergir (mesma lógica do
    /relatorio RF-04/RF-05 e do Lex R6/R11), reusando os helpers — honesto, indício a verificar."""
    out: list[dict] = []
    cad = cadastro or {}
    # CNAE/atividade × objeto contratado (TCE-RJ) — atividade-fim incompatível.
    cnae = cad.get("cnae_principal") or cad.get("atividade") or ""
    try:
        from compliance_agent.reporting.inteligencia import _termos_significativos
        from compliance_agent.collectors.tcerj_aberto import contratos_de_fornecedor
        objs = [(c.get("objeto") or "").strip() for c in contratos_de_fornecedor(cnpj, limite=60)]
        objs = [o for o in objs if len(o) >= 12]
        if cnae and objs:
            tc, to_ = _termos_significativos(cnae), _termos_significativos(" ".join(objs))
            if tc and to_ and not (tc & to_):
                out.append({"flag": "cnae_objeto_incompativel",
                            "obs": f"CNAE/atividade (“{cnae[:60]}”) sem aderência ao objeto contratado "
                                   f"(ex.: “{objs[0][:60]}…”) — possível empresa de prateleira/fachada."})
    except Exception as exc:  # noqa: BLE001
        logger.warning("red flag CNAE×objeto (TCE-RJ) falhou p/ CNPJ %s: %s", cnpj, exc)
    # Troca de controle societário posterior a receita pública (socios data_entrada × OBs antes).
    try:
        socios = cad.get("socios") or []
        entradas = [s.get("data_entrada") or "" for s in socios]
        entradas = [d for d in entradas if len(d) == 10 and d.count("-") == 2]
        _DB = _resolver_db()
        if entradas and _DB.exists():
            recente = max(entradas)
            con = sqlite3.connect(str(_DB))
            try:
                norm = "REPLACE(REPLACE(REPLACE(favorecido_cpf,'.',''),'/',''),'-','')"
                antes = con.execute(
                    f"SELECT COUNT(*), COALESCE(SUM(valor),0) FROM ordens_bancarias WHERE {norm}=? "
                    "AND data_pagamento IS NOT NULL AND length(data_pagamento)=10 AND data_pagamento<?",
                    (cnpj, recente)).fetchone()
                tg = con.execute(f"SELECT COALESCE(SUM(valor),0) FROM ordens_bancarias WHERE {norm}=?",
                                 (cnpj,)).fetchone()[0] or 0
            finally:
                con.close()
            n_antes, tot_antes = antes[0], antes[1] or 0
            share = (tot_antes / tg * 100) if tg else 0
            if tot_antes >= 1_000_000 and share >= 15:
                out.append({"flag": "troca_controle_pos_receita",
                            "obs": f"Ingresso no QSA em {recente} posterior a R$ {tot_antes:,.2f} já pagos "
                                   f"({n_antes} OBs, {share:.0f}%) — sucessão/interposição a verificar."})
    except Exception as exc:  # noqa: BLE001
        logger.warning("red flag troca de controle×OB falhou p/ CNPJ %s: %s", cnpj, exc)
    return out


async def dossie(alvo: str, gerar_pdf: bool = True) -> dict:
    """Monta o dossiê 360 de um CNPJ. Retorna {ok, alvo, cadastro, sancoes, ob, conflito,
    rede, score, path_pdf, _fontes}. Cada bloco é best-effort e honesto (INDISPONÍVEL)."""
    cnpj = _digits(alvo)
    if len(cnpj) != 14:
        return {"ok": False, "erro": "informe um CNPJ (14 dígitos)"}

    d: dict = {"ok": True, "alvo": cnpj, "gerado_em": datetime.now().isoformat(timespec="seconds")}

    # 1) cadastro (BrasilAPI)
    try:
        from compliance_agent.collectors.cnpj import buscar_cnpj
        d["cadastro"] = await buscar_cnpj(cnpj)
    except Exception as e:  # noqa: BLE001
        d["cadastro"] = {"_nota": f"INDISPONÍVEL: {e}"}

    # 2) sanções CEIS/CNEP — honesto: só pontua se VERIFICADO (INDISPONÍVEL ≠ "limpo")
    sancionado = False
    sancao_verificada = False
    try:
        from compliance_agent.collectors.ceis import verificar_sancao
        d["sancoes"] = await verificar_sancao(cnpj)
        sancao_verificada = bool(d["sancoes"].get("verificado"))
        sancionado = sancao_verificada and bool(d["sancoes"].get("sancionado"))
    except Exception as e:  # noqa: BLE001
        d["sancoes"] = {"_nota": f"INDISPONÍVEL: {e}", "verificado": False}

    # (OpenSanctions/OCCRP Aleph removidos por decisão do dono 2026-07-18: exigiam chave grátis que
    #  nunca foi provida e geravam INDISPONÍVEL em toda perícia. Sanção doméstica CEIS/CNEP acima basta.)

    # 2d) Mídia adversa (fontes abertas, KEYLESS via GDELT) — DD §9
    try:
        from compliance_agent.enrich.midia_adversa import varrer as _midia
        nome_alvo = (d.get("cadastro") or {}).get("razao_social") or alvo
        d["midia_adversa"] = _midia(nome_alvo, cnpj)
    except Exception as exc:  # noqa: BLE001
        logger.warning("seção mídia adversa (GDELT) do dossiê indisponível p/ CNPJ %s: %s", cnpj, exc)

    # 2e) Pistas de investigação hospedada (Max Intel/OSINT-Brazuca/RedeCNPJ…) — deep-links MANUAIS
    try:
        from compliance_agent.providers import lookup as _plookup
        nome_alvo = (d.get("cadastro") or {}).get("razao_social") or alvo
        d["links_investigacao"] = (_plookup("links", nome=nome_alvo, cnpj=cnpj).dados or {}).get("links", [])
    except Exception as exc:  # noqa: BLE001
        logger.debug("links de investigação hospedada indisponíveis p/ CNPJ %s: %s", cnpj, exc)

    # 3) OB / contratos (dado interno)
    d["ob"] = _resumo_ob(cnpj)

    # 4) conflito doador↔contrato (TSE)
    try:
        from compliance_agent.lex_conflito import conflito
        c = conflito(cnpj=cnpj, limite=20)
        d["conflito"] = {"n": len(c.get("rede", [])), "rede": c.get("rede", [])[:10],
                         "_nota": c.get("_nota")}
    except Exception as e:  # noqa: BLE001
        d["conflito"] = {"_nota": f"INDISPONÍVEL: {e}"}

    # 5) rede (Grafo de Poder)
    try:
        from compliance_agent.grafo_poder import vizinhanca
        r = vizinhanca(cnpj, saltos=2)
        d["rede"] = {"n_nos": r.get("n_nos", 0), "n_arestas": len(r.get("arestas", [])),
                     "nos": r.get("nos", [])[:30]}
    except Exception as e:  # noqa: BLE001
        d["rede"] = {"_nota": f"INDISPONÍVEL: {e}"}

    # 5b) red flags ESTRUTURAIS (fachada/laranja) — mesma lógica do /relatorio e do Lex
    d["red_flags_estruturais"] = _red_flags_estruturais(cnpj, d.get("cadastro") or {})

    # 6) score de convergência (a partir dos sinais reunidos)
    sinais = {
        "conflito_doador": bool(d.get("conflito", {}).get("n")),
        "concentracao_orgao": 1.0 if (d["ob"].get("concentracao_top_ug") or 0) >= 0.6 else 0.0,
        # cada red flag estrutural conta como um red flag de edital/TR (teto interno de 3 no score)
        "red_flag_edital": len(d["red_flags_estruturais"]),
    }
    if sancao_verificada:  # só entra no score quando a consulta foi REALMENTE feita
        sinais["sancao_ceis_cnep"] = sancionado
    else:
        d["sancoes"]["_aviso_score"] = "sanção não verificada → não pontuada (INDISPONÍVEL ≠ limpo)"
    try:
        from compliance_agent.analysis.score_convergencia import convergencia
        d["score"] = convergencia(sinais)
    except Exception as e:  # noqa: BLE001
        d["score"] = {"_nota": f"INDISPONÍVEL: {e}"}

    d["_fontes"] = "BrasilAPI · CEIS/CNEP · OB(TFE/SIAFE) · TSE · Grafo de Poder"
    d["_nota"] = ("Indícios para apuração interna; presunção de legitimidade dos atos. "
                  "Nenhum bloco indisponível foi fabricado.")

    if gerar_pdf:
        # Onda 7: relatório classe mundial (HTML→PDF via Playwright). FPDF compacto = fallback.
        try:
            d["path_pdf"] = await _gerar_pdf_classe_mundial(d)
        except Exception:  # noqa: BLE001
            try:
                d["path_pdf"] = _gerar_pdf(d)
            except Exception as e:  # noqa: BLE001
                d["path_pdf"] = None
                d["_pdf_erro"] = str(e)
    return d


async def montar_ctx_completo(alvo: str) -> dict:
    """Dossiê COMPLETO de fornecedor (pedido do dono 2026-07-20): o dossiê 360 + capítulos novos —
    veredito de fachada explícito, cláusulas restritivas na íntegra, suspeitas registradas e a
    árvore/íntegra dos processos SEID. Sem limite de páginas; prosa + tabelas; neutro. Puro ctx
    (o PDF sai por reporting/render_html.gerar_pdf). O parecer jurídico Lex segue como documento
    próprio (o /relatorio já o envia) — aqui ficam os capítulos factuais e de cláusulas."""
    import sqlite3

    from compliance_agent.reporting import capitulos_dossie as _cap
    from compliance_agent.reporting.neutralidade import neutralizar_ctx

    cnpj = _digits(alvo)
    d = await dossie(cnpj, gerar_pdf=False)
    if not d.get("ok"):
        return {"ok": False, "erro": d.get("erro") or "dossiê indisponível"}
    ctx = _ctx_dossie(d)

    # enriquece com o escore de fachada persistido (fantasma_score) p/ o veredito explícito
    try:
        from compliance_agent.emendas.db import conectar
        con = conectar()
        row = con.execute("SELECT score, classificacao, sinais_json FROM fantasma_score WHERE cnpj=?",
                          (cnpj,)).fetchone()
        if row:
            import json as _json
            d["fantasma"] = {"score": row[0], "classificacao": row[1],
                             "sinais": _json.loads(row[2]) if row[2] else []}
    except sqlite3.Error:
        con = None

    secoes = list(ctx.get("secoes") or [])
    novas = []
    novas.append(_cap.secao_veredito_fachada(d))
    if con is not None:
        novas.append(_cap.secao_clausulas_restritivas(con, cnpj))
        novas.append(_cap.secao_suspeitas(con, cnpj, d))
    # árvore + íntegra dos processos SEI do fornecedor (arquivo primeiro)
    try:
        from compliance_agent.correlacao_sei import processos_de_fornecedor
        procs = [p.get("numero_sei") for p in processos_de_fornecedor(cnpj, limite=12) if p.get("numero_sei")]
        if procs:
            novas.append(_cap.secao_sei_arvore(procs))
    except Exception as exc:  # noqa: BLE001 — capítulo SEI é bônus; nunca derruba o dossiê
        logger.debug("capítulo SEI do dossiê completo indisponível p/ %s: %s", cnpj, exc)
    if con is not None:
        con.close()

    ctx["secoes"] = secoes + [s for s in novas if s]
    ctx["titulo"] = "Dossiê Completo — Fornecedor"
    ctx = neutralizar_ctx(ctx)
    ctx["ok"] = True
    ctx["_cnpj"] = cnpj
    return ctx


async def gerar_pdf_completo(alvo: str) -> dict:
    """Gera o PDF do dossiê completo de fornecedor (Kroll) com gate de neutralidade."""
    from compliance_agent.reporting.neutralidade import garantir_neutro
    from compliance_agent.reporting.render_html import gerar_pdf, render_html
    ctx = await montar_ctx_completo(alvo)
    if not ctx.get("ok"):
        return ctx
    garantir_neutro(render_html(ctx), "dossiê completo de fornecedor")
    path = await gerar_pdf(ctx, f"dossie_completo_{ctx['_cnpj']}")
    return {"ok": True, "path_pdf": path, "titulo": ctx.get("subtitulo") or ctx["titulo"]}


def _brl(v) -> str:
    try:
        return f"{float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return str(v)


def _esc(s) -> str:
    import html as _h
    return _h.escape(str(s or ""))


def _ctx_dossie(d: dict) -> dict:
    """Monta o ctx COMPLETO do dossiê (rating card + gráficos + TODAS as seções coletadas). Puro
    e testável: recebe o dict de dossie() e devolve o ctx do render_html — sem I/O.

    Bug 2026-07-12: a versão anterior renderizava só OB + matriz + síntese, ignorando cadastro/QSA,
    sanções (CEIS/CNEP), conflito doador↔contrato, rede de poder, mídia adversa e
    pistas de investigação — tudo isso JÁ vinha coletado em `d`, mas nunca chegava ao PDF."""
    from compliance_agent.reporting import charts_svg as C

    cad = d.get("cadastro", {}) or {}
    nome = cad.get("razao_social") or cad.get("nome") or d["alvo"]
    ob = d.get("ob", {}) or {}
    sc = d.get("score", {}) or {}
    conf = d.get("conflito", {}) or {}
    rede = d.get("rede", {}) or {}
    secoes: list[dict] = []

    # 1) Identificação cadastral + QSA (BrasilAPI) — honesto se indisponível
    if cad.get("error") or cad.get("_nota"):
        secoes.append({"titulo": "1. Identificação cadastral",
                       "html": f"<p class='indisp'>INDISPONÍVEL — {_esc(cad.get('error') or cad.get('_nota'))}. "
                               "Nada foi fabricado.</p>"})
    else:
        socios = cad.get("socios") or []
        qsa = "".join(
            f"<tr><td>{_esc(s.get('nome'))}</td><td>{_esc(s.get('qualificacao'))}</td>"
            f"<td>{_esc(s.get('data_entrada'))}</td></tr>" for s in socios)
        secoes.append({"titulo": "1. Identificação cadastral e quadro societário (QSA)",
                       "html":
            "<table><tr><th>Campo</th><th>Valor</th></tr>"
            f"<tr><td>Razão social</td><td>{_esc(nome)}</td></tr>"
            f"<tr><td>Nome fantasia</td><td>{_esc(cad.get('nome_fantasia'))}</td></tr>"
            f"<tr><td>Situação cadastral</td><td>{_esc(cad.get('situacao'))}</td></tr>"
            f"<tr><td>Abertura</td><td>{_esc(cad.get('data_abertura'))}</td></tr>"
            f"<tr><td>Natureza jurídica</td><td>{_esc(cad.get('natureza_jur'))}</td></tr>"
            f"<tr><td>Atividade (CNAE)</td><td>{_esc(cad.get('atividade'))}</td></tr>"
            f"<tr><td>Capital social</td><td>R$ {_brl(cad.get('capital_social', 0))}</td></tr>"
            f"<tr><td>Município/UF</td><td>{_esc(cad.get('municipio'))}/{_esc(cad.get('uf'))}</td></tr>"
            "</table>" + (
                f"<h4>Sócios/dirigentes ({len(socios)})</h4><table>"
                "<tr><th>Nome</th><th>Qualificação</th><th>Entrada</th></tr>" + qsa + "</table>"
                if socios else "<p class='nota'>Sem QSA na fonte (natureza jurídica pode não expor sócios).</p>")})

    # 2) Sanções CEIS/CNEP/CEPIM (doméstico) — honesto
    san = d.get("sancoes", {}) or {}
    if san.get("verificado"):
        if san.get("sancionado"):
            linhas = "".join(
                f"<li>{_esc(x.get('tipo'))} — {_esc(x.get('orgao'))} (desde {_esc(x.get('inicio'))})</li>"
                for x in (san.get("sancoes") or [])) or "<li>sanção registrada</li>"
            san_html = f"<p class='flag'>⚠️ SANCIONADA (CEIS/CNEP/CEPIM):</p><ul>{linhas}</ul>"
        else:
            san_html = "<p>Sem sanção localizada no CEIS/CNEP/CEPIM na data da consulta.</p>"
    else:
        san_html = (f"<p class='indisp'>Sanção CEIS/CNEP <b>não verificada</b> — {_esc(san.get('_nota') or 'INDISPONÍVEL')}. "
                    "INDISPONÍVEL ≠ limpo; não pontuada no índice.</p>")
    secoes.append({"titulo": "2. Idoneidade — sanções (CEIS/CNEP/CEPIM)", "html": san_html})

    # 3) Pagamentos (OB) — gráfico de concentração + síntese
    ugs = ob.get("ugs") or []
    if ugs:
        total = ob.get("total_ob") or 1
        secoes.append({"titulo": "3. Concentração de pagamentos por órgão (OB)",
                       "chart": C.barras([u["nome"] or u["ug"] for u in ugs],
                                         [(u["total"] / total) for u in ugs], "Participação por UG"),
                       "html": "<p class='nota'>OB = pagamento efetivo (empenho não entra). "
                               f"Total pago: R$ {_brl(ob.get('total_ob', 0))} em {ob.get('n_ob', 0)} "
                               f"OBs sobre {ob.get('n_ugs', 0)} UG(s).</p>"})
    else:
        secoes.append({"titulo": "3. Pagamentos (OB)",
                       "html": f"<p class='nota'>{_esc(ob.get('_nota') or 'Sem OB deste favorecido na base (pode ser fornecedor municipal/federal ou fora da cobertura).')}</p>"})

    # 4) Conflito doador↔contrato (TSE)
    rede_conf = conf.get("rede") or []
    if rede_conf:
        linhas = "".join(
            f"<tr><td>{_esc(r.get('doador'))}</td><td>{_esc(r.get('candidato'))} ({_esc(r.get('partido'))}/{_esc(r.get('ano'))})</td>"
            f"<td>R$ {_brl(r.get('valor_doacao'))}</td><td>R$ {_brl(r.get('total_ob'))}</td>"
            f"<td>{_esc(r.get('via'))}</td></tr>" for r in rede_conf)
        secoes.append({"titulo": "4. Conflito doador de campanha ↔ contrato (TSE × OB)",
                       "html": "<table><tr><th>Doador (sócio)</th><th>Beneficiário</th><th>Doação</th>"
                               f"<th>Pago à empresa</th><th>Vínculo</th></tr>{linhas}</table>"
                               "<p class='nota'>Indício a verificar; CPF de sócio mascarado, match por nome+fragmento (LGPD).</p>"})
    else:
        secoes.append({"titulo": "4. Conflito doador ↔ contrato",
                       "html": f"<p class='nota'>{_esc(conf.get('_nota') or 'Nenhum vínculo doador↔contrato localizado.')}</p>"})

    # 5) Rede de poder (Grafo de Poder, 2 saltos)
    if rede.get("_nota"):
        secoes.append({"titulo": "5. Rede de poder", "html": f"<p class='indisp'>{_esc(rede.get('_nota'))}</p>"})
    else:
        nos = rede.get("nos") or []
        amostra = "".join(f"<li>{_esc(n.get('rotulo') or n.get('id'))} <i>({_esc(n.get('tipo'))})</i></li>"
                          for n in nos[:20])
        secoes.append({"titulo": "5. Rede de poder (2 saltos)",
                       "html": f"<p>{rede.get('n_nos', 0)} nós e {rede.get('n_arestas', 0)} arestas "
                               "(sócios, servidores, doações, contratos, nomeações). Amostra:</p>"
                               f"<ul>{amostra}</ul>" if nos else
                               f"<p>{rede.get('n_nos', 0)} nós / {rede.get('n_arestas', 0)} arestas.</p>"})

    # 6) Red flags estruturais (fachada/laranja)
    rfe = d.get("red_flags_estruturais") or []
    if rfe:
        linhas = "".join(f"<li><b>{_esc(r.get('flag'))}</b> — {_esc(r.get('obs'))}</li>" for r in rfe)
        secoes.append({"titulo": "6. Red flags estruturais (fachada/laranja — indício a verificar)",
                       "html": f"<ul>{linhas}</ul>"})

    # 7) Mídia adversa (GDELT)
    mid = d.get("midia_adversa") or {}
    if mid.get("adversos"):
        linhas = "".join(
            f"<tr><td>{_esc(a.get('data'))}</td><td>{_esc(a.get('titulo'))}</td><td>{_esc(a.get('fonte'))}</td></tr>"
            for a in mid["adversos"][:15])
        secoes.append({"titulo": "7. Mídia adversa (fontes abertas)",
                       "html": f"<p>{mid.get('n_adversos', 0)} de {mid.get('n_total', 0)} artigos com termos de risco.</p>"
                               f"<table><tr><th>Data</th><th>Manchete</th><th>Fonte</th></tr>{linhas}</table>"})
    elif mid and not mid.get("ok"):
        secoes.append({"titulo": "7. Mídia adversa",
                       "html": f"<p class='indisp'>INDISPONÍVEL — {_esc(mid.get('erro'))}.</p>"})

    # 8) Matriz de risco P×I (TCU)
    prob = max(1, min(round((sc.get("score", 0) or 0) / 11) + 1, 9))
    imp = max(1, min(round((ob.get("concentracao_top_ug", 0) or 0) * 9) + 1, 9))
    secoes.append({"titulo": "8. Matriz de risco P×I (TCU)", "chart": C.heatmap_pxi(prob, imp)})

    # 9) Síntese
    secoes.append({"titulo": "9. Síntese",
                   "html": "<table><tr><th>Indicador</th><th>Valor</th></tr>"
                           f"<tr><td>Total pago (OB)</td><td>R$ {_brl(ob.get('total_ob', 0))}</td></tr>"
                           f"<tr><td>Nº de OBs / UGs</td><td>{ob.get('n_ob', 0)} / {ob.get('n_ugs', 0)}</td></tr>"
                           f"<tr><td>Conflito doador↔contrato</td><td>{conf.get('n', 0)} vínculo(s)</td></tr>"
                           f"<tr><td>Rede de poder (2 saltos)</td><td>{rede.get('n_nos', 0)} nós</td></tr>"
                           f"<tr><td>Red flags estruturais</td><td>{len(rfe)}</td></tr></table>"})

    # 10) Pistas de investigação hospedada (deep-links manuais)
    links = d.get("links_investigacao") or []
    if links:
        linhas = "".join(f"<li>{_esc(l.get('fonte'))} <i>({_esc(l.get('categoria'))})</i>: "
                         f"<a href='{_esc(l.get('url'))}'>{_esc(l.get('url'))}</a></li>" for l in links[:20])
        secoes.append({"titulo": "10. Pistas de investigação (fontes hospedadas — uso manual)",
                       "html": f"<ul>{linhas}</ul>"})

    return {
        "_dados": d, "titulo": f"Dossiê 360 — {nome}", "subtitulo": f"CNPJ {d['alvo']}",
        "classificacao": "CONFIDENCIAL — USO INTERNO (controle externo)",
        "score": sc.get("score", 0), "faixa": sc.get("faixa", "BAIXO"),
        "top_flags": [c["flag"] for c in (sc.get("contribuicoes") or [])[:3]],
        "secoes": secoes,
        "proveniencia": [
            {"dado": "Pagamentos (OB)", "estado": "REAL", "fonte": "TFE/SIAFE", "data": d.get("gerado_em", "")[:10]},
            {"dado": "Cadastro/QSA", "estado": "REAL" if cad.get("razao_social") else "INDISPONÍVEL",
             "fonte": "BrasilAPI", "data": d.get("gerado_em", "")[:10]},
            {"dado": "Sanções", "estado": "REAL" if san.get("verificado") else "INDISPONÍVEL",
             "fonte": "CEIS/CNEP/CEPIM", "data": d.get("gerado_em", "")[:10]},
            {"dado": "Doações", "estado": "REAL", "fonte": "TSE", "data": d.get("gerado_em", "")[:10]},
            {"dado": "Rede de poder", "estado": "REAL" if not rede.get("_nota") else "INDISPONÍVEL",
             "fonte": "Grafo de Poder (interno)", "data": d.get("gerado_em", "")[:10]},
        ],
    }


async def _gerar_pdf_classe_mundial(d: dict) -> str:
    """Onda 7 — gera o PDF do dossiê a partir do ctx completo (_ctx_dossie)."""
    from compliance_agent.reporting.render_html import gerar_pdf
    return await gerar_pdf(_ctx_dossie(d), f"dossie_{d['alvo']}")


def _gerar_pdf(d: dict) -> str:
    """PDF compacto do dossiê (FPDF). Estética sóbria; rodapé com ressalva e data."""
    from fpdf import FPDF

    cad = d.get("cadastro", {}) or {}
    nome = cad.get("razao_social") or cad.get("nome") or cad.get("nome_fantasia") or d["alvo"]
    sc = d.get("score", {}) or {}

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 15)
    pdf.cell(0, 9, "DOSSIE 360", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, _ascii(f"Alvo: {nome}  |  CNPJ: {d['alvo']}"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.cell(0, 6, _ascii(f"Gerado em: {d.get('gerado_em','')}"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(2)

    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 7, _ascii(f"Score de convergencia: {sc.get('score','-')} ({sc.get('faixa','-')})"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("Helvetica", "", 9)
    for c in (sc.get("contribuicoes") or [])[:8]:
        pdf.cell(0, 5, _ascii(f"  - {c['flag']}: +{c['contribuicao']}"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(2)

    ob = d.get("ob", {}) or {}
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 6, "Pagamentos (OB)", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(0, 5, _ascii(f"Total pago: R$ {ob.get('total_ob',0):,.2f}  |  OBs: {ob.get('n_ob',0)}  |  "
                          f"UGs: {ob.get('n_ugs',0)}  |  Concentracao top UG: {ob.get('concentracao_top_ug')}"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(1)

    conf = d.get("conflito", {}) or {}
    rede = d.get("rede", {}) or {}
    san = d.get("sancoes", {}) or {}
    pdf.set_font("Helvetica", "B", 11); pdf.cell(0, 6, "Indicios", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(0, 5, _ascii(f"Conflito doador<->contrato: {conf.get('n','-')} vinculo(s)"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.cell(0, 5, _ascii(f"Sancao CEIS/CNEP: {'SIM' if (san.get('sancionado') or san.get('sancoes')) else 'nao localizada'}"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.cell(0, 5, _ascii(f"Rede de poder: {rede.get('n_nos','-')} nos / {rede.get('n_arestas','-')} arestas (2 saltos)"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.ln(3)
    pdf.set_font("Helvetica", "I", 8)
    pdf.multi_cell(0, 4, _ascii(
        "Indicios para apuracao interna; presuncao de legitimidade dos atos administrativos. "
        "Nenhum bloco indisponivel foi fabricado. Score = risco de ACHADO, nao de punicao. "
        "Fontes: " + str(d.get("_fontes", ""))))

    _REPORTS.mkdir(parents=True, exist_ok=True)
    destino = _REPORTS / f"dossie_{d['alvo']}_{datetime.now().date()}.pdf"
    pdf.output(str(destino))
    return str(destino)


def _ascii(s: str) -> str:
    """FPDF core fonts são latin-1; normaliza para evitar erro de encoding."""
    return str(s).encode("latin-1", "replace").decode("latin-1")
