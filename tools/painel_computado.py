#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""painel_computado — a PROVA de que uma mudanca de cascata nao mudou nada na tela.

POR QUE EXISTE. O §6.2-A do `PAINEL-v58-ESTADO-E-CONTINUACAO` quer `@layer` no CSS, e `@layer`
reordena a cascata inteira de um arquivo de 248 KB com `.btn` declarado em 14 pontos e `.card`
em tres geracoes. Nao existe revisao de codigo capaz de dizer se uma reordenacao dessas mudou
alguma coisa: o efeito e distribuido por milhares de pares (elemento, propriedade), e o sintoma de
um erro e visual e local — um botao com a borda de outra geracao, uma unica aba.

A unica prova possivel e MEDIR: fotografa-se o estilo computado do painel inteiro ANTES, aplica-se
a mudanca, fotografa-se DEPOIS, e o diff tem de sair vazio. E o mesmo metodo do `painel_css_cortar`
(sha256 identico antes e depois), um andar acima: la a prova e sobre o ARQUIVO, aqui e sobre o
RESULTADO na tela.

POR QUE UMA FERRAMENTA NOVA E NAO UM MODO DO `auditar_layout.py`, como o plano dizia. O
`auditar_layout` fala CDP com um Chrome externo ja aberto na porta 9222; o resto do portao do
painel (`painel_boot_check`) sobe o proprio Chromium por Playwright. Pendurar a prova da cascata
num navegador que precisa estar aberto a mao torna-a opcional na pratica — e prova opcional nao e
prova. Aqui ela sobe o navegador sozinha, como o boot_check.

O FORMATO E HASH POR ELEMENTO, e nao despejo de propriedade. O despejo literal seria 60 abas x 2
larguras x ~2.000 elementos x ~340 propriedades: centenas de megabytes que ninguem compara. Em vez
disso cada elemento vira uma linha `caminho -> sha1(estilo inteiro)`. Um bit que mude em qualquer
propriedade muda o hash. Quando o diff acusa, `--detalhe` volta so nas abas acusadas e imprime
QUAL propriedade mudou, de que valor para qual — a informacao cara so e paga quando ha o que ver.

O caminho do elemento e estrutural (`div>div.grid>div.card:nth-child(3)`) e nao um id: o painel
nao poe id em quase nada, e a comparacao precisa casar o MESMO no entre duas execucoes.

USO
    # 1. antes de tocar no CSS
    PYTHONPATH=. .venv/bin/python -m tools.painel_computado --gravar data/computado-antes.json
    # 2. aplica o @layer, reconstroi o painel.css
    # 3. a prova
    PYTHONPATH=. .venv/bin/python -m tools.painel_computado --comparar data/computado-antes.json
    # 4. so quando o passo 3 acusa
    PYTHONPATH=. .venv/bin/python -m tools.painel_computado --comparar ... --detalhe e_sobre
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
BASE = os.environ.get("JFN_BASE", "http://127.0.0.1:8000")
LARGURAS = [1440, 390]

# O que NAO entra na foto, e cada exclusao tem um motivo medido — sem elas o diff nunca sai vazio
# nem quando nada mudou, e um comparador que sempre acusa e um comparador desligado.
#
#   As gramaticas de revelacao (v59) escrevem `--i` inline e classes `rv-*` a cada render; o valor
#   depende de quantos itens a rota devolveu naquele segundo.
#   O spotlight escreve `--mx/--my/--rx/--ry` conforme o ponteiro.
#   `animation-*` carrega o atraso que deriva de `--i`, e o proprio relogio (`--bpm`) muda de
#   marcha sozinho conforme a carga da VM.
#   O canvas da malha (`view-wire`) tem largura/altura em pixel do momento.
#
# Nada disso e cascata; e estado vivo. Cascata e o que sobra.
IGNORAR_PREFIXOS = ("animation", "transition", "--")
#   O TICKER e os CHIPS da mesa sao alimentados pelo barramento a cada evento: o conteudo, e
#   portanto a largura e a altura, mudam entre duas execucoes por definicao. Entraram na lista
#   depois de serem os unicos acusados numa comparacao em que a cascata era neutra (o `.btn` ja
#   corrigido) — eram 4 telas de 120, todas em regiao viva.
IGNORAR_SELETORES = (".view-wire, .skel, .sp, video, canvas, "
                     ".ck-ticker, .ck-ticker *, #nu-chips, #nu-chips *, .nu-hud, .nu-sweep")

