# -*- coding: utf-8 -*-
"""Conluio por participação — perdedor de cobertura, par inseparável e rodízio, contra o acaso DO MERCADO.

O antecessor (`editais/screens_participacao`) media o lift contra o universo inteiro (15 mil certames
de 91 municípios): duas empresas de Bom Jesus do Itabapoana que se encontram 4 vezes davam lift
2.572× — o acaso "esperado" era 0,0 porque o denominador era o estado. Cada teste negativo abaixo é
um falso positivo que esse desenho produzia ou que o dado real mostrou.
"""
from __future__ import annotations

import sqlite3

import pytest

from compliance_agent.editais import conluio_participacao as cp


@pytest.fixture()
def con():
    c = sqlite3.connect(":memory:")
    c.execute("""CREATE TABLE tcerj_licitante (
        ente TEXT, ano INTEGER, mes INTEGER, processo TEXT, participante TEXT, resultado TEXT,
        tipo_participacao TEXT, data_homologacao TEXT, modalidade TEXT, objeto TEXT,
        qtd_participantes INTEGER, valor_homologacao REAL, valor_estimado REAL,
        tipologia TEXT, coletado_em TEXT)""")
    return c


def _cert(con, proc, vencedores, perdedores, *, ente="MUN", tip="OUTRAS COMPRAS",
          mod="PREGÃO ELETRÔNICO", data="2024-03-01", tipo="COMUM", valor=100.0):
    if isinstance(vencedores, str):
        vencedores = [vencedores]
    n = len(set(vencedores) | set(perdedores))
    linhas = [(ente, 2024, 1, proc, v, "VENCEDOR", tipo, data, mod, "objeto " + proc, n, valor, 120.0, tip, "")
              for v in vencedores]
    linhas += [(ente, 2024, 1, proc, p, "PERDEDOR", tipo, data, mod, "objeto " + proc, n, valor, 120.0, tip, "")
               for p in perdedores]
    con.executemany("INSERT INTO tcerj_licitante VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", linhas)


def _mercado_de_fundo(con, n, *, ente="MUN", tip="OUTRAS COMPRAS", prefixo="F"):
    """Mercado competitivo: vencedores e perdedores variados, ninguém fixo."""
    for i in range(n):
        _cert(con, f"{prefixo}{i}", f"{prefixo}V{i % 7} COMERCIO", [f"{prefixo}P{(i * 3) % 11} LTDA",
                                                                   f"{prefixo}Q{(i * 5) % 13} LTDA"],
              ente=ente, tip=tip)


# ───────────────────────── leitura do certame ─────────────────────────────────────────────────

def test_quem_vence_um_item_e_perde_outro_NAO_e_perdedor_do_certame(con):
    # 15.064 (ente, processo, participante) do TCE-RJ têm VENCEDOR e PERDEDOR — pregão por item.
    _cert(con, "1", ["ALFA LTDA", "BETA LTDA"], ["BETA LTDA", "GAMA LTDA"])
    c = cp.certames_tcerj(con)[0]
    assert c["vencedores"] == {"ALFA", "BETA"}
    assert c["perdedores"] == {"GAMA"}


@pytest.mark.parametrize("mod,tip", [
    ("CREDENCIAMENTO (LEI 14.133/2021)", "OUTROS SERVIÇOS"),
    ("CHAMAMENTO PÚBLICO", "CHAMAMENTO PÚBLICO"),
    ("LEILÃO ELETRÔNICO (LEI 14.133/2021)", "ALIENAÇÃO DE BENS MÓVEIS OU IMÓVEIS"),
    ("PREGÃO ELETRÔNICO", "PERMISSÃO DE USO DE BENS NÃO ONEROSA"),
])
def test_procedimento_sem_disputa_fica_fora(con, mod, tip):
    # credenciamento: todos "vencem"; leilão: quem disputa é comprador; chamamento: não é preço.
    _cert(con, "1", "ALFA LTDA", ["BETA LTDA"], mod=mod, tip=tip)
    assert cp.certames_tcerj(con) == []


