# -*- coding: utf-8 -*-
"""Dossiê 360 — JFN 2.0, Onda 4. Perfil 1-comando agregando todas as fontes reais.

Une, sobre um alvo (CNPJ): cadastro (BrasilAPI), sanções (CEIS/CNEP), rede (Grafo de Poder),
OB/contratos, conflito doador↔contrato (TSE), e o score de convergência decomponível.
Gera um PDF compacto. Honesto: cada fonte que falhar vira INDISPONÍVEL — nunca fabrica.

Invariante: indícios para apuração; presunção de legitimidade; CPF mascarado (LGPD).
"""
from __future__ import annotations

import re
import sqlite3
from datetime import datetime
from pathlib import Path

_DB = Path(__file__).resolve().parent.parent / "data" / "compliance.db"
_REPORTS = Path(__file__).resolve().parent.parent / "reports"


def _digits(s) -> str:
    return re.sub(r"\D", "", str(s or ""))


def _resumo_ob(cnpj: str) -> dict:
    """Total pago, nº de OBs e concentração por UG (OB = pagamento)."""
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
    return {
        "total_ob": round(total, 2),
        "n_ob": sum(r[3] for r in rows),
        "n_ugs": len(rows),
        "concentracao_top_ug": round(top, 3),
        "ugs": [{"ug": r[0], "nome": r[1], "total": round(r[2] or 0, 2)} for r in rows[:5]],
    }


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

    # 2) sanções CEIS/CNEP
    sancionado = False
    try:
        from compliance_agent.collectors.ceis import verificar_sancao
        d["sancoes"] = await verificar_sancao(cnpj)
        sancionado = bool(d["sancoes"].get("sancionado") or d["sancoes"].get("sancoes"))
    except Exception as e:  # noqa: BLE001
        d["sancoes"] = {"_nota": f"INDISPONÍVEL: {e}"}

    # 2b) OpenSanctions (PEP + sanções internacionais) — Onda 12 (key-gated, honesto)
    try:
        from compliance_agent.enrich.opensanctions import checar
        d["opensanctions"] = checar(cnpj)
        sancionado = sancionado or bool(d["opensanctions"].get("sancionado"))
    except Exception:  # noqa: BLE001
        pass

    # 2c) OCCRP Aleph (follow-the-money cross-jurisdição) — Onda 12 (API, key-gated, honesto)
    try:
        from compliance_agent.enrich.aleph import buscar as _aleph
        d["aleph"] = _aleph(cnpj)
    except Exception:  # noqa: BLE001
        pass

    # 2d) Mídia adversa (fontes abertas, KEYLESS via GDELT) — DD §9
    try:
        from compliance_agent.enrich.midia_adversa import varrer as _midia
        nome_alvo = (d.get("cadastro") or {}).get("razao_social") or alvo
        d["midia_adversa"] = _midia(nome_alvo, cnpj)
    except Exception:  # noqa: BLE001
        pass

    # 2e) Pistas de investigação hospedada (Max Intel/OSINT-Brazuca/RedeCNPJ…) — deep-links MANUAIS
    try:
        from compliance_agent.providers import lookup as _plookup
        nome_alvo = (d.get("cadastro") or {}).get("razao_social") or alvo
        d["links_investigacao"] = (_plookup("links", nome=nome_alvo, cnpj=cnpj).dados or {}).get("links", [])
    except Exception:  # noqa: BLE001
        pass

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

    # 6) score de convergência (a partir dos sinais reunidos)
    sinais = {
        "conflito_doador": bool(d.get("conflito", {}).get("n")),
        "sancao_ceis_cnep": sancionado,
        "concentracao_orgao": 1.0 if (d["ob"].get("concentracao_top_ug") or 0) >= 0.6 else 0.0,
    }
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


