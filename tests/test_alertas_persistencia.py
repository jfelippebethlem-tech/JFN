# -*- coding: utf-8 -*-
"""O gravador da fila do fiscal — ele APAGA linhas, e não tinha um teste sequer.

As quatro regras que este módulo carrega: dedup por (tipo, título); nunca apagar linha com triagem
humana; detector que zerou por falha de fonte é POUPADO (INDISPONÍVEL ≠ 0); e todo alerta carrega
`created_at` (quando apareceu) e `visto_em` (última corrida que ainda o produziu). A quarta nasceu
em 2026-08-10, ao medir que os 3.082 alertas do acervo tinham `created_at` NULO — a coluna existia
e ninguém a preenchia, então a fila era atemporal justamente no dia em que a régua do art. 125
mudou.
"""
from __future__ import annotations

import sqlite3

import pytest

from compliance_agent.alertas_persistencia import gravar

SEV = {"alto": "alta", "medio": "media", "baixo": "baixa"}


@pytest.fixture()
def con():
    c = sqlite3.connect(":memory:")
    c.execute("""create table alertas (id integer primary key, tipo text, severidade text,
                 titulo text, descricao text, evidencias text, status text, created_at text)""")
    return c


def _achado(det="d1", titulo="ACHADO A", risco="alto"):
    return {"detector": det, "titulo": titulo, "descricao": "d", "risco": risco, "evidencias": {}}


def _gravar(con, achados, cobertura=None, detectores=("d1",)):
    return gravar(con, achados, cobertura or {"d1": "ok"},
                  prefixo="t", detectores=detectores, severidade=lambda r: SEV[r])


def test_regravar_atualiza_e_nao_empilha(con):
    _gravar(con, [_achado()])
    _gravar(con, [_achado()])
    assert con.execute("select count(*) from alertas").fetchone()[0] == 1


def test_carimba_created_at_e_visto_em(con):
    _gravar(con, [_achado()])
    r = con.execute("select created_at, visto_em from alertas").fetchone()
    assert r[0] and r[1], "alerta sem data é alerta que ninguém sabe se ainda vale"


def test_visto_em_avanca_na_regravacao_e_created_at_NAO(con):
    """`created_at` é quando o achado apareceu; `visto_em` é quando o detector o reconfirmou.
    Confundir os dois apaga a idade do achado a cada corrida."""
    _gravar(con, [_achado()])
    antes = con.execute("select created_at, visto_em from alertas").fetchone()
    con.execute("update alertas set visto_em='1999-01-01 00:00:00'")
    _gravar(con, [_achado()])
    depois = con.execute("select created_at, visto_em from alertas").fetchone()
    assert depois[0] == antes[0], "created_at não pode ser reescrito"
    assert depois[1] > "1999-01-01 00:00:00", "visto_em tem de avançar"


def test_base_sem_a_coluna_visto_em_segue_funcionando(con):
    """A coluna é criada por ALTER idempotente; base antiga não pode quebrar."""
    _gravar(con, [_achado()])
    assert "visto_em" in {r[1] for r in con.execute("pragma table_info(alertas)")}


def test_nunca_apaga_linha_com_triagem_humana(con):
    _gravar(con, [_achado()])
    con.execute("update alertas set status='confirmado'")
    _gravar(con, [])                       # detector não produz mais nada
    assert con.execute("select count(*) from alertas").fetchone()[0] == 1, (
        "a decisão de quem fiscaliza não é do detector para desfazer")


def test_detector_que_zerou_por_falha_de_fonte_e_poupado(con):
    """INDISPONÍVEL ≠ 0: cobertura que não começa com 'ok' significa que o detector não mediu."""
    _gravar(con, [_achado()])
    _gravar(con, [], cobertura={"d1": "erro: tabela sumiu"})
    assert con.execute("select count(*) from alertas").fetchone()[0] == 1


def test_achado_superado_SAI_quando_o_detector_ainda_produz_outros(con):
    """A poda retira o superado quando há com o que comparar: o detector produziu B, então A morreu."""
    _gravar(con, [_achado(titulo="ACHADO A")])
    _gravar(con, [_achado(titulo="ACHADO B")])
    titulos = {r[0] for r in con.execute("select titulo from alertas")}
    assert titulos == {"ACHADO B"}


def test_detector_que_zera_por_inteiro_e_POUPADO_e_declarado(con):
    """Zerar por completo é ambíguo — pode ser fonte quebrada. O módulo poupa e DIZ que poupou;
    quem separa os dois casos depois é o `visto_em`, que não avança para o alerta não reconfirmado."""
    _gravar(con, [_achado()])
    aviso = _gravar(con, [])
    assert con.execute("select count(*) from alertas").fetchone()[0] == 1
    assert "POUPADOS" in aviso and "visto_em" in aviso
