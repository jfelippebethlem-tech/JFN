# -*- coding: utf-8 -*-
"""A sentinela vigia o `fim` dos ciclos — morte silenciosa no meio do sweep vira invariante.

O caso que criou isto (2026-08-08): `sweep_sei.sh` morria na expansão de um `$REPO` indefinido
(`set -u`), o erro ia ao stderr do cron que ninguém lê, e todos os passos depois da linha ficaram
um dia e meio sem rodar. Não havia `rc` para mentir — o processo só acabava. O único rastro era a
AUSÊNCIA do `say "fim"` no log. A catraca estática (`test_sweep_sem_variavel_fantasma`) impede a
RECORRÊNCIA daquela causa; esta invariante pega QUALQUER causa da mesma família em tempo de
execução — OOM kill no meio, `exit` esquecido num branch novo, disco cheio.

Régua: 3 ciclos consecutivos iniciados há mais de 6 h sem `fim` = violado. Um ciclo isolado morre
por reboot legítimo; três seguidos é estrutural. Ciclo recente ainda em curso não conta.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta

import pytest

from tools import sentinela_integridade as S


def _ts(horas_atras: float) -> str:
    return (datetime.now() - timedelta(hours=horas_atras)).strftime("%Y-%m-%d %H:%M:%S")


@pytest.fixture()
def raiz(tmp_path, monkeypatch):
    (tmp_path / "data").mkdir()
    monkeypatch.setattr(S, "RAIZ", tmp_path)
    return tmp_path


def _log(raiz, nome: str, linhas: list[str]) -> None:
    (raiz / "data" / f"{nome}.log").write_text("\n".join(linhas) + "\n", encoding="utf-8")


def test_tres_ciclos_sem_fim_violam(raiz):
    _log(raiz, "sweep_sei", [
        f"[{_ts(30)}] início (best-effort)",
        f"[{_ts(30)}] sei_sweep rc=0",
        f"[{_ts(20)}] início (best-effort)",
        f"[{_ts(20)}] sei_pais rc=0",
        f"[{_ts(10)}] início (best-effort)",
        f"[{_ts(10)}] fila por parecer rc=0",
    ])
    r = S.inv_ciclo_chega_ao_fim()
    assert r["estado"] == "violado"
    assert "sweep_sei" in r["evidencia"][0]


def test_ciclo_saudavel_nao_alarma(raiz):
    _log(raiz, "sweep_sei", [
        f"[{_ts(30)}] início (best-effort)", f"[{_ts(29)}] fim",
        f"[{_ts(20)}] início (best-effort)", f"[{_ts(19)}] fim",
        f"[{_ts(10)}] início (best-effort)", f"[{_ts(9.5)}] fim",
    ])
    assert S.inv_ciclo_chega_ao_fim()["estado"] == "ok"


def test_ciclo_em_curso_nao_conta(raiz):
    """Um ciclo iniciado há 1 h ainda vai terminar — alarmar aqui seria alarme permanente."""
    _log(raiz, "sweep_sei", [
        f"[{_ts(20)}] início (best-effort)", f"[{_ts(19)}] fim",
        f"[{_ts(12)}] início (best-effort)", f"[{_ts(11)}] fim",
        f"[{_ts(1)}] início (best-effort)",
    ])
    assert S.inv_ciclo_chega_ao_fim()["estado"] == "ok"


def test_um_morto_entre_vivos_nao_alarma(raiz):
    """Reboot no meio de um ciclo é vida real — só a SEQUÊNCIA de mortes é estrutural."""
    _log(raiz, "sweep_sei", [
        f"[{_ts(30)}] início (best-effort)", f"[{_ts(29)}] fim",
        f"[{_ts(20)}] início (best-effort)",                      # morreu (reboot)
        f"[{_ts(10)}] início (best-effort)", f"[{_ts(9)}] fim",
    ])
    assert S.inv_ciclo_chega_ao_fim()["estado"] == "ok"


def test_log_ausente_e_silencio_nao_erro(raiz):
    assert S.inv_ciclo_chega_ao_fim()["estado"] == "ok"


def test_o_caso_real_com_prefixo_de_colher(raiz):
    """As linhas do colher têm prefixo `[colher_vm2]` entre o timestamp e o texto — o parser
    precisa atravessá-lo, senão um `fim` legítimo com prefixo não conta."""
    _log(raiz, "sweep_dados", [
        f"[{_ts(20)}] início",
        f"[{_ts(19)}] [colher_vm2] fim (rc=0) — arquivo local: 2236 processos",
    ])
    r = S.inv_ciclo_chega_ao_fim()
    assert r["estado"] == "ok"