# ───────────────────────── perdedor de cobertura ─────────────────────────────────────────────

def _cobertura_classica(con, k=6, ente="MUN"):
    for i in range(k):
        _cert(con, f"C{i}", "ALFA CONSTRUCOES LTDA", ["SOMBRA SERVICOS LTDA", f"OUTRO{i} LTDA"], ente=ente)


def test_perdedor_que_so_aparece_ao_lado_do_mesmo_vencedor_e_cobertura(con):
    _mercado_de_fundo(con, 60)
    _cobertura_classica(con)
    r = cp.analisar(cp.certames_tcerj(con))
    cob = r["cobertura"]["achados"]
    assert cob, r["cobertura"]["funil"]
    a = cob[0]
    assert (a["vencedor"], a["perdedor"]) == ("ALFA CONSTRUCOES", "SOMBRA SERVICOS")
    assert a["encontros"] == 6 and a["vitorias_do_perdedor"] == 0
    assert a["fidelidade"] == 1.0
    assert a["p_valor"] < r["cobertura"]["alfa_corrigido"]


def test_perdedor_que_perde_para_varios_vencedores_NAO_e_cobertura(con):
    # mesmo número de derrotas, cada uma para um vencedor diferente: competição normal
    _mercado_de_fundo(con, 60)
    for i in range(6):
        _cert(con, f"C{i}", f"VENCEDOR{i} LTDA", ["SOMBRA SERVICOS LTDA"])
    assert not [a for a in cp.analisar(cp.certames_tcerj(con))["cobertura"]["achados"]
                if a["perdedor"] == "SOMBRA SERVICOS"]


def test_perdedor_que_ja_venceu_NAO_e_cobertura(con):
    _mercado_de_fundo(con, 60)
    _cobertura_classica(con)
    _cert(con, "X", "SOMBRA SERVICOS LTDA", ["ALFA CONSTRUCOES LTDA"])
    assert not cp.analisar(cp.certames_tcerj(con))["cobertura"]["achados"]


def test_vencedor_que_ganha_quase_tudo_no_mercado_NAO_gera_cobertura(con):
    # Município pequeno, um fornecedor dominante (vence 90% do mercado): perder sempre para ele é o
    # esperado pelo acaso do mercado — era exatamente o falso positivo do lift global.
    for i in range(40):
        _cert(con, f"D{i}", "DOMINANTE LTDA", [f"X{i % 9} LTDA"], ente="PEQUENO")
    for i in range(4):
        _cert(con, f"E{i}", f"OUTRO{i} LTDA", [f"Y{i} LTDA"], ente="PEQUENO")
    for i in range(6):
        _cert(con, f"S{i}", "DOMINANTE LTDA", ["SOMBRA SERVICOS LTDA"], ente="PEQUENO")
    cob = cp.analisar(cp.certames_tcerj(con))["cobertura"]["achados"]
    assert not [a for a in cob if a["perdedor"] == "SOMBRA SERVICOS"]


def test_poucos_encontros_e_anedota(con):
    _mercado_de_fundo(con, 60)
    _cobertura_classica(con, k=3)
    assert not cp.analisar(cp.certames_tcerj(con))["cobertura"]["achados"]


def test_consorcio_e_grupo_aparente_sao_marcados_nao_escondidos(con):
    _mercado_de_fundo(con, 60)
    for i in range(6):
        _cert(con, f"G{i}", "VIEIRA ENGENHARIA LTDA", ["VIEIRA CONSTRUCOES LTDA", f"Z{i} LTDA"])
    a = cp.analisar(cp.certames_tcerj(con))["cobertura"]["achados"][0]
    assert "grupo_aparente" in {e["tipo"] for e in a["explicacoes_inocentes"]}