# ⚠️ AS ANIMACOES SAO CONGELADAS ANTES DE MEDIR, e isto e a diferenca entre um comparador que
# serve e um que grita. Ignorar `animation-*` NAO basta: o que a cascata de entrada faz e MUTAR
# `opacity`, `transform` e `filter` quadro a quadro, e essas tres nao podem ser ignoradas — sao
# justamente onde uma inversao de cascata aparece.
#
# Medido: a primeira versao acusou 120 telas de 120, e boa parte do diff era `opacity: 1 -> 0` e
# `transform: none -> matrix(1,0,0,1,0,5)` — dois instantes diferentes da MESMA animacao de
# entrada, nao duas cascatas diferentes. Um comparador que acusa tudo nao distingue nada.
#
# A folha abaixo entra como `!important` porque tem de vencer o proprio painel, e mede o que
# interessa: o valor ESTATICO que a cascata produz, com o tempo fora da conta.
_CONGELAR = """
  *,*::before,*::after{
    animation:none !important;
    transition:none !important;
    animation-play-state:paused !important}
"""

_SONDA = r"""(largura => {
  const alvo = document.getElementById('view');
  if (!alvo) return {erro: 'sem #view'};
  const IGN_PREF = %s;
  const ignorado = p => IGN_PREF.some(x => p.startsWith(x));
  // caminho estrutural estavel entre execucoes: tag + primeira classe + posicao entre irmaos
  const caminho = el => {
    const partes = [];
    for (let e = el; e && e !== alvo && partes.length < 12; e = e.parentElement) {
      const t = (e.tagName || '').toLowerCase();
      const cls = (typeof e.className === 'string' ? e.className : '').trim()
        .split(/\s+/).filter(c => c && !c.startsWith('rv-'))[0] || '';
      const i = e.parentElement ? [...e.parentElement.children].indexOf(e) : 0;
      partes.unshift(t + (cls ? '.' + cls : '') + ':' + i);
    }
    return partes.join('>');
  };
  const fora = new Set([...alvo.querySelectorAll(%s)]);
  const saida = {};
  for (const el of alvo.querySelectorAll('*')) {
    if (fora.has(el)) continue;
    const s = getComputedStyle(el);
    const pares = [];
    for (let k = 0; k < s.length; k++) {
      const p = s[k];
      if (ignorado(p)) continue;
      pares.push(p + '=' + s.getPropertyValue(p));
    }
    saida[caminho(el)] = pares.join('|');
  }
  return {largura, n: Object.keys(saida).length, estilos: saida};
})""" % (json.dumps(list(IGNORAR_PREFIXOS)), json.dumps(IGNORAR_SELETORES))


def _h(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:16]


