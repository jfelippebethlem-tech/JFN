# -*- coding: utf-8 -*-
"""Testes da Onda 5 (SEI/PNCP em escala): extração por schema, corpus FTS5, varredor."""
from __future__ import annotations

_EDITAL = ("EDITAL DE PREGÃO ELETRÔNICO. Objeto: aquisição de material da marca ABC modelo X. "
           "Valor estimado: R$ 1.234.567,89. Exige-se atestado de capacidade técnica e capital "
           "social mínimo. CNPJ 11.222.333/0001-44. Abertura 15/07/2025.")


def test_extrair_schema():
    from compliance_agent.sei_extract import extrair

    e = extrair(_EDITAL)
    assert e["modalidade"] == "Pregão eletrônico"
    assert e["valor_estimado"] == 1234567.89
    assert "atestado de capacidade técnica" in e["exigencias_habilitacao"]
    assert "11222333000144" in e["cnpjs_participantes"]
    assert "15/07/2025" in e["datas"]
    assert e["lido"] is True


def test_extrair_vazio_honesto():
    from compliance_agent.sei_extract import extrair

    e = extrair("")
    assert e["lido"] is False and e["cnpjs_participantes"] == [] and e["valor_estimado"] == 0.0


def test_corpus_indexar_buscar(tmp_path, monkeypatch):
    from compliance_agent import sei_corpus

    monkeypatch.setattr(sei_corpus, "_DB", tmp_path / "c.db")
    assert sei_corpus.indexar("R1", _EDITAL, objeto="material ABC") is True
    assert sei_corpus.indexar("R2", "outro edital de limpeza predial", objeto="limpeza") is True
    refs = [r["ref"] for r in sei_corpus.buscar("atestado")]
    assert refs == ["R1"]  # só o que tem 'atestado'
    assert sei_corpus.stats()["n_editais_indexados"] == 2
    # texto vazio não indexa (honesto)
    assert sei_corpus.indexar("R3", "") is False


def test_varrer_direcionamento_mock(monkeypatch, tmp_path):
    """Varre, extrai, roda red flags e ranqueia por gravidade (sem rede)."""
    import asyncio

    from compliance_agent.collectors import pncp
    from compliance_agent import sei_corpus

    monkeypatch.setattr(sei_corpus, "_DB", tmp_path / "c.db")

    async def fake_busca(*a, **k):
        return [{"id_pncp": "A/2025", "objeto": "material marca ABC", "modalidade": "Pregão", "valor": 1000, "link": "x"},
                {"id_pncp": "B/2025", "objeto": "limpeza", "modalidade": "Pregão", "valor": 2000, "link": "y"}]

    async def fake_docs(ref, *a, **k):
        return [{"texto": _EDITAL if ref == "A/2025" else "edital comum de limpeza predial"}]

    monkeypatch.setattr(pncp, "buscar_contratacoes", fake_busca)
    monkeypatch.setattr(pncp, "baixar_documentos", fake_docs)

    from compliance_agent.sei_direcionamento import varrer_direcionamento
    r = asyncio.run(varrer_direcionamento(max_itens=5))
    assert r["ok"] is True and r["n_analisados"] == 2
    # o edital com marca+atestado sem 'ou equivalente' (A) deve ranquear acima
    assert r["processos"][0]["ref"] == "A/2025"
    assert any(rf["rf"] == "R7" for rf in r["processos"][0]["red_flags"])


def test_capability_direcionamento_pronto():
    from compliance_agent.skilltree import SkillTree

    st = SkillTree()
    st.reload()
    cap = st.capacidades.get("buscar_direcionamento")
    assert cap is not None and cap["status"] == "PRONTO"
    assert st.validate() == []


def test_sei_porta_unica_delega_itkava(monkeypatch):
    """Consolidação: TODA leitura SEI passa pela porta única, que delega ao reader itkava
    (tools.sei_reader.ler) — o caminho antigo com CAPTCHA não é mais invocado."""
    import asyncio

    chamado = {}

    async def fake_ler(numero, usar_cache=True, **k):
        chamado["numero"] = numero
        chamado["via_itkava"] = True
        return {"numero": numero, "texto": "ok", "_login": {"via": "sei_reader/itkava"}}

    monkeypatch.setattr("tools.sei_reader.ler", fake_ler)
    from compliance_agent.collectors.sei_cdp import ler_processo_sei
    r = asyncio.run(ler_processo_sei("SEI-070002/008633/2022"))
    assert chamado.get("via_itkava") is True
    assert chamado["numero"] == "SEI-070002/008633/2022"
    assert r["texto"] == "ok"


def test_ler_itkava_honesto_sem_senha(monkeypatch):
    """ler() sem SEI_PASS => INDISPONÍVEL (não tenta browser, não fabrica)."""
    import asyncio

    import tools.sei_reader as R
    monkeypatch.setattr(R, "P", "")  # SEI_PASS vazio
    r = asyncio.run(R.ler("SEI-070002/008633/2022", usar_cache=False))
    assert "INDISPONÍVEL" in r["erro"] and r["texto"] == ""