def test_funil_conta_cada_filtro(con):
    _mercado_de_fundo(con, 60)
    _cobertura_classica(con)
    f = cp.analisar(cp.certames_tcerj(con))["cobertura"]["funil"]
    assert f["pares_brutos"] >= f["com_min_encontros"] >= f["perdedor_nunca_venceu"] \
        >= f["fidelidade"] >= f["acima_do_acaso_corrigido"] >= 1


# ───────────────────────── par inseparável ───────────────────────────────────────────────────

def test_dois_que_sempre_perdem_juntos_sao_inseparaveis(con):
    _mercado_de_fundo(con, 60)
    for i in range(6):
        _cert(con, f"I{i}", f"VENC{i} LTDA", ["FIGURANTE UM LTDA", "FIGURANTE DOIS LTDA"])
    ins = cp.analisar(cp.certames_tcerj(con))["inseparaveis"]["achados"]
    assert {(a["a"], a["b"]) for a in ins} == {("FIGURANTE DOIS", "FIGURANTE UM")}
    assert ins[0]["juntos"] == 6 and ins[0]["jaccard"] == 1.0


def test_dupla_que_se_encontra_mas_tambem_separada_NAO_e_inseparavel(con):
    _mercado_de_fundo(con, 60)
    for i in range(6):
        _cert(con, f"I{i}", f"VENC{i} LTDA", ["FIGURANTE UM LTDA", "FIGURANTE DOIS LTDA"])
    for i in range(10):
        _cert(con, f"J{i}", f"VENCJ{i} LTDA", ["FIGURANTE UM LTDA"])
        _cert(con, f"K{i}", f"VENCK{i} LTDA", ["FIGURANTE DOIS LTDA"])
    assert not cp.analisar(cp.certames_tcerj(con))["inseparaveis"]["achados"]


# ───────────────────────── rodízio ───────────────────────────────────────────────────────────

def test_dois_que_se_revezam_no_primeiro_lugar_sao_rodizio(con):
    _mercado_de_fundo(con, 60)
    for i in range(8):
        a, b = ("ROTA UM LTDA", "ROTA DOIS LTDA") if i % 2 else ("ROTA DOIS LTDA", "ROTA UM LTDA")
        _cert(con, f"R{i}", a, [b])
    rod = cp.analisar(cp.certames_tcerj(con))["rodizio"]["achados"]
    assert rod and set(rod[0]["membros"]) == {"ROTA UM", "ROTA DOIS"}
    assert rod[0]["certames_juntos"] == 8


def test_um_que_sempre_vence_o_outro_NAO_e_rodizio(con):
    _mercado_de_fundo(con, 60)
    for i in range(8):
        _cert(con, f"R{i}", "ROTA UM LTDA", ["ROTA DOIS LTDA"])
    assert not cp.analisar(cp.certames_tcerj(con))["rodizio"]["achados"]


# ───────────────────────── estatística ───────────────────────────────────────────────────────

def test_cauda_de_poisson():
    assert cp.cauda_poisson(0, 3.0) == 1.0
    assert abs(cp.cauda_poisson(1, 1.0) - (1 - 2.718281828459045 ** -1)) < 1e-12
    assert cp.cauda_poisson(10, 0.1) < 1e-15
    assert 0.0 < cp.cauda_poisson(30, 0.01) < 1e-40   # sem underflow para 0 nem negativo


def test_base_sem_tabela_nao_quebra():
    vazio = sqlite3.connect(":memory:")
    assert cp.certames_tcerj(vazio) == []
    r = cp.analisar([])
    assert r["cobertura"]["achados"] == [] and r["rodizio"]["achados"] == []


# ───────────────────────── resolução de nome → CNPJ ──────────────────────────────────────────

