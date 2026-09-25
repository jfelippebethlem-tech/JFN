"""Graduação do efeito jurídico das sanções do CEIS/CNEP.

Presença no cadastro não é vedação: a categoria e o ente sancionador é que decidem.
"""
import sqlite3
from pathlib import Path

import pytest

from compliance_agent.knowledge.efeito_sancao import (
    AMPLO, CONTROVERSO, RESTRITO_AO_ENTE, SEM_IMPEDIMENTO, efeito, veda_contratar)


def test_inidoneidade_alcanca_todos_os_entes():
    """Art. 156, IV e §5º da Lei 14.133/2021."""
    for cat in ("Declaração de Inidoneidade sem prazo determinado",
                "Declaração de Inidoneidade com prazo determinado"):
        e = efeito(cat)
        assert e["efeito"] == AMPLO and e["gravidade"] == 3
        assert veda_contratar(cat)["veda"] is True


def test_impedimento_com_prazo_e_restrito_ao_ente():
    """Art. 156, III e §4º: vale só no ente federativo sancionador."""
    cat = "Impedimento/proibição de contratar com prazo determinado"
    assert efeito(cat)["efeito"] == RESTRITO_AO_ENTE
    r = veda_contratar(cat, orgao_sancionador="PREFEITURA MUNICIPAL SAO SEBASTIAO DO ALTO-RJ")
    assert r["veda"] is None, "sanção de outro município não pode virar vedação automática"
    assert "mesmo ente" in r["motivo"]


def test_multa_e_publicacao_nao_vedam_contratar():
    """Lei 12.846: sanção pecuniária e de publicidade não interditam contratar."""
    for cat in ("Multa", "Publicação extraordinária da decisão condenatória"):
        assert efeito(cat)["efeito"] == SEM_IMPEDIMENTO
        assert veda_contratar(cat)["veda"] is False


def test_suspensao_e_declarada_controversa_nao_resolvida():
    """Art. 87, II da 8.666: literal restringe, STJ já ampliou. Não se decide em silêncio."""
    r = veda_contratar("Suspensão")
    assert efeito("Suspensão")["efeito"] == CONTROVERSO
    assert r["veda"] is None and "controverso" in r["motivo"]


def test_impedimento_sem_prazo_equipara_se_a_inidoneidade():
    assert efeito("Impedimento/proibição de contratar sem prazo determinado")["efeito"] == AMPLO


def test_categoria_desconhecida_e_indisponivel_nunca_liberada():
    """INDISPONÍVEL ≠ 'pode contratar'. Omissão não pode virar liberação."""
    r = veda_contratar("Sanção inventada que não existe")
    assert r["efeito"] is None
    assert r["veda"] is None, "categoria não catalogada não pode ser lida como ausência de vedação"


def test_demissao_e_sancao_a_agente_nao_a_fornecedor():
    assert efeito("Demissão")["efeito"] == SEM_IMPEDIMENTO


def test_toda_categoria_do_acervo_real_tem_veredito():
    """Controle positivo contra a base: nenhuma categoria pode cair no 'não catalogada'."""
    db = Path("data/compliance.db")
    if not db.exists():
        pytest.skip("compliance.db ausente")
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        cats = [r[0] for r in con.execute(
            "SELECT DISTINCT categoria FROM sancoes_federais WHERE categoria IS NOT NULL")]
    except sqlite3.OperationalError:
        pytest.skip("tabela sancoes_federais ausente")
    finally:
        con.close()
    sem = [c for c in cats if efeito(c)["efeito"] is None]
    assert not sem, f"categorias sem graduação: {sem}"


def test_fundamento_e_por_extenso_e_cita_a_norma():
    """Todo veredito de entregável precisa do critério por extenso."""
    for cat in ("Declaração de Inidoneidade sem prazo determinado",
                "Impedimento/proibição de contratar com prazo determinado", "Multa"):
        f = efeito(cat)["fundamento"]
        assert len(f) > 40 and ("art." in f or "Lei" in f)
