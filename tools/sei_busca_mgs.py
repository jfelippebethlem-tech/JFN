#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Busca SEI por TEXTO LIVRE (campo 'q' do form avançado) com a mecânica PROVADA do _ler_cracked
(#sbmPesquisar UMA vez + expect_navigation). Lista os processos onde o termo aparece — usado p/
enumerar os processos de pagamento/execução da MGS no ITERJ (ciclos 2022-2023, unidade 330020/330005).
VM-guarded. Uso: sei_busca_mgs.py "MGS CLEAN" [--docs]   (--docs = Considerar Documentos)."""
import asyncio
import json
import sys
sys.path.insert(0, "/home/ubuntu/JFN")
from tools.vm_guard import preflight, cleanup_orphans

import re
TERMO = next((a for a in sys.argv[1:] if not a.startswith("--")), "MGS CLEAN")
# LIGADO POR PADRÃO: o índice de texto livre do SEI é sobre DOCUMENTOS. Desmarcado, ele varre só
# metadado de processo e devolve zero para QUALQUER termo — foi o que manteve o #10 aberto.
# `--sem-docs` mantém o comportamento antigo, para quem quiser exatamente isso.
DOCS = "--sem-docs" not in sys.argv
ORGAO = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--orgao=")), "")  # regex p/ texto da opção
DE = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--de=")), "")       # dd/mm/aaaa
ATE = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--ate=")), "")
LISTAORGAOS = "--listorgaos" in sys.argv
INTERESSADO = "--interessado" in sys.argv  # busca ESTRUTURADA por Contato/Interessado (não full-text)


# ── o que a tela devolve, medido ao vivo em 2026-08-11 ──────────────────────────────────────────
# O #10 do handoff ficou um dia aberto porque três coisas se somaram, e nenhuma era "seletor mudou":
#
# 1. O ÍNDICE DO SEI É SOBRE DOCUMENTOS. Com `Considerar Documentos` desmarcado — o padrão desta
#    ferramenta — a busca por texto livre varre só metadado de processo e devolve ZERO para
#    qualquer coisa, inclusive o controle positivo. Marcada, "LIMPEZA" devolve 213.563.
# 2. A CONTAGEM TEM OUTRO FORMATO. O parser procurava `Lista de Processos ... (N registros)`; a
#    tela devolve `<div class="pesquisaBarraD">Exibindo 1 - 10 de 213.563</div>`.
# 3. "Nenhum resultado encontrado" É TEMPLATE ESCONDIDO — vem no HTML mesmo com 213.563 achados.
#    Lê-lo como veredito é publicar ausência que não existe.
_RE_EXIBINDO = re.compile(
    r"Exibindo\s*([\d.]+)\s*-\s*([\d.]+)\s*de\s*([\d.]+)", re.IGNORECASE)
_RE_PROTOCOLO = re.compile(
    r'<a[^>]*class="protocoloNormal"[^>]*title="([^"]*)"[^>]*>\s*(SEI-\d{6}/\d{6}/\d{4})\s*</a>',
    re.IGNORECASE)


def _num(s: str) -> int:
    return int(re.sub(r"\D", "", s or "0") or 0)


def parse_resultado(html: str) -> dict:
    """Lê a tela de resultado. Distingue ZERO LEGÍTIMO de NÃO CONSEGUI LER — as duas respostas
    saíam iguais (`n_total: 0`, `n_registros: null`), e é por isso que o #10 ficou sem causa.

    Estados:
        com_resultado  a barra de contagem existe e é > 0
        sem_resultado  a barra existe e é 0, ou a página traz a barra vazia — zero apurado
        nao_parseei    não achei a barra: pode ser sessão caída, WAF, layout novo. NUNCA é zero.
    """
    h = html or ""
    m = _RE_EXIBINDO.search(h)
    procs: dict[str, str] = {}
    for titulo, num in _RE_PROTOCOLO.findall(h):
        procs.setdefault(num, (titulo or "").strip()[:120])
    if m:
        total = _num(m.group(3))
        return {"estado": "com_resultado" if total else "sem_resultado", "total": total,
                "exibindo": (_num(m.group(1)), _num(m.group(2))), "processos": procs}
    if 'class="pesquisaBarra"' in h:
        # a barra existe e não traz contagem: a tela do SEI a omite quando não há nada
        return {"estado": "sem_resultado", "total": 0, "exibindo": (0, 0), "processos": procs}
    return {"estado": "nao_parseei", "total": None, "exibindo": None, "processos": procs}


async def main():
    from playwright.async_api import async_playwright
    from tools.sei_session import abrir_sessao
    async with async_playwright() as pw:
        b, ctx, pg, ok = await abrir_sessao(pw)  # reusa a sessão salva (sem flap do WAF)
        try:
            if not ok:
                print(json.dumps({"ok": False, "erro": "login"})); return
            # abrir Pesquisa (clique REAL preserva sessão)
            await pg.evaluate(r"""()=>{const e=[...document.querySelectorAll('a')].find(a=>/^pesquisa$/i.test((a.innerText||'').trim())||/protocolo_pesquisar\b/i.test(a.href||a.getAttribute('onclick')||''));if(e)e.click();}""")
            await pg.wait_for_timeout(5000)
            if LISTAORGAOS:
                ops = await pg.evaluate(r"""()=>{const s=document.getElementById('selOrgaoPesquisa');return s?[...s.options].map(o=>o.text.trim()).filter(Boolean):[];}""")
                print(json.dumps({"ok": True, "orgaos": ops}, ensure_ascii=False, indent=1)); return
            # MODO INTERESSADO: campo Contato + autocomplete + checkbox Interessado (lista só processos onde MGS é parte)
            inter_dbg = None
            if INTERESSADO:
                await pg.evaluate(r"""(t)=>{const c=document.getElementById('txtContato');
                  if(c){c.value=t;c.focus();c.dispatchEvent(new Event('input',{bubbles:true}));c.dispatchEvent(new KeyboardEvent('keyup',{bubbles:true,key:'a'}));}}""", TERMO)
                await pg.wait_for_timeout(4000)  # espera o AJAX do autocomplete
                inter_dbg = await pg.evaluate(r"""(t)=>{
                  const T=t.toUpperCase().replace(/[^0-9A-Z]/g,'').slice(0,8);
                  const cand=[...document.querySelectorAll('ul.ui-autocomplete li, li.ui-menu-item, div.ajax_result a, a, li, div')]
                    .filter(e=>{const s=(e.innerText||'').toUpperCase().replace(/[^0-9A-Z ]/g,'');return s&&(s.includes('MGS')||s.includes('19088605'))&&s.length<140;});
                  if(cand.length){cand[0].click();return {sel:(cand[0].innerText||'').trim().slice(0,90)};}
                  return {sel:null, amostra:[...document.querySelectorAll('li,div.ajax_result a')].map(e=>(e.innerText||'').trim()).filter(Boolean).slice(0,8)};}""", TERMO)
                await pg.wait_for_timeout(500)
                await pg.evaluate(r"""()=>{const c=document.getElementById('chkSinInteressado'); if(c&&!c.checked)c.click();}""")
            # setup: radio Processos + texto q + Órgão (filtra/limpa) + Restringir DESMARCADO + Docs + datas
            setup = await pg.evaluate(r"""(o)=>{
              const hit=[];
              const rp=document.getElementById('optProcessos'); if(rp&&!rp.checked){rp.click();hit.push('optProcessos');}
              const q=document.getElementById('q'); if(q&&!o.inter){q.value=o.termo;q.dispatchEvent(new Event('input',{bubbles:true}));hit.push('q');}
              const so=document.getElementById('selOrgaoPesquisa');
              if(so){[...so.options].forEach(x=>x.selected=false);
                if(o.orgao){const re=new RegExp(o.orgao,'i');let n=0;[...so.options].forEach(x=>{if(re.test(x.text)){x.selected=true;n++;}});hit.push('orgao:sel='+n);}
                else hit.push('orgao:limpo');
                so.dispatchEvent(new Event('change',{bubbles:true}));}
              const ro=document.getElementById('chkSinRestringirOrgao'); if(ro&&ro.checked){ro.click();hit.push('restringir:off');}
              const cd=document.getElementById('chkSinConsiderarDocumentos');
              if(cd){ if(o.docs&&!cd.checked){cd.click();hit.push('docs:on');} if(!o.docs&&cd.checked){cd.click();hit.push('docs:off');} }
              if(o.de){const e=document.getElementById('txtDataInicio'); if(e){e.value=o.de;e.dispatchEvent(new Event('input',{bubbles:true}));hit.push('de');}}
              if(o.ate){const e=document.getElementById('txtDataFim'); if(e){e.value=o.ate;e.dispatchEvent(new Event('input',{bubbles:true}));hit.push('ate');}}
              return hit;
            }""", {"termo": TERMO, "docs": DOCS, "orgao": ORGAO, "de": DE, "ate": ATE, "inter": INTERESSADO})
            await pg.wait_for_timeout(800)
            # diagnóstico do submit: o botão #sbmPesquisar existe mesmo?
            diag = await pg.evaluate(r"""()=>{
              const b=document.querySelector('#sbmPesquisar');
              const todos=[...document.querySelectorAll('button,input[type=submit],input[type=button]')]
                .filter(e=>/pesquisar/i.test(e.value||e.innerText||'')).map(e=>(e.id||e.value||e.innerText||'').trim().slice(0,30));
              return {tem_sbmPesquisar:!!b, botoes_pesquisar:todos};
            }""")
            # submit PROVADO: #sbmPesquisar uma vez + expect_navigation
            try:
                async with pg.expect_navigation(wait_until="domcontentloaded", timeout=35000):
                    await pg.evaluate(r"""()=>{const b=document.querySelector('#sbmPesquisar');if(b){b.click();return;}const f=document.querySelector('#frmProtocoloPesquisa,form[action*=protocolo_pesquisar],form[action*=pesquisa]');if(f)f.submit();}""")
            except Exception:
                pass
            try:
                await pg.wait_for_load_state("networkidle", timeout=25000)
            except Exception:
                pass
            await pg.wait_for_timeout(3000)
            laudo = parse_resultado(await pg.content())
            reg = laudo["total"]
            # pares tipo↔número, percorrendo TODAS as páginas
            achados: dict[str, str] = {}

            async def colher():
                for _ in range(3):
                    try:
                        await pg.wait_for_load_state("domcontentloaded", timeout=10000)
                    except Exception:
                        pass
                    try:
                        return await _colher_eval()
                    except Exception:
                        await pg.wait_for_timeout(2000)
                return None

            async def _colher_eval():
                pares = await pg.evaluate(r"""()=>{
                  const out=[]; let tipo='';
                  document.querySelectorAll('a,span,td,div').forEach(e=>{
                    const s=(e.innerText||'').replace(/\s+/g,' ').trim();
                    const m=s.match(/(?:(.+?)\s+N[ºo°]\s*)?SEI[- ]?(\d{6}\/\d{6}\/\d{4})/);
                    if(m){ if(m[1])tipo=m[1].trim().slice(0,70); out.push([m[2], (m[1]||tipo||'').trim().slice(0,70)]); }
                  });
                  return out;}""")
                for num, tipo in pares:
                    achados.setdefault(num, tipo or achados.get(num, ""))

            await colher()
            for _ in range(5):  # paginação (capada — antes travava em 20×networkidle)
                antes = len(achados)
                try:
                    prox = await pg.evaluate(r"""()=>{const a=[...document.querySelectorAll('a')].find(e=>/pr[oó]xim|seguinte|^›$|^»$/i.test(((e.innerText||'')+' '+(e.title||'')).trim())&&!/desabilit|disabled/i.test(e.className||''));if(a){a.click();return true;}return false;}""")
                except Exception:
                    break
                if not prox:
                    break
                await pg.wait_for_timeout(2500)
                await colher()
                if len(achados) == antes:  # não cresceu → fim
                    break
            pagamentos = {n: t for n, t in achados.items() if re.search(r"pagament", t, re.I)}
            # o que a página DIZ, ao lado do que nós colhemos: se `estado` é `nao_parseei`, um
            # `n_total: 0` não é zero — é leitura falha, e quem consome tem de saber a diferença.
            achados.update({k: v for k, v in laudo["processos"].items() if k not in achados})
            _saida = {"ok": True, "termo": TERMO, "modo": ("interessado" if INTERESSADO else "fulltext"),
                      "estado": laudo["estado"], "exibindo": laudo["exibindo"],
                              "considerar_docs": DOCS, "setup": setup, "interessado_dbg": inter_dbg,
                              "diag_submit": diag, "n_registros": reg, "n_total": len(achados),
                              "n_pagamentos": len(pagamentos),
                              "pagamentos": dict(sorted(pagamentos.items())),
                              "todos": dict(sorted(achados.items()))}
            _registrar({k: v for k, v in _saida.items() if k != "todos"}
                       | {"n_todos": len(achados)})
            print(json.dumps(_saida, ensure_ascii=False, indent=1))
        finally:
            await b.close()


def _registrar(payload: dict) -> None:
    """Grava SEMPRE o resultado em disco, inclusive a recusa do guard.

    Quem chama esta ferramenta pelo sweep lê o `n_total` do stdout e descarta o resto. Quando o
    CONTROLE POSITIVO não retorna, o ciclo aborta corretamente — mas sem nada em disco não há como
    saber POR QUÊ (guard? sessão tomada? seletor?). Medido em 2026-08-10 às 18:52: a busca abortou
    dizendo "controle positivo não devolveu contagem válida" e o motivo se perdeu com o stdout.
    """
    import datetime
    import pathlib
    import re as _re
    try:
        base = pathlib.Path("/home/ubuntu/JFN/data/sei_buscas")
        base.mkdir(parents=True, exist_ok=True)
        slug = _re.sub(r"[^A-Za-z0-9]+", "_", TERMO)[:40] or "termo"
        payload = dict(payload)
        payload["quando"] = datetime.datetime.now().isoformat(timespec="seconds")
        (base / f"_ultimo_{slug}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError as exc:
        # registro é diagnóstico e nunca derruba a busca — mas falhar CALADO aqui seria o mesmo
        # defeito que este registro existe para consertar
        print(json.dumps({"aviso": f"não consegui gravar o diagnóstico: {exc}"}, ensure_ascii=False),
              file=sys.stderr)


if __name__ == "__main__":
    ok, motivo = preflight()
    if not ok:
        recusa = {"ok": False, "vm_guard": motivo}
        _registrar(recusa)
        print(json.dumps(recusa)); sys.exit(1)
    cleanup_orphans()
    try:
        asyncio.run(main())
    finally:
        cleanup_orphans()
