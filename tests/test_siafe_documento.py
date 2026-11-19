# -*- coding: utf-8 -*-
"""Ingestão da Nota de Empenho: coluna pelo NOME do cabeçalho, nunca pela posição."""
import sqlite3

from compliance_agent import siafe_documento as N

_HEADER = ["Número", "UG Emitente", "Data Emissão", "Doc. Alt.", "Tipo Alt.", "Status", "Credor", "Nome do Credor",
           "Fonte", "Natureza", "Precatório", "Processo", "Tipo de reconhecimento de passivo",
           "Assinatura Eletrônica", "Valor"]
_LINHA = ["2026NE03532", "123400", "27/10/2026", "", "", "Contabilizado", "CG0006025", "RIOPREV/PENSIONISTA",
          "801", "319003", "Não", "SEI-040014/000956/2026", "Passivo a ser reconhecido", "Não Solicitado",
          "100.830.023,49"]


def test_ingere_pelo_nome_do_cabecalho(tmp_path):
    db = tmp_path / "c.db"
    r = N.ingerir(2026, _HEADER, [_LINHA, ["Total", "", "", ""]], db=db)
    assert r["ok"] and r["ingeridas"] == 1
    row = sqlite3.connect(db).execute("SELECT numero, fonte, natureza, processo, tipo_reconhecimento_passivo, "
                                      "valor FROM ne_siafe").fetchone()
    assert row == ("2026NE03532", "801", "319003", "SEI-040014/000956/2026", "Passivo a ser reconhecido",
                   100830023.49)


def test_ordem_das_colunas_diferente_nao_desloca(tmp_path):
    db = tmp_path / "c.db"
    ordem = list(range(len(_HEADER)))[::-1]
    N.ingerir(2026, [_HEADER[i] for i in ordem], [[_LINHA[i] for i in ordem]], db=db)
    assert sqlite3.connect(db).execute("SELECT fonte, valor FROM ne_siafe").fetchone() == ("801", 100830023.49)


def test_cabecalho_sem_numero_nao_grava_nada(tmp_path):
    assert N.ingerir(2026, ["Fonte", "Valor"], [["801", "1,00"]], db=tmp_path / "c.db")["ok"] is False


def test_ne_com_sufixo_p_e_aceita(tmp_path):
    db = tmp_path / "c.db"
    linha = list(_LINHA)
    linha[0] = "2026NE00744P"
    assert N.ingerir(2026, _HEADER, [linha], db=db)["ingeridas"] == 1


def test_ano_da_ne_vem_do_numero_e_nao_da_consulta(tmp_path):
    """A tela consultada em 2025 lista RP de anos anteriores: a NE de 2002 não é empenho de 2025."""
    db = tmp_path / "c.db"
    linha = list(_LINHA)
    linha[0] = "2002NE00011"
    N.ingerir(2025, _HEADER, [linha], db=db)
    assert sqlite3.connect(db).execute("SELECT exercicio, ano_ne FROM ne_siafe").fetchone() == (2025, 2002)


_HEADER_NL = ["Número", "UG Emitente", "Data Emissão", "Doc. Alt.", "Tipo Alt.", "Status", "NE", "NL Rec.",
              "Status Comp.", "Credor", "Nome do Credor", "GD", "Precatório", "Processo", "Valor Retido",
              "Assinatura Eletrônica", "Valor"]


def test_nl_grava_a_ne_vinculada_e_o_valor_retido(tmp_path):
    db = tmp_path / "c.db"
    linha = ["2026NL04226", "123400", "27/10/2026", "", "", "Contabilizado", "2026NE03532", "",
             "Passivo reconhecido e Liquidado", "CG0006025", "RIOPREV/PENSIONISTA", "", "Não",
             "SEI-040014/000956/2026", "16.320.192,87", "Não Solicitado", "100.830.023,49"]
    r = N.ingerir(2026, _HEADER_NL, [linha], db=db, tipo="NL")
    assert r["ingeridas"] == 1
    assert sqlite3.connect(db).execute("SELECT ne, ano_nl, valor_retido, valor, status_comp FROM nl_siafe").fetchone() \
        == ("2026NE03532", 2026, 16320192.87, 100830023.49, "Passivo reconhecido e Liquidado")


def test_numero_de_ne_nao_entra_como_nl(tmp_path):
    db = tmp_path / "c.db"
    linha = ["2026NE03532"] + [""] * 16
    assert N.ingerir(2026, _HEADER_NL, [linha], db=db, tipo="NL")["ingeridas"] == 0


def test_limite_decidido_pelo_rotulo_e_nao_pelo_id():
    """NE/NL: "Limite de 1000 registros" marcado = limite ATIVO (166100 parou em 1.000 achando o contrário)."""
    assert N._acao_limite("Limite de 1000 registros.", True) == "clicar"
    assert N._acao_limite("Limite de 1000 registros.", False) == "nada"
    assert N._acao_limite("Remover limite", False) == "clicar"
    assert N._acao_limite("Remover limite", True) == "nada"
    assert N._acao_limite("", True) == "desconhecido"


