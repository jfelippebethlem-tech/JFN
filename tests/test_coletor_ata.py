# -*- coding: utf-8 -*-
"""Teste do COLETOR DE ATA → ctx de julgamento (decisões/propostas/resultado).

Estratégia (leve, sem rede/LLM): ata SINTÉTICA em texto plausível com um padrão de DOIS PESOS (perdedor
inabilitado por certidão vencida × vencedor com a MESMA falha tolerado via diligência). Verifica: (a) as
decisões são extraídas com `classe_falha` correta (reuso do J7); (b) o `resultado` agrega licitantes/inabilitados;
(c) sem ata legível → ctx vazio (degrada honesto). Também cruza com o J7 real (par confirmado).
Rodar só este arquivo:  .venv/bin/python -m pytest tests/test_coletor_ata.py -q
"""
from __future__ import annotations

from compliance_agent.detectores.coletor_ata import (
    _docs_de_julgamento,
    _extrair_decisoes,
    _extrair_resultado,
    montar_ctx_julgamento,
)
from compliance_agent.detectores.j7_inabilitacao_seletiva import J7InabilitacaoSeletiva

# ata sintética: dois-pesos por certidão de regularidade fiscal (mesma classe de falha)
_ATA_TXT = """
ATA DE SESSÃO PÚBLICA DE JULGAMENTO — CONCORRÊNCIA Nº 07/2024

A empresa ALFA SERVICOS LTDA, CNPJ 11.111.111/0001-11, foi INABILITADA por apresentar certidão de
regularidade fiscal vencida na data da sessão.

A empresa BETA COMERCIO LTDA, CNPJ 22.222.222/0001-22, apesar de também apresentar certidão de regularidade
fiscal vencida, foi concedido prazo para saneamento (diligência), sendo posteriormente HABILITADA e declarada
VENCEDORA do certame, com proposta de R$ 1.850.000,00.
"""


def _leitura_ata(numero: str = "SEI-330020/000762/2021") -> dict:
    return {
        "numero": numero,
        "texto": "Processo de licitação — Concorrência 07/2024.",
        "documentos": [{"texto": "Ata de Julgamento", "url": "https://sei/doc/ata"}],
        "conteudo_documentos": [{"doc": "Ata de Sessão de Julgamento 07/2024", "conteudo": _ATA_TXT}],
    }


def test_docs_de_julgamento_acha_a_ata_por_classificacao():
    fontes = _docs_de_julgamento(_leitura_ata())
    assert fontes
    assert any("ata" in f["fonte"].lower() or "julgamento" in f["fonte"].lower() for f in fontes)


def test_extrai_decisoes_com_classe_falha():
    decisoes = _extrair_decisoes(_docs_de_julgamento(_leitura_ata()))
    por_cnpj = {d["cnpj"]: d for d in decisoes}
    assert por_cnpj["11.111.111/0001-11"]["decisao"] == "inabilitado"
    # BETA teve saneamento/diligência → TOLERÂNCIA (não 'inabilitado', apesar da palavra vencida)
    assert por_cnpj["22.222.222/0001-22"]["decisao"] == "diligencia"
    assert por_cnpj["22.222.222/0001-22"]["vencedor"] is True
    # classe de falha normalizada pelo reuso do J7 (certidão/regularidade fiscal)
    assert por_cnpj["11.111.111/0001-11"]["classe_falha"] == "certidao_vencida"


def test_resultado_agrega_licitantes_e_inabilitados():
    ctx = montar_ctx_julgamento(_leitura_ata(), usar_llm=False)
    res = ctx["resultado"]
    assert res["licitantes"] >= 2
    assert res["inabilitados"] == 1
    assert res["motivos"]  # motivo do inabilitado presente
    assert res["vencedor_cnpj"] == "22.222.222/0001-22"


def test_ctx_julgamento_alimenta_j7_par_confirmado():
    """O ctx do coletor_ata, passado ao J7 real, confirma o par dois-pesos (equivalência pré-injetada)."""
    ctx = montar_ctx_julgamento(_leitura_ata(), usar_llm=False)
    ctx["processo"] = "SEI-330020/000762/2021"
    # rubrica de equivalência pré-injetada (sem rede): as falhas comparadas são equivalentes
    ctx["_rubrica_equivalencia"] = {"nivel": "falhas-equivalentes", "trecho": "certidão de regularidade fiscal vencida"}
    res = J7InabilitacaoSeletiva().avaliar(ctx)
    assert res.status == "confirmado"
    assert res.score >= 0.85  # par crítico (vencedor tolerado) → forte/crítico


def test_degrada_honesto_sem_ata():
    """Processo sem documento de julgamento → ctx sem decisoes/propostas/resultado (campo ausente ≠ 0)."""
    leitura = {"numero": "SEI-x", "texto": "Apenas o edital, sem ata de julgamento ainda.",
               "documentos": [], "conteudo_documentos": [{"doc": "Edital", "conteudo": "Edital de pregão menor preço."}]}
    ctx = montar_ctx_julgamento(leitura, usar_llm=False)
    assert "decisoes" not in ctx
    assert "resultado" not in ctx


def test_persistir_julgamento_grava_e_infere_diligencia(tmp_path):
    """persistir_julgamento: resultado da ata deixa de ser efêmero (alimenta a família certame_ata do
    índice); a diligência da própria sessão exculpa a violação de saneamento (anti-FP conservador)."""
    import sqlite3

    from compliance_agent.detectores.coletor_ata import persistir_julgamento
    from compliance_agent.editais.db import init_schema

    con = sqlite3.connect(tmp_path / "c.db")
    init_schema(con)
    agg = persistir_julgamento(_leitura_ata(), "CERT-1", con, processo_sei="SEI-330020/000762/2021")
    assert agg is not None and agg["n"] >= 1
    assert agg["violacoes_saneamento"] == 0  # BETA recebeu diligência na sessão → houve_diligencia=True
    row = con.execute("SELECT licitantes, inabilitados, houve_diligencia FROM certame_julgamento "
                      "WHERE certame='CERT-1'").fetchone()
    assert row[0] == 2 and row[1] == 1 and row[2] == 1
    con.close()


def test_persistir_julgamento_sem_resultado_nao_grava(tmp_path):
    import sqlite3

    from compliance_agent.detectores.coletor_ata import persistir_julgamento
    from compliance_agent.editais.db import init_schema

    con = sqlite3.connect(tmp_path / "c.db")
    init_schema(con)
    leitura = {"numero": "SEI-x", "texto": "", "documentos": [],
               "conteudo_documentos": [{"doc": "Edital", "conteudo": "Edital de pregão."}]}
    assert persistir_julgamento(leitura, "CERT-2", con) is None
    assert con.execute("SELECT COUNT(*) FROM certame_julgamento").fetchone()[0] == 0
    con.close()
