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


def _db_certames(tmp_path, n=5):
    """Banco sintético: `n` certames competitivos com vencedor; nenhum com ata."""
    con = sqlite3.connect(str(tmp_path / "c.db"))
    con.execute("CREATE TABLE pncp_resultado(certame, orgao_cnpj, modalidade, ordem_classificacao, data_pub)")
    con.execute("CREATE TABLE certame_indice(certame, faixa)")
    con.executemany("INSERT INTO pncp_resultado VALUES (?,?,6,1,?)",
                    [(f"00000000000100-1-{i:06d}/2026", "00000000000100", f"2026-01-{i + 1:02d}")
                     for i in range(n)])
    con.commit()
    return con


def _sem_arquivo(monkeypatch):
    async def _vazio(endpoint, params):
        return []                                  # PNCP respondeu "não há arquivo" (fato, não falha)
    monkeypatch.setattr(AJ, "_get_pncp", _vazio)


def test_cursor_dias_seguidos_examinam_certames_diferentes(tmp_path, monkeypatch):
    """Laudo 13/11/2026 (4.12): o lote de 400 era o mesmo todo dia. Certame examinado sem ata fica fora 30 dias."""
    import asyncio
    con = _db_certames(tmp_path, n=5)
    _sem_arquivo(monkeypatch)
    dia1 = set(c for c, _ in asyncio.run(AJ._certames_pendentes(con, 2)))
    asyncio.run(AJ.coletar_atas_julgamento(con, limite=2, pausa=0))
    dia2 = set(c for c, _ in asyncio.run(AJ._certames_pendentes(con, 2)))
    assert len(dia1) == 2 and len(dia2) == 2 and dia1.isdisjoint(dia2)
    motivos = dict(con.execute("SELECT certame, motivo FROM ata_exame"))
    assert set(motivos) == dia1 and set(motivos.values()) == {"sem_arquivo_no_pncp"}


def test_fila_esgotada_e_declarada(tmp_path, monkeypatch):
    import asyncio
    con = _db_certames(tmp_path, n=2)
    _sem_arquivo(monkeypatch)
    asyncio.run(AJ.coletar_atas_julgamento(con, limite=10, pausa=0))
    r = asyncio.run(AJ.coletar_atas_julgamento(con, limite=10, pausa=0))
    assert r["certames"] == 0 and r["fila_esgotada"] is True


def test_reexame_depois_de_30_dias(tmp_path, monkeypatch):
    import asyncio
    con = _db_certames(tmp_path, n=1)
    _sem_arquivo(monkeypatch)
    asyncio.run(AJ.coletar_atas_julgamento(con, limite=10, pausa=0))
    con.execute("UPDATE ata_exame SET examinado_em = datetime('now', '-31 days')")
    assert len(asyncio.run(AJ._certames_pendentes(con, 10))) == 1


def test_falha_da_api_nao_vira_exame_de_30_dias(tmp_path, monkeypatch):
    """INDISPONÍVEL ≠ 'sem ata': a falha de rede volta à fila no dia seguinte, não daqui a 30 dias."""
    import asyncio
    con = _db_certames(tmp_path, n=1)

    async def _falha(endpoint, params):
        return None
    monkeypatch.setattr(AJ, "_get_pncp", _falha)
    r = asyncio.run(AJ.coletar_atas_julgamento(con, limite=10, pausa=0))
    assert r["api_indisponivel"] == 1 and r["sem_arquivo_no_pncp"] == 0
    assert con.execute("SELECT motivo FROM ata_exame").fetchone()[0] == "api_indisponivel"
    assert asyncio.run(AJ._certames_pendentes(con, 10)) == []          # hoje não repete
    con.execute("UPDATE ata_exame SET examinado_em = datetime('now', '-2 days')")
    assert len(asyncio.run(AJ._certames_pendentes(con, 10))) == 1      # amanhã volta


def test_resumo_tem_carimbo_de_data_para_o_ao_vivo():
    linha = AJ.linha_resumo({"atas_gravadas": 0, "certames": 400})
    import re
    assert re.match(r"^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\] resumo atas: ", linha)
    assert "'atas_gravadas': 0" in linha


def test_init_schema_cria_tabela(tmp_path):
    con = sqlite3.connect(str(tmp_path / "t.db"))
    AJ.init_schema(con)
    cols = [c[1] for c in con.execute("PRAGMA table_info(ata_documento)")]
    assert {"certame", "orgao_cnpj", "titulo", "fonte_texto", "n_cnpj", "texto"} <= set(cols)
    con.close()
