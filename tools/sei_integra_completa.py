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
sys.path.insert(0, "/home/ubuntu/JFN")
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
MAX_PAG = int(os.environ.get("SEI_MAX_PAG", "40"))
ENV = Path.home() / ".hermes" / ".env"   # por usuário: `/home/ubuntu` cravado quebrava fora desta VM
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
        b = await pw.chromium.launch(headless=True, args=G.guarded_launch_args())
        ctx = await b.new_context(ignore_https_errors=True, locale="pt-BR",
              user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
        pg = await ctx.new_page(); await pg.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
        try:
            if not await SR.login(pg, tentativas=25): print("LOGIN FALHOU"); return
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
                print("SEM ÁRVORE (processo não abriu) — "
                      f"via={dump.get('via')!r} erro_cracked={dump.get('erro_cracked')!r} "
                      f"cadeado={dump.get('cadeado')!r} "
                      f"n_docs_restritos={dump.get('n_docs_restritos')!r} "
                      f"relacionados={len(dump.get('relacionados') or [])} "
                      f"abrir_processo={'ok' if fr else 'falhou'}", flush=True)
                return
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

            def _grava(man: list, completo: bool) -> None:
                tmp = outdir / "manifest.json.tmp"   # atômico: morte no meio não corrompe
                tmp.write_text(_json.dumps(
                    {"processo": PROC, "total_arvore": len(docs), "completo": completo,
                     "docs": man}, ensure_ascii=False, indent=1), encoding="utf-8")
                tmp.replace(man_path)

            manifest = []
            _grava(manifest, False)   # marca "em andamento" já no primeiro instante
            for i, x in enumerate(docs):
                fp = outdir / f"{i:03d}.pdf"
                ok = False
                if fp.exists() and fp.stat().st_size > 0:
                    paths.append(fp); ok = True     # retomada: não rebaixa o que já veio
                else:
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
            await b.close()
    G.cleanup_orphans()

if __name__ == "__main__":   # importar este módulo NÃO pode disparar o trabalho
    raise SystemExit(asyncio.run(main()) or 0)
