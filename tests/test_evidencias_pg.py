# -*- coding: utf-8 -*-
"""Integração da plataforma de evidências com o PostgreSQL (docs/PLANO-PLATAFORMA-EVIDENCIAS.md, Fase 3).

Roda SÓ com `JFN_EVIDENCIAS_DSN=postgresql://...` no ambiente (banco de TESTE: as tabelas são esvaziadas).
Critério de saída da Fase 3: worker derrubado sem perda nem efeito em dobro — reserva concorrente real (threads com
conexões próprias) e prazo vencido pelo relógio do servidor."""
import os
import threading
import time

import pytest

from compliance_agent import evidencias as E

DSN = os.environ.get(E.ENV_DSN, "")
pytestmark = pytest.mark.skipif(not DSN.startswith(("postgresql://", "postgres://")),
                                reason="sem JFN_EVIDENCIAS_DSN (PostgreSQL de teste)")


@pytest.fixture()
def con():
    c = E.conectar(DSN)
    with c:
        c.execute("TRUNCATE jobs RESTART IDENTITY")
    yield c
    c.close()


def test_conectar_sem_argumento_usa_o_dsn_do_ambiente():
    c = E.conectar()
    try:
        assert E._e_pg(c)
    finally:
        c.close()


def test_fila_basica_no_pg(con):
    assert E.enfileirar(con, "ocr", "doc:1") is True
    assert E.enfileirar(con, "ocr", "doc:1") is False                          # ON CONFLICT DO NOTHING
    j = E.reservar(con, "ocr", dono="a", prazo_s=60)
    assert j["chave"] == "doc:1" and E.reservar(con, "ocr", dono="b", prazo_s=60) is None
    assert E.concluir(con, j["id"], j["ficha"]) is True
    assert E.reservar(con, "ocr", dono="c", prazo_s=60) is None


def test_reserva_concorrente_50_jobs_nenhum_entregue_duas_vezes(con):
    for k in range(50):
        E.enfileirar(con, "x", f"k{k}")
    vistos: list[str] = []
    trava = threading.Lock()
    erros: list[BaseException] = []

    def worker(nome: str) -> None:
        c = E.conectar(DSN)                                                    # conexão própria por thread
        try:
            while True:
                j = E.reservar(c, "x", dono=nome, prazo_s=300)
                if j is None:
                    # SKIP LOCKED pode devolver vazio enquanto o outro segura a linha: só sai com a fila vazia
                    if c.execute("SELECT COUNT(*) FROM jobs WHERE tipo='x' AND estado='fila'").fetchone()[0] == 0:
                        return
                    continue
                with trava:
                    vistos.append(j["chave"])
                assert E.concluir(c, j["id"], j["ficha"]) is True
        except BaseException as exc:                                           # noqa: BLE001 — repassa ao teste
            erros.append(exc)
        finally:
            c.close()

    ts = [threading.Thread(target=worker, args=(n,)) for n in ("a", "b")]
    for t in ts:
        t.start()
    for t in ts:
        t.join(timeout=120)
    assert not erros, erros
    assert len(vistos) == len(set(vistos)) == 50
    assert con.execute("SELECT COUNT(*) FROM jobs WHERE tipo='x' AND estado='feito'").fetchone()[0] == 50


def test_worker_que_morre_e_recusado_ao_concluir(con):
    """Prazo pelo relógio do SERVIDOR (sem `agora`): o worker some, o prazo vence, outro assume; o antigo volta
    tarde e é recusado — não grava resultado velho por cima do novo."""
    E.enfileirar(con, "ocr", "doc:m")
    morto = E.reservar(con, "ocr", dono="itcampo", prazo_s=0.5)
    assert E.reservar(con, "ocr", dono="vm2", prazo_s=60) is None              # ainda no prazo
    time.sleep(1.2)
    vivo = E.reservar(con, "ocr", dono="vm2", prazo_s=60)
    assert vivo["id"] == morto["id"] and vivo["ficha"] > morto["ficha"]
    assert E.concluir(con, morto["id"], morto["ficha"]) is False
    assert E.falhar(con, morto["id"], morto["ficha"]) is False
    assert E.concluir(con, vivo["id"], vivo["ficha"]) is True


def test_quarentena_no_pg(con):
    E.enfileirar(con, "ocr", "doc:9")
    t = 1000.0
    for _ in range(E.MAX_TENTATIVAS):
        assert E.reservar(con, "ocr", dono="w", prazo_s=10, agora=t) is not None
        t += 20
    assert E.reservar(con, "ocr", dono="w", prazo_s=10, agora=t) is None
    assert con.execute("SELECT estado FROM jobs WHERE chave='doc:9'").fetchone()[0] == "quarentena"
