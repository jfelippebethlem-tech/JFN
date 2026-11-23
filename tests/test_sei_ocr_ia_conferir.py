# -*- coding: utf-8 -*-
"""CLI de conferência do OCR por IA (`tools/sei_ocr_ia_conferir`): confirmação por Tesseract no PDF real, marcar,
pendentes, ficha e o aplicador da fila do Opus."""
import json
import shutil

import pytest

from compliance_agent.sei import acervo_texto
from compliance_agent.sei import ocr_ia_prova as P
from tools import sei_ocr_ia_conferir as C

TAG = "080002_000001_2024"
CNPJ = "05.340.639/0001-30"
TEXTO_IA = f"NOTA FISCAL\nPrestador CNPJ {CNPJ}\nValor total R$ 100.083,95\nEmissão 05/03/2024"   # IA trocou 3→8


@pytest.fixture()
def acervo(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "LEDGER", tmp_path / "conf.jsonl")
    raiz = tmp_path / "sei_arquivo"
    pasta = raiz / TAG
    (pasta / "texto").mkdir(parents=True)
    (pasta / "texto" / "007_nf.txt").write_text("[NF 1] (tipo: nota_fiscal)\n\n" + TEXTO_IA, encoding="utf-8")
    docs = [{"i": 7, "titulo": "NF 1", "tipo": "nota_fiscal", "texto": "texto/007_nf.txt", "ocr": "True",
             "ocr_motor": "surya-ocr-2.5"}]
    (pasta / "manifest.json").write_text(json.dumps({"docs": docs}), encoding="utf-8")
    monkeypatch.setattr(acervo_texto, "RAIZ", raiz)
    monkeypatch.setattr(C, "CACHE", tmp_path / "sei_cache")
    monkeypatch.setattr(C, "FICHAS", tmp_path / "fichas")
    monkeypatch.setattr(P, "fontes_externas", lambda numero, con=None: {})
    monkeypatch.setattr(C, "_PROC", {})
    return pasta


def _pdf_escaneado(destino, linhas):
    """PDF com a página como IMAGEM (escaneado): texto renderizado e rasterizado."""
    import fitz
    src = fitz.open()
    pg = src.new_page(width=595, height=842)
    for k, ln in enumerate(linhas):
        pg.insert_text((50, 100 + 40 * k), ln, fontsize=20)
    png = pg.get_pixmap(dpi=200).tobytes("png")
    out = fitz.open()
    out.new_page(width=595, height=842).insert_image(fitz.Rect(0, 0, 595, 842), stream=png)
    destino.parent.mkdir(parents=True, exist_ok=True)
    out.save(destino)


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="sem tesseract")
def test_confirmar_com_tesseract_no_pdf(acervo):
    _pdf_escaneado(C.CACHE / f"integra_{TAG}" / "007.pdf",
                   ["NOTA FISCAL", f"Prestador CNPJ {CNPJ}", "Valor total R$ 100.033,95", "Emissao 05/03/2024"])
    d = acervo_texto.manifesto(acervo)["docs"][0]
    r = C.confirmar_documento(acervo, d)
    est = {x["tipo"]: x for x in r["resultados"]}
    assert est["cnpj"]["estado"] == "confirmado" and est["cnpj"]["fonte"] == "tesseract"
    assert est["data"]["estado"] == "confirmado"
    assert est["valor"]["estado"] == "divergente" and est["valor"]["leitura_2"] == "100033.95"


def test_sem_pdf_fica_a_conferir_e_nao_vira_zero(acervo):
    d = acervo_texto.manifesto(acervo)["docs"][0]
    r = C.confirmar_documento(acervo, d, usar_pdf=False)
    assert {x["estado"] for x in r["resultados"]} == {"a_conferir"} and len(r["resultados"]) == 3


def test_marcar_e_pendentes(acervo):
    d = acervo_texto.manifesto(acervo)["docs"][0]
    P.registrar(C.confirmar_documento(acervo, d, usar_pdf=False)["resultados"])
    assert len(C.pendentes()) == 3
    e = C.marcar(TAG, 7, CNPJ, "confirmado", "jorge")
    assert e["tipo"] == "cnpj" and P.vale_como_prova(TAG, d, "cnpj", CNPJ)
    assert len(C.pendentes()) == 2 and C.pendentes()[0]["tipo"] == "valor"        # maior valor primeiro
    with pytest.raises(ValueError):
        C.marcar(TAG, 7, "99.999.999/9999-99", "confirmado", "jorge")            # número que a IA não leu
    with pytest.raises(ValueError):
        C.marcar(TAG, 7, CNPJ, "confirmado", " ")


