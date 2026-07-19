# -*- coding: utf-8 -*-
"""Teste TARGETED do detector J8 — atestado de capacidade técnica cruzado (Ac. TCU 725/2026).

Estratégia (leve, VM 2 vCPU): fixtures de CONTEXTO (dicts) + sqlite temporário; sem rede/LLM.
Cobre: (a) identidade/peso; (b) nao_avaliavel sem entradas (campo ausente ≠ 0); (c) CONFIRMADO
'forte' com achados injetados (hook de teste) e explicação inocente presente; (d) DESCARTADO
registrado quando avaliou e não achou; (e) pipeline real: extrair_atestados acha o emissor no
papel timbrado + vinculos_emissor_licitante flagra sócio em comum (guard de homonímia ativo).
Rodar só este arquivo:  .venv/bin/python -m pytest tests/test_detector_j8.py -q
"""
from __future__ import annotations

import sqlite3

from compliance_agent.detectores.base import STATUS_VALIDOS, ResultadoDetector
from compliance_agent.detectores.j_atestado_cruzado import (
    JAtestadoCruzado, atestado_cruzado, extrair_atestados)

EMISSOR = "11222333000181"
LICITANTE = "99888777000166"

TEXTO_HABILITACAO = (
    "EMISSORA ENGENHARIA LTDA — CNPJ 11.222.333/0001-81 — Av. X, 100\n"
    "ATESTADO DE CAPACIDADE TÉCNICA\n"
    "Atestamos que a empresa LICITANTE OBRAS EIRELI, CNPJ 99.888.777/0001-66, executou "
    "a contento os serviços de manutenção predial no período de 2023-2024."
)


def _valido(r: ResultadoDetector) -> None:
    """Invariantes do schema §1.4."""
    assert isinstance(r, ResultadoDetector)
    assert r.status in STATUS_VALIDOS
    assert 0.0 <= r.score <= 1.0
    assert isinstance(r.evidencia, list)


def _db_com_socio_comum(tmp_path, nome="MARIA APARECIDA DOS SANTOS"):
    db = str(tmp_path / "compliance.db")
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE socios_fornecedor (cnpj TEXT, socio_nome TEXT, socio_nome_norm TEXT)")
    con.executemany("INSERT INTO socios_fornecedor VALUES (?,?,?)",
                    [(EMISSOR, nome, nome), (LICITANTE, nome, nome)])
    con.execute("CREATE TABLE socios_receita (cnpj_basico TEXT, nome_socio TEXT, nome_norm TEXT)")
    con.execute("CREATE TABLE endereco_fornecedor (cnpj TEXT, endereco_norm TEXT)")
    con.commit(); con.close()
    return db


def test_j8_identidade():
    det = JAtestadoCruzado()
    assert det.id == "J8"
    assert det.familia == "conluio"


def test_j8_sem_entradas_e_nao_avaliavel():
    r = JAtestadoCruzado().avaliar({"processo": "p1"})
    _valido(r)
    assert r.status == "nao_avaliavel"
    assert "ausente" in (r.motivo_refutacao or "")


def test_j8_confirmado_com_achados_injetados():
    ctx = {"processo": "p2", "achados_atestado": [{
        "emissor_cnpj": EMISSOR, "licitante_cnpj": LICITANTE,
        "vinculos": ["qsa"], "evidencia": "trecho", "fundamento": "Ac. TCU 725/2026"}]}
    r = JAtestadoCruzado().avaliar(ctx)
    _valido(r)
    assert r.status == "confirmado"
    assert r.score >= 0.7                       # âncora 'forte'
    assert r.explicacao_inocente               # grupo econômico declarado — sempre presente
    assert any("qsa" in e.get("trecho", "") for e in r.evidencia)


def test_j8_avaliado_sem_achado_e_descartado():
    r = JAtestadoCruzado().avaliar({"processo": "p3", "achados_atestado": []})
    _valido(r)
    assert r.status == "descartado"
    assert "nenhum atestado" in (r.motivo_refutacao or "")


def test_j8_pipeline_real_socio_comum(tmp_path):
    db = _db_com_socio_comum(tmp_path)
    blocos = extrair_atestados(TEXTO_HABILITACAO)
    assert len(blocos) == 1 and blocos[0]["emissor_cnpj"] == EMISSOR  # papel timbrado ANTES do marcador
    achados = atestado_cruzado(TEXTO_HABILITACAO, LICITANTE, db)
    assert len(achados) == 1
    assert achados[0]["vinculos"] == ["qsa"]
    r = JAtestadoCruzado().avaliar({"processo": "p4", "texto_habilitacao": TEXTO_HABILITACAO,
                                    "licitante_cnpj": LICITANTE, "db_path": db})
    _valido(r)
    assert r.status == "confirmado"


def test_j8_emissor_igual_licitante_nao_conta(tmp_path):
    db = _db_com_socio_comum(tmp_path)
    texto = ("LICITANTE OBRAS EIRELI CNPJ 99.888.777/0001-66\n"
             "ATESTADO DE CAPACIDADE TÉCNICA\nAtestamos que executou os serviços.")
    assert atestado_cruzado(texto, LICITANTE, db) == []   # auto-atestado ≠ cruzado
