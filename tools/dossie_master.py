#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Documento-MESTRE do caso ONG Con-tato × Ambiente Jovem × SOLAZER × Emendatio × Pampolha.

Monta UM ÚNICO PDF com:
  (1) a peça analítica (tools/dossie_emendatio.build_html → HTML→PDF Kroll: mapa do dinheiro,
      contrato/aditivos, controle, SOLAZER, Emendatio, Pampolha/TCE, núcleos, FECAM, contratados),
  (2) ANEXO A — íntegra do processo SEI-070026/000705/2021 (contrato de gestão + aditivos +
      prestação de contas), se já baixada (data/sei_cache/INTEGRA_070026_000705_2021.pdf),
  (3) ANEXO B — íntegra do processo/acórdão do TCE-RJ (data/tce_processo.pdf), se disponível,
e um SUMÁRIO EXECUTIVO CLICÁVEL = outline/bookmarks do PDF (com subitens), gerado localizando cada
título de seção pela página (fitz.search_for). Assim o leitor navega pela barra lateral.

Uso: PYTHONPATH=. .venv/bin/python tools/dossie_master.py [--enviar]
"""
from __future__ import annotations

import re
import sys
from datetime import datetime
from pathlib import Path

import fitz  # PyMuPDF

REPO = Path(__file__).resolve().parent.parent
SEI_INTEGRA = REPO / "data" / "sei_cache" / "INTEGRA_070026_000705_2021.pdf"
INSTRUMENTOS = REPO / "data" / "aj_instrumentos"   # instrumentos públicos (contrato+aditivos+prest.contas)
TCE_DOCS = REPO / "data" / "tce_docs"              # peças individuais do processo TCE (doc_N.pdf)
TCE_PDF = REPO / "data" / "tce_processo.pdf"
CEDAE_ATOS = REPO / "data" / "cedae_atos"          # atos societários da CEDAE (atas do CA, DOERJ)
PROC_INTEGRA = REPO / "data" / "proc_integra"      # processos administrativos na íntegra (1 PDF/processo, c/ toc por doc)

# Anexo C — atos da CEDAE (fonte primária: atas do Conselho de Administração / portal RI + DOERJ)
_CEDAE_ORDEM = [
    ("Ata_827a_CA_10-10-2025.pdf", "Ata 827ª do Conselho de Administração (10/10/2025) — eleição de José Ricardo F. de Brito (DSG)"),
    ("Ata_833a_CA_26-11-2025.pdf", "Ata 833ª do Conselho de Administração (26/11/2025) — eleição de Philipe Campello (DSU) + criação da Diretoria de Sustentabilidade"),
    ("Regimento_Interno_CEDAE.pdf", "Regimento Interno da CEDAE (consolidado pós-AGE 26/11/2025)"),
]


def _headers(html: str) -> list[tuple[int, str]]:
    """Extrai, em ordem, (nível, título) de todos os <h2> (nível 1) e <h3> (nível 2) do HTML —
    limpa tags internas e macros. É a base do índice clicável (cada título e subitem)."""
    out = []
    for m in re.finditer(r"<h([23])[^>]*>(.*?)</h\1>", html, re.S):
        txt = re.sub(r"<[^>]+>", "", m.group(2))
        txt = re.sub(r"\s+", " ", txt).strip()
        if txt and "{{" not in txt:
            out.append((int(m.group(1)) - 1, txt))
    return out


def _injeta_indice(html: str, heads: list[tuple[int, str]]) -> str:
    """Insere ids nos h2/h3 e uma PÁGINA DE ÍNDICE VISÍVEL (com links clicáveis <a href='#id'>)
    logo após a capa. Cada seção e subitem vira um link que salta para o ponto no PDF."""
    idx = {"i": 0}

    def _id(m):
        idx["i"] += 1
        return f"<h{m.group(1)} id=\"s{idx['i']}\"{m.group(2)}>"

    html = re.sub(r"<h([23])([^>]*)>", _id, html, count=len(heads))
    linhas = []
    for i, (lvl, txt) in enumerate(heads, 1):
        cls = "i1" if lvl == 1 else "i2"
        linhas.append(f"<div class='{cls}'><a href='#s{i}'>{txt}</a></div>")
    idx_html = ("<div class='indice'><div class='it'>ÍNDICE CLICÁVEL</div>"
                "<div class='ihint'>Toque num item para saltar até ele. A barra lateral do leitor traz o "
                "índice completo, incluindo cada documento dos Anexos A (instrumentos) e B (processo TCE).</div>"
                + "".join(linhas) + "</div><div style='page-break-after:always'></div>")
    # injeta imediatamente antes do 1º <h2 id="s1"> (a 1ª seção) — robusto a espaçamento
    return re.sub(r'(<h2 id="s1")', idx_html + r"\1", html, count=1)

# ordem de leitura dos instrumentos públicos no Anexo A (contrato → aditivos → execução → auditoria)
_INSTR_ORDEM = [
    ("Contrato_de_Gestao_Contato_SEAS.pdf", "Contrato de Gestão nº 001/2021 (SEAS × ONG Con-tato)"),
    ("1o-termo-aditivo-ao-contrato.pdf", "1º Termo Aditivo (cria 100 auxiliares)"),
    ("2o-termo-aditivo-ao-contrato.pdf", "2º Termo Aditivo (+25 NUPs; +R$ 10,46 mi)"),
    ("3o-termo-aditivo-ao-contrato.pdf", "3º Termo Aditivo (prorrogação)"),
    ("4o-Termo-Aditivo-ao-Contrato-de-Gestao-Ambiente-Jovem.pdf", "4º Termo Aditivo (+R$ 43,30 mi; total R$ 95,81 mi)"),
    ("1o-RELATORIO-AMBIENTE-JOVEM-_FECAM_ANO-02-VERSAO_A.pdf", "Relatório de Execução FECAM — Ano 02"),
    ("Relatorio-de-Execucao-de-Metas-e-Indicadores-Projeto-Ambiente-Jovem.pdf", "Relatório de Metas e Indicadores"),
    ("Qtde-Alunos-AJ-01-x-02.pdf", "Relação de alunos por município (Anos 01 e 02)"),
    ("Relatorio-Auditores-2023.pdf", "Relatório dos Auditores Independentes (31/12/2023)"),
]

# Estrutura do sumário: (nível, título EXATO como aparece no PDF). Nível 1 = seção, 2 = subitem.
# Os títulos batem com os <h2>/<h3> gerados por dossie_emendatio.build_html().
_OUTLINE = [
    (1, "Sumário executivo"),
    (1, "1. Mapa do dinheiro"),
    (2, "Evolução anual"),
    (1, "2. O contrato de gestão do Ambiente Jovem"),
    (2, "Signatários dos instrumentos"),
    (2, "Pagamentos efetivos da SEAS"),
    (1, "3. Estrutura de controle da ONG"),
    (1, "4. Segundo veículo do mesmo operador"),
    (1, "5. Operação Emendatio"),
    (2, "Presos e investigados"),
    (2, "Volume financeiro apontado"),
    (2, "Parlamentares que destinaram emendas"),
    (1, "6. Thiago Pampolha"),
    (1, "7. Núcleos de Pertencimento"),
    (1, "8. FECAM"),
    (1, "Contratados do projeto"),
    (2, "Contratados que já foram candidatos"),
    (2, "Contratados que constam recebendo benefício"),
    (1, "9. José Ricardo Ferreira de Brito"),
    (1, "10. CEDAE — o acordo de R$ 900"),
    (1, "11. INEA e SEAS na gestão Pampolha"),
    (1, "12. Repasses de 2017"),
    (1, "13. Situação processual"),
    (1, "14. Em apuração"),
]


def _pagina_do_titulo(doc, titulo: str, ini: int = 0) -> int:
    """1ª página (1-based) onde o título aparece, a partir de `ini`. 0 se não achar."""
    for pno in range(ini, doc.page_count):
        if doc[pno].search_for(titulo, quads=False):
            return pno + 1
    return 0


def _pagina_indice(doc) -> int:
    """Página (0-based) da PÁGINA DE ÍNDICE VISÍVEL; -1 se não houver. A resolução dos títulos
    tem de começar DEPOIS dela — senão cada título casa primeiro na lista do índice (que traz
    todos), e todos os bookmarks caem na página 1."""
    for pno in range(min(5, doc.page_count)):
        if doc[pno].search_for("ÍNDICE CLICÁVEL"):
            return pno
    return -1


def construir_outline(doc, heads: list, base_offset: int = 0) -> list:
    """Bookmarks da peça analítica = TODOS os títulos/subitens (h2/h3) extraídos, na ordem,
    cada um mapeado à sua 1ª página REAL (busca começa após a página de índice). Prefixo p/
    não quebrar em títulos longos."""
    piso = _pagina_indice(doc) + 1  # 0 se não houver índice; senão, 1ª página após o índice
    toc, ultimo = [], piso
    for nivel, titulo in heads:
        alvo = titulo[:38]
        p = _pagina_do_titulo(doc, alvo, max(piso, ultimo - 1)) or _pagina_do_titulo(doc, alvo, piso)
        if p:
            toc.append([nivel, titulo[:70], p + base_offset])
            ultimo = p
    return toc


def _linkar_indice(doc, outline: list) -> int:
    """Torna a PÁGINA DE ÍNDICE VISÍVEL de fato clicável: cada linha de título vira um link
    (LINK_GOTO) para a página resolvida no bookmark. Corrige o fato de o Playwright não
    converter as âncoras <a href='#sN'> em links de PDF. Retorna nº de links inseridos."""
    idxpg = _pagina_indice(doc)
    if idxpg < 0:
        return 0
    page = doc[idxpg]
    n = 0
    for nivel, titulo, destino in outline:
        if destino - 1 <= idxpg:  # só os títulos analíticos que estão listados no índice
            continue
        rects = page.search_for(titulo[:34])
        if not rects:
            continue
        page.insert_link({"kind": fitz.LINK_GOTO, "from": rects[0],
                          "page": destino - 1, "to": fitz.Point(0, 0)})
        n += 1
    return n


async def montar() -> str:
    from compliance_agent.reporting.render_html import html_to_pdf
    from tools.dossie_emendatio import build_html

    # 1) peça analítica — com ÍNDICE CLICÁVEL injetado (ids nos títulos + página de índice)
    html = build_html()
    heads = _headers(html)
    html = _injeta_indice(html, heads)
    analitico = REPO / "reports" / f"_master_analitico_{datetime.now().date()}.pdf"
    await html_to_pdf(html, str(analitico))
    doc = fitz.open(str(analitico))
    outline = construir_outline(doc, heads)   # bookmarks = todos os títulos e subitens
    _linkar_indice(doc, outline)              # torna a página de índice visível de fato clicável

    # 2) ANEXO A — íntegra dos instrumentos e prestação de contas.
    # Preferência: íntegra do processo SEI (se baixada); senão, os INSTRUMENTOS PÚBLICOS que a própria
    # ONG publica (mesmos documentos substantivos: contrato + 4 aditivos + relatórios FECAM + auditoria).
    anexos = []
    if SEI_INTEGRA.exists():
        base = doc.page_count
        cap = fitz.open(); cap.new_page().insert_text((60, 300),
            "ANEXO A — ÍNTEGRA DO PROCESSO SEI-070026/000705/2021", fontsize=15)
        doc.insert_pdf(cap); outline.append([1, "ANEXO A — Íntegra do processo SEI (contrato + aditivos + prestação de contas)", base + 1])
        cap.close()
        sei = fitz.open(str(SEI_INTEGRA))
        if sei.page_count:
            doc.insert_pdf(sei)
        sei.close()
        anexos.append("SEI")
    elif INSTRUMENTOS.exists():
        base = doc.page_count
        cap = fitz.open(); pg = cap.new_page()
        pg.insert_text((60, 260), "ANEXO A — INSTRUMENTOS E PRESTAÇÃO DE CONTAS (ÍNTEGRA)", fontsize=15)
        pg.insert_textbox(fitz.Rect(60, 285, 535, 420),
            "Fonte: documentos publicados pela própria ONG Con-tato (transparência institucional). "
            "Contrato de Gestão 001/2021, os quatro termos aditivos, relatórios de execução do FECAM, "
            "relação de alunos e o relatório dos auditores independentes. O processo administrativo "
            "interno (SEI-070026/000705/2021) tramita em outra unidade; os documentos substantivos "
            "constam aqui pela via pública oficial da própria contratada.",
            fontsize=10)
        doc.insert_pdf(cap); outline.append([1, "ANEXO A — Instrumentos e prestação de contas (íntegra, fonte pública)", base + 1]); cap.close()
        for arq, titulo in _INSTR_ORDEM:
            fp = INSTRUMENTOS / arq
            if not fp.exists():
                continue
            base = doc.page_count
            sep = fitz.open(); sep.new_page().insert_text((60, 200), f"A.  {titulo}", fontsize=13)
            doc.insert_pdf(sep); outline.append([2, titulo, base + 1]); sep.close()
            try:
                d2 = fitz.open(str(fp))
                if d2.page_count:
                    doc.insert_pdf(d2)
                d2.close()
            except Exception:  # noqa: BLE001 — PDF corrompido não derruba o master
                pass
        anexos.append("instrumentos-públicos")
    # ANEXO B — íntegra do processo TCE-RJ 107.485-1/2016, com um MARCADOR POR PEÇA (doc_N.pdf) para
    # navegar direto a cada documento dos autos. Se as peças individuais não existirem, cai no PDF unido.
    tce_pieces = sorted(TCE_DOCS.glob("doc_*.pdf"),
                        key=lambda p: int(re.search(r"doc_(\d+)", p.name).group(1))) if TCE_DOCS.exists() else []
    if tce_pieces:
        base = doc.page_count
        cap = fitz.open(); pg = cap.new_page()
        pg.insert_text((60, 260), "ANEXO B — PROCESSO TCE-RJ Nº 107.485-1/2016 (ÍNTEGRA)", fontsize=15)
        pg.insert_textbox(fitz.Rect(60, 285, 535, 400),
            "Contrato de Gestão nº 002/2015 — programa \"Esporte RJ\" (Lote 1) — OS SOLAZER O Clube dos "
            "Excepcionais. Auditoria da Subsecretaria de Controle Estadual (2ª CCE). Íntegra das peças "
            f"públicas dos autos ({len(tce_pieces)} documentos), do sistema Consulta de Processos do TCE-RJ.",
            fontsize=10)
        doc.insert_pdf(cap); outline.append([1, "ANEXO B — Processo TCE-RJ 107.485-1/2016 (íntegra)", base + 1]); cap.close()
        for i, fp in enumerate(tce_pieces, 1):
            base = doc.page_count
            sep = fitz.open(); sep.new_page().insert_text((60, 200), f"B.{i}  Peça {i} dos autos", fontsize=13)
            doc.insert_pdf(sep); outline.append([2, f"Peça {i} — TCE 107.485-1/16", base + 1]); sep.close()
            try:
                d2 = fitz.open(str(fp))
                if d2.page_count:
                    doc.insert_pdf(d2)
                d2.close()
            except Exception:  # noqa: BLE001
                pass
        anexos.append("TCE-por-peça")
    elif TCE_PDF.exists():
        base = doc.page_count
        cap = fitz.open(); cap.new_page().insert_text((60, 300),
            "ANEXO B — PROCESSO/ACÓRDÃO DO TCE-RJ", fontsize=15)
        doc.insert_pdf(cap); outline.append([1, "ANEXO B — Processo/acórdão do TCE-RJ", base + 1])
        cap.close()
        tce = fitz.open(str(TCE_PDF))
        if tce.page_count:
            doc.insert_pdf(tce)
        tce.close()
        anexos.append("TCE")

    # ANEXO C — atos da CEDAE (atas do Conselho de Administração + Regimento), um marcador por documento.
    cedae_docs = [(a, t) for a, t in _CEDAE_ORDEM if (CEDAE_ATOS / a).exists()] if CEDAE_ATOS.exists() else []
    if cedae_docs:
        base = doc.page_count
        cap = fitz.open(); pg = cap.new_page()
        pg.insert_text((60, 260), "ANEXO C — ATOS SOCIETÁRIOS DA CEDAE (ÍNTEGRA)", fontsize=15)
        pg.insert_textbox(fitz.Rect(60, 285, 535, 400),
            "Fonte primária: atas do Conselho de Administração da CEDAE (portal de Relações com "
            "Investidores) e Diário Oficial do RJ. Documentam a eleição dos diretores José Ricardo "
            "Ferreira de Brito (DSG) e Philipe Campello (DSU) e a criação da Diretoria de Sustentabilidade. "
            "Registre-se que o Termo de Conciliação de R$ 900 mi NÃO consta de deliberação do Conselho.",
            fontsize=10)
        doc.insert_pdf(cap); outline.append([1, "ANEXO C — Atos societários da CEDAE (íntegra)", base + 1]); cap.close()
        for arq, titulo in cedae_docs:
            base = doc.page_count
            sep = fitz.open(); sep.new_page().insert_textbox(fitz.Rect(60, 190, 535, 320), f"C.  {titulo}", fontsize=12)
            doc.insert_pdf(sep); outline.append([2, titulo[:70], base + 1]); sep.close()
            try:
                d2 = fitz.open(str(CEDAE_ATOS / arq))
                if d2.page_count:
                    doc.insert_pdf(d2)
                d2.close()
            except Exception:  # noqa: BLE001
                pass
        anexos.append("CEDAE-atos")

    # ANEXO D — processos administrativos na íntegra (toda a instrução), um por PDF, com o índice de
    # documentos de CADA processo aninhado no sumário (nível 3 = cada despacho/parecer/medição).
    proc_pdfs = sorted(PROC_INTEGRA.glob("*.pdf")) if PROC_INTEGRA.exists() else []
    if proc_pdfs:
        base = doc.page_count
        cap = fitz.open(); pg = cap.new_page()
        pg.insert_text((60, 260), "ANEXO D — PROCESSOS ADMINISTRATIVOS NA ÍNTEGRA", fontsize=15)
        pg.insert_textbox(fitz.Rect(60, 285, 535, 420),
            "Instrução completa dos processos SEI dos maiores contratos de INEA/SEAS na gestão Pampolha "
            "e do contrato de gestão do Ambiente Jovem — todos os documentos da árvore (declarações do "
            "ordenador, despachos, pareceres, termos, notas técnicas, medições, prestação de contas), com "
            "índice clicável por documento. Fonte: SEI-RJ (leitura autenticada). Documento sem texto "
            "extraível = imagem/anexo; consta do índice.", fontsize=10)
        doc.insert_pdf(cap); outline.append([1, "ANEXO D — Processos administrativos (íntegra da instrução)", base + 1]); cap.close()
        for fp in proc_pdfs:
            base = doc.page_count
            nome = re.sub(r"[-_]+", " ", fp.stem)
            outline.append([2, nome[:70], base + 1])
            try:
                src = fitz.open(str(fp))
                for lvl, tit, p in (src.get_toc() or []):
                    if lvl >= 2:  # os bookmarks por-documento do processo (nível 2 no arquivo) → nível 3 aqui
                        outline.append([3, tit[:70], base + p])
                doc.insert_pdf(src); src.close()
            except Exception:  # noqa: BLE001
                pass
        anexos.append("processos-integra")

    # trava de neutralidade: o entregável não pode carregar nomes internos (pedido do dono). Checa só o
    # texto EXTRAÍVEL da peça analítica (os anexos são documentos oficiais de terceiros). "lex" é
    # ignorado por casar com "Alexandre"/"Complexo"; usa-se \bLex\b só como palavra isolada.
    import re as _re
    _an = "".join(doc[i].get_text() for i in range(min(doc.page_count, 12)))
    _bad = [t for t in ("itkava", "iterj", "jfn", "yoda") if _re.search(r"\b" + t + r"\b", _an, _re.I)]
    if _re.search(r"\bLex\b", _an):
        _bad.append("Lex")
    if _bad:
        raise AssertionError(f"dossiê-mestre contém termo interno proibido: {_bad}")

    doc.set_toc(outline)   # SUMÁRIO CLICÁVEL (bookmarks com subitens)
    saida = REPO / "reports" / f"DOSSIE_MASTER_pampolha_ambientejovem_{datetime.now().date()}.pdf"
    doc.save(str(saida), deflate=True, garbage=4)
    doc.close()
    analitico.unlink(missing_ok=True)
    print(f"MASTER: {saida} | anexos: {anexos or 'nenhum ainda (SEI/TCE pendentes)'} | "
          f"{fitz.open(str(saida)).page_count} págs")
    return str(saida)


if __name__ == "__main__":
    import asyncio
    p = asyncio.run(montar())
    if "--enviar" in sys.argv:
        import os
        import re
        for ln in open(REPO / ".env", encoding="utf-8", errors="replace"):
            m = re.match(r"^\s*([A-Z0-9_]+)\s*=\s*(.*?)\s*$", ln)
            if m:
                os.environ.setdefault(m.group(1), m.group(2).strip().strip('"').strip("'"))
        os.environ["TELEGRAM_CHAT_ID"] = os.environ.get("TELEGRAM_OWNER_ID", "")
        from compliance_agent.notifications.telegram import enviar_arquivo
        asyncio.run(enviar_arquivo(p, caption="📕 DOSSIÊ-MESTRE — Pampolha/Ambiente Jovem/SOLAZER/Emendatio (sumário clicável)",
                                   chat_id=os.environ.get("TELEGRAM_OWNER_ID", "")))
        print("enviado")
