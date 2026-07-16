# -*- coding: utf-8 -*-
"""Testes da triagem em lote de PPPs (``pcrj/triagem_ppp.py``). DB isolado (conftest)."""
import json

from compliance_agent.pcrj import db, triagem_ppp, lente_ppp


def _seed(con, slug, nome, edital_texto=None):
    con.execute("INSERT INTO pcrj_ppp (slug,nome,fase,coletado_em) VALUES (?,?,?,?)",
                (slug, nome, "Assinatura do Contrato", "2026-07-15"))
    if edital_texto:
        con.execute("INSERT INTO pcrj_processo_doc (numero_processo,seq,tipo,titulo,texto,coletado_em) "
                    "VALUES (?,?,?,?,?,?)", (slug, 0, "edital_ccpar", "Edital", edital_texto, "2026-07-15"))
    con.commit()


EDITAL_ALTO = ("GARANTIA PÚBLICA com receitas vinculadas do FUNDO NACIONAL DE SAÚDE; APORTE PÚBLICO; "
               "ressarcimento dos estudos do PMI; PRAZO DA CONCESSÃO de 30 (trinta) anos; "
               "VALOR ESTIMADO DO CONTRATO; VERIFICADOR INDEPENDENTE.")
EDITAL_LIMPO = "Concessão simples de serviço, sem garantia pública nem aporte."


def test_rankeia_por_gravidade(tmp_path, monkeypatch):
    p = tmp_path / "pcrj.db"
    db.inicializar(p)
    con = db.conectar(p)
    _seed(con, "alto-x", "PPP Alta", EDITAL_ALTO)
    _seed(con, "limpo-y", "PPP Limpa", EDITAL_LIMPO)
    con.close()
    r = triagem_ppp.triar_lote(db_path=p)
    assert r["resumo"]["projetos"] == 2
    # o de garantia FNS vem primeiro (🔴)
    assert r["itens"][0]["nome"] == "PPP Alta"
    assert r["itens"][0]["grau"] == "🔴 alto"
    assert "garantia_receita_saude" in r["itens"][0]["flags"]
    assert r["resumo"]["alto"] == 1


def test_projeto_sem_texto_vira_sem_dados(tmp_path):
    p = tmp_path / "pcrj.db"
    db.inicializar(p)
    con = db.conectar(p)
    _seed(con, "vazio-z", "PPP Sem Texto", None)
    con.close()
    r = triagem_ppp.triar_lote(db_path=p)
    assert r["itens"][0]["grau"] == "sem_dados"


def test_texto_menu_tem_cabecalho(tmp_path):
    p = tmp_path / "pcrj.db"
    db.inicializar(p)
    con = db.conectar(p)
    _seed(con, "a", "PPP A", EDITAL_ALTO)
    con.close()
    r = triagem_ppp.triar_lote(db_path=p)
    assert "Triagem de PPPs" in r["texto"]
    assert "Indício ≠ acusação" in r["texto"]
