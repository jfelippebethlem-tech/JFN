# -*- coding: utf-8 -*-
"""ContasRio (Relação de Contratos) → contasrio_contrato; anexos do CCON → pcrj_processo_doc (12/09/2026)."""
from __future__ import annotations

import sqlite3

from tools.contasrio_ingest import brl, ingerir_anexos, ingerir_contratos, parse_linha

_LINHA = ["   11709793000139 - CINEMA DO RIO CULTURA E EVENTOS LTDA. ", "3051 - DISTRIBUIDORA DE FILMES S/A",
          "300051 - DISTRIBUIDORA DE FILMES S/A", "Contrato", "2026", "2611958", "20/08/2026",
          "Contratação do Festival do Rio 2026", "Assinado", "20/08/2027", "20/08/2027", "006300.000569/2026-14",
          "Contratação Direta - Inexigibilidade",
          "<a href='https://acesso.processo.rio/sigaex/public/app/transparencia/processo?n=006300.000569/2026-14'>Anexos até 2025</a>"
          "<a href='https://siafic-apps-externas.rio.rj.gov.br/ccon-web/?contrato=2611958'>Anexos após 2025</a>",
          "2500000", "2500000", "0", "2500000", "1234567,89"]


def test_parse_linha_extrai_cnpj_contrato_processo_e_valores():
    d = parse_linha(_LINHA)
    assert d["contrato"] == "2611958" and d["favorecido_doc"] == "11709793000139"
    assert d["favorecido_nome"] == "CINEMA DO RIO CULTURA E EVENTOS LTDA."
    assert d["processo"] == "006300.000569/2026-14" and d["ano"] == 2026
    assert d["total_pago"] == 1234567.89 and d["valor_atualizado"] == 2500000.0
    assert parse_linha(["TOTAL"] * 19) is None and parse_linha(["x"] * 5) is None
    antigo = _LINHA[:13] + ["<a href='https://acesso.processo.rio/sigaex/public/app/transparencia/processo?n=SMS-PRO-2023/1'>Anexos até 2025</a>"] + _LINHA[14:]
    d2 = parse_linha(antigo)   # contrato de 2023: só link do SIGA → chave = nº do instrumento, sem url CCON
    assert d2["contrato"] == "2611958" and d2["url_ccon"] is None
    assert brl("") is None and brl("1.234,50") == 1234.5


def test_ingest_liga_anexo_ao_processo_do_contrato(tmp_path):
    csv_dir = tmp_path / "contasrio"
    csv_dir.mkdir()
    (csv_dir / "contratos_2026.csv").write_text(
        "cab;" * 18 + "cab\n" + "TOTAL;" * 18 + "0\n" + ";".join(_LINHA) + "\n", encoding="latin-1")
    db = tmp_path / "pcrj.db"
    r = ingerir_contratos(csv_dir, db)
    assert r["linhas"] == 1 and r["total"] == 1
    ccon = tmp_path / "ccon.db"
    c = sqlite3.connect(ccon)
    c.execute("CREATE TABLE ccon_anexo (contrato, anexo_id, tipo, descricao, arquivo, media_type, n_bytes, texto, capturado_em)")
    c.execute("INSERT INTO ccon_anexo VALUES ('2611958', 16198, 'TERMO DE REFERÊNCIA', 'Contrato Assinado', 'c.pdf', "
              "'application/pdf', 10, 'CONTRATO Nº 2611958 …', '2026-09-12')")
    c.execute("INSERT INTO ccon_anexo VALUES ('999', 1, 'OUTROS', 'x', 'x.pdf', 'application/pdf', 10, 'texto', '2026-09-12')")
    c.commit()
    c.close()
    r = ingerir_anexos(ccon, db)
    assert r["documentos"] == 2 and r["sem_processo"] == 1
    con = sqlite3.connect(db)
    rows = con.execute("SELECT numero_processo, seq, tipo FROM pcrj_processo_doc ORDER BY seq").fetchall()
    assert rows == [("CCON-999", 1, "ccon_outros"), ("006300.000569/2026-14", 16198, "ccon_termo_de_referencia")]
