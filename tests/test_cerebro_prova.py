# -*- coding: utf-8 -*-
"""Ponteiro de prova no fato de caso — lacuna entre o documento e o código (docs/ARQUITETURA-SEGUNDO-CEREBRO-ALVO.md
§5.2 e critério da Fase 4: "100% dos fatos de nível 2 com `prova_doc` preenchido"). O serviço aceita
`prova_doc`/`prova_trecho` desde 19/11, mas nenhum produtor os mandava: `enviar_pendentes` não tinha os campos e a
ponte guardava só verdadeiro/falso da conferência. Sem rede, sem tocar em data/."""
import sqlite3

from compliance_agent import cerebro_compartilhado as C
from compliance_agent import cerebro_ponte as ponte
from tests.test_cerebro_ponte import CORPUS, LAUDO


def _enviados(monkeypatch):
    enviados = []

    def http(caminho, corpo=None):
        enviados.append(corpo)
        return {"status": "gravada", "id": 100 + len(enviados)}
    monkeypatch.setattr(C, "_http", http)
    return enviados


def test_fato_de_nivel_2_leva_o_documento_e_o_trecho_literal_que_foi_localizado(tmp_path, monkeypatch):
    conf = ponte.conferir(LAUDO, CORPUS, None)
    fato = ponte.fatos_do_laudo(LAUDO, conf)[0]
    assert fato["prova"] == ("SEI-030001/047970/2026 — texto arquivado do processo (laudo data/pericia_agentes/"
                             "030001_047970_2026.json)", "A estratégia logística utilizou 137 polos de distribuição")
    con = C.conectar(tmp_path / "p.db")
    enviados = _enviados(monkeypatch)
    assert C.registrar(fato["chave"], fato["texto"], fato["kind"], fato["assunto"], con=con, prova=fato["prova"]) == "novo"
    C.enviar_pendentes(con=con)
    assert enviados[0]["prova_doc"].startswith("SEI-030001/047970/2026") and "137 polos" in enviados[0]["prova_trecho"]


def test_controle_negativo_sem_citacao_localizada_nao_ha_prova_e_o_envio_nao_inventa(tmp_path, monkeypatch):
    conf = ponte.conferir(LAUDO, "outro texto qualquer do processo, sem relação", None)
    fatos = ponte.fatos_do_laudo(LAUDO, conf)
    assert all(f.get("prova") is None for f in fatos), "nível 1 e lição candidata não levam ponteiro de prova"
    con = C.conectar(tmp_path / "p.db")
    enviados = _enviados(monkeypatch)
    C.registrar("k", "fato sem prova", "semantica", None, con=con)
    C.enviar_pendentes(con=con)
    assert "prova_doc" not in enviados[0] and "prova_trecho" not in enviados[0]


def test_trecho_de_prova_com_dado_pessoal_nao_sai_e_o_fato_limpo_vai_sem_ponteiro(tmp_path, monkeypatch):
    con = C.conectar(tmp_path / "p.db")
    enviados = _enviados(monkeypatch)
    r = C.registrar("k", "fato limpo", "semantica", None, con=con, prova=("doc 3", "assinado por 123.456.789-09 em 2026"))
    assert r == "novo"
    assert con.execute("SELECT conteudo, prova_doc, prova_trecho FROM cerebro WHERE chave='k'").fetchone() == ("fato limpo", None, None)
    C.enviar_pendentes(con=con)
    assert "123.456.789-09" not in str(enviados) and "prova_trecho" not in enviados[0]


def test_registro_antigo_ganha_as_colunas_sem_perder_linha(tmp_path):
    db = tmp_path / "antigo.db"
    velho = sqlite3.connect(db)
    velho.execute("CREATE TABLE cerebro(chave TEXT PRIMARY KEY, kind TEXT, assunto TEXT, conteudo TEXT, hash TEXT, "
                  "mem_id INTEGER, hash_enviado TEXT, enviado_em REAL, tentativas INTEGER DEFAULT 0, erro TEXT, criado_em REAL)")
    velho.execute("INSERT INTO cerebro(chave, conteudo, hash, hash_enviado, mem_id) VALUES ('a', 'texto', 'h', 'h', 7)")
    velho.commit()
    velho.close()
    con = C.conectar(db)
    assert con.execute("SELECT chave, mem_id, prova_doc FROM cerebro").fetchall() == [("a", 7, None)]
    assert C.resumo(con)["pendentes"] == 0, "migrar não pode reabrir o envio do que já foi gravado"
