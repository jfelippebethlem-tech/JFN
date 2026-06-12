# -*- coding: utf-8 -*-
"""Testes da resolução de CPF mascarado (nome + 6 díg do meio → CPF completo), técnica br-acc.

Determinísticos: montam um SQLite temporário com `ordens_bancarias` (favorecido_cpf/nome) e exercem
o match 1:1, a guarda de ambiguidade, a normalização de acentos e o reconhecimento da máscara."""
import sqlite3

from compliance_agent.resolucao_cpf import middle6, resolver


def _db(tmp_path, linhas):
    p = tmp_path / "compliance.db"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE ordens_bancarias (favorecido_cpf TEXT, favorecido_nome TEXT)")
    con.executemany("INSERT INTO ordens_bancarias VALUES (?,?)", linhas)
    con.commit()
    con.close()
    return p


def test_middle6_extrai_so_da_mascara():
    assert middle6("***912137**") == "912137"
    assert middle6("***.912.137-**") == "912137"
    assert middle6("12345678901") == ""   # CPF limpo NÃO é máscara
    assert middle6("") == ""


def test_resolve_par_unico(tmp_path):
    # CPF 11122334455 → 6 do meio (pos 4-9) = 223344
    p = _db(tmp_path, [("11122334455", "JOAO DA SILVA"), ("99988877766", "OUTRO NOME")])
    out = resolver("JOAO DA SILVA", "***223344**", db_path=p)
    assert out["resolvido"] and out["cpf"] == "11122334455"
    assert out["confianca"] == 0.85


def test_acento_normalizado(tmp_path):
    p = _db(tmp_path, [("11122334455", "JOÃO DA SILVA")])  # base com acento
    out = resolver("joao da silva", "***223344**", db_path=p)  # consulta sem acento/minúscula
    assert out["resolvido"] and out["cpf"] == "11122334455"


def test_ambiguidade_nao_resolve(tmp_path):
    # mesmo nome + mesmo middle6 em 2 CPFs distintos → não resolve (honesto)
    p = _db(tmp_path, [("11122334455", "JOSE SANTOS"), ("88822334400", "JOSE SANTOS")])
    out = resolver("JOSE SANTOS", "***223344**", db_path=p)
    assert not out["resolvido"] and "ambíguo" in out["motivo"]


def test_sem_correspondencia(tmp_path):
    p = _db(tmp_path, [("11122334455", "JOAO DA SILVA")])
    out = resolver("MARIA SOUZA", "***223344**", db_path=p)
    assert not out["resolvido"] and "sem correspondência" in out["motivo"]


def test_doc_nao_mascarado_nao_resolve(tmp_path):
    p = _db(tmp_path, [("11122334455", "JOAO DA SILVA")])
    out = resolver("JOAO DA SILVA", "11122334455", db_path=p)  # sem '*' → não é máscara
    assert not out["resolvido"]


# ───────── cont.19: TSE como 2ª fonte (multi-fonte oficial) ─────────

def _db_multi(tmp_path, ob_linhas, tse_linhas):
    p = tmp_path / "compliance.db"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE ordens_bancarias (favorecido_cpf TEXT, favorecido_nome TEXT)")
    con.executemany("INSERT INTO ordens_bancarias VALUES (?,?)", ob_linhas)
    con.execute("CREATE TABLE doacoes_eleitorais (cpf_cnpj_doador TEXT, nome_doador TEXT)")
    con.executemany("INSERT INTO doacoes_eleitorais VALUES (?,?)", tse_linhas)
    con.commit()
    con.close()
    return p


def test_resolver_multi_cai_no_tse_quando_nao_ha_no_ob(tmp_path):
    from compliance_agent.resolucao_cpf import carregar_indice_tse, resolver_multi
    # nome NÃO está no OB; está no TSE com CPF cujo middle6 bate a máscara
    p = _db_multi(tmp_path, [("99999999999", "OUTRA PESSOA")],
                  [("11122334455", "JOÃO DA SILVA")])
    idx = carregar_indice_tse(db_path=p)
    out = resolver_multi("joao da silva", "***223344**", db_path=p, tse_idx=idx)
    assert out["resolvido"] and out["cpf"] == "11122334455" and out["fonte"] == "tse_doadores"


def test_resolver_multi_prefere_ob(tmp_path):
    from compliance_agent.resolucao_cpf import carregar_indice_tse, resolver_multi
    p = _db_multi(tmp_path, [("11122334455", "JOAO DA SILVA")],
                  [("11122334455", "JOAO DA SILVA")])
    idx = carregar_indice_tse(db_path=p)
    out = resolver_multi("JOAO DA SILVA", "***223344**", db_path=p, tse_idx=idx)
    assert out["resolvido"] and out["fonte"] == "favorecidos_pf"


def test_resolver_multi_tse_ambiguo_nao_resolve(tmp_path):
    from compliance_agent.resolucao_cpf import carregar_indice_tse, resolver_multi
    p = _db_multi(tmp_path, [("99999999999", "X")],
                  [("11122334455", "JOSE SANTOS"), ("88822334400", "JOSE SANTOS")])
    idx = carregar_indice_tse(db_path=p)
    out = resolver_multi("JOSE SANTOS", "***223344**", db_path=p, tse_idx=idx)
    assert not out["resolvido"] and "ambíguo" in out["motivo"]


def test_resolver_multi_cai_no_sei_quando_nao_ha_ob_nem_tse(tmp_path):
    from compliance_agent.resolucao_cpf import carregar_indice_sei, resolver_multi
    import sqlite3
    p = tmp_path / "compliance.db"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE ordens_bancarias (favorecido_cpf TEXT, favorecido_nome TEXT)")
    con.execute("CREATE TABLE sei_cpf (nome_norm TEXT, cpf TEXT)")
    con.execute("INSERT INTO sei_cpf VALUES ('JOAO DA SILVA','11122334455')")
    con.commit(); con.close()
    sei = carregar_indice_sei(db_path=p)
    out = resolver_multi("joao da silva", "***223344**", db_path=p, sei_idx=sei)
    assert out["resolvido"] and out["cpf"] == "11122334455" and out["fonte"] == "sei_docs"
