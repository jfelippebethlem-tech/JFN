# -*- coding: utf-8 -*-
"""Grupo cimentado por COMANDO ≠ grupo cimentado por coparticipação profissional.

Medido em 2026-08-09 nos dois maiores grupos do acervo, ambos legítimos como "grupo de fato":

  · UG 660100 (Cidades): 5 pontes ligam 7 CNPJs, **duas administram** — comando comum;
  · UG 294200 (FSERJ): 11 pontes ligam 8 CNPJs, **uma administra**; as outras dez são sócias de
    sociedades médicas com 17 a 110 cotistas — ser cotista de duas clínicas é a profissão.

O fecho transitivo trata os dois igual e deve mesmo (grupo de fato não exige controle declarado).
O defeito era entregar os dois com a MESMA cara: quem lê 10,3% da FSERJ ao lado de 57,5% de
Cidades imagina a mesma estrutura. Este qualificador não muda agrupamento nem HHI — muda a leitura.

E ausência de QSA nunca pode virar "não há comando": sai `indisponivel`, não `coparticipação`.
"""
from __future__ import annotations

import sqlite3

import pytest

from compliance_agent.osint.grupo_economico import cimento_do_grupo


def _base(linhas):
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE socios_receita (cnpj_basico TEXT, nome_socio TEXT,"
                " qualificacao_txt TEXT)")
    con.executemany("INSERT INTO socios_receita VALUES (?,?,?)", linhas)
    return con


CIDADES = [  # a ponte MANDA nas duas
    ("11111111", "FILIPE VIEIRA", "Administrador"),
    ("22222222", "FILIPE VIEIRA", "Administrador"),
    ("11111111", "OUTRO SOCIO", "Sócio"),
]
FSERJ = [  # a ponte só participa das duas
    ("33333333", "MEDICA COTISTA", "Sócio"),
    ("44444444", "MEDICA COTISTA", "Sócio"),
    ("33333333", "DONO DA CLINICA A", "Sócio-Administrador"),
    ("44444444", "DONO DA CLINICA B", "Sócio-Administrador"),
]


def test_comando_comum_quando_a_ponte_administra_duas():
    r = cimento_do_grupo(_base(CIDADES), ["11111111000191", "22222222000122"])
    assert r["estado"] == "medido"
    assert r["pontes_que_administram"] == 1
    assert "FILIPE VIEIRA" in r["administradores_em_comum"]
    assert r["tipo"] == "comando_comum" and "comando comum" in r["leitura"]


def test_coparticipacao_quando_ninguem_administra_duas():
    """Cada clínica tem seu próprio administrador; a ponte é uma cotista. Não é comando."""
    r = cimento_do_grupo(_base(FSERJ), ["33333333000133", "44444444000144"])
    assert r["estado"] == "medido"
    assert r["pontes"] == 1 and r["pontes_que_administram"] == 0
    assert "coparticipação" in r["leitura"]


def test_administrador_de_uma_so_nao_conta_como_comando():
    """`Sócio-Administrador` em UMA das duas não é ponte de comando — é o dono da própria empresa."""
    r = cimento_do_grupo(_base(FSERJ), ["33333333000133", "44444444000144"])
    assert "DONO DA CLINICA A" not in (r.get("administradores_em_comum") or [])


def test_qsa_ausente_e_indisponivel_nunca_coparticipacao():
    con = sqlite3.connect(":memory:")
    r = cimento_do_grupo(con, ["11111111000191", "22222222000122"])
    assert r["estado"] == "indisponivel", "sem QSA não se conclui nada sobre comando"
    assert "coparticipação" not in str(r)


def test_grupo_sem_ponte_no_qsa_tambem_e_indisponivel():
    con = _base([("11111111", "SO DESTA", "Sócio")])
    assert cimento_do_grupo(con, ["11111111000191", "99999999000199"])["estado"] == "indisponivel"


@pytest.mark.parametrize("cnpjs", ([], ["11111111000191"]))
def test_grupo_de_um_nao_tem_cimento(cnpjs):
    assert cimento_do_grupo(_base(CIDADES), cnpjs)["estado"] == "grupo_de_um"


def test_uma_ponte_de_mando_numa_teia_grande_nao_e_comando_comum():
    """FSERJ no dado real: 1 administrador em 28 pontes. Um teste de EXISTÊNCIA acendia
    'comando comum' ali igual a Cidades (2 em 5). A proporção é que separa os dois."""
    linhas = [("00000000", "MANDA NAS DUAS", "Administrador"),
              ("00000001", "MANDA NAS DUAS", "Administrador")]
    for i in range(2, 30):  # 28 cotistas ligando pares distintos, nenhuma administrando
        linhas += [(f"{i:08d}", f"COTISTA {i}", "Sócio"),
                   (f"{i + 100:08d}", f"COTISTA {i}", "Sócio")]
    cnpjs = [f"{i:08d}000100" for i in range(0, 30)] + [f"{i + 100:08d}000100" for i in range(2, 30)]
    r = cimento_do_grupo(_base(linhas), cnpjs)
    assert r["pontes"] == 29 and r["pontes_que_administram"] == 1
    assert r["tipo"] == "coparticipacao_com_excecao", (
        "1 ponte de mando em 29 não é estrutura de comando — é a exceção dentro da teia")
    assert r["fracao_de_comando"] < 0.05
