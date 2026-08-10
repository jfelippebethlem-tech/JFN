#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Os cinco painéis de PADRÃO nascem depois de um CLIQUE — e nada os testava.

`painel_boot_check` percorre abas e falha em `pageerror`; mas os cards da fila do fiscal (taxa por
unidade, janela de fim de exercício, concentração por grupo, coparticipação de relacionadas,
recuperação judicial, aditivo precoce) só são montados quando alguém aperta *"Ver a fila"*. Uma
rota que quebre, um campo renomeado, um `await` que devolva `ok:false` — nada disso apareceria no
boot, e o card simplesmente não existiria na tela, em silêncio.

Este verificador clica e confere que cada seção chegou ao DOM. É a diferença entre "a aba abre" e
"o que a aba deveria mostrar está lá".

    PYTHONPATH=. .venv/bin/python -m tools.painel_fila_check
"""
from __future__ import annotations

import asyncio
import json
import sys

URL = "http://127.0.0.1:8000/painel"
# trecho do título de cada seção esperada — casado por texto, que é o que o fiscal vê
# CASO-INSENSÍVEL de propósito: os títulos passam por `text-transform: uppercase` e o
# `inner_text` do navegador devolve o texto TRANSFORMADO — procurar "Concentração por GRUPO"
# nunca casaria. Custou uma investigação inteira para descobrir isso.
ESPERADOS = (
    "o padrão por unidade",
    "pago em nov–dez",
    "concentração por grupo",
    "relacionadas no mesmo certame",
    "pagos em recuperação judicial",
    "aditivo de valor nos primeiros",
    "núcleo de arranjo",
    "um consórcio por certame",
)


async def checar(url: str = URL, espera_s: int = 120) -> dict:
    from playwright.async_api import async_playwright

    laudo: dict = {"ok": False, "pageerror": [], "faltando": [], "achados": []}
    async with async_playwright() as pw:
        b = await pw.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        pg = await (await b.new_context()).new_page()
        pg.on("pageerror", lambda e: laudo["pageerror"].append(str(e)[:300]))
        try:
            await pg.goto(url, wait_until="domcontentloaded", timeout=60_000)
            await pg.wait_for_function("typeof TABS !== 'undefined'", timeout=30_000)
            await pg.evaluate("ir('g_pecas')")
            await pg.wait_for_selector('[data-fila="todos"]', timeout=20_000)
            await pg.click('[data-fila="todos"]')
            # Cada card é um fetch próprio e alguns demoram mais de 20 s (o de coparticipação
            # cruza 82.941 licitantes). Esperar pouco daria "faltando" para card que só estava
            # a caminho — e essa foi a primeira leitura errada deste verificador.
            for _ in range(espera_s):
                texto = (await pg.inner_text("#ff-out")).lower()
                if all(e in texto for e in ESPERADOS):
                    break
                await asyncio.sleep(1)
            texto = (await pg.inner_text("#ff-out")).lower()
            laudo["achados"] = [e for e in ESPERADOS if e in texto]
            laudo["faltando"] = [e for e in ESPERADOS if e not in texto]
            laudo["ok"] = not laudo["faltando"] and not laudo["pageerror"]
        finally:
            await b.close()
    return laudo


def main() -> int:  # pragma: no cover
    laudo = asyncio.run(checar())
    print(json.dumps(laudo, ensure_ascii=False, indent=1))
    if laudo["ok"]:
        print(f"OK — os {len(ESPERADOS)} painéis da fila chegaram à tela.")
        return 0
    print(f"FALHOU — faltando: {laudo['faltando']} · pageerror: {laudo['pageerror'][:2]}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
