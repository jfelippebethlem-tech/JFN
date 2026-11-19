# -*- coding: utf-8 -*-
"""Medição do ingest do SIAFE: INDISPONÍVEL ≠ 0, UG nunca lida não vira 'zero NE', status congelado por idade."""
import sqlite3
from datetime import datetime

from compliance_agent import siafe_ingest_cobertura as M

HOJE = datetime(2026, 11, 19, 9, 0)


def _db(tmp_path, com_nl=True):
    p = tmp_path / "c.db"
    c = sqlite3.connect(p)
    c.execute("CREATE TABLE ob_orcamentaria_siafe(numero_ob,ug_emitente,exercicio,data_emissao,status,status_envio,"
              "valor,credor,nl,processo,coletado_em,ug_pagadora,tipo,finalidade,tipo_ob,ug_liquidante,competencia,gd,re,"
              "pd,tipo_regularizacao,qtd_impressoes,assinatura_digital,vinculacao_pagamento)")
    linhas = [
        ("2026OB1", "A", 2026, "10/11/2026", "Contabilizado", "Enviado ao Banco", 100.0, "11111111000101",
         "2026NL00001", "SEI-123456/000001/2026", "2026-11-11 08:00:00"),
        ("2026OB2", "A", 2026, "10/07/2026", "Contabilizado", "Enviado ao Banco", 50.0, "11111111000101",
         "2026NL00002", "", "2026-07-11 08:00:00"),
        ("2026OB3", "B", 2026, "10/07/2026", "Contabilizado", "Processado e Pago", 70.0, "11111111000101",
         "2026NL00003", "123456/000001/2026", "2026-07-11 08:00:00"),
    ]
    c.executemany("INSERT INTO ob_orcamentaria_siafe(numero_ob,ug_emitente,exercicio,data_emissao,status,status_envio,"
                  "valor,credor,nl,processo,coletado_em) VALUES (?,?,?,?,?,?,?,?,?,?,?)", linhas)
    c.execute("CREATE TABLE siafe_documento_cobertura(tipo,ug_emitente,exercicio,completo,colhidas,em)")
    c.execute("INSERT INTO siafe_documento_cobertura VALUES ('NL','A',2026,1,1,'2026-11-18 03:00:00')")
    if com_nl:
        c.execute("CREATE TABLE nl_siafe(numero,ug_emitente,exercicio,ne)")
        c.execute("INSERT INTO nl_siafe VALUES ('2026NL00001','A',2026,'')")
    c.commit()
    c.close()
    return p


def test_ug_nunca_lida_e_tabela_ausente_nao_viram_zero(tmp_path):
    m = M.medir(db=_db(tmp_path), exercicios=(2026,), hoje=HOJE)
    nl = m["documentos"]["NL"][2026]
    assert (nl["completas"], nl["nunca_lidas"], nl["universo_ugs"]) == (1, 1, 2)
    assert nl["nl_citadas_pela_ob"] == 3 and nl["nl_citadas_achadas"] == 1
    assert m["documentos"]["NE"][2026]["estado"] == "INDISPONÍVEL"          # ne_siafe não existe
    assert m["ob"][2025]["estado"] == "INDISPONÍVEL" if 2025 in m["ob"] else True


def test_status_congelado_separa_recente_de_velho_e_conta_foto_precoce(tmp_path):
    st = M.medir(db=_db(tmp_path), exercicios=(2026,), hoje=HOJE)["status"][2026]
    assert st["intermediarios"]["ate_60d"]["n"] == 1 and st["intermediarios"]["mais_60d"]["n"] == 1
    assert st["foto_precoce_nunca_relida"]["n"] == 2                    # as duas colhidas 1 dia após a emissão


def test_processo_do_fornecedor_por_legibilidade(tmp_path):
    p = M.medir(db=_db(tmp_path), exercicios=(2026,), hoje=HOJE)["ob"][2026]["processo_fornecedor"]
    assert {k: v["n"] for k, v in p.items()} == {"sei": 1, "sei_sem_prefixo": 1, "vazio": 1}


def test_sem_tabela_de_ob_tudo_indisponivel(tmp_path):
    p = tmp_path / "vazio.db"
    sqlite3.connect(p).close()
    assert M.medir(db=p)["estado"] == "INDISPONÍVEL"
