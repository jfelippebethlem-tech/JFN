

def test_coleta_interrompida_nao_para_em_numero_redondo(tmp_path):
    """O detector do teto vê "parou em 1.000". Coleta que MORREU no meio para em qualquer número.

    Medido em 2026-08-09: a UG 294200/2025 tinha 3.007 linhas — nada de redondo — e **227 das 245
    OBs que o espelho conhece para um único credor (93%) não existiam na fonte canônica**. A causa
    apareceu no log do dreno no mesmo dia: passadas que terminam em `rc=124` (timeout) gravam o que
    deu tempo e param. Varrendo assim, 7 pares truncados viram **557 parciais + 258 nunca
    coletados** — e o total do SIAFE é 21,1% das OBs do espelho.

    O teste é por IDENTIDADE (o número da OB existe do outro lado?), nunca por volume: os dois
    universos não são idênticos e há par com mais valor no SIAFE que no espelho.
    """
    import sqlite3
    from compliance_agent.reporting import cobertura_siafe as C
    p = tmp_path / "c.db"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE ob_orcamentaria_siafe (numero_ob TEXT, ug_emitente TEXT,"
                " data_emissao TEXT, valor REAL)")
    con.execute("CREATE TABLE ordens_bancarias (numero_ob TEXT, ug_codigo TEXT,"
                " data_emissao TEXT, valor REAL)")
    # par PARCIAL: o espelho tem 100 OBs, a fonte canônica só as 10 primeiras (contagem não-redonda)
    for i in range(100):
        con.execute("INSERT INTO ordens_bancarias VALUES (?,?,?,?)",
                    (f"2025OB{i:05d}", "294200", "2025-06-01", 1000.0))
        if i < 10:
            con.execute("INSERT INTO ob_orcamentaria_siafe VALUES (?,?,?,?)",
                        (f"2025OB{i:05d}", "294200", "01/06/2025", 1000.0))
    # par ÍNTEGRO: tudo o que o espelho tem está na fonte canônica
    for i in range(60):
        con.execute("INSERT INTO ordens_bancarias VALUES (?,?,?,?)",
                    (f"2025OX{i:05d}", "999999", "2025-06-01", 500.0))
        con.execute("INSERT INTO ob_orcamentaria_siafe VALUES (?,?,?,?)",
                    (f"2025OX{i:05d}", "999999", "01/06/2025", 500.0))
    con.commit()
    con.close()

    r = C.medir(db=str(p))
    por = {(x["ug"], x["exercicio"]): x for x in r["parciais"]}
    assert ("294200", "2025") in por, "coleta interrompida sem contagem redonda passou batido"
    assert por[("294200", "2025")]["estado"] == "parcial"
    assert por[("294200", "2025")]["obs_siafe"] == 10
    assert por[("294200", "2025")]["pct_ausente"] == 90.0
    assert ("999999", "2025") not in por, "par íntegro não pode ser acusado"
    assert r["pares_truncados"] == 0, "nenhum par parou em 1.000 — o outro detector não deve acender"


def test_nunca_coletado_e_rotulado_a_parte(tmp_path):
    """"Nunca visitado" e "morreu no meio" são lacunas diferentes: a segunda parece pronta."""
    import sqlite3
    from compliance_agent.reporting import cobertura_siafe as C
    p = tmp_path / "c.db"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE ob_orcamentaria_siafe (numero_ob TEXT, ug_emitente TEXT,"
                " data_emissao TEXT, valor REAL)")
    con.execute("CREATE TABLE ordens_bancarias (numero_ob TEXT, ug_codigo TEXT,"
                " data_emissao TEXT, valor REAL)")
    for i in range(80):
        con.execute("INSERT INTO ordens_bancarias VALUES (?,?,?,?)",
                    (f"2024OB{i:05d}", "010100", "2024-03-01", 100.0))
    con.commit()
    con.close()
    r = C.medir(db=str(p))
    assert r["parciais"][0]["estado"] == "nunca_coletado"
    assert r["parciais"][0]["obs_siafe"] == 0


def test_estado_do_par_e_barato_e_honesto(tmp_path):
    """`medir()` amostra ~800 pares e não cabe num pedido HTTP; a rota precisa da versão de UM par.

    Foi o que faltou quando a concentração da UG 660100 saiu com 57,5% sem avisar que **65% da
    amostra daquele ano não está na fonte canônica**. Fração só vale o que valer a base.
    """
    import sqlite3
    from compliance_agent.reporting import cobertura_siafe as C
    p = tmp_path / "c.db"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE ob_orcamentaria_siafe (numero_ob TEXT, ug_emitente TEXT,"
                " data_emissao TEXT, valor REAL)")
    con.execute("CREATE TABLE ordens_bancarias (numero_ob TEXT, ug_codigo TEXT,"
                " data_emissao TEXT, valor REAL)")
    for i in range(100):
        con.execute("INSERT INTO ordens_bancarias VALUES (?,?,?,?)",
                    (f"2025OB{i:05d}", "660100", "2025-06-01", 10.0))
        if i < 20:
            con.execute("INSERT INTO ob_orcamentaria_siafe VALUES (?,?,?,?)",
                        (f"2025OB{i:05d}", "660100", "01/06/2025", 10.0))
    for i in range(40):                                   # par COBERTO
        con.execute("INSERT INTO ordens_bancarias VALUES (?,?,?,?)",
                    (f"2024OB{i:05d}", "660100", "2024-06-01", 10.0))
        con.execute("INSERT INTO ob_orcamentaria_siafe VALUES (?,?,?,?)",
                    (f"2024OB{i:05d}", "660100", "01/06/2024", 10.0))
    con.commit()
    con.close()

    r = C.estado_do_par("660100", "2025", db=str(p))
    assert r["estado"] == "parcial" and r["pct_ausente"] == 80.0 and r["obs_siafe"] == 20
    assert C.estado_do_par("660100", "2024", db=str(p))["estado"] == "coberto"
    # sem espelho não se afirma NADA sobre cobertura — nem completa, nem incompleta
    assert C.estado_do_par("660100", "2019", db=str(p))["estado"] == "sem_referencia"
    assert C.estado_do_par("999999", "2025", db=str(p))["estado"] == "sem_referencia"