@pytest.fixture()
def estab():
    e = sqlite3.connect(":memory:")
    e.execute("CREATE TABLE empresas (cnpj_basico TEXT PRIMARY KEY, razao_social TEXT, natureza_cod TEXT,"
              " capital_social REAL, porte_cod TEXT, fonte_mes TEXT)")
    e.execute("CREATE TABLE estabelecimentos (cnpj TEXT PRIMARY KEY, cnpj_basico TEXT, uf TEXT, "
              "municipio TEXT, situacao_cadastral TEXT, data_inicio_atividade TEXT, endereco_norm TEXT,"
              " telefone1 TEXT, telefone2 TEXT, correio_eletronico TEXT, matriz_filial TEXT DEFAULT '1',"
              " complemento TEXT)")
    e.executemany("INSERT INTO empresas (cnpj_basico, razao_social) VALUES (?,?)", [
        ("11111111", "SOMBRA SERVICOS LTDA"),
        ("22222222", "HOMONIMA COMERCIO LTDA"), ("33333333", "HOMONIMA COMERCIO LTDA"),
        ("44444444", "ALFA CONSTRUCOES LTDA"),
    ])
    e.executemany("INSERT INTO estabelecimentos (cnpj, cnpj_basico, uf) VALUES (?,?,?)", [
        ("11111111000101", "11111111", "RJ"), ("22222222000101", "22222222", "RJ"),
        ("33333333000101", "33333333", "SP"), ("44444444000101", "44444444", "RJ"),
    ])
    return e


def test_resolve_razao_unica(estab):
    r = cp.resolver_cnpj(estab, {"SOMBRA SERVICOS": "SOMBRA SERVICOS LTDA"})
    assert r["SOMBRA SERVICOS"] == {"raiz": "11111111", "via": "razao_unica"}


def test_razao_repetida_desempata_so_pela_uf_rj(estab):
    r = cp.resolver_cnpj(estab, {"HOMONIMA COMERCIO": "HOMONIMA COMERCIO LTDA"})
    assert r["HOMONIMA COMERCIO"]["raiz"] == "22222222"
    assert r["HOMONIMA COMERCIO"]["via"] == "razao_repetida_unica_no_rj"


def test_razao_cortada_em_50_caracteres_resolve_por_prefixo_unico(estab):
    estab.execute("INSERT INTO empresas (cnpj_basico, razao_social) VALUES "
                  "('55555555', 'COMERCIAL DE EQUIPAMENTOS MEDICO HOSPITALARES SERRANA LTDA')")
    cru = "COMERCIAL DE EQUIPAMENTOS MEDICO HOSPITALARES SERR"      # 50 caracteres, como veio do TCE-RJ
    r = cp.resolver_cnpj(estab, {"X": cru})
    assert r["X"] == {"raiz": "55555555", "via": "prefixo_unica"}


def test_prefixo_curto_nao_resolve(estab):
    # "ALFA" é prefixo de muita coisa — abaixo de 30 caracteres não se tenta
    assert cp.resolver_cnpj(estab, {"ALFA": "ALFA CONS"}) == {}


def test_nome_sem_registro_nao_resolve(estab):
    assert cp.resolver_cnpj(estab, {"FANTASMA": "FANTASMA LTDA"}) == {}


# ───────────────────────── falsos positivos do dado real (18/11/2026) ────────────────────────

def test_pregao_por_item_com_varios_vencedores_NAO_e_rodizio(con):
    # Dado real: 27 dos 28 "rodízios" eram distribuidoras odontológicas dividindo ITENS de registro de
    # preço (3+ vencedores por certame). Dividir itens não é revezar o 1º lugar.
    _mercado_de_fundo(con, 60)
    for i in range(10):
        a, b = ("ROTA UM LTDA", "ROTA DOIS LTDA") if i % 2 else ("ROTA DOIS LTDA", "ROTA UM LTDA")
        _cert(con, f"R{i}", [a, f"TERCEIRO{i} LTDA", f"QUARTO{i} LTDA"], [b])
    assert not cp.analisar(cp.certames_tcerj(con))["rodizio"]["achados"]


