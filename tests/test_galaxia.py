import json
import math
import sqlite3

from compliance_agent.galaxia import _empacotar, leve, montar, recortar


def _con():
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE socios_fornecedor (cnpj TEXT, razao TEXT, socio_nome_norm TEXT, socio_doc TEXT)")
    c.executemany("INSERT INTO socios_fornecedor VALUES (?,?,?,?)", [
        ("11111111000111", "ALFA LTDA", "JOAO SILVA", "***123456**"),
        ("22222222000122", "BETA LTDA", "JOAO SILVA", "***123456**"),
        ("33333333000133", "GAMA LTDA", "(sem QSA público)", ""),
    ])
    c.execute("CREATE TABLE alertas (id INTEGER, tipo TEXT, severidade TEXT, titulo TEXT, evidencias TEXT, status TEXT)")
    c.executemany("INSERT INTO alertas VALUES (?,?,?,?,?,?)", [
        (1, "acumulacao", "alta", "Emprego múltiplo — MARIA TESTE (CPF XX123456XXX)",
         json.dumps({"cpf": "XX123456XXX", "nome": "MARIA TESTE", "orgaos": "SECRETARIA DE SAUDE,SECRETARIA DE EDUCACAO"}), "novo"),
        (2, "doerj_anomalia", "media", "OB × DOERJ — DELTA LTDA",
         json.dumps({"cpf_cnpj": "44444444000144", "favorecido": "DELTA LTDA"}), "novo"),
        (3, "doerj_anomalia", "media", "descartado não entra",
         json.dumps({"cpf_cnpj": "55555555000155", "favorecido": "EPSILON LTDA"}), "descartado"),
        (4, "enriquecimento", "alta", "Teto — FULANO", json.dumps({"nome": "FULANO", "cpf": "XX9XX"}), "novo"),
    ])
    c.execute("CREATE TABLE ordens_bancarias (ug_codigo TEXT, ug_nome TEXT)")
    c.executemany("INSERT INTO ordens_bancarias VALUES (?,?)", [("294200", "FUNDACAO SAUDE"), ("100100", "SECRETARIA DE SAUDE")])
    c.execute("CREATE TABLE ob_orcamentaria_siafe (credor TEXT, ug_emitente TEXT, valor REAL, status TEXT)")
    c.executemany("INSERT INTO ob_orcamentaria_siafe VALUES (?,?,?,?)", [
        ("44444444000144", "294200", 1000.0, "Contabilizado"),
        ("44444444000144", "294200", 9e9, "Anulado"),           # OB anulada não é pagamento
        ("66666666000166", "294200", 500.0, "Contabilizado"),
    ])
    return c


CASOS = [
    {"slug": "a", "titulo": "Caso A", "nivel": 4, "cnpjs": ["11.111.111/0001-11"], "sei": ["SEI-1"], "entidade": "UG X"},
    {"slug": "b", "titulo": "Caso B", "nivel": 2, "cnpjs": ["22.222.222/0001-22"], "sei": ["SEI-1"], "entidade": "ug x"},
    {"slug": "c", "titulo": "Caso C", "nivel": 1, "cnpjs": ["33.333.333/0001-33", "123"], "sei": [], "entidade": ""},
]
RADAR = {"ok": True, "achados": [
    {"cnpj": "66666666000166", "nome": "ZETA LTDA", "score": 55, "sinais": [{"sinal": "fenix", "peso": 30, "detalhe": "x"}]},
    {"cnpj": "77777777000177", "nome": "ETA LTDA", "score": 12, "sinais": []},
]}


def _g(**kw):
    return montar(CASOS, _con(), RADAR, None, **kw)


