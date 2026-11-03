# -*- coding: utf-8 -*-
"""A home não espera cálculo frio: cache vencido entrega o último valor, e toda rota da home é pré-aquecida."""
import re
import threading
import time
from pathlib import Path

from rotas import investigacao as inv

RAIZ = Path(__file__).resolve().parents[1]


def test_vencido_entrega_o_velho_e_renova_em_segundo_plano(monkeypatch):
    monkeypatch.setattr(inv, "_cache", {"k": (time.time() - 99, "velho")})
    monkeypatch.setattr(inv, "_cache_travas", {})
    liberar, chamou = threading.Event(), threading.Event()

    def calc():
        chamou.set()
        liberar.wait(5)
        return "novo"
    t0 = time.time()
    assert inv._cache_calc("k", 10, calc) == "velho"
    assert time.time() - t0 < 1                       # não esperou o cálculo
    assert chamou.wait(2)
    assert inv._cache_calc("k", 10, calc) == "velho"  # recálculo em curso: não dispara outro
    liberar.set()
    for _ in range(50):
        if inv._cache["k"][1] == "novo":
            break
        time.sleep(0.05)
    assert inv._cache_calc("k", 10, calc) == "novo"


def test_frio_sem_valor_calcula_na_hora(monkeypatch):
    monkeypatch.setattr(inv, "_cache", {})
    monkeypatch.setattr(inv, "_cache_travas", {})
    assert inv._cache_calc("k", 10, lambda: 7) == 7


def test_prewarm_cobre_toda_rota_da_home():
    js = (RAIZ / "static/js/src/abas/cockpit.js").read_text(encoding="utf-8")
    home = set(re.findall(r"J\('/api/([^']+)'", js))
    sh = (RAIZ / "tools/prewarm_painel.sh").read_text(encoding="utf-8")
    aquecidas = set(re.findall(r'^\s*"([^"]+)"', sh, re.M))
    assert home and not (home - aquecidas), f"rotas da home fora do prewarm: {sorted(home - aquecidas)}"
