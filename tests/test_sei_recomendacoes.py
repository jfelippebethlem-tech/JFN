# -*- coding: utf-8 -*-
"""Testes do detector de recomendações não atendidas no SEI (camada determinística, sem LLM/rede)."""
from __future__ import annotations

from compliance_agent import sei_recomendacoes as S


DESP_PGE_NAO = {"ref": "DOC-10", "tipo": "Parecer", "texto":
    "PROCURADORIA GERAL DO ESTADO. Parecer nº 123. Esta Procuradoria RECOMENDA a anulação do item 4 do edital por "
    "restrição à competitividade. Em despacho posterior, verifica-se que a recomendação NÃO FOI ATENDIDA, "
    "permanecendo a ressalva. Reitera-se a impugnação."}
DESP_CGE_OK = {"ref": "DOC-11", "tipo": "Despacho", "texto":
    "CONTROLADORIA GERAL DO ESTADO determina a juntada da pesquisa de preços. Recomendação sanada conforme fls. 50."}
DOC_NEUTRO = {"ref": "DOC-12", "tipo": "Ofício", "texto":
    "Encaminho o processo para pagamento da nota fiscal nº 99, conforme empenho."}


def test_detecta_pge_recomendacao_nao_atendida():
    a = S.detectar([DESP_PGE_NAO])
    assert len(a) == 1
    assert a[0]["emissor"] == "PGE"
    assert a[0]["sinal_nao_atendida"] is True
    assert a[0]["status"] == "INDICIO_NAO_ATENDIDA"
    assert a[0]["trechos_nao_atendida"]


def test_detecta_cge_recomendacao_sem_sinal_de_nao_atendida():
    a = S.detectar([DESP_CGE_OK])
    assert len(a) == 1 and a[0]["emissor"] == "CGE"
    assert a[0]["sinal_nao_atendida"] is False
    assert a[0]["status"] == "RECOMENDACAO_A_CONFERIR"


def test_ignora_doc_sem_orgao_de_controle():
    assert S.detectar([DOC_NEUTRO]) == []


def test_classificar_emissor():
    assert S.classificar_emissor("Assembleia... Assessoria Jurídica opina") == "ASSESSORIA_JURIDICA"
    assert S.classificar_emissor("Tribunal de Contas do Estado") == "TCE"
    assert S.classificar_emissor("memorando interno qualquer") is None


def test_analisar_sem_llm_honesto():
    r = S.analisar([DESP_PGE_NAO, DESP_CGE_OK, DOC_NEUTRO], usar_llm=False)
    assert r["n_candidatos"] == 2
    assert r["n_indicio_nao_atendida"] == 1
    assert "não atendida" in r["leitura"].lower()


def test_leitura_vazia_honesta():
    r = S.analisar([DOC_NEUTRO], usar_llm=False)
    assert r["n_candidatos"] == 0
    assert "INDISPONÍVEL" in r["leitura"]
