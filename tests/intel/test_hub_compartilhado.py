# -*- coding: utf-8 -*-
"""hub_compartilhado — 1 âncora física (endereço/telefone/e-mail) com N CNPJs (ninho de fantasmas).

DB principal tmp (favorecido_resumo mínima) + DB estab tmp (tabela `estabelecimentos`).
Nunca toca o data/receita_estab.db real — tudo em sqlite temporário.
"""
from __future__ import annotations

import sqlite3

import pytest

from compliance_agent.cruzamentos_intel import hub_compartilhado

ENDERECO_NINHO = "RUA DAS FLORES 100 CENTRO 20000000"
EMAIL_CONTABIL = "contato@contabilidade.com.br"
EMAIL_NINHO = "laranja@ninho.io"
TELEFONE_MASSA = "21999990000"


def _cnpj(pref: str, i: int) -> str:
    return pref[:2] + str(i).zfill(12)


@pytest.fixture()
def dbs(tmp_path):
    """(db_principal, db_estab) — retorna os dois caminhos."""
    main = str(tmp_path / "compliance.db")
    estab = str(tmp_path / "receita_estab.db")

    cm = sqlite3.connect(main)
    cm.execute("CREATE TABLE favorecido_resumo (favorecido_cpf TEXT, favorecido_nome TEXT, "
               "total_pago REAL, n_obs INTEGER)")

    ce = sqlite3.connect(estab)
    ce.execute("CREATE TABLE estabelecimentos (cnpj TEXT PRIMARY KEY, endereco_norm TEXT, "
               "telefone1 TEXT, correio_eletronico TEXT, situacao_cadastral TEXT)")

    linhas: list[tuple] = []
    favor: list[tuple] = []

    # Grupo A — endereço-ninho: 8 CNPJs, 3 ATIVA / 5 BAIXADA, 4 recebem OB (R$2mi) → 'alto'.
    for i in range(8):
        c = _cnpj("10", i)
        sit = "ATIVA" if i < 3 else "BAIXADA"
        linhas.append((c, ENDERECO_NINHO, "", "", sit))
        if i < 4:
            favor.append((c, f"NINHO {i}", 500_000.0, 2))

    # Grupo pequeno S — 3 CNPJs no mesmo endereço: NÃO deve aparecer com min_cnpjs=5.
    for i in range(3):
        linhas.append((_cnpj("20", i), "RUA Y 5 X 30000000", "", "", "ATIVA"))

    # Grupo T — telefone de massa: 300 CNPJs, endereços distintos → contador/call-center → 'baixo'.
    for i in range(300):
        linhas.append((_cnpj("30", i), f"RUA T {i} BAIRRO 40000000", TELEFONE_MASSA, "", "ATIVA"))

    # Grupo E1 — e-mail de contabilidade: 6 CNPJs → guarda anti-FP → 'baixo'.
    for i in range(6):
        linhas.append((_cnpj("40", i), f"RUA E1 {i} 50000000", "", EMAIL_CONTABIL, "ATIVA"))

    # Grupo E2 — e-mail-ninho com materialidade: 5 CNPJs, 1 ATIVA / 4 BAIXADA, 3 recebem OB → 'alto'.
    for i in range(5):
        c = _cnpj("50", i)
        sit = "ATIVA" if i == 0 else "BAIXADA"
        linhas.append((c, f"RUA E2 {i} 60000000", "", EMAIL_NINHO, sit))
        if i < 3:
            favor.append((c, f"E2 {i}", 500_000.0, 1))

    ce.executemany("INSERT INTO estabelecimentos VALUES (?,?,?,?,?)", linhas)
    cm.executemany("INSERT INTO favorecido_resumo VALUES (?,?,?,?)", favor)
    ce.commit(); ce.close(); cm.commit(); cm.close()
    return main, estab


def test_endereco_ninho_alto(dbs):
    main, estab = dbs
    d = hub_compartilhado(chave="endereco", min_cnpjs=5, db_path=main, estab_path=estab)
    assert d["ok"] is True
    # só o grupo A qualifica (S tem 3<5; T/E têm endereços distintos)
    assert len(d["grupos"]) == 1
    g = d["grupos"][0]
    assert g["valor"] == ENDERECO_NINHO
    assert g["n_cnpjs"] == 8 and g["n_recebem_ob"] == 4
    assert g["n_ativos"] == 3
    assert g["total_recebido_ob"] == 2_000_000.0
    assert g["risco"] == "alto"
    assert len(g["cnpjs"]) == 8


def test_grupo_pequeno_nao_aparece(dbs):
    main, estab = dbs
    d = hub_compartilhado(chave="endereco", min_cnpjs=5, db_path=main, estab_path=estab)
    assert all(g["n_cnpjs"] >= 5 for g in d["grupos"])
    assert all(g["valor"] != "RUA Y 5 X 30000000" for g in d["grupos"])


def test_telefone_massa_e_baixo_contador(dbs):
    main, estab = dbs
    d = hub_compartilhado(chave="telefone", min_cnpjs=5, db_path=main, estab_path=estab)
    assert d["ok"] is True and len(d["grupos"]) == 1
    g = d["grupos"][0]
    assert g["valor"] == TELEFONE_MASSA and g["n_cnpjs"] == 300
    assert g["risco"] == "baixo"
    assert "contabilidade de massa" in g["motivo"] or "call-center" in g["motivo"]


def test_email_contabil_rebaixado_e_ninho_alto(dbs):
    main, estab = dbs
    d = hub_compartilhado(chave="email", min_cnpjs=5, db_path=main, estab_path=estab)
    assert d["ok"] is True
    por_valor = {g["valor"]: g for g in d["grupos"]}
    assert por_valor[EMAIL_CONTABIL]["risco"] == "baixo"      # guarda anti-FP contábil
    assert por_valor[EMAIL_NINHO]["risco"] == "alto"          # ninho real com OB
    assert por_valor[EMAIL_NINHO]["n_recebem_ob"] == 3


def test_chave_invalida(dbs):
    main, estab = dbs
    d = hub_compartilhado(chave="cpf", db_path=main, estab_path=estab)
    assert d["ok"] is False and "inválida" in d["erro"]


def test_estab_indisponivel_e_honesto(dbs):
    main, _ = dbs
    d = hub_compartilhado(chave="endereco", db_path=main, estab_path="/nao/existe/x.db")
    assert d["ok"] is False and "indispon" in d["erro"].lower()
