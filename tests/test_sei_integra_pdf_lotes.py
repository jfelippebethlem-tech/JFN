# -*- coding: utf-8 -*-
""""Gerar PDF do processo" em LOTES (`sei_integra_completa.gerar_pdf_lotes`) — complemento do laço doc a doc.

Teste real de 20/11/2026: 30–40× mais rápido, mas o SEI omite documento CALADO (2/738), um documento ruim aborta o
lote ("Erro na manipulação do documento X") e lote grande dá 500. Aqui, com PDFs sintéticos (um marcador por
documento, como o do SEI): corte pelo marcador casado pelo nº SEI, omitido calado não vira arquivo, recusado sai do
lote e o resto é refeito, 500 divide ao meio, e a associação é pelo id/nº — nunca pela posição no PDF.
"""
from __future__ import annotations

import asyncio
import json

import fitz
import pytest

from tools import sei_integra_completa as C

PROC_CARIMBO = "SEI SEI-310003/001042/2025 / pg. {n}"


def _doc(k: int, numero: str, titulo: str | None = None) -> dict:
    return {"t": titulo or f"Despacho {k} ({numero})",
            "u": f"https://sei.rj.gov.br/sei/controlador.php?acao=arvore_visualizar&id_documento={9000 + k}&x=1",
            "pai": ""}


def _pdf_lote(destino, docs: list[dict], ordem: list[int] | None = None, omitir: set = frozenset(),
              vazio: set = frozenset()) -> None:
    """PDF como o do SEI: cada documento começa numa página com marcador de nível 1 (título + nº SEI)."""
    pdf = fitz.open()
    toc = []
    for k in (ordem if ordem is not None else range(len(docs))):
        if k in omitir:
            continue
        x = docs[k]
        toc.append([1, x["t"], pdf.page_count + 1])
        for pag in range(2):
            p = pdf.new_page()
            if k not in vazio:
                p.insert_text((50, 80), f"TEOR DO DOCUMENTO {x['t']} pagina {pag}", fontsize=9)
            p.insert_text((50, 800), f"{x['t']}         " + PROC_CARIMBO.format(n=pdf.page_count), fontsize=6)
    pdf.set_toc(toc)
    pdf.save(str(destino))
    pdf.close()


def _texto(fp) -> str:
    with fitz.open(str(fp)) as d:
        return "".join(p.get_text() for p in d)


def _sei_falso(docs, *, recusar: set = frozenset(), teto_lote: int = 99, omitir: set = frozenset(),
               ordem_reversa: bool = False, chamadas: list | None = None):
    """`pedir(lote, destino)` que imita o SEI: recusa por título, 500 acima de `teto_lote`, omite calado."""
    async def pedir(lote, destino):
        ks = [docs.index(x) for _, x in lote]
        if chamadas is not None:
            chamadas.append(ks)
        ruim = [k for k in ks if k in recusar]
        if ruim:
            return "erro_doc", docs[ruim[0]]["t"]
        if len(ks) > teto_lote:
            return "erro_500", "Erro gerando PDF."
        _pdf_lote(destino, docs, ordem=list(reversed(ks)) if ordem_reversa else ks, omitir=omitir)
        return "ok", ""
    return pedir


def _rodar(docs, tmp_path, **kw):
    pedir = _sei_falso(docs, **{k: v for k, v in kw.items() if k != "tam"})
    return asyncio.run(C.gerar_pdf_lotes(None, docs, tmp_path, pedir=pedir, tam=kw.get("tam", 40)))


def test_corte_por_marcador_grava_cada_documento_no_nome_do_laco(tmp_path):
    docs = [_doc(k, str(120000000 + k)) for k in range(5)]
    r = _rodar(docs, tmp_path)
    assert r["via"] == {k: "pdf_nativo" for k in range(5)}
    for k in range(5):
        t = _texto(tmp_path / f"{k:03d}.pdf")
        assert f"TEOR DO DOCUMENTO Despacho {k} " in t
        assert "SEI SEI-" not in t                   # carimbo do rodapé fora do texto
    donos = json.loads((tmp_path / C.RETOMADA / C.DONOS).read_text())
    assert donos == {f"{k:03d}.pdf": str(9000 + k) for k in range(5)}
    assert not list((tmp_path / C.LOTES_DIR).glob("*.pdf"))   # PDF do lote apagado depois do corte


def test_omitido_calado_nao_vira_arquivo_e_fica_para_o_laco(tmp_path):
    docs = [_doc(k, str(120000000 + k)) for k in range(6)]
    r = _rodar(docs, tmp_path, omitir={3})
    assert r["omitidos"] == [3]
    assert not (tmp_path / "003.pdf").exists()
    assert set(r["via"]) == {0, 1, 2, 4, 5}


