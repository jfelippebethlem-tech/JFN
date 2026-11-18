# -*- coding: utf-8 -*-
"""Ligações de conluio da galáxia — controle positivo E negativo para cada tipo (contato, sócio variante,
concorrentes ligados), e a integração em `galaxia.montar` (tipos novos no FIM, CPF nunca na saída)."""
import json
import sqlite3

from compliance_agent import ligacoes_conluio as L
from compliance_agent.galaxia import TIPOS_ARESTA, leve, montar

A, B, C, D = "11111111000111", "22222222000122", "33333333000133", "44444444000144"
E, F, G, H = "55555555000155", "66666666000166", "77777777000177", "88888888000188"
I, J = "99999999000199", "12121212000112"
FILIAL_A = "11111111000292"
GAL = [A, B, C, D, E, F, G, H, I, J, FILIAL_A]


def _estab():
    e = sqlite3.connect(":memory:")
    e.execute("CREATE TABLE estabelecimentos (cnpj TEXT PRIMARY KEY, telefone1 TEXT, telefone2 TEXT, "
              "correio_eletronico TEXT)")
    e.execute("CREATE TABLE empresas (cnpj_basico TEXT PRIMARY KEY, razao_social TEXT)")
    linhas = [
        (A, "2133334444", "", "alfa@alfa.com.br"),
        (FILIAL_A, "2133334444", "", ""),                    # filial: mesma empresa, não liga
        (B, "2177778888", "2133334444", ""),                  # telefone2 = telefone1 de A → liga
        (C, "2155556666", "", "joao.compras@gmail.com"),
        (D, "2155556666", "", "maria.vendas@gmail.com"),      # mesmo DOMÍNIO genérico → não liga
        (E, "2140001000", "", "socios@gmail.com"),
        (F, "2140002000", "", "socios@gmail.com"),            # mesmo endereço completo → liga
        (G, "2140003000", "", "fulano.contabilidade@gmail.com"),
        (H, "2140004000", "", "fulano.contabilidade@gmail.com"),  # contador → não liga
        (I, "2140005000", "", ""), (J, "2140006000", "", ""),
    ]
    # C e D dividem um telefone usado por mais 6 empresas fora da galáxia: central, acima do teto
    linhas += [(f"{70000000 + k:08d}000100", "2155556666", "", "") for k in range(6)]
    e.executemany("INSERT INTO estabelecimentos VALUES (?,?,?,?)", linhas)
    e.executemany("INSERT INTO empresas VALUES (?,?)", [
        (A[:8], "ALFA LTDA"), (B[:8], "BETA LTDA"), (C[:8], "GAMA LTDA"), (D[:8], "DELTA LTDA"),
        (E[:8], "EPSILON SERVICOS LTDA"), (F[:8], "ZETA OBRAS LTDA"), (G[:8], "ETA LTDA"), (H[:8], "TETA LTDA"),
        (I[:8], "IOTA LTDA"), (J[:8], "IOTA LTDA"),          # razão repetida: o nome não resolve
        ("13131313", "ETA LTDA"),                             # ETA repetida fora da galáxia: não resolve
    ])
    return e


def _con():
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE socios_fornecedor (cnpj TEXT, razao TEXT, socio_nome_norm TEXT, socio_doc TEXT)")
    c.executemany("INSERT INTO socios_fornecedor VALUES (?,?,?,?)", [
        (A, "ALFA LTDA", "JOSE CARLOS DA SILVA", "***908172**"),
        (C, "GAMA LTDA", "JOSE CARLOS SILVA", "***908172**"),       # variante do mesmo sócio
        (B, "BETA LTDA", "MARIA SOUZA", "***364519**"),
        (D, "DELTA LTDA", "MARIA SOUZA", "***827364**"),            # homônimo: CPF diferente
        (G, "ETA LTDA", "PEDRO ALVES", "***615243**"),
        (H, "TETA LTDA", "ANA BEATRIZ ROCHA", "***615243**"),       # colisão de dígitos, nome distante
        (I, "IOTA LTDA", "PAULO MENDES", "***739182**"),
    ])
    c.execute("CREATE TABLE socios_receita (cnpj_basico TEXT, ident TEXT, nome_norm TEXT, doc_socio TEXT)")
    c.executemany("INSERT INTO socios_receita VALUES (?,?,?,?)", [
        (J[:8], "2", "PAULO MENDES", "***739182**"),                # mesmo sócio que I, pelo documento
    ])
    c.execute("CREATE TABLE pncp_resultado (certame TEXT, fornecedor_cnpj TEXT, fornecedor_nome TEXT, "
              "orgao_nome TEXT, objeto TEXT)")
    c.executemany("INSERT INTO pncp_resultado VALUES (?,?,?,?,?)", [
        ("CERT-1", A, "ALFA", "SECRETARIA X", "merenda"), ("CERT-1", B, "BETA", "SECRETARIA X", "merenda"),
        ("CERT-2", B, "BETA", "SECRETARIA Y", "obra"), ("CERT-2", D, "DELTA", "SECRETARIA Y", "obra"),
    ])
    c.execute("CREATE TABLE proposta_item (certame TEXT, fornecedor_cnpj TEXT, fonte TEXT)")
    c.executemany("INSERT INTO proposta_item VALUES (?,?,?)", [
        ("SEI-9", A, "sei_precos"), ("SEI-9", C, "sei_precos"),     # pesquisa de preço não é disputa
        ("SEI-8", I, "sei_proposta"), ("SEI-8", J, "sei_proposta"),
    ])
    c.execute("CREATE TABLE tcerj_licitante (ente TEXT, ano INTEGER, processo TEXT, participante TEXT, objeto TEXT)")
    c.executemany("INSERT INTO tcerj_licitante VALUES (?,?,?,?,?)", [
        ("NITEROI", 2024, "10/2024", "Epsilon Serviços Ltda", "limpeza"),
        ("NITEROI", 2024, "10/2024", "ZETA OBRAS LTDA", "limpeza"),
        ("MACAE", 2024, "11/2024", "ETA LTDA", "x"), ("MACAE", 2024, "11/2024", "TETA LTDA", "x"),
    ])
    return c


