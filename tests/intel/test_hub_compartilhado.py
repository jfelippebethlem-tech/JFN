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
ENDERECO_GOVERNO = "AV PRES ANTONIO CARLOS 375 CENTRO 20020010"
ENDERECO_MATRIZ = "RUA MATRIZ 1 CENTRO 70000000"
ENDERECO_TORRE = "AV PRESIDENTE VARGAS 2655 CIDADE NOVA 20210030"
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
    ce.execute("CREATE TABLE estabelecimentos (cnpj TEXT PRIMARY KEY, cnpj_basico TEXT, "
               "cnae_principal TEXT, endereco_norm TEXT, "
               "telefone1 TEXT, correio_eletronico TEXT, situacao_cadastral TEXT)")

    linhas: list[tuple] = []
    favor: list[tuple] = []

    def _linha(c, end, tel, email, sit, raiz=None, cnae="4711301"):
        # raiz default = DISTINTA por CNPJ (ninho real junta raízes diferentes)
        linhas.append((c, raiz or c[:4] + c[-4:], cnae, end, tel, email, sit))

    # Grupo A — endereço-ninho: 8 CNPJs, 3 ATIVA / 5 BAIXADA, 4 recebem OB (R$2mi) → 'alto'.
    for i in range(8):
        c = _cnpj("10", i)
        sit = "ATIVA" if i < 3 else "BAIXADA"
        _linha(c, ENDERECO_NINHO, "", "", sit)
        if i < 4:
            favor.append((c, f"NINHO {i}", 500_000.0, 2))

    # Grupo pequeno S — 3 CNPJs no mesmo endereço: NÃO deve aparecer com min_cnpjs=5.
    for i in range(3):
        _linha(_cnpj("20", i), "RUA Y 5 X 30000000", "", "", "ATIVA")

    # Grupo T — telefone de massa: 300 CNPJs, endereços distintos → contador/call-center → 'baixo'.
    for i in range(300):
        _linha(_cnpj("30", i), f"RUA T {i} BAIRRO 40000000", TELEFONE_MASSA, "", "ATIVA")

    # Grupo E1 — e-mail de contabilidade: 6 CNPJs → guarda anti-FP → 'baixo'.
    for i in range(6):
        _linha(_cnpj("40", i), f"RUA E1 {i} 50000000", "", EMAIL_CONTABIL, "ATIVA")

    # Grupo E2 — e-mail-ninho com materialidade: 5 CNPJs, 1 ATIVA / 4 BAIXADA, 3 recebem OB → 'alto'.
    for i in range(5):
        c = _cnpj("50", i)
        sit = "ATIVA" if i == 0 else "BAIXADA"
        _linha(c, f"RUA E2 {i} 60000000", "", EMAIL_NINHO, sit)
        if i < 3:
            favor.append((c, f"E2 {i}", 500_000.0, 1))

    # Grupo P — prédio de GOVERNO: 6 CNPJs, 2 da adm pública (CNAE 84), OB bilionária → 'info'.
    for i in range(6):
        c = _cnpj("60", i)
        _linha(c, ENDERECO_GOVERNO, "", "", "ATIVA",
               cnae="8411600" if i < 2 else "4711301")
        if i < 3:
            favor.append((c, f"ORGAO {i}", 2_000_000_000.0, 9))

    # Grupo F — FILIAIS de uma raiz só (banco/estatal): 7 CNPJs, mesma raiz, 2 recebem OB → 'info'.
    for i in range(7):
        c = _cnpj("70", i)
        _linha(c, ENDERECO_MATRIZ, "", "", "ATIVA", raiz="70000000")
        if i < 2:
            favor.append((c, f"FILIAL {i}", 800_000.0, 3))

    # Grupo X — TORRE COMERCIAL: 6 CNPJs de 6 setores CNAE distintos, 3 recebem OB → 'medio'.
    cnaes_torre = ["7319002", "4399103", "3600601", "5611203", "3314719", "5620104"]
    for i in range(6):
        c = _cnpj("80", i)
        _linha(c, ENDERECO_TORRE, "", "", "ATIVA", cnae=cnaes_torre[i])
        if i < 3:
            favor.append((c, f"TORRE {i}", 600_000_000.0, 4))

    ce.executemany("INSERT INTO estabelecimentos VALUES (?,?,?,?,?,?,?)", linhas)
    cm.executemany("INSERT INTO favorecido_resumo VALUES (?,?,?,?)", favor)
    ce.commit(); ce.close(); cm.commit(); cm.close()
    return main, estab


def test_endereco_ninho_alto(dbs):
    main, estab = dbs
    d = hub_compartilhado(chave="endereco", min_cnpjs=5, db_path=main, estab_path=estab)
    assert d["ok"] is True
    g = {x["valor"]: x for x in d["grupos"]}[ENDERECO_NINHO]
    assert g["n_cnpjs"] == 8 and g["n_recebem_ob"] == 4
    assert g["n_ativos"] == 3
    assert g["total_recebido_ob"] == 2_000_000.0
    assert g["risco"] == "alto"
    assert len(g["cnpjs"]) == 8


def test_ente_publico_e_info(dbs):
    """Prédio de governo (CNAE 84 no grupo) NUNCA vira ninho — mesmo com OB bilionária."""
    main, estab = dbs
    d = hub_compartilhado(chave="endereco", min_cnpjs=5, db_path=main, estab_path=estab)
    g = {x["valor"]: x for x in d["grupos"]}[ENDERECO_GOVERNO]
    assert g["risco"] == "info"
    assert g["n_publicos"] == 2
    assert "administração pública" in g["motivo"]


def test_torre_comercial_setores_diversos_e_medio(dbs):
    """Setores CNAE diversos = inquilinos de prédio comercial, não lote de fachadas → 'medio'."""
    main, estab = dbs
    d = hub_compartilhado(chave="endereco", min_cnpjs=5, db_path=main, estab_path=estab)
    g = {x["valor"]: x for x in d["grupos"]}[ENDERECO_TORRE]
    assert g["risco"] == "medio"
    assert g["n_setores"] == 5      # 56xx aparece 2× (lanchonete+catering) → 5 setores
    assert "multi-inquilino" in g["motivo"]


def test_filiais_mesma_raiz_e_info(dbs):
    """Matriz+filiais de UMA raiz de CNPJ (banco/estatal/rede) não é ninho de fachadas."""
    main, estab = dbs
    d = hub_compartilhado(chave="endereco", min_cnpjs=5, db_path=main, estab_path=estab)
    g = {x["valor"]: x for x in d["grupos"]}[ENDERECO_MATRIZ]
    assert g["risco"] == "info"
    assert g["n_raizes"] == 1
    assert "filiais" in g["motivo"].lower()


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
