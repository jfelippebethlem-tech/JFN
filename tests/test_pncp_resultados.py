# -*- coding: utf-8 -*-
"""Coletor de resultados estruturados do PNCP — lógica determinística (sem rede).

A coleta HTTP (coletar_resultados) não é testada com rede na suíte; aqui vão o schema, o gerador
de janelas mensais, a agregação registros_vencedores e o detector de rodízio de vencedores.
"""
import sqlite3

from compliance_agent.collectors import pncp_resultados as PR
from compliance_agent.rodizio_grafo import detectar_rodizio_vencedores

A, B, C = "11111111000111", "22222222000122", "33333333000133"


def _con():
    con = sqlite3.connect(":memory:")
    PR.init_schema(con)
    return con


def _seed(con, certame, orgao, item, cnpj, nome, valor, ordem=1, uf="RJ"):
    con.execute("INSERT OR IGNORE INTO pncp_resultado (certame,orgao_cnpj,uf,item,fornecedor_cnpj,"
                "fornecedor_nome,valor_homologado,ordem_classificacao) VALUES (?,?,?,?,?,?,?,?)",
                (certame, orgao, uf, item, cnpj, nome, valor, ordem))
    con.commit()


def test_schema_cria_tabela_e_indices():
    con = _con()
    cols = {r[1] for r in con.execute("PRAGMA table_info(pncp_resultado)")}
    assert {"certame", "fornecedor_cnpj", "valor_homologado", "ordem_classificacao", "uf"} <= cols
    idx = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    assert any("forn" in i for i in idx)


def test_meses_gera_janelas_fechadas():
    janelas = list(PR._meses(2024, 11, 2025, 2))
    assert janelas[0] == ("20241101", "20241130")
    assert janelas[1] == ("20241201", "20241231")  # dezembro fecha em 31
    assert janelas[2] == ("20250101", "20250131")
    assert janelas[-1] == ("20250201", "20250228")  # fevereiro 2025 = 28 dias
    assert len(janelas) == 4


def test_meses_um_unico_mes():
    assert list(PR._meses(2025, 6, 2025, 6)) == [("20250601", "20250630")]


def test_registros_vencedores_agrega_por_certame():
    con = _con()
    _seed(con, "cert-1", A, 1, B, "EMP B", 1000.0)
    _seed(con, "cert-1", A, 2, B, "EMP B", 500.0)   # mesmo vencedor, 2 itens → soma
    _seed(con, "cert-2", A, 1, C, "EMP C", 2000.0)
    regs = PR.registros_vencedores(con)
    by = {r["certame"]: r for r in regs}
    assert len(regs) == 2
    v1 = by["cert-1"]["vencedores"][0]
    assert v1["cnpj"] == B and abs(v1["valor"] - 1500.0) < 0.01  # soma dos 2 itens


def test_registros_vencedores_ignora_nao_homologado():
    con = _con()
    _seed(con, "cert-1", A, 1, B, "EMP B", 1000.0, ordem=1)
    _seed(con, "cert-1", A, 1, C, "EMP C", 900.0, ordem=2)  # 2º lugar não é vencedor
    regs = PR.registros_vencedores(con)
    cnpjs = {v["cnpj"] for v in regs[0]["vencedores"]}
    assert cnpjs == {B}  # só o ordem=1


def test_registros_vencedores_filtra_uf():
    con = _con()
    _seed(con, "c-rj", A, 1, B, "B", 1.0, uf="RJ")
    _seed(con, "c-sp", A, 1, C, "C", 1.0, uf="SP")
    assert len(PR.registros_vencedores(con, uf="RJ")) == 1
    assert len(PR.registros_vencedores(con, uf=None)) == 2


def test_detecta_captura_de_orgao():
    regs = [{"certame": f"c{i}", "orgao": A, "vencedores": [{"cnpj": B, "valor": 100}]} for i in range(9)]
    regs.append({"certame": "c9", "orgao": A, "vencedores": [{"cnpj": C, "valor": 100}]})
    r = detectar_rodizio_vencedores(regs, min_certames=5)
    assert r["captura"] and r["captura"][0]["vencedor"] == B
    assert r["captura"][0]["share"] == 0.9