def test_ficha_sem_pdf_gera_html(acervo, monkeypatch):
    monkeypatch.setattr(C, "pdf_do_documento", lambda tag, i, trazer=True: None)
    alvo = C.ficha(TAG, 7)
    h = alvo.read_text()
    assert "PDF INDISPONÍVEL" in h and "100.083,95" in h and "marcar" in h


def test_aplicador_do_opus_so_com_base_objetiva(acervo):
    item = json.dumps({"tag": TAG, "i": 7, "tipo": "valor", "norma": "100083.95", "literal": "100.083,95"})
    assert not C.aplicar_conferencia(item, '{"decisao": "A", "base": "nenhuma"}', "opus", None)
    assert not C.aplicar_conferencia(item, '{"decisao": "indecidivel", "base": "nenhuma"}', "opus", None)
    assert C.aplicar_conferencia(item, '{"decisao": "B", "base": "extenso", "justificativa": "x"}', "opus", None)
    assert P.estado(TAG, 7, "valor", "100083.95") == "errado"


# ── 23/11/2026: rodada automática (2ª leitura do RapidOCR ao lado, OCR do PDF na VM-2, fila da reserva) ──────────
def _ao_lado_reserva(pasta, texto):
    (pasta / "texto" / "007_nf.reserva.txt").write_text("[NF 1] (tipo: nota_fiscal)\n\n" + texto, encoding="utf-8")


def test_reserva_ao_lado_nova_reabre_o_documento_e_confirma(acervo):
    d = acervo_texto.manifesto(acervo)["docs"][0]
    P.registrar(C.confirmar_documento(acervo, d, usar_pdf=False)["resultados"])
    assert C._ja_decidido(acervo, d)                                   # nada novo: não refaz
    _ao_lado_reserva(acervo, f"NOTA FISCAL\nPrestador CNPJ {CNPJ}\nValor total R$ 100.033,95\nEmissao 05/03/2024")
    assert not C._ja_decidido(acervo, d)                               # 2ª leitura nova ainda não tentada
    P.registrar(C.confirmar_documento(acervo, d, usar_pdf=False)["resultados"])
    assert P.estado(TAG, 7, "cnpj", P.normalizar("cnpj", CNPJ)) == "confirmado"
    assert P.estado(TAG, 7, "valor", "100083.95") == "divergente"      # a IA trocou 3→8: não vira prova
    assert C._ja_decidido(acervo, d)                                   # já tentada: não refaz de novo


def test_fila_da_reserva_so_ia_pendente_sem_reserva_ao_lado(acervo, monkeypatch, tmp_path):
    monkeypatch.setattr(C, "FILA_RESERVA", tmp_path / "fila_reserva.txt")
    d = acervo_texto.manifesto(acervo)["docs"][0]
    P.registrar(C.confirmar_documento(acervo, d, usar_pdf=False)["resultados"])
    assert C.fila_reserva() == [f"integra_{TAG}/007.pdf"]
    C.gravar_fila_reserva()
    assert C.FILA_RESERVA.read_text().split() == [f"integra_{TAG}/007.pdf"]
    _ao_lado_reserva(acervo, f"NOTA FISCAL CNPJ {CNPJ}")
    assert C.fila_reserva() == []                                      # negativo: já tem a leitura do RapidOCR


def test_leitura_na_vm2_usa_o_resultado_remoto_e_queda_adia(acervo, monkeypatch):
    import subprocess as sp
    d = acervo_texto.manifesto(acervo)["docs"][0]
    chamadas = []

    def run_ok(argv, input=None, capture_output=True, timeout=None):
        chamadas.append(argv)
        return sp.CompletedProcess(argv, 0, json.dumps({"pdf": "vm2:x", "paginas": [1], "segundos": {"1": 2.0},
                                                         "leituras": {"tesseract": f"CNPJ {CNPJ}"}}).encode(), b"")
    monkeypatch.setattr(C.subprocess, "run", run_ok)
    r = C.confirmar_documento(acervo, d, ler_em="vm2")
    assert chamadas and chamadas[0][-2] == "vm2" and "tools.sei_ocr_ia_conferir ler" in chamadas[0][-1]
    assert {x["tipo"]: x["estado"] for x in r["resultados"]}["cnpj"] == "confirmado" and not r.get("adiado")
    monkeypatch.setattr(C.subprocess, "run", lambda *a, **k: sp.CompletedProcess(a, 255, b"", b"ssh: timeout"))
    r = C.confirmar_documento(acervo, d, ler_em="vm2")
    assert r["adiado"] and r["resultados"] == []                        # VM-2 fora: não grava a_conferir sem tentar