def test_partilha_nunca_passa_de_100_por_cento(con):
    # Defeito medido: certame com mais de 40 participantes saía da contagem de pares, mas entrava na
    # lista de certames do par — partilha 1,22.
    _mercado_de_fundo(con, 60)
    for i in range(8):
        a, b = ("ROTA UM LTDA", "ROTA DOIS LTDA") if i % 2 else ("ROTA DOIS LTDA", "ROTA UM LTDA")
        _cert(con, f"R{i}", a, [b])
    _cert(con, "GRANDE", "ROTA UM LTDA", ["ROTA DOIS LTDA"] + [f"MULTIDAO{i} LTDA" for i in range(45)])
    for a in cp.analisar(cp.certames_tcerj(con))["rodizio"]["achados"]:
        assert a["partilha"] <= 1.0 and len(a["certames"]) == a["certames_juntos"]


def test_nicho_de_poucos_fornecedores_NAO_e_par_inseparavel(con):
    # Dado real: GENTE SEGURADORA × PORTO SEGURO juntas em 17 certames de 14 municípios — seguro de
    # frota tem meia dúzia de seguradoras que disputam; o mercado "OUTROS SERVIÇOS" escondia o nicho.
    _mercado_de_fundo(con, 80)
    for i in range(10):
        _cert(con, f"S{i}", f"VENCE SEGURO{i % 2} SEGURADORA", ["SEGURADORA ALFA", "SEGURADORA BETA"])
    con.execute("UPDATE tcerj_licitante SET objeto = 'CONTRATACAO DE SEGURO DE VEICULOS DA FROTA' "
                "WHERE processo LIKE 'S%'")
    ins = cp.analisar(cp.certames_tcerj(con))["inseparaveis"]["achados"]
    par = [a for a in ins if {a["a"], a["b"]} == {"SEGURADORA ALFA", "SEGURADORA BETA"}]
    assert par, "pelo mercado o par passa — o corte que tem de barrar é o do nicho"
    assert not par[0]["passa_nicho"]
    assert "nicho_dominado" in {e["tipo"] for e in par[0]["explicacoes_inocentes"]} or \
        "nicho_restrito" in {e["tipo"] for e in par[0]["explicacoes_inocentes"]}


# ───────────────────────── concorrentes vinculados ───────────────────────────────────────────

def test_concorrentes_com_telefone_em_comum_no_mesmo_certame(con):
    _cert(con, "1", "ALFA CONSTRUCOES LTDA", ["SOMBRA SERVICOS LTDA"])
    _cert(con, "2", "ALFA CONSTRUCOES LTDA", ["SOMBRA SERVICOS LTDA", "TERCEIRA LTDA"])
    ids = {"ALFA CONSTRUCOES": {"raiz": "44444444"}, "SOMBRA SERVICOS": {"raiz": "11111111"},
           "TERCEIRA": {"raiz": "99999999"}}
    juntos = cp.pares_que_concorreram(cp.certames_tcerj(con), ids)
    assert set(juntos) == {("11111111", "44444444"), ("11111111", "99999999"), ("44444444", "99999999")}
    vin = {"pares": {("11111111", "44444444"): {"vinculos": [{"tipo": "telefone", "via": "mesmo telefone"}]},
                     ("11111111", "99999999"): {"vinculos": []}}}
    r = cp.concorrentes_vinculados(juntos, vin)
    assert len(r) == 1 and r[0]["certames_juntos"] == 2 and r[0]["tipos_vinculo"] == ["telefone"]
    assert r[0]["um_sempre_perde"] is True


def test_filial_da_mesma_raiz_nao_e_par(con):
    _cert(con, "1", "ALFA CONSTRUCOES LTDA", ["ALFA CONSTRUCOES FILIAL LTDA"])
    ids = {"ALFA CONSTRUCOES": {"raiz": "44444444"}, "ALFA CONSTRUCOES FILIAL": {"raiz": "44444444"}}
    assert cp.pares_que_concorreram(cp.certames_tcerj(con), ids) == {}


