import json
import sqlite3

from tools import sei_busca_credor as B


def _base():
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE contratos_tcerj (processo TEXT, cnpj TEXT, unidade TEXT)")
    c.execute("CREATE TABLE ob_orcamentaria_siafe (ug_emitente TEXT, processo TEXT)")
    c.execute("INSERT INTO contratos_tcerj VALUES ('SEI-330005/000022/2026','1','ITERJ - INSTIT DE TERRAS')")
    c.execute("INSERT INTO contratos_tcerj VALUES ('SEI-999999/000001/2026','1','XYZ - ORGAO INEXISTENTE')")
    for _ in range(3):
        c.execute("INSERT INTO ob_orcamentaria_siafe VALUES ('133100','SEI-330005/000022/2026')")
        c.execute("INSERT INTO ob_orcamentaria_siafe VALUES ('999100','SEI-999999/000001/2026')")
    return c


def test_sigla_so_vale_se_existe_na_lista_do_sei(tmp_path, monkeypatch):
    arq = tmp_path / "orgaos.json"
    arq.write_text(json.dumps({"orgaos": ["ITERJ", "SEFAZ"]}))
    monkeypatch.setattr(B, "ORGAOS_SEI", arq)
    assert B.siglas_por_ug(_base()) == {"133100": "ITERJ"}          # XYZ não existe no SEI: fora


def test_sem_lista_de_orgaos_nao_inventa_sigla(tmp_path, monkeypatch):
    monkeypatch.setattr(B, "ORGAOS_SEI", tmp_path / "nao_existe.json")
    assert B.siglas_por_ug(_base()) == {}


def test_filtrar_so_pagamento_de_unidade_que_a_ug_usa():
    todos = {"330005/000008/2024": "Financeiro: Pagamento", "330005/000009/2024": "Contratação: Aditivo",
             "080001/042896/2025": "Financeiro: Pagamento de Despesas de Serviços Contratados"}
    assert B.filtrar(todos, {"330005"}) == ["SEI-330005/000008/2024"]


def test_prefixo_precisa_de_3_obs_para_ser_aprendido():
    c = _base()
    c.execute("INSERT INTO ob_orcamentaria_siafe VALUES ('133100','SEI-777777/000001/2026')")   # 1 só: ruído
    assert B.prefixos_por_ug(c)["133100"] == {"330005"}


def test_sigla_tce_vira_opcao_do_sei():
    v = {"DER", "DETRO", "EMATER", "DEGASE", "FS", "SEDEC", "RIOPREV", "ITERJ", "PESAGRO"}
    assert B.sigla_sei("DER-RJ", v) == "DER" and B.sigla_sei("DETRO-RJ", v) == "DETRO"
    assert B.sigla_sei("EMATER-RIO", v) == "EMATER" and B.sigla_sei("PESAGRO-RIO", v) == "PESAGRO"
    assert B.sigla_sei("NOVO DEGASE", v) == "DEGASE" and B.sigla_sei("FSERJ", v) == "FS"
    assert B.sigla_sei("FUNESBOM", v) == "SEDEC" and B.sigla_sei("RIOPREVIDÊNCIA", v) == "RIOPREV"
    assert B.sigla_sei("ITERJ", v) == "ITERJ" and B.sigla_sei("FDRM-RJ", v) == ""
