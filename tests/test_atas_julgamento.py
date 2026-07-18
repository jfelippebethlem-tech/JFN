# -*- coding: utf-8 -*-
"""atas_julgamento — extração de texto (pdf/ocr), filtro de marcador e gravação de perdedoras."""
from __future__ import annotations

import sqlite3

from compliance_agent.collectors import atas_julgamento as AJ


def test_marcador_titulo_reconhece_ata_e_rejeita_edital():
    assert AJ._RX_ATA_TITULO.search("Ata_Sessao_Final_CE_1325")
    assert AJ._RX_ATA_TITULO.search("MAPA DE LANCES pregao 05")
    assert AJ._RX_ATA_TITULO.search("Resultado do Julgamento")
    assert not AJ._RX_ATA_TITULO.search("Termo de Referencia material")
    assert not AJ._RX_ATA_TITULO.search("DFD - documento de demanda")


def test_marcador_conteudo_exige_ata_real_nao_boilerplate():
    ata = "ATA DA SESSÃO PÚBLICA de julgamento das propostas. Foi declarada vencedora a empresa X."
    edital = "Será inabilitado o licitante que não apresentar a documentação exigida no item 9."
    assert AJ._RX_ATA_CONTEUDO.search(ata)
    assert not AJ._RX_ATA_CONTEUDO.search(edital)


def test_extrair_texto_pdf_bom_nao_chama_ocr(monkeypatch):
    texto_rico = "ATA DE SESSÃO. " + "conteúdo " * 100
    monkeypatch.setattr(AJ, "_texto_de_pdf", lambda blob: texto_rico)
    chamou = {"ocr": False}
    monkeypatch.setattr(AJ, "_ocr_pdf", lambda blob, **k: chamou.__setitem__("ocr", True) or "x")
    txt, fonte = AJ._extrair_texto_ata(b"%PDF-1.4 fake", com_ocr=True)
    assert fonte == "pdf" and chamou["ocr"] is False


def test_extrair_texto_pdf_escaneado_cai_no_ocr(monkeypatch):
    monkeypatch.setattr(AJ, "_texto_de_pdf", lambda blob: "  ")     # PDF sem camada de texto
    monkeypatch.setattr(AJ, "_ocr_pdf", lambda blob, **k: "ATA DE JULGAMENTO ocr " * 30)
    txt, fonte = AJ._extrair_texto_ata(b"%PDF-1.4 scan", com_ocr=True)
    assert fonte == "ocr" and "JULGAMENTO" in txt


def test_extrair_texto_sem_ocr_devolve_pdf_pobre(monkeypatch):
    monkeypatch.setattr(AJ, "_texto_de_pdf", lambda blob: "")
    txt, fonte = AJ._extrair_texto_ata(b"%PDF-1.4", com_ocr=False)
    assert fonte == "pdf" and txt == ""


def test_init_schema_cria_tabela(tmp_path):
    con = sqlite3.connect(str(tmp_path / "t.db"))
    AJ.init_schema(con)
    cols = [c[1] for c in con.execute("PRAGMA table_info(ata_documento)")]
    assert {"certame", "orgao_cnpj", "titulo", "fonte_texto", "n_cnpj", "texto"} <= set(cols)
    con.close()
