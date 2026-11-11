# -*- coding: utf-8 -*-
"""Sem argumento, o `empresas_dump_sweep` usa o mês do dump BAIXADO (`.mes_baixado`).

Medido em 10–11/11/2026: o drop-in `cadenrich.conf` do `jfn-intel-cache` chama o script sem o
mês, que desde o commit 19f4bd0c exige `AAAA-MM` — a unit ficou `failed` 4 vezes em 2 dias e o
remédio automático reexecutava a unit inteira (11 min de CPU, pico de 3,8 GB). O mês padrão não
é chute: é o mesmo `.mes_baixado` que o `socios_dump_refresh.sh` já usa. Sem ele, falha nomeada.
"""
import pytest

import tools.empresas_dump_sweep as E


def test_argumento_explicito_manda(tmp_path, monkeypatch):
    monkeypatch.setattr(E, "_DUMP", tmp_path)
    (tmp_path / ".mes_baixado").write_text("2026-10\n")
    assert E._mes_do_dump(["x", "2026-05"]) == "2026-05"


def test_sem_argumento_usa_o_mes_baixado(tmp_path, monkeypatch):
    monkeypatch.setattr(E, "_DUMP", tmp_path)
    monkeypatch.delenv("MES", raising=False)
    (tmp_path / ".mes_baixado").write_text("2026-10\n")
    assert E._mes_do_dump(["x"]) == "2026-10"


def test_env_MES_forca_como_no_refresh(tmp_path, monkeypatch):
    monkeypatch.setattr(E, "_DUMP", tmp_path)
    monkeypatch.setenv("MES", "2026-09")
    (tmp_path / ".mes_baixado").write_text("2026-10\n")
    assert E._mes_do_dump(["x"]) == "2026-09"


@pytest.mark.parametrize("conteudo", [None, "", "lixo", "2026-13x"])
def test_sem_mes_valido_falha_nomeado(tmp_path, monkeypatch, conteudo):
    monkeypatch.setattr(E, "_DUMP", tmp_path)
    monkeypatch.delenv("MES", raising=False)
    if conteudo is not None:
        (tmp_path / ".mes_baixado").write_text(conteudo)
    with pytest.raises(SystemExit, match="mês do dump"):
        E._mes_do_dump(["x"])
