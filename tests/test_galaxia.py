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


def _con_orgao():
    """Base mínima do resolvedor de órgão: OB SIAFE com processo, PCRJ despesa, TFE e PNCP."""
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE ob_orcamentaria_siafe (numero_ob TEXT, credor TEXT, ug_emitente TEXT, valor REAL, status TEXT, "
              "status_envio TEXT, processo TEXT)")
    c.executemany("INSERT INTO ob_orcamentaria_siafe VALUES (?,?,?,?,?,?,?)", [
        # prefixo 040002 → UG 180100 (3 OB pagas de processos diferentes); o processo 000009 é da UG 296100
        ("1", "90000000000190", "180100", 10.0, "Contabilizado", "Processado e Pago", "SEI-040002/000001/2024"),
        ("2", "90000000000190", "180100", 10.0, "Contabilizado", "Processado e Pago", "SEI-040002/000002/2024"),
        ("3", "90000000000190", "180100", 10.0, "Contabilizado", "Processado e Pago", "SEI-040002/000003/2024"),
        ("4", "91000000000191", "296100", 70.0, "Contabilizado", "Processado e Pago", "SEI-150001/000009/2025"),
        ("5", "91000000000191", "296100", 70.0, "Contabilizado", "Processado e Pago", "SEI-150001/000009/2025"),
        # OB anulada não conta: nem pagamento do CNPJ, nem índice de prefixo
        ("6", "92000000000192", "999900", 9e9, "Anulado", "", "SEI-770001/000001/2024"),
        ("7", "92000000000192", "999900", 9e9, "Anulado", "", "SEI-770001/000002/2024"),
        ("8", "92000000000192", "999900", 9e9, "Anulado", "", "SEI-770001/000003/2024"),
        # outro estabelecimento (filial 0002) da empresa 93000000 recebeu; a matriz 0001 não
        ("9", "93000000000293", "180100", 5.0, "Contabilizado", "Processado e Pago", "0"),
    ])
    c.execute("CREATE TABLE pcrj_despesa (credor_documento TEXT, orgao TEXT, pago REAL, exercicio INTEGER)")
    c.executemany("INSERT INTO pcrj_despesa VALUES (?,?,?,?)", [
        ("94000000000194", "Secretaria Municipal de Saúde", 300.0, 2022),
        ("94000000000194", "Secretaria Municipal de Educação", 50.0, 2023),
        ("95000000000195", "Secretaria Municipal de Saúde", 0.0, 2022),            # só empenho: pago 0 não é pagamento
    ])
    c.execute("CREATE TABLE ordens_bancarias (ug_codigo TEXT, ug_nome TEXT, favorecido_cpf TEXT)")
    c.execute("INSERT INTO ordens_bancarias VALUES ('180100', 'SEEDUC', '96000000000196')")
    c.execute("CREATE TABLE pncp_resultado (fornecedor_cnpj TEXT, fornecedor_nome TEXT)")
    return c


