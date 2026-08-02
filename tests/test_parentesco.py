# -*- coding: utf-8 -*-
"""Parentesco inferido — e a regra que impede o eixo prevalente de acender sozinho.

O QUE ESTE TESTE PROTEGE. Não é a capacidade de achar parentesco: é a de NÃO acusar um quinto do
acervo. As medições de 2026-07-29 sobre 31.132 raízes com QSA:

  · co-ocorrência societária das mesmas duas pessoas em 2+ empresas — **4,76%**  (sinal)
  · coabitação (endereço idêntico entre empresas distintas)        — **3,9%**   (sinal)
  · sobrenome de família repetido no MESMO QSA                     — **16,9%**  (NÃO é sinal)
  · sobrenome raro compartilhado ENTRE empresas                    — **25,9%**  (NÃO é sinal)

Empresa familiar é a norma no Brasil, e o corte por raridade quase não move o número (16,9% → 10,6%
exigindo sobrenome com ≤3 ocorrências). Deixar sobrenome pontuar isolado seria repetir o defeito que
a casa já corrigiu três vezes: o laranja que marcava 55% da base, o P1 que acusava 71% dos certames,
os dois detectores de lift anti-preditivo.

Rodar só este arquivo:  .venv/bin/python -m pytest tests/test_parentesco.py -q
"""
from __future__ import annotations

import sqlite3

import pytest

from compliance_agent.osint.parentesco import DILIGENCIA, EIXOS, avaliar, familias_do_qsa

_DDL = """
CREATE TABLE socios_receita (
  cnpj_basico TEXT, ident TEXT, nome_socio TEXT, nome_norm TEXT, doc_socio TEXT,
  qualificacao_cod TEXT, qualificacao_txt TEXT, data_entrada TEXT, faixa_etaria TEXT,
  fonte_mes TEXT);
CREATE TABLE endereco_fornecedor (
  cnpj TEXT PRIMARY KEY, razao TEXT, endereco TEXT, endereco_norm TEXT, municipio TEXT,
  uf TEXT, cep TEXT, atualizado_em TEXT);
"""


def _ins(con, raiz, nome, doc, faixa="5", qualif="Sócio"):
    con.execute(
        "INSERT INTO socios_receita (cnpj_basico, ident, nome_socio, nome_norm, doc_socio, "
        "qualificacao_txt, data_entrada, faixa_etaria, fonte_mes) "
        "VALUES (?,'2',?,?,?,?,'20200101',?, '2026-07')",
        (raiz, nome, nome.upper(), doc, qualif, faixa))


@pytest.fixture()
def con():
    c = sqlite3.connect(":memory:")
    c.executescript(_DDL)
    yield c
    c.close()


# ─────────────────────────────────────────────────────────────────────────────
# A regra central
# ─────────────────────────────────────────────────────────────────────────────

def test_sobrenome_sozinho_nao_passa_de_hipotese_fraca(con):
    """Dois irmãos aparentes numa empresa familiar. Prevalência 16,9%: não sustenta indício."""
    _ins(con, "11111111", "JOAO PEREIRA MACHADO", "***111111**")
    _ins(con, "11111111", "MARIA PEREIRA MACHADO", "***222222**")
    r = avaliar(con, "11111111")
    assert r["grau"] == "hipotese_fraca"
    assert [e["id"] for e in r["eixos_acionados"]] == ["sobrenome_no_qsa"]
    assert r["falso_positivo_esperado_pct"] == pytest.approx(16.9)
    assert "mede a base, não o alvo" in r["leitura"]


def test_eixo_prevalente_esta_marcado_como_incapaz_de_acender_sozinho():
    assert EIXOS["sobrenome_no_qsa"].pode_acender_sozinho is False
    assert EIXOS["sobrenome_entre_empresas"].pode_acender_sozinho is False
    assert EIXOS["coocorrencia_societaria"].pode_acender_sozinho is True
    assert EIXOS["coabitacao"].pode_acender_sozinho is True
    # e a prevalência de cada um tem de estar declarada, para o leitor calcular o falso positivo
    for e in EIXOS.values():
        assert e.prevalencia_medida > 0
        assert e.exculpatoria, f"eixo {e.id} sem explicação inocente"
        # o limiar não é opinião: acima de ~10% o eixo mede a base
        assert e.pode_acender_sozinho == (e.prevalencia_medida < 10.0)


def test_coocorrencia_societaria_sustenta_hipotese(con):
    """As MESMAS duas pessoas sócias de duas empresas — eixo forte, 4,76% da base."""
    for raiz in ("11111111", "22222222"):
        _ins(con, raiz, "ANA COSTA LIMA", "***111111**")
        _ins(con, raiz, "BRUNO SANTOS REIS", "***222222**")
    r = avaliar(con, "11111111")
    assert r["grau"] == "hipotese"
    ids = {e["id"] for e in r["eixos_acionados"]}
    assert "coocorrencia_societaria" in ids
    assert any(len(h["empresas_em_comum"]) >= 2 for h in r["hipoteses"] if "empresas_em_comum" in h)


