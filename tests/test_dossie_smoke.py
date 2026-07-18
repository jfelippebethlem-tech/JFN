"""Smoke test mínimo e DETERMINÍSTICO do produto Dossiê (`compliance_agent/dossie.py`).

O Dossiê 360 foi validado manualmente mas não tinha NENHUM teste — uma regressão
estrutural (chave faltando, crash no agregador, score quebrado) passaria despercebida.

Este smoke valida a ESTRUTURA do retorno de `dossie()`, não o conteúdo das fontes:
  - semeia 1 OB num DB ISOLADO (env JFN_DB, via fixture autouse do conftest); os agregadores
    (dossie/grafo_poder/lex_conflito) resolvem o caminho do DB em call-time via `_resolver_db()`,
    então respeitam o JFN_DB — assim NUNCA lêem nem escrevem a `compliance.db` de produção;
  - desliga a rede: mocka os coletores externos (BrasilAPI/CEIS/OpenSanctions/Aleph/GDELT)
    para retornos fixos → rápido, offline e determinístico (não depende de WAF/DNS da VM);
  - desliga o PDF (`gerar_pdf=False`) → não depende de Playwright/Skia/FPDF.

Honesto: o smoke NÃO valida o conteúdo real das fontes externas nem a geração de PDF
(testados manualmente). Valida que a agregação retorna `ok=True` com a estrutura esperada.
"""
import asyncio
from datetime import date

import pytest

# CNPJ sintético (14 dígitos) — só existe no DB isolado deste teste.
_CNPJ = "12345678000195"


@pytest.fixture
def _db_isolado(tmp_path):
    """Cria o tmp DB (apontado por JFN_DB pela fixture `_isola_db` do conftest) e semeia 1 OB.
    Os agregadores resolvem o DB em call-time via `_resolver_db()` → respeitam o JFN_DB sozinhos."""
    import os

    from compliance_agent.database.models import OrdemBancaria, get_session, init_db

    # A fixture autouse `_isola_db` já setou JFN_DB → tmp_path/test_compliance.db.
    db_path = os.environ["JFN_DB"]
    init_db()
    s = get_session()
    try:
        # Mínimo p/ `_resumo_ob` retornar total/concentração: 1 OB com favorecido_cpf=CNPJ + valor.
        s.add(OrdemBancaria(
            numero_ob="2026OBSMOKE1", data_emissao=date(2026, 1, 10),
            favorecido_cpf=_CNPJ, favorecido_nome="DOSSIE SMOKE LTDA",
            ug_codigo="133100", valor=250000.0,
        ))
        s.commit()
    finally:
        s.close()
    return db_path


@pytest.fixture
def _sem_rede(monkeypatch):
    """Desliga TODA chamada externa do dossiê → determinístico e offline (sem WAF/DNS da VM)."""
    import compliance_agent.collectors.cnpj as cnpj_mod
    import compliance_agent.collectors.ceis as ceis_mod
    import compliance_agent.enrich.midia_adversa as midia_mod

    async def _fake_cnpj(cnpj, client=None):
        return {"razao_social": "DOSSIE SMOKE LTDA", "cnae_principal": "Construção de edifícios"}

    async def _fake_ceis(cnpj):
        return {"verificado": True, "sancionado": False, "sancoes": []}

    monkeypatch.setattr(cnpj_mod, "buscar_cnpj", _fake_cnpj)
    monkeypatch.setattr(ceis_mod, "verificar_sancao", _fake_ceis)
    monkeypatch.setattr(midia_mod, "varrer", lambda *a, **k: {"_nota": "INDISPONÍVEL (smoke)", "artigos": []})


def test_dossie_smoke_estrutura(_db_isolado, _sem_rede):
    """`dossie()` retorna ok=True com a estrutura básica (perfil/OB/rede/score) sem crashar."""
    from compliance_agent.dossie import dossie

    res = asyncio.run(dossie(alvo=_CNPJ, gerar_pdf=False))

    # 1) Não crashou e identificou o alvo.
    assert res["ok"] is True
    assert res["alvo"] == _CNPJ

    # 2) Blocos estruturais presentes (best-effort, mas a CHAVE existe sempre).
    for chave in ("cadastro", "sancoes", "ob", "conflito", "rede", "score"):
        assert chave in res, f"bloco esperado ausente no dossiê: {chave}"

    # 3) Score de convergência decomponível — a estrutura, não o número (frágil).
    score = res["score"]
    assert "score" in score and "faixa" in score
    assert isinstance(score["score"], (int, float))

    # 4) OB agregada a partir do dado semeado (250k em 1 UG → concentração total).
    ob = res["ob"]
    assert ob.get("n_ob") == 1
    assert ob.get("total_ob") == 250000.0
    assert ob.get("concentracao_top_ug") == 1.0

    # 5) PDF desligado → não tentou gerar (sem path nem erro de PDF).
    assert "path_pdf" not in res

    # 6) Nota de honestidade presente (invariante do produto: indício ≠ acusação).
    assert "_nota" in res


def test_dossie_smoke_cnpj_invalido():
    """CNPJ malformado degrada honesto (ok=False), sem crash e sem tocar o DB."""
    from compliance_agent.dossie import dossie

    res = asyncio.run(dossie(alvo="123", gerar_pdf=False))
    assert res["ok"] is False
    assert "erro" in res