def test_detecta_rodizio_de_vencedores():
    regs = [{"certame": f"c{i}", "orgao": A, "vencedores": [{"cnpj": (B if i % 2 else C), "valor": 100}]}
            for i in range(10)]
    r = detectar_rodizio_vencedores(regs, min_certames=5)
    assert r["rodizio_vencedores"] and r["rodizio_vencedores"][0]["cobertura_grupo"] == 1.0
    assert set(r["rodizio_vencedores"][0]["grupo"]) == {B, C}


def test_mercado_competitivo_nao_dispara():
    # 10 certames, 10 vencedores distintos → nem captura nem rodízio
    regs = [{"certame": f"c{i}", "orgao": A,
             "vencedores": [{"cnpj": f"{i:014d}", "valor": 100}]} for i in range(10)]
    r = detectar_rodizio_vencedores(regs, min_certames=5)
    assert not r["captura"] and not r["rodizio_vencedores"]


def test_amostra_pequena_nao_dispara():
    regs = [{"certame": f"c{i}", "orgao": A, "vencedores": [{"cnpj": B, "valor": 100}]} for i in range(4)]
    r = detectar_rodizio_vencedores(regs, min_certames=5)
    assert not r["captura"]


# ── gate de similaridade de objeto no rodízio (corta o FP 'ventilador vs vestibular') ──

def _reg_obj(certame, orgao, objeto, cnpj):
    return {"certame": certame, "orgao": orgao, "objeto": objeto,
            "vencedores": [{"cnpj": cnpj, "valor": 100}]}


def test_gate_objeto_similar_dispara_rodizio():
    regs = [_reg_obj(f"s{i}", A, "limpeza e conservacao predial escolar", (B if i % 2 else C))
            for i in range(6)]
    r = detectar_rodizio_vencedores(regs, min_certames=4)
    assert len(r["rodizio_vencedores"]) == 1
    rod = r["rodizio_vencedores"][0]
    assert rod["coesao_objeto"] and rod["coesao_objeto"] >= 0.3
    assert "limpeza" in rod["termos_comuns"]


def test_gate_objeto_diverso_suprime_rodizio():
    objs = ["ventiladores hospitalares uti", "concurso vestibular medicina",
            "locacao de veiculos", "material de escritorio",
            "servico de vigilancia armada", "obras de pavimentacao asfaltica"]
    regs = [_reg_obj(f"d{i}", A, o, (B if i % 2 else C)) for i, o in enumerate(objs)]
    r = detectar_rodizio_vencedores(regs, min_certames=4)
    assert r["rodizio_vencedores"] == []  # objetos diversos → clusters pequenos → sem rodízio


def test_gate_remove_tokens_do_nome_do_orgao():
    # objetos diversos, mas todos citam o nome do município → não pode gerar coesão falsa
    regs = [{"certame": f"m{i}", "orgao": A, "orgao_nome": "MUNICIPIO DE PATY DO ALFERES",
             "objeto": f"prefeitura de paty do alferes - {o}",
             "vencedores": [{"cnpj": (B if i % 2 else C), "valor": 100}]}
            for i, o in enumerate(["merenda escolar", "combustivel", "material medico",
                                   "obras de drenagem", "locacao de veiculos", "servico de limpeza"])]
    r = detectar_rodizio_vencedores(regs, min_certames=4)
    assert r["rodizio_vencedores"] == []  # nome do órgão removido → objetos ficam diversos → sem rodízio


def test_gate_sem_objeto_mantem_compat():
    regs = [_reg_obj(f"o{i}", A, "", (B if i % 2 else C)) for i in range(6)]
    r = detectar_rodizio_vencedores(regs, min_certames=4)
    assert len(r["rodizio_vencedores"]) == 1
    assert r["rodizio_vencedores"][0]["coesao_objeto"] is None  # bucket ∅, sem gate


# ── unidadeOrgao (bug: painel mostrava sempre o ENTE "Estado do Rio de Janeiro") ──
# O PNCP identifica contratação estadual pelo CNPJ do ente federativo; o órgão REAL
# (secretaria/autarquia) vem em unidadeOrgao. Sem ela, todos os órgãos do Estado
# colapsam num só — nome errado no painel e análise de captura/rodízio corrompida.

ENTE_RJ = "42498600000171"