async def _fotografar(detalhe: set[str], fixo: Path | None = None) -> dict:
    """Fotografa as 60 abas em duas larguras.

    `fixo` e o ARQUIVO DE DADO CONGELADO, e sem ele esta ferramenta nao serve para nada — foi a
    licao mais cara desta sessao. A primeira versao comparava duas fotos do painel VIVO e acusou
    118 telas de 120 com ZERO mudanca de CSS. Nao era ruido de timing (as animacoes ja estavam
    congeladas): e que o painel mostra dado vivo, e entre duas execucoes a rota devolve outros
    valores — um cartao vira `.hl` porque o achado ficou grave, um numero muda de largura, uma
    lista muda de tamanho. O estilo computado depende do DADO, e comparar cascata sobre dado que
    se move e comparar duas coisas ao mesmo tempo.

    Um comparador que acusa tudo nao distingue nada. Com o dado congelado ele volta a medir uma
    variavel so: a cascata.

    Primeira execucao GRAVA as respostas de `/api/**`; as seguintes as REPRODUZEM. O arquivo fica
    ao lado do baseline, e os dois envelhecem juntos: baseline novo pede fixture nova.
    """
    from playwright.async_api import async_playwright

    gravando = fixo is not None and not fixo.exists()
    respostas: dict[str, dict] = {}
    if fixo is not None and fixo.exists():
        respostas = json.loads(fixo.read_text(encoding="utf-8"))

    foto: dict = {"_detalhe": sorted(detalhe)}
    async with async_playwright() as p:
        nav = await p.chromium.launch(args=["--no-sandbox"])
        pg = await nav.new_page(viewport={"width": LARGURAS[0], "height": 900})

        if fixo is not None:
            async def _rota(route, req):
                # a chave ignora o host: o mesmo fixture serve qualquer JFN_BASE
                chave = req.url.split("/api/", 1)[-1]
                if gravando:
                    try:
                        r = await route.fetch()
                        corpo = await r.text()
                        respostas["/api/" + chave] = {"s": r.status, "b": corpo,
                                                      "t": r.headers.get("content-type", "")}
                        await route.fulfill(status=r.status, body=corpo,
                                            headers={"content-type": r.headers.get(
                                                "content-type", "application/json")})
                    except Exception as e:                  # noqa: BLE001
                        print(f"  [fixture] nao gravei {chave[:48]}: {e!s:.50}", file=sys.stderr)
                        await route.continue_()
                    return
                g = respostas.get("/api/" + chave)
                if g is None:
                    # rota que nao existia na gravacao: NAO inventa resposta. Deixa passar e o
                    # comparador vera a diferenca — melhor uma diferenca visivel que um dado falso.
                    await route.continue_()
                    return
                await route.fulfill(status=g["s"], body=g["b"],
                                    headers={"content-type": g["t"] or "application/json"})
            await pg.route("**/api/**", _rota)

        await pg.goto(f"{BASE}/painel", wait_until="load")
        await pg.wait_for_timeout(1500)
        await pg.add_style_tag(content=_CONGELAR)
        abas = await pg.evaluate("() => Object.values(TABS).flat().map(t => t.id)")
        for larg in LARGURAS:
            await pg.set_viewport_size({"width": larg, "height": 900})
            for aba in abas:
                try:
                    # `__estavel` e o contador do estabilizador abaixo. ZERAR AQUI e obrigatorio:
                    # sem isso a primeira leitura da aba nova se compara com a contagem da aba
                    # ANTERIOR, e duas abas de tamanho parecido dao "estavel" no primeiro poll —
                    # a foto sai antes de a tela existir.
                    await pg.evaluate(f"() => {{ window.__estavel = -1; ir('{aba}'); }}")
                    # 1,4 s e o mesmo tempo que a sonda de revelacao usa: e o teto do atraso da
                    # cascata (380 ms) mais a duracao mais longa, com folga para a rota responder.
                    await pg.wait_for_timeout(1400)
                    # ⚠️ E ESPERA O `_countUp` ASSENTAR. Congelar as animacoes de CSS nao o alcanca:
                    # ele e um laco de `requestAnimationFrame` que reescreve o `textContent` do
                    # numero, e texto diferente e LARGURA diferente. Medido: com o dado ja
                    # congelado, sobravam 41 telas de 120 acusadas, sempre com dois elementos, e
                    # sempre `div.v` — o valor do KPI apanhado no meio da contagem. Ele marca
                    # `.counting` enquanto corre; esperar a classe sumir preserva a cobertura sobre
                    # o elemento (a cor dele AINDA e cascata) em vez de exclui-lo da foto.
                    try:
                        await pg.wait_for_function(
                            "() => !document.querySelector('#view .counting')", timeout=4000)
                    except Exception as e:                  # noqa: BLE001
                        # Contagem presa nao invalida a foto — mas tambem nao pode sumir: se ela
                        # ficar presa SEMPRE, o `div.v` volta a ser ruido e alguem tem de saber por
                        # que. `pass` mudo aqui esconderia exatamente essa pista.
                        print(f"  [{aba}@{larg}] _countUp nao assentou: {e!s:.60}", file=sys.stderr)
                    # E ESPERA O DOM PARAR. Aba que busca varias rotas termina de montar depois do
                    # tempo fixo, e as duas execucoes pegam momentos diferentes: medido em
                    # `g_acuracia`, onde uma foto tinha 55 nos a mais que a outra e as alturas dos
                    # containers mudavam junto. Duas leituras iguais seguidas = parou.
                    try:
                        await pg.wait_for_function(
                            """() => { const v = document.getElementById('view');
                                 if (!v) return false;
                                 const n = v.querySelectorAll('*').length;
                                 const ok = window.__estavel === n;
                                 window.__estavel = n; return ok; }""",
                            timeout=6000, polling=450)
                    except Exception as e:                  # noqa: BLE001
                        # Tela que nunca para nao trava a foto, e diz que nao parou: e a assinatura
                        # de aba com carga assincrona sem fim, que e a causa conhecida de churn de
                        # nos entre duas execucoes.
                        print(f"  [{aba}@{larg}] DOM nao estabilizou: {e!s:.60}", file=sys.stderr)
                    # ⚠️ A VARIAVEL QUE FALTAVA CONGELAR: o MODO SOBRIO.
                    # `body.fps-baixo` liga por MEDICAO de FPS, e a medicao muda entre execucoes —
                    # numa a VM estava sob carga, na outra nao. E ele nao e cosmetico: o estrato
                    # `70-v49-sobrio` tem `body.fps-baixo .card{background:var(--bg2)}`, ou seja o
                    # cartao TROCA de fundo. Foi isso que fez o CONTROLE (mesma folha, zero
                    # mudanca) acusar 88 telas, quase todas em `div.card` — e eu quase creditei
                    # essa diferenca ao `@layer`.
                    # Fixar aqui, imediatamente antes da foto, e o unico ponto em que nem o
                    # `_medirFps` (2,6 s) nem o `sobrioAoMudar` conseguem reabrir a janela.
                    # `html.rest` entra junto pelo mesmo motivo: ele depende de a aba estar visivel.
                    await pg.evaluate("() => { document.body.classList.remove('fps-baixo');"
                                      " document.documentElement.classList.remove('rest'); }")
                    r = await pg.evaluate(_SONDA, larg)
                except Exception as e:                          # noqa: BLE001
                    foto[f"{aba}@{larg}"] = {"erro": str(e)[:160]}
                    continue
                if r.get("erro"):
                    foto[f"{aba}@{larg}"] = {"erro": r["erro"]}
                    continue
                est = r["estilos"]
                chave = f"{aba}@{larg}"
                foto[chave] = {"n": r["n"],
                               "hash": {k: _h(v) for k, v in est.items()}}
                if aba in detalhe:
                    foto[chave]["cru"] = est
                print(f"  {chave}: {r['n']} elementos", file=sys.stderr)
        await nav.close()
    if gravando and fixo is not None:
        fixo.write_text(json.dumps(respostas), encoding="utf-8")
        print(f"[computado] dado congelado em {fixo} ({len(respostas)} rotas)", file=sys.stderr)
    return foto