def test_recusado_sai_do_lote_e_o_resto_e_refeito(tmp_path):
    docs = [_doc(k, str(120000000 + k)) for k in range(8)]
    chamadas: list = []
    r = asyncio.run(C.gerar_pdf_lotes(None, docs, tmp_path, pedir=_sei_falso(docs, recusar={2}, chamadas=chamadas)))
    assert [e["i"] for e in r["recusados"]] == [2]
    assert "manipulação" in r["recusados"][0]["motivo"]
    assert chamadas == [list(range(8)), [0, 1, 3, 4, 5, 6, 7]]
    assert set(r["via"]) == {0, 1, 3, 4, 5, 6, 7} and not (tmp_path / "002.pdf").exists()


def test_erro_500_divide_o_lote_ao_meio(tmp_path):
    docs = [_doc(k, str(120000000 + k)) for k in range(8)]
    chamadas: list = []
    r = asyncio.run(C.gerar_pdf_lotes(None, docs, tmp_path, pedir=_sei_falso(docs, teto_lote=2, chamadas=chamadas)))
    assert [len(c) for c in chamadas] == [8, 4, 2, 2, 4, 2, 2]   # divide ao meio até caber
    assert sorted(k for c in chamadas if len(c) <= 2 for k in c) == list(range(8))
    assert set(r["via"]) == set(range(8)) and r["recusados"] == []


def test_500_com_o_documento_sozinho_vira_recusado(tmp_path):
    docs = [_doc(0, "120000000")]

    async def pedir(lote, destino):
        return "teto", ""
    r = asyncio.run(C.gerar_pdf_lotes(None, docs, tmp_path, pedir=pedir))
    assert [e["i"] for e in r["recusados"]] == [0] and r["via"] == {}


def test_associacao_pelo_numero_com_pdf_em_ordem_diferente_da_pedida(tmp_path):
    docs = [_doc(k, str(120000000 + k)) for k in range(6)]
    r = _rodar(docs, tmp_path, ordem_reversa=True)
    assert set(r["via"]) == set(range(6))
    for k in range(6):                                # o teor de cada NNN.pdf é o do documento k, não o da posição
        assert f"Despacho {k} " in _texto(tmp_path / f"{k:03d}.pdf")


def test_lista_reordenada_entre_rodadas_retoma_pelo_id(tmp_path):
    docs = [_doc(k, str(120000000 + k)) for k in range(4)]
    _rodar(docs, tmp_path)
    (tmp_path / "manifest.json").write_text(json.dumps({"docs": [
        {"arquivo": f"{k:03d}.pdf", "url": d["u"]} for k, d in enumerate(docs)]}))
    nova = [docs[2], docs[0], docs[3], docs[1]]       # a árvore veio noutra ordem
    C.preparar_retomada(tmp_path, nova)
    chamadas: list = []
    r = asyncio.run(C.gerar_pdf_lotes(None, nova, tmp_path, pedir=_sei_falso(nova, chamadas=chamadas)))
    assert chamadas == [] and r["via"] == {}          # nada a pedir: tudo já veio, só mudou de posição
    for i, x in enumerate(nova):
        assert C.arquivo_retomado(tmp_path, i, x) is not None
        assert x["t"].split(" (")[0] + " " in _texto(tmp_path / f"{i:03d}.pdf")


def test_numero_repetido_em_dois_marcadores_nao_e_cortado(tmp_path):
    docs = [_doc(0, "120000000"), _doc(1, "120000000", titulo="Anexo (120000000)")]
    r = _rodar(docs, tmp_path)
    assert sorted(r["omitidos"]) == [0, 1] and r["via"] == {}


def test_marcador_sem_teor_e_vazio_e_titulo_sem_numero_vai_ao_laco(tmp_path):
    docs = [_doc(0, "120000000"), _doc(1, "120000001"), _doc(2, "", titulo="Planilha sem número")]

    async def pedir(lote, destino):
        _pdf_lote(destino, docs, ordem=[docs.index(x) for _, x in lote], vazio={1})
        return "ok", ""
    r = asyncio.run(C.gerar_pdf_lotes(None, docs, tmp_path, pedir=pedir))
    assert r["via"] == {0: "pdf_nativo"} and r["vazios"] == [1] and r["sem_numero"] == [2]


def test_pagina_escaneada_preserva_as_paginas_originais(tmp_path):
    docs = [_doc(0, "120000000")]

    async def pedir(lote, destino):
        pdf = fitz.open()
        p = pdf.new_page()
        pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 500, 500), False)
        pix.clear_with(200)
        p.insert_image(p.rect, pixmap=pix)
        pdf.set_toc([[1, docs[0]["t"], 1]])
        pdf.save(str(destino))
        return "ok", ""
    r = asyncio.run(C.gerar_pdf_lotes(None, docs, tmp_path, pedir=pedir))
    assert r["via"] == {0: "pdf_nativo"}
    with fitz.open(str(tmp_path / "000.pdf")) as d:
        assert d[0].get_images()                     # a imagem (scan) foi ao arquivo para o OCR de sempre


