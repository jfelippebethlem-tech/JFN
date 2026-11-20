"""Ritmo semanal da assinatura (16/11/2026): a conta tem de durar até a virada de sábado 19:00."""
import json
import time
from datetime import datetime

import pytest

from compliance_agent.llm import contingencia as C
from compliance_agent.llm import ritmo_assinatura as R

VOLTA = datetime(2026, 11, 21, 19, 0).timestamp()


def _bruto(pct, volta=VOLTA):
    iso = datetime.fromtimestamp(volta).astimezone().isoformat()
    return {"five_hour": {"utilization": 10.0, "resets_at": iso}, "seven_day": {"utilization": pct, "resets_at": iso}}


@pytest.fixture(autouse=True)
def _dados(tmp_path, monkeypatch):
    monkeypatch.setenv("JFN_CLAUDE_DADOS", str(tmp_path))
    monkeypatch.delenv("JFN_CLAUDE_CONTINGENCIA", raising=False)
    monkeypatch.setattr(C, "_uso", lambda: {})
    return tmp_path


def test_linha_cresce_do_piso_ao_alvo():
    assert R.linha(VOLTA, VOLTA - R.SEMANA_S) == pytest.approx(R.PISO)
    assert R.linha(VOLTA, VOLTA) == pytest.approx(R.ALVO_SEMANA)
    assert R.PISO < R.linha(VOLTA, VOLTA - R.SEMANA_S / 2) < R.ALVO_SEMANA


def test_niveis_pela_linha():
    agora = VOLTA - R.SEMANA_S / 2          # linha = 47,5
    m = lambda p: R.extrair(_bruto(p), agora)
    assert R.classificar(m(20), agora)["nivel"] == "normal"
    assert R.classificar(m(44), agora)["nivel"] == "economia"
    assert R.classificar(m(48), agora)["nivel"] == "contido"
    fora = VOLTA - 2 * 86400                # fora do dia da virada: teto duro 90
    assert R.classificar(R.extrair(_bruto(91), fora), fora)["nivel"] == "contido"


def test_medicao_velha_ou_ausente_nao_inventa_restricao():
    agora = VOLTA - R.SEMANA_S / 2
    assert R.classificar(None, agora)["nivel"] == "normal"
    velha = R.extrair(_bruto(99), agora - R.VALIDADE_S - 1)
    r = R.classificar(velha, agora)
    assert r["nivel"] == "normal" and r["medido"] is False


def test_medir_grava_so_numeros(_dados):
    r = R.medir(buscar=lambda: _bruto(45.0))
    salvo = json.loads((_dados / "claude_assinatura_uso.json").read_text())
    assert salvo["semana_pct"] == 45.0 and r["medido"] is True
    linha = json.loads((_dados / "claude_assinatura_uso.jsonl").read_text().splitlines()[-1])
    assert set(linha) == {"em", "sessao_pct", "semana_pct", "linha_pct", "nivel"}


def test_falha_de_rede_mantem_o_ultimo(_dados):
    R.medir(buscar=lambda: _bruto(30.0))
    def falha():
        raise OSError("rede")
    r = R.medir(buscar=falha)
    assert r["erro"] == "OSError" and r["semana_pct"] == 30.0


def test_contido_bloqueia_tudo_menos_canario(monkeypatch):
    monkeypatch.setattr(R, "nivel", lambda agora=None: {"nivel": "contido", "motivo": "m",
                                                        "reavaliar_em": "2026-11-16T18:30:00"})
    assert C.estado()["origem"] == "ritmo_semanal"
    assert C.motivo_bloqueio("canario") is None
    assert C.motivo_bloqueio("verificacao_opus")
    assert C.motivo_bloqueio("pericia_integral")


def test_economia_deixa_so_o_opus_que_confere(monkeypatch):
    monkeypatch.setattr(R, "nivel", lambda agora=None: {"nivel": "economia", "motivo": "m",
                                                        "reavaliar_em": "2026-11-16T18:30:00"})
    assert C.motivo_bloqueio("verificacao_opus") is None
    assert C.motivo_bloqueio("conferencia_opus") is None
    assert C.motivo_bloqueio("pericia_integral")


def test_normal_nao_ativa(monkeypatch):
    monkeypatch.setattr(R, "nivel", lambda agora=None: {"nivel": "normal", "reavaliar_em": "2026-11-16T18:30:00"})
    assert C.estado()["ativa"] is False


def test_dia_da_virada_libera_o_pesado_ate_100():
    """Dono 20/11/2026: pesado no sábado para usar toda a cota da semana antes da virada."""
    volta = datetime(2026, 11, 21, 19, 0).timestamp()          # sábado 19:00
    agora = datetime(2026, 11, 21, 9, 0).timestamp()           # sábado 09:00
    assert not R.dia_da_virada(volta, datetime(2026, 11, 20, 20, 0).timestamp())   # sexta à noite: ainda não
    m = {"medido_ts": agora, "semana_pct": 90.0, "semana_volta": R._iso(volta)}
    c = R.classificar(m, agora)
    assert c["nivel"] == "normal" and c["janela_final"] and c["linha_pct"] == 100.0
    m["semana_pct"] = 97.0
    assert R.classificar(m, agora)["nivel"] == "contido"                          # 09:00: teto 97
    tarde = datetime(2026, 11, 21, 17, 30).timestamp()                             # 17:30: os 3% guardados
    assert R.classificar(dict(m, medido_ts=tarde), tarde)["nivel"] == "normal"
    m["semana_pct"] = 100.0
    assert R.classificar(m, agora)["nivel"] == "contido"
    m.update(semana_pct=91.0, semana_volta=R._iso(agora + 3 * 86400))  # fora do sábado: teto 90 vale
    assert R.classificar(m, agora)["nivel"] == "contido"
