# -*- coding: utf-8 -*-
"""Homônimos desfeitos por OUTRO DADO nos cruzamentos que casavam só pelo nome (2ª rodada, 19/11/2026).

Pedido do dono: "homônimos em tudo têm que ser desmistificados através de outros dados". Base sintética:
  · sócio oculto — o mesmo nome com CPF diferente é OUTRA pessoa (não soma empresas); sem documento no QSA
    é INDETERMINADO e fica fora de `achados`;
  · nepotismo — sobrenome igual é HIPÓTESE; vira INDÍCIO só quando as pessoas são sócias da mesma empresa
    com a identidade de cada uma conferida pelo CPF da folha (homônimo de CPF diferente não corrobora);
  · nepotismo cruzado — o "parente colocado" que é a própria autoridade (mesmo nome, mesmo CPF) é descartado;
  · grafo de famílias — comissionado e sócio de mesmo nome só viram um nó com CPF compatível.
"""
from __future__ import annotations

import sqlite3

import pytest

from compliance_agent import cruzamentos_intel as C
from compliance_agent import identidade_pessoa as ip


# ─────────────────── régua: helpers novos ─────────────────────────────────────────────────────

def test_chave_qsa_pessoa_e_nome_mais_documento():
    assert ip.chave_qsa("José da Silva", "***123456**") == ("JOSE DA SILVA", "pf:123456")
    assert ip.chave_qsa("JOSE DA SILVA", "00012345678") == ("JOSE DA SILVA", "pf:123456")   # CPF completo = mesma chave
    assert ip.chave_qsa("JOSE DA SILVA", "***654321**") != ip.chave_qsa("JOSE DA SILVA", "***123456**")
    assert ip.chave_qsa("HOLDING X LTDA", "40218781000100") == ip.chave_qsa("HOLDING X LTDA", "40218781")
    assert ip.chave_qsa("JOSE DA SILVA", "") == ("JOSE DA SILVA", "")


def test_mesma_pessoa_folhas_positivo_e_negativos():
    mesma = ip.mesma_pessoa_folhas("ANA LUZ", "XX123456XXX", "gesperj_estado", "2026-06",
                                   "ANA LUZ", "XX123456XXX", "gesperj_estado", "2026-08")
    assert mesma["resultado"] == "MESMA"
    hom = ip.mesma_pessoa_folhas("ANA LUZ", "XX123456XXX", "gesperj_estado", None,
                                 "ANA LUZ", "XX654321XXX", "gesperj_estado", None)
    assert hom["resultado"] == "DISTINTAS"
    sem = ip.mesma_pessoa_folhas("ANA LUZ", "", "tjrj_anexo8", None, "ANA LUZ", "XX123456XXX", "gesperj_estado", None)
    assert sem["resultado"] == ip.INDETERMINADO and "TJRJ" in sem["motivo"]
    assert ip.mesma_pessoa_folhas("ANA LUZ", "", None, None, "RUI LUZ", "", None, None)["resultado"] == "DISTINTAS"


def test_selo_parentesco_so_sobrenome_e_hipotese():
    h = ip.selo_parentesco([])
    assert h["selo"] == ip.HIPOTESE and h["exculpatoria"] and "não é parentesco" in h["motivo"]
    i = ip.selo_parentesco(["A e B são sócios da mesma empresa"])
    assert i["selo"] == ip.INDICIO and i["grau"] == "indicio"


# ─────────────────── base sintética ───────────────────────────────────────────────────────────

