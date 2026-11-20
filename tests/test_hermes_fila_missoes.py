# -*- coding: utf-8 -*-
"""`/api/hermes/parar` esvazia a fila de missões.

Defeito (medido em 20/11/2026): a rota chamava `mission_queue.empty()` e `dequeue_nowait()`, que `MissionQueue`
nunca teve; o `AttributeError` caía num `except` com log de debug e a fila só crescia.
"""
import asyncio

from compliance_agent.hermes_goal import MissionQueue


def test_esvaziar_tira_tudo_e_diz_quantos():
    async def cenario():
        fila = MissionQueue()
        await fila.enqueue({"tipo": "missao", "texto": "a"})
        await fila.enqueue({"tipo": "missao", "texto": "b"})
        return fila.esvaziar(), fila.qsize(), fila.esvaziar()

    assert asyncio.run(cenario()) == (2, 0, 0)
