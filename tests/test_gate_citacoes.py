# -*- coding: utf-8 -*-
"""Gate de citações — nenhuma peça sai com acórdão que não existe.

Índice sintético em tmp_path; nenhum teste toca a rede nem o índice de produção.
"""
import sqlite3

import pytest

from compliance_agent.knowledge import tcu_juris_index as T
from compliance_agent.reporting import gate_citacoes as G
from compliance_agent.reporting.neutralidade import termos_proibidos


@pytest.fixture()
def db(tmp_path):
    caminho = tmp_path / "tcu.db"
    con = sqlite3.connect(caminho)
    T.init_schema(con)
    con.executemany("INSERT INTO tcu_acordao VALUES (?,?,?,?,?,?,?,?,?)", [
        ("K1", 645, 2007, "Plenário", "Licitação", "Dispensa", "Emergência",
         "Dispensa por emergência não cabe se houve falta de planejamento.", ""),
        ("K2", 2696, 2019, "Primeira Câmara", "Licitação", "Qualificação", "Atestado",
         "É irregular exigir quantitativo superior a 50%.", ""),
        ("K3", 3100, 2022, "Plenário", "Contrato", "Aditivo", "Limite",
         "O aditivo não pode transfigurar o objeto.", ""),
    ])
    con.execute("INSERT INTO tcu_fts(tcu_fts) VALUES('rebuild')")
    con.commit()
    con.close()
    return caminho


# ------------------------------------------------------------------ auditoria

def test_auditar_classifica_sem_alterar(db):
    texto = "Vide Acórdão 645/2007-Plenário e Acórdão 9244/2022-Plenário."
    rel = G.auditar(texto, db=db)
    assert rel["total"] == 2
    assert len(rel["confirmadas"]) == 1
    assert len(rel["impossiveis"]) == 1
    assert rel["limpo"] is False


def test_texto_so_com_citacao_real_esta_limpo(db):
    assert G.auditar("Acórdão 645/2007-Plenário", db=db)["limpo"] is True


# ------------------------------------------------------------------ saneamento

def test_citacao_inexistente_e_removida_do_texto(db):
    texto = "Conforme o Acórdão 9244/2022-Plenário, o gestor responde."
    saneado, rel = G.aplicar(texto, db=db)
    assert "9244" not in saneado
    assert G._MARCA_REMOVIDA in saneado
    assert len(rel["impossiveis"]) == 1


def test_colegiado_errado_e_corrigido_e_a_citacao_sobrevive(db):
    """O acórdão existe — não se joga fora, conserta-se."""
    saneado, rel = G.aplicar("Acórdão 2696/2019-Plenário trata de atestado.", db=db)
    assert "Acórdão 2696/2019-Primeira Câmara" in saneado
    assert "Plenário" not in saneado
    assert len(rel["colegiado_errado"]) == 1


def test_nao_confirmada_permanece_no_texto(db):
    """Ausência do recorte curado é dúvida, não veredito — não se apaga citação por dúvida."""
    saneado, rel = G.aplicar("Acórdão 3101/2022-Plenário é pertinente.", db=db)
    assert "Acórdão 3101/2022-Plenário" in saneado
    assert len(rel["nao_confirmadas"]) == 1


def test_citacao_de_outra_corte_nao_e_tocada(db):
    texto = "TCE-RJ, Acórdão 25279/2022 — Pleno, decidiu pela irregularidade."
    saneado, _ = G.aplicar(texto, db=db)
    assert saneado == texto


def test_modo_estrito_falha_alto(db):
    with pytest.raises(AssertionError, match="citação defeituosa"):
        G.aplicar("Acórdão 9244/2022-Plenário", db=db, estrito=True)


def test_estrito_nao_falha_por_duvida(db):
    """`nao_confirmado` não pode derrubar a geração — é dúvida legítima."""
    G.aplicar("Acórdão 3101/2022-Plenário", db=db, estrito=True)


# ------------------------------------------------------------------ índice ausente

def test_sem_indice_o_gate_declara_que_nao_conferiu(tmp_path):
    texto = "Acórdão 9244/2022-Plenário"
    saneado, rel = G.aplicar(texto, db=tmp_path / "nao_existe.db")
    assert saneado == texto, "sem índice não se apaga nada"
    assert rel["indice_ausente"] is True
    assert "não" in G.nota_de_auditoria(rel) and "conferidas" in G.nota_de_auditoria(rel)


# ------------------------------------------------------------------ nota ao pé

def test_nota_declara_supressao_e_pendencia(db):
    texto = ("Acórdão 645/2007-Plenário, Acórdão 9244/2022-Plenário e "
             "Acórdão 3101/2022-Plenário.")
    _, rel = G.aplicar(texto, db=db)
    nota = G.nota_de_auditoria(rel)
    assert "suprimidas" in nota
    assert "conferidas na fonte" in nota
    assert "não** significa que inexistam" in nota, "lacuna ≠ inexistência tem de estar escrito"


def test_nota_vazia_quando_nao_ha_citacao(db):
    assert G.nota_de_auditoria(G.auditar("texto sem citação", db=db)) == ""


def test_nota_nao_viola_o_gate_de_neutralidade(db):
    """A nota vai colada no entregável — não pode carregar nome interno."""
    _, rel = G.aplicar("Acórdão 645/2007-Plenário e Acórdão 9244/2022-Plenário", db=db)
    assert termos_proibidos(G.nota_de_auditoria(rel)) == []


def test_sanear_parecer_faz_as_duas_coisas(db):
    r = G.sanear_parecer("Base: Acórdão 9244/2022-Plenário.", db=db)
    assert G._MARCA_REMOVIDA in r
    assert "Nota de conferência" in r