def test_fatia_no_teto_subdivide_ate_tres_digitos():
    assert N._subdividir("2025NE0", 1000, len("2025NE")) == [f"2025NE0{d}" for d in range(10)]
    assert N._subdividir("2025NE0", 400, len("2025NE")) == []
    assert N._subdividir("2025NE012", 1000, len("2025NE")) == []       # profundidade máxima: declara capada


def test_navegacao_tenta_de_novo_quando_o_menu_nao_montou(monkeypatch):
    import asyncio
    chamadas = []

    async def uma_vez(pg, tela):
        chamadas.append(tela)
        return len(chamadas) == 3

    class _Pg:
        async def wait_for_timeout(self, ms):
            return None
    monkeypatch.setattr(N, "_ir_para_uma_vez", uma_vez)
    assert asyncio.run(N._ir_para(_Pg(), "Nota de Empenho")) is True and len(chamadas) == 3


def test_fatia_cujas_linhas_nao_casam_o_prefixo_e_filtro_que_nao_aplicou():
    """04/11/2026, NL 166100: o filtro de Número não pegou e cada fatia devolveu a mesma página (974 linhas, abaixo
    do limiar) — o coletor aceitou como completo."""
    linhas = [["2025NL04500"], ["2025NL04501"], ["2025NL04502"]]
    assert N._fatia_casa(linhas, "2025NL0", N.TIPOS["NL"]["re"]) is True       # 045xx começa mesmo com 2025NL0
    assert N._fatia_casa(linhas, "2025NL1", N.TIPOS["NL"]["re"]) is False      # filtro não aplicou
    assert N._fatia_casa(linhas, "2025NL045", N.TIPOS["NL"]["re"]) is True
    assert N._fatia_casa([], "2025NL9", N.TIPOS["NL"]["re"]) is True           # vazio é aceitável (fim da série)


def test_nl_so_e_completa_se_cobre_as_nl_que_as_ob_citam(tmp_path):
    db = tmp_path / "c.db"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE ob_orcamentaria_siafe(ug_emitente,exercicio,status,nl)")
    c.executemany("INSERT INTO ob_orcamentaria_siafe VALUES ('166100',2025,'Contabilizado',?)",
                  [(f"2025NL{i:05d}",) for i in range(100)])
    c.commit()
    c.close()
    N.ingerir(2025, _HEADER_NL, [[f"2025NL{i:05d}", "166100"] + [""] * 15 for i in range(40)], db=db, tipo="NL")
    assert N.cobertura_pela_ob("166100", 2025, db=db) == 0.4


def test_fatia_com_974_linhas_ainda_e_teto():
    """A rolagem virtual perde algumas linhas: 2025NL0 tinha ~5.400, o servidor cortou em 1.000 e vieram 974 —
    um abaixo do limiar antigo (975), e nada foi subdividido."""
    assert N._subdividir("2025NL0", 974, len("2025NL")) == [f"2025NL0{d}" for d in range(10)]


def test_prazo_e_conferido_entre_fatias(monkeypatch):
    monkeypatch.setattr(N.time, "strftime", lambda fmt: "04:41")
    assert N._passou("04:40") is True and N._passou(None) is False


# ── 19/11/2026: incremental, prova de completude por fatia e controle positivo da NE pela NL ─────────────────────

def test_prefixos_incrementais_cobrem_tudo_acima_do_ultimo_sem_sobrepor():
    p = N.prefixos_incrementais("2026NL", "2026NL01234")
    assert p[:3] == ["2026NL012", "2026NL013", "2026NL014"] and p[-1] == "2026NL9"
    # cobertura: todo número ≥ 01200 casa exatamente UM prefixo; abaixo, nenhum
    for n in (1200, 1234, 1299, 1300, 1999, 2000, 45678, 99999):
        assert sum(f"2026NL{n:05d}".startswith(x) for x in p) == 1
    for n in (0, 999, 1199):
        assert not any(f"2026NL{n:05d}".startswith(x) for x in p)
    assert N.prefixos_incrementais("2026NL", "lixo") == [f"2026NL{d}" for d in range(10)]


def test_fatia_registra_prova_e_marca_a_que_encostou_no_teto(tmp_path):
    db = tmp_path / "c.db"
    N.registrar_fatia("NL", "296100", 2025, "2025NL012", 950, db=db)
    N.registrar_fatia("NL", "296100", 2025, "2025NL013", 12, db=db)
    rows = sqlite3.connect(db).execute("SELECT prefixo, linhas, no_teto FROM siafe_documento_fatia ORDER BY 1").fetchall()
    assert rows == [("2025NL012", 950, 1), ("2025NL013", 12, 0)]


