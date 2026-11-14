# -*- coding: utf-8 -*-
"""Verificação independente de 13/11/2026 sobre as correções da revisão cética (pontos 1, 5 e 6).
Base sintética: nenhum nome, CPF ou CNPJ real."""
from __future__ import annotations

import sqlite3

import pytest

from compliance_agent import governo_couto_regras as GR
from compliance_agent.sancao_abrangencia import veda_ente

NOVA, VELHA = "11111111000111", "22222222000122"
O = "INSERT INTO ob_orcamentaria_siafe VALUES (?,?,?,?,NULL,?,?,'SEI-100001/000001/2026',?,?,?,?)"


@pytest.fixture()
def base(tmp_path):
    db = tmp_path / "c.db"
    c = sqlite3.connect(db)
    c.executescript("""
    CREATE TABLE ob_orcamentaria_siafe (numero_ob TEXT, ug_emitente TEXT, data_emissao TEXT, status TEXT, nl TEXT,
        credor TEXT, nome_credor TEXT, processo TEXT, valor REAL, exercicio INTEGER, gd TEXT, status_envio TEXT);
    CREATE TABLE ordens_bancarias (numero_ob TEXT, ug_codigo TEXT, valor REAL);
    CREATE TABLE despesa_execucao (ug TEXT, nome_ug TEXT);
    CREATE TABLE sancoes_federais (cadastro TEXT, cpf_cnpj TEXT, nome TEXT, categoria TEXT, data_inicio TEXT,
        data_fim TEXT, orgao TEXT, uf TEXT, processo TEXT, fundamentacao TEXT, abrangencia TEXT,
        esfera_sancionador TEXT, data_publicacao TEXT);
    CREATE TABLE agente_publico_societario (nome_norm TEXT, nome_socio TEXT, doc_socio TEXT, cnpj_basico TEXT,
        qualif_cod TEXT, origem TEXT, cargo TEXT, vinculo TEXT, orgao TEXT, comissionado INTEGER, construido_em TEXT);
    CREATE TABLE registros_folha (nome TEXT, cpf TEXT, fonte TEXT);
    CREATE TABLE contratos_tcerj (processo TEXT, sei_norm TEXT, data_contratacao TEXT, valor_contrato REAL,
        status TEXT, unidade TEXT, objeto TEXT, fornecedor TEXT, cnpj TEXT);
    CREATE TABLE publicacoes_doerj (data_publicacao TEXT, texto TEXT);
    """)
    c.executemany("INSERT INTO despesa_execucao VALUES (?,?)", [
        ("100100", "SECRETARIA FICTICIA"), ("300300", "SECRETARIA DE ESTADO DE EDUCACAO"),
        ("400400", "FUNDO ESTADUAL DE SAUDE")])
    c.executemany(O, [
        ("2026OB00001", "100100", "10/05/2026", "Contabilizado", NOVA, "NOVA LTDA", 6_000_000.0, 2026, "", ""),
        ("2022OB00009", "100100", "10/05/2022", "Contabilizado", VELHA, "VELHA SA", 1_000.0, 2022, "", ""),
        ("2026OB00011", "100100", "10/11/2026", "Contabilizado", VELHA, "VELHA SA", 10.0, 2026, "", ""),
    ])
    c.commit()
    c.close()
    return db


def _ctx(base, tmp_path, receita=None):
    return GR.Ctx(base, receita=receita, tse=None, dir_tmp=tmp_path)


# ───────────────── ponto 1: devolução só pelo SIAFE ─────────────────

def test_devolucao_so_pelo_siafe_o_espelho_do_tfe_nao_entra(base, tmp_path):
    con = sqlite3.connect(base)
    # GD sem 'Erro no Pagamento' (devolução parcial): o espelho diz 5 mi, mas o espelho não é fonte de OB
    con.execute(O, ("2026OB00020", "100100", "13/05/2026", "Contabilizado", NOVA, "NOVA LTDA", 9_000_000.0, 2026,
                    "2026GD00009", "Parcialmente Pago"))
    con.execute("INSERT INTO ordens_bancarias VALUES ('2026OB00020','100100',5000000.0)")
    con.commit()
    con.close()
    c = _ctx(base, tmp_path)
    try:
        d10 = {x["cnpj"]: x for x in GR.d10(c)["casos"]}
        assert d10[NOVA]["pago_ob"] == pytest.approx(6_000_000.0)      # piso: a OB com GD fica fora da soma
        assert c.n_devolvidas_sem_valor == 1
    finally:
        c.fechar()


