# -*- coding: utf-8 -*-
"""Contrato de ingestão (O4.11): `config/fontes_cobertura.yaml` validado, cobrindo as fontes da propagação, e a
migração 0003 que cria `ingestao_lote`/`ingestao_quarentena` (cabeça única, DDL igual ao do módulo)."""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import pytest
from pydantic import ValidationError

from compliance_agent.ingestao import contrato as ct
from compliance_agent.ingestao import quarentena as qt

RAIZ = Path(__file__).resolve().parent.parent
MIGRACAO = RAIZ / "compliance_agent/database/alembic/versions/0003_ingestao_quarentena.py"


def _externa(**kw):
    base = {"nome": "x", "natureza": "externa", "dono": "frente x", "coletor": "m", "frequencia": "diaria",
            "tabela": "t", "coluna_frescor": "coletado_em", "slo_frescor_h": 24, "chave_natural": ["id"],
            "campos": {"id": {"tipo": "texto", "obrigatorio": True}}}
    base.update(kw)
    return base


# ── o arquivo real ────────────────────────────────────────────────────────────────────────────────

def test_contrato_real_valida_e_cobre_toda_a_propagacao():
    c = ct.carregar()
    cob = ct.conferir_propagacao(c, ct.fontes_da_propagacao())
    assert cob == {"faltam": [], "inexistentes": []}, cob
    assert len(ct.fontes_da_propagacao()) >= 36


def test_contrato_real_declara_as_coletas_paradas_com_motivo():
    f = ct.carregar().fontes
    for fid in ("compras_diretas_tcerj", "tcerj_licitante", "tfe_ob", "tfe_despesa_ckan", "doerj", "siafe_ne"):
        assert f[fid].estado != "ATIVA" and f[fid].motivo_estado, fid
    assert f["tfe_ob"].estado == "INDISPONIVEL"          # recusa de datacenter não é "atrasado"
    assert f["noticias_orgaos"].efemera is True
    assert f["siafe_ob"].efemera is False


def test_contrato_sem_topologia_sensivel():
    texto = (RAIZ / "config" / "fontes_cobertura.yaml").read_text(encoding="utf-8")
    assert not re.search(r"\b\d{1,3}(\.\d{1,3}){3}\b", texto), "IP no contrato"
    for proibido in (".ts.net", "tailscale", "vm2-ts", "senha", "password", "token", "/home/"):
        assert proibido not in texto.lower(), proibido


# ── regras do esquema ─────────────────────────────────────────────────────────────────────────────

def test_externa_exige_chave_tabela_frescor_e_slo():
    for faltando in ("chave_natural", "tabela", "coluna_frescor", "slo_frescor_h"):
        d = _externa()
        d[faltando] = [] if faltando == "chave_natural" else None
        with pytest.raises(ValidationError):
            ct.Fonte.model_validate(d)


def test_interna_nao_exige_chave():
    ct.Fonte.model_validate({"nome": "regra", "natureza": "interna", "dono": "x", "coletor": "git",
                             "frequencia": "evento"})


def test_estado_nao_ativo_sem_motivo_e_recusado():
    with pytest.raises(ValidationError, match="motivo_estado"):
        ct.Fonte.model_validate(_externa(estado="PARADA"))


def test_chave_fora_dos_campos_e_recusada():
    with pytest.raises(ValidationError, match="chave_natural"):
        ct.Fonte.model_validate(_externa(chave_natural=["id", "ug"]))


@pytest.mark.parametrize("campo,valor", [("tabela", "t; DROP TABLE x"), ("coluna_frescor", 'a"b'),
                                         ("chave_natural", ["id OR 1=1"])])
def test_identificador_sql_injetavel_e_recusado(campo, valor):
    with pytest.raises(ValidationError):
        ct.Fonte.model_validate(_externa(**{campo: valor}))


def test_regex_invalida_e_faixa_invertida_sao_recusadas():
    with pytest.raises(ValidationError):
        ct.Campo.model_validate({"regex": "(["})
    with pytest.raises(ValidationError, match="faixa"):
        ct.Campo.model_validate({"tipo": "real", "minimo": 10, "maximo": 1})


# ── validação de registro ─────────────────────────────────────────────────────────────────────────

def _fonte_ob():
    return ct.Fonte.model_validate(_externa(chave_natural=["numero_ob", "ug", "exercicio"], campos={
        "numero_ob": {"tipo": "texto", "obrigatorio": True, "regex": r"\d{4}OB\d{5}"},
        "ug": {"tipo": "ug", "obrigatorio": True},
        "exercicio": {"tipo": "ano", "obrigatorio": True, "minimo": 2016, "maximo": 2027},
        "data_emissao": {"tipo": "data_br", "obrigatorio": True},
        "status": {"tipo": "texto", "dominio": ["Contabilizado", "Anulado"]},
        "valor": {"tipo": "real", "minimo": 0},
        "credor": {"tipo": "cpf_cnpj"}}))


_OK = {"numero_ob": "2025OB24997", "ug": "036100", "exercicio": 2025, "data_emissao": "10/12/2025",
       "status": "Contabilizado", "valor": 66920.0, "credor": "55935697000184"}


def test_registro_valido_nao_tem_motivo():
    assert ct.validar_registro(_fonte_ob(), _OK) == []


@pytest.mark.parametrize("campo,valor,trecho", [
    ("data_emissao", "31/02/2025", "não é data real"),
    ("data_emissao", "2025-12-10", "formato data_br"),
    ("numero_ob", "2025PD02779", "não casa"),          # coluna deslocada medida no snapshot (status_envio)
    ("status", "2017PD02779", "fora do domínio"),
    ("valor", -1, "abaixo do mínimo"),
    ("exercicio", 2031, "acima do máximo"),
    ("credor", "1234", "formato cpf_cnpj"),
    ("ug", None, "obrigatório ausente"),
])
def test_registro_invalido_diz_o_motivo(campo, valor, trecho):
    motivos = ct.validar_registro(_fonte_ob(), {**_OK, campo: valor})
    assert len(motivos) == 1 and trecho in motivos[0], motivos


def test_campo_extra_vira_extensao_nao_rejeicao():
    reg = {**_OK, "coluna_nova": 1}
    assert ct.validar_registro(_fonte_ob(), reg) == []
    assert ct.extensoes(_fonte_ob(), reg) == {"coluna_nova"}


# ── migração 0003 ─────────────────────────────────────────────────────────────────────────────────

def _ddl_da_migracao() -> str:
    texto = MIGRACAO.read_text(encoding="utf-8")
    return texto.split('DDL = """', 1)[1].split('"""', 1)[0]


def test_ddl_da_migracao_igual_ao_do_modulo():
    assert _ddl_da_migracao() == qt.DDL


def test_cabeca_unica_e_0003_no_topo():
    from alembic.script import ScriptDirectory

    from compliance_agent.database.migrar import _config
    heads = ScriptDirectory.from_config(_config()).get_heads()
    assert heads == ["0003_ingestao_quarentena"], heads


def test_upgrade_em_banco_vazio_cria_as_tabelas(tmp_path):
    from compliance_agent.database import migrar
    db = tmp_path / "novo.db"
    sqlite3.connect(db).close()
    r = migrar.atualizar(db)
    assert r["ok"] and r["atual"] == "0003_ingestao_quarentena"
    con = sqlite3.connect(db)
    try:
        nomes = {x[0] for x in con.execute("SELECT name FROM sqlite_master WHERE name LIKE 'ingestao_%'")}
    finally:
        con.close()
    assert {"ingestao_lote", "ingestao_quarentena"} <= nomes