def test_dossies_e_pontes_entre_casos():
    g = _g()
    ids = {n["id"]: n for n in g["nos"]}
    assert {"caso:a", "caso:b", "caso:c", "cnpj:11111111000111", "sei:SEI-1", "socio:JOAO SILVA"} <= set(ids)
    assert ids["cnpj:11111111000111"]["l"] == "ALFA LTDA"
    assert "socio:(sem QSA público)" not in ids and "cnpj:123" not in ids
    ponte = [e for e in g["arestas"] if e["tipo"] == "caso_caso"]
    assert len(ponte) == 1 and {g["nos"][ponte[0]["s"]]["id"], g["nos"][ponte[0]["t"]]["id"]} == {"caso:a", "caso:b"}
    assert ponte[0]["motivos"] == {"socio": 1, "sei": 1, "ent": 1} and ponte[0]["peso"] == 3.0
    assert g["resumo"]["pontes_entre_casos"] == 1


def test_radar_alertas_e_orgao_pagador():
    g = _g()
    ids = {n["id"]: n for n in g["nos"]}
    assert ids["cnpj:66666666000166"]["s"] == 55 and g["resumo"]["criticos"] == 1
    assert "cnpj:77777777000177" in ids                         # score baixo também entra (todos os casos)
    # fornecedor mora no aglomerado de quem PAGOU (OB contabilizada), e a aresta diz o valor da OB
    assert ids["cnpj:44444444000144"]["cl"] == "ug:294200"
    e = [e for e in g["arestas"] if e["tipo"] == "orgao" and g["nos"][e["t"]]["id"] == "cnpj:44444444000144"
         or e["tipo"] == "orgao" and g["nos"][e["s"]]["id"] == "cnpj:44444444000144"][0]
    assert e["via"] == "OB" and "1.000,00" in e["det"]          # a OB anulada (9e9) não soma
    assert ids["cnpj:44444444000144"]["nal"] == 1
    # controle negativo: alerta descartado não vira nó nem conta
    assert "cnpj:55555555000155" not in ids and g["resumo"]["alertas_abertos"] == 3
    # alerta de pessoa vira CONTAGEM no órgão (casado pelo nome da UG), sem nome nem CPF
    assert ids["org:ug:100100"]["al"] == {"acumulacao": 1}
    assert "MARIA TESTE" not in json.dumps(g, ensure_ascii=False) and "XX123456XXX" not in json.dumps(g)
    assert g["resumo"]["alertas_sem_ancora"] == {"enriquecimento": 1}


def test_sem_documento_na_saida_e_sem_base():
    g = _g()
    assert "123456" not in json.dumps(g)
    g2 = montar(CASOS, None)
    assert g2["ok"] and not any(n["t"] == "socio" for n in g2["nos"])
    assert g2["fontes"]["alertas"] == "INDISPONÍVEL" and g2["fontes"]["radar"] == "INDISPONÍVEL"


def test_recorte_mantem_orgaos_e_dossies_e_resumo_global():
    g = _g()
    r = recortar(g, limite=1)
    assert sum(1 for n in r["nos"] if n["t"] == "cnpj") == 1
    assert sum(1 for n in r["nos"] if n["t"] == "caso") == 3
    assert r["resumo"] == g["resumo"]
    n = len(r["nos"])
    assert all(0 <= e["s"] < n and 0 <= e["t"] < n for e in r["arestas"])
    lv = leve(r)
    assert all(isinstance(a, list) and len(a) == 3 for a in lv["arestas"])
    assert not any("sin" in x or "ex" in x for x in lv["nos"])  # prova vem do detalhe, não do desenho
    from compliance_agent import cores_orgaos              # cor do nó = cor do órgão do aglomerado (paleta única)
    assert all(x["cor"] == cores_orgaos.cor(x.get("cl")) for x in lv["nos"])
    assert len({x["cor"] for x in lv["nos"] if x["t"] == "orgao"}) > 1


def test_empacotar_sem_sobreposicao():
    raios = [120, 80, 80, 40, 30, 30, 20, 10, 10, 10, 5]
    pos = _empacotar(raios, folga=10)
    for i in range(len(raios)):
        for j in range(i):
            d = math.dist(pos[i], pos[j])
            assert d >= raios[i] + raios[j] + 10 - 1e-6
