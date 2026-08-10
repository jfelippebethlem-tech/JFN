# -*- coding: utf-8 -*-
"""Um consórcio por certame — o mesmo núcleo em veículos diferentes.

A concentração por grupo já dizia que a UG 660100 tinha 57,5% em sete CNPJs, mas não dizia COMO.
O quadro societário disse: os "concorrentes" são consórcios constituídos um por certame, com o
MESMO par de empresas dentro e o MESMO administrador. Medido em 2026-08-09 nos 36 consórcios que
receberam OB: cinco pessoas administram mais de um, e a primeira soma **R$ 417,9 mi em seis
veículos, em três unidades gestoras** — alcance que o recorte por UG, sozinho, não mostra.

Consórcio é lícito (art. 15 da Lei 14.133) e administrar vários também. O que se mede é a
REPETIÇÃO, e o núcleo comum é o que a torna legível.
"""
from __future__ import annotations

import sqlite3

import pytest

import tools.screen_consorcio_veiculo as S


@pytest.fixture()
def db(tmp_path):
    p = tmp_path / "c.db"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE ob_orcamentaria_siafe (credor TEXT, nome_credor TEXT, valor REAL,"
                " status TEXT, ug_emitente TEXT)")
    con.execute("CREATE TABLE socios_receita (cnpj_basico TEXT, nome_socio TEXT,"
                " qualificacao_txt TEXT)")

    def consorcio(raiz, nome, valor, ug, adm, membros, status="Contabilizado"):
        con.execute("INSERT INTO ob_orcamentaria_siafe VALUES (?,?,?,?,?)",
                    (raiz + "000100", nome, valor, status, ug))
        con.execute("INSERT INTO socios_receita VALUES (?,?,?)", (raiz, adm, "Administrador"))
        for m in membros:
            con.execute("INSERT INTO socios_receita VALUES (?,?,?)", (raiz, m, "Sociedade Consorciada"))

    # o mesmo administrador em três veículos, com DUAS empresas em todos e a terceira variando
    consorcio("11111111", "CONSORCIO ALFA", 100_000_000.0, "660100", "FILIPE VIEIRA",
              ["F P VIEIRA", "R C VIEIRA", "METROPOLITANA"])
    consorcio("22222222", "CONSORCIO BETA", 50_000_000.0, "660100", "FILIPE VIEIRA",
              ["F P VIEIRA", "R C VIEIRA", "JEED"])
    consorcio("33333333", "CONSORCIO GAMA", 5_000_000.0, "530100", "FILIPE VIEIRA",
              ["F P VIEIRA", "R C VIEIRA"])
    # administrador de UM só — não é repetição
    consorcio("44444444", "CONSORCIO SOZINHO", 80_000_000.0, "240200", "OUTRO ADM", ["X LTDA"])
    # dois veículos, mas valor irrisório
    consorcio("55555555", "CONSORCIO MIUDO I", 1_000.0, "010100", "ADM PEQUENO", ["Y LTDA"])
    consorcio("66666666", "CONSORCIO MIUDO II", 2_000.0, "010100", "ADM PEQUENO", ["Y LTDA"])
    # OB cancelada não conta como pagamento
    consorcio("77777777", "CONSORCIO CANCELADO I", 90_000_000.0, "020100", "ADM FANTASMA",
              ["Z LTDA"], status="Excluído")
    consorcio("88888888", "CONSORCIO CANCELADO II", 90_000_000.0, "020100", "ADM FANTASMA",
              ["Z LTDA"], status="Excluído")
    con.commit()
    con.close()
    return str(p)


def test_pega_o_administrador_de_varios_veiculos(db):
    r = {x["administrador"]: x for x in S.medir(db=db)}
    assert "FILIPE VIEIRA" in r
    assert r["FILIPE VIEIRA"]["n_consorcios"] == 3
    assert r["FILIPE VIEIRA"]["total"] == pytest.approx(155_000_000.0)


def test_nucleo_comum_e_a_intersecao(db):
    """O que revela 'um veículo por certame' é a empresa que está em TODOS."""
    r = {x["administrador"]: x for x in S.medir(db=db)}
    assert r["FILIPE VIEIRA"]["nucleo_comum"] == ["F P VIEIRA", "R C VIEIRA"]
    assert "METROPOLITANA" not in r["FILIPE VIEIRA"]["nucleo_comum"]


def test_alcance_em_varias_UGs_sai_declarado(db):
    r = {x["administrador"]: x for x in S.medir(db=db)}
    assert r["FILIPE VIEIRA"]["n_ugs"] == 2 and r["FILIPE VIEIRA"]["ugs"] == ["530100", "660100"]


def test_administrador_de_um_so_nao_entra(db):
    assert "OUTRO ADM" not in {x["administrador"] for x in S.medir(db=db)}


def test_piso_de_valor(db):
    assert "ADM PEQUENO" not in {x["administrador"] for x in S.medir(db=db)}
    assert "ADM PEQUENO" in {x["administrador"] for x in S.medir(db=db, min_valor=100.0)}


def test_ob_cancelada_nao_conta(db):
    """R$ 180 mi em OB Excluída não podem promover um administrador a achado."""
    assert "ADM FANTASMA" not in {x["administrador"] for x in S.medir(db=db, min_valor=1.0)}


def test_ordena_por_numero_de_veiculos_depois_valor(db):
    itens = S.medir(db=db, min_valor=100.0)
    assert itens[0]["administrador"] == "FILIPE VIEIRA"


def test_base_sem_as_tabelas_devolve_vazio(tmp_path):
    p = tmp_path / "vazio.db"
    sqlite3.connect(p).close()
    assert S.medir(db=str(p)) == []


def test_ressalva_diz_que_consorcio_e_licito():
    assert "LÍCITA" in S.RESSALVA and "art. 15" in S.RESSALVA
    assert "APARENTE" in S.RESSALVA


def test_exposicao_direta_entra_no_total(db):
    """Ler só os consórcios subestima o comando: o 2º da lista real tem R$ 243,5 mi em empresas
    que administra FORA de consórcio, contra R$ 107 mi dentro deles."""
    con = sqlite3.connect(db)
    con.execute("INSERT INTO ob_orcamentaria_siafe VALUES "
                "('99999999000199','LAND SERVICOS LTDA',60000000.0,'Contabilizado','404400')")
    con.execute("INSERT INTO socios_receita VALUES ('99999999','FILIPE VIEIRA','Administrador')")
    con.commit(); con.close()
    r = {x["administrador"]: x for x in S.medir(db=db)}
    fv = r["FILIPE VIEIRA"]
    assert fv["total"] == pytest.approx(155_000_000.0), "o total dos VEÍCULOS não muda"
    assert fv["total_com_diretas"] == pytest.approx(215_000_000.0)
    assert fv["empresas_diretas"][0]["nome"] == "LAND SERVICOS LTDA"


def test_consorcio_nao_conta_como_empresa_direta(db):
    """O veículo já está no total dos consórcios — contá-lo de novo dobraria o valor."""
    r = {x["administrador"]: x for x in S.medir(db=db)}
    nomes = {d["nome"] for d in r["FILIPE VIEIRA"]["empresas_diretas"]}
    assert not any(n.startswith("CONSORCIO") for n in nomes)