def _pares(r, tipo):
    return {(e["a"], e["b"]) for e in r["arestas"] if e["tipo"] == tipo}


def test_contato_positivo_e_negativos():
    r = L.contatos(_estab(), GAL)
    assert (A[:8], B[:8]) in r["pares"]                                   # telefone1 × telefone2
    assert (E[:8], F[:8]) in r["pares"]                                   # mesmo e-mail completo
    assert (C[:8], D[:8]) not in r["pares"]                               # central acima do teto
    assert (G[:8], H[:8]) not in r["pares"]                               # e-mail de contador
    assert all(a != b for a, b in r["pares"])                             # filial não liga com a matriz
    assert r["medida"]["telefone_acima_do_teto"] == 1 and r["medida"]["email_de_servico"] == 2
    via = r["pares"][(E[:8], F[:8])][0]["via"]
    assert "so***@gmail.com" in via and "socios@" not in via              # e-mail sai mascarado


def test_socio_variante_positivo_e_negativos():
    regs, fontes = L.registros_socios(_con(), GAL)
    assert fontes == {"socios_fornecedor": "ok", "socios_receita": "ok"}
    var = L.socios_variantes(regs)
    assert set(var) == {(A[:8], C[:8])}                                   # grafia diferente, mesmos dígitos
    assert "908172" not in json.dumps(list(var.values()))                              # os dígitos nunca saem
    ident = L.socios_identicos(regs)
    assert (B[:8], D[:8]) not in ident                                    # homônimo com CPF diferente
    assert (G[:8], H[:8]) not in var and (G[:8], H[:8]) not in ident      # colisão de dígitos
    assert (J[:8], I[:8]) in ident                                        # mesmo nome E mesmo documento


def test_concorrentes_ligados_positivo_e_negativos():
    r = L.levantar(_con(), _estab(), GAL, end_grupos={G: {"mesma sala 601"}, H: {"mesma sala 601"}})
    cl = {(e["a"], e["b"]): e for e in r["arestas"] if e["tipo"] == "concorrentes_ligados"}
    assert (A[:8], B[:8]) in cl                                           # CERT-1 + mesmo telefone
    assert cl[(A[:8], B[:8])]["ev"]["certames"][0]["certame"] == "CERT-1"
    assert cl[(A[:8], B[:8])]["ev"]["tipos_vinculo"] == ["telefone"]
    assert (E[:8], F[:8]) in cl                                           # TCE-RJ pela razão única + e-mail
    assert (J[:8], I[:8]) in cl                                           # proposta nos autos + sócio
    assert (B[:8], D[:8]) not in cl                                       # disputaram, mas homônimo não é vínculo
    assert (A[:8], C[:8]) not in cl                                       # vínculo, mas só pesquisa de preço
    assert (G[:8], H[:8]) not in cl                                       # ETA LTDA repetida na Receita: não resolve
    assert all(e["estado"] == "indício a verificar" for e in r["arestas"])
    assert r["medida"]["certames"]["por_fonte"] == {"pncp": 2, "sei": 1, "tcerj": 1}


def test_integracao_na_galaxia_tipos_no_fim_e_sem_cpf():
    radar = {"ok": True, "achados": [{"cnpj": c, "nome": "", "score": 10, "sinais": []} for c in GAL]}
    g = montar([], _con(), radar, None, _estab())
    tipos = {e["tipo"] for e in g["arestas"]}
    assert {"contato", "socio_variante", "concorrentes_ligados"} <= tipos
    assert TIPOS_ARESTA[:7] == ("orgao", "socio", "cita_cnpj", "cita_sei", "caso_orgao", "caso_caso", "endereco")
    lv = leve(g)
    i = lv["tipos_aresta"].index("concorrentes_ligados")
    assert any(a[2] == i for a in lv["arestas"])
    assert g["resumo"]["ligacoes_concorrentes"] >= 2 and g["resumo"]["ligacoes_socio_variante"] == 1
    ids = {n["id"] for n in g["nos"]}
    assert f"cnpj:{FILIAL_A}" in ids                                      # nada de pessoa física como nó
    assert not any(n["t"] not in ("orgao", "cnpj", "socio", "caso", "sei") for n in g["nos"])
    s = json.dumps(g, ensure_ascii=False)
    for dig in ("908172", "364519", "827364", "615243", "739182"):
        assert dig not in s


def test_sem_receita_contato_indisponivel_nao_zero():
    radar = {"ok": True, "achados": [{"cnpj": c, "nome": "", "score": 10, "sinais": []} for c in GAL]}
    g = montar([], _con(), radar, None, None)
    assert g["fontes"]["conluio_contato_receita"] == "INDISPONÍVEL"
    assert g["fontes"]["conluio_tcerj_licitante"].startswith("INDISPONÍVEL")
