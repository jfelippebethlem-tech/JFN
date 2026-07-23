"""Um processo que estoura o timeout NÃO pode derrubar a fila inteira.

Bug provado em 2026-07-23 (recaptura dos 274): `subprocess.run(timeout=900)` levantava
`TimeoutExpired` NÃO capturado no loop — propagava até o `finally` (que remove as flags
de pausa e loga "encerrada") e crashava a fila. Como a fila é priorizada por exposição,
o 1º processo é sempre o maior → sempre estoura 900s → a fila SEMPRE morria no processo 1,
nunca chegando aos outros 273 (log real: 1 ÍNTEGRA, "0 arquivado(s)", traceback).

`_baixar_e_arquivar` isola o par download+arquivar e converte o timeout em status, sem
propagar. A íntegra parcial já ficou salva pelo manifesto incremental — a próxima passada
retoma. Assim o loop segue para o próximo processo.
"""
import subprocess

import tools.sei_integra_fila as F


def test_timeout_no_download_vira_status_nao_excecao(monkeypatch):
    def _fake_run(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, 900)
    monkeypatch.setattr(F.subprocess, "run", _fake_run)

    status = F._baixar_e_arquivar("260007/004617/2024", env={})

    assert status == "timeout", "timeout tem de virar status, não exceção que crasha a fila"


def test_sucesso_devolve_ok(monkeypatch):
    class _R:
        returncode = 0
    monkeypatch.setattr(F.subprocess, "run", lambda cmd, **kw: _R())

    assert F._baixar_e_arquivar("260007/004617/2024", env={}) == "ok"


def test_loop_continua_apos_um_timeout(monkeypatch):
    """O caso real: 1º processo (maior) estoura, os outros têm de ser tentados."""
    chamados = []

    def _fake(proc, env):
        chamados.append(proc)
        return "timeout" if proc == "GRANDE" else "ok"
    monkeypatch.setattr(F, "_baixar_e_arquivar", _fake)

    feitos = F._rodar_fila(["GRANDE", "p2", "p3"], env={}, deadline=None, log=lambda m: None)

    assert chamados == ["GRANDE", "p2", "p3"], "todos os processos têm de ser tentados"
    assert feitos == 3