def test_convergencia_de_eixos_chega_a_indicio(con):
    """Mesma família E as mesmas pessoas em duas empresas: dois eixos, um deles forte."""
    for raiz in ("11111111", "22222222"):
        _ins(con, raiz, "ANA COSTA LIMA", "***111111**", faixa="5")
        _ins(con, raiz, "PEDRO COSTA LIMA", "***222222**", faixa="3")
    r = avaliar(con, "11111111")
    assert r["grau"] in ("hipotese", "indicio")
    ids = {e["id"] for e in r["eixos_acionados"]}
    assert {"coocorrencia_societaria", "sobrenome_no_qsa"} <= ids
    tipos = {h["tipo_provavel"] for h in r["hipoteses"]}
    assert "ascendente_descendente" in tipos, (
        "faixas 5 (41-50) e 3 (21-30) devem sugerir ascendente/descendente, não cônjuge"
    )


def test_qsa_sem_eixo_nao_afasta_parentesco(con):
    """Silêncio não é limpeza — nenhuma base aberta publica filiação."""
    _ins(con, "11111111", "CARLOS ANDRADE", "***111111**")
    r = avaliar(con, "11111111")
    assert r["grau"] is None
    assert r["hipoteses"] == []
    assert "INDISPONÍVEL, não ausência" in r["leitura"]
    assert r["diligencia"] is None


def test_toda_hipotese_carrega_diligencia_e_metodologia(con):
    _ins(con, "11111111", "JOAO PEREIRA MACHADO", "***111111**")
    _ins(con, "11111111", "MARIA PEREIRA MACHADO", "***222222**")
    r = avaliar(con, "11111111")
    assert r["diligencia"] is DILIGENCIA
    assert any("JUCERJA" in f for f in DILIGENCIA["fontes"])
    assert "CGU" in " ".join(DILIGENCIA["fontes"])
    assert "TCU" in DILIGENCIA["metodologia_citavel"]
    assert "restritas não disponíveis" in DILIGENCIA["metodologia_citavel"], (
        "citar o método do TCU sem declarar que o insumo dele não é nosso seria fingir a fonte"
    )


def test_familias_do_qsa_extrai_sobrenome(con):
    _ins(con, "11111111", "JOAO PEREIRA MACHADO NETO", "***111111**")
    s = familias_do_qsa(con, "11111111")[0]
    assert s["familia"] == "PEREIRA MACHADO", "sufixo Neto tem de ser ignorado"
    assert s["doc"] == "***111111**"


# ── prevalência sobre o acervo real ──────────────────────────────────────────

def _tem_base() -> bool:
    """A base serve para ESTE teste? Existir o arquivo não basta.

    No runner do CI o `compliance.db` é CRIADO vazio por outros testes, então o guard antigo
    (só `Path(_DB).exists()`) deixava este teste rodar contra um banco sem tabelas e quebrar com
    `no such table: socios_receita` — falha de ambiente disfarçada de regressão. Mesmo vício que
    a corrida da árvore do SEI (2026-08-02): **checar presença quando o que importa é conteúdo**.
    """
    import sqlite3
    from pathlib import Path

    from compliance_agent.reporting.intel_base import _DB
    if not Path(_DB).exists():
        return False
    try:
        con = sqlite3.connect(f"file:{_DB}?mode=ro", uri=True)
        try:
            return bool(con.execute(
                "select 1 from sqlite_master where type='table' and name='socios_receita'").fetchone())
        finally:
            con.close()
    except sqlite3.Error:
        return False


@pytest.mark.skipif(not _tem_base(), reason="compliance.db ausente nesta máquina")
def test_calibracao_nao_envelheceu_em_silencio():
    """Recalcula a prevalência na base de hoje e compara com a calibração declarada. Se um eixo
    dobrou de prevalência, ele deixou de discriminar — e o produto precisa saber antes de acender."""
    from compliance_agent.osint.parentesco import prevalencia

    p = prevalencia()
    for eixo_id, medida in p["eixos"].items():
        declarada = EIXOS[eixo_id].prevalencia_medida
        assert medida <= max(declarada * 2.0, declarada + 10.0), (
            f"eixo {eixo_id}: prevalência real {medida}% contra {declarada}% declarada — "
            "recalibrar antes de continuar usando"
        )
    assert p["eixos"]["coocorrencia_societaria"] < 10.0, (
        "o eixo forte deixou de ser raro; revisar `pode_acender_sozinho`"
    )
