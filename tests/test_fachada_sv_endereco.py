from tools.fachada_streetview_sweep import mesmo_endereco, pontos_em_volta


def test_rua_diferente_rejeita():
    ok, porque = mesmo_endereco("251 R. Teixeira da Silva o Was", "ALAMEDA, SANTOS, 193, CERQUEIRA CESAR, SAO PAULO")
    assert not ok and porque == "rua diferente"


def test_mesma_rua_numero_longe_rejeita():
    ok, porque = mesmo_endereco("222 Estr. São Lourenço o ==", "ESTRADA, SAO LOURENCO, 661, QUADRA06 LOTE 18")
    assert not ok and "222" in porque


def test_mesma_rua_numero_perto_aceita():
    assert mesmo_endereco("640 Estr. São Lourenço", "ESTRADA, SAO LOURENCO, 661, QUADRA06")[0]


def test_ilegivel_rejeita():
    assert not mesmo_endereco("", "RUA X, 10")[0]


def test_pontos_em_volta_25_e_camera_para_a_sede():
    pts = pontos_em_volta(-22.9, -43.2)
    assert len(pts) == 25 and pts[0][:2] == (-22.9, -43.2)
    lat, lon, h = pts[1]            # k=0: ponto ao NORTE → câmera para o SUL
    assert lat > -22.9 and h == 180.0


def test_rumo_e_distancia():
    from tools.fachada_streetview_sweep import dist_m, rumo_graus
    assert abs(rumo_graus(0, 0, 1, 0) - 0) < 0.01 and abs(rumo_graus(0, 0, 0, 1) - 90) < 0.01
    assert 105 < dist_m(-22.9, -43.2, -22.901, -43.2) < 117


def test_letreiro_bate_outro_e_sem():
    from tools.fachada_streetview_sweep import letreiro_bate
    assert letreiro_bate(["OMEGA Construtora"], "OMEGA CONSTRUTORA E SERVICOS LTDA", []) == "bate"
    assert letreiro_bate(["Megatruck Mecânica Diesel"], "OMEGA CONSTRUTORA E SERVICOS LTDA", ["Omega"]) == "outro_nome"
    assert letreiro_bate([], "X LTDA", []) == "sem_letreiro"
    # palavra genérica sozinha não basta
    assert letreiro_bate(["Construtora Brasil"], "OMEGA CONSTRUTORA LTDA", []) == "outro_nome"
