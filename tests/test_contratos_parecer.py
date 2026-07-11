# -*- coding: utf-8 -*-
"""C7 — câmara delibera parecer TC."""
from compliance_agent.contratos import parecer
from compliance_agent.editais import db as ed
from compliance_agent.enxame import lentes


def _seed_mem(con):
    con.execute("""create table if not exists memoria_aprendizado (id integer primary key,
        categoria text, chave text, valor text, confianca real, n_observacoes int,
        fonte text, primeira_vez text, ultima_vez text)""")
    con.commit()


def test_dossie_txt_inclui_memoria():
    txt = lentes._dossie_txt({"objeto": "x", "clausula": {"texto": "y"},
                              "memoria_ctx": "MEMÓRIA: já refutado"})
    assert "MEMÓRIA" in txt


def test_deliberar_monta_4_secoes(monkeypatch, tmp_path):
    con = ed.conectar(tmp_path / "t.db"); _seed_mem(con)
    dossie = {"contrato": {"numero_controle_pncp": "C1", "fornecedor_documento": "11222333000181",
                           "fornecedor_nome": "ACME", "objeto": "obra", "valor_inicial": 100000,
                           "valor_global": 140000},
              "aditivos": [], "pagamentos": {}, "sinais_fornecedor": []}
    achados = [{"dimensao": "aditivo", "risco": 8, "texto": "acréscimo 40%", "norma": "art. 125",
                "proveniencia": {}}]
    monkeypatch.setattr(parecer, "_deliberar_achado",
                        lambda con, d, a, gerar=None: {"score_final": 8,
                                                       "veredito": "indício de irregularidade", "votos": {}})
    p = parecer.deliberar(con, dossie, achados)
    assert p["conclusao"] in ("regular", "diligência", "indício de irregularidade")
    assert {"relatorio", "fundamentacao", "conclusao", "voto"} <= set(p)
    assert p["conclusao"] == "indício de irregularidade" and p["score"] == 8


def test_deliberar_sem_achado_relevante(monkeypatch, tmp_path):
    con = ed.conectar(tmp_path / "t.db"); _seed_mem(con)
    dossie = {"contrato": {"numero_controle_pncp": "C2", "fornecedor_documento": "1", "objeto": "x",
                           "valor_inicial": 1, "valor_global": 1}, "aditivos": [], "pagamentos": {},
              "sinais_fornecedor": []}
    p = parecer.deliberar(con, dossie, [{"dimensao": "x", "risco": 2, "texto": "", "norma": "", "proveniencia": {}}])
    assert p["conclusao"] == "regular"