def test_pagina_de_texto_desenhado_vai_inteira_para_o_ocr(tmp_path):
    """Espelho do SIAFE vem em vetor: só o carimbo como texto e milhares de traços (medido 20/11, NAD/NE)."""
    docs = [_doc(0, "131566913")]

    async def pedir(lote, destino):
        pdf = fitz.open()
        p = pdf.new_page()
        for k in range(80):
            p.draw_line((50, 100 + 5 * k), (300, 100 + 5 * k))
        p.insert_text((50, 800), docs[0]["t"] + "  " + PROC_CARIMBO.format(n=1), fontsize=6)
        pdf.set_toc([[1, docs[0]["t"], 1]])
        pdf.save(str(destino))
        return "ok", ""
    r = asyncio.run(C.gerar_pdf_lotes(None, docs, tmp_path, pedir=pedir))
    assert r["via"] == {0: "pdf_nativo"}
    with fitz.open(str(tmp_path / "000.pdf")) as d:
        assert len(d[0].get_drawings()) >= 50


def test_janela_esgotada_deixa_pendentes(tmp_path):
    docs = [_doc(k, str(120000000 + k)) for k in range(5)]
    r = asyncio.run(C.gerar_pdf_lotes(None, docs, tmp_path, pedir=_sei_falso(docs), prazo=0.0, tam=2))
    assert r["pendentes_janela"] == [0, 1, 2, 3, 4] and r["via"] == {}


def test_documento_ja_salvo_nao_e_pedido_de_novo(tmp_path):
    docs = [_doc(k, str(120000000 + k)) for k in range(3)]
    _rodar(docs, tmp_path)
    chamadas: list = []
    asyncio.run(C.gerar_pdf_lotes(None, docs, tmp_path, pedir=_sei_falso(docs, chamadas=chamadas)))
    assert chamadas == []


def test_valor_documentos_apenas_usa_o_id():
    v = C.valor_documentos_apenas([_doc(0, "1"), _doc(1, "2", titulo="A¥B±C")])
    assert v == "9000±Despacho 0 (1)¥9001±A B C"


@pytest.mark.parametrize("msg,esperado", [("Ordem Bancária 2026OB00208 (126766754)", 1), ("Outro (999999999)", None)])
def test_doc_recusado_pelo_numero_da_mensagem(msg, esperado):
    lote = [(0, _doc(0, "126766000")), (1, _doc(1, "126766754", titulo="Ordem Bancária 2026OB00208 (126766754)"))]
    quem = C.doc_recusado(msg, lote)
    assert (quem[0] if quem else None) == esperado


def test_resumo_lotes_identifica_cada_faltante():
    docs = [_doc(0, "120000000"), _doc(1, "120000001")]
    res = {"via": {0: "pdf_nativo"}, "recusados": [], "omitidos": [1], "vazios": [], "sem_numero": [],
           "pendentes_janela": [], "extras": [], "lotes_ok": 1, "lotes_pedidos": 1, "erro": None}
    s = C.resumo_lotes(res, docs)
    assert s["via_pdf"] == 1 and s["omitidos"][0]["id_documento"] == "9001" and s["omitidos"][0]["numero_sei"] == "120000001"


def test_handler_de_download_aceita_o_wrap_do_playwright(tmp_path, monkeypatch):
    """Ensaio real 20/11: `list.append` como handler → o Playwright faz `setattr(handler, ...)` e um builtin recusa
    (AttributeError), o que derrubou a captura. O handler tem de ser função de verdade."""
    class Pag:
        def __init__(self):
            self.h = []

        def on(self, ev, f):
            setattr(f, "_pw_impl_instance_", 1)     # o que o Playwright faz com o handler
            self.h.append(f)

        def remove_listener(self, ev, f):
            self.h.remove(f)

    class Ctx(Pag):
        pass
    p = Pag()
    ctx = Ctx()
    ctx.pages = [p]
    p.context = ctx

    async def sem_frame(pg):
        return None
    monkeypatch.setattr(C.SR, "_frame_visualizacao", sem_frame)
    st, _ = asyncio.run(C._pedir_lote_sei(p, "u", "v", tmp_path / "x.pdf", teto=1))
    assert st == "erro_500" and p.h == [] and ctx.h == []      # registrou e removeu sem erro


def test_fila_sobe_o_teto_so_para_arvore_grande(tmp_path, monkeypatch):
    from tools import sei_integra_fila as F
    monkeypatch.setattr(F, "CACHE", tmp_path / "cache")
    monkeypatch.setattr(F, "ARQUIVO", tmp_path / "arq")
    p = tmp_path / "cache" / "integra_330001_000568_2025"
    p.mkdir(parents=True)
    (p / "manifest.json").write_text(json.dumps({"total_arvore": 738, "docs": []}))
    assert F._teto_processo("330001/000568/2025", {}) == max(F.TETO_PROCESSO_S, F.TETO_PROCESSO_GRANDE_S)
    assert F._teto_processo("330001/000568/2025", {"SEI_PDF_LOTES": "0"}) == F.TETO_PROCESSO_S
    assert F._teto_processo("270006/012756/2024", {}) == F.TETO_PROCESSO_S
