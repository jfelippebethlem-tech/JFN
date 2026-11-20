#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ÍNTEGRA COMPLETA de um processo SEI: pagina TODOS os documentos, baixa cada um (PDF ou HTML→PDF),
junta num PDF único e ENVIA ao Telegram (divide em partes <45MB). Conteúdo lido SEMPRE pela árvore
viva (cross-unit sem envenenar a sessão, 2026-07-23): nativo=texto do editor; escaneado=PDF original
preservado (imagens/fotos de prova) + OCR já feito por _conteudo_via_arvore. Guardado.
Uso: .venv/bin/python tools/sei_integra_completa.py "330020/000762/2021"
"""
import os
import sys
import re
import asyncio
from pathlib import Path
# A RAIZ DESTA ÁRVORE, não `/home/ubuntu/JFN` cravado: no worker da VM-2 (~/JFN-worker) o caminho fixo punha a
# cópia ANTIGA ~/JFN na frente do sys.path e o `tools.sei_reader` importado era o de lá (achado em 14/11/2026).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import sei_reader as SR
from tools import vm_guard as G
from playwright.async_api import async_playwright, Error as PWError
import httpx
import fitz

PROC = sys.argv[1] if len(sys.argv) > 1 else ""   # import (pytest) não traz argumento
# O PREFIXO `SEI-` TEM DE SAIR ANTES DO TAG. Sem isto, cada letra dele vira um underscore e o
# destino fica `integra_____080002_023009_2024`, enquanto `sei_arquivar.py` procura
# `integra_080002_023009_2024`. Medido em 2026-08-15: a captura do `080002/023009/2024` baixou os
# 69 documentos (206 MB) e o arquivamento seguinte disse "íntegra não encontrada" — 0 documentos
# arquivados, com tudo no disco. Já havia 396 diretórios nesse estado.
#
# O defeito foi DOCUMENTADO em duas rodadas anteriores e mordeu nas duas seguintes (a última
# escondeu 57 docs / 28 MB). Documentar não conserta: o conserto é esta linha.
PROC = re.sub(r"^SEI-", "", PROC.strip())
TAG = re.sub(r"[^0-9]", "_", PROC)
# Códigos de saída — antes LOGIN FALHOU e SEM ÁRVORE saíam com 0 e a fila (`sei_integra_fila`)
# chamava de "ok" uma captura sem documento nenhum (laudo dos motores, 13/11/2026: 255 "ok" em
# 7 dias, 48 processos, todos com 0 documento). 75 (adiado por carga) já existia.
RC_LOGIN_FALHOU = 3
RC_SEM_ARVORE = 4
ENV = Path.home() / ".hermes" / ".env"   # por usuário: `/home/ubuntu` cravado quebrava fora desta VM
# RENOVAÇÃO DA ABA (19/11/2026, it-campo): a aba do 150016/009553/2024 chegou a 4,9 GB de RSS no renderer após 711
# documentos — o CDP dizia 391 `Documents` e 379 `Frames` vivos com só 4 frames na árvore: cada documento clicado deixa
# o anterior desanexado e retido. A cada N documentos BAIXADOS o processo é reaberto numa aba nova (mesmo login) e a
# velha fecha. 0 desliga. Medido ao vivo (19/11, 828 nós): a reabertura custa 90–100 s (busca pelo cracked) e os
# documentos seguintes saem normais (42/42 ok) — 250 docs ≈ 1,7 GB de pico por aba e ~5–8% de tempo de reabertura.
RENOVAR_ABA_DOCS = int(os.environ.get("SEI_RENOVAR_ABA_DOCS", "250"))


def hora_de_renovar(baixados_desde: int, limite: int = RENOVAR_ABA_DOCS) -> bool:
    return limite > 0 and baixados_desde >= limite


async def renovar_aba(ctx, pg, reabrir):
    """Abre o processo numa aba NOVA (`reabrir(aba) -> bool` deixa a árvore viva nela) e só então fecha a velha.
    Falhou ou deu erro → fecha a nova e devolve a velha: a captura segue como estava, sem perder o processo."""
    nova = await ctx.new_page()
    try:
        await nova.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
        if await reabrir(nova):
            try:
                await pg.close()
            except PWError:
                pass
            return nova
        print("  aba NÃO renovada (o processo não reabriu) — sigo na aba atual", flush=True)
    except (PWError, asyncio.TimeoutError) as e:
        print(f"  aba NÃO renovada ({str(e)[:60]}) — sigo na aba atual", flush=True)
    try:
        await nova.close()
    except PWError:
        pass
    return pg
def _k(n):
    # `_k` roda no IMPORT (linha abaixo), então não pode depender de arquivo existir: o CI pegou
    # `FileNotFoundError: /home/ubuntu/.hermes/.env` importando este módulo num runner limpo.
    try:
        texto = ENV.read_text()
    except OSError:
        return ""
    m = re.search(rf"^{n}=(.+)$", texto, re.M); return m.group(1).strip().strip('"').strip("'") if m else ""
TOK, CHAT = _k("TELEGRAM_BOT_TOKEN"), _k("TELEGRAM_CHAT_ID")


def envia(path, caption):
    with open(path, "rb") as f:
        return httpx.post(f"https://api.telegram.org/bot{TOK}/sendDocument",
                          data={"chat_id": CHAT, "caption": caption[:1000]},
                          files={"document": (Path(path).name, f, "application/pdf")}, timeout=300).json().get("ok")


# Siglas que só aparecem juntas na TELA DE SELEÇÃO DE UNIDADE do SEI. Quando o
# documento é de outra unidade, o SEI não serve o teor: devolve essa lista. Capturá-la
# como conteúdo grava a relação de órgãos no lugar do comprovante/despacho — falso
# conteúdo, pior que conteúdo ausente (achado em 2026-07-23, SEI-260007/004617/2024).
_SIGLAS_UNIDADE = ("AGENERSA", "AGETRANSP", "CECIERJ", "CEHAB", "DEGASE",
                   "FAETEC", "FAPERJ", "EMATER", "DETRO", "CODIN")


def parece_pagina_de_unidade(texto: str) -> bool:
    """True se o texto é a tela de escolha de unidade, não o documento."""
    t = (texto or "").upper()
    if len(t) < 60:
        return False
    return sum(1 for s in _SIGLAS_UNIDADE if s in t) >= 5


def arvore_anterior(man_path: Path) -> int:
    """Tamanho da árvore que uma captura ANTERIOR desta pasta enumerou (0 se não houver/ilegível).

    A ENUMERAÇÃO NÃO É DETERMINÍSTICA: as pastas lazy-load da árvore às vezes não terminam de carregar e a
    lista volta menor. Medido em 18/11/2026 na VM-2: o `150016/009553/2024` tinha 668 PDFs de uma captura
    (títulos e ids seguindo a ordem da árvore) e a seguinte enumerou só 356 e gravou `completo: True`; no
    acervo da VM-1, o `330001/000788/2024` saiu `captura_completa` com `total_arvore` 15 e 257 documentos."""
    import json as _json
    try:
        d = _json.loads(man_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    if not isinstance(d, dict):
        return len(d) if isinstance(d, list) else 0
    try:
        return max(int(d.get("total_arvore") or 0), len(d.get("docs") or []))
    except (TypeError, ValueError):
        return 0


async def main():
    G.cleanup_orphans()
    ok, m = G.preflight()
    print("PREFLIGHT:", ok, m, flush=True)
    if not ok:
        ok, m = G.wait_until_safe(150)
        if not ok:
            # ADIADO, não falhado. Saía com código 0 sem capturar nada; o `sei_arquivar` seguinte
            # então falhava por falta de material e a fila registrava "erro" — o mesmo rótulo de
            # uma captura que realmente quebrou. Quem lesse o log diagnosticava problema no
            # processo quando o que houve foi a VM ocupada. 75 = EX_TEMPFAIL.
            print("ADIADO por carga:", m, flush=True)
            return 75
    outdir = Path(f"data/sei_cache/integra_{TAG}"); outdir.mkdir(parents=True, exist_ok=True)
    # MUTEX REAL DO NAVEGADOR — o mesmo que `sei_reader.ler()` e `extrair_primarios_v3` usam. Este
    # roteiro abria o Playwright DIRETO, fora do lock, e por isso quem quisesse não somar dois
    # Chromium (que já derrubaram esta VM 4×) tinha de inventar uma guarda por fora.
    #
    # A guarda que inventei media a coisa errada: ausência de PROCESSO com "sweep" no nome. Medido em
    # 2026-08-15, depois de QUATRO horas de espera sem uma única captura: `browser.lock` inexistente,
    # ZERO Chromium vivo, e o "alheio" que bloqueava era um `sei_sweep --ug 296100` com 2 SEGUNDOS de
    # vida. Os sweeps do cron nascem e morrem o tempo todo; esperar que nenhum exista é esperar por
    # algo que quase nunca acontece — enquanto o recurso disputado de verdade estava livre.
    #
    # Com o lock, a exclusão é sobre o RECURSO (um browser por vez), não sobre um nome de processo,
    # e o `idade_max` ainda descarta lock órfão de sessão que morreu.
    from compliance_agent.recursos import browser_lock_async
    async with browser_lock_async(espera_max=1800), async_playwright() as pw:
        # SEI_HEADED=1: janela do navegador VISÍVEL (it-campo, pedido do dono 14/11/2026: "nada de janelas ocultas")
        # SEI_CHROMIUM_ARGS: posição/tamanho da janela por sessão (it-campo: mosaico fixo, sem cobrir o trabalho do dono)
        # SEI_CDP_URL (it-campo): conecta no navegador FIXO da sessão, aberto e logado — uma aba por processo, sem
        # abrir/fechar janela nem relogar a cada processo. Sem ela, lança um navegador como sempre (VM-1/VM-2).
        b, ctx, fixo = await SR.navegador_sei(
            pw, args=G.guarded_launch_args(os.environ.get("SEI_CHROMIUM_ARGS", "").split() or None))
        pg = await ctx.new_page(); await pg.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
        try:
            if not await SR.entrar(pg, fixo=fixo, tentativas=25): print("LOGIN FALHOU", flush=True); return RC_LOGIN_FALHOU
            print("login OK", flush=True)
            # ENUMERAÇÃO — caminho CRACKED primeiro (mesmo do ler() canônico): abre processos de OUTRA
            # unidade que o itkava VÊ mas o abrir_processo/arvore_do_fonte não abre (070002/INEA,
            # 070026/SEAS). Provado 2026-07-13: INEA 070002/004135/2025 = 274 docs via cracked. Fallback:
            # arvore_do_fonte (unidade do login). Os docs trazem {titulo,url}; a url é o nó arvore_visualizar.
            arv = []
            dump = {}
            try:
                dump = await SR._ler_cracked(pg, PROC)
                arv = dump.get("documentos") or []
            except (PWError, asyncio.TimeoutError) as e:
                print(f"cracked: {str(e)[:60]}", flush=True)
            fr = None
            origem = "cracked" if arv else None
            if not arv:
                fr = await SR.abrir_processo(pg, PROC)
                if fr:
                    arv = await SR.arvore_do_fonte(pg)
                    origem = "fallback/arvore_do_fonte" if arv else None
            # POR QUAL VIA A ÁRVORE VEIO. O log de sucesso dizia só "baixando N docs" e nunca a
            # origem — e isso escondeu a pergunta que importa. Medido em 2026-08-15: o
            # `080002/011494/2024` falha SEMPRE com `erro_cracked='campo de pesquisa não apareceu'`,
            # enquanto o `080002/023009/2024` abre normalmente. Se o cracked falhar nos DOIS e o
            # segundo estiver entrando pelo fallback, então o cracked está quebrado para todo mundo
            # — e ele é o único caminho para processo de OUTRA unidade, uma classe inteira do acervo
            # que ficaria inalcançável sem ninguém perceber.
            if arv:
                print(f"árvore via {origem}: {len(arv)} nós"
                      + (f" (cracked falhou: {dump.get('erro_cracked')!r})"
                         if origem != "cracked" and dump.get("erro_cracked") else ""), flush=True)
            if not arv:
                # A CAUSA ESTAVA SENDO COLHIDA E JOGADA FORA. `_ler_cracked` NÃO levanta exceção
                # quando falha de leve: devolve `{"documentos": [], "erro_cracked": "..."}` — e ainda
                # marca `cadeado`/`n_docs_restritos` quando o processo tem documento restrito. Nada
                # disso era impresso, então três tentativas seguidas no `080002/011494/2024` (R$ 6,4
                # mi) produziram a MESMA linha muda, "SEM ÁRVORE", sem dizer o que falhou.
                #
                # Log que afirma menos do que o código sabe custa rodada de diagnóstico: eu tinha de
                # abrir o dump à mão para descobrir algo que o processo já tinha em mãos.
                # E A RESPOSTA DO PRÓPRIO SEI. Medido em 13/11/2026 (tela capturada, VM-2): os quatro processos
                # que saíam com "link 'Pesquisa' NÃO ESTÁ no DOM" tinham, na página, "Unidade atual não possui
                # acesso ao processo restrito SEI-…" — nível de acesso RESTRITO do processo, dito pelo SEI. A
                # mensagem do cracked apontava o navegador; a da página aponta o processo. Registrar a da página.
                try:
                    corpo = await pg.evaluate("()=>document.body ? document.body.innerText : ''")
                except PWError:
                    corpo = ""
                aviso = re.search(r"Unidade atual não possui acesso ao processo restrito[^\n.]*", corpo or "")
                print("SEM ÁRVORE (processo não abriu) — "
                      + (f"RESTRITO: SEI diz '{aviso.group(0)}' — " if aviso else "")
                      + f"via={dump.get('via')!r} erro_cracked={dump.get('erro_cracked')!r} "
                      f"cadeado={dump.get('cadeado')!r} "
                      f"n_docs_restritos={dump.get('n_docs_restritos')!r} "
                      f"relacionados={len(dump.get('relacionados') or [])} "
                      f"abrir_processo={'ok' if fr else 'falhou'}", flush=True)
                return RC_SEM_ARVORE
            # formato p/ o resto do script: {t: titulo, u: url, pai: ''}
            docs = [{"t": d.get("titulo") or d.get("texto") or "", "u": d.get("url") or "", "pai": ""}
                    for d in arv if d.get("url")]
            print(f"baixando {len(docs)} docs…", flush=True)
            paths = []

            async def baixa_um(x, fp):
                # CONTEÚDO só pela ÁRVORE VIVA (_conteudo_doc). O GET-direto que existia
                # aqui (ctx.request.get de documento_visualizar) ENVENENAVA a sessão para
                # documento de OUTRA unidade: o request com o infra_hash invalidado fazia o
                # SEI resetar o contexto server-side de documento/unidade, e a partir dali
                # TODA leitura pela árvore voltava vazia — causa provada dos 11.9k "brancos"
                # (2026-07-23: 0/646 docs com o GET; _conteudo_via_arvore sozinho rende 2.348
                # chars/doc). O drill na árvore serve nativo (texto do editor) e escaneado
                # (baixa o anexo + OCR) sem envenenar — mesmo caminho de sei_processo_integral.
                c = await SR._conteudo_doc(pg, {"url": x["u"], "texto": x["t"]})
                txt = ((c or {}).get("conteudo") or "").strip()
                if len(txt) < 15:
                    return False
                if parece_pagina_de_unidade(txt):
                    # o SEI não serviu o documento: devolveu a tela de unidades.
                    # Gravar isso seria inventar teor — melhor registrar a falta.
                    print(f"  doc NÃO SERVIDO (tela de unidade): {x['t'][:40]}", flush=True)
                    return False
                # gravar_doc preserva o PDF ORIGINAL quando escaneado (imagens = fotos de
                # prova) e usa texto p/ nativo; nunca deixa página em branco (confere o
                # retorno de insert_textbox). anexo_bytes vem de _conteudo_via_arvore.
                from compliance_agent.sei.pdf_texto import gravar_doc
                if not gravar_doc(fp, x["t"], txt, (c or {}).get("anexo_bytes")):
                    print(f"  doc sem teor gravável: {x['t'][:40]}", flush=True)
                    return False
                # o OCR deste anexo já foi pago aqui: fica ao lado do PDF para o `sei_arquivar` não refazê-lo do
                # zero (ver `_ocr_da_captura`). Texto cortado no teto de caracteres NÃO serve — o arquivador lê inteiro.
                if (c or {}).get("via") == "ocr" and (c or {}).get("anexo_bytes") and len(txt) < SR.MAX_CHARS_DOC:
                    fp.with_suffix(".ocr.txt").write_text(txt, encoding="utf-8")
                return True

            # manifest com os TÍTULOS da árvore: é ele que permite classificar a
            # fase de cada documento depois (tools/sei_arquivar.py).
            # GRAVAÇÃO INCREMENTAL (2026-07-23): antes o manifesto só era escrito DEPOIS do
            # loop inteiro — quando a fila matava o processo por timeout (900s) no meio de
            # centenas de documentos, TODO o trabalho baixado virava lixo não catalogado.
            # Agora cada documento é registrado na hora e `completo` só vira True no fim,
            # então uma morte no meio deixa uma captura PARCIAL aproveitável e retomável.
            import json as _json
            man_path = outdir / "manifest.json"

            # ÁRVORE QUE ENCOLHEU não fecha a captura: a enumeração de agora é menor que a de antes nesta
            # mesma pasta, então o que falta é leitura nossa, não documento inexistente. Guarda o maior
            # tamanho e não marca `completo` — a próxima passada reenumera e retoma.
            n_antes = arvore_anterior(man_path)
            encolheu = n_antes > len(docs)
            if encolheu:
                print(f"ÁRVORE ENCOLHEU: {len(docs)} nós agora, {n_antes} numa captura anterior — "
                      "captura NÃO marcada completa", flush=True)

            def _grava(man: list, completo: bool) -> None:
                tmp = outdir / "manifest.json.tmp"   # atômico: morte no meio não corrompe
                tmp.write_text(_json.dumps(
                    {"processo": PROC, "total_arvore": max(len(docs), n_antes),
                     "completo": completo and not encolheu,
                     "docs": man}, ensure_ascii=False, indent=1), encoding="utf-8")
                tmp.replace(man_path)

            async def reabrir(aba) -> bool:
                """Mesma via que deu a árvore no início; vale só se a aba nova tem árvore viva. A aba nasce em
                about:blank e o cracked procura o link 'Pesquisa' na página atual: primeiro vai ao início do SEI
                (mesma sessão do contexto — sem login novo; sessão caída = não renova). Medido 19/11: sem este passo
                a renovação falhava calada e a aba seguia crescendo (1,4 GB em 159 docs)."""
                if not await SR.ja_logado(aba):
                    return False
                if origem == "cracked":
                    if not ((await SR._ler_cracked(aba, PROC)).get("documentos")):
                        return False
                elif not (await SR.abrir_processo(aba, PROC) and await SR.arvore_do_fonte(aba)):
                    return False
                return await SR._frame_arvore(aba) is not None

            manifest = []
            _grava(manifest, False)   # marca "em andamento" já no primeiro instante
            baixados_desde = 0
            for i, x in enumerate(docs):
                fp = outdir / f"{i:03d}.pdf"
                ok = False
                if fp.exists() and fp.stat().st_size > 0:
                    paths.append(fp); ok = True     # retomada: não rebaixa o que já veio
                else:
                    if hora_de_renovar(baixados_desde):
                        import time as _t
                        t0 = _t.time()
                        nova = await renovar_aba(ctx, pg, reabrir)
                        baixados_desde = 0
                        renovou = nova is not pg
                        if renovou:
                            pg = nova
                            print(f"  aba renovada em {_t.time() - t0:.0f}s (doc {i}/{len(docs)})", flush=True)
                        # a saída da captura não chega ao log da fila: o registro fica aqui para medir a renovação
                        with open("data/sei_aba_renovada.jsonl", "a", encoding="utf-8") as _f:
                            _f.write(_json.dumps({"t": _t.strftime("%F %T"), "processo": PROC, "doc": i,
                                                  "total": len(docs), "renovou": renovou,
                                                  "s": round(_t.time() - t0, 1)}) + "\n")
                    baixados_desde += 1
                    try:
                        # REDE DE SEGURANÇA acima do orçamento do OCR (OCR_BUDGET_S=300s): o
                        # OCR de scan se AUTO-LIMITA por tempo e declara parcial, então este
                        # wait_for não precisa mais casar com nº de páginas (o design frágil
                        # antigo). 450 = 300 do OCR + ~150 de download/render/click, com folga.
                        # Só dispara se algo travar de verdade (o request tem timeout próprio, 45s).
                        if await asyncio.wait_for(baixa_um(x, fp), timeout=int(os.environ.get("SEI_DOC_TIMEOUT", "450"))):
                            paths.append(fp); ok = True
                    except (asyncio.TimeoutError, PWError, httpx.HTTPError, RuntimeError, OSError, ValueError) as e:
                        print(f"  doc {i} pulado: {str(e)[:35]}", flush=True)
                manifest.append({"i": i, "arquivo": fp.name, "titulo": x.get("t") or "",
                                 "contexto": x.get("pai") or "", "url": x.get("u") or "",
                                 "ok": ok})
                _grava(manifest, False)
                if i % 15 == 0:
                    print(f"  {i}/{len(docs)} ({len(paths)} ok)", flush=True)
            _grava(manifest, True)
            # NÓ DE CAPTURA (it-campo): o lote entregue à VM-1 leva `arquivo/` e `cache/integra_<proc>/` — o PDF
            # único abaixo NÃO vai, e `sei_integra_vm2._limpar_local` o apaga depois da entrega. Montá-lo era só
            # custo: 14/11/2026, quatro deles com 0,6–1,0 GB, juntados inteiros na memória (`garbage=4`) por
            # sessão — pico de RAM na máquina onde a memória é o que limita o nº de sessões.
            if os.environ.get("SEI_SEM_PDF_UNICO") == "1":
                print(f"ÍNTEGRA: {len(paths)} docs (PDF único dispensado: SEI_SEM_PDF_UNICO=1)", flush=True)
                return
            # junta
            out = fitz.open()
            sep = fitz.open(); spg = sep.new_page(); spg.insert_text((60, 120), f"ÍNTEGRA — PROCESSO SEI-{PROC} ({len(paths)} documentos)", fontsize=14); out.insert_pdf(sep); sep.close()
            for fp in paths:
                try:
                    s = fitz.open(str(fp))
                    if s.is_pdf and s.page_count: out.insert_pdf(s)
                    s.close()
                except (RuntimeError, ValueError, OSError): pass
            full = Path(f"data/sei_cache/INTEGRA_{TAG}.pdf"); out.save(str(full), deflate=True, garbage=4)
            sz = full.stat().st_size; print(f"ÍNTEGRA: {len(paths)} docs, {out.page_count} págs, {sz/1024/1024:.1f}MB", flush=True)
            # envia (divide se >45MB); SEI_SEM_TG=1 → só baixa/arquiva, sem Telegram
            if os.environ.get("SEI_SEM_TG") == "1":
                print("TG: pulado (SEI_SEM_TG=1)", flush=True)
                return
            LIM = 45 * 1024 * 1024
            if sz <= LIM:
                print("TG:", envia(str(full), f"📚 ÍNTEGRA COMPLETA — Processo SEI-{PROC} ({len(paths)} docs, {out.page_count} págs)"), flush=True)
            else:
                npart = sz // LIM + 1; per = (out.page_count // npart) + 1
                for k in range(0, out.page_count, per):
                    part = fitz.open(); part.insert_pdf(out, from_page=k, to_page=min(k + per - 1, out.page_count - 1))
                    pp = Path(f"data/sei_cache/INTEGRA_{TAG}_p{k//per+1}.pdf"); part.save(str(pp), deflate=True, garbage=4); part.close()
                    print(f"TG parte {k//per+1}:", envia(str(pp), f"📚 ÍNTEGRA SEI-{PROC} (parte {k//per+1}, págs {k+1}-{min(k+per,out.page_count)})"), flush=True)
        finally:
            await SR.fechar_sei(b, pg, fixo=fixo)
    G.cleanup_orphans()

if __name__ == "__main__":   # importar este módulo NÃO pode disparar o trabalho
    raise SystemExit(asyncio.run(main()) or 0)
