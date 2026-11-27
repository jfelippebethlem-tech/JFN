# -*- coding: utf-8 -*-
"""Planejador do motor de fluxo (O1.8): cron mínimo (puro), agenda → jobs, eventos → dependentes, liderança única
por advisory lock e saúde honesta — os de banco em ESQUEMA TEMPORÁRIO (tests/fluxo_pg.py)."""
from datetime import datetime

import pytest

from compliance_agent.fluxo import fila, planejador as P
from compliance_agent.fluxo.fila import Resultado
from tests.fluxo_pg import DSN, chave_lock, con, esquema_tmp, precisa_pg  # noqa: F401 — fixtures

BR = P.FUSO


def _br(*a):
    return datetime(*a, tzinfo=BR)


# ── cron (puro) ──
@pytest.mark.parametrize("expr,depois,esperado", [
    ("*/15 * * * *", _br(2026, 11, 24, 13, 7), _br(2026, 11, 24, 13, 15)),
    ("0 3 * * *", _br(2026, 11, 24, 3, 0), _br(2026, 11, 25, 3, 0)),            # estritamente depois
    ("30 2 1 * *", _br(2026, 11, 24, 0, 0), _br(2026, 12, 1, 2, 30)),
    ("0 19 * * 6", _br(2026, 11, 24, 12, 0), _br(2026, 11, 28, 19, 0)),         # sábado (dia da virada)
    ("0 19 * * 7", _br(2026, 11, 24, 12, 0), _br(2026, 11, 29, 19, 0)),         # 7 = domingo
    ("0 8 1-5 * 1-5/2", _br(2026, 11, 24, 12, 0), _br(2026, 11, 25, 8, 0)),     # dia OU semana (Vixie): qua
    ("5,35 9-10 * * *", _br(2026, 11, 24, 9, 35), _br(2026, 11, 24, 10, 5)),
    ("0 0 29 2 *", _br(2026, 3, 1, 0, 0), _br(2028, 2, 29, 0, 0)),              # bissexto
])
def test_cron_proximo(expr, depois, esperado):
    assert P.Cron(expr).proximo(depois) == esperado


def test_cron_converte_utc_para_brasilia():
    from datetime import timezone
    utc = datetime(2026, 11, 24, 5, 0, tzinfo=timezone.utc)                    # 05:00 UTC = 02:00 em Brasília
    assert P.Cron("0 3 * * *").proximo(utc) == _br(2026, 11, 24, 3, 0)


@pytest.mark.parametrize("expr", ["* * * *", "60 * * * *", "* 24 * * *", "*/0 * * * *", "5-1 * * * *", "x * * * *"])
def test_cron_invalido_recusa(expr):
    with pytest.raises(ValueError):
        P.Cron(expr)


# ── banco ──
@precisa_pg
def test_agenda_nova_so_calcula_e_vencida_vira_um_job(con):
    con.execute("INSERT INTO agenda(id, cron_expr, tipo_job, payload) VALUES ('eco5', '*/5 * * * *', 'eco', "
                "'{\"a\": 1}')")
    assert P.materializar_agenda(con) == 0                               # recém-criada: não dispara
    proximo = con.execute("SELECT proximo FROM agenda").fetchone()[0]
    assert proximo is not None and con.execute("SELECT count(*) FROM jobs").fetchone()[0] == 0
    con.execute("UPDATE agenda SET proximo = now() - interval '2 hours'")    # 24 horários atrasados
    assert P.materializar_agenda(con, {"eco": {"recursos": ["llm"], "prioridade": 7}}) == 1   # UMA execução
    tipo, chave, payload, rec, pri = con.execute("SELECT tipo, chave, payload, recursos, prioridade FROM jobs"
                                                 ).fetchone()
    assert tipo == "eco" and chave.startswith("eco:agenda:eco5:") and payload == {"a": 1}
    assert rec == ["llm"] and pri == 7
    assert con.execute("SELECT proximo > now() FROM agenda").fetchone()[0]
    assert P.materializar_agenda(con) == 0                               # nada vencido de novo


