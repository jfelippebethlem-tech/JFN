# -*- coding: utf-8 -*-
"""Testes da visão de sanções do TCE-RJ por UG (auto-matcher + overrides + depuração).

Sem rede; SQLite temporário p/ as linhas do TCE. O auto-matcher lê o `data/ug_canonico.json` real (rodar da raiz).
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from compliance_agent.reporting import penalidades_tce_view as pv


@pytest.fixture()
def db(tmp_path: Path) -> Path:
    p = tmp_path / "t.db"
    con = sqlite3.connect(p)
    con.execute("""CREATE TABLE penalidades_tcerj (
        id TEXT, processo TEXT, ano_condenacao INT, tipo TEXT, valor REAL, condenacao TEXT,
        tipo_ente TEXT, orgao TEXT, grupo_natureza TEXT, data_sessao TEXT, ingerido_em TEXT)""")
    linhas = [
        ("1", "100036-1/2018", 2022, "DEBITO", 194161.27, "253/2022-2", "ESTADUAL", "SEC EST SAÚDE", "TOMADA DE CONTAS", "2022-03-02T00:00:00"),
        ("2", "100036-1/2018", 2022, "MULTA", 5824.84, "255/2022-2", "ESTADUAL", "SEC EST SAÚDE", "TOMADA DE CONTAS", "2022-03-02T00:00:00"),
        ("3", "200000-0/2021", 2023, "MULTA", 3000.0, "789/2023-0", "ESTADUAL", "SEC EST SAÚDE", "PRESTAÇÃO DE CONTAS", "2023-04-24T00:00:00"),
        # TJ — a sanção é do TRIBUNAL, NÃO do Fundo Especial do TJ (036100). Discriminador de tipo deve acertar.
        ("4", "300000-0/2020", 2021, "DEBITO", 170554.39, "1/2021-0", "ESTADUAL", "TRIBUNAL DE JUSTICA DO ESTADO RJ", "PRESTAÇÃO DE CONTAS", "2021-01-01T00:00:00"),
    ]
    con.executemany("INSERT INTO penalidades_tcerj (id,processo,ano_condenacao,tipo,valor,condenacao,tipo_ente,orgao,grupo_natureza,data_sessao) VALUES (?,?,?,?,?,?,?,?,?,?)", linhas)
    con.commit(); con.close()
    return p


# ───────── auto-matcher e resolução ─────────
def test_overrides_bem_formados():
    for orgao, (ugs, conf, nota) in pv.OVERRIDES.items():
        assert conf in ("alta", "media")
        assert nota
        if ugs is None:  # sem âncora (ex.: CEDAE)
            continue
        for u in ugs:
            assert u.isdigit() and len(u) == 6, f"UG inválida {u} em {orgao}"


def test_tipo_discrimina_orgao_de_fundo():
    """O bug clássico: a sanção do TRIBUNAL não pode cair no FUNDO ESPECIAL do TJ (036100)."""
    r = pv.resolver("TRIBUNAL DE JUSTICA DO ESTADO RJ")
    assert "030100" in r["ug_codes"]      # Tribunal de Justica
    assert "036100" not in r["ug_codes"]  # NÃO o Fundo Especial do TJ


def test_auto_match_secretaria_e_acronimo():
    assert "290100" in pv.resolver("SEC EST SAÚDE")["ug_codes"]
    assert "263100" in pv.resolver("DETRAN-DEPARTAMENTO DE TRÂNSITO")["ug_codes"]
    assert "403200" in pv.resolver("PRODERJ - CENTRO TECN DA INF E COMUNI RJ")["ug_codes"]


def test_override_vence_e_marca_historico():
    r = pv.resolver("SEC EST INFRAESTRUTURA E OBRAS (EXTINTA)")
    assert set(r["ug_codes"]) == {"070100", "530100"}
    assert r["fonte"] == "override"
    assert r["historico"] is True  # marcador (EXTINTA)


def test_sem_ancora_nao_quebra():
    r = pv.resolver("CEDAE-COMPANHIA ESTADUAL AGUAS E ESGOTOS")
    assert r["ug_codes"] == []
    assert r["sem_ancora"] is True


# ───────── agregação por UG ─────────
def test_por_ug_saude_agrega_so_o_orgao_certo(db: Path):
    agg = pv.por_ug("290100", db_path=db)  # Secretaria de Estado de Saude
    assert agg["ok"]
    assert agg["n_condenacoes"] == 3
    assert agg["n_processos"] == 2
    assert agg["valor_total"] == pytest.approx(194161.27 + 5824.84 + 3000.0)
    assert agg["por_tipo"]["DEBITO"]["valor"] == pytest.approx(194161.27)
    assert agg["itens"][0]["valor"] == pytest.approx(194161.27)  # ordenado desc


def test_por_ug_tj_no_tribunal_nao_no_fundo(db: Path):
    assert pv.por_ug("030100", db_path=db)["n_condenacoes"] == 1   # Tribunal
    assert pv.por_ug("036100", db_path=db)["ok"] is False          # Fundo Especial do TJ: nada


def test_ug_sem_mapeamento_vazio(db: Path):
    assert pv.por_ug("999999", db_path=db)["ok"] is False


def test_dedup_solidaria_nao_infla_erario(tmp_path: Path):
    """Responsabilidade solidária (mesmo débito a N responsáveis) = N linhas → valor contado UMA vez."""
    p = tmp_path / "s.db"
    con = sqlite3.connect(p)
    con.execute("""CREATE TABLE penalidades_tcerj (id TEXT, processo TEXT, ano_condenacao INT, tipo TEXT,
        valor REAL, condenacao TEXT, tipo_ente TEXT, orgao TEXT, grupo_natureza TEXT, data_sessao TEXT)""")
    # mesmo débito R$ 5.117.670,88 imputado a 3 responsáveis (3 linhas, condenacao diferente)
    base = ("102605-9/2020", 2025, "DEBITO", 5117670.88, "ESTADUAL", "SEC EST SAÚDE", "AUDITORIA", "2025-09-01")
    for i in (1, 2, 3):
        con.execute("INSERT INTO penalidades_tcerj (id,processo,ano_condenacao,tipo,valor,condenacao,tipo_ente,orgao,grupo_natureza,data_sessao) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?)", (str(i), base[0], base[1], base[2], base[3], f"253/2025-{i}", base[4], base[5], base[6], base[7]))
    con.commit(); con.close()
    agg = pv.por_ug("290100", db_path=p)
    assert agg["n_condenacoes"] == 3           # 3 responsáveis julgados
    assert agg["n_eventos"] == 1               # 1 débito distinto
    assert agg["valor_total"] == pytest.approx(5117670.88)  # contado UMA vez (não 3×)
    assert agg["tem_solidaria"] is True
    assert agg["itens"][0]["n_resp"] == 3
    assert "solidária" in pv.leitura(agg, "a Saúde").lower()


# ───────── depuração / auto-auditoria ─────────
def test_depurar_sem_match_zero():
    """Nenhum órgão-TCE pode ficar sem âncora além do CEDAE (sem UG no canônico)."""
    d = pv.depurar()
    assert d["ok"]
    assert d["resumo"]["sem_match"] == 0
    assert d["resumo"]["sem_ancora"] == 1  # só CEDAE


# ───────── leitura ─────────
def test_leitura_vazia_honesta():
    txt = pv.leitura(pv._vazio(), "o órgão X")
    assert "INDISPONÍVEL" in txt and "não equivale" in txt.lower()


def test_leitura_cita_debito_multa_e_fato_julgado(db: Path):
    txt = pv.leitura(pv.por_ug("290100", db_path=db), "a Secretaria de Saúde")
    assert "DÉBITO" in txt and "MULTA" in txt
    assert "fato julgado" in txt.lower()


# ───────── P2.4: Sec. das Cidades (UG 660100) resolve, e sem_sancao ≠ INDISPONÍVEL ─────────
def test_cidades_660100_no_override():
    """A pasta combinada infra+cidades imputa sanções tambén à sucessora Sec. das Cidades (UG 660100)."""
    ugs, conf, nota = pv.OVERRIDES["SEC EST INFRAESTRUTURA E CIDADES"]
    assert "660100" in ugs  # antes só 070100/530100 → 660100 caía em INDISPONÍVEL por join


def _db_cidades(tmp_path: Path) -> Path:
    p = tmp_path / "cid.db"
    con = sqlite3.connect(p)
    con.execute("""CREATE TABLE penalidades_tcerj (
        id TEXT, processo TEXT, ano_condenacao INT, tipo TEXT, valor REAL, condenacao TEXT,
        tipo_ente TEXT, orgao TEXT, grupo_natureza TEXT, data_sessao TEXT, ingerido_em TEXT)""")
    con.execute("INSERT INTO penalidades_tcerj (id,processo,ano_condenacao,tipo,valor,condenacao,tipo_ente,orgao,grupo_natureza,data_sessao) VALUES (?,?,?,?,?,?,?,?,?,?)",
                ("9", "777/2025", 2025, "DEBITO", 50000.0, "1/2025", "ESTADUAL", "SEC EST INFRAESTRUTURA E CIDADES", "PRESTAÇÃO DE CONTAS", "2025-05-01T00:00:00"))
    con.commit(); con.close()
    return p


def test_por_ug_660100_resolve_sancao_real(tmp_path: Path):
    """UG 660100 deixa de cair em INDISPONÍVEL: resolve p/ a pasta infra+cidades e traz a sanção real."""
    agg = pv.por_ug("660100", db_path=_db_cidades(tmp_path))
    assert agg["ok"] is True
    assert "SEC EST INFRAESTRUTURA E CIDADES" in agg["orgaos_tce"]
    assert agg["valor_total"] == 50000.0


def test_sem_sancao_distingue_de_indisponivel(tmp_path: Path):
    """UG que RESOLVE p/ órgão-TCE mas sem condenação → 'sem sanção' (limpo de fato), NÃO INDISPONÍVEL."""
    p = tmp_path / "vazio.db"
    con = sqlite3.connect(p)
    con.execute("""CREATE TABLE penalidades_tcerj (
        id TEXT, processo TEXT, ano_condenacao INT, tipo TEXT, valor REAL, condenacao TEXT,
        tipo_ente TEXT, orgao TEXT, grupo_natureza TEXT, data_sessao TEXT, ingerido_em TEXT)""")
    # tabela existe, mas SEM linha p/ a pasta de Cidades
    con.execute("INSERT INTO penalidades_tcerj (id,orgao,tipo,valor) VALUES ('1','SEC EST SAÚDE','MULTA',10.0)")
    con.commit(); con.close()
    agg = pv.por_ug("660100", db_path=p)
    assert agg["ok"] is False
    assert agg["motivo"] == "sem_sancao"          # resolveu o join, só não há condenação
    assert agg["orgaos_tce"]                       # registra a quem o join chegou
    txt = pv.leitura(agg, "Secretaria de Estado das Cidades")
    assert "Sem sanção" in txt and "INDISPONÍVEL" not in txt


def test_ug_inexistente_e_indisponivel(tmp_path: Path):
    """UG sem nenhum órgão-TCE correspondente → INDISPONÍVEL (join não estabelecido)."""
    p = tmp_path / "x.db"
    con = sqlite3.connect(p)
    con.execute("""CREATE TABLE penalidades_tcerj (
        id TEXT, processo TEXT, ano_condenacao INT, tipo TEXT, valor REAL, condenacao TEXT,
        tipo_ente TEXT, orgao TEXT, grupo_natureza TEXT, data_sessao TEXT, ingerido_em TEXT)""")
    con.execute("INSERT INTO penalidades_tcerj (id,orgao,tipo,valor) VALUES ('1','SEC EST SAÚDE','MULTA',10.0)")
    con.commit(); con.close()
    agg = pv.por_ug("999999", db_path=p)
    assert agg["ok"] is False and agg["motivo"] == "indisponivel"
    assert "INDISPONÍVEL" in pv.leitura(agg, "órgão fantasma")
