# -*- coding: utf-8 -*-
"""Fila do motor de fluxo no PostgreSQL (O1.7/O1.8) — em ESQUEMA TEMPORÁRIO (tests/fluxo_pg.py).

Critério de pronto da O1.7: 3 workers × 1.000 jobs ⇒ 0 duplicado e 0 perdido; lease vencido recuperado; ficha
velha não conclui; idempotência por chave; backoff e quarentena; 'feito' só com efeito conferido."""
import threading

from compliance_agent.fluxo import fila
from compliance_agent.fluxo.fila import Resultado
from tests.fluxo_pg import DSN, con, esquema_tmp, precisa_pg  # noqa: F401 — fixtures

pytestmark = precisa_pg
OK = Resultado(efeito={"x": 1}, efeito_conferido=True)


def _estado(con, chave):
    return con.execute("SELECT estado, tentativas, erro_tipo FROM jobs WHERE chave = %s", (chave,)).fetchone()


def _vencer_lease(con, chave):
    con.execute("UPDATE jobs SET prazo = now() - interval '1 second' WHERE chave = %s", (chave,))


def test_schema_aplicado_e_verificado(con, esquema_tmp):
    from compliance_agent.fluxo import schema
    v = schema.verificar(con, esquema_tmp)
    assert v["ok"], v["faltando"]
    assert schema.aplicar(con, esquema_tmp) == []                     # idempotente: nada novo na 2ª vez


def test_idempotencia_por_chave(con):
    a = fila.enfileirar(con, "eco", "eco:1", {"v": 1})
    assert a is not None
    assert fila.enfileirar(con, "eco", "eco:1", {"v": 2}) is None
    assert con.execute("SELECT count(*), max(payload->>'v') FROM jobs").fetchone() == (1, "1")


def test_tres_workers_mil_jobs_zero_duplicado_zero_perdido(con, esquema_tmp):
    with con.cursor() as cur:
        cur.executemany("INSERT INTO jobs(tipo, chave) VALUES ('x', %s)", [(f"x:{i}",) for i in range(1000)])
    vistos: list[str] = []
    trava = threading.Lock()
    erros: list[BaseException] = []

    def worker(no: str) -> None:
        c = fila.conectar(DSN, esquema_tmp)                           # conexão própria por worker
        try:
            while True:
                j = fila.reservar(c, no, {"cpu_leve": 1}, prazo_s=300)
                if j is None:
                    # SKIP LOCKED pode devolver vazio enquanto outro segura a linha: só sai com a fila vazia
                    if c.execute("SELECT count(*) FROM jobs WHERE estado = 'fila'").fetchone()[0] == 0:
                        return
                    continue
                with trava:
                    vistos.append(j.chave)
                assert fila.concluir(c, j.ficha, OK) == "feito"
        except BaseException as exc:                                  # noqa: BLE001 — repassa ao teste
            erros.append(exc)
        finally:
            c.close()

    ts = [threading.Thread(target=worker, args=(n,)) for n in ("vm1", "vm2", "itcampo")]
    for t in ts:
        t.start()
    for t in ts:
        t.join(timeout=600)
    assert not erros, erros
    assert len(vistos) == len(set(vistos)) == 1000                    # 0 duplicado
    assert con.execute("SELECT count(*) FROM jobs WHERE estado = 'feito' AND tentativas = 1").fetchone()[0] == 1000
    assert con.execute("SELECT count(DISTINCT ficha) FROM jobs").fetchone()[0] == 1000   # ficha única por reserva
    assert con.execute("SELECT count(DISTINCT dono) FROM jobs").fetchone()[0] >= 2       # concorrência real


def test_lease_vencido_e_recuperado_e_a_ficha_velha_nao_conclui(con):
    fila.enfileirar(con, "eco", "eco:m")
    morto = fila.reservar(con, "itcampo", ["cpu_leve"])
    assert fila.reservar(con, "vm2", ["cpu_leve"]) is None            # ainda reservado
    _vencer_lease(con, "eco:m")
    assert fila.heartbeat(con, morto.ficha) is False                  # lease vencido não se renova
    assert fila.concluir(con, morto.ficha, OK) is None                # nem conclui (fencing pelo prazo)
    assert fila.recuperar_vencidos(con) == 1
    assert _estado(con, "eco:m") == ("fila", 1, "lease_vencido")
    con.execute("UPDATE jobs SET disponivel_em = now() WHERE chave = 'eco:m'")   # pula o backoff
    vivo = fila.reservar(con, "vm2", ["cpu_leve"])
    assert vivo.id == morto.id and vivo.ficha > morto.ficha
    assert fila.concluir(con, morto.ficha, OK) is None                # ficha velha recusada
    assert fila.falhar(con, morto.ficha, "tarde") is None
    assert fila.concluir(con, vivo.ficha, OK) == "feito"


def test_heartbeat_estende_o_lease(con):
    fila.enfileirar(con, "eco", "eco:h")
    j = fila.reservar(con, "vm1", ["cpu_leve"], prazo_s=5)
    p1 = con.execute("SELECT prazo FROM jobs WHERE id = %s", (j.id,)).fetchone()[0]
    assert fila.heartbeat(con, j.ficha, prazo_s=600) is True
    p2 = con.execute("SELECT prazo FROM jobs WHERE id = %s", (j.id,)).fetchone()[0]
    assert (p2 - p1).total_seconds() > 500