# ───────────────── ponto 5: D14, D10, D13 ─────────────────

def test_d14_vermelho_so_com_contrato_novo_na_vigencia_e_prova_dentro_dela(base, tmp_path):
    inid, inid_novo = "91919191000191", "92929292000192"
    con = sqlite3.connect(base)
    con.executemany(O, [
        ("2026OB00030", "100100", "02/04/2026", "Contabilizado", inid, "INID LTDA", 900_000.0, 2026, "", ""),
        ("2026OB00031", "100100", "20/06/2026", "Contabilizado", inid, "INID LTDA", 100_000.0, 2026, "", ""),
        ("2026OB00032", "100100", "20/06/2026", "Contabilizado", inid_novo, "INID NOVO LTDA", 100_000.0, 2026, "", ""),
    ])
    con.executemany(
        "INSERT INTO sancoes_federais VALUES ('CEIS',?,?,'Declaração de Inidoneidade com prazo determinado',"
        "'2026-06-01','2029-06-01','Secretaria de Estado Ficticia','RJ','p','LEI 14133 - ART. 156, IV',"
        "'Todas as Esferas em todos os Poderes','ESTADUAL',NULL)", [(inid, "INID"), (inid_novo, "INID NOVO")])
    con.executemany("INSERT INTO contratos_tcerj VALUES (?,?,?,?,?,?,?,?,?)", [
        ("SEI-100001/000020/2026", "1000010000202026", "2026-04-10", 1.0, "Ativo", "UNIDADE X", "SERVIÇO", "INID", inid),
        ("SEI-100001/000021/2026", "1000010000212026", "2026-07-15", 1.0, "Ativo", "UNIDADE X", "SERVIÇO", "INID NOVO",
         inid_novo),
    ])
    con.commit()
    con.close()
    c = _ctx(base, tmp_path)
    try:
        res = {"D14": GR.d14(c)}
        GR.anexar_provas(c, res)
    finally:
        c.fechar()
    casos = {x["cnpj"]: x for x in res["D14"]["casos"]}
    assert casos[inid]["n_contratos_na_vigencia"] == 0 and casos[inid_novo]["n_contratos_na_vigencia"] == 1
    assert casos[inid]["pago_ob"] == pytest.approx(100_000.0)
    assert not any("2026OB00030" in p for p in casos[inid]["prova_primaria"])      # OB anterior à sanção não é prova
    a = {x["id"]: x for x in GR.achados_deterministicos(res)}
    assert a[f"D14-{inid}-2026-06-01"]["grau"] == "🟡" and "ex nunc" in a[f"D14-{inid}-2026-06-01"]["regra_ou_hipotese"]
    assert a[f"D14-{inid_novo}-2026-06-01"]["grau"] == "🔴"
    assert a["D14"]["grau"] == "🟡"            # a regra soma pagamentos; o vermelho é do caso com contrato novo


def test_d14_regra_sem_caso_de_contrato_novo_nao_e_vermelha(base, tmp_path):
    con = sqlite3.connect(base)
    con.execute(O, ("2026OB00033", "100100", "20/06/2026", "Contabilizado", NOVA, "NOVA LTDA", 1.0, 2026, "", ""))
    con.execute("INSERT INTO sancoes_federais VALUES ('CEIS',?,'N','Declaração de Inidoneidade com prazo determinado',"
                "'2026-06-01','2029-06-01','Secretaria de Estado Ficticia','RJ','p','LEI 14133 - ART. 156, IV',"
                "'Todas as Esferas em todos os Poderes','ESTADUAL',NULL)", (NOVA,))
    con.commit()
    con.close()
    c = _ctx(base, tmp_path)
    try:
        a = {x["id"]: x for x in GR.achados_deterministicos({"D14": GR.d14(c)})}
    finally:
        c.fechar()
    assert a["D14"]["grau"] == "🟡"


