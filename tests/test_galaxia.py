import sqlite3

from compliance_agent.galaxia import montar


def _con():
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE socios_fornecedor (cnpj TEXT, razao TEXT, socio_nome_norm TEXT, socio_doc TEXT)")
    c.executemany("INSERT INTO socios_fornecedor VALUES (?,?,?,?)", [
        ("11111111000111", "ALFA LTDA", "JOAO SILVA", "***123456**"),
        ("22222222000122", "BETA LTDA", "JOAO SILVA", "***123456**"),
        ("33333333000133", "GAMA LTDA", "(sem QSA público)", ""),
    ])
    return c


CASOS = [
    {"slug": "a", "titulo": "Caso A", "nivel": 4, "cnpjs": ["11.111.111/0001-11"], "sei": ["SEI-1"], "entidade": "UG X"},
    {"slug": "b", "titulo": "Caso B", "nivel": 2, "cnpjs": ["22.222.222/0001-22"], "sei": ["SEI-1"], "entidade": "ug x"},
    {"slug": "c", "titulo": "Caso C", "nivel": 1, "cnpjs": ["33.333.333/0001-33", "123"], "sei": [], "entidade": ""},
]


def test_estrelas_planetas_e_pontes():
    g = montar(CASOS, _con())
    ids = {n["id"]: n for n in g["nos"]}
    assert {"caso:a", "caso:b", "caso:c", "cnpj:11111111000111", "sei:SEI-1", "socio:JOAO SILVA"} <= set(ids)
    assert ids["cnpj:11111111000111"]["label"] == "ALFA LTDA"
    assert "socio:(sem QSA público)" not in ids and "cnpj:123" not in ids
    ponte = [e for e in g["arestas"] if e["tipo"] == "caso_caso"]
    assert len(ponte) == 1 and {ponte[0]["source"], ponte[0]["target"]} == {"caso:a", "caso:b"}
    assert ponte[0]["motivos"] == {"socio": 1, "sei": 1, "ent": 1} and ponte[0]["peso"] == 3.0
    assert g["resumo"]["pontes_entre_casos"] == 1


def test_sem_documento_na_saida_e_sem_base():
    g = montar(CASOS, _con())
    assert "123456" not in str(g)
    g2 = montar(CASOS, None)
    assert g2["ok"] and not any(n["tipo"] == "socio" for n in g2["nos"])
