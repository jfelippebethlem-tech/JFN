# -*- coding: utf-8 -*-
"""Testes do sweep de benefícios dos sócios (laranja). Sem rede/SQL pesado: montam um SQLite temporário
com `socios_fornecedor` + índices/`beneficio_fn` injetados. Cobrem: gravação resolvido+benefício,
INDISPONÍVEL honesto p/ sócio não resolvido, resumibilidade (não reprocessa) e detecção de fila vazia."""
import asyncio
import json
import sqlite3

from compliance_agent.resolucao_cpf import carregar_indice_favorecidos
from tools import beneficios_sweep as bsw


def _db(tmp_path, socios, favorecidos=()):
    p = tmp_path / "compliance.db"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE socios_fornecedor (cnpj TEXT, razao TEXT, socio_nome TEXT, "
                "socio_nome_norm TEXT, socio_doc TEXT, qualificacao TEXT, ingerido_em TEXT)")
    con.executemany("INSERT INTO socios_fornecedor (cnpj, socio_nome_norm, socio_doc) VALUES (?,?,?)", socios)
    con.execute("CREATE TABLE ordens_bancarias (favorecido_cpf TEXT, favorecido_nome TEXT)")
    con.executemany("INSERT INTO ordens_bancarias VALUES (?,?)", favorecidos)
    con.commit()
    con.close()
    return p


def _run(coro):
    return asyncio.run(coro)


async def _benef_recebe(cpf):  # fake do verificar_beneficios — recebe Bolsa Família
    return {"verificado": True, "recebe_beneficio": True,
            "beneficios": [{"tipo": "Bolsa Família"}], "motivo": ""}


async def _benef_indisponivel(cpf):
    return {"verificado": False, "recebe_beneficio": None, "beneficios": [], "motivo": "sem chave"}


def test_resolve_e_grava_beneficio(tmp_path):
    # sócio cujo CPF (11122334455, middle6=223344) está nos favorecidos PF → resolve e consulta benefício
    p = _db(tmp_path, [("CNPJ1", "JOAO DA SILVA", "***223344**")],
            favorecidos=[("11122334455", "JOAO DA SILVA")])
    pf_idx = carregar_indice_favorecidos(db_path=p)
    r = _run(bsw.processar_lote(p, 10, pf_idx=pf_idx, tse_idx={}, beneficio_fn=_benef_recebe))
    assert r == {"processados": 1, "resolvidos": 1, "com_beneficio": 1}
    con = sqlite3.connect(p)
    row = con.execute("SELECT resolvido, cpf_resolvido, fonte, verificado, recebe_beneficio, beneficios_json "
                      "FROM socio_beneficio").fetchone()
    assert row[0] == 1 and row[1] == "11122334455" and row[2] == "favorecidos_pf"
    assert row[3] == 1 and row[4] == 1 and "Bolsa Família" in json.loads(row[5])


def test_nao_resolvido_e_indisponivel_honesto(tmp_path):
    # sócio sem correspondência → grava resolvido=0, sem consultar benefício (recebe_beneficio NULL)
    p = _db(tmp_path, [("CNPJ1", "MARIA SOUZA", "***999999**")])
    r = _run(bsw.processar_lote(p, 10, pf_idx={}, tse_idx={}, beneficio_fn=_benef_recebe))
    assert r == {"processados": 1, "resolvidos": 0, "com_beneficio": 0}
    con = sqlite3.connect(p)
    row = con.execute("SELECT resolvido, recebe_beneficio, verificado FROM socio_beneficio").fetchone()
    assert row[0] == 0 and row[1] is None and row[2] == 0  # INDISPONÍVEL ≠ "não recebe"


def test_resolvido_mas_beneficio_indisponivel(tmp_path):
    # resolve o CPF, mas a API de benefícios não responde → verificado=0, recebe NULL (honesto)
    p = _db(tmp_path, [("CNPJ1", "JOAO DA SILVA", "***223344**")],
            favorecidos=[("11122334455", "JOAO DA SILVA")])
    pf_idx = carregar_indice_favorecidos(db_path=p)
    r = _run(bsw.processar_lote(p, 10, pf_idx=pf_idx, tse_idx={}, beneficio_fn=_benef_indisponivel))
    assert r == {"processados": 1, "resolvidos": 1, "com_beneficio": 0}
    con = sqlite3.connect(p)
    row = con.execute("SELECT resolvido, verificado, recebe_beneficio FROM socio_beneficio").fetchone()
    assert row[0] == 1 and row[1] == 0 and row[2] is None


def test_resumivel_nao_reprocessa(tmp_path):
    # 2º lote não reprocessa o que já está em socio_beneficio (fila vazia → processados=0)
    p = _db(tmp_path, [("CNPJ1", "JOAO DA SILVA", "***223344**")],
            favorecidos=[("11122334455", "JOAO DA SILVA")])
    pf_idx = carregar_indice_favorecidos(db_path=p)
    _run(bsw.processar_lote(p, 10, pf_idx=pf_idx, tse_idx={}, beneficio_fn=_benef_recebe))
    r2 = _run(bsw.processar_lote(p, 10, pf_idx=pf_idx, tse_idx={}, beneficio_fn=_benef_recebe))
    assert r2 == {"processados": 0, "resolvidos": 0, "com_beneficio": 0}  # fila vazia (supervisor → back-off)


def test_ignora_socio_nao_mascarado_e_sem_nome(tmp_path):
    # doc sem '*' (não é QSA mascarado) e nome vazio não entram na fila
    p = _db(tmp_path, [("CNPJ1", "", "***223344**"), ("CNPJ2", "FULANO", "11122334455")])
    r = _run(bsw.processar_lote(p, 10, pf_idx={}, tse_idx={}, beneficio_fn=_benef_recebe))
    assert r["processados"] == 0