def _ne_nl(db, n_ne, n_nl_citando):
    N.ingerir(2025, ["Número", "UG Emitente"], [[f"2025NE{i:05d}", "166100"] for i in range(n_ne)], db=db, tipo="NE")
    N.ingerir(2025, _HEADER_NL, [[f"2025NL{i:05d}", "166100"] + [""] * 15 for i in range(n_nl_citando)], db=db,
              tipo="NL")
    c = sqlite3.connect(db)
    c.executemany("UPDATE nl_siafe SET ne=? WHERE numero=?", [(f"2025NE{i:05d}", f"2025NL{i:05d}")
                                                               for i in range(n_nl_citando)])
    c.commit()
    c.close()


def test_ne_so_e_completa_se_cobre_as_ne_que_as_nl_citam(tmp_path):
    """Controle POSITIVO da NE: as NL citam a NE; NE coletada sem 60 das 100 citadas não é completa."""
    db = tmp_path / "c.db"
    _ne_nl(db, 40, 100)
    assert N.cobertura_ne_pela_nl("166100", 2025, db=db) == 0.4
    assert N.fechar_cobertura("NE", "166100", 2025, {"ok": True, "colhidas": 40}, db=db) is False


def test_ne_sem_nl_para_conferir_fica_completa_e_a_nl_depois_rebaixa(tmp_path):
    """NE colhida antes da NL: sem NL não há o que conferir (None ≠ 0). Quando a NL fecha completa e cita NE que
    não existem, a NE registrada completa é REBAIXADA — parcial nunca segue marcado como completo."""
    db = tmp_path / "c.db"
    N.ingerir(2025, ["Número", "UG Emitente"], [[f"2025NE{i:05d}", "166100"] for i in range(40)], db=db, tipo="NE")
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE ob_orcamentaria_siafe(numero_ob,ug_emitente,exercicio,status,nl,gd)")
    c.commit()
    c.close()
    assert N.fechar_cobertura("NE", "166100", 2025, {"ok": True, "colhidas": 40}, db=db) is True
    _ne_nl(db, 0, 100)
    r = {"ok": True, "colhidas": 100}
    assert N.fechar_cobertura("NL", "166100", 2025, r, db=db) is True
    assert r["ne_rebaixada"] is True
    assert N.ugs_completas(sqlite3.connect(db)) == set()


# ── 19/11/2026: Bloqueio Judicial (lista única, controle pela sequência do código) e DEA ────────────────────────

_HEADER_BJ = ["Código", "Código Credor", "Nome Credor", "Valor Bloqueado", "Data Bloqueio", "Data Desbloqueio",
              "Autos do Bloqueio", "Status"]


def test_bloqueio_judicial_ingere_sem_coluna_de_ug_e_confere_a_sequencia(tmp_path):
    db = tmp_path / "c.db"
    linhas = [[str(i), "07046566000101", "Fornecedor", "R$ 42.565.673,37" if i == 5 else "R$ 0,00", "03/02/2026", "",
               "", "Bloqueado"] for i in (1, 2, 3, 5)]                 # falta o 4
    r = N.ingerir(2026, _HEADER_BJ, linhas, db=db, tipo="BJ")
    assert r["ingeridas"] == 4
    row = sqlite3.connect(db).execute("SELECT ug_emitente, valor_bloqueado FROM bloqueio_judicial_siafe "
                                      "WHERE numero='5'").fetchone()
    assert row == ("TODAS", 42565673.37)
    assert N.cobertura_bj_sequencia(2026, db=db) == 0.8               # 4 de 5: buraco na sequência
    assert N.fechar_cobertura("BJ", "TODAS", 2026, {"ok": True, "colhidas": 4}, db=db) is False
    N.ingerir(2026, _HEADER_BJ, [["4", "1", "x", "R$ 0,00", "", "", "", "Bloqueado"]], db=db, tipo="BJ")
    assert N.fechar_cobertura("BJ", "TODAS", 2026, {"ok": True, "colhidas": 5}, db=db) is True


def test_dea_ingere_pela_coluna_ug_e_fatia_pelo_codigo():
    import tempfile
    from pathlib import Path
    db = Path(tempfile.mkdtemp()) / "c.db"
    cab = ["Código", "UG", "Número Termo", "Código Credor", "Status", "Documento Registro", "Documento Reconhecimento",
           "Valor"]
    r = N.ingerir(2026, cab, [["26011891", "045200", "SEI-030022/004923/20", "210700", "Reconhecido", "2026NP001153",
                               "2026NP001153", "3.350,80"]], db=db, tipo="DEA")
    assert r["ingeridas"] == 1
    assert sqlite3.connect(db).execute("SELECT ug_emitente, valor FROM dea_siafe").fetchone() == ("045200", 3350.8)
    assert N.TIPOS["DEA"]["base"](2026) == "26" and N.TIPOS["DEA"]["prop_ug"] == "UG"


def test_dea_sem_controle_positivo_nao_vira_completa(tmp_path):
    r = {"ok": True, "colhidas": 56}
    assert N.fechar_cobertura("DEA", "045200", 2026, r, db=tmp_path / "c.db") is False
    assert r["sem_controle_positivo"] is True