def test_levantar_ponta_a_ponta_com_cache(con, estab, tmp_path):
    estab.execute("UPDATE estabelecimentos SET telefone1 = '2133334444' WHERE cnpj_basico IN ('11111111','44444444')")
    for i in range(3):
        _cert(con, f"V{i}", "ALFA CONSTRUCOES LTDA", ["SOMBRA SERVICOS LTDA"])
    cache = tmp_path / "ids.json"
    r = cp.levantar(con, estab, cache=cache, estab_mtime=1.0)
    assert r["vinculados"]["so_socio_vigente"]["estado"].startswith("INDISPONÍVEL")
    viz = r["vinculados"]["achados"]
    assert len(viz) == 1 and viz[0]["tipos_vinculo"] == ["telefone"] and viz[0]["certames_juntos"] == 3
    assert viz[0]["ob_estado"]["ALFA CONSTRUCOES"].startswith("INDISPONÍVEL")
    assert cache.exists()
    # 2ª rodada: o cache responde; um nome tentado e não resolvido não volta a ser consultado
    estab.execute("DELETE FROM empresas")
    r2 = cp.levantar(con, estab, cache=cache, estab_mtime=1.0)
    assert len(r2["vinculados"]["achados"]) == 1
    # Receita mudou (mtime novo) → cache descartado
    assert cp.levantar(con, estab, cache=cache, estab_mtime=2.0)["vinculados"]["achados"] == []


def test_contato_de_filial_nao_liga_e_sala_liga(con, estab):
    # Itaú × Santander: telefone de AGÊNCIA (filial) em comum — não é vínculo entre concorrentes
    estab.executemany("INSERT INTO estabelecimentos (cnpj, cnpj_basico, uf, matriz_filial, telefone1) VALUES (?,?,?,?,?)",
                      [("11111111000282", "11111111", "RJ", "2", "2133334444"),
                       ("44444444000282", "44444444", "RJ", "2", "2133334444")])
    v = cp.vinculos(estab, [("11111111", "44444444")])
    assert v["pares"][("11111111", "44444444")]["vinculos"] == []
    # mesma SALA (complemento com dígito) liga; o mesmo prédio sem sala não
    estab.execute("UPDATE estabelecimentos SET endereco_norm = 'RUA DA ASSEMBLEIA 10 CENTRO 20011000', "
                  "complemento = 'SALA 601' WHERE cnpj IN ('11111111000101','44444444000101')")
    v = cp.vinculos(estab, [("11111111", "44444444")])
    assert [x["tipo"] for x in v["pares"][("11111111", "44444444")]["vinculos"]] == ["endereco"]
    estab.execute("UPDATE estabelecimentos SET complemento = 'LOJA' WHERE cnpj IN ('11111111000101','44444444000101')")
    assert cp.vinculos(estab, [("11111111", "44444444")])["pares"][("11111111", "44444444")]["vinculos"] == []


def test_valor_homologado_e_do_processo_nao_soma_por_vencedor(con):
    # O campo do TCE-RJ é o total do processo repetido em cada linha; somar por vencedor multiplicava.
    _cert(con, "1", ["ALFA LTDA", "BETA LTDA"], ["GAMA LTDA"], valor=100.0)
    assert cp.certames_tcerj(con)[0]["valor_homologacao"] == 100.0


def test_homologado_implausivel_vira_ausente_nao_numero(con):
    # compra de gaze em Macaé: R$ 2,21 bi homologados contra R$ 2,95 mi estimados (750×)
    _cert(con, "1", "ALFA LTDA", ["GAMA LTDA"], valor=2_210_000_000.0)
    con.execute("UPDATE tcerj_licitante SET valor_estimado = 2950000")
    c = cp.certames_tcerj(con)[0]
    assert c["valor_homologacao"] is None
    assert cp._resumo_certame(c)["valor_homologado_do_processo"] == "INDISPONÍVEL"