@pytest.fixture()
def base(tmp_path):
    p = tmp_path / "c.db"
    con = sqlite3.connect(p)
    con.executescript("""
    CREATE TABLE registros_folha (id INTEGER PRIMARY KEY, cpf TEXT, nome TEXT, orgao_nome TEXT, cargo TEXT,
        vinculo TEXT, competencia TEXT, fonte TEXT, matricula TEXT);
    CREATE TABLE socios_fornecedor (cnpj TEXT, razao TEXT, socio_nome TEXT, socio_nome_norm TEXT, socio_doc TEXT,
        qualificacao TEXT, cpf_resolvido TEXT);
    CREATE TABLE favorecido_resumo (favorecido_cpf TEXT PRIMARY KEY, favorecido_nome TEXT, n_obs INTEGER, total_pago REAL);
    CREATE TABLE socios_receita (cnpj_basico TEXT, nome_socio TEXT, nome_norm TEXT, doc_socio TEXT);
    CREATE TABLE socios_reverso (doc_socio TEXT, nome_socio TEXT, nome_norm TEXT, cnpj_basico TEXT);
    """)
    folha = [
        # nepotismo: KLOTZ BRANDT — irmãos sócios da mesma empresa (CPF confere) → INDÍCIO
        ("XX111111XXX", "ANA KLOTZ BRANDT", "SECRETARIA X", "ASSESSOR ESPECIAL", "2026-06", "gesperj_estado"),
        ("XX222222XXX", "RUI KLOTZ BRANDT", "SECRETARIA X", "ASSESSOR", "2026-06", "gesperj_estado"),
        # nepotismo: VARGO TENREIRO — só sobrenome (o sócio de mesmo nome tem OUTRO CPF) → HIPÓTESE
        ("XX333333XXX", "LIA VARGO TENREIRO", "SECRETARIA Y", "ASSESSOR", "2026-06", "gesperj_estado"),
        ("XX444444XXX", "IVO VARGO TENREIRO", "SECRETARIA Y", "ASSESSOR", "2026-06", "gesperj_estado"),
        # nepotismo cruzado: a "colocada" no órgão B é a própria autoridade de A (mesmo CPF) → descartado
        ("XX555555XXX", "BIA POUSO MERLIN", "ORGAO A", "SECRETARIO", "2026-06", "gesperj_estado"),
        ("XX555555XXX", "BIA POUSO MERLIN", "ORGAO B", "ASSESSOR", "2026-08", "gesperj_estado"),
        ("XX666666XXX", "TEO ZANIN ORLEY", "ORGAO B", "SECRETARIO", "2026-06", "gesperj_estado"),
        ("XX666666XXX", "TEO ZANIN ORLEY", "ORGAO A", "ASSESSOR", "2026-08", "gesperj_estado"),
    ]
    con.executemany("INSERT INTO registros_folha (cpf,nome,orgao_nome,cargo,competencia,fonte) VALUES (?,?,?,?,?,?)", folha)
    socios = [
        # sócio oculto: JOSE QUINTAL — 3 empresas, mas uma é de um homônimo de CPF diferente → não soma 3
        ("11111111000101", "EMP A", "JOSE QUINTAL", "***101010**"), ("22222222000101", "EMP B", "JOSE QUINTAL", "***101010**"),
        ("33333333000101", "EMP C", "JOSE QUINTAL", "***909090**"),
        # sócio oculto verdadeiro: mesmo nome e documento em 3 empresas
        ("11111111000101", "EMP A", "MARA SOLTO", "***202020**"), ("22222222000101", "EMP B", "MARA SOLTO", "***202020**"),
        ("33333333000101", "EMP C", "MARA SOLTO", "***202020**"),
        # sem documento: INDETERMINADO
        ("11111111000101", "EMP A", "SEM DOC NUNES", ""), ("22222222000101", "EMP B", "SEM DOC NUNES", ""),
        ("33333333000101", "EMP C", "SEM DOC NUNES", ""),
        # grafo de famílias: comissionado LIA VARGO TENREIRO tem homônimo sócio de CPF diferente
        ("44444444000101", "EMP D", "LIA VARGO TENREIRO", "***999999**"),
    ]
    con.executemany("INSERT INTO socios_fornecedor (cnpj,razao,socio_nome,socio_nome_norm,socio_doc,qualificacao) "
                    "VALUES (?,?,?,?,?,'Sócio-Administrador')", [(c, r, n, n, d) for c, r, n, d in socios])
    con.executemany("INSERT INTO favorecido_resumo VALUES (?,?,1,?)",
                    [("11111111000101", "EMP A", 1e6), ("22222222000101", "EMP B", 2e6),
                     ("33333333000101", "EMP C", 3e6), ("44444444000101", "EMP D", 4e6)])
    con.executemany("INSERT INTO socios_receita VALUES (?,?,?,?)", [
        ("77777777", "ANA KLOTZ BRANDT", "ANA KLOTZ BRANDT", "***111111**"),
        ("77777777", "RUI KLOTZ BRANDT", "RUI KLOTZ BRANDT", "***222222**"),
        ("88888888", "LIA VARGO TENREIRO", "LIA VARGO TENREIRO", "***999999**"),   # homônimo: CPF ≠
        ("88888888", "IVO VARGO TENREIRO", "IVO VARGO TENREIRO", "***444444**"),
    ])
    con.commit()
    con.close()
    return str(p)


