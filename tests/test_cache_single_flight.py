"""`_cache_calc`: com o cache frio, N visitas simultâneas fazem UM cálculo (24/09/2026: 25 threads refaziam
`fornecedor_dependente` ao mesmo tempo, carga 29 em 2 vCPU, painel sem responder por mais de 120 s)."""
import threading
import time

from rotas import investigacao as inv


def test_dez_visitas_simultaneas_calculam_uma_vez():
    chave = "teste:single-flight"
    inv._cache.pop(chave, None)
    chamadas = []

    def lento():
        chamadas.append(1)
        time.sleep(0.3)
        return {"ok": True}

    res = []
    ts = [threading.Thread(target=lambda: res.append(inv._cache_calc(chave, 60, lento))) for _ in range(10)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert len(chamadas) == 1
    assert res == [{"ok": True}] * 10


def test_chaves_diferentes_nao_se_esperam():
    for k in ("teste:a", "teste:b"):
        inv._cache.pop(k, None)
    assert inv._cache_calc("teste:a", 60, lambda: {"v": 1}) == {"v": 1}
    assert inv._cache_calc("teste:b", 60, lambda: {"v": 2}) == {"v": 2}


def test_resultado_vazio_nao_fica_preso_no_cache():
    """Mesma semântica de antes: resultado falso (dict vazio) conta como ausência e recalcula."""
    inv._cache.pop("teste:vazio", None)
    n = []
    inv._cache_calc("teste:vazio", 60, lambda: n.append(1) or {})
    inv._cache_calc("teste:vazio", 60, lambda: n.append(1) or {})
    assert len(n) == 2
