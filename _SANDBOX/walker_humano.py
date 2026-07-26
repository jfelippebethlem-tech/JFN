#!/usr/bin/env python3
"""Walker-humano: percorre o painel como um usuário — login, abertura frame a
frame, todas as abas — coletando EVIDÊNCIA (fase 1 do systematic-debugging).

Saída: screenshots/walker/ + walker_laudo.json com, por aba:
  erros de console, tamanho do conteúdo, cliques sondados, sinais de vazio.
Não conserta nada — só enxerga.
"""
import json
import pathlib
import time

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path("/home/ubuntu/JFN")
OUT = ROOT / "screenshots" / "walker"
OUT.mkdir(parents=True, exist_ok=True)


def senha():
    for line in (ROOT / ".env").read_text().splitlines():
        if line.startswith("JFN_DASH_PASSWORD="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def main():
    laudo = {"portal": {}, "abas": {}}
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--no-sandbox"])
        ctx = b.new_context(viewport={"width": 1600, "height": 1000})
        pg = ctx.new_page()
        erros = []
        pg.on("console", lambda m: erros.append(m.text[:160]) if m.type == "error" else None)
        pg.on("pageerror", lambda e: erros.append("PAGEERROR: " + str(e)[:160]))

        # 1. LOGIN (como humano: digita e envia)
        pg.goto("http://127.0.0.1:8000/login_jfn", wait_until="load")
        pg.screenshot(path=str(OUT / "00-login.png"))
        pg.fill("input[name=senha]", senha())
        pg.press("input[name=senha]", "Enter")
        pg.wait_for_timeout(1200)

        # 2. ABERTURA frame a frame (portal ~2.4s)
        pg.goto("http://127.0.0.1:8000/painel", wait_until="load")
        for i in range(9):
            pg.screenshot(path=str(OUT / f"01-portal-{i:02d}.png"))
            pg.wait_for_timeout(400)
        laudo["portal"]["erros"] = list(erros)

        # 3. TODAS as abas
        tabs = pg.evaluate("Object.values(TABS).flat().map(t=>t.id)")
        for aba in tabs:
            del erros[:]
            try:
                pg.evaluate("id => ir(id)", aba)
            except Exception as e:  # noqa: BLE001
                laudo["abas"][aba] = {"falha_ir": str(e)[:160]}
                continue
            pg.wait_for_timeout(4500)
            info = pg.evaluate(
                """(()=>{const v=document.getElementById('view');
                  const cards=v.querySelectorAll('.card,.lnk,table,li').length;
                  const texto=v.innerText.trim().length;
                  const clicaveis=v.querySelectorAll('[onclick],button,.clk').length;
                  const skel=v.querySelectorAll('.skel').length;
                  const invisiveis=[...v.querySelectorAll('.card')].filter(c=>{
                    const s=getComputedStyle(c);return s.opacity==='0'||s.visibility==='hidden';}).length;
                  return {cards,texto,clicaveis,skel,invisiveis,
                    altura:v.scrollHeight};})()"""
            )
            # sonda de clique: primeiro elemento clicável do conteúdo
            clique = None
            try:
                alvo = pg.query_selector("#view [onclick], #view .clk, #view button")
                if alvo:
                    alvo.click(timeout=2000)
                    pg.wait_for_timeout(900)
                    clique = "ok"
                    pg.keyboard.press("Escape")
            except Exception as e:  # noqa: BLE001
                clique = "FALHOU: " + str(e)[:120]
            try:
                # VM de 2 vCPU: em aba longa (154 cards, 26k px) a captura
                # estoura os 30s padrao. Timeout folgado + animacoes paradas.
                pg.screenshot(path=str(OUT / f"10-{aba}.png"), timeout=90000,
                              animations="disabled")
            except Exception as e:  # noqa: BLE001
                info_shot = "SHOT FALHOU: " + str(e)[:80]
            else:
                info_shot = None
            info["clique"] = clique
            if info_shot:
                info["shot"] = info_shot
            info["erros"] = list(erros)
            laudo["abas"][aba] = info

        b.close()
    (OUT / "walker_laudo.json").write_text(json.dumps(laudo, ensure_ascii=False, indent=1))
    # resumo triado: só o que cheira a defeito
    ruins = {}
    for aba, i in laudo["abas"].items():
        sinais = []
        if i.get("falha_ir"):
            sinais.append("ir() FALHOU")
        if i.get("erros"):
            sinais.append(f"{len(i['erros'])} erro(s) console")
        if i.get("invisiveis"):
            sinais.append(f"{i['invisiveis']} card(s) invisível(is)")
        if i.get("texto", 1) < 120:
            sinais.append(f"conteúdo raso ({i.get('texto')} chars)")
        if i.get("skel"):
            sinais.append("skeleton preso")
        if isinstance(i.get("clique"), str) and i["clique"].startswith("FALHOU"):
            sinais.append(i["clique"][:60])
        if sinais:
            ruins[aba] = sinais
    print(json.dumps({"abas_com_sinal": ruins,
                      "portal_erros": laudo["portal"]["erros"][:5],
                      "total_abas": len(laudo["abas"])}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
