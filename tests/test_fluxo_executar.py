"""27/11/2026 — regra 3 do motor: interrupção da infraestrutura não gasta tentativa. Um job do E6 foi à quarentena
porque a conexão it-campo → PG da VM-2 caiu nas 5 tentativas. Conexão PERDIDA vira espera (Adiado, sem gastar
tentativa); erro real do banco (QueryCanceled por tempo) continua sendo falha — senão um defeito ficaria escondido."""
import json

import psycopg
import pytest

from compliance_agent.fluxo import executar as X


class _Estagio:
    def __init__(self, exc):
        self.exc = exc

    def handler(self, payload, ctx):
        raise self.exc


def test_conexao_perdida_vira_espera_sem_gastar_tentativa(tmp_path):
    saida = tmp_path / "s.json"
    exc = psycopg.OperationalError("consuming input failed: server closed the connection unexpectedly")
    assert X._rodar("rodar", {"payload": {}}, _Estagio(exc), None, str(saida)) == X.SAIDA_ADIADO
    d = json.loads(saida.read_text())
    assert d["adiado"].startswith("Adiado: infra: conexão com o PostgreSQL caiu") and d["reabre_em"]


def test_tempo_de_consulta_estourado_nao_e_infra():
    with pytest.raises(psycopg.errors.QueryCanceled):
        X._rodar("rodar", {"payload": {}}, _Estagio(psycopg.errors.QueryCanceled("canceling statement due to statement timeout")),
                 None, "/dev/null")


def test_outro_erro_operacional_continua_falha():
    with pytest.raises(psycopg.OperationalError):
        X._rodar("rodar", {"payload": {}}, _Estagio(psycopg.OperationalError("deadlock detected")), None, "/dev/null")