def test_socio_oculto_homonimo_de_cpf_diferente_nao_soma_empresas(base):
    d = C.socio_oculto(db_path=base)
    nomes = {a["socio"]: a for a in d["achados"]}
    assert "JOSE QUINTAL" not in nomes                     # negativo: 2 + 1 de outra pessoa
    assert nomes["MARA SOLTO"]["selo"] == ip.VERIFICADO    # positivo
    assert nomes["MARA SOLTO"]["doc"] == "***.202.020-**" and not nomes["MARA SOLTO"]["holding"]
    assert "SEM DOC NUNES" not in nomes                    # só o nome: fora da lista
    assert [x["socio"] for x in d["indeterminados"]] == ["SEM DOC NUNES"]


def test_nepotismo_sobrenome_so_vira_achado_com_sociedade_conferida_por_cpf(base):
    d = C.nepotismo(db_path=base)
    assert [a["sobrenome"] for a in d["achados"]] == ["KLOTZ BRANDT"]
    assert d["achados"][0]["selo"] == ip.INDICIO and "77777777" in d["achados"][0]["motivo"]
    hip = {a["sobrenome"]: a for a in d["hipoteses"]}
    # LIA tem homônimo sócio da 88888888 com OUTRO CPF: não corrobora — fica hipótese
    assert hip["VARGO TENREIRO"]["selo"] == ip.HIPOTESE


def test_nepotismo_cruzado_descarta_a_propria_autoridade(base):
    d = C.nepotismo_cruzado(db_path=base)
    assert d["n"] == 0 and d["n_hipoteses"] == 0
    assert d["descartados_mesma_pessoa"] == 1


def test_grafo_familias_nao_funde_comissionado_e_socio_so_pelo_nome(base):
    g = C.grafo_familias(db_path=base, so_com_empresa=False)
    assert g["identidade"]["homonimos_separados"] >= 1 and g["identidade"]["fundidos_por_cpf"] == 0
    lia = [n for n in g["nodes"] if n["tipo"] == "pessoa" and n["label"] == "LIA VARGO TENREIRO"]
    assert len(lia) == 2                                  # comissionado e sócio homônimo: dois nós
    assert all(n["selo"] == ip.HIPOTESE for n in g["nodes"] if n["tipo"] == "familia")
    assert all(lk["tipo"] != "parentesco" for lk in g["links"])


# ─────────────────── rede de sócios (Lex, relatório, /api) ───────────────────────────────────

def test_rede_por_socio_exige_nome_e_documento(tmp_path, monkeypatch):
    from compliance_agent import rede_societaria as rs
    db = tmp_path / "r.db"
    monkeypatch.setattr(rs, "_DB", str(db))
    con = rs._con()
    con.executemany("INSERT INTO socios_fornecedor (cnpj,razao,socio_nome,socio_nome_norm,socio_doc) VALUES (?,?,?,?,?)", [
        ("11111111000101", "ALVO", "JOSE QUINTAL", "JOSE QUINTAL", "***101010**"),
        ("11111111000101", "ALVO", "SEM DOC NUNES", "SEM DOC NUNES", ""),
        ("22222222000101", "MESMO DONO", "JOSE QUINTAL", "JOSE QUINTAL", "***101010**"),     # positivo
        ("33333333000101", "HOMONIMO", "JOSE QUINTAL", "JOSE QUINTAL", "***909090**"),       # negativo
        ("44444444000101", "SO NOME", "SEM DOC NUNES", "SEM DOC NUNES", "")])                # indeterminado
    con.commit(); con.close()
    r = rs.rede_por_socio("11111111000101")
    assert [x["cnpj"] for x in r["relacionados"]] == ["22222222000101"]
    assert r["relacionados"][0]["selo"] == ip.VERIFICADO
    assert [x["cnpj"] for x in r["indeterminados"]] == ["44444444000101"]
    assert r["homonimos_descartados"] == 1


