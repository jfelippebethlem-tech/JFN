# -*- coding: utf-8 -*-
"""Um processo lento não pode travar o lote — e o teto precisa ABANDONAR, não esperar.

Medido no mesmo caminho de código: um processo levou **2,4 s** e outro passou de **600 s**. A
variância é POR PROCESSO (o modelo gera resposta longa para autos complexos), não por provedor nem
por tamanho de prompt — as duas hipóteses que testei antes e refutei. `best_free_chat` não aceita
timeout e a chamada bloqueia, então o teto tem de vir desta camada.

A armadilha, que custou uma medição: com `with ThreadPoolExecutor(...)`, o `__exit__` faz
`shutdown(wait=True)` e **espera a thread lenta terminar**. Com limite de 3 s, o processo ainda
levou 60 s — o teto era enfeite. Sem o `with`, e com executor de módulo, a chamada estourada fica
órfã de propósito: termina sozinha pelos timeouts de HTTP da cadeia, e ninguém espera por ela.
"""
from __future__ import annotations

import time

import tools.sei_leitura_dupla as M


def test_a_janela_lenta_e_abandonada_e_o_lote_anda(monkeypatch):
    monkeypatch.setattr(M, "_LIMITE_S", 2)
    t0 = time.time()
    r = M.extrair_interpretativo("x" * (M._JANELA * 2), "p/teste/2024",
                                 gerar=lambda p, s: (time.sleep(20), "{}")[1])
    gasto = time.time() - t0
    assert gasto < 12, f"esperou a thread lenta ({gasto:.0f}s) — o teto virou enfeite"
    assert r["estado"] == "indisponivel", "sem resposta alguma, o honesto é NÃO MEDI"


def test_o_que_ja_foi_colhido_sobrevive_ao_estouro(monkeypatch):
    """Estourar a segunda janela não pode apagar a leitura que a primeira entregou."""
    monkeypatch.setattr(M, "_LIMITE_S", 2)
    chamadas = []

    def gerar(prompt, _sis):
        chamadas.append(1)
        if len(chamadas) == 1:
            return '{"contrato": "443/2025", "dispositivo": "art. 75, VIII", "pregao": "NAO_CONSTA"}'
        time.sleep(20)
        return "{}"

    r = M.extrair_interpretativo("x" * (M._JANELA * 3), "p/teste/2024", gerar=gerar)
    assert r["estado"] == "ok" and r["fatos"]["contrato"] == "443/2025"


def test_chamadas_abandonadas_nao_congestionam_as_seguintes(monkeypatch):
    """A segunda armadilha, e ela nasceu do conserto da primeira.

    Com pool de módulo (4 trabalhadores), as chamadas ABANDONADAS ocupam os trabalhadores. A partir
    da quarta, tudo entra em fila — e o tempo de FILA conta no teto, criando estouro em cascata.
    Medido no acervo: **10 janelas estouradas para 2 processos lidos**, com uma leitura saindo
    `indisponivel` sem que o modelo tivesse falhado.

    Thread descartável por chamada resolve: a abandonada não segura trabalhador nenhum.
    """
    monkeypatch.setattr(M, "_LIMITE_S", 2)
    t0 = time.time()
    for _ in range(6):
        M.extrair_interpretativo("x" * 30_000, "p/teste/2024",
                                 gerar=lambda p, s: (time.sleep(20), "{}")[1])
    gasto = time.time() - t0
    assert gasto < 20, (
        f"6 chamadas com teto de 2 s levaram {gasto:.0f}s — as abandonadas estão congestionando")
