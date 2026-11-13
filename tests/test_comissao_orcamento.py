import json
import sqlite3

import pytest

from compliance_agent import comissao_orcamento as C


@pytest.fixture
def bases(tmp_path, monkeypatch):
    db, ach, ab = tmp_path / "c.db", tmp_path / "a.db", tmp_path / "d.db"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE pericia_fornecedor (cnpj, ug, favorecido, grau, score, total_pago, n_obs, achados_json)")
    t07 = json.dumps([{"codigo": "T07-DUPLICIDADE-COMP", "status": "INDICIO", "titulo": "dup", "evidencia": "2x"},
                      {"codigo": "T01-3WAY", "status": "AFASTADO"}])
    c.executemany("INSERT INTO pericia_fornecedor VALUES (?,?,?,?,?,?,?,?)", [
        ("111", "030100", "ACME", "🟡", 25, 1000.0, 3, t07),       # TJRJ
        ("222", "044100", "OBRAS", "🟢", 0, 500.0, 2, "[]"),        # DER: UG 04…, órgão 53
        ("333", "044100", "PONTE", "🟡", 25, 9000.0, 4, t07)])
    c.execute("CREATE TABLE resolucao_duplicidade (cnpj, ug, veredito)")
    c.executemany("INSERT INTO resolucao_duplicidade VALUES (?,?,?)", [("111", "030100", "AFASTADO"),
                                                                        ("111", "030100", "PENDENTE_CAPTURA")])
    c.commit()
    a = sqlite3.connect(ach)
    a.execute("CREATE TABLE achado_detector (ug, processo, detector, score, motivo, status)")
    a.execute("INSERT INTO achado_detector VALUES ('030100','999','C8',70,'sócio servidor','confirmado')")
    a.commit()
    d = sqlite3.connect(ab)
    d.execute("CREATE TABLE da_despesa (ug, orgao, nome_orgao, posicao, valor_empenhado)")
    d.executemany("INSERT INTO da_despesa VALUES (?,?,?,?,?)", [
        ("030100", "03", "Tribunal de Justiça", "12/2024", 10.0), ("044100", "53", "Secretaria de Infraestrutura",
                                                                    "12/2024", 10.0),
        ("044100", "04", "Vice-Governadoria", "12/2024", 1.0)])           # descentralização: fatia menor
    d.commit()
    for x in (c, a, d):
        x.close()
    monkeypatch.setattr(C, "DB", db)
    monkeypatch.setattr(C, "DB_ACHADOS", ach)
    monkeypatch.setattr(C, "DB_ABERTOS", ab)
    C._CACHE.clear()
    return C


def test_orgao_pelo_dono_da_ug_e_instituicoes_primeiro(bases):
    r = bases.montar()
    org = {d["orgao"]: d for d in r["orgaos"]}
    assert r["orgaos"][0]["orgao"] == "03" and org["03"]["nome"] == "TJRJ"
    assert "53" in org and "04" not in org                    # DER no órgão dono, não no prefixo da UG
    assert org["53"]["nome"] == "Secretaria de Infraestrutura" and org["53"]["n_problemas"] == 1


def test_problema_traz_indicio_duplicidade_e_detector(bases):
    tj = next(d for d in bases.montar()["orgaos"] if d["orgao"] == "03")
    acme = next(p for p in tj["problemas"] if p["cnpj"] == "111")
    assert [a["codigo"] for a in acme["achados"]] == ["T07-DUPLICIDADE-COMP"]      # AFASTADO não é problema
    assert acme["duplicidade"] == {"AFASTADO": 1, "PENDENTE_CAPTURA": 1}
    assert any(p["cnpj"] == "999" and p["achados"][0]["codigo"] == "C8" for p in tj["problemas"])
    assert tj["valor_com_problema"] == 1000.0


def test_detector_indicio_fraco_nao_vira_vermelho_e_ganha_nome(bases, tmp_path):
    a = sqlite3.connect(bases.DB_ACHADOS)
    a.execute("INSERT INTO achado_detector VALUES ('030100','777','C2',30,'H-CAPITAL (INDICIO/MEDIO) → C2 âncora fraco','confirmado')")
    a.execute("INSERT INTO achado_detector VALUES ('030100','888','C3/C5','90','H-SITUACAO (CONFIRMADO/ALTO) → C3/C5 âncora forte','confirmado')")
    a.commit(); a.close()
    bases._CACHE.clear()
    tj = next(d for d in bases.montar()["orgaos"] if d["orgao"] == "03")
    p777 = next(p for p in tj["problemas"] if p["cnpj"] == "777")
    p888 = next(p for p in tj["problemas"] if p["cnpj"] == "888")
    assert p777["grau"] == "🟡" and p777["achados"][0]["status"] == "INDICIO"
    assert "capital ínfimo" in p777["achados"][0]["titulo"]
    assert p888["grau"] == "🔴" and p888["achados"][0]["status"] == "CONFIRMADO"


def test_cpf_de_pessoa_fisica_sai_mascarado_e_grau_da_linha_e_o_maior(bases):
    c = sqlite3.connect(bases.DB)
    c.execute("INSERT INTO pericia_fornecedor VALUES ('08765593723','030100','FULANO','🟡',25,10.0,1,'[]')")
    c.commit(); c.close()
    a = sqlite3.connect(bases.DB_ACHADOS)
    a.execute("INSERT INTO achado_detector VALUES ('030100','111','C3/C5',90,'H-SITUACAO (CONFIRMADO/ALTO) → x','confirmado')")
    a.commit(); a.close()
    bases._CACHE.clear()
    tj = next(d for d in bases.montar()["orgaos"] if d["orgao"] == "03")
    pf = next(p for p in tj["problemas"] if p["fornecedor"] == "FULANO")
    assert pf["tipo_doc"] == "CPF" and "***" in pf["cnpj"] and "08765593723" not in json.dumps(tj)
    acme = next(p for p in tj["problemas"] if p["fornecedor"] == "ACME")
    assert acme["grau"] == "🔴"                       # perícia 🟡 + detector CONFIRMADO
