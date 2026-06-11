# -*- coding: utf-8 -*-
"""Testes do browser_lock — robustez a reboot (o bug que travou o SEI sweep após restart da VM).

Um lock criado antes do último boot tem de ser considerado obsoleto na hora (PID reusado após reboot
pode parecer vivo). Também: lock de PID morto é obsoleto; lock do próprio processo vivo NÃO é."""
import os
import time

from compliance_agent import recursos


def _escreve_lock(pid, ts):
    recursos._LOCK.parent.mkdir(parents=True, exist_ok=True)
    recursos._LOCK.write_text(f"{pid}:{ts}", encoding="utf-8")


def _limpa():
    try:
        recursos._LOCK.unlink()
    except OSError:
        pass


def test_lock_anterior_ao_boot_e_obsoleto(monkeypatch):
    # boot "agora"; lock criado 1h ANTES do boot, com PID que (fingimos) está vivo → ainda assim obsoleto
    agora = time.time()
    monkeypatch.setattr(recursos, "_boot_time", lambda: agora)
    monkeypatch.setattr(recursos, "_pid_vivo", lambda pid: True)
    _escreve_lock(999999, agora - 3600)
    try:
        assert recursos._lock_obsoleto(idade_max=1800) is True
    finally:
        _limpa()


def test_lock_de_pid_morto_e_obsoleto(monkeypatch):
    monkeypatch.setattr(recursos, "_boot_time", lambda: 0.0)  # ignora boot
    monkeypatch.setattr(recursos, "_pid_vivo", lambda pid: False)
    _escreve_lock(999999, time.time())
    try:
        assert recursos._lock_obsoleto(idade_max=1800) is True
    finally:
        _limpa()


def test_lock_proprio_vivo_e_recente_nao_e_obsoleto(monkeypatch):
    # lock do PRÓPRIO processo (vivo), criado DEPOIS do boot, recente → NÃO obsoleto (não roubar lock válido)
    monkeypatch.setattr(recursos, "_boot_time", lambda: time.time() - 86400)  # boot ontem
    _escreve_lock(os.getpid(), time.time())
    try:
        assert recursos._lock_obsoleto(idade_max=1800) is False
    finally:
        _limpa()


def test_boot_time_real_le_proc_stat():
    # /proc/stat existe no Linux da VM → btime > 0 e no passado
    bt = recursos._boot_time()
    assert bt == 0.0 or (0 < bt <= time.time())


def test_aquisicao_rouba_lock_pre_boot(monkeypatch):
    # integração: com um lock pré-boot, _tentar_adquirir deve ROUBAR e adquirir p/ o processo atual
    agora = time.time()
    monkeypatch.setattr(recursos, "_boot_time", lambda: agora)
    monkeypatch.setattr(recursos, "_pid_vivo", lambda pid: True)
    _escreve_lock(999999, agora - 3600)
    try:
        assert recursos._tentar_adquirir(idade_max=1800) is True
        dono = recursos._LOCK.read_text(encoding="utf-8").split(":")[0]
        assert int(dono) == os.getpid()
    finally:
        _limpa()
