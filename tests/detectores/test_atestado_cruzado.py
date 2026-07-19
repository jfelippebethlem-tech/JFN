# -*- coding: utf-8 -*-
"""Teste TARGETED do detector J8 (atestado de capacidade técnica cruzado — Ac. TCU 725/2026).

Estratégia (leve, VM 2 vCPU): texto sintético de habilitação + sqlite tmp com as MESMAS tabelas/colunas
do compliance.db real (schema espiado por PRAGMA em 2026-07-19: socios_receita.cnpj_basico/nome_norm,
socios_fornecedor.cnpj/socio_nome_norm, endereco_fornecedor.cnpj/endereco_norm). Nunca toca o DB de produção.
Cobre: extração de atestado+CNPJ emissor (formatado e cru); vínculo QSA e endereço; guards anti-FP;
pipeline completo com fundamento; schema §1.4 do detector.
Rodar só este arquivo:  .venv/bin/python -m pytest tests/detectores/test_atestado_cruzado.py -q
"""
from __future__ import annotations

import sqlite3

import pytest

from compliance_agent.detectores.base import ANCORAS, STATUS_VALIDOS, ResultadoDetector
from compliance_agent.detectores.j_atestado_cruzado import (
    FUNDAMENTO,
    JAtestadoCruzado,
    atestado_cruzado,
    extrair_atestados,
    vinculos_emissor_licitante,
)

EMISSOR = "11222333000144"
LICITANTE = "55666777000188"

TEXTO = (
    "EMISSORA ENGENHARIA LTDA, inscrita no CNPJ 11.222.333/0001-44, com sede na Rua das Obras, 100, Rio de Janeiro.\n"
    "ATESTADO DE CAPACIDADE TECNICA\n"
    "Atestamos que a empresa LICITANTE OBRAS EIRELI, CNPJ 55.666.777/0001-88, executou a seu contento os servicos "
    "de manutencao predial no periodo de 2023 a 2024, cumprindo prazos, quantidades e especificacoes contratadas."
)


@pytest.fixture
def db_path(tmp_path) -> str:
    """sqlite tmp com as mesmas tabelas/colunas do compliance.db real (subconjunto usado pelo detector)."""
    caminho = tmp_path / "compliance.db"
    con = sqlite3.connect(caminho)
    con.executescript(
        """
        CREATE TABLE socios_receita (cnpj_basico TEXT, ident TEXT, nome_socio TEXT, nome_norm TEXT,
            doc_socio TEXT, qualificacao_cod TEXT, qualificacao_txt TEXT, data_entrada TEXT,
            faixa_etaria TEXT, fonte_mes TEXT);
        CREATE TABLE socios_fornecedor (cnpj TEXT, razao TEXT, socio_nome TEXT, socio_nome_norm TEXT,
            socio_doc TEXT, qualificacao TEXT, ingerido_em TEXT);
        CREATE TABLE endereco_fornecedor (cnpj TEXT, razao TEXT, endereco TEXT, endereco_norm TEXT,
            municipio TEXT, uf TEXT, cep TEXT, atualizado_em TEXT);
        """
    )
    # sócio em comum entre emissor e licitante (match por nome_norm, como no DB real)
    con.execute("INSERT INTO socios_receita (cnpj_basico, nome_socio, nome_norm) VALUES (?,?,?)",
                (EMISSOR[:8], "JOAO DA SILVA SANTOS", "JOAO DA SILVA SANTOS"))
    con.execute("INSERT INTO socios_receita (cnpj_basico, nome_socio, nome_norm) VALUES (?,?,?)",
                (LICITANTE[:8], "JOAO DA SILVA SANTOS", "JOAO DA SILVA SANTOS"))
    con.commit()
    con.close()
    return str(caminho)


def _conectar_ro(db_path: str) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)


# ═══════════════════════════════ extrair_atestados ═══════════════════════════════
def test_extrai_emissor_do_papel_timbrado():
    """Emissor = último CNPJ ANTES do marcador (papel timbrado); os 2 marcadores próximos = 1 bloco só."""
    achados = extrair_atestados(TEXTO)
    assert len(achados) == 1
    assert achados[0]["emissor_cnpj"] == EMISSOR
    assert LICITANTE in achados[0]["cnpjs_bloco"]
    assert "Atestamos que" in achados[0]["evidencia"]


def test_extrai_cnpj_cru_apos_marcador():
    """CNPJ sem formatação (14 dígitos corridos) e emissor APÓS o marcador (fallback)."""
    texto = ("Atestado de Capacidade Tecnica. Emitido por CONSTRUTORA BETA SA, CNPJ 99888777000166, "
             "em favor da contratada, pela execucao de obras de pavimentacao.")
    achados = extrair_atestados(texto)
    assert len(achados) == 1
    assert achados[0]["emissor_cnpj"] == "99888777000166"


def test_texto_sem_atestado_ou_sem_cnpj_nao_gera_bloco():
    assert extrair_atestados("Relatorio de visita tecnica sem atestado algum.") == []
    assert extrair_atestados("Atestamos que os servicos foram prestados a contento.") == []  # sem CNPJ → fora
    assert extrair_atestados("") == []


# ═══════════════════════════════ vinculos_emissor_licitante ═══════════════════════════════
def test_vinculo_qsa_por_socio_comum(db_path):
    db = _conectar_ro(db_path)
    try:
        assert vinculos_emissor_licitante(EMISSOR, LICITANTE, db) == ["qsa"]
    finally:
        db.close()


