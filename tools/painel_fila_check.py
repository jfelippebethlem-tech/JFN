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
    # o nono: processos que a casa LEU e voltaram vazios, com a causa não medida. Entra no gate
    # porque é o card mais fácil de sumir em silêncio — ele depende de dois arquivos de estado
    # (progresso do sweep e registro de restritos) que podem simplesmente não existir.
    "voltaram vazios",
    # o décimo: o framework de detectores, que gravava em data/achados.db sem nenhum leitor
    "framework de detectores",
)


def veredito(faltando: list[str], pageerror: list[str], em_voo: list[str]) -> dict:
    """Três valores, não dois — card que não chegou porque a rota ainda VOA não é card quebrado.

    Em 2026-08-11 este verificador bloqueou um commit dizendo que três cards não chegaram; cinco
    minutos depois, com o mesmo código, os dez chegaram. A diferença era cache frio (servidor
    recém-reiniciado) somado a `load 11`: a API é single-process, as rotas pesadas serializam e as
    três últimas ainda estavam em voo quando os 120 s acabaram.

    Gate que confunde "ainda não chegou" com "não existe" treina quem trabalha a usar
    `--no-verify` — a porta pela qual já entrou painel quebrado aqui. Mesma disciplina do
    `pre_push_gate`, que acima de load 6 DECLARA que não mediu em vez de aprovar em silêncio.

    `pageerror` é exceção: é defeito de código, não lentidão, e bloqueia sempre.
    """
    if pageerror:
        return {"estado": "falhou", "bloqueia": True, "faltando": faltando,
                "em_voo": em_voo, "motivo": "pageerror no console — defeito de código"}
    if not faltando:
        return {"estado": "ok", "bloqueia": False, "faltando": [], "em_voo": em_voo,
                "motivo": "todos os painéis chegaram à tela"}
    if em_voo:
        return {"estado": "nao_medido", "bloqueia": False, "faltando": faltando, "em_voo": em_voo,
                "motivo": ("orçamento esgotado com requisição de API ainda em voo — NÃO MEDI. "
                           "Rode de novo com a API quente (ou carga menor) antes de concluir.")}
    return {"estado": "falhou", "bloqueia": True, "faltando": faltando, "em_voo": [],
            "motivo": "nenhuma requisição pendente e a seção não existe — o card não vem"}


async def checar(url: str = URL, espera_s: int = 120) -> dict:
    from playwright.async_api import async_playwright

    laudo: dict = {"ok": False, "pageerror": [], "faltando": [], "achados": [], "em_voo": []}
    # QUAIS estão pendentes, não quantos: sem o nome, ninguém sabe se a lentidão é da rota que
    # interessa ou de outra.
    voando: dict[str, int] = {}

    def _abriu(req):
        if "/api/" in req.url:
            voando[req.url.split("127.0.0.1:8000")[-1]] = 1

    def _fechou(req):
        voando.pop(req.url.split("127.0.0.1:8000")[-1], None)

    async with async_playwright() as pw:
        b = await pw.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        pg = await (await b.new_context()).new_page()
        pg.on("pageerror", lambda e: laudo["pageerror"].append(str(e)[:300]))
        pg.on("request", _abriu)
        pg.on("requestfinished", _fechou)
        pg.on("requestfailed", _fechou)
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
            laudo["em_voo"] = sorted(voando)
            laudo |= veredito(laudo["faltando"], laudo["pageerror"], laudo["em_voo"])
            laudo["ok"] = laudo["estado"] == "ok"
        finally:
            await b.close()
    return laudo


def main() -> int:  # pragma: no cover
    laudo = asyncio.run(checar())
    print(json.dumps(laudo, ensure_ascii=False, indent=1))
    if laudo["estado"] == "ok":
        print(f"OK — os {len(ESPERADOS)} painéis da fila chegaram à tela.")
        return 0
    if laudo["estado"] == "nao_medido":
        print(f"⚠️  NÃO MEDI — {laudo['motivo']}\n"
              f"    faltando: {laudo['faltando']}\n    ainda em voo: {laudo['em_voo']}")
        return 0
    print(f"FALHOU — {laudo['motivo']}\n    faltando: {laudo['faltando']} · "
          f"pageerror: {laudo['pageerror'][:2]}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