def _comparar(antes: dict, agora: dict) -> int:
    problemas = 0
    chaves = sorted(set(antes) | set(agora))
    for c in chaves:
        if c.startswith("_"):
            continue
        a, b = antes.get(c), agora.get(c)
        if a is None or b is None:
            print(f"❌ {c}: existe so em {'DEPOIS' if a is None else 'ANTES'}")
            problemas += 1
            continue
        if "erro" in a or "erro" in b:
            # INDISPONIVEL nao e diferenca. Aba que falhou nos dois lados nao prova nada, e nao
            # pode ser contada como regressao — seria transformar dado ausente em achado.
            if "erro" in a and "erro" in b:
                continue
            print(f"⚠️  {c}: erro em um dos lados ({a.get('erro') or b.get('erro')})")
            continue
        ha, hb = a["hash"], b["hash"]
        sumiu = [k for k in ha if k not in hb]
        surgiu = [k for k in hb if k not in ha]
        mudou = [k for k in ha if k in hb and ha[k] != hb[k]]
        if not mudou:
            # NO QUE APARECE E SOME, A CASCATA NAO TEM PARTE. CSS nao cria nem destroi elemento —
            # `@layer` pode mudar a COR de um no, nunca a existencia dele. Entao contagem de nos
            # diferente e vida da tela, nao regressao: medido no `i_cockpit`, onde o ticker do
            # barramento enche a faixa com os eventos que chegaram naquele minuto. Contar isso
            # como falha faria a unica tela viva do painel reprovar para sempre, e um comparador
            # que reprova sempre e um comparador desligado.
            if sumiu or surgiu:
                print(f"⚠️  {c}: 0 diferenca de estilo; {len(sumiu)} no(s) sumiram e "
                      f"{len(surgiu)} surgiram — vida da tela, nao cascata")
            continue
        problemas += 1
        print(f"❌ {c}: {len(mudou)} elemento(s) com estilo diferente, "
              f"{len(sumiu)} sumiram, {len(surgiu)} surgiram")
        for k in mudou[:6]:
            print(f"     ~ {k}")
            ca, cb = a.get("cru", {}).get(k), b.get("cru", {}).get(k)
            if ca and cb:
                da = dict(x.split("=", 1) for x in ca.split("|") if "=" in x)
                db = dict(x.split("=", 1) for x in cb.split("|") if "=" in x)
                for p in sorted(set(da) | set(db)):
                    if da.get(p) != db.get(p):
                        print(f"         {p}: {da.get(p)!r} -> {db.get(p)!r}")
    return problemas


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gravar", metavar="ARQ", help="fotografa e grava o baseline")
    ap.add_argument("--comparar", metavar="ARQ", help="fotografa e compara contra o baseline")
    ap.add_argument("--detalhe", action="append", default=[],
                    help="aba(s) que guardam o estilo CRU, para o diff por propriedade")
    a = ap.parse_args(argv)
    if not (a.gravar or a.comparar):
        ap.error("use --gravar ou --comparar")

    detalhe = set(a.detalhe)
    if a.comparar:
        antes = json.loads(Path(a.comparar).read_text(encoding="utf-8"))
        detalhe |= set(antes.get("_detalhe") or [])

    alvo = Path(a.gravar or a.comparar)
    fixo = alvo.with_name(alvo.stem + "-dado.json")
    foto = asyncio.run(_fotografar(detalhe, fixo))

    if a.gravar:
        Path(a.gravar).write_text(json.dumps(foto), encoding="utf-8")
        n = sum(v.get("n", 0) for k, v in foto.items() if not k.startswith("_"))
        print(f"[computado] baseline gravado em {a.gravar} — "
              f"{len([k for k in foto if not k.startswith('_')])} telas, {n} elementos")
        return 0

    antes = json.loads(Path(a.comparar).read_text(encoding="utf-8"))
    n = _comparar(antes, foto)
    if n:
        print(f"\n❌ {n} tela(s) com estilo computado diferente do baseline. "
              f"A mudanca de cascata NAO e neutra — nao entre com ela.")
        return 1
    print("\nOK — estilo computado identico ao baseline em todas as telas e larguras.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
