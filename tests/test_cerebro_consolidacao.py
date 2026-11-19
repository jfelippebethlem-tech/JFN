# -*- coding: utf-8 -*-
"""Consolidação do segundo cérebro: fila + teto. Sem rede e sem modelo — tudo injetado."""
from types import SimpleNamespace

import pytest

from compliance_agent import cerebro_consolidacao as K


def _par(a, b, sim=0.95):
    lado = lambda i: {"id": i, "kind": "decisoria", "subject": "s", "content": f"fato {i}", "chave": f"k:{i}",  # noqa: E731
                      "created_at": "2026-11-10T00:00:00+00:00"}
    return {"sim": sim, "a": lado(a), "b": lado(b)}


@pytest.fixture
def con(tmp_path):
    c = K._con(tmp_path / "fila.db")
    yield c
    c.close()


def _pensar(veredito="mesmo_fato", modelo="claude-sonnet-5-5", chamadas=None):
    def f(tarefa, prompt, **k):
        assert k["backend"] == "cli"                    # nunca API paga, nunca cascata
        if chamadas is not None:
            chamadas.append(prompt)
        return SimpleNamespace(modelo=modelo, segundos=10.0,
                               dados={"veredito": veredito, "texto": "fato único", "motivo": "iguais"})
    return f


FOLGA = lambda: (9000.0, None)  # noqa: E731


def test_colher_nao_repete_par(con):
    assert K.colher(con, [_par(1, 2), _par(3, 4)])["novos_na_fila"] == 2
    assert K.colher(con, [_par(1, 2), _par(5, 6)])["novos_na_fila"] == 1
    assert K.resumo(con) == {"aberto": 3}


def test_propor_respeita_teto_de_chamadas_e_o_resto_fica_na_fila(con, monkeypatch):
    K.colher(con, [_par(i, i + 100, 0.99 - i / 1000) for i in range(5)])
    monkeypatch.setenv("JFN_CONSOLIDACAO_MAX", "2")
    r = K.propor(con, pensar=_pensar(), folga=FOLGA, registrar_proposta=lambda *a: 77)
    assert r["chamadas"] == 2 and r["propostas"] == 2 and "2 chamadas" in r["parou_por"]
    assert K.resumo(con) == {"aberto": 3, "proposto": 2}
    it = con.execute("SELECT * FROM fila WHERE estado='proposto' ORDER BY sim DESC").fetchone()
    assert it["a"] == 0 and it["proposta"] == "fato único" and it["mem_proposta"] == 77   # o mais parecido primeiro


def test_teto_de_segundos(con, monkeypatch):
    K.colher(con, [_par(i, i + 100) for i in range(5)])
    monkeypatch.setenv("JFN_CONSOLIDACAO_MAX_S", "25")
    r = K.propor(con, pensar=_pensar(), folga=FOLGA, registrar_proposta=lambda *a: None)
    assert r["chamadas"] == 3 and "25 s" in r["parou_por"]              # 10 + 10 + 10 ≥ 25


def test_reserva_do_orcamento_do_dia_impede_a_primeira_chamada(con):
    K.colher(con, [_par(1, 2)])
    chamadas = []
    r = K.propor(con, pensar=_pensar(chamadas=chamadas), folga=lambda: (300.0, None), registrar_proposta=lambda *a: None)
    assert chamadas == [] and r["chamadas"] == 0 and "reserva" in r["parou_por"]
    r = K.propor(con, pensar=_pensar(chamadas=chamadas), folga=lambda: (9000.0, "limite de uso da assinatura"),
                 registrar_proposta=lambda *a: None)
    assert chamadas == [] and "limite de uso" in r["parou_por"]


def test_assinatura_indisponivel_para_e_resposta_da_api_e_descartada(con):
    K.colher(con, [_par(1, 2), _par(3, 4)])
    r = K.propor(con, pensar=lambda *a, **k: None, folga=FOLGA, registrar_proposta=lambda *a: None)
    assert r["chamadas"] == 0 and "assinatura indisponível" in r["parou_por"]
    r = K.propor(con, pensar=_pensar(modelo="claude-haiku-5-5@api"), folga=FOLGA, registrar_proposta=lambda *a: None)
    assert r["chamadas"] == 0 and r["propostas"] == 0 and "API paga" in r["parou_por"]
    assert K.resumo(con) == {"aberto": 2}                               # nada foi gravado a partir da API


def test_distintos_fecha_sem_proposta_e_formato_ruim_fica_aberto(con):
    K.colher(con, [_par(1, 2)])
    r = K.propor(con, pensar=_pensar("talvez"), folga=FOLGA, registrar_proposta=lambda *a: None)
    assert r["propostas"] == 0 and K.resumo(con) == {"aberto": 1}
    r = K.propor(con, pensar=_pensar("distintos"), folga=FOLGA, registrar_proposta=lambda *a: None)
    assert r["distintos"] == 1 and K.resumo(con) == {"distintos": 1}


def test_decidir_so_vale_para_proposta_e_recusar_nao_toca_o_cerebro(con, monkeypatch):
    K.colher(con, [_par(1, 2)])
    assert "erro" in K.decidir(con, 1, True)                            # ainda 'aberto'
    K.propor(con, pensar=_pensar(), folga=FOLGA, registrar_proposta=lambda *a: None)
    monkeypatch.setattr(K.cerebro, "_http", lambda *a, **k: pytest.fail("recusar não fala com o cérebro"))
    assert K.decidir(con, 1, False, "não é o mesmo")["estado"] == "recusado"