def test_sem_orgao_resolvido_na_fonte_e_resto_com_motivo():
    from compliance_agent import cores_orgaos
    radar = {"ok": True, "achados": [{"cnpj": c, "nome": n, "score": 30, "sinais": []} for c, n in (
        ("90000000000190", "PAGA LTDA"), ("94000000000194", "MUNICIPAL LTDA"), ("95000000000195", "SO EMPENHO LTDA"),
        ("93000000000193", "MATRIZ LTDA"), ("96000000000196", "TFE LTDA"))]}
    casos = [
        {"slug": "proc", "titulo": "P", "cnpjs": [], "sei": ["SEI-150001/000009/2025", "SEI-040002/000777/2024"]},
        {"slug": "pref", "titulo": "Q", "cnpjs": [], "sei": ["SEI-040002/000555/2026"]},
        {"slug": "decl", "titulo": "D", "cnpjs": [], "sei": [], "ug": "133100"},
        {"slug": "nada", "titulo": "N", "cnpjs": [], "sei": []},
        {"slug": "anul", "titulo": "A", "cnpjs": [], "sei": ["SEI-770001/000004/2024"]},
        {"slug": "fed", "titulo": "F", "cnpjs": ["97000000000197"], "sei": ["SEI-040002/000556/2026"], "esfera": "federal"},
    ]
    g = montar(casos, _con_orgao(), radar, None)
    ids = {n["id"]: n for n in g["nos"]}
    # positivo (a): OB paga no SIAFE → UG; secundários expostos no nó
    assert ids["cnpj:90000000000190"]["cl"] == "ug:180100" and ids["cnpj:90000000000190"]["orgs"][0]["via"] == "OB"
    # positivo: pago pela PCRJ → órgão municipal que mais pagou, o outro fica como secundário; aresta diz o valor
    m = ids["cnpj:94000000000194"]
    assert m["cl"].startswith("pcrj:") and "SAUDE" in m["cl"] and len(m["orgs"]) == 2 and m["orgs"][0]["pago"] == 300.0
    # positivo (b/c): OB do próprio processo vence o prefixo; sem OB do processo, o prefixo do índice dá a UG
    assert ids["caso:proc"]["cl"] == "ug:296100" and "OB do processo" in ids["caso:proc"]["via"]
    assert ids["caso:pref"]["cl"] == "ug:180100" and "prefixo SEI" in ids["caso:pref"]["via"]
    assert ids["caso:decl"]["cl"] == "ug:133100"                       # UG declarada no frontmatter vence
    # negativos: nada é chutado — cada sobra carrega o MOTIVO medido, em cinza
    assert ids["cnpj:95000000000195"]["cl"] == "sem:sem_ob"            # empenho com pago 0 não é pagamento
    assert ids["cnpj:93000000000193"]["cl"] == "sem:outra_raiz"        # a filial recebeu, não este CNPJ
    assert ids["cnpj:96000000000196"]["cl"] == "sem:so_tfe"
    assert ids["caso:nada"]["cl"] == "sem:dossie_sem_sei_cnpj" and ids["caso:nada"]["mot"] == "nota sem SEI nem CNPJ completo"
    assert ids["caso:anul"]["cl"] == "sem:dossie_sei_sem_ug"           # prefixo só com OB anulada não entra no índice
    assert ids["caso:fed"]["cl"] == "sem:dossie_esfera"                # esfera federal não ganha UG do Estado pelo SEI
    assert all(n["l"] != "Sem órgão identificado na base" for n in g["nos"])
    assert g["resumo"]["sem_orgao"]["fornecedores"] == {"sem:sem_ob": 2, "sem:outra_raiz": 1, "sem:so_tfe": 1}
    lv = {n["id"]: n for n in leve(g)["nos"]}
    assert lv["cnpj:95000000000195"]["cor"] == cores_orgaos.cor("") and lv["cnpj:95000000000195"]["mot"]
    assert lv["cnpj:90000000000190"]["cor"] == cores_orgaos.cor("180100")   # resolvido herda a cor do órgão


def test_notas_do_vault_resolvidas_por_sei_e_cnpj(tmp_path, monkeypatch):
    from compliance_agent import orgao_fonte
    monkeypatch.setattr(orgao_fonte, "CACHE", tmp_path / "prefixo.json")      # nunca a cópia real em data/cache
    db = tmp_path / "c.db"
    src = _con_orgao()
    src.commit()                                                          # backup espera a transação aberta
    dst = sqlite3.connect(db)
    src.backup(dst)
    dst.close()
    fm = "---\ntipo: caso\n{}tags: [caso, orgao/indeterminado]\n---\n"
    notas = {
        "proc": fm.format("") + "processo SEI-150001/000009/2025\n",
        "pref": fm.format("") + "ver SEI-040002/000555/2026\n",
        "cnpj": fm.format("") + "PAGA LTDA (90.000.000/0001-90)\n",
        "decl": fm.format("entidade: INEA (UG 243200)\n"),
        "040002_000444_2024": fm.format(""),                       # nota de processo: o número está no nome do arquivo
        "pcrj": fm.format("orgao: Prefeitura do Rio\n") + "PAGA LTDA (90.000.000/0001-90)\n",
        "nada": fm.format("") + "texto sem número\n",
        "anul": fm.format("") + "SEI-770001/000004/2024 e 92.000.000/0001-92\n",
    }
    r = orgao_fonte.resolver_notas(notas, db)
    assert {k: r[k]["ug"] for k in ("proc", "pref", "cnpj", "decl", "040002_000444_2024")} == {
        "proc": "296100", "pref": "180100", "cnpj": "180100", "decl": "243200", "040002_000444_2024": "180100"}
    assert r["pcrj"] == {"ug": "", "motivo": "esfera"}               # Prefeitura não ganha UG do Estado pelo CNPJ
    assert r["nada"] == {"ug": "", "motivo": "sem_sei_cnpj"}
    assert r["anul"] == {"ug": "", "motivo": "sei_e_cnpj"}          # OB anulada não resolve nada
