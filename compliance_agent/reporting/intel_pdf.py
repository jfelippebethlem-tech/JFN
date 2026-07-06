# -*- coding: utf-8 -*-
"""Render PDF (fpdf2 + HTML/Playwright) do relatório — extraído de inteligencia.py (split 2026-07-06).
Comportamento idêntico; rede de segurança: tools/inteligencia_snapshot_check.py + tests/test_inteligencia_snapshot.py.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sqlite3
import time
from collections import OrderedDict, defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from fpdf.enums import XPos, YPos

from compliance_agent.reporting.intel_base import _REPORTS, _num_brl, fmt_cnpj, moeda, so_digitos, cabecalho_frescor
from compliance_agent.reporting.intel_dados import _crescimento
from compliance_agent.reporting.intel_analise import (
    _anomalias_fornecedor, _red_flags, _resumo_executivo, parecer_fornecedor,
)
from compliance_agent.reporting.intel_md import (
    _FONTES_DEJAVU, _capital_recebido_md, _fachada_b2_html, _realidade_sede_texto, _rodizio_fornecedor,
)

def _registrar_fonte(pdf) -> tuple[str, bool]:
    """Registra DejaVu (Unicode) se disponível. Retorna (familia, eh_unicode).
    Italico mapeia para o regular (DejaVuSans nao tem oblique no pacote core)."""
    reg, bold = _FONTES_DEJAVU
    if Path(reg).exists() and Path(bold).exists():
        try:
            pdf.add_font("DejaVu", "", reg)
            pdf.add_font("DejaVu", "B", bold)
            pdf.add_font("DejaVu", "I", reg)
            pdf.add_font("DejaVu", "BI", bold)
            return "DejaVu", True
        except Exception:
            pass
    return "Helvetica", False


async def render_pdf_html(ctx: dict, destino: str) -> str:
    """Onda 7 — relatório de fornecedor CLASSE MUNDIAL (HTML→PDF via Playwright).

    Resolve margem estourada e truncamento (CSS quebra texto) e traz TODAS as seções:
    perfil cadastral · quadro societário · DOAÇÕES ELEITORAIS DOS SÓCIOS (conflito) ·
    listas restritivas/OSINT (CEIS/CNEP+OpenSanctions) · pagamentos por ano · concentração ·
    contratos · proveniência + hash. Indícios, nunca acusação.
    """
    import html as _html

    from compliance_agent.reporting import charts_svg as C
    from compliance_agent.reporting.render_html import render_html, html_to_pdf

    def esc(s):
        return _html.escape(str(s if s not in (None, "") else "—"))

    p = ctx["pagamentos"]
    cnpj = ctx["cnpj"]
    emp = (ctx["enriq"].get("dados") or {}).get("empresa") if ctx["enriq"].get("ok") else None
    secoes = []

    # 1. Perfil cadastral
    if emp:
        _endcz = (ctx.get("cruzamento") or {}).get("endereco") or {}  # fallback município/UF (mesma fonte da Seção 1-B)
        _mun = emp.get("municipio") or _endcz.get("municipio") or "—"
        _uf = emp.get("uf") or _endcz.get("uf") or "—"
        campos = [("Razão social", emp.get("razao_social")), ("Situação", emp.get("situacao")),
                  ("Data de abertura", emp.get("data_abertura")), ("Porte", emp.get("porte")),
                  ("Natureza jurídica", emp.get("natureza_juridica")),
                  ("Capital social", f"R$ {moeda(emp.get('capital_social'))}" if emp.get("capital_social") else None),
                  ("CNAE principal", emp.get("cnae_principal")),
                  ("Município/UF", f"{_mun}/{_uf}"),
                  ("Endereço (sede)", emp.get("endereco") or (ctx.get("cruzamento") or {}).get("endereco", {}).get("endereco"))]
        _rs = _realidade_sede_texto(ctx.get("cnpj", ""))
        if _rs:
            campos.append(("Realidade da sede", _rs))  # a empresa é real? (cruzamento de endereço)
        rows = "".join(f"<tr><th>{esc(k)}</th><td>{esc(v)}</td></tr>" for k, v in campos)
        # foto da fachada guardada no B2 (FLAGUEADOS) — embutida on-demand, degrada honesto se indisponível
        _foto = _fachada_b2_html(ctx.get("cnpj", ""))
        secoes.append({"titulo": "1. Perfil cadastral", "html": f"<table>{rows}</table>" + _foto})
    else:
        end = (ctx.get("cruzamento") or {}).get("endereco", {}).get("endereco")
        _rs = _realidade_sede_texto(ctx.get("cnpj", ""))
        _foto = _fachada_b2_html(ctx.get("cnpj", ""))
        secoes.append({"titulo": "1. Perfil cadastral",
                       "html": f"<p class='nota'>Perfil cadastral {esc(ctx.get('fonte_enriq'))} — dados financeiros abaixo são REAIS."
                               + (f" Endereço (sede): {esc(end)}." if end else "")
                               + (f" Realidade da sede: {esc(_rs)}." if _rs else "") + "</p>" + _foto})

    # 2. Quadro societário (sócios/diretores)
    socios = (emp or {}).get("socios") or []
    if socios:
        rows = "".join(f"<tr><td>{esc(s.get('nome'))}</td><td>{esc(s.get('qualificacao'))}</td>"
                       f"<td>{esc(s.get('data_entrada'))}</td></tr>" for s in socios[:25])
        secoes.append({"titulo": "2. Quadro societário (QSA / diretores)",
                       "html": f"<table><tr><th>Sócio</th><th>Qualificação</th><th>Entrada</th></tr>{rows}</table>"})

    # 2-B. Benefícios sociais dos sócios/administradores (laranja) — paridade com o MD §1-C
    try:
        from compliance_agent.reporting import beneficios_view as bv
        _b = bv.por_fornecedor(cnpj)
    except Exception:  # noqa: BLE001
        _b = {}
    _intro_bs = ("<p class='nota'>Cruza o CPF dos sócios/administradores do QSA com benefícios de subsistência "
                 "(Bolsa Família, BPC, Aux. Emergencial, PETI, Safra, Defeso — Portal da Transparência/CGU). Ser "
                 "dono/gestor de empresa que recebe recursos públicos <b>e</b> receber benefício de subsistência é "
                 "<b>indício de testa-de-ferro (laranja)</b> — art. 337-F CP; art. 11 Lei 8.429/92. CPF mascarado "
                 "(LGPD); resolvido via favorecidos PF + doadores TSE. <b>INDISPONÍVEL ≠ ausência.</b> Indício, nunca acusação.</p>")
    if _b.get("total_qsa"):
        _leitura_bs = esc(bv.leitura(_b, escopo="deste fornecedor").replace("**", ""))
        _resumo_bs = (f"<p>QSA mascarado: <b>{_b['total_qsa']}</b> · varridos: {_b['n_varridos']} · CPF resolvido: "
                      f"{_b['n_resolvidos']} · verificados: {_b['n_verificados']} ({_b['cobertura']}%) · com benefício "
                      f"(indício): <b>{_b['n_com_beneficio']}</b> · INDISPONÍVEL: {_b['n_indisponivel']}</p>")
        _fmap_bs = {"favorecidos_pf": "favorecidos PF", "tse_doadores": "doadores TSE"}
        _itens_bs = _b.get("itens") or []
        _tab_bs = ""
        if _itens_bs:
            _rows_bs = "".join(f"<tr><td>{esc(it.get('nome'))}</td><td>{esc(it.get('papel'))}</td>"
                               f"<td>{esc(', '.join(it.get('tipos') or []) or '—')}</td>"
                               f"<td>{esc(_fmap_bs.get(it.get('fonte', ''), it.get('fonte', '') or '—'))}</td></tr>"
                               for it in _itens_bs[:20])
            _tab_bs = ("<table><tr><th>Sócio/Administrador</th><th>Papel</th><th>Benefício</th>"
                       f"<th>Fonte do CPF</th></tr>{_rows_bs}</table>")
        secoes.append({"titulo": "2-B. Benefícios sociais dos sócios/administradores (indício de laranja)",
                       "html": _intro_bs + f"<p>{_leitura_bs}</p>" + _resumo_bs + _tab_bs})
    else:
        secoes.append({"titulo": "2-B. Benefícios sociais dos sócios/administradores",
                       "html": _intro_bs + "<p class='nota'>Sem sócios/administradores com CPF mascarado no QSA "
                               "(ou QSA público não ingerido) — INDISPONÍVEL.</p>"})

    # 2-C. Capital social × recebido (subcapitalização) — paridade com o MD §1
    _cap_md = _capital_recebido_md(emp, p)
    if _cap_md:
        _cap_txt = (_cap_md[2:] if _cap_md.startswith("- ") else _cap_md).replace("**", "")
        secoes.append({"titulo": "2-C. Capital social × recebido (subcapitalização)",
                       "html": f"<p>{esc(_cap_txt)}</p>"})

    # 2-D. Rodízio de vencedores / cartel (bid rotation) — paridade com o MD §1-E
    _rodf = ctx.get("rodizio_forn") or _rodizio_fornecedor(cnpj)
    if _rodf.get("ok"):
        _aneis = _rodf.get("aneis") or []
        if _aneis:
            _rr = "".join(f"<tr><td>{esc(a['ug'])}</td><td>{a.get('score')}</td><td>{a.get('n_campeoes')}</td>"
                          f"<td>{a.get('n_vitorias')}x</td><td>{esc(', '.join(str(y) for y in (a.get('anos') or [])))}</td></tr>"
                          for a in _aneis)
            _rh = ("<p class='nota'>Fornecedor é <b>campeão de rodízio</b> (bid rotation/cartel — OCDE; Lei 12.529 "
                   "art.36; Lei 8.666 art.90) nas UGs abaixo. A OB expõe o vencedor, não os licitantes — corroborar "
                   "no SEI/PNCP. Indício, não prova.</p>"
                   f"<table><tr><th>UG</th><th>Score</th><th>Nº campeões</th><th>Vitórias</th><th>Anos</th></tr>{_rr}</table>")
        else:
            _rh = (f"<p class='nota'>Avaliadas {_rodf.get('ugs_avaliadas')} UG(s) que mais pagam este fornecedor: "
                   "nenhum anel de rodízio com ele como campeão (indício de cartel afastado para essas UGs; demais "
                   "UGs não avaliadas — INDISPONÍVEL).</p>")
        secoes.append({"titulo": "2-D. Rodízio de vencedores / cartel (bid rotation)", "html": _rh})

    # 2-E. Conflito de pessoal — sócio/admin (CPF resolvido) na folha do Estado — paridade com o MD §1-F
    try:
        from compliance_agent.reporting import conflito_pessoal_view as _cpv
        _cpa = _cpv.por_fornecedor(cnpj)
    except Exception:  # noqa: BLE001
        _cpa, _cpv = {}, None
    if _cpa.get("n_socios") and _cpv:
        _ci = _cpa.get("itens") or []
        _ch = f"<p class='nota'>{esc(_cpv.leitura(_cpa).replace('**', ''))}</p>"
        if _ci:
            _cr = "".join(f"<tr><td>{esc(it['nome'])}</td><td>{esc(it['papel'])}</td><td>{esc(it['orgao'])}</td>"
                          f"<td>{esc(it['cargo'])}</td><td>{esc(it['vinculo'])}</td></tr>" for it in _ci[:20])
            _ch += ("<table><tr><th>Sócio/Adm</th><th>Papel</th><th>Órgão (folha)</th><th>Cargo</th>"
                    f"<th>Vínculo</th></tr>{_cr}</table>")
        secoes.append({"titulo": "2-E. Conflito de pessoal — sócio na folha do Estado", "html": _ch})

    # 3. DOAÇÕES ELEITORAIS dos sócios/empresa (conflito doador↔contrato) — pedido do dono
    # reusa a rede já calculada em montar() (evita 2ª query ao TSE); fallback recalcula
    rede = ctx.get("conflito_rede")
    if rede is None:
        try:
            from compliance_agent.lex_conflito import conflito
            rede = conflito(cnpj=cnpj, limite=30).get("rede", [])
        except Exception:  # noqa: BLE001
            rede = []
    if rede:
        def _ug_cell(r):
            ugs_l = r.get("ugs") or []
            if not ugs_l:
                return "—"
            top = "; ".join(f"{esc(u.get('nome'))} (R$ {moeda(u.get('total'))})" for u in ugs_l[:3])
            extra = f" (+{len(ugs_l) - 3} UG)" if len(ugs_l) > 3 else ""
            return top + extra

        def _sei_cell(r):
            seis_l = r.get("seis") or []
            if not seis_l:
                return "—"
            return ", ".join(esc(s) for s in seis_l[:8]) + (f" (+{len(seis_l) - 8})" if len(seis_l) > 8 else "")

        rows = "".join(f"<tr><td>{esc(r.get('doador'))}</td><td>{esc(r.get('via'))}</td>"
                       f"<td>{esc(r.get('candidato'))}</td><td>{esc(r.get('partido'))}</td>"
                       f"<td>{esc(r.get('ano'))}</td><td>R$ {moeda(r.get('valor_doacao'))}</td>"
                       f"<td>{_ug_cell(r)}</td><td class='nota'>{_sei_cell(r)}</td></tr>" for r in rede[:20])
        secoes.append({"titulo": "3. Doações eleitorais (sócios/empresa → candidatos) — conflito de interesse",
                       "html": "<p class='nota'>Cruzamento TSE × QSA × contratos: o doador pode ser a empresa OU um sócio dela (coluna Via). "
                               "As colunas <b>Órgão (UG) pagador</b> e <b>Processos SEI</b> mostram por onde a empresa contratada recebeu — "
                               "fechando a cadeia doador→fornecedor→candidato→UG→SEI. Indício a verificar (presunção de legitimidade), nunca acusação.</p>"
                               f"<table><tr><th>Doador</th><th>Via</th><th>Candidato</th><th>Partido</th><th>Ano</th><th>Valor doado</th>"
                               f"<th>Órgão (UG) pagador</th><th>Processos SEI</th></tr>{rows}</table>"})
    else:
        secoes.append({"titulo": "3. Doações eleitorais dos sócios/empresa",
                       "html": "<p class='nota'>Nenhuma doação eleitoral (TSE) localizada para a empresa ou seus sócios na base.</p>"})

    # 4. Listas restritivas / OSINT (CEIS/CNEP + OpenSanctions)
    osint = []
    try:
        from compliance_agent.collectors.ceis import verificar_sancao
        s = await verificar_sancao(cnpj)
        if not s.get("verificado"):
            osint.append(f"<li>CEIS/CNEP/CEPIM (CGU): <b>INDISPONÍVEL</b> "
                         f"<span class='nota'>({esc(s.get('motivo') or 'não verificado')}) — não equivale a “limpo”</span></li>")
        elif s.get("sancionado"):
            sl = s.get("sancoes") or []
            top = "; ".join(f"{esc(x.get('_fonte'))}: {esc(x.get('tipo_sancao') or x.get('fundamentacao'))}"
                            for x in sl[:3])
            osint.append(f"<li>CEIS/CNEP/CEPIM (CGU): <b>SANCIONADA — {esc(len(sl))} registro(s)</b> — {top} "
                         f"<span class='nota'>(verificar vigência na fonte)</span></li>")
        else:
            osint.append("<li>CEIS/CNEP/CEPIM (CGU): nada localizado <span class='nota'>(consulta verificada)</span></li>")
    except Exception:  # noqa: BLE001
        osint.append("<li>CEIS/CNEP: INDISPONÍVEL</li>")
    try:
        from compliance_agent.enrich.opensanctions import checar
        o = checar(cnpj)
        osint.append("<li>OpenSanctions (PEP/sanções intl.): INDISPONÍVEL (sem chave grátis)</li>"
                     if o.get("sancionado") is None else
                     f"<li>OpenSanctions: sanção={esc(o.get('sancionado'))} · PEP={esc(o.get('pep'))}</li>")
    except Exception:  # noqa: BLE001
        pass
    try:
        from compliance_agent.enrich.aleph import buscar as _aleph
        al = _aleph(cnpj)
        if not al.get("matches"):
            osint.append("<li>OCCRP Aleph (follow-the-money intl.): INDISPONÍVEL (sem chave grátis) ou sem registro</li>")
        else:
            tops = "; ".join(f"{esc(m.get('nome'))} ({esc(m.get('schema'))})" for m in al["matches"][:3])
            osint.append(f"<li>OCCRP Aleph: <b>{esc(al.get('total'))} registro(s)</b> — {tops} <span class='nota'>(indício a confirmar na fonte)</span></li>")
    except Exception:  # noqa: BLE001
        pass
    gz = ctx.get("gazetas") or {}
    if gz.get("total"):
        muns = "; ".join(dict.fromkeys(
            f"{esc(i.get('municipio'))}/{esc(i.get('uf'))} ({esc(i.get('data'))})"
            for i in (gz.get("itens") or [])[:4] if i.get("municipio")))
        osint.append(f"<li>Diários Oficiais (Querido Diário): <b>{esc(gz['total'])} menção(ões)</b> "
                     f"em diários municipais — {muns} <span class='nota'>(contexto para cotejar contratos além do Estado)</span></li>")
    elif gz.get("_indisponivel"):
        osint.append(f"<li>Diários Oficiais (Querido Diário): INDISPONÍVEL <span class='nota'>({esc(gz['_indisponivel'])})</span></li>")
    secoes.append({"titulo": "4. Listas restritivas e OSINT", "html": f"<ul>{''.join(osint)}</ul>"})

    # 4-C. Mídia adversa (fontes abertas, KEYLESS via GDELT) — DD §9; ideia do dono: usar a internet p/ DD
    try:
        from compliance_agent.enrich.midia_adversa import varrer as _midia
        ma = _midia(ctx.get("nome") or "", cnpj)
        adversos = ma.get("adversos") or []
        if adversos:
            li = "".join(
                f"<li><a href='{esc(a.get('url'))}'>{esc(a.get('titulo'))}</a> "
                f"<span class='nota'>— {esc(a.get('fonte'))} · {esc(a.get('data'))} · termos: {esc(', '.join(a.get('termos') or []))}</span></li>"
                for a in adversos[:10])
            ma_html = (f"<p class='nota'>Varredura de cobertura jornalística (GDELT, fontes abertas, sem chave). "
                       f"{ma.get('n_adversos')} de {ma.get('n_total')} matérias com termos de risco. "
                       "Indício a confirmar na fonte — cobertura não é prova e pode haver homônimos.</p>"
                       f"<ul>{li}</ul>")
        else:
            nota = (ma.get("_nota", "") or "").rstrip(". ")
            ma_html = ("<p class='nota'>Nenhuma matéria com termos de risco localizada em fontes abertas (GDELT)"
                       + (f" — {esc(nota)}" if "INDISPONÍVEL" in nota else " na janela analisada") + ".</p>")
        secoes.append({"titulo": "4-C. Mídia adversa (fontes abertas — OSINT)", "html": ma_html})
    except Exception:  # noqa: BLE001
        pass

    # 4-D. Pistas de investigação hospedada (Max Intel, OSINT-Brazuca, RedeCNPJ…) — deep-links MANUAIS
    try:
        from compliance_agent.providers import lookup as _plookup
        lk = _plookup("links", nome=(ctx.get("nome") or None), cnpj=cnpj)
        links = (lk.dados or {}).get("links") if getattr(lk, "ok", False) else None
        if links:
            li = "".join(f"<li><a href='{esc(x.get('url'))}'>{esc(x.get('fonte'))}</a> "
                         f"<span class='nota'>— {esc(x.get('categoria'))}</span></li>" for x in links)
            secoes.append({"titulo": "4-D. Pistas de investigação (OSINT hospedado — uso manual)",
                           "html": "<p class='nota'>Agregadores e fontes hospedadas grátis (você pesquisa; o JFN só "
                                   "monta o link já preenchido com o alvo). Aprofundamento de DD — não são dados coletados.</p>"
                                   f"<ul>{li}</ul>"})
    except Exception:  # noqa: BLE001
        pass

    # 5. Pagamentos — TABELA CRUZADA Órgão (UG) × Ano (pedido do dono: por ano, dividido por órgão)
    if p["tem_dados"]:
        # agrega valor por (órgão, ano) a partir das linhas de OB
        matriz: dict = {}
        tot_ano: dict = {}
        for a in p["anos"]:
            # por_orgao já é a agregação COMPLETA por órgão naquele exercício
            for org, v in (p["por_ano"][a].get("por_orgao") or {}).items():
                matriz.setdefault(org or "—", {})[a] = v
                tot_ano[a] = tot_ano.get(a, 0.0) + (v or 0)
        orgs_ord = sorted(matriz, key=lambda o: -sum(matriz[o].values()))
        thead = "<tr><th>Órgão (UG)</th>" + "".join(f"<th>{a}</th>" for a in p["anos"]) + "<th>Total</th></tr>"
        body = ""
        for org in orgs_ord:
            tot_org = sum(matriz[org].values())
            cells = "".join(f"<td>{('R$ ' + moeda(matriz[org].get(a, 0))) if matriz[org].get(a) else '—'}</td>" for a in p["anos"])
            body += f"<tr><td>{esc(org)}</td>{cells}<td><b>R$ {moeda(tot_org)}</b></td></tr>"
        body += ("<tr><th>TOTAL</th>" + "".join(f"<th>R$ {moeda(tot_ano.get(a, 0))}</th>" for a in p["anos"])
                 + f"<th>R$ {moeda(p['total_geral'])}</th></tr>")
        spark = C.sparkline([p["por_ano"][a]["total"] for a in p["anos"]], "Total pago por ano")
        # transparência da consolidação: se a empresa tem matriz+filiais (mesma raiz), mostra a quebra
        estab = p.get("por_estabelecimento") or []
        estab_html = ""
        if len(estab) > 1:
            linhas_e = "".join(
                f"<tr><td>{fmt_cnpj(e['cnpj'])}</td><td>{esc(e['tipo'])}</td><td>{esc(e['nome'])}</td>"
                f"<td>{e['n']}</td><td>R$ {moeda(e['total'])}</td></tr>" for e in estab)
            estab_html = (f"<p class='nota'>Empresa consolidada pela <b>raiz {p.get('raiz')}</b> "
                          f"({len(estab)} estabelecimentos — matriz + filiais são <b>uma só pessoa jurídica</b>, "
                          "CC arts. 44/985/1.142 e STJ REsp 1.286.122; o Estado paga cada estabelecimento pelo CNPJ próprio):</p>"
                          "<table><tr><th>CNPJ</th><th>Tipo</th><th>Razão social (na OB)</th><th>OBs</th><th>Pago</th></tr>"
                          f"{linhas_e}</table>")
        secoes.append({"titulo": "5. Pagamentos (Ordens Bancárias) — por Órgão (UG) × Ano",
                       "html": "<p class='nota'>OB = pagamento (dado definitivo, SIAFE/TFE-RJ). Cada célula = total pago "
                               f"àquele órgão naquele exercício ({p['n_geral']} OBs no total). Detalhe por OB individual no XLSX.</p>"
                               + estab_html
                               + f"<table>{thead}{body}</table>",
                       "chart": spark})

        # 5-B. Pagamentos MÊS A MÊS — Órgão × Mês × Ano-exercício (pedido do dono: granularidade mensal de volta)
        mma = p.get("por_orgao_mes_ano") or []
        if mma:
            MESES = {1: "Jan", 2: "Fev", 3: "Mar", 4: "Abr", 5: "Mai", 6: "Jun",
                     7: "Jul", 8: "Ago", 9: "Set", 10: "Out", 11: "Nov", 12: "Dez", 0: "S/data"}
            presentes = sorted({m for row in mma for m in row["meses"]}, key=lambda m: (m == 0, m))

            def _mc(v):  # valor compacto p/ caber 12+ colunas no A4
                if not v:
                    return "—"
                if abs(v) >= 1e6:
                    return f"{v / 1e6:.2f} mi"
                if abs(v) >= 1e3:
                    return f"{v / 1e3:.0f} mil"
                return f"{v:.0f}"

            thead2 = ("<tr><th>Órgão (UG)</th><th>Exerc.</th>"
                      + "".join(f"<th>{MESES[m]}</th>" for m in presentes) + "<th>Total</th></tr>")
            body2 = ""
            for row in mma:
                cells = "".join(f"<td>{_mc(row['meses'].get(m, 0))}</td>" for m in presentes)
                body2 += (f"<tr><td>{esc(row['orgao'])}</td><td>{row['ano']}</td>{cells}"
                          f"<td><b>R$ {moeda(row['total'])}</b></td></tr>")
            secoes.append({"titulo": "5-B. Pagamentos mês a mês (Órgão × Mês × Ano-exercício)",
                           "html": "<p class='nota'>Granularidade mensal das OBs por órgão e exercício (complementa a tabela "
                                   "cruzada acima). Células em forma compacta (mi = milhões, mil = milhares); o Total fica em "
                                   "precisão cheia e o detalhe por OB individual vai no XLSX. Útil para flagrar pagamentos "
                                   "concentrados em meses atípicos — fim de exercício / véspera eleitoral (red flag ACFE).</p>"
                                   f"<table>{thead2}{body2}</table>"})

        # 5-C. DETALHAMENTO POR OB — cada pagamento com VALOR EXATO + nº da OB (pedido do dono 2026-06-09):
        # nos meses com 2-3 OBs, a 5-B agrega num só número compacto; aqui cada OB aparece em sua linha,
        # com o valor exato e o código da OB. Recente → antigo; lista completa também no XLSX.
        linhas_ob = []
        for _ano, _b in (p.get("por_ano") or {}).items():
            for _ln in _b.get("linhas", []):
                _d = _ln.get("data") or "—"
                _ok = isinstance(_d, str) and len(_d) >= 7 and _d[4:5] == "-"
                _mes = int(_d[5:7]) if _ok else 0
                linhas_ob.append((int(_ano or 0), _mes, _ln, (f"{_d[5:7]}/{_d[0:4]}" if _ok else "s/data")))
        if linhas_ob:
            _LIM = 400
            linhas_ob.sort(key=lambda t: (t[0], t[1], float(t[2].get("valor") or 0)), reverse=True)
            _total_ob = len(linhas_ob)
            _rows = "".join(
                f"<tr><td>{esc(comp)}</td><td>{esc(ln.get('numero_ob') or '—')}</td>"
                f"<td>{esc(ln.get('orgao') or '—')}</td><td>R$ {moeda(ln.get('valor'))}</td></tr>"
                for _a, _m, ln, comp in linhas_ob[:_LIM])
            _nota_cap = (f" Mostrando as {_LIM} OBs mais recentes de {_total_ob}; a lista completa (todas as OBs) "
                         "está na planilha XLSX." if _total_ob > _LIM else "")
            secoes.append({"titulo": "5-C. Detalhamento por OB — valor exato + nº da OB (por mês)",
                           "html": "<p class='nota'>Cada Ordem Bancária com o <b>valor exato</b> e o <b>número da OB</b>, "
                                   "do mês mais recente para o mais antigo. Quando um mês tem dois ou mais pagamentos, "
                                   f"cada um aparece em sua própria linha (a seção 5-B agrega por mês).{_nota_cap}</p>"
                                   "<table><tr><th>Competência</th><th>OB nº</th><th>Órgão (UG)</th>"
                                   f"<th>Valor (R$)</th></tr>{_rows}</table>"})

        # 6. Concentração por órgão (HHI) + barras
        tot = p["total_geral"] or 1
        orgs = list(p["por_orgao_geral"].items())
        bars = C.barras([o for o, _ in orgs[:8]], [v / tot for _, v in orgs[:8]], "Concentração por órgão")
        rows = "".join(f"<tr><td>{esc(o)}</td><td>R$ {moeda(v)}</td><td>{v / tot * 100:.1f}%</td></tr>" for o, v in orgs)
        flag = ("<p class='nota'>🔴 Red flag (ACFE): concentração ≥60% num único órgão sem justificativa pede verificação (Art. 37 CF/88).</p>"
                if p["hhi"].get("top_share", 0) >= 60 else "")
        secoes.append({"titulo": f"6. Concentração por órgão — HHI {p['hhi'].get('indice')} ({p['hhi'].get('nivel')}; maior = {p['hhi'].get('top_share')}%)",
                       "html": f"{flag}<table><tr><th>Órgão (UG)</th><th>Valor pago</th><th>%</th></tr>{rows}</table>",
                       "chart": bars})

    # 7. Contratos — base local (compliance.db) OU TCE-RJ Dados Abertos (fonte oficial, independe do SEI)
    c = ctx["contratos"]
    tcerj_itens = ctx.get("tcerj_itens") or []
    tcerj_contr = [i for i in tcerj_itens if i.get("_tipo") == "contrato"]
    contratado = float(ctx.get("contratado_tcerj") or 0)
    pago = float(p.get("total_geral") or 0)
    if c["n"]:
        rows = "".join(f"<tr><td>{esc(ln['numero'])}</td><td>{esc(ln['objeto'])}</td><td>{esc(ln['orgao'])}</td>"
                       f"<td>R$ {moeda(ln['valor'])}</td><td>{esc(ln['status'])}</td></tr>" for ln in c["linhas"])
        secoes.append({"titulo": f"7. Carteira de contratos ({c['n']} — R$ {moeda(c['total'])})",
                       "html": f"<table><tr><th>Nº</th><th>Objeto</th><th>Órgão</th><th>Valor</th><th>Situação</th></tr>{rows}</table>"})
    elif tcerj_contr:
        tcerj_contr.sort(key=lambda i: (i.get("valor_contrato") or 0), reverse=True)
        rows = "".join(f"<tr><td>{esc(i.get('numero') or i.get('processo'))}</td>"
                       f"<td>{esc((i.get('objeto') or '—')[:70])}</td><td>{esc(i.get('orgao') or i.get('unidade') or '—')}</td>"
                       f"<td>R$ {moeda(i.get('valor_contrato'))}</td></tr>" for i in tcerj_contr[:15])
        gap = (f" <b>Pago (OB) R$ {moeda(pago)} = {pago/contratado:.1f}× o contratado</b> — possíveis aditivos/contratos "
               "não listados, a verificar." if contratado and pago > contratado * 1.2 else "")
        secoes.append({"titulo": f"7. Carteira de contratos — TCE-RJ ({len(tcerj_contr)} — R$ {moeda(contratado)})",
                       "html": "<p class='nota'>Fonte: Dados Abertos do TCE-RJ (controle externo; independe do SEI/WAF). "
                               f"Contratado registrado: R$ {moeda(contratado)}.{gap}</p>"
                               f"<table><tr><th>Nº/Processo</th><th>Objeto</th><th>Órgão</th><th>Valor contrato</th></tr>{rows}</table>"})
    else:
        secoes.append({"titulo": "7. Carteira de contratos",
                       "html": "<p class='nota'>Nenhum contrato formal localizado na base local nem no TCE-RJ Dados Abertos "
                               "para este CNPJ (os pagamentos podem decorrer de atas de registro de preços/adesões — verificar).</p>"})

    # 8. Matriz de risco P×I (TCU) + 9. Análise estatística (Benford)
    if p["tem_dados"]:
        _prob = max(1, min(round((ctx.get("score", 0) or 0) / 11) + 1, 9))
        _imp = max(1, min(round((p["hhi"].get("top_share", 0) or 0) / 100 * 9) + 1, 9))
        secoes.append({"titulo": "8. Matriz de risco P×I (metodologia TCU)",
                       "html": "<p class='nota'>Probabilidade × Impacto (1–9). ✕ marca a posição do achado.</p>",
                       "chart": C.heatmap_pxi(_prob, _imp)})
        try:
            from compliance_agent.analysis.benford import benford
            vals = [ln.get("valor") or 0 for a in p["anos"] for ln in p["por_ano"][a].get("linhas", []) if (ln.get("valor") or 0) > 0]
            bf = benford(vals)
            d1 = bf["primeiro_digito"]
            secoes.append({"titulo": "9. Análise estatística (Lei de Benford)",
                           "html": f"<p class='nota'>1º dígito dos valores de OB (n={d1['n']}). MAD de Nigrini = <b>{d1['mad']}</b> "
                                   f"→ <b>{d1['faixa_nigrini']}</b>. {'Conforme = sem sinal de fracionamento/fabricação.' if 'CONFORM' in d1['faixa_nigrini'].upper() or 'conformidade' in d1['faixa_nigrini'] else 'NÃO conformidade pede verificação (fracionamento/valores fabricados).'} "
                                   f"{'(amostra pequena — pouco confiável)' if not bf['suficiente'] else ''}</p>"})
        except Exception:  # noqa: BLE001
            pass

        # 9-B. Anomalias nas OBs (modelo de detecção) — paridade com o MD §8-C
        _an = _anomalias_fornecedor(cnpj)
        if _an.get("ok"):
            _ai = _an.get("itens") or []
            if _ai:
                _ar = "".join(f"<tr><td>{it['score']:.3f}</td><td>{esc(it.get('ob', '-'))}</td>"
                              f"<td>{esc(moeda(it.get('valor')))}</td><td>{esc(str(it.get('data', '-')))}</td></tr>"
                              for it in _ai[:12])
                _ah = (f"<p class='nota'>Das {_an['n_obs']} OBs pontuadas, <b>{_an['n_anomalas']}</b> com score alto "
                       "(≥0,70) de anomalia (valor/frequência/dia/UG). Indício de pagamento atípico a inspecionar "
                       "(lastro/contrato/medição) — não prova.</p>"
                       f"<table><tr><th>Score</th><th>OB</th><th>Valor</th><th>Data</th></tr>{_ar}</table>")
            else:
                _ah = (f"<p class='nota'>{_an['n_obs']} OBs pontuadas, nenhuma com score alto — sem anomalia "
                       "destacada pelo modelo (não afasta outras irregularidades).</p>")
            secoes.append({"titulo": "9-B. Anomalias nas Ordens Bancárias (modelo de detecção)", "html": _ah})

    # 10. Co-endereço / sócios em comum (sinal de cartel/laranja) — sempre presente (sem buraco de numeração)
    coend = (ctx.get("cruzamento") or {}).get("coendereco") or []
    if coend:
        rows = "".join(f"<tr><td>{esc(x.get('razao') or x.get('cnpj'))}</td><td>{esc(x.get('cnpj'))}</td></tr>" for x in coend[:15])
        secoes.append({"titulo": "10. Empresas no MESMO endereço (sinal de cartel/laranja)",
                       "html": "<p class='nota'>Outras empresas registradas no mesmo endereço da sede — indício de "
                               "fachada/cartel a verificar (não é prova).</p>"
                               f"<table><tr><th>Empresa</th><th>CNPJ</th></tr>{rows}</table>"})
    else:
        secoes.append({"titulo": "10. Empresas no mesmo endereço (cartel/laranja)",
                       "html": "<p class='nota'>Nenhuma outra empresa no mesmo endereço da sede localizada na base "
                               "(não exclui co-endereço fora da base; verificar no RedeCNPJ — seção 4-D).</p>"})

    # 11. Red flags consolidados (com fundamento) — agora alimentados pela CALIBRAGEM (sinais reais)
    cal = ctx.get("calibragem") or {}
    pago = float(p.get("total_geral") or 0)
    contratado = float(ctx.get("contratado_tcerj") or 0)
    flags = []
    if p.get("hhi", {}).get("top_share", 0) >= 60:
        flags.append("🔴 Concentração ≥60% num único órgão (isonomia/impessoalidade — Art. 37 CF/88; ACFE).")
    if contratado and pago > contratado * 1.5:
        flags.append(f"🔴 Pago (R$ {moeda(pago)}) ≫ contratado registrado no TCE-RJ (R$ {moeda(contratado)}) — "
                     f"{pago/contratado:.1f}×: aditivos sucessivos (>25%/50% — arts. 125-126 Lei 14.133) ou contratos não publicados, a verificar.")
    elif contratado and pago > contratado * 1.2:
        flags.append(f"🟡 Pago acima do contratado registrado ({pago/contratado:.1f}×) — verificar aditivos/atas de adesão.")
    if rede:
        flags.append("🟡 Doador eleitoral (empresa/sócio) que é fornecedor — conflito de interesse a verificar (TSE×contratos).")
    if _crescimento(p) >= 4:
        flags.append(f"🟡 Crescimento de faturamento atípico (pico/base = {_crescimento(p):.1f}×) — verificar capacidade operacional vs. salto de receita pública.")
    if coend:
        flags.append("🟡 Empresa(s) no mesmo endereço — possível fachada/cartel (Art. 90 Lei 8.666/Art. 337-F CP).")
    # §8-C: alta fração de OBs anômalas (modelo PyOD) — sinal que agora também pesa no score (P1.2).
    _an = ctx.get("anomalias") or {}
    if _an.get("ok") and (_an.get("n_obs") or 0) > 0:
        _frac = (_an.get("n_anomalas") or 0) / _an["n_obs"]
        if _frac >= 0.15 and (_an.get("n_anomalas") or 0) >= 2:
            flags.append(f"🟡 {_frac*100:.0f}% das OBs com score alto de anomalia (§8-C, ensemble não supervisionado) — "
                         f"pagamentos atípicos a inspecionar.")
    # RF-04/05 (controle societário · CNAE×objeto): fonte ÚNICA em _red_flags(ctx) p/ MD e PDF concordarem.
    for _tit, _desc, _f in _red_flags(ctx):
        if _tit.startswith(("RF-04", "RF-05")):
            _resumo = _desc.split(". ")[0].replace("**", "")
            flags.append("🟡 " + esc(_tit.split("—", 1)[-1].strip()) + ": " + esc(_resumo) + ".")
    if not flags:
        flags.append("🟢 Sem red flags estruturais automáticos nesta triagem (não exclui exame manual).")
    nota_cal = (f"<p class='nota'>Risco JFN recalibrado: <b>{esc(ctx.get('risco'))}</b> (score {ctx.get('score')}/100 = "
                f"máx[externo {cal.get('score_externo',0)}, interno {cal.get('score_interno',0)}]). "
                "O score interno incorpora os sinais REAIS do relatório — inclusive rede mesma-sede (§1-B) e "
                "anomalias nas OBs (§8-C) — com peso conservador. "
                "Indícios a verificar, nunca acusação (presunção de legitimidade).</p>") if cal else ""
    secoes.append({"titulo": "11. Red flags de compliance (fundamento legal)",
                   "html": nota_cal + "<ul>" + "".join(f"<li>{esc(f)}</li>" for f in flags) + "</ul>"})
    # 11-B. ANÁLISE RACIOCINADA — síntese de IA que CONECTA os achados (cruzamento), sobre os FATOS coletados.
    raciocinio = ctx.get("raciocinio")
    if raciocinio:
        corpo = "".join(f"<li>{esc(b[2:].strip())}</li>" for b in raciocinio.splitlines() if b.strip().startswith("- "))
        corpo_html = f"<ul>{corpo}</ul>" if corpo else f"<p>{esc(raciocinio)}</p>"
        secoes.append({"titulo": "11-B. Análise raciocinada — cruzamento dos achados",
                       "html": corpo_html + "<p class='nota'>Síntese gerada por IA <b>a partir dos fatos coletados "
                               "neste relatório</b> (não inventa dados); indícios para apuração, jamais conclusão de "
                               "irregularidade. O parecer estruturado e os red flags acima permanecem como base.</p>"})
    # recomendações dirigidas pelos achados reais (coerentes com o risco recalibrado)
    if contratado and pago > contratado * 1.5:
        imediato = (f"<b>Imediato:</b> requisitar os termos aditivos e as atas/adesões que expliquem o pago "
                    f"(R$ {moeda(pago)}) ser {pago/contratado:.1f}× o contratado registrado (R$ {moeda(contratado)}) — "
                    "checar limites de 25%/50% (arts. 125-126 Lei 14.133).")
    elif p.get("hhi", {}).get("top_share", 0) >= 40:
        imediato = "<b>Imediato:</b> verificar a motivação técnica da concentração e a pesquisa de preços dos maiores contratos."
    elif (ctx.get("risco") or "").upper() in ("ALTO", "MÉDIO"):
        imediato = "<b>Imediato:</b> abrir diligência sobre os indícios da seção 11 (priorizar os 🔴/🟡 de maior valor)."
    else:
        imediato = "<b>Imediato:</b> manter monitoramento de rotina."
    rec = [imediato,
           "<b>Curto prazo:</b> cruzar doações eleitorais dos sócios com as datas de contratação (conflito de interesse)." if rede else "<b>Curto prazo:</b> confirmar QSA e capacidade operacional (anti-fachada).",
           "<b>Estrutural:</b> consolidar no Radar 24/7 (alerta em novo edital/OB do alvo) e gerar minuta de diligência (TCE-RJ/ALERJ) se confirmado."]
    secoes.append({"titulo": "12. Recomendações (priorizadas)",
                   "html": "<ul>" + "".join(f"<li>{r}</li>" for r in rec) + "</ul>"})
    secoes.append({"titulo": "13. Referências normativas",
                   "html": "<p class='nota'>CF/88 art. 37 e 70-71 · Lei 14.133/2021 · Lei 8.666/93 (contratos vigentes) · "
                           "Lei 4.320/64 (OB = pagamento) · jurisprudência TCU/TCE-RJ (direcionamento, sobrepreço, fracionamento) · "
                           "metodologia P×I (TCU) e red flags (ACFE Report to the Nations).</p>"})

    faixa = (ctx.get("risco") or "BAIXO").upper()
    top = (["concentração ≥60%"] if p.get("hhi", {}).get("top_share", 0) >= 60 else []) + (["doação↔contrato"] if rede else [])
    ctx_html = {
        "_dados": {"cnpj": cnpj, "total": p.get("total_geral"), "score": ctx.get("score")},
        "titulo": f"Relatório de Inteligência — {ctx['nome']}",
        "subtitulo": f"CNPJ {ctx['cnpj_fmt']} · Due Diligence de Integridade · Exposição Financeira · Risco & Compliance",
        "classificacao": "CONFIDENCIAL — USO INTERNO (controle externo)",
        "score": ctx.get("score", 0), "faixa": faixa, "top_flags": top, "secoes": secoes,
        "metodologia": "Due diligence Nível II + red flags TCU/TCE-RJ + conflito TSE",
        "proveniencia": [
            {"dado": "Pagamentos (OB)", "estado": "REAL", "fonte": "SIAFE/TFE", "data": ctx["data"]},
            {"dado": "Cadastro/QSA", "estado": "REAL" if emp else "INDISPONÍVEL", "fonte": "BrasilAPI", "data": ctx["data"]},
            {"dado": "Doações eleitorais", "estado": "REAL", "fonte": "TSE", "data": ctx["data"]},
        ],
    }
    return await html_to_pdf(render_html(ctx_html), destino)


def render_pdf(ctx: dict, destino: str) -> str:
    """Gera o PDF due-diligence (inclui as tabelas de OBs por ano). Retorna o caminho salvo."""
    from fpdf import FPDF

    p = ctx["pagamentos"]
    cor_risco = {"ALTO": (220, 53, 69), "MÉDIO": (255, 150, 0), "BAIXO": (40, 167, 69)}.get(ctx["risco"], (90, 90, 90))

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=14)
    # Fonte Unicode (DejaVu) p/ acentos e travessões; fallback p/ core latin-1.
    pdf._fam, pdf._uni = _registrar_fonte(pdf)
    pdf.add_page()

    def _t(s: str) -> str:
        s = s or ""
        if getattr(pdf, "_uni", False):
            return s  # fonte Unicode: passa direto
        # core latin-1: normaliza símbolos comuns fora do latin-1
        for a, b in (("—", "-"), ("–", "-"), ("₂", "2"), ("’", "'"), ("“", '"'), ("”", '"'), ("•", "-")):
            s = s.replace(a, b)
        return s.encode("latin-1", "replace").decode("latin-1")

    # Capa
    pdf.set_fill_color(20, 30, 50); pdf.set_text_color(255, 255, 255)
    pdf.set_font(pdf._fam, "B", 16)
    pdf.cell(0, 13, _t("RELATÓRIO DE INTELIGÊNCIA DE FORNECEDOR"), fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
    pdf.set_font(pdf._fam, "", 9); pdf.set_fill_color(45, 60, 90)
    pdf.cell(0, 7, _t("Due Diligence de Integridade · Exposição Financeira · Risco & Compliance"), fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
    pdf.cell(0, 7, _t(f"JFN Intelligence Engine  |  {ctx['data']}"), fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
    pdf.ln(4)
    pdf.set_text_color(0, 0, 0); pdf.set_font(pdf._fam, "B", 14)
    _mc(pdf, 8, _t(ctx["nome"]))
    pdf.set_font(pdf._fam, "", 10)
    pdf.cell(0, 6, _t(f"CNPJ: {ctx['cnpj_fmt']}"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(2)
    pdf.set_fill_color(*cor_risco)
    pdf.set_text_color(0, 0, 0) if ctx["risco"] == "MÉDIO" else pdf.set_text_color(255, 255, 255)
    pdf.set_font(pdf._fam, "B", 12)
    pdf.cell(70, 9, _t(f"  RISCO: {ctx['risco']}   Score: {ctx['score']}/100"), fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_text_color(0, 0, 0); pdf.ln(3)
    pdf.set_font(pdf._fam, "", 9)
    _mc(pdf, 5, _t(_resumo_executivo(ctx)))
    pdf.ln(2)
    pdf.set_font(pdf._fam, "I", 7); pdf.set_text_color(110, 110, 110)
    _mc(pdf, 4, _t(f"Fonte: OBs/contratos = REAL (SIAFE/TFE) · perfil/sanções/rede = {ctx['fonte_enriq']}. "
                            "OB = pagamento (dado definitivo). Empenho ≠ pagamento."))
    pdf.set_text_color(0, 0, 0)

    # Exposição por exercício
    if p["tem_dados"]:
        pdf.ln(4); pdf.set_font(pdf._fam, "B", 12)
        pdf.cell(0, 8, _t("Exposição financeira — pagamentos por exercício"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        _tab_header(pdf, [("Exercício", 40), ("Nº OBs", 30), ("Valor pago (R$)", 80)])
        pdf.set_font(pdf._fam, "", 9)
        for a in p["anos"]:
            b = p["por_ano"][a]
            _tab_row(pdf, [(str(a), 40, "L"), (str(b["n"]), 30, "R"), (moeda(b["total"]), 80, "R")])
        pdf.set_font(pdf._fam, "B", 9)
        _tab_row(pdf, [("Total", 40, "L"), (str(p["n_geral"]), 30, "R"), (moeda(p["total_geral"]), 80, "R")])

    # Tabelas de OBs por ano (requisito)
    if p["tem_dados"]:
        for a in p["anos"]:
            b = p["por_ano"][a]
            pdf.add_page()
            pdf.set_font(pdf._fam, "B", 13); pdf.set_text_color(20, 30, 50)
            pdf.cell(0, 9, _t(f"Pagamentos (OBs) — exercício {a}"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.set_text_color(0, 0, 0); pdf.set_font(pdf._fam, "", 9)
            _maiores = sorted(b["linhas"], key=lambda ln: -(ln.get("valor") or 0))[:12]
            _nota = f"{b['n']} OBs — Total pago: R$ {moeda(b['total'])}" + (
                f"  ·  {len(_maiores)} maiores abaixo; lista completa na planilha XLSX" if b["n"] > len(_maiores) else "")
            pdf.cell(0, 6, _t(_nota), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.ln(1)
            _tab_header(pdf, [("#", 10), ("Nº OB", 28), ("Data", 24), ("Órgão (UG)", 90), ("Valor (R$)", 36)])
            pdf.set_font(pdf._fam, "", 7)
            for i, ln in enumerate(_maiores, 1):
                _tab_row(pdf, [(str(i), 10, "R"), (_t(ln["numero_ob"]), 28, "L"), (_t(ln["data"])[:10], 24, "L"),
                               (_t(ln["orgao"])[:56], 90, "L"), (moeda(ln["valor"]), 36, "R")], h=4.5)
            pdf.set_font(pdf._fam, "B", 8)
            _tab_row(pdf, [("", 10, "L"), ("", 28, "L"), ("", 24, "L"),
                           (f"Total {a}", 90, "R"), (moeda(b["total"]), 36, "R")], h=5)

    # Concentração por órgão
    if p["tem_dados"]:
        pdf.add_page()
        pdf.set_font(pdf._fam, "B", 13); pdf.set_text_color(20, 30, 50)
        pdf.cell(0, 9, _t("Concentração por órgão (HHI)"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_text_color(0, 0, 0); pdf.set_font(pdf._fam, "", 9)
        pdf.cell(0, 6, _t(f"HHI {p['hhi'].get('indice')} — concentração {p['hhi'].get('nivel')} "
                          f"(maior órgão = {p['hhi'].get('top_share')}%)"), new_x=XPos.LMARGIN, new_y=YPos.NEXT); pdf.ln(1)
        _tab_header(pdf, [("Órgão (UG)", 120), ("Valor pago (R$)", 40), ("%", 20)])
        pdf.set_font(pdf._fam, "", 8)
        tot = p["total_geral"] or 1
        for org, val in p["por_orgao_geral"].items():
            _tab_row(pdf, [(_t(org)[:78], 120, "L"), (moeda(val), 40, "R"), (f"{val/tot*100:.1f}", 20, "R")], h=5)

    # Contratos
    c = ctx["contratos"]
    if c["n"]:
        pdf.add_page()
        pdf.set_font(pdf._fam, "B", 13); pdf.set_text_color(20, 30, 50)
        pdf.cell(0, 9, _t(f"Carteira de contratos (SIAFE) — {c['n']} contratos / R$ {moeda(c['total'])}"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_text_color(0, 0, 0)
        _tab_header(pdf, [("Nº", 22), ("Objeto", 78), ("Órgão", 38), ("Valor (R$)", 34)])
        pdf.set_font(pdf._fam, "", 7)
        for ln in c["linhas"]:
            _tab_row(pdf, [(_t(ln["numero"])[:14], 22, "L"), (_t(ln["objeto"])[:50], 78, "L"),
                           (_t(ln["orgao"])[:24], 38, "L"), (moeda(ln["valor"]), 34, "R")], h=4.5)

    # Sinais + red flags (texto)
    pdf.add_page()
    pdf.set_font(pdf._fam, "B", 13); pdf.set_text_color(20, 30, 50)
    pdf.cell(0, 9, _t("Sinais de risco e red flags"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_text_color(0, 0, 0); pdf.set_font(pdf._fam, "", 9)
    if ctx["enriq"].get("ok"):
        for s in (ctx["enriq"].get("sinais") or [])[:20]:
            _mc(pdf, 5, _t(f"[{s.get('nivel','')}] {s.get('descricao','')} {('- '+s.get('detalhe','')) if s.get('detalhe') else ''}"))
    else:
        _mc(pdf, 5, _t(f"Perfil/sinais corporativos: {ctx['fonte_enriq']} ({ctx['enriq'].get('_motivo','-')})."))
    pdf.ln(2); pdf.set_font(pdf._fam, "B", 10); pdf.cell(0, 6, _t("Red flags:"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font(pdf._fam, "", 8)
    rf = _red_flags(ctx)
    if rf:
        for titulo, desc, fund in rf:
            pdf.set_font(pdf._fam, "B", 8); _mc(pdf, 4.5, _t(titulo))
            pdf.set_font(pdf._fam, "", 8); _mc(pdf, 4.5, _t(desc))
            pdf.set_font(pdf._fam, "I", 7); _mc(pdf, 4.5, _t("Fundamento: " + fund)); pdf.ln(1)
    else:
        _mc(pdf, 4.5, _t("Nenhum red flag automático a partir dos dados locais."))

    # Parecer jurídico e de mérito (texto corrido) — o diferencial do JFN
    pdf.add_page()
    pdf.set_font(pdf._fam, "B", 14); pdf.set_text_color(20, 30, 50)
    pdf.cell(0, 10, _t("Análise Jurídica e de Mérito — Parecer Preliminar do JFN"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_text_color(0, 0, 0)
    raciocinio = ctx.get("raciocinio")
    if raciocinio:
        pdf.set_font(pdf._fam, "B", 11); pdf.cell(0, 7, _t("Análise raciocinada — cruzamento dos achados"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_font(pdf._fam, "", 10)
        _render_parecer_pdf(pdf, _t, raciocinio)
        pdf.ln(2)
    _render_parecer_pdf(pdf, _t, parecer_fornecedor(ctx))

    pdf.ln(3); pdf.set_font(pdf._fam, "I", 7); pdf.set_text_color(120, 120, 120)
    _mc(pdf, 4, _t("Gerado automaticamente pelo JFN Intelligence Engine. Não substitui análise jurídica especializada."))

    Path(destino).parent.mkdir(parents=True, exist_ok=True)
    pdf.output(destino)
    return destino


def _emit_md_table(pdf, _t, block: list):
    """Renderiza um bloco de tabela markdown como TABELA bordada que CABE na largura da página
    (larguras proporcionais ao conteúdo; trunca cada célula p/ não estourar a margem)."""
    import re as _re
    rows = []
    for ln in block:
        if _re.match(r"^\|[\s:\-|]+\|?$", ln):  # linha separadora |---|
            continue
        rows.append([c.strip() for c in ln.strip().strip("|").split("|")])
    if not rows:
        return
    ncol = max(len(r) for r in rows)
    rows = [r + [""] * (ncol - len(r)) for r in rows]
    epw = pdf.epw
    maxlen = [max((len(_re.sub(r"\*\*", "", rows[i][c])) for i in range(len(rows))), default=1) for c in range(ncol)]
    tot = sum(maxlen) or 1
    widths = [max(11.0, epw * ml / tot) for ml in maxlen]
    f = epw / sum(widths)
    widths = [w * f for w in widths]

    def fit(txt, w):
        txt = _t(_re.sub(r"\*\*(.+?)\*\*", r"\1", txt))
        if pdf.get_string_width(" " + txt + " ") <= w:
            return txt
        while txt and pdf.get_string_width(" " + txt + "… ") > w:
            txt = txt[:-1]
        return txt + "…"

    pdf.set_font(pdf._fam, "B", 7.2); pdf.set_fill_color(60, 70, 90); pdf.set_text_color(255, 255, 255)
    pdf.set_x(pdf.l_margin)
    for c in range(ncol):
        pdf.cell(widths[c], 6, " " + fit(rows[0][c], widths[c]), border=1, fill=True)
    pdf.ln(); pdf.set_text_color(0, 0, 0); pdf.set_font(pdf._fam, "", 7.2)
    zebra = False
    for r in rows[1:]:
        pdf.set_fill_color(244, 246, 250) if zebra else pdf.set_fill_color(255, 255, 255)
        zebra = not zebra
        if pdf.get_y() > pdf.h - pdf.b_margin - 6:
            pdf.add_page()
        pdf.set_x(pdf.l_margin)
        for c in range(ncol):
            cell = r[c]
            num = bool(_re.search(r"\d", cell)) and bool(_re.match(r"^[\sR$\d.,%+\-/]+$", cell))
            pdf.cell(widths[c], 5.0, " " + fit(cell, widths[c]), border=1, align=("R" if num else "L"), fill=True)
        pdf.ln()
    pdf.ln(1.5)


def _render_parecer_pdf(pdf, _t, md_text: str):
    """Renderiza o parecer (markdown leve: ###, **negrito**, '- ', '> ', e TABELAS) no PDF, sem estourar a margem."""
    import re as _re
    linhas = md_text.split("\n")
    i, n = 0, len(linhas)
    while i < n:
        raw = linhas[i].rstrip()
        # bloco de tabela markdown
        if raw.startswith("|") and raw.endswith("|"):
            bloco = []
            while i < n and linhas[i].rstrip().startswith("|"):
                bloco.append(linhas[i].rstrip()); i += 1
            _emit_md_table(pdf, _t, bloco)
            continue
        i += 1
        linha = raw
        if not linha:
            pdf.ln(1.5); continue
        if linha.startswith("### "):
            pdf.ln(1); pdf.set_font(pdf._fam, "B", 11); pdf.set_text_color(30, 45, 70)
            _mc(pdf, 6, _t(linha[4:])); pdf.set_text_color(0, 0, 0); continue
        if linha.startswith("## "):  # cabeçalho de seção (antes saía com '##' literal no PDF)
            pdf.ln(1.5); pdf.set_font(pdf._fam, "B", 12); pdf.set_text_color(20, 35, 60)
            _mc(pdf, 6.5, _t(linha[3:])); pdf.set_text_color(0, 0, 0); continue
        if linha.startswith("# "):
            pdf.ln(2); pdf.set_font(pdf._fam, "B", 13); pdf.set_text_color(20, 30, 50)
            _mc(pdf, 7, _t(linha[2:])); pdf.set_text_color(0, 0, 0); continue
        bullet = linha.startswith("- ")
        quote = linha.startswith("> ")
        txt = linha[2:] if (bullet or quote) else linha
        txt = _re.sub(r"\*\*(.+?)\*\*", r"\1", txt)  # remove negrito md
        if quote:
            pdf.set_font(pdf._fam, "I", 8.5); pdf.set_text_color(90, 90, 90)
            _mc(pdf, 4.6, _t(txt)); pdf.set_text_color(0, 0, 0)
        elif bullet:
            pdf.set_font(pdf._fam, "", 9); _mc(pdf, 4.8, _t("•  " + txt))
        else:
            pdf.set_font(pdf._fam, "", 9); _mc(pdf, 4.8, _t(txt))


def _mc(pdf, h: float, txt: str, **kw):
    """multi_cell robusto: reseta X para a margem e usa a largura efetiva da página (evita o
    erro 'Not enough horizontal space' quando o cursor ficou deslocado por uma tabela larga)."""
    pdf.set_x(pdf.l_margin)
    pdf.multi_cell(pdf.epw, h, txt, **kw)


def _tab_header(pdf, cols: list[tuple]):
    pdf.set_fill_color(60, 70, 90); pdf.set_text_color(255, 255, 255); pdf.set_font(pdf._fam, "B", 8)
    for txt, w in cols:
        pdf.cell(w, 6, " " + txt, fill=True, border=1)
    pdf.ln(); pdf.set_text_color(0, 0, 0)


def _tab_row(pdf, cells: list[tuple], h: float = 5.5):
    fill = getattr(pdf, "_zebra", False)
    pdf.set_fill_color(244, 246, 250) if fill else pdf.set_fill_color(255, 255, 255)
    pdf._zebra = not fill
    for txt, w, align in cells:
        pdf.cell(w, h, " " + str(txt), border=1, align=align, fill=True)
    pdf.ln()