def _seed_uni(con, certame, cnpj_ente, ente_nome, uni_cod, uni_nome, forn, forn_nome):
    con.execute("INSERT OR IGNORE INTO pncp_resultado (certame,orgao_cnpj,orgao_nome,uf,item,"
                "fornecedor_cnpj,fornecedor_nome,valor_homologado,ordem_classificacao,"
                "unidade_codigo,unidade_nome) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (certame, cnpj_ente, ente_nome, "RJ", 1, forn, forn_nome, 100.0, 1,
                 uni_cod, uni_nome))
    con.commit()


def test_schema_tem_colunas_de_unidade():
    con = _con()
    cols = {r[1] for r in con.execute("PRAGMA table_info(pncp_resultado)")}
    assert {"unidade_codigo", "unidade_nome"} <= cols


def test_init_schema_migra_tabela_antiga():
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE pncp_resultado (certame TEXT NOT NULL, orgao_cnpj TEXT, "
                "orgao_nome TEXT, uf TEXT, municipio TEXT, modalidade INTEGER, objeto TEXT, "
                "data_pub TEXT, item INTEGER NOT NULL, fornecedor_cnpj TEXT, fornecedor_nome TEXT, "
                "valor_homologado REAL, ordem_classificacao INTEGER, porte_fornecedor INTEGER, "
                "coletado_em TEXT, PRIMARY KEY (certame, item, fornecedor_cnpj))")
    PR.init_schema(con)
    cols = {r[1] for r in con.execute("PRAGMA table_info(pncp_resultado)")}
    assert {"unidade_codigo", "unidade_nome"} <= cols


def test_registros_vencedores_separa_orgaos_por_unidade():
    con = _con()
    _seed_uni(con, "e-1", ENTE_RJ, "ESTADO DO RIO DE JANEIRO", "100", "SECRETARIA DE ESTADO DE SAUDE", B, "EMP B")
    _seed_uni(con, "e-2", ENTE_RJ, "ESTADO DO RIO DE JANEIRO", "200", "DETRAN-RJ", C, "EMP C")
    regs = PR.registros_vencedores(con)
    chaves = {r["orgao"] for r in regs}
    assert len(chaves) == 2  # mesma razão social do ente ≠ mesmo órgão
    by = {r["certame"]: r for r in regs}
    assert by["e-1"]["unidade_nome"] == "SECRETARIA DE ESTADO DE SAUDE"
    assert by["e-1"]["orgao_nome"] == "ESTADO DO RIO DE JANEIRO"  # ente preservado (esfera/compat)


def test_registros_vencedores_sem_unidade_mantem_chave_cnpj():
    con = _con()
    _seed(con, "cert-1", A, 1, B, "EMP B", 1000.0)
    regs = PR.registros_vencedores(con)
    assert regs[0]["orgao"] == A  # linha antiga (sem backfill) não muda de chave


def test_conluio_enriquecido_mostra_nome_da_unidade():
    con = _con()
    # captura: EMP B vence 5/5 certames da SES; ente = Estado do RJ
    for i in range(5):
        _seed_uni(con, f"ses-{i}", ENTE_RJ, "ESTADO DO RIO DE JANEIRO", "100",
                  "SECRETARIA DE ESTADO DE SAUDE", B, "EMP B")
    r = PR.conluio_enriquecido(con, min_certames=4)
    assert r["captura"], "captura da unidade deve disparar"
    cap = r["captura"][0]
    assert cap["orgao_nome"] == "SECRETARIA DE ESTADO DE SAUDE"  # o órgão real, não o ente
    assert cap["ente_nome"] == "ESTADO DO RIO DE JANEIRO"
    assert cap["orgao_cnpj_fmt"] == "42.498.600/0001-71"  # CNPJ do ente, não a chave composta


def test_esfera_considera_unidade_alem_do_ente():
    # dado REAL do PNCP: certame com ente "ESTADO DO RIO DE JANEIRO" mas unidade
    # "PREF.MUN.DO RIO DE JANEIRO/RJ" — a esfera correta é prefeitura, não estado
    con = _con()
    for i in range(5):
        _seed_uni(con, f"pm-{i}", ENTE_RJ, "ESTADO DO RIO DE JANEIRO", "986001",
                  "PREF.MUN.DO RIO DE JANEIRO/RJ", B, "EMP B")
    r_pref = PR.conluio_enriquecido(con, min_certames=4, esfera="prefeitura")
    r_est = PR.conluio_enriquecido(con, min_certames=4, esfera="estado")
    assert r_pref["captura"], "unidade municipal deve cair na esfera prefeitura"
    assert not r_est["captura"], "e sair da esfera estado"