@precisa_pg
def test_agenda_inativa_nao_dispara(con):
    con.execute("INSERT INTO agenda(id, cron_expr, tipo_job, proximo, ativo) VALUES ('x', '* * * * *', 'eco', "
                "now() - interval '1 hour', false)")
    assert P.materializar_agenda(con) == 0


@precisa_pg
def test_lideranca_unica_e_passa_adiante_quando_o_lider_cai(esquema_tmp):
    chave = chave_lock()
    a, b = fila.conectar(DSN, esquema_tmp), fila.conectar(DSN, esquema_tmp)
    try:
        assert P.tentar_lideranca(a, chave) is True
        assert P.tentar_lideranca(b, chave) is False
        assert P.tentar_lideranca(a, chave) is True                       # reentrante para o próprio líder
        a.close()                                                         # o líder morreu: o lock de sessão cai
        assert P.tentar_lideranca(b, chave) is True
    finally:
        for c in (a, b):
            if not c.closed:
                c.close()


@precisa_pg
def test_evento_vira_job_do_dependente_e_reabre_depois_do_feito(con):
    grafo = {"teste:origem": [{"tipo": "eco", "debounce_s": 0}]}
    fila.emitir(con, "teste:origem", "mudou", "proc:1")
    fila.emitir(con, "teste:origem", "mudou", "proc:1")                   # dois eventos, mesma chave ⇒ 1 job
    assert P.propagar_eventos(con, grafo) == 2
    assert con.execute("SELECT count(*), max(chave) FROM jobs").fetchone() == (1, "eco:proc:1")
    j = fila.reservar(con, "vm2", ["cpu_leve"])
    fila.emitir(con, "teste:origem", "mudou", "proc:1")                   # chega DURANTE a execução
    assert P.propagar_eventos(con, grafo) == 0                            # fica pendente, não se perde
    fila.concluir(con, j.ficha, Resultado(efeito_conferido=True))
    assert P.propagar_eventos(con, grafo) == 1                            # agora reabre o job
    assert fila.estado_de(con, "eco:proc:1") == "fila"
    assert con.execute("SELECT count(*) FROM eventos WHERE processado_em IS NULL").fetchone()[0] == 0


@precisa_pg
def test_evento_sem_dependente_fica_pendente_e_a_saude_diz_bloqueado(con):
    """1.1 (revisão 25/11): evento que ninguém consome NÃO é marcado processado — some calado era o defeito."""
    _no(con, "vm2", None)
    fila.emitir(con, "ninguem:depende", "x")
    assert P.propagar_eventos(con, P.GRAFO_EXEMPLO) == 0
    assert con.execute("SELECT count(*) FROM jobs").fetchone()[0] == 0
    assert con.execute("SELECT count(*) FROM eventos WHERE processado_em IS NULL").fetchone()[0] == 1
    s = P.saude(con, grafo=P.GRAFO_EXEMPLO)
    assert s["estado"] == "BLOQUEADO" and any("evento sem consumidor: ninguem:depende/x" in m for m in s["motivos"])
    assert P.propagar_eventos(con, P.GRAFO_EXEMPLO, terminais={"ninguem:depende/x": "fim"}) == 1   # terminal: marca
    assert P.saude(con, grafo=P.GRAFO_EXEMPLO)["estado"] == "SAUDAVEL"


def _no(con, no, slots, idade_s=0):
    con.execute("INSERT INTO nos(no, slots, heartbeat_em) VALUES (%s, %s, now() - make_interval(secs => %s))",
                (no, '{"cpu_leve": 2}' if slots is None else slots, idade_s))


@precisa_pg
def test_saude_indisponivel_sem_no_vivo(con):
    _no(con, "vm2", None, idade_s=900)
    assert P.saude(con)["estado"] == "INDISPONIVEL"


