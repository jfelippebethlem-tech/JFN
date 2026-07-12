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

import sys
from datetime import datetime
from pathlib import Path

import fitz  # PyMuPDF

REPO = Path(__file__).resolve().parent.parent
SEI_INTEGRA = REPO / "data" / "sei_cache" / "INTEGRA_070026_000705_2021.pdf"
INSTRUMENTOS = REPO / "data" / "aj_instrumentos"   # instrumentos públicos (contrato+aditivos+prest.contas)
TCE_PDF = REPO / "data" / "tce_processo.pdf"

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
    (1, "9. Repasses de 2017"),
    (1, "10. Situação processual"),
    (1, "11. Em apuração"),
]


def _pagina_do_titulo(doc, titulo: str, ini: int = 0) -> int:
    """1ª página (1-based) onde o título aparece, a partir de `ini`. 0 se não achar."""
    for pno in range(ini, doc.page_count):
        if doc[pno].search_for(titulo, quads=False):
            return pno + 1
    return 0


def construir_outline(doc, base_offset: int = 0) -> list:
    toc, ultimo = [], 0
    for nivel, titulo in _OUTLINE:
        p = _pagina_do_titulo(doc, titulo, max(0, ultimo - 1))
        if not p:
            p = _pagina_do_titulo(doc, titulo, 0)
        if p:
            toc.append([nivel, titulo, p + base_offset])
            ultimo = p
    return toc


async def montar() -> str:
    from compliance_agent.reporting.render_html import html_to_pdf
    from tools.dossie_emendatio import build_html

    # 1) peça analítica
    analitico = REPO / "reports" / f"_master_analitico_{datetime.now().date()}.pdf"
    await html_to_pdf(build_html(), str(analitico))
    doc = fitz.open(str(analitico))
    outline = construir_outline(doc)   # bookmarks da parte analítica

    # 2) ANEXO A — íntegra dos instrumentos e prestação de contas.
    # Preferência: íntegra do SEI (se o reader tiver baixado); senão, os INSTRUMENTOS PÚBLICOS que a
    # própria ONG publica (mesmos documentos substantivos: contrato + 4 aditivos + relatórios FECAM +
    # auditoria). O processo SEI interno (070026/000705/2021) é cross-unit e não abriu pelo reader
    # itkava/ITERJ — limitação de método a resolver; o conteúdo substantivo está coberto pela via pública.
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
            "relação de alunos e o relatório dos auditores independentes. O processo SEI interno "
            "(SEI-070026/000705/2021) é de outra unidade e não foi aberto pelo leitor itkava/ITERJ "
            "(limitação de método a resolver); os documentos substantivos constam aqui pela via pública.",
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
    if TCE_PDF.exists():
        base = doc.page_count
        cap = fitz.open(); cap.new_page().insert_text((60, 300),
            "ANEXO B — PROCESSO/ACÓRDÃO DO TCE-RJ (dano ao erário — OS de esporte)", fontsize=15)
        doc.insert_pdf(cap); outline.append([1, "ANEXO B — Processo/acórdão do TCE-RJ", base + 1])
        cap.close()
        tce = fitz.open(str(TCE_PDF))
        if tce.page_count:
            doc.insert_pdf(tce)
        tce.close()
        anexos.append("TCE")

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
        print("enviado ao Yoda")
