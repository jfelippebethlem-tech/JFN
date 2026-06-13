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


def test_confirmar_cpf_anti_homonimo():
    from compliance_agent.resolucao_cpf import confirmar_cpf
    # QSA mascarado ***223344** => middle6 esperado 223344 (CPF posições 4-9)
    ok = confirmar_cpf("JOAO DA SILVA", "11122334455", "***223344**")  # 112-223-344-55 -> meio 223344
    assert ok["confirmado"] and ok["cpf"] == "11122334455"
    # candidato com OUTRO middle6 = homônimo -> rejeita
    homo = confirmar_cpf("JOAO DA SILVA", "11199988877", "***223344**")
    assert not homo["confirmado"] and "HOMÔNIMO" in homo["motivo"]
    # CPF inválido (tamanho)
    assert not confirmar_cpf("X", "123", "***223344**")["confirmado"]


def test_gerar_cpfs_da_mascara():
    from compliance_agent.resolucao_cpf import gerar_cpfs_da_mascara
    from compliance_agent.sei.extrair_cpf import validar_cpf
    cands = gerar_cpfs_da_mascara("***512815**")
    assert len(cands) == 1000 and all(validar_cpf(c) for c in cands)
    assert all(c[3:9] == "512815" for c in cands)
    assert "94451281504" in cands  # CPF real cai entre os candidatos
    assert gerar_cpfs_da_mascara("11122334455") == []  # sem máscara


# ───────────────────────── fusão de máscaras folha×QSA (tier B) ─────────────────────────
def test_folha_middle():
    from compliance_agent.resolucao_cpf import folha_middle
    assert folha_middle("XX223344XXX") == "223344"   # folha mascara pos 1-2 e 9-11 → mostra 3-8
    assert folha_middle("11122334455") == ""          # CPF limpo não é máscara da folha
    assert folha_middle("") == ""


def _db_fusao(tmp_path):
    p = tmp_path / "compliance.db"
    con = sqlite3.connect(p)
    con.executescript("""
        CREATE TABLE registros_folha (nome TEXT, cpf TEXT);
        CREATE TABLE socios_fornecedor (cnpj TEXT, socio_nome TEXT, socio_doc TEXT,
                                        socio_servidor INTEGER, cpf_pos3a9 TEXT);
    """)
    # CPF real 11122334455: QSA mostra pos4-9=223344; folha mostra pos3-8=122334
    con.execute("INSERT INTO registros_folha VALUES('JOAO DA SILVA','XX122334XXX')")
    con.execute("INSERT INTO registros_folha VALUES('MARIA SOUZA','XX999888XXX')")  # nome bate, dígito não
    con.commit(); con.close()
    return p


def test_fusao_folha_qsa_servidor_consistente(tmp_path):
    from compliance_agent.resolucao_cpf import carregar_indice_folha, fusao_folha_qsa
    idx = carregar_indice_folha(_db_fusao(tmp_path))
    r = fusao_folha_qsa("JOAO DA SILVA", "***223344**", idx)
    assert r["servidor"] is True
    assert r["conhecidos_3a9"] == "1223344"   # pos3 (folha) + pos4-9 (QSA)
    assert r["n_candidatos"] == 100


def test_fusao_folha_qsa_homonimo_rejeita(tmp_path):
    from compliance_agent.resolucao_cpf import carregar_indice_folha, fusao_folha_qsa
    idx = carregar_indice_folha(_db_fusao(tmp_path))
    # nome bate (MARIA SOUZA) mas dígitos do CPF divergem → não afirma servidor
    r = fusao_folha_qsa("MARIA SOUZA", "***223344**", idx)
    assert r["servidor"] is False and "homônimo" in r["motivo"].lower()
    # nome ausente na folha
    assert fusao_folha_qsa("FULANO INEXISTENTE", "***223344**", idx)["servidor"] is False


def test_socios_servidores_accessor(tmp_path):
    from compliance_agent.resolucao_cpf import socios_servidores
    p = _db_fusao(tmp_path)
    con = sqlite3.connect(p)
    con.execute("UPDATE socios_fornecedor SET cnpj='11111111000111'")  # no-op (vazio)
    con.execute("INSERT INTO socios_fornecedor VALUES('11111111000111','JOAO DA SILVA','***223344**',1,'1223344')")
    con.commit(); con.close()
    out = socios_servidores("11111111000111", db_path=p)
    assert len(out) == 1 and out[0]["nome"] == "JOAO DA SILVA" and out[0]["cpf_pos3a9"] == "1223344"
    assert socios_servidores("99999999000199", db_path=p) == []


def test_dd_hipotese_socio_servidor(tmp_path, monkeypatch):
    from compliance_agent import investigacao_dd as dd
    monkeypatch.setattr("compliance_agent.resolucao_cpf.socios_servidores",
                        lambda cnpj, db_path=None: [{"nome": "JOAO DA SILVA", "cpf_pos3a9": "1223344"}])
    out = dd.investigar("11111111000111", cadastral={}, pagamentos={"total_pago": 2_000_000})
    h = [x for x in out["hipoteses"] if x["codigo"] == "H-SOCIO-SERVIDOR"]
    assert h and h[0]["status"] == "INDICIO" and h[0]["nivel"] == "ALTO"