@precisa_pg
def test_saude_saudavel_degradado_atrasado_bloqueado(con):
    _no(con, "vm2", None)
    assert P.saude(con)["estado"] == "SAUDAVEL"
    assert P.saude(con, ("vm2", "itcampo"))["estado"] == "DEGRADADO"      # nó esperado fora
    fila.enfileirar(con, "eco", "eco:q")
    fila.falhar(con, fila.reservar(con, "vm2", ["cpu_leve"]).ficha, "x", transitorio=False)
    s = P.saude(con)
    assert s["estado"] == "DEGRADADO" and any("quarentena" in m for m in s["motivos"])
    con.execute("UPDATE jobs SET criado_em = now() - interval '3 days', concluido_em = now() - interval '3 days'")
    assert P.saude(con)["estado"] == "DEGRADADO"                          # 1.3: toda quarentena aberta, sem janela
    fila.enfileirar(con, "eco", "eco:velho")
    con.execute("UPDATE jobs SET disponivel_em = now() - interval '1 hour' WHERE chave = 'eco:velho'")
    assert P.saude(con)["estado"] == "ATRASADO"
    fila.enfileirar(con, "ocr", "ocr:1", recursos=["gpu"])               # só o it-campo tem GPU, e está fora
    s = P.saude(con)
    assert s["estado"] == "BLOQUEADO" and any("gpu" in m for m in s["motivos"])


@precisa_pg
def test_ciclo_recupera_lease_vencido(con):
    fila.enfileirar(con, "eco", "eco:l")
    fila.reservar(con, "vm1", ["cpu_leve"])
    con.execute("UPDATE jobs SET prazo = now() - interval '1 second'")
    r = P.ciclo(con, grafo={})
    assert r["recuperados"] == 1 and fila.estado_de(con, "eco:l") == "fila"


@precisa_pg
def test_linha_nova_de_estagio_ja_liberado_entra_ativa(con):
    """26/11/2026: linha nova da agenda entrava SEMPRE desativada (a liberação é quem ativa) — rotina criada depois da
    religação, num estágio já liberado, ficava parada para sempre. Estágio liberado ⇒ a linha nova já entra ativa."""
    con.execute("INSERT INTO liberacao(estagio, por) VALUES ('E18', 't')")
    linhas = [{"id": "nova_e18", "cron_expr": "*/15 * * * *", "tipo_job": "legado:x", "payload": {"estagio": "E18"}},
              {"id": "nova_e10", "cron_expr": "*/15 * * * *", "tipo_job": "legado:y", "payload": {"estagio": "E10"}}]
    P.sincronizar_agenda(con, linhas)
    at = dict(con.execute("SELECT id, ativo FROM agenda WHERE id IN ('nova_e18', 'nova_e10')").fetchall())
    assert at == {"nova_e18": True, "nova_e10": False}


@precisa_pg
def test_contrato_novo_vale_para_quem_ainda_espera_na_fila(con):
    """26/11/2026: recurso, prioridade e nós do E6 mudaram no yaml 4 vezes no dia, e os jobs JÁ na fila seguiam com o
    contrato da criação (payload.nos=['vm2'] congelado — o it-campo nunca pegava o E6); corrigi à mão com UPDATE 4×.
    Regra: na recarga do yaml o líder reaplica o contrato atual a quem está em 'fila' (reservado/feito não mudam)."""
    from compliance_agent.fluxo import grafo as G
    g = G.carregar()
    ek = next(k for k, e in g.estagios.items() if e.tipo == "confirmar_ocr")
    velho = {**g.payload_do_estagio(ek), "nos": ["vm2"], "x": 1}
    fila.enfileirar(con, "confirmar_ocr", "confirmar_ocr:a", velho, prioridade=99, recursos=["cpu_leve"])
    fila.enfileirar(con, "confirmar_ocr", "confirmar_ocr:b", velho, prioridade=99, recursos=["cpu_leve"])
    con.execute("UPDATE jobs SET estado = 'reservado' WHERE chave = 'confirmar_ocr:b'")
    n = P.reaplicar_contrato(con, g)
    assert n.get("confirmar_ocr") == 1
    c = g.contrato_do_estagio(ek)
    pr, rec, pay = con.execute("SELECT prioridade, recursos, payload FROM jobs WHERE chave = 'confirmar_ocr:a'").fetchone()
    assert pr == c["prioridade"] and rec == c["recursos"] and pay["nos"] == c["nos"] and pay["x"] == 1
    assert con.execute("SELECT prioridade FROM jobs WHERE chave = 'confirmar_ocr:b'").fetchone()[0] == 99
    assert P.reaplicar_contrato(con, g) == {}                        # idempotente: nada mais a mudar