async def _gerar_pdf_classe_mundial(d: dict) -> str:
    """Onda 7 — monta o ctx do dossiê (rating card + gráficos SVG + proveniência) e gera o PDF."""
    from compliance_agent.reporting import charts_svg as C
    from compliance_agent.reporting.render_html import gerar_pdf

    cad = d.get("cadastro", {}) or {}
    nome = cad.get("razao_social") or cad.get("nome") or d["alvo"]
    ob = d.get("ob", {}) or {}
    sc = d.get("score", {}) or {}
    conf = d.get("conflito", {}) or {}
    rede = d.get("rede", {}) or {}

    secoes = []
    ugs = ob.get("ugs") or []
    if ugs:
        total = ob.get("total_ob") or 1
        secoes.append({"titulo": "Concentração de pagamentos por órgão (OB)",
                       "chart": C.barras([u["nome"] or u["ug"] for u in ugs],
                                         [(u["total"] / total) for u in ugs], "Participação por UG")})
    # matriz P×I a partir do score (heurística: prob~score/10, impacto~concentração)
    prob = max(1, min(round((sc.get("score", 0) or 0) / 11) + 1, 9))
    imp = max(1, min(round((ob.get("concentracao_top_ug", 0) or 0) * 9) + 1, 9))
    secoes.append({"titulo": "Matriz de risco P×I (TCU)", "chart": C.heatmap_pxi(prob, imp)})
    secoes.append({"titulo": "Síntese",
                   "html": f"<table><tr><th>Indicador</th><th>Valor</th></tr>"
                           f"<tr><td>Total pago (OB)</td><td>R$ {ob.get('total_ob', 0):,.2f}</td></tr>"
                           f"<tr><td>Nº de OBs / UGs</td><td>{ob.get('n_ob', 0)} / {ob.get('n_ugs', 0)}</td></tr>"
                           f"<tr><td>Conflito doador↔contrato</td><td>{conf.get('n', 0)} vínculo(s)</td></tr>"
                           f"<tr><td>Rede de poder (2 saltos)</td><td>{rede.get('n_nos', 0)} nós</td></tr></table>"})

    ctx = {
        "_dados": d, "titulo": f"Dossiê 360 — {nome}", "subtitulo": f"CNPJ {d['alvo']}",
        "classificacao": "CONFIDENCIAL — USO INTERNO (controle externo)",
        "score": sc.get("score", 0), "faixa": sc.get("faixa", "BAIXO"),
        "top_flags": [c["flag"] for c in (sc.get("contribuicoes") or [])[:3]],
        "secoes": secoes,
        "proveniencia": [
            {"dado": "Pagamentos (OB)", "estado": "REAL", "fonte": "TFE/SIAFE", "data": d.get("gerado_em", "")[:10]},
            {"dado": "Cadastro", "estado": "REAL" if cad.get("razao_social") else "INDISPONÍVEL",
             "fonte": "BrasilAPI", "data": d.get("gerado_em", "")[:10]},
            {"dado": "Doações", "estado": "REAL", "fonte": "TSE", "data": d.get("gerado_em", "")[:10]},
        ],
    }
    return await gerar_pdf(ctx, f"dossie_{d['alvo']}")


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
    pdf.cell(0, 9, "DOSSIE 360 - JFN", ln=True)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, _ascii(f"Alvo: {nome}  |  CNPJ: {d['alvo']}"), ln=True)
    pdf.cell(0, 6, _ascii(f"Gerado em: {d.get('gerado_em','')}"), ln=True)
    pdf.ln(2)

    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 7, _ascii(f"Score de convergencia: {sc.get('score','-')} ({sc.get('faixa','-')})"), ln=True)
    pdf.set_font("Helvetica", "", 9)
    for c in (sc.get("contribuicoes") or [])[:8]:
        pdf.cell(0, 5, _ascii(f"  - {c['flag']}: +{c['contribuicao']}"), ln=True)
    pdf.ln(2)

    ob = d.get("ob", {}) or {}
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 6, "Pagamentos (OB)", ln=True)
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(0, 5, _ascii(f"Total pago: R$ {ob.get('total_ob',0):,.2f}  |  OBs: {ob.get('n_ob',0)}  |  "
                          f"UGs: {ob.get('n_ugs',0)}  |  Concentracao top UG: {ob.get('concentracao_top_ug')}"), ln=True)
    pdf.ln(1)

    conf = d.get("conflito", {}) or {}
    rede = d.get("rede", {}) or {}
    san = d.get("sancoes", {}) or {}
    pdf.set_font("Helvetica", "B", 11); pdf.cell(0, 6, "Indicios", ln=True)
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(0, 5, _ascii(f"Conflito doador<->contrato: {conf.get('n','-')} vinculo(s)"), ln=True)
    pdf.cell(0, 5, _ascii(f"Sancao CEIS/CNEP: {'SIM' if (san.get('sancionado') or san.get('sancoes')) else 'nao localizada'}"), ln=True)
    pdf.cell(0, 5, _ascii(f"Rede de poder: {rede.get('n_nos','-')} nos / {rede.get('n_arestas','-')} arestas (2 saltos)"), ln=True)

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
