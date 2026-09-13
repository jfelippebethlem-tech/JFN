# -*- coding: utf-8 -*-
"""Pares verificador/CRC do rodapé SEI publicados no D.O. Rio (12/09/2026)."""
from __future__ import annotations

from tools.pcrj_sei_crc_harvest import extrair_pares

_DOE = ("Processo 000900.064554/2026-39 … Cumpra as Exigências 1) Certifique-se conforme minuta, "
        "disponibilizada no site SEI.Rio, no item “Autenticidade de Documentos”, utilizando como número "
        "de referência o código verificador 7073421 e o código CRC 9A5C1569. 2) Junte … "
        "código verificador 7073421 e o código CRC 9a5c1569 (repetido) … "
        "Documento assinado eletronicamente. Código Verificador: 5637168 Código CRC: F7FF29B7.")


def test_extrai_pares_unicos_com_processo_mais_proximo():
    ps = extrair_pares(_DOE)
    assert [(p["verificador"], p["crc"]) for p in ps] == [("7073421", "9A5C1569"), ("5637168", "F7FF29B7")]
    assert ps[0]["processo"] == "000900.064554/2026-39"
    assert "CRC 9A5C1569" in ps[0]["contexto"]


def test_sem_par_nao_fabrica():
    assert extrair_pares("código verificador 123 sem CRC") == []
    assert extrair_pares("") == []


def test_ingest_liga_documento_ao_processo_sem_inventar():
    from tools.pcrj_sei_ingest import processo_do_documento
    assert processo_do_documento("000900.064554/2026-39", "x", "1") == "000900.064554/2026-39"
    assert processo_do_documento(None, "Processo nº 000100.003402/2026-85 — Despacho", "7073421") == "000100.003402/2026-85"
    assert processo_do_documento(None, "planta sem número", "7073421") == "SEI-DOC-7073421"
    assert processo_do_documento(None, "MINUTA | Processo Nº : EIS-PRO-2023/06224 | Licença", "7073421") == "EIS-PRO-2023/06224"


def test_colher_dos_corpora_le_rodape_dos_pdfs_baixados(tmp_path):
    import sqlite3
    from tools.pcrj_sei_crc_harvest import colher_dos_corpora
    corpus = tmp_path / "ccon.db"
    c = sqlite3.connect(corpus)
    c.execute("CREATE TABLE ccon_anexo (texto)")
    c.execute("INSERT INTO ccon_anexo VALUES ('Processo 000700.007924/2026-97 … código verificador 5192267 e o código CRC 1A2B3C4D.')")
    c.commit(); c.close()
    r = colher_dos_corpora(tmp_path / "pcrj.db", corpora=((corpus, "ccon_anexo", "texto"),))
    assert r["novos"] == 1 and r["total"] == 1


def test_ingest_busca_livre_do_sei_municipal(tmp_path):
    import sqlite3
    from tools.pcrj_sei_ingest import ingerir_busca
    o = tmp_path / "sei_pcrj.db"
    c = sqlite3.connect(o)
    c.execute("CREATE TABLE sei_pcrj_busca (termo, prot, processo, titulo, tipo_registro, unidade, data, snippet, href, capturado_em)")
    c.execute("INSERT INTO sei_pcrj_busca VALUES ('TUISE','4344543','006900.007829/2026-13','LIQUIDAÇÃO nº006900.007829/2026-13 4344543','documento','RS/PRE','20/04/2026','…TUISE…',NULL,'2026-09-13')")
    c.commit(); c.close()
    r = ingerir_busca(o, tmp_path / "pcrj.db")
    assert r["busca"] == 1 and r["processos_distintos"] == 1


def test_ingest_enum_cataloga_processo_com_tipo_e_unidade_sem_apagar_o_que_ja_existe(tmp_path):
    import sqlite3
    from tools.pcrj_sei_ingest import ingerir_enum
    o = tmp_path / "sei_pcrj.db"
    c = sqlite3.connect(o)
    c.execute("CREATE TABLE sei_pcrj_enum (processo, tipo, unidade, data, dia_consulta, capturado_em)")
    c.execute("INSERT INTO sei_pcrj_enum VALUES ('000900.084662/2026-28','AQUISIÇÃO DE MATERIAL','S/SUBG/CIL/GI','01/09/2026','01/09/2026','2026-09-13')")
    c.commit(); c.close()
    r = ingerir_enum(o, tmp_path / "pcrj.db")
    assert r["enum"] == 1 and r["pcrj_processo_sei"] == 1
    con = sqlite3.connect(tmp_path / "pcrj.db")
    assert con.execute("SELECT assunto, orgao, disponivel FROM pcrj_processo").fetchone() == ("AQUISIÇÃO DE MATERIAL · gerado 01/09/2026", "S/SUBG/CIL/GI", None)
