# -*- coding: utf-8 -*-
"""Dois furos do `_pular` do sweep SEI que faziam o motor bombeiros (e o sweep principal) reler
os mesmos processos sem fim.

Medido em 11/11/2026: (1) o cache tem **9.336 `.json.zst` contra 610 `.json`** e o `_ja_lido_ok`
só procurava o `.json` — ~94% dos processos pareciam "nunca lidos"; (2) o ramo
`_arquivo_incompleto` devolvia à fila sem limite: processos com `n_docs>0` chegaram a **56
tentativas** e a cobertura dos bombeiros ficou parada em 150/9.609 por 11 dias.
"""
import json
import subprocess
from datetime import datetime, timedelta

import tools.sei_sweep as S


def _grava_cache(cache, proc, docs, zst):
    cf = cache / f"cdp_{proc.replace('-', '_').replace('/', '_')}.json"
    corpo = json.dumps({"documentos": docs,
                        "_cached_at": datetime.now().isoformat(timespec="seconds")}).encode()
    if zst:
        alvo = cf.with_name(cf.name + ".zst")
        alvo.write_bytes(subprocess.run(["zstd", "-q", "-c", "-"], input=corpo,
                                        capture_output=True, check=True).stdout)
    else:
        cf.write_bytes(corpo)


def test_ja_lido_ok_reconhece_cache_comprimido(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "CACHE", tmp_path)
    _grava_cache(tmp_path, "SEI-270006/010915/2026", [{"t": "a"}], zst=True)
    assert S._ja_lido_ok("SEI-270006/010915/2026") is True


def test_ja_lido_ok_segue_lendo_json_cru(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "CACHE", tmp_path)
    _grava_cache(tmp_path, "SEI-270007/014968/2026", [{"t": "a"}], zst=False)
    assert S._ja_lido_ok("SEI-270007/014968/2026") is True


def test_ja_lido_ok_zst_com_zero_docs_nao_pula(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "CACHE", tmp_path)
    _grava_cache(tmp_path, "SEI-270007/017398/2026", [], zst=True)
    assert S._ja_lido_ok("SEI-270007/017398/2026") is False


def _f(sem_ganho=None, tentativas=1, horas_atras=0.0, n_docs=5):
    f = {"n_docs": n_docs, "tentativas": tentativas,
         "em": (datetime.now() - timedelta(hours=horas_atras)).isoformat(timespec="seconds")}
    if sem_ganho is not None:
        f["sem_ganho"] = sem_ganho
    return f


def test_releitura_sem_historico_de_ganho_e_liberada():
    # primeira releitura de captura incompleta: ainda nada gasto em vão
    assert S._releitura_liberada(_f(sem_ganho=0, horas_atras=7)) is True


def test_releitura_respeita_backoff_exponencial():
    # 2 releituras sem ganho → espera 6h·2² = 24h; 10h depois ainda não
    assert S._releitura_liberada(_f(sem_ganho=2, horas_atras=10)) is False
    assert S._releitura_liberada(_f(sem_ganho=2, horas_atras=25)) is True


def test_releitura_acima_do_teto_espera_a_janela_longa():
    # o caso medido: 56 tentativas sem ganho. Não pode voltar no lote seguinte...
    assert S._releitura_liberada(_f(tentativas=56, horas_atras=1)) is False
    assert S._releitura_liberada(_f(tentativas=56, horas_atras=24 * 10)) is False
    # ...mas desistir não é para sempre: passada a janela longa, ganha nova chance
    assert S._releitura_liberada(_f(tentativas=56, horas_atras=24 * 31)) is True


def test_sem_ganho_conta_e_zera_quando_a_leitura_rende():
    assert S._contar_sem_ganho({"n_docs": 5, "sem_ganho": 1}, 5) == 2
    assert S._contar_sem_ganho({"n_docs": 5, "sem_ganho": 1}, 3) == 2
    assert S._contar_sem_ganho({"n_docs": 5, "sem_ganho": 4}, 9) == 0
    # processo novo (sem registro) não começa devendo
    assert S._contar_sem_ganho({}, 0) == 0
    assert S._contar_sem_ganho({}, 7) == 0
