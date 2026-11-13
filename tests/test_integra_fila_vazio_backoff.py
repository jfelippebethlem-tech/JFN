# -*- coding: utf-8 -*-
"""Captura que volta VAZIA não pode encabeçar a fila de íntegras toda noite.

Medido em 2026-11-13 em `data/sei_integra_fila.log` (30 dias, 14/10→13/11): 1.384 rodadas
"ok" sobre só 140 processos; **1.202 delas (87%) caíram em 48 processos cuja captura termina
VAZIA** (manifesto `captura_vazia`, 0 documento) — cada um retentado 25 a 36 vezes, ~3 min de
browser por vez. Na rodada noturna de 2 h (`--geral --segundos 7200`) isso foi **40,5 h de
52,5 h (77%)**, contra 3,9 h de captura que rendeu documento. A causa dupla:

1. `_baixar_e_arquivar` devolvia **"ok"** quando `sei_integra_completa` não abria a árvore
   (sai com 0) — o log dizia sucesso e escondia o vazio.
2. `_arquivado_ok` (corretamente) não dá por arquivado um manifesto sem documento, então o
   processo voltava à fila na rodada seguinte, sem espera nenhuma — e os inscritos vêm primeiro.

O conserto NÃO afirma causa (vazio ≠ restrito ≠ inexistente; o acesso é liberado): só dá um
intervalo a quem acabou de voltar vazio, e o processo volta sozinho depois dele.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import tools.sei_integra_fila as F


def _manifesto(pasta, *, docs, gerado_em, captura_vazia=None):
    pasta.mkdir(parents=True, exist_ok=True)
    m = {"processo": "x", "gerado_em": gerado_em, "docs": docs}
    if captura_vazia is not None:
        m["captura_vazia"] = captura_vazia
    (pasta / "manifest.json").write_text(json.dumps(m), encoding="utf-8")
    return pasta


def _iso(dias_atras: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=dias_atras)).isoformat(timespec="seconds")


# ── o veredito "captura vazia" é lido do manifesto, nos dois formatos que existem ──

def test_manifesto_captura_vazia_e_vazio(tmp_path):
    d = _manifesto(tmp_path / "a", docs=0, gerado_em=_iso(0), captura_vazia=True)
    assert F._captura_vazia(d) is True


def test_manifesto_com_lista_vazia_e_vazio(tmp_path):
    d = _manifesto(tmp_path / "a", docs=[], gerado_em=_iso(0))
    assert F._captura_vazia(d) is True


def test_manifesto_com_documentos_nao_e_vazio(tmp_path):
    d = _manifesto(tmp_path / "a", docs=[{"i": 0, "chars": 900}], gerado_em=_iso(0))
    assert F._captura_vazia(d) is False


def test_sem_manifesto_nao_e_vazio(tmp_path):
    """Nunca tentado não é "voltou vazio" — esse tem de ir para a fila normalmente."""
    assert F._captura_vazia(tmp_path / "nunca") is False


# ── o intervalo ──

def test_vazio_recente_espera(tmp_path):
    d = _manifesto(tmp_path / "a", docs=0, gerado_em=_iso(1), captura_vazia=True)
    assert F._vazio_recente(d) is True


def test_vazio_antigo_volta_a_fila(tmp_path):
    """Desistir não é para sempre: passado o intervalo, tenta de novo."""
    d = _manifesto(tmp_path / "a", docs=0, gerado_em=_iso(F.DIAS_ESPERA_VAZIO + 1), captura_vazia=True)
    assert F._vazio_recente(d) is False


def test_vazio_sem_data_nao_e_segurado(tmp_path):
    """Sem data não há como saber quando foi: na dúvida, não nega a tentativa."""
    d = _manifesto(tmp_path / "a", docs=0, gerado_em="", captura_vazia=True)
    assert F._vazio_recente(d) is False


def test_com_documentos_nunca_e_segurado(tmp_path):
    d = _manifesto(tmp_path / "a", docs=[{"i": 0, "chars": 10}], gerado_em=_iso(0))
    assert F._vazio_recente(d) is False


# ── o status honesto ──

def test_captura_que_termina_vazia_nao_e_ok(tmp_path, monkeypatch):
    """rc=0 dos dois passos e manifesto vazio = "vazio", não "ok"."""
    arq = tmp_path / "sei_arquivo"
    monkeypatch.setattr(F, "ARQUIVO", arq)

    class _R:
        returncode = 0
        stdout = "login OK\nSEM ÁRVORE (processo não abriu) — via='cracked' erro_cracked=None\n"

    def _fake(cmd, **kw):
        if "sei_arquivar.py" in " ".join(cmd):
            _manifesto(arq / "030001_008372_2024", docs=0, gerado_em=_iso(0), captura_vazia=True)
        return _R()

    monkeypatch.setattr(F.subprocess, "run", _fake)
    linhas = []
    monkeypatch.setattr(F, "_log", linhas.append)
    assert F._baixar_e_arquivar("030001/008372/2024", {}) == "vazio"
    assert any("SEM ÁRVORE" in x for x in linhas), "a causa que a captura conhece tem de chegar ao log"


def test_captura_com_documentos_continua_ok(tmp_path, monkeypatch):
    arq = tmp_path / "sei_arquivo"
    monkeypatch.setattr(F, "ARQUIVO", arq)

    class _R:
        returncode = 0
        stdout = "baixando 12 docs…\n"

    def _fake(cmd, **kw):
        if "sei_arquivar.py" in " ".join(cmd):
            _manifesto(arq / "030001_008372_2024", docs=[{"i": 0, "chars": 900}], gerado_em=_iso(0))
        return _R()

    monkeypatch.setattr(F.subprocess, "run", _fake)
    assert F._baixar_e_arquivar("030001/008372/2024", {}) == "ok"


# ── códigos de saída distintos da captura (laudo dos motores 13/11, P1) ──

def _rc(monkeypatch, rc_captura, arq, gravar_manifesto=True):
    chamadas = []

    class _R:
        def __init__(self, rc, out=""):
            self.returncode, self.stdout = rc, out

    def _fake(cmd, **kw):
        chamadas.append(" ".join(cmd))
        if "sei_arquivar.py" in chamadas[-1]:
            if gravar_manifesto:
                _manifesto(arq / "030001_008372_2024", docs=0, gerado_em=_iso(0), captura_vazia=True)
            return _R(0)
        return _R(rc_captura, "SEM ÁRVORE (processo não abriu) — via='cracked'\n" if rc_captura == 4
                  else "LOGIN FALHOU\n")

    monkeypatch.setattr(F.subprocess, "run", _fake)
    monkeypatch.setattr(F, "_log", lambda m: None)
    return chamadas


def test_login_falho_e_status_proprio_e_nao_arquiva(tmp_path, monkeypatch):
    """Login que não completou não diz nada sobre o processo: não arquiva manifesto vazio
    (que o seguraria 7 dias) e não é "ok"."""
    arq = tmp_path / "sei_arquivo"
    monkeypatch.setattr(F, "ARQUIVO", arq)
    chamadas = _rc(monkeypatch, F.RC_LOGIN_FALHOU, arq)
    assert F._baixar_e_arquivar("030001/008372/2024", {}) == "login"
    assert not any("sei_arquivar.py" in c for c in chamadas)


def test_sem_arvore_e_status_proprio_e_registra_o_vazio(tmp_path, monkeypatch):
    """Árvore que não abriu: arquiva (o manifesto `captura_vazia` é o que dá o intervalo) e
    devolve "sem_arvore", nunca "ok"."""
    arq = tmp_path / "sei_arquivo"
    monkeypatch.setattr(F, "ARQUIVO", arq)
    chamadas = _rc(monkeypatch, F.RC_SEM_ARVORE, arq)
    assert F._baixar_e_arquivar("030001/008372/2024", {}) == "sem_arvore"
    assert any("sei_arquivar.py" in c for c in chamadas)


def test_captura_sai_com_codigos_distintos():
    """O roteiro de captura tem de SAIR com esses códigos (antes: `return` → 0 nos dois casos)."""
    from pathlib import Path
    fonte = (Path(F.__file__).parent / "sei_integra_completa.py").read_text(encoding="utf-8")
    assert "return RC_LOGIN_FALHOU" in fonte and "return RC_SEM_ARVORE" in fonte
    import tools.sei_integra_completa as C
    assert (C.RC_LOGIN_FALHOU, C.RC_SEM_ARVORE) == (F.RC_LOGIN_FALHOU, F.RC_SEM_ARVORE)


# ── a seleção da rodada pula quem acabou de voltar vazio, e declara quantos ──

def test_rodada_pula_vazio_recente_e_declara(tmp_path, monkeypatch):
    arq = tmp_path / "sei_arquivo"
    _manifesto(arq / "030001_008372_2024", docs=0, gerado_em=_iso(1), captura_vazia=True)
    _manifesto(arq / "420001_003257_2024", docs=0, gerado_em=_iso(30), captura_vazia=True)
    monkeypatch.setattr(F, "ARQUIVO", arq)
    monkeypatch.setattr(F, "_ja_rodando", lambda: False)
    monkeypatch.setattr(F, "_fila_geral", lambda: [{"sei": "SEI-510001/001518/2025"}])
    monkeypatch.setattr(F, "_fila_inscrita",
                        lambda: ["SEI-030001/008372/2024", "SEI-420001/003257/2024"])
    monkeypatch.setattr(F, "_fila_reler_por_ob", lambda: [])
    monkeypatch.setattr(F, "_esperar_browser_livre", lambda *a, **k: None)
    monkeypatch.setattr(F, "PAUSA", tmp_path / ".p1")
    monkeypatch.setattr(F, "PAUSA_SEI", tmp_path / ".p2")
    tentados = []
    monkeypatch.setattr(F, "_rodar_fila", lambda alvos, env, dl, log: tentados.extend(alvos) or len(alvos))
    linhas = []
    monkeypatch.setattr(F, "_log", linhas.append)
    monkeypatch.setattr("sys.argv", ["sei_integra_fila.py", "--geral", "--segundos", "60"])

    F.main()

    assert "030001/008372/2024" not in tentados, "vazio de ontem não pode encabeçar a rodada de hoje"
    assert tentados == ["420001/003257/2024", "510001/001518/2025"], tentados
    assert any("captura vazia" in x and "1 " in x for x in linhas), linhas
