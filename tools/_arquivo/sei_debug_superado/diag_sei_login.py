#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Diagnóstico do estado do SEI pós-login: workspace? 2FA? login? E uma busca de teste."""
import asyncio
import sys
sys.path.insert(0, "/home/ubuntu/JFN")
from tools import sei_reader as SR


async def main():
    from compliance_agent.recursos import browser_lock_async
    from playwright.async_api import async_playwright
    async with browser_lock_async(espera_max=300), async_playwright() as pw:
        b = await pw.chromium.launch(headless=True, args=["--no-sandbox", "--ignore-certificate-errors"])
        ctx = await b.new_context(ignore_https_errors=True, locale="pt-BR")
        pg = await ctx.new_page()
        try:
            ok = await SR.login(pg, tentativas=30)
            print("login() retornou:", ok)
            print("URL pós-login:", pg.url[:110])
            body = (await pg.inner_text("body"))[:600] if await pg.query_selector("body") else ""
            low = body.lower()
            sinais = {
                "2FA/dois fatores": "dois fatores" in low or "autenticação em dois" in low,
                "tela de login (Usuário/Senha)": "senha" in low and "acessar" in low,
                "workspace (Controle de Processos)": "controle de processos" in low or "iniciar processo" in low,
                "captcha": "captcha" in low,
                "bloqueio/erro": "bloquead" in low or "indisponível" in low or "erro" in low,
            }
            for k, v in sinais.items():
                print(f"  [{'✓' if v else ' '}] {k}")
            print("\nbody[:400]:", repr(body[:400]))
        finally:
            await b.close()


asyncio.run(main())