def test_d10_consorcio_nao_e_estreia(base, tmp_path):
    cons = "93939393000193"
    con = sqlite3.connect(base)
    con.execute(O, ("2026OB00040", "100100", "20/06/2026", "Contabilizado", cons, "CONSORCIO FICTICIO ALFA",
                    8_000_000.0, 2026, "", ""))
    con.commit()
    con.close()
    c = _ctx(base, tmp_path)
    try:
        r = GR.d10(c)
    finally:
        c.fechar()
    rot = {x["cnpj"]: x["rotulo"] for x in r["casos"]}
    assert rot[cons] == "consorcio" and rot[NOVA] == "estreia"
    assert r["n"] == 1 and r["n_consorcio"] == 1 and r["soma"] == pytest.approx(6_000_000.0)
    a = {x["id"]: x for x in GR.achados_deterministicos({"D10": r})}
    assert a[f"D10-{cons}"]["grau"] == "⚪" and "CONSÓRCIO" in a[f"D10-{cons}"]["regra_ou_hipotese"]


def test_d10_grupo_com_historico_pelo_email_de_contato(base, tmp_path):
    rec = tmp_path / "r.db"
    con = sqlite3.connect(rec)
    con.executescript("""CREATE TABLE empresas (cnpj_basico TEXT, razao_social TEXT, natureza_cod TEXT);
        CREATE TABLE estabelecimentos (cnpj TEXT, cnpj_basico TEXT, endereco_norm TEXT, correio_eletronico TEXT);""")
    con.executemany("INSERT INTO estabelecimentos VALUES (?,?,?,?)", [
        (NOVA, NOVA[:8], "RUA FICTICIA 10 CENTRO 20000000", "fiscal@grupoficticio.example"),
        (VELHA, VELHA[:8], "AVENIDA OUTRA 99 CENTRO 20000001", "fiscal@grupoficticio.example")])
    con.commit()
    con.close()
    c = _ctx(base, tmp_path, receita=rec)
    try:
        r = GR.d10(c)
    finally:
        c.fechar()
    x = {k["cnpj"]: k for k in r["casos"]}[NOVA]
    assert x["rotulo"] == "grupo_com_historico" and VELHA[:8] in x["base_rotulo"]
    assert r["n"] == 0 and r["n_grupo_com_historico"] == 1


def test_d10_email_de_contador_e_endereco_dividido_nao_tiram_da_estreia(base, tmp_path):
    rec = tmp_path / "r2.db"
    con = sqlite3.connect(rec)
    con.executescript("""CREATE TABLE empresas (cnpj_basico TEXT, razao_social TEXT, natureza_cod TEXT);
        CREATE TABLE estabelecimentos (cnpj TEXT, cnpj_basico TEXT, endereco_norm TEXT, correio_eletronico TEXT);""")
    linhas = [(NOVA, NOVA[:8], "RUA FICTICIA 10 SALA 1 20000000", "atendimento@contadorficticio.example"),
              (VELHA, VELHA[:8], "RUA FICTICIA 10 SALA 1 20000000", "atendimento@contadorficticio.example")]
    linhas += [(f"{70000000 + i}000100", str(70000000 + i), "OUTRA RUA", "atendimento@contadorficticio.example")
               for i in range(20)]                                   # e-mail de escritório contábil: 21 raízes
    con.executemany("INSERT INTO estabelecimentos VALUES (?,?,?,?)", linhas)
    con.commit()
    con.close()
    c = _ctx(base, tmp_path, receita=rec)
    try:
        r = GR.d10(c)
    finally:
        c.fechar()
    x = {k["cnpj"]: k for k in r["casos"]}[NOVA]
    assert x["rotulo"] == "estreia" and "mesmo endereço" in x["base_rotulo"]     # anotado, não retirado
    assert r["n"] == 1 and r["n_grupo_com_historico"] == 0


