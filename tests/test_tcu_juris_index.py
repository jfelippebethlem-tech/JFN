# -*- coding: utf-8 -*-
"""Índice TCU + verificador anti-alucinação de citações.

Tudo offline: monta um índice sintético em tmp_path. Nenhum teste toca a rede.
"""
import sqlite3

import pytest

from compliance_agent.knowledge import tcu_juris_index as T


@pytest.fixture()
def db(tmp_path):
    caminho = tmp_path / "tcu.db"
    con = sqlite3.connect(caminho)
    T.init_schema(con)
    con.executemany("INSERT INTO tcu_acordao VALUES (?,?,?,?,?,?,?,?,?)", [
        ("K1", 1742, 2026, "Plenário", "Licitação", "Qualificação técnica",
         "Atestado de capacidade técnica", "É irregular a exigência de atestado sem delimitação.", "art. 67"),
        ("K2", 2696, 2019, "Primeira Câmara", "Licitação", "Qualificação técnica",
         "Atestado", "É irregular exigir quantitativo superior a 50%.", "art. 30"),
        ("K3", 3100, 2022, "Plenário", "Contrato Administrativo", "Aditivo",
         "Limite", "O aditivo não pode transfigurar o objeto.", "art. 125"),
    ])
    con.execute("INSERT INTO tcu_sumula VALUES (?,?,?,?,?)",
                (292, "Compete ao TCU julgar as contas.", "Competência", "Jurisdição", "Sim"))
    con.execute("INSERT INTO tcu_fts(tcu_fts) VALUES('rebuild')")
    con.commit()
    con.close()
    return caminho


def test_limpar_tira_html_do_enunciado():
    assert T._limpar('<p class="x">É <b>irregular</b> a <a href="u">Lei</a>.</p>') == "É irregular a Lei ."


@pytest.mark.parametrize("texto,esperado", [
    ("Acórdão 1742/2026-Plenário", (1742, 2026, "Plenário")),
    ("acórdão nº 2.696/2019 - Primeira Câmara", (2696, 2019, "Primeira Câmara")),
    ("Acordao 3100/2022", (3100, 2022, None)),
    ("ACÓRDÃO 1.273/2020 — 1ª Câmara", (1273, 2020, "Primeira Câmara")),
])
def test_regex_captura_variantes_de_citacao(texto, esperado):
    r = T.verificar_citacao(texto, db="/nao/existe")[0]
    assert (r["numero"], r["ano"], r["colegiado_citado"]) == esperado


def test_exige_a_palavra_acordao_por_perto():
    """Fronteira deliberada: 'AC 3100/2022' e datas soltas NÃO são citação.

    Sem a âncora textual, qualquer 'nnnn/aaaa' de um processo administrativo viraria
    citação e o verificador encheria o parecer de ruído.
    """
    assert T.verificar_citacao("AC 3100/2022 e o ofício 55/2024", db="/nao/existe") == []


def test_confirma_citacao_real(db):
    r = T.verificar_citacao("conforme o Acórdão 1742/2026-Plenário", db=db)[0]
    assert r["status"] == "confirmado"
    assert "atestado" in r["enunciado"].lower()


def test_numero_impossivel_e_o_sinal_forte_de_alucinacao(db):
    # Plenário/2022 fecha em 3100 no acervo; com folga de 30% o teto é 4030.
    r = T.verificar_citacao("vide Acórdão 9244/2022-Plenário", db=db)[0]
    assert r["status"] == "numero_impossivel"
    assert r["teto_do_ano"] == 4030


def test_nao_confirmado_nao_e_inexistente(db):
    """Número dentro da faixa plausível mas ausente do recorte curado: dúvida, não veredito."""
    r = T.verificar_citacao("vide Acórdão 3101/2022-Plenário", db=db)[0]
    assert r["status"] == "nao_confirmado"


def test_colegiado_divergente(db):
    r = T.verificar_citacao("Acórdão 2696/2019-Plenário", db=db)[0]
    assert r["status"] == "colegiado_diverge"
    assert r["colegiado_real"] == ["Primeira Câmara"]


def test_citacao_de_outra_corte_nao_e_julgada_por_este_indice(db):
    """TCE-RJ numera até a casa das dezenas de milhares e chama o colegiado de 'Pleno'.

    Sem este recorte, toda citação do TCE-RJ viraria 'citação fabricada' — falso positivo.
    """
    r = T.verificar_citacao("TCE-RJ, Acórdão 25279/2022 — Pleno", db=db)[0]
    assert r["status"] == "fora_do_escopo"


def test_sumula_confirmada_e_inventada(db):
    res = T.verificar_citacao("Súmula TCU 292 e Súmula 999", db=db)
    por_num = {c["numero"]: c["status"] for c in res if c["tipo"] == "sumula"}
    assert por_num == {292: "confirmado", 999: "nao_confirmado"}


def test_indice_ausente_nao_mente(tmp_path):
    r = T.verificar_citacao("Acórdão 1/2020-Plenário", db=tmp_path / "nada.db")[0]
    assert r["status"] == "indice_ausente"


def test_citacoes_suspeitas_filtra_so_o_que_nao_fecha(db):
    texto = "Acórdão 1742/2026-Plenário, Acórdão 9244/2022-Plenário e Acórdão 2696/2019-Plenário"
    sus = {c["numero"] for c in T.citacoes_suspeitas(texto, db=db)}
    assert sus == {9244, 2696}


def test_busca_enunciados_por_fts_e_area(db):
    r = T.buscar_enunciados("atestado", area="Licitação", db=db)
    assert len(r) == 2
    assert all(i["area"] == "Licitação" for i in r)
    assert T.buscar_enunciados("atestado", area="Pessoal", db=db) == []


def test_fundamentar_so_cita_acordao_do_acervo(db):
    bloco = T.fundamentar("aditivo", area="Contrato Administrativo", db=db)
    assert "Acórdão 3100/2022-Plenário" in bloco
    assert T.fundamentar("assunto inexistente xyz", db=db) == ""


def test_status_indice(db):
    s = T.status_indice(db=db)
    assert s["construido"] and s["acordaos"] == 3 and s["sumulas"] == 1