# ─────────────────── servidor-fantasma da Prefeitura/Câmara (folha sem CPF) ──────────────────

def test_fantasma_so_por_nome_nunca_e_forte():
    from compliance_agent.pcrj import fantasma_servidor as fs
    assert fs._faixa(9, False) == "verificar"                       # sem documento: teto VERIFICAR
    assert fs._faixa(2, False) == "fraco"
    assert fs._faixa(9, False, identidade="VERIFICADO") == "forte"  # positivo: só com identidade conferida
    assert fs._faixa(9, True, identidade="VERIFICADO") == "verificar"


# ─────────────────── comissionados da Prefeitura × candidatos (TSE traz CPF/título) ─────────

def test_comissionado_candidato_expoe_homonimo_do_tse_e_fica_indeterminado(tmp_path):
    from compliance_agent.pcrj import comissionados_candidatos as cc
    h = ["NM_CANDIDATO", "NR_CPF_CANDIDATO", "NR_TITULO_ELEITORAL_CANDIDATO"]
    (tmp_path / "consulta_cand_2020_RJ.csv").write_text(
        ";".join(h) + "\n" + "JOSE QUINTAL;11122233344;123456789012\n" + "JOSE QUINTAL;55566677788;999888777666\n"
        + "MARA SOLTO;12312312312;111122223333\n", encoding="latin-1")
    pt = cc.pessoas_tse_por_nome(tmp_path)
    assert pt == {"JOSE QUINTAL": 2, "MARA SOLTO": 1}
    linha = {"orgao_pcrj": "SMS", "cargo_pcrj": "ASSESSOR", "admissao": "2021-01", "exoneracao": None,
             "matricula": "1", "cand_ano": 2020, "cand_cargo": "VEREADOR", "cand_cidade": "RIO DE JANEIRO"}
    out = {p["nome_norm"]: p for p in cc.agrupar_por_pessoa(
        [{**linha, "nome_norm": "JOSE QUINTAL", "nome_pcrj": "JOSE QUINTAL"},
         {**linha, "nome_norm": "MARA SOLTO", "nome_pcrj": "MARA SOLTO"}], pt)}
    assert out["JOSE QUINTAL"]["homonimo_provavel"] and "2 candidatos DIFERENTES" in out["JOSE QUINTAL"]["identidade_motivo"]
    assert not out["MARA SOLTO"]["homonimo_provavel"]
    assert {p["identidade"] for p in out.values()} == {"INDETERMINADO"}       # sem documento comum: nunca achado


def test_partido_nao_e_atribuido_quando_o_nome_tem_mais_de_um_titulo():
    from compliance_agent.pcrj.pericia_beneficios import _partido_de
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("CREATE TABLE pcrj_filiado (nome_norm TEXT, partido TEXT, situacao TEXT, titulo TEXT)")
    con.executemany("INSERT INTO pcrj_filiado VALUES (?,?,?,?)", [
        ("JOSE QUINTAL", "AAA", "REGULAR", "111122223333"), ("JOSE QUINTAL", "BBB", "REGULAR", "999988887777"),
        ("MARA SOLTO", "CCC", "REGULAR", "123412341234")])
    assert _partido_de(con, "JOSE QUINTAL").startswith("homônimo (2 títulos")
    assert _partido_de(con, "MARA SOLTO") == "CCC"
    assert _partido_de(con, "NINGUEM") == "—"