def test_d13_associacao_de_apoio_a_escola_fica_a_parte_e_mesmo_orgao_e_igualdade(base, tmp_path):
    aae, forn = "94949494000194", "95959595000195"
    con = sqlite3.connect(base)
    con.executemany(O, [
        ("2026OB00050", "300300", "20/06/2026", "Contabilizado", aae, "Aae Ce Ficticio", 500_000.0, 2026, "", ""),
        ("2026OB00051", "400400", "20/06/2026", "Contabilizado", forn, "CLINICA FICTICIA LTDA", 500_000.0, 2026, "", ""),
    ])
    con.executemany(
        "INSERT INTO agente_publico_societario VALUES (?,?,?,?,'49','folha_estado','PROFESSOR','EFETIVO',?,0,'x')", [
            ("DOCENTE FICTICIO UM", "DOCENTE FICTICIO UM", "***333444**", aae[:8], "SECRETARIA DE ESTADO DE EDUCACAO"),
            ("MEDICO FICTICIO DOIS", "MEDICO FICTICIO DOIS", "***555666**", forn[:8], "SECRETARIA DE ESTADO DE SAUDE"),
        ])
    con.executemany("INSERT INTO registros_folha VALUES (?,?,?)", [
        ("DOCENTE FICTICIO UM", "XX333444XXX", "gesperj_estado"),
        ("MEDICO FICTICIO DOIS", "XX555666XXX", "gesperj_estado")])
    con.commit()
    con.close()
    c = _ctx(base, tmp_path)
    try:
        r = GR.d13(c)
    finally:
        c.fechar()
    casos = {x["cnpj_basico"]: x for x in r["casos"]}
    assert aae[:8] not in casos and r["n_unidade_executora_escolar"] == 1
    # "SAUDE" em comum entre a Secretaria e o Fundo não faz "mesmo órgão": só a igualdade do nome
    assert casos[forn[:8]]["mesmo_orgao"] is False and r["n_mesmo_orgao"] == 0
    assert GR.unidade_executora_escolar("A A E Ciep 000 Ficticio", "SECRETARIA DE ESTADO DE EDUCACAO")
    assert not GR.unidade_executora_escolar("CE COMERCIO LTDA", "SECRETARIA DE ESTADO DE SAUDE")


# ───────────────── ponto 6: leis especiais no alcance da sanção ─────────────────

def test_inidoneidade_do_tcu_lei_8443_art_46_so_alcanca_a_uniao():
    s = {"categoria": "Declaração de Inidoneidade com prazo determinado", "orgao": "TRIBUNAL DE CONTAS DA UNIÃO",
         "uf": "DF", "fundamentacao": "LEI 8443 - ART. 46 - VERIFICADA A OCORRÊNCIA DE FRAUDE COMPROVADA À LICITAÇÃO",
         "data_inicio": "2026-01-01"}
    assert veda_ente(s, "estadual", "RJ")["veda"] is False                       # sem abrangência declarada
    assert veda_ente({**s, "abrangencia": "Todas as Esferas em todos os Poderes", "esfera_sancionador": "FEDERAL"},
                     "estadual", "RJ")["veda"] is False                          # a declaração não alarga a lei
    assert veda_ente(s, "federal", "RJ")["veda"] is True


def test_lei_13303_art_83_so_alcanca_a_entidade_sancionadora():
    s = {"categoria": "Impedimento/proibição de contratar com prazo determinado", "orgao": "Secretaria de Estado X",
         "uf": "RJ", "fundamentacao": "LEI 13303 - ART. 83, III - SUSPENSÃO TEMPORÁRIA", "data_inicio": "2026-01-01",
         "esfera_sancionador": "ESTADUAL"}
    assert veda_ente(s, "estadual", "RJ")["veda"] is False


def test_improbidade_depois_da_lei_14230_sem_abrangencia_declarada_nao_e_total():
    s = {"categoria": "Impedimento/proibição de contratar com prazo determinado", "uf": "SP",
         "orgao": "Tribunal de Justiça do Estado de São Paulo", "fundamentacao": "LEI 8429 - ART. 12 - INDEPENDENTEMENTE"}
    assert veda_ente({**s, "data_inicio": "2023-05-01"}, "estadual", "RJ")["veda"] is False   # art. 12, §4º: ente lesado
    assert veda_ente({**s, "data_inicio": "2019-05-01"}, "estadual", "RJ")["veda"] is True    # anterior: leitura ampla
    assert veda_ente({**s, "data_inicio": "2023-05-01", "abrangencia": "Todas as Esferas em todos os Poderes"},
                     "estadual", "RJ")["veda"] is True                                        # decisão que estende