def test_esfera_municipio_vazio_nao_e_rio():
    # BUG real 2026-07-20: municipio VAZIO era tratado como Rio → Companhia de Desenvolvimento de
    # MARICÁ (esfera oficial 'M', campo municipio em branco) vazava na aba Prefeitura do Rio.
    oficial = {"29131075000193": "M", "42498733000148": "M"}
    # Maricá (esf 'M', municipio vazio, nome sem "RIO DE JANEIRO") → 'municipios', NÃO 'prefeitura'
    marica = {"orgao_cnpj": "29131075000193", "orgao_nome": "MUNICIPIO DE MARICA",
              "unidade_nome": "", "municipio": ""}
    assert PR.classificar_esfera(marica, oficial) == "municipios"
    # Município do Rio (esf 'M', municipio vazio, MAS nome tem "RIO DE JANEIRO") → 'prefeitura'
    rio = {"orgao_cnpj": "42498733000148", "orgao_nome": "MUNICIPIO DO RIO DE JANEIRO",
           "unidade_nome": "SMS", "municipio": ""}
    assert PR.classificar_esfera(rio, oficial) == "prefeitura"
    # Rio pelo campo municipio explícito também
    rio2 = {"orgao_cnpj": "42498733000148", "orgao_nome": "PREFEITURA", "unidade_nome": "H",
            "municipio": "Rio de Janeiro"}
    assert PR.classificar_esfera(rio2, oficial) == "prefeitura"


def test_esfera_unidade_estadual_com_municipios_no_nome_fica_estado():
    # counterexample do code review: substring "MUNICÍPIOS" em unidade ESTADUAL não pode
    # reclassificar o órgão como prefeitura
    assert PR.esfera_do_orgao("SECRETARIA DE ESTADO DE APOIO AOS MUNICIPIOS") == "estado"
    assert PR.esfera_do_orgao("MUNICIPIO DE PARACAMBI") == "prefeitura"


def test_leitores_degradam_em_schema_antigo_sem_unidade():
    # base pré-migração (mode=ro nunca roda init_schema): não pode dar 500
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE pncp_resultado (certame TEXT NOT NULL, orgao_cnpj TEXT, "
                "orgao_nome TEXT, uf TEXT, municipio TEXT, modalidade INTEGER, objeto TEXT, "
                "data_pub TEXT, item INTEGER NOT NULL, fornecedor_cnpj TEXT, fornecedor_nome TEXT, "
                "valor_homologado REAL, ordem_classificacao INTEGER, porte_fornecedor INTEGER, "
                "coletado_em TEXT, PRIMARY KEY (certame, item, fornecedor_cnpj))")
    con.execute("INSERT INTO pncp_resultado (certame,orgao_cnpj,orgao_nome,uf,item,fornecedor_cnpj,"
                "fornecedor_nome,valor_homologado,ordem_classificacao) VALUES "
                "('c1',?,?, 'RJ',1,?, 'EMP B',100.0,1)", (A, "ORGAO X", B))
    con.commit()
    regs = PR.registros_vencedores(con)
    assert regs and regs[0]["orgao"] == A and regs[0]["unidade_nome"] is None


def test_cobertura_expoe_certames_sem_unidade():
    con = _con()
    _seed(con, "cert-1", A, 1, B, "EMP B", 1000.0)  # sem unidade (pré-backfill)
    _seed_uni(con, "e-1", ENTE_RJ, "ESTADO DO RIO DE JANEIRO", "100", "SES", C, "EMP C")
    r = PR.conluio_enriquecido(con, min_certames=99)
    assert r["cobertura"]["certames_sem_unidade"] == 1


def test_conluio_do_orgao_casa_por_nome_da_unidade():
    import os
    import tempfile
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        con = sqlite3.connect(path)
        PR.init_schema(con)
        for i in range(4):
            _seed_uni(con, f"det-{i}", ENTE_RJ, "ESTADO DO RIO DE JANEIRO", "200",
                      "DEPARTAMENTO DE TRANSITO DETRAN", B, "EMP B")
        con.close()
        r = PR.conluio_do_orgao("DETRAN", db_path=path, min_certames=3)
        assert r["n_certames"] == 4  # match pelo nome da UNIDADE (orgao_nome é o ente)
    finally:
        os.unlink(path)