def test_vinculo_endereco_igual(db_path):
    con = sqlite3.connect(db_path)
    end = "RUADASOBRAS100SALA201CENTRORIODEJANEIRORJ20000000"
    con.execute("DELETE FROM socios_receita")  # isola o sinal de endereço
    con.execute("INSERT INTO endereco_fornecedor (cnpj, endereco_norm) VALUES (?,?)", (EMISSOR, end))
    con.execute("INSERT INTO endereco_fornecedor (cnpj, endereco_norm) VALUES (?,?)", (LICITANTE, end))
    con.commit(); con.close()
    db = _conectar_ro(db_path)
    try:
        assert vinculos_emissor_licitante(EMISSOR, LICITANTE, db) == ["endereco"]
    finally:
        db.close()


def test_sem_vinculo_retorna_vazio(db_path):
    db = _conectar_ro(db_path)
    try:
        assert vinculos_emissor_licitante("00999888000155", LICITANTE, db) == []
    finally:
        db.close()


def test_guard_nome_curto_nao_vincula(db_path):
    """Nome de sócio < 5 chars (homonímia trivial) não sustenta vínculo QSA."""
    con = sqlite3.connect(db_path)
    con.execute("DELETE FROM socios_receita")
    for basico in (EMISSOR[:8], LICITANTE[:8]):
        con.execute("INSERT INTO socios_receita (cnpj_basico, nome_socio, nome_norm) VALUES (?,?,?)",
                    (basico, "ANA", "ANA"))
    con.commit(); con.close()
    db = _conectar_ro(db_path)
    try:
        assert vinculos_emissor_licitante(EMISSOR, LICITANTE, db) == []
    finally:
        db.close()


# ═══════════════════════════════ atestado_cruzado (pipeline) ═══════════════════════════════
def test_atestado_cruzado_achado_completo(db_path):
    achados = atestado_cruzado(TEXTO, "55.666.777/0001-88", db_path)
    assert len(achados) == 1
    a = achados[0]
    assert a["emissor_cnpj"] == EMISSOR
    assert a["licitante_cnpj"] == LICITANTE
    assert a["vinculos"] == ["qsa"]
    assert a["fundamento"] == FUNDAMENTO == "Ac. TCU 725/2026"
    assert "Atestamos que" in a["evidencia"]


def test_emissor_igual_ao_licitante_nao_e_achado_deste_detector(db_path):
    texto = TEXTO.replace("11.222.333/0001-44", "55.666.777/0001-88")
    assert atestado_cruzado(texto, LICITANTE, db_path) == []


def test_sem_vinculo_no_db_sem_achado(tmp_path, db_path):
    con = sqlite3.connect(db_path)
    con.execute("DELETE FROM socios_receita")
    con.commit(); con.close()
    assert atestado_cruzado(TEXTO, LICITANTE, db_path) == []


def test_licitante_cnpj_invalido_degrada_honesto(db_path, caplog):
    import logging
    with caplog.at_level(logging.WARNING, logger="compliance_agent.detectores.j_atestado_cruzado"):
        assert atestado_cruzado(TEXTO, "cnpj-invalido", db_path) == []
    assert any("NÃO realizada" in r.message for r in caplog.records)


# ═══════════════════════════════ detector J8 (schema §1.4) ═══════════════════════════════
def _valido(r: ResultadoDetector) -> None:
    assert isinstance(r, ResultadoDetector)
    assert r.status in STATUS_VALIDOS
    assert 0.0 <= r.score <= 1.0
    d = r.to_dict()
    assert set(d) == {"detector", "processo", "score", "valores", "evidencia",
                      "explicacao_inocente", "refutada", "motivo_refutacao", "status"}


def test_j8_confirma_com_vinculo(db_path):
    ctx = {"processo": "cert-1", "texto_habilitacao": TEXTO,
           "licitante_cnpj": LICITANTE, "db_path": db_path}
    r = JAtestadoCruzado().avaliar(ctx)
    _valido(r)
    assert r.status == "confirmado"
    assert r.score == ANCORAS["forte"]
    assert r.valores["n_achados"] == 1
    assert r.evidencia and FUNDAMENTO in r.evidencia[0]["fonte"]
    assert r.explicacao_inocente  # honestidade: a explicação inocente clássica vem preenchida


def test_j8_descartado_sem_vinculo(db_path):
    con = sqlite3.connect(db_path)
    con.execute("DELETE FROM socios_receita")
    con.commit(); con.close()
    r = JAtestadoCruzado().avaliar({"processo": "cert-2", "texto_habilitacao": TEXTO,
                                    "licitante_cnpj": LICITANTE, "db_path": db_path})
    _valido(r)
    assert r.status == "descartado"
    assert r.score == ANCORAS["ausente"]


def test_j8_sem_entradas_nao_avaliavel():
    r = JAtestadoCruzado().avaliar({"processo": "cert-3"})
    _valido(r)
    assert r.status == "nao_avaliavel"
    assert "nao_avaliavel" in r.motivo_refutacao


def test_j8_registrado_no_registro():
    from compliance_agent.detectores import PESOS_DETECTOR, REGISTRO
    assert "J8" in REGISTRO
    assert PESOS_DETECTOR["J8"] == pytest.approx(0.9)