def test_backoff_exponencial_e_quarentena_apos_max_tentativas(con):
    fila.enfileirar(con, "eco", "eco:b", max_tentativas=3)
    esperas = []
    for n in range(1, 4):
        j = fila.reservar(con, "vm2", ["cpu_leve"])
        assert j is not None and j.tentativas == n
        estado = fila.falhar(con, j.ficha, "rede caiu", transitorio=True)
        espera = con.execute("SELECT extract(epoch FROM disponivel_em - now()) FROM jobs WHERE id = %s",
                             (j.id,)).fetchone()[0]
        esperas.append(float(espera))
        if n < 3:
            assert estado == "fila"
            assert fila.reservar(con, "vm2", ["cpu_leve"]) is None    # ainda no backoff
            con.execute("UPDATE jobs SET disponivel_em = now() WHERE id = %s", (j.id,))
        else:
            assert estado == "quarentena"
    assert 25 < esperas[0] <= 30 and 55 < esperas[1] <= 60           # 30 s, 60 s
    assert fila.backoff_s(1) == 30 and fila.backoff_s(2) == 60 and fila.backoff_s(30) == fila.BACKOFF_TETO_S
    assert fila.reservar(con, "vm2", ["cpu_leve"]) is None            # quarentena não volta sozinha


def test_erro_permanente_vai_direto_a_quarentena(con):
    fila.enfileirar(con, "eco", "eco:p")
    j = fila.reservar(con, "vm2", ["cpu_leve"])
    assert fila.falhar(con, j.ficha, "documento não existe", transitorio=False, erro_tipo="permanente") == "quarentena"
    assert _estado(con, "eco:p") == ("quarentena", 1, "permanente")


def test_sem_efeito_conferido_volta_com_backoff_e_esgotado_e_falhou_efeito(con):
    """1.2 (revisão 25/11): sem conferência o job VOLTA (o E3 com omitido e o E5 com página pendente contam com
    isso) gastando tentativa, com o motivo no erro_resumo; esgotadas, `falhou_efeito` com concluido_em. Sem evento."""
    fila.enfileirar(con, "eco", "eco:e", max_tentativas=2)
    j = fila.reservar(con, "vm2", ["cpu_leve"])
    r = Resultado(efeito={"metrica_id": 7}, efeito_conferido=False, eventos=[{"fonte": "eco", "tipo": "concluido"}])
    assert fila.concluir(con, j.ficha, r, "omitidos: 3") == "fila"
    assert _estado(con, "eco:e") == ("fila", 1, "efeito")
    espera, resumo, fim = con.execute("SELECT extract(epoch FROM disponivel_em - now()), erro_resumo, concluido_em "
                                      "FROM jobs WHERE chave = 'eco:e'").fetchone()
    assert 25 <= espera <= 31 and resumo == "omitidos: 3" and fim is None        # backoff de 30 s
    con.execute("UPDATE jobs SET disponivel_em = now()")
    j = fila.reservar(con, "vm2", ["cpu_leve"])
    assert fila.concluir(con, j.ficha, r) == "falhou_efeito"
    assert _estado(con, "eco:e") == ("falhou_efeito", 2, "efeito")
    assert con.execute("SELECT concluido_em IS NOT NULL FROM jobs WHERE chave = 'eco:e'").fetchone()[0]
    assert con.execute("SELECT count(*) FROM eventos").fetchone()[0] == 0


def test_quarentena_grava_concluido_em(con):
    """1.3: a quarentena tem concluido_em (a saúde conta toda quarentena aberta)."""
    fila.enfileirar(con, "eco", "eco:q1")
    j = fila.reservar(con, "vm2", ["cpu_leve"])
    fila.falhar(con, j.ficha, "x", transitorio=False)
    fila.enfileirar(con, "eco", "eco:q2", max_tentativas=1)
    fila.reservar(con, "vm2", ["cpu_leve"])
    _vencer_lease(con, "eco:q2")
    assert fila.recuperar_vencidos(con) == 1
    assert con.execute("SELECT count(*) FROM jobs WHERE estado = 'quarentena' AND concluido_em IS NOT NULL"
                       ).fetchone()[0] == 2


