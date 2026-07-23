"""Escrever texto em PDF não pode virar página em branco EM SILÊNCIO.

Causa dos 11.901 documentos em branco do arquivo SEI (2026-07-23): `insert_textbox`
devolve valor NEGATIVO e **não escreve nada** quando o texto não cabe — e o que não
cabe não é texto longo, é texto com MUITAS LINHAS CURTAS (120 linhas já estouram as
~79 que cabem a fontsize 8). Documento do SEI (despacho, nota de liquidação, ofício)
é exatamente assim: um campo por linha. O retorno era ignorado, o PDF vazio era salvo
e a função devolvia sucesso — perícia inteira lendo "documento sem teor".
"""
import fitz
import pytest

from compliance_agent.sei.pdf_texto import escrever_texto


def _texto_do_pdf(doc) -> str:
    return "\n".join(p.get_text() for p in doc).strip()


def test_muitas_linhas_curtas_nao_viram_pagina_em_branco():
    """O caso REAL que quebrava: 120 linhas curtas → insert_textbox devolvia -583."""
    txt = "\n".join(f"linha {i} do despacho de encaminhamento" for i in range(120))
    doc = fitz.open()

    escrever_texto(doc, "Despacho de Encaminhamento", txt)

    saida = _texto_do_pdf(doc)
    assert "linha 0 do despacho" in saida
    assert "linha 119 do despacho" in saida, "a última linha não pode se perder"
    doc.close()


@pytest.mark.parametrize("n_linhas", [80, 300, 1200])
def test_preserva_todas_as_linhas_em_qualquer_volume(n_linhas):
    txt = "\n".join(f"L{i}" for i in range(n_linhas))
    doc = fitz.open()

    escrever_texto(doc, "Nota de Liquidação", txt)

    saida = _texto_do_pdf(doc)
    faltando = [f"L{i}" for i in range(n_linhas)
                if f"L{i}\n" not in saida + "\n" and f"L{i} " not in saida]
    assert not faltando, f"linhas perdidas: {faltando[:5]} (de {n_linhas})"
    doc.close()


def test_texto_corrido_longo_continua_funcionando():
    txt = "palavra " * 3000
    doc = fitz.open()
    escrever_texto(doc, "Parecer", txt)
    assert len(_texto_do_pdf(doc)) > 15000
    doc.close()


def test_titulo_sempre_presente():
    doc = fitz.open()
    escrever_texto(doc, "Nota Fiscal 16821", "conteúdo curto")
    assert "Nota Fiscal 16821" in _texto_do_pdf(doc)
    doc.close()


def test_texto_vazio_nao_cria_pagina_fantasma():
    doc = fitz.open()
    escrever_texto(doc, "Anexo", "")
    assert "Anexo" in _texto_do_pdf(doc), "só o título, mas nunca uma página muda"
    doc.close()
