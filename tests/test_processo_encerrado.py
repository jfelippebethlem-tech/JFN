# -*- coding: utf-8 -*-
"""Processo encerrado e já lido não se relê — e "encerrado" não significa "inauditável".

O sweep de CAPTURA já pula árvore encerrada (`sei_arvore.encerrado`, 686 dos 3.919 processos).
A ANÁLISE EM SÉRIE, que é a parte que gasta cota de modelo, nunca consultou esse sinal: ela
relê processo encerrado, sem fato novo, pelo mesmo preço de um processo vivo.

A regra tem três condições, e todas importam:

    já foi lido por inteiro   — nunca pular o que nunca se leu, encerrado ou não
    está encerrado            — termo de encerramento no arquivo OU árvore autoritativa
    sem pagamento novo        — OB posterior à leitura reabre o interesse, mesmo encerrado

Encerramento é razão para não REPETIR trabalho, jamais para não fiscalizar: processo encerrado
segue auditável, e o que muda é só a prioridade de reler. Por isso o veredito vem sempre com o
MOTIVO — quem lê a fila precisa saber se o processo saiu por estar em dia ou por estar cego.
"""
from compliance_agent.sei.encerramento import deve_reanalisar, encerrado_no_arquivo

DOCS_COM_TERMO = [
    {"titulo": "Despacho de Encaminhamento", "tipo": "despacho", "chars": 900},
    {"titulo": "Termo de Encerramento de Processo (137002914)", "tipo": "outro", "chars": 1200},
]
DOCS_SEM_TERMO = [
    {"titulo": "Despacho de Encaminhamento", "tipo": "despacho", "chars": 900},
    {"titulo": "Nota de Empenho 2026NE00123", "tipo": "nota_empenho", "chars": 800},
]


def test_reconhece_o_termo_de_encerramento_no_arquivo():
    assert encerrado_no_arquivo(DOCS_COM_TERMO) is True
    assert encerrado_no_arquivo(DOCS_SEM_TERMO) is False


def test_encerramento_de_CONTRATO_nao_e_encerramento_de_PROCESSO():
    """"Termo de encerramento do contrato" é peça de execução — o processo segue tramitando."""
    docs = [{"titulo": "Termo de Encerramento do Contrato 36/2023", "tipo": "contrato", "chars": 500}]
    assert encerrado_no_arquivo(docs) is False


def test_lista_vazia_nao_afirma_encerramento():
    assert encerrado_no_arquivo([]) is False
    assert encerrado_no_arquivo(None) is False


# ── a decisão de gastar (ou não) cota ────────────────────────────────────────────────────────

def test_nao_rele_encerrado_ja_lido_e_sem_pagamento_novo():
    d = deve_reanalisar(ja_lido=True, encerrado=True, ob_apos_leitura=False)
    assert d["reanalisar"] is False
    assert "encerrad" in d["motivo"].lower()


def test_rele_o_que_nunca_foi_lido_mesmo_encerrado():
    """Encerrado que nunca se leu é dinheiro pago sobre o qual não se leu uma linha."""
    d = deve_reanalisar(ja_lido=False, encerrado=True, ob_apos_leitura=False)
    assert d["reanalisar"] is True


def test_pagamento_DEPOIS_da_leitura_reabre_mesmo_encerrado():
    """OB nova em processo 'encerrado' é o próprio motivo de olhar de novo."""
    d = deve_reanalisar(ja_lido=True, encerrado=True, ob_apos_leitura=True)
    assert d["reanalisar"] is True
    assert "pagamento" in d["motivo"].lower() or "ob" in d["motivo"].lower()


def test_processo_vivo_ja_lido_continua_na_fila():
    d = deve_reanalisar(ja_lido=True, encerrado=False, ob_apos_leitura=False)
    assert d["reanalisar"] is True


def test_leitura_incompleta_nao_conta_como_lido():
    """Dossiê com lote perdido não é leitura: pular por 'já lido' cristalizaria o erro."""
    d = deve_reanalisar(ja_lido=True, encerrado=True, ob_apos_leitura=False, leitura_incompleta=True)
    assert d["reanalisar"] is True
    assert "incompleta" in d["motivo"].lower()


def test_o_veredito_sempre_traz_motivo():
    """Fila sem motivo vira caixa-preta: quem lê precisa saber se saiu por dia ou por cegueira."""
    for kw in ({"ja_lido": True, "encerrado": True, "ob_apos_leitura": False},
               {"ja_lido": False, "encerrado": False, "ob_apos_leitura": False}):
        assert deve_reanalisar(**kw)["motivo"].strip()


# ── a fusão dos sinais reais (arquivo + árvore + OB) ─────────────────────────────────────────

def test_situacao_funde_arquivo_e_arvore_declarando_a_fonte(tmp_path, monkeypatch):
    """Duas fontes independentes; o veredito diz QUAL delas afirmou o encerramento."""
    import json

    import compliance_agent.sei.encerramento as E

    p = tmp_path / "080001_000001_2024"
    (p / "texto").mkdir(parents=True)
    (p / "manifest.json").write_text(json.dumps(
        {"docs": [{"titulo": "Termo de Encerramento de Processo (1)", "chars": 10}]}), encoding="utf-8")
    monkeypatch.setattr(E, "ACERVO", tmp_path)
    s = E.situacao_do_processo("080001_000001_2024", arvore_encerradas=set())
    assert s["encerrado"] is True
    assert "arquivo" in s["fonte"]


def test_situacao_aceita_a_arvore_como_fonte_autoritativa(tmp_path, monkeypatch):
    import json

    import compliance_agent.sei.encerramento as E

    p = tmp_path / "080001_000002_2024"
    (p / "texto").mkdir(parents=True)
    (p / "manifest.json").write_text(json.dumps({"docs": []}), encoding="utf-8")
    monkeypatch.setattr(E, "ACERVO", tmp_path)
    s = E.situacao_do_processo("080001_000002_2024",
                               arvore_encerradas={"SEI-080001/000002/2024"})
    assert s["encerrado"] is True
    assert "árvore" in s["fonte"] or "arvore" in s["fonte"]


def test_sem_manifest_nao_afirma_nada(tmp_path, monkeypatch):
    import compliance_agent.sei.encerramento as E

    monkeypatch.setattr(E, "ACERVO", tmp_path)
    s = E.situacao_do_processo("nao_existe", arvore_encerradas=set())
    assert s["encerrado"] is False
    assert "sem" in s["fonte"].lower() or "indispon" in s["fonte"].lower()