def test_adiado_volta_na_reabertura_sem_gastar_tentativa(con):
    """1.12: espera conhecida (ritmo da assinatura) não leva à quarentena: devolve a tentativa e reabre na hora."""
    from datetime import datetime, timedelta, timezone
    fila.enfileirar(con, "eco", "eco:ad", max_tentativas=1)
    reabre = datetime.now(timezone.utc) + timedelta(hours=2)
    for _ in range(3):                                   # 3 adiamentos com max_tentativas=1: nunca quarentena
        con.execute("UPDATE jobs SET disponivel_em = now()")
        j = fila.reservar(con, "vm2", ["cpu_leve"])
        assert fila.adiar(con, j.ficha, "SemCota: ritmo contido", reabre) == "fila"
    assert _estado(con, "eco:ad") == ("fila", 0, "adiado")
    espera = con.execute("SELECT extract(epoch FROM disponivel_em - now()) FROM jobs").fetchone()[0]
    assert 7100 <= espera <= 7201
    con.execute("UPDATE jobs SET disponivel_em = now()")
    j = fila.reservar(con, "vm2", ["cpu_leve"])
    assert fila.adiar(con, j.ficha, "sem reabertura informada") == "fila"
    espera = con.execute("SELECT extract(epoch FROM disponivel_em - now()) FROM jobs").fetchone()[0]
    assert 880 <= espera <= 901                          # padrão 15 min


def test_parada_do_supervisor_nao_gasta_tentativa(con):
    """26/11/2026: 2 jobs do E6 foram à quarentena com «supervisor parado (SIGTERM)» depois de 5 reinícios de deploy —
    cada reserva gastava uma tentativa e a parada não a devolvia. Interrupção da infraestrutura não é falha do job."""
    fila.enfileirar(con, "eco", "eco:pa", max_tentativas=1)
    for _ in range(5):
        j = fila.reservar(con, "vm2", ["cpu_leve"])
        assert fila.devolver_parada(con, j.ficha, "supervisor parado (SIGTERM)") == "fila"
    assert _estado(con, "eco:pa") == ("fila", 0, "parada")
    assert con.execute("SELECT disponivel_em <= now() FROM jobs").fetchone()[0]     # volta já, sem backoff


def test_feito_grava_os_eventos_na_mesma_transacao(con):
    fila.enfileirar(con, "eco", "eco:ev", correlation_id="cid-1")
    j = fila.reservar(con, "vm2", ["cpu_leve"])
    r = Resultado(efeito={"ok": 1}, efeito_conferido=True, eventos=[{"fonte": "eco", "tipo": "concluido"}])
    assert fila.concluir(con, j.ficha, r) == "feito"
    assert con.execute("SELECT fonte, chave, tipo, detalhe->>'correlation_id' FROM eventos").fetchone() == (
        "eco", "eco:ev", "concluido", "cid-1")


def test_reserva_respeita_recursos_e_prioridade(con):
    fila.enfileirar(con, "ocr", "ocr:gpu", recursos=["gpu"], prioridade=1)
    fila.enfileirar(con, "eco", "eco:baixa", prioridade=200)
    fila.enfileirar(con, "eco", "eco:alta", prioridade=10)
    assert fila.reservar(con, "vm2", {"cpu_leve": 1, "gpu": 0}).chave == "eco:alta"   # gpu sem slot: pula
    assert fila.reservar(con, "itcampo", {"gpu": 1, "cpu_leve": 1}).chave == "ocr:gpu"
    assert fila.reservar(con, "vm2", {"cpu_leve": 0}) is None                          # nenhum slot livre


def test_no_preferido_desempata(con):
    fila.enfileirar(con, "eco", "eco:qualquer")
    fila.enfileirar(con, "eco", "eco:do-itcampo", no_preferido="itcampo")
    assert fila.reservar(con, "itcampo", ["cpu_leve"]).chave == "eco:do-itcampo"


def test_notify_jfn_jobs_no_insert(con, esquema_tmp):
    import psycopg
    escuta = psycopg.connect(DSN, autocommit=True)
    try:
        escuta.execute("LISTEN jfn_jobs")
        fila.enfileirar(con, "eco", "eco:notify")
        recebidos = [n.payload for n in escuta.notifies(timeout=5, stop_after=1)]
    finally:
        escuta.close()
    assert recebidos == ["eco"]


def test_reabrir_devolve_terminado_a_fila_mas_nao_mexe_em_reservado(con):
    fila.enfileirar(con, "eco", "eco:r")
    j = fila.reservar(con, "vm2", ["cpu_leve"])
    assert fila.enfileirar(con, "eco", "eco:r", reabrir=True) is None    # reservado: fica como está
    fila.concluir(con, j.ficha, OK)
    assert fila.enfileirar(con, "eco", "eco:r", {"de_novo": 1}, reabrir=True) == j.id
    assert _estado(con, "eco:r") == ("fila", 0, None)


def test_arquivar_jobs_move_so_feito_antigo(con):
    for k in ("a", "b"):
        fila.enfileirar(con, "eco", f"eco:arq:{k}")
        fila.concluir(con, fila.reservar(con, "vm2", ["cpu_leve"]).ficha, OK)
    fila.enfileirar(con, "eco", "eco:arq:q")
    fila.falhar(con, fila.reservar(con, "vm2", ["cpu_leve"]).ficha, "x", transitorio=False)
    con.execute("UPDATE jobs SET concluido_em = now() - interval '40 days' WHERE chave = 'eco:arq:a'")
    assert con.execute("SELECT arquivar_jobs(30)").fetchone()[0] == 1
    assert con.execute("SELECT chave FROM jobs_arquivo").fetchall() == [("eco:arq:a",)]
    assert con.execute("SELECT count(*) FROM jobs").fetchone()[0] == 2
