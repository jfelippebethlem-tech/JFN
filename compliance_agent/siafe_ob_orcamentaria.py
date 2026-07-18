# -*- coding: utf-8 -*-
"""
SIAFE-Rio 2 — varredura da tela "Execução > Execução Financeira > OB Orçamentária"
(tela `ordemBancariaOrcamentariaCad.jsp`, tabela ADF `pt1:tblOBOrcamentaria:tabViewerDec`).

ABORDAGEM (a mais robusta): o Playwright LOGA (tratando o diálogo de sessão única do SIAFE) e abre a tela;
depois **rola a tabela virtualizada de verdade** e colhe as linhas do DOM à medida que o Oracle ADF as
carrega por PPR. Assim o navegador cuida de ViewState/clientTokens/fetch sozinho — sem replay frágil.

Login: SIAFE_USER (CPF) e SIAFE_PASS vêm SÓ do .env (nunca hardcoded). Sessão é única por usuário: ao logar,
o SIAFE pergunta "usuário já logado... Deseja continuar? [Sim]" e FECHA a outra sessão (ex.: seu navegador).

USO:
    cd ~/JFN
    .venv/bin/python -m compliance_agent.siafe_ob_orcamentaria --exercicio 2025 --max 300
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import sys
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

logger = logging.getLogger(__name__)

# SIAFE 2.0 por padrão; aponte JFN_SIAFE_LOGIN_URL p/ o SIAFE 1 (www5.fazenda.rj.gov.br/SiafeRio,
# anos 2016–2023) — mesmo login/nav ADF. Sessões independentes → pode rodar 1 e 2 em paralelo.
LOGIN_URL = os.environ.get("JFN_SIAFE_LOGIN_URL", "https://siafe2.fazenda.rj.gov.br/Siafe/faces/login.jsp")
TABLE_DB = "pt1:tblOBOrcamentaria:tabViewerDec::db"   # container rolável do corpo da tabela
OB_RE = re.compile(r"20\d\dOB\d{5,6}")
_STATE = _REPO / "data" / "sei_cache" / "siafe_state.json"
_CKPT = _REPO / "data" / "sei_cache" / "ob_orcamentaria_checkpoint.json"


_DB = _REPO / "data" / "compliance.db"
# colunas da OB Orçamentária na ordem do header do SIAFE (23) -> nomes de coluna na base
_COLS_SIAFE = [
    "numero_ob", "ug_emitente", "ug_pagadora", "data_emissao", "status", "tipo", "finalidade",
    "tipo_ob", "nl", "credor", "nome_credor", "ug_liquidante", "valor", "competencia", "status_envio",
    "gd", "processo", "re", "pd", "tipo_regularizacao", "qtd_impressoes", "assinatura_digital",
    "vinculacao_pagamento",
]


def _norm_label(s: str) -> str:
    """Normaliza um rótulo de coluna do grid (minúsculo, sem acento/pontuação) p/ casar header×coluna."""
    import unicodedata
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return "".join(ch for ch in s.lower() if ch.isalnum())


# rótulo (normalizado) do header AO VIVO -> coluna da base. Cobre SIAFE 2 (23 col) E SIAFE 1 (19 col,
# SEM Tipo de OB/NL/Processo e em ordem diferente). Casamento por LABEL evita o desalinhamento posicional.
_LABEL2COL = {
    "numero": "numero_ob", "ugemitente": "ug_emitente", "ugpagadora": "ug_pagadora",
    "dataemissao": "data_emissao", "status": "status", "tipo": "tipo", "finalidade": "finalidade",
    "tipodeob": "tipo_ob", "tipoob": "tipo_ob", "nl": "nl", "notadeliquidacao": "nl",
    "credor": "credor", "nomedocredor": "nome_credor", "ugliquidante": "ug_liquidante",
    "valor": "valor", "datadecompetencia": "competencia", "competencia": "competencia",
    "statusdeenvio": "status_envio", "guiadevolucao": "gd", "gd": "gd", "processo": "processo",
    "re": "re", "pd": "pd", "tipoderegularizacao": "tipo_regularizacao",
    "qtdimpressoes": "qtd_impressoes", "qtddeimpressoes": "qtd_impressoes",
    "assinaturadigital": "assinatura_digital", "vinculacaodepagamento": "vinculacao_pagamento",
    "vinculacao": "vinculacao_pagamento",
}


def _money_br(s) -> float:
    """'32.087.593,78' -> 32087593.78. Vazio/—/inválido -> 0.0."""
    s = (str(s) or "").strip().replace(".", "").replace(",", ".")
    try:
        return float(s)
    except (ValueError, TypeError):
        return 0.0


def ingerir(exercicio: int, header: list, linhas: list) -> dict:
    """
    Ingere as OBs da OB Orçamentária na `compliance.db`, tabela `ob_orcamentaria_siafe`.
    **SIAFE PREPONDERA**: chave = numero_ob; INSERT OR REPLACE (a versão do SIAFE sobrescreve a anterior).
    Guarda as 23 colunas ricas (NL, PD, Processo, Credor, Competência...) que o TFE não tem.
    """
    import sqlite3
    import time as _t
    if not linhas:
        return {"ok": True, "ingeridas": 0, "exercicio": exercicio}
    con = sqlite3.connect(str(_DB))
    try:
        con.execute(
            "CREATE TABLE IF NOT EXISTS ob_orcamentaria_siafe ("
            + ", ".join(f"{c} TEXT" for c in _COLS_SIAFE if c not in ("valor",))
            + ", valor REAL, exercicio INTEGER, coletado_em TEXT, "
            "PRIMARY KEY (numero_ob))"
        )
        con.execute("CREATE INDEX IF NOT EXISTS ix_obsiafe_ug ON ob_orcamentaria_siafe(ug_emitente)")
        con.execute("CREATE INDEX IF NOT EXISTS ix_obsiafe_ex ON ob_orcamentaria_siafe(exercicio)")
        agora = _t.strftime("%Y-%m-%d %H:%M:%S", _t.gmtime())
        campos = _COLS_SIAFE + ["exercicio", "coletado_em"]
        sql = (f"INSERT OR REPLACE INTO ob_orcamentaria_siafe ({','.join(campos)}) "
               f"VALUES ({','.join('?' * len(campos))})")
        # mapeia coluna-de-índice pelo HEADER ao vivo (corrige SIAFE 1×2); fallback posicional se o header
        # não vier reconhecível (anti-regressão).
        col_por_idx = {}
        if header:
            for i, h in enumerate(header):
                col = _LABEL2COL.get(_norm_label(h))
                if col:
                    col_por_idx[i] = col
        usar_header = len(col_por_idx) >= 4
        n = 0
        for r in linhas:
            if usar_header:
                rowmap = {col_por_idx[i]: r[i] for i in col_por_idx if i < len(r)}
                vals = [(_money_br(rowmap.get(c, "")) if c == "valor" else rowmap.get(c, "")) for c in _COLS_SIAFE]
            else:
                vals = [(_money_br(r[i]) if c == "valor" else (r[i] if i < len(r) else "")) for i, c in enumerate(_COLS_SIAFE)]
            vals += [int(exercicio) if exercicio else None, agora]
            con.execute(sql, vals)
            n += 1
        con.commit()
        tot = con.execute("SELECT COUNT(*) FROM ob_orcamentaria_siafe").fetchone()[0]
    finally:
        con.close()
    return {"ok": True, "ingeridas": n, "total_tabela": tot, "exercicio": exercicio}


class SessaoPerdida(Exception):
    """Disparada quando o SIAFE nos desconecta no meio (ex.: o Mestre Jorge logou e tomou a sessão única)."""


async def _sessao_perdida(pg) -> bool:
    """Detecta se fomos REALMENTE deslogados. ESTRITO: só voltar pro login.jsp ou mensagem explícita de
    expiração conta — NÃO confundir com o widget 'Sua sessão expira em...' do workspace (falso positivo)."""
    try:
        url = (pg.url or "").lower()
        if "login.jsp" in url:
            # confirma que o form de login está presente (não só a URL)
            return await pg.evaluate("""()=>!!document.getElementById('loginBox:itxSenhaAtual::content')""")
        txt = ((await pg.inner_text("body")) or "").lower()
    except Exception:
        return True  # página morreu = trate como perda
    return any(k in txt for k in ("sessão expirada", "sessao expirada", "sessão encerrada",
                                  "sessao encerrada", "sua sessão expirou", "sua sessao expirou",
                                  "faça login novamente", "faca login novamente"))


async def _logado(pg) -> bool:
    return await pg.evaluate("""()=>[...document.querySelectorAll('a.xyo')].some(e=>(e.innerText||'').trim()==='Execução')""")


async def _logout(pg):
    """Clica 'Sair' (canto superior direito) para encerrar a sessão — necessário para TROCAR de exercício
    (o SIAFE reconecta automaticamente no exercício anterior se não sair)."""
    await pg.evaluate("""()=>{const a=[...document.querySelectorAll('a,button,span,td')].find(e=>(e.innerText||'').trim()==='Sair');if(a)a.click();}""")
    await pg.wait_for_timeout(4000)


async def _login(pg, exercicio: int):
    from compliance_agent.envfile import carregar_env
    try:
        carregar_env()
    except Exception as exc:
        logger.debug("falha ao carregar .env antes do login SIAFE: %s", exc)
    # Credenciais POR SISTEMA (opcional): SIAFE1_USER/PASS (www5) e SIAFE2_USER/PASS (siafe2) têm
    # precedência sobre SIAFE_USER/PASS. Permite plugar uma conta SIAFE 1 com acesso GLOBAL (todas as UGs)
    # sem mexer na credencial do SIAFE 2. Cai no SIAFE_USER/PASS quando a específica não existe.
    _sis = "1" if ("www5" in LOGIN_URL or "SiafeRio" in LOGIN_URL) else "2"
    u = (os.environ.get(f"SIAFE{_sis}_USER") or os.environ.get("SIAFE_USER") or "").strip()
    p = (os.environ.get(f"SIAFE{_sis}_PASS") or os.environ.get("SIAFE_PASS") or "").strip()
    if not u or not p:
        return {"ok": False, "erro": f"sem SIAFE{_sis}_USER/PASS nem SIAFE_USER/PASS no .env"}
    await pg.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=45000)
    await pg.wait_for_timeout(2500)
    # se o SIAFE reconectou numa sessão existente (exercício anterior), SAIR para poder escolher o ano
    if await _logado(pg):
        await _logout(pg)
        await pg.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=45000)
        await pg.wait_for_timeout(2500)
    # FLUXO QUE FUNCIONA: preencher usuário+senha, escolher o exercício (com retry — o ADF reverte o
    # <select> sozinho), repor a senha se o re-render limpou, e CLICAR o botão de login por ID.
    await pg.fill('[id="loginBox:itxUsuario::content"]', u)
    await pg.fill('[id="loginBox:itxSenhaAtual::content"]', p)
    if exercicio:
        alvo = str(exercicio)
        for _ in range(12):
            try:
                await pg.select_option('[id="loginBox:cbxExercicio::content"]', label=alvo)
            except Exception:
                break
            await pg.wait_for_timeout(150)
            atual = await pg.evaluate("""()=>{const s=document.getElementById('loginBox:cbxExercicio::content');return s?(s.options[s.selectedIndex]||{}).label:'';}""")
            if atual == alvo:
                break
        # repõe a senha se o re-render do ADF a limpou
        if (await pg.evaluate("""()=>{const e=document.getElementById('loginBox:itxSenhaAtual::content');return e?e.value.length:0;}""")) == 0:
            await pg.fill('[id="loginBox:itxSenhaAtual::content"]', p)
    await pg.wait_for_timeout(400)
    try:
        await pg.click('[id="loginBox:btnConfirmar"]', timeout=8000)
    except Exception:
        # o clique pode disparar a navegação ENQUANTO o evaluate roda → "context destroyed" é, na prática,
        # o login prosseguindo. Tolerar (o fluxo abaixo espera/verifica o estado).
        try:
            await pg.evaluate("""()=>{const b=document.getElementById('loginBox:btnConfirmar');if(b)b.click();}""")
        except Exception as exc:
            logger.debug("clique JS de fallback no botão de login (loginBox:btnConfirmar) falhou: %s", exc)
    await pg.wait_for_timeout(4000)
    # EXERCÍCIO BLOQUEADO para esta conta? (ex.: "O SIAFE-Rio 2023 está bloqueado...")
    body0 = ((await pg.inner_text("body")) or "")
    if "bloqueado" in body0.lower() and "exerc" in body0.lower() or "está bloqueado" in body0.lower():
        return {"ok": False, "erro": "exercicio_bloqueado", "ano": exercicio,
                "detail": f"Exercício {exercicio} bloqueado para esta conta (pedir liberação ao Administrador do SIAFE)."}
    # SEQUÊNCIA DE POPUPS pós-Ok (sessão única "já logado" + MFA da build 13/07/2026 + avisos/termos).
    # Clica nos botões conhecidos até não haver mais (até 7 rodadas). MFA tem tratamento próprio ANTES do
    # clique genérico (senão o "Ok" do diálogo MFA seria clicado com o código vazio).
    for _ in range(7):
        if await _mfa_presente(pg):
            r = await _resolver_mfa(pg)
            if not r.get("ok"):
                return r
            await pg.wait_for_timeout(3000)
            continue
        agiu = await pg.evaluate(
            """()=>{
                if ((document.body.innerText||'').includes('Autenticação Multifator')) return null;
                const vis = el => { if(!el) return false; const r=el.getBoundingClientRect(); const s=getComputedStyle(el);
                    return r.width>0 && r.height>0 && s.visibility!=='hidden' && s.display!=='none'; };
                // 1) botão "Sim" do diálogo de sessão única (id conhecido)
                const sim = document.getElementById('myBtnConfirm');
                if (vis(sim)) { sim.click(); return 'sim'; }
                // 2) qualquer botão/link visível de confirmação/aviso
                const alvo = ['Sim','Continuar','Confirmar','Ciente','Estou ciente','Acessar','Prosseguir','Fechar','OK','Ok'];
                const els = [...document.querySelectorAll('button,a,input[type=button],input[type=submit]')];
                for (const t of alvo) {
                    const el = els.find(e => ((e.innerText||e.value||'').trim()===t) && vis(e)
                                              && (e.id||'').indexOf('loginBox:btnConfirmar')<0);
                    if (el) { el.click(); return t; }
                }
                return null;
            }""")
        if not agiu:
            if await _mfa_presente(pg):
                continue
            break
        await pg.wait_for_timeout(2800)
    await pg.wait_for_timeout(3000)
    body = ((await pg.inner_text("body")) or "")
    bl = body.lower()
    # marcadores de sucesso: sumiu o campo de senha do login E/OU apareceu o menu do workspace
    tem_senha_login = await pg.evaluate("""()=>!!document.getElementById('loginBox:itxSenhaAtual::content')""")
    tem_workspace = await pg.evaluate("""()=>[...document.querySelectorAll('a.xyo')].some(e=>(e.innerText||'').trim()==='Execução')||/workspace/.test(location.href)""")
    # Não logar o corpo da página pós-login (higiene: evita despejar conteúdo sensível em stdout/log).
    print(f"   [login] url={pg.url} | senha_login={tem_senha_login} workspace={tem_workspace}", flush=True)
    if any(k in bl for k in ("token", "código de verificação", "autenticação de dois",
                             "autenticação multifator", "código de autenticação")):
        return {"ok": False, "erro": "mfa", "detail": "SIAFE pediu MFA e o código não foi resolvido a tempo."}
    if tem_workspace or not tem_senha_login:
        return {"ok": True, "url": pg.url}
    try:
        await pg.screenshot(path=str(_REPO / "data/sei_cache/ERRO_login.png"))
    except Exception as exc:
        logger.debug("screenshot de erro de login (ERRO_login.png) falhou: %s", exc)
    return {"ok": False, "erro": "login_falhou", "url": pg.url, "body": body[:300]}


async def _mfa_presente(pg) -> bool:
    """Diálogo de Autenticação Multifator na tela? (novo na build 4.168.13, 13/07/2026 — código por e-mail).
    Sinal robusto: o campo de token do form MFA visível (id exato); fallback textual."""
    try:
        campo = await pg.evaluate(
            """()=>{const e=document.getElementById('loginBox:frmTokenMfa:itxTokenMfa::content');
                if(!e) return false; const r=e.getBoundingClientRect(); const s=getComputedStyle(e);
                return r.width>0 && r.height>0 && s.visibility!=='hidden' && s.display!=='none';}""")
        if campo:
            return True
        body = ((await pg.inner_text("body")) or "").lower()
    except Exception:
        return False
    return "autenticação multifator" in body or "código de autenticação" in body


async def _resolver_mfa(pg, timeout_s: int = 900) -> dict:
    """Resolve o MFA: marca "Dispensar código neste dispositivo por 30 dias" (persiste no perfil de browser),
    pede o código ao Mestre Jorge via Telegram (chega no e-mail ALERJ dele) e aguarda o Yoda gravar o flag
    (`siafe codigo NNNNNN` → siafe_coord.set_mfa). Preenche e confirma."""
    from compliance_agent import siafe_coord
    pedido_ts = time.time()
    siafe_coord.notificar(
        "🔐 JFN — SIAFE-2 agora exige código MFA (mudança da SEFAZ em 13/07).\n\n"
        "Um código de 6 dígitos acabou de ser enviado ao seu e-mail da ALERJ.\n"
        "Responda aqui: *siafe codigo NNNNNN*\n\n"
        "Vou marcar 'dispensar por 30 dias' — só pedirei de novo no mês que vem.")
    print("   [mfa] aguardando código do Mestre via Telegram...", flush=True)
    codigo = ""
    while time.time() - pedido_ts < timeout_s:
        codigo = siafe_coord.get_mfa(depois_de=pedido_ts - 60)
        if codigo:
            break
        await asyncio.sleep(10)
    if not codigo:
        return {"ok": False, "erro": "mfa_sem_codigo",
                "detail": f"Mestre não enviou o código MFA em {timeout_s//60}min (responder 'siafe codigo NNNNNN')."}
    print("   [mfa] código recebido — preenchendo", flush=True)
    # IDs EXATOS do diálogo MFA (build 4.168.13). O form de login (usuário/senha) CONTINUA no DOM
    # atrás do popup — um seletor genérico digitava o código no campo Senha e a validação falhava.
    # Preenchimento NATIVO (Playwright type/press): o input ADF só comita o valor no modelo com
    # eventos de tecla reais — setar .value por JS não basta.
    campo = '[id="loginBox:frmTokenMfa:itxTokenMfa::content"]'
    try:
        await pg.click(campo, timeout=8000)
        await pg.fill(campo, "")
        await pg.type(campo, codigo, delay=60)  # digitação real, tecla a tecla
        # "dispensar 30 dias" → o cookie do perfil persistente evita novo MFA por 1 mês
        try:
            await pg.check('[id="loginBox:frmTokenMfa:ckTrustDevice::content"]', timeout=3000)
        except Exception as exc:
            logger.debug("checkbox 'dispensar 30 dias' não marcado (segue sem persistir): %s", exc)
    except Exception as exc:
        try:
            await pg.screenshot(path=str(_REPO / "data/sei_cache/ERRO_mfa.png"))
        except Exception:
            pass
        return {"ok": False, "erro": "mfa_campo_nao_encontrado", "detail": f"campo MFA inacessível: {exc}"}
    await pg.wait_for_timeout(400)
    # confirma: Enter no campo E clique no botão (o que disparar primeiro resolve)
    try:
        await pg.press(campo, "Enter")
    except Exception as exc:
        logger.debug("Enter no campo MFA falhou (segue p/ o clique do botão): %s", exc)
    try:
        await pg.click('[id="loginBox:frmTokenMfa:btnConfirmToken"]', timeout=5000)
    except Exception as exc:
        logger.debug("clique no botão Ok do MFA falhou (Enter pode ter resolvido): %s", exc)
    await pg.wait_for_timeout(4500)
    if await _mfa_presente(pg):
        # deixa evidência p/ diagnóstico (o valor entrou no campo? há msg de erro?)
        try:
            await pg.screenshot(path=str(_REPO / "data/sei_cache/ERRO_mfa.png"))
        except Exception:
            pass
        return {"ok": False, "erro": "mfa_codigo_rejeitado",
                "detail": "Código MFA preenchido mas o diálogo persiste (código errado/expirado?)."}
    siafe_coord.notificar("✅ Código MFA aceito — coleta SIAFE retomada. Dispensa de 30 dias marcada.")
    return {"ok": True}


async def _shot(pg, nome):
    # screenshots só quando JFN_SIAFE_DEBUG está setado, e vão para /tmp (efêmero) — não acumulam na base.
    if not os.environ.get("JFN_SIAFE_DEBUG"):
        return
    try:
        await pg.screenshot(path=f"/tmp/siafe_nav_{nome}.png")
    except Exception as exc:
        logger.debug("screenshot de debug siafe_nav_%s falhou: %s", nome, exc)


async def _contar_linhas(pg) -> int:
    return await pg.evaluate(
        r"""()=>{const db=document.getElementById('""" + TABLE_DB + r"""');
            return db ? [...db.querySelectorAll('tr')].filter(tr=>/20\d\dOB\d{5,6}/.test(tr.innerText||'')).length : 0;}""")


async def _glasspane_ativo(pg) -> bool:
    """True se há um glasspane/spinner de carregamento do ADF visível (tabela ainda carregando)."""
    return await pg.evaluate(r"""()=>{
        const vis = e => { const r=e.getBoundingClientRect(); const s=getComputedStyle(e);
            return r.width>3 && r.height>3 && s.visibility!=='hidden' && s.display!=='none'; };
        return [...document.querySelectorAll('.AFBlockingGlassPane,[id*="glassPane"],[id*="GlassPane"],.xlk,.x1ie')].some(vis);
    }""")


async def tabela_pronta(pg) -> bool:
    """Detector de 'load concluído': tabela existe + tem linhas de OB + sem glasspane + contagem estável."""
    if await _glasspane_ativo(pg):
        return False
    n1 = await _contar_linhas(pg)
    if n1 <= 0:
        return False
    await pg.wait_for_timeout(1500)
    if await _glasspane_ativo(pg):
        return False
    n2 = await _contar_linhas(pg)
    return n2 == n1 and n2 > 0  # estável entre duas leituras


async def _navegar(pg) -> dict:
    """Execução → Execução Financeira → OB Orçamentária. Retorna {ok, itens_submenu}."""
    await _shot(pg, "0_poslogin")
    await pg.evaluate(r"""()=>{const a=[...document.querySelectorAll('a.xyo')].find(e=>(e.innerText||'').trim()==='Execução');if(a)a.click();}""")
    await pg.wait_for_timeout(1800)
    await _shot(pg, "1_execucao")
    await pg.evaluate(r"""()=>{const a=document.getElementById('pt1:pt_np3:1:pt_cni4::disclosureAnchor')||[...document.querySelectorAll('a.xyo')].find(e=>(e.innerText||'').trim()==='Execução Financeira');if(a)a.click();}""")
    await pg.wait_for_timeout(2200)
    await _shot(pg, "2_execfinanceira")
    itens = await pg.evaluate(r"""()=>[...document.querySelectorAll('a')].map(e=>(e.innerText||'').trim()).filter(t=>t.length>2&&t.length<60)""")
    # clica EXATAMENTE em "OB Orçamentária" (não em "Execução Orçamentária", que também casa "orçamentária")
    clicou = await pg.evaluate(r"""()=>{
        const norm = s => (s||'').trim().toLowerCase().replace(/\s+/g,' ');
        const els = [...document.querySelectorAll('a')];
        let el = els.find(e => norm(e.innerText)==='ob orçamentária' || norm(e.innerText)==='ob orcamentaria');
        if(!el) el = els.find(e => /^ob\s+or[çc]ament[áa]ria$/.test(norm(e.innerText)));
        if(el){el.click();return (el.innerText||'').trim();}
        return null;
    }""")
    await pg.wait_for_timeout(2000)
    await _shot(pg, "3_clicou_ob_orcamentaria")
    # a grade é PESADA e demora bastante a aparecer/carregar — espera a tabela (poll até ~90s)
    achou = False
    for i in range(45):
        await pg.wait_for_timeout(2000)
        try:  # o evaluate pode estourar "context destroyed" se um PPR/navegação está em voo — tolerar e repetir
            achou = await pg.evaluate(r"""()=>!!document.querySelector('[id*="tblOBOrcamentaria"]')""")
        except Exception:
            achou = False
        if achou:
            break
        if i in (10, 25):
            await _shot(pg, f"4_aguardando_tabela_{i}")
    # detector de LOAD CONCLUÍDO: espera a tabela ficar pronta (linhas + sem spinner + contagem estável)
    pronta = False
    if achou:
        for _ in range(30):  # até ~70s
            if await tabela_pronta(pg):
                pronta = True
                break
            await pg.wait_for_timeout(2000)
    await _shot(pg, "5_tabela_final")
    n_ini = await _contar_linhas(pg) if achou else 0
    return {"ok": bool(achou and pronta), "clicou": clicou, "linhas_iniciais": n_ini,
            "itens_submenu": [t for t in itens if "ob" in t.lower() or "orçament" in t.lower() or "orcament" in t.lower()][:10]}


async def _remover_limite(pg) -> str:
    """Marca o checkbox `chkRemoveLimit` da tabela OB Orçamentária p/ remover o teto de 1000 registros por
    consulta (ver docs/SIAFE-RIO2-GUIA-AUTOMACAO.md §5 — destrava o gargalo §8b). Best-effort: se o checkbox
    não existir ou já estiver marcado, segue o fluxo (com o limite padrão / filtros). Dispara o PPR do ADF e
    aguarda a tabela recarregar. Retorna 'marcado'|'ja_marcado'|'ausente'."""
    estado = await pg.evaluate(r"""()=>{
        const cb = document.getElementById('pt1:tblOBOrcamentaria:chkRemoveLimit::content')
                 || document.querySelector('[id*="tblOBOrcamentaria"][id*="chkRemoveLimit"][type="checkbox"]');
        if(!cb) return 'ausente';
        if(cb.checked) return 'ja_marcado';
        cb.click(); cb.dispatchEvent(new Event('change',{bubbles:true}));
        return 'marcado';
    }""")
    if estado == "marcado":
        # ADF recarrega a tabela sem o limite — aguardar o glasspane sumir / a tabela ficar pronta
        for _ in range(20):  # ~30s
            await pg.wait_for_timeout(1500)
            if await tabela_pronta(pg):
                break
    return estado


TABLE_SCROLLER = "pt1:tblOBOrcamentaria:tabViewerDec::scroller"


async def _colher(pg, maxn: int, vistos: set, linhas: list, save_cb=None) -> list:
    """Colhe as OBs ROLANDO O CONTAINER VIRTUAL (`::scroller`, ~40000px), colhendo o corpo (`::db`) a cada
    passo. A tabela é virtualizada (só ~50 linhas no DOM por vez) e tem limite de 1000 registros por
    consulta — rolar o ::db (1950px) não bastava; é o ::scroller que dispara o fetch do ADF.
    Levanta SessaoPerdida se deslogar. `save_cb()` persiste o progresso."""
    header = await pg.evaluate(r"""()=>{
        const h=document.querySelector('[id="pt1:tblOBOrcamentaria:tabViewerDec::ch"]')||document.querySelector('[id*="tblOBOrcamentaria"][id*="::ch"]');
        if(!h)return[];return [...h.querySelectorAll('th,td')].map(c=>(c.innerText||'').replace(/\s+/g,' ').trim()).filter(x=>x);
    }""")
    js_rows = r"""()=>{const db=document.getElementById('""" + TABLE_DB + r"""');const o=[];if(db)db.querySelectorAll('tr').forEach(tr=>{const tds=[...tr.querySelectorAll('td')].map(td=>(td.innerText||'').replace(/\s+/g,' ').trim());if(tds.some(x=>x))o.push(tds);});return o;}"""
    js_geo = r"""()=>{const s=document.getElementById('""" + TABLE_SCROLLER + r"""');return s?{top:s.scrollTop,sh:s.scrollHeight,ch:s.clientHeight}:null;}"""

    def js_scroll_to(y):
        return (r"""()=>{const s=document.getElementById('""" + TABLE_SCROLLER + r"""');
            if(!s)return -1;s.scrollTop=""" + str(int(y)) + r""";
            s.dispatchEvent(new Event('scroll',{bubbles:true}));return s.scrollTop;}""")

    async def _harvest():
        novos = 0
        for r in await pg.evaluate(js_rows):
            m = OB_RE.search(" ".join(r))
            if m and m.group(0) not in vistos and len([c for c in r if c]) >= 4:
                vistos.add(m.group(0)); linhas.append(r); novos += 1
        return novos

    await _harvest()  # 1ª janela (já no DOM)
    geo = await pg.evaluate(js_geo) or {"sh": 0, "ch": 727}
    sh, ch = geo["sh"], max(geo["ch"], 300)
    passo = int(ch * 0.7)  # sobreposição p/ não pular linhas
    y, seco, ciclo = 0, 0, 0
    while len(linhas) < maxn and seco < 10:
        y += passo
        await pg.evaluate(js_scroll_to(y))
        await pg.wait_for_timeout(1100)  # espera o ADF buscar/renderizar o próximo bloco
        novos = await _harvest()
        seco = 0 if novos else seco + 1
        if save_cb and novos:
            save_cb(header, linhas)
        ciclo += 1
        # chegou ao fim do scroller? recalcula (pode crescer conforme carrega) e encerra se passou do fim
        geo = await pg.evaluate(js_geo)
        if geo:
            sh = max(sh, geo["sh"])
            if y >= sh - ch and not novos:
                break
        if ciclo % 8 == 0 and await _sessao_perdida(pg):
            if save_cb:
                save_cb(header, linhas)
            raise SessaoPerdida(f"deslogado após colher {len(linhas)} OBs")
    if save_cb:
        save_cb(header, linhas)
    return header


def _ckpt_load(exercicio: int) -> tuple[set, list, list]:
    try:
        d = json.loads(_CKPT.read_text(encoding="utf-8"))
        if d.get("exercicio") == exercicio:
            linhas = d.get("linhas", [])
            vistos = set()
            for r in linhas:
                m = OB_RE.search(" ".join(r))
                if m:
                    vistos.add(m.group(0))
            return vistos, linhas, d.get("header", [])
    except Exception as exc:
        logger.debug("checkpoint de OBs (exercício %s) ausente ou ilegível em %s: %s", exercicio, _CKPT, exc)
    return set(), [], []


def _ckpt_save(exercicio: int, header: list, linhas: list):
    try:
        _CKPT.parent.mkdir(parents=True, exist_ok=True)
        _CKPT.write_text(json.dumps({"exercicio": exercicio, "header": header, "linhas": linhas},
                                    ensure_ascii=False), encoding="utf-8")
    except Exception as exc:
        logger.warning("falha ao salvar checkpoint de OBs (exercício %s) em %s: %s", exercicio, _CKPT, exc)


_PROFILE = _REPO / "data" / "siafe_profile"


async def _novo_browser(pw, headless=True):
    """Contexto PERSISTENTE (data/siafe_profile): preserva o cookie "dispensar MFA por 30 dias" entre
    coletas — o código MFA só é pedido ao Mestre ~1×/mês. Retorna (ctx, pg); ctx.close() encerra tudo."""
    _PROFILE.mkdir(parents=True, exist_ok=True)
    ctx = await pw.chromium.launch_persistent_context(
        str(_PROFILE), headless=headless, args=["--no-sandbox", "--ignore-certificate-errors"],
        ignore_https_errors=True, locale="pt-BR", timezone_id="America/Sao_Paulo",
        viewport={"width": 1600, "height": 1000},
        user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"))
    await ctx.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
    pg = await ctx.new_page()
    return ctx, pg


async def coletar(exercicio=2025, maxn=300, headless=True, vistos=None, linhas=None) -> dict:
    """Uma passada: login → navega → colhe. Acumula em `vistos`/`linhas` (para retomar entre tentativas)."""
    from playwright.async_api import async_playwright
    vistos = vistos if vistos is not None else set()
    linhas = linhas if linhas is not None else []
    save_cb = lambda h, ls: _ckpt_save(exercicio, h, ls)
    async with async_playwright() as pw:
        b, pg = await _novo_browser(pw, headless)
        _t0 = time.time()
        _log = lambda m: print(f"[{time.time()-_t0:5.1f}s] {m}", flush=True)
        try:
            _log("login: iniciando...")
            log = await _login(pg, exercicio)
            _log(f"login: {log}")
            if not log.get("ok"):
                return {"ok": False, "etapa": "login", **log}
            _log("navegação: Execução > Execução Financeira > OB Orçamentária...")
            nav = await _navegar(pg)
            _log(f"navegação: {nav}")
            if not nav.get("ok"):
                try:
                    await pg.screenshot(path=str(_REPO / "data/sei_cache/ERRO_nav_ob_orc.png"))
                except Exception as exc:
                    logger.debug("screenshot de erro de navegação (ERRO_nav_ob_orc.png) falhou: %s", exc)
                return {"ok": False, "etapa": "navegacao", "detail": "tabela tblOBOrcamentaria não apareceu",
                        "itens_submenu": nav.get("itens_submenu")}
            try:
                await ctx.storage_state(path=str(_STATE))
            except Exception as exc:
                logger.debug("falha ao salvar storage_state da sessão SIAFE em %s: %s", _STATE, exc)
            # remove o teto de 1000 registros/consulta antes de varrer (docs/SIAFE-RIO2-GUIA-AUTOMACAO.md §5)
            lim = await _remover_limite(pg)
            _log("limite 1000: " + {"marcado": "removido via chkRemoveLimit", "ja_marcado": "já removido",
                 "ausente": "checkbox ausente nesta tela — usar filtros/iteração p/ >1000"}.get(lim, lim))
            _log(f"colhendo (rolando a tabela, alvo {maxn})...")
            header = await _colher(pg, maxn, vistos, linhas, save_cb)
            _log(f"colheu {len(linhas)} OBs | header={header}")
            return {"ok": True, "exercicio": exercicio, "header": header, "n": len(linhas), "linhas": linhas}
        finally:
            await b.close()


async def coletar_resiliente(exercicio=2025, maxn=100000, max_tentativas=24,
                             headless=True, coordenar=True, espera_fallback_s=3600,
                             _sleep=None, _aguardar=None) -> dict:
    """
    Varredura RESILIENTE à sessão única do SIAFE. Se o Mestre Jorge logar e nos derrubar (ou vice-versa),
    a sessão cai: salvamos o progresso (checkpoint) e, em vez de esperar um tempo fixo, **perguntamos no
    Telegram** e aguardamos o Jorge liberar (ele responde 'siafe livre' → o Yoda seta o flag). Aí RETOMAMOS
    de onde paramos. Se `coordenar=False`, cai no modo de espera fixa (`espera_fallback_s`).
    """
    _sleep = _sleep or asyncio.sleep
    try:
        from compliance_agent import siafe_coord
    except Exception:
        siafe_coord = None
    _aguardar = _aguardar or (siafe_coord.aguardar_liberacao if (siafe_coord and coordenar) else None)

    async def _esperar(motivo):
        if _aguardar:
            # roda o aguardar (bloqueante) numa thread para não travar o loop async
            await asyncio.to_thread(_aguardar, motivo)
            if siafe_coord:
                siafe_coord.set_status("coletor_rodando", "varredura em curso")
        else:
            await _sleep(espera_fallback_s)

    vistos, linhas, _ = _ckpt_load(exercicio)
    # antes de logar (e derrubar o Jorge), se ele marcou 'ocupado', pergunta e aguarda liberar
    if siafe_coord and coordenar and siafe_coord.get_status() == "ocupado":
        await _esperar("preciso iniciar a varredura, mas o flag está 'ocupado'")
    for tentativa in range(1, max_tentativas + 1):
        try:
            res = await coletar(exercicio, maxn, headless=headless, vistos=vistos, linhas=linhas)
        except SessaoPerdida as e:
            print(f"[resiliente] sessão perdida ({e}). {len(linhas)} OBs salvas. Coordenando via Telegram...", flush=True)
            await _esperar(f"fui desconectado no meio da varredura (já tenho {len(linhas)} OBs)")
            continue
        if not res.get("ok"):
            if res.get("erro") == "exercicio_bloqueado":
                # ano bloqueado para a conta (ex.: 2023). NÃO insistir — devolve para o sweep PULAR este ano.
                return {"ok": False, "erro": "exercicio_bloqueado", "ano": res.get("ano"),
                        "n": len(linhas), "detail": res.get("detail")}
            if res.get("erro") == "mfa":
                if siafe_coord:
                    siafe_coord.notificar("🔐 SIAFE pediu MFA na varredura — me mande o código, Mestre Jorge.")
                return {"ok": False, "erro": "mfa", "n": len(linhas),
                        "detail": "SIAFE pediu MFA — preciso do código do Mestre Jorge."}
            print(f"[resiliente] falha '{res.get('etapa')}' ({res.get('erro') or res.get('detail')}). Coordenando...", flush=True)
            await _esperar(f"falhei na etapa '{res.get('etapa')}' do SIAFE")
            continue
        if len(linhas) >= maxn:
            return {"ok": True, "completo": False, "exercicio": exercicio,
                    "header": res.get("header", []), "n": len(linhas), "linhas": linhas}
        # passada concluiu sem perder sessão → varredura completa
        return {"ok": True, "completo": True, "exercicio": exercicio,
                "header": res.get("header", []), "n": len(linhas), "linhas": linhas}
    return {"ok": False, "erro": "max_tentativas", "n": len(linhas), "linhas": linhas}


# ── Filtro ADF da OB Orçamentária (IDs VALIDADOS 2026-06-07 — docs/SIAFE-EVOLUCAO-TENTATIVAS §6) ──
_F_DISC = "pt1:tblOBOrcamentaria:sdtFilter::disAcr"
_F_PROP = "pt1:tblOBOrcamentaria:table_rtfFilter:0:cbx_col_sel_rtfFilter::content"
_F_OP = "pt1:tblOBOrcamentaria:table_rtfFilter:0:cbx_op_sel_rtfFilter::content"
_F_VAL_SEL = '[id*="table_rtfFilter:0"] input[type="text"]:visible'  # campo valor (locator robusto)
_FILTRO_CKPT = lambda ex: _REPO / "data" / "sei_cache" / f"siafe_filtro_ckpt_{ex}.json"


async def _click_real(pg, elem_id) -> bool:
    """Clique de MOUSE real no centro do bbox — o ADF IGNORA locator.click()/JS click em
    disclosure/popup (botão pode estar 0x0). Receita validada (siafe_contratos.click_vis)."""
    c = await pg.evaluate(
        """(id)=>{for(const e of document.querySelectorAll('[id=\"'+id+'\"]')){const r=e.getBoundingClientRect();if(r.width>0&&r.height>0)return{x:r.left+r.width/2,y:r.top+r.height/2}}return null}""",
        elem_id)
    if c:
        await pg.mouse.click(c["x"], c["y"]); return True
    return False


async def _filtrar(pg, prop, op, valor) -> dict:
    """Filtro: fecha popups → disclosure (mouse real) → Propriedade/Operador (select) →
    Valor (keyboard.type+Enter), esperando o sync do ADF a cada passo. Receita validada."""
    from compliance_agent.siafe_adf import AdfSync
    adf = AdfSync(pg)
    for t in ("OK", "Sim"):  # popups que às vezes cobrem a tela
        try:
            e = pg.get_by_text(t, exact=True).first
            if await e.is_visible(timeout=800):
                await e.click(); await adf.wait()
        except Exception as exc:
            logger.debug("popup '%s' não encontrado/fechado antes do filtro: %s", t, exc)
    if await pg.locator(f'[id="{_F_PROP}"]').count() == 0:
        await _click_real(pg, _F_DISC); await adf.wait()
    if await pg.locator(f'[id="{_F_PROP}"]').count() == 0:
        return {"ok": False, "erro": "painel de filtro não abriu"}
    await pg.locator(f'[id="{_F_PROP}"]:visible').first.select_option(str(prop)); await adf.wait()
    await pg.locator(f'[id="{_F_OP}"]:visible').first.select_option(str(op)); await adf.wait()
    v = pg.locator(_F_VAL_SEL).last
    await v.click(); await v.press("Control+a"); await v.press("Delete")
    await pg.keyboard.type(str(valor), delay=80); await pg.keyboard.press("Enter")
    await adf.wait()
    return {"ok": True, "prop": prop, "op": op, "valor": valor}


def _ckpt_prefixos(ex) -> set:
    p = _FILTRO_CKPT(ex)
    try:
        return set(json.loads(p.read_text())) if p.exists() else set()
    except Exception:
        return set()


def _ckpt_marca(ex, pref) -> None:
    feitos = _ckpt_prefixos(ex); feitos.add(pref)
    try:
        _FILTRO_CKPT(ex).write_text(json.dumps(sorted(feitos)))
    except Exception as exc:
        logger.warning("falha ao gravar checkpoint de prefixo %s (exercício %s): %s", pref, ex, exc)


async def _sweep_sessao(exercicio, prefixos, maxn, headless, _log) -> dict:
    """UMA sessão SIAFE: login+nav, aplica cada prefixo PENDENTE, INGERE por prefixo (persiste) e
    marca o checkpoint. Para na 1ª falha (sessão ~1h caiu) p/ o chamador relogar e continuar."""
    from playwright.async_api import async_playwright
    from compliance_agent.siafe_adf import AdfSync
    pend = [p for p in prefixos if p not in _ckpt_prefixos(exercicio)]
    if not pend:
        return {"ok": True, "pendentes": []}
    async with async_playwright() as pw:
        b, pg = await _novo_browser(pw, headless)
        try:
            lg = await _login(pg, exercicio); _log(f"login: {lg.get('ok')}")
            if not lg.get("ok"):
                return {"ok": False, "etapa": "login"}
            nv = await _navegar(pg); _log(f"nav: {nv.get('ok')}")
            if not nv.get("ok"):
                return {"ok": False, "etapa": "navegacao"}
            try:
                await ctx.storage_state(path=str(_STATE))
            except Exception as exc:
                logger.debug("falha ao salvar storage_state da sessão SIAFE em %s: %s", _STATE, exc)
            adf = AdfSync(pg); await adf.boot()
            for pref in pend:
                try:
                    fr = await _filtrar(pg, 0, 8, pref)
                    if not fr.get("ok"):
                        _log(f"filtro {pref} falhou ({fr.get('erro')}) — relogar"); return {"ok": False}
                    vistos, linhas = set(), []
                    header = await _colher(pg, maxn, vistos, linhas, None)
                    ing = ingerir(exercicio, header, linhas) if linhas else {"ingeridas": 0}
                    _ckpt_marca(exercicio, pref)
                    _log(f"prefixo {pref}: {len(linhas)} OBs, {ing.get('ingeridas')} ingeridas ✓")
                except Exception as e:
                    _log(f"prefixo {pref} ERRO {type(e).__name__}: {str(e)[:70]} — relogar")
                    return {"ok": False}
            return {"ok": True, "pendentes": []}
        finally:
            await b.close()


async def coletar_filtrado(exercicio=2026, prefixos=None, headless=True, maxn=4000, max_sessoes=8) -> dict:
    """Sweep RESUMÍVEL por filtro Número 'começa com' (fura o teto de 1000). Ingere e dá checkpoint
    POR PREFIXO; se a sessão do SIAFE cair (~1h máx) ou der erro, RELOGA e CONTINUA de onde parou.
    Default: {ex}OB0..{ex}OB9 (subdividir prefixos se um bloco passar de ~1000)."""
    import time as _t
    if not prefixos:
        prefixos = [f"{exercicio}OB{d}" for d in range(10)]
    t0 = _t.time(); _log = lambda m: print(f"[{_t.time()-t0:6.1f}s] {m}", flush=True)
    for sessao in range(max_sessoes):
        if not [p for p in prefixos if p not in _ckpt_prefixos(exercicio)]:
            _log("todos os prefixos concluídos ✓")
            break
        pend = [p for p in prefixos if p not in _ckpt_prefixos(exercicio)]
        _log(f"sessão {sessao+1}/{max_sessoes}: {len(pend)} pendente(s): {pend}")
        try:
            await _sweep_sessao(exercicio, prefixos, maxn, headless, _log)
        except Exception as e:
            _log(f"sessão {sessao+1} caiu: {type(e).__name__}: {str(e)[:70]} — nova sessão")
    feitos = sorted(_ckpt_prefixos(exercicio))
    pend = [p for p in prefixos if p not in _ckpt_prefixos(exercicio)]
    return {"ok": not pend, "exercicio": exercicio, "feitos": feitos, "pendentes": pend}


async def _typeahead(pg, elem_id, text):
    """Seleciona um <select> ADF por TYPEAHEAD (evento CONFIÁVEL — select_option/dispatch são
    ignorados pelo ADF). Foco por mouse real → digita → Enter → Tab. Resolve o §8b."""
    await _click_real(pg, elem_id); await pg.wait_for_timeout(350)
    await pg.keyboard.type(str(text), delay=110); await pg.wait_for_timeout(500)
    await pg.keyboard.press("Enter"); await pg.wait_for_timeout(300)
    await pg.keyboard.press("Tab"); await pg.wait_for_timeout(1500)


async def _filtrar_ug(pg, ug_codigo) -> dict:
    """Filtra a OB Orçamentária por UG Emitente = <ug_codigo> (receita VALIDADA 2026-06-07).
    Propriedade/Operador por typeahead; VALOR commitado com **Tab** (Enter NÃO aplica)."""
    from compliance_agent.siafe_adf import AdfSync
    adf = AdfSync(pg)
    if await pg.locator(f'[id="{_F_PROP}"]').count() == 0:
        await _click_real(pg, _F_DISC); await adf.wait()
    if await pg.locator(f'[id="{_F_PROP}"]').count() == 0:
        return {"ok": False, "erro": "painel de filtro não abriu"}
    await _typeahead(pg, _F_PROP, "UG Emi"); await adf.wait()      # Propriedade = UG Emitente
    # "começa com" (não "igual"): UG tem 6 dígitos → equivale a igual no SIAFE 2 E renderiza o campo de
    # valor no SIAFE 1 (onde "igual" não rende). Unifica os dois sistemas.
    await _typeahead(pg, _F_OP, "começa com"); await adf.wait()
    val = pg.locator('[id*="in_value_rtfFilter"]:visible').last     # campo de valor (renderiza após os 2 typeaheads)
    if await val.count() == 0:
        return {"ok": False, "erro": "campo de valor não renderizou"}
    await val.click(); await val.press("Control+a"); await val.press("Delete")
    await pg.keyboard.type(str(ug_codigo), delay=100)
    await pg.keyboard.press("Tab")                                  # COMMIT por Tab (blur) → PPR refiltra
    await adf.wait(); await pg.wait_for_timeout(3000)
    return {"ok": True, "ug": ug_codigo}


# linha 1 do filtro (a tabela já vem com 2 linhas: 0 e 1) — p/ combinar UG (linha 0) + Número (linha 1)
_F_PROP1 = "pt1:tblOBOrcamentaria:table_rtfFilter:1:cbx_col_sel_rtfFilter::content"
_F_OP1 = "pt1:tblOBOrcamentaria:table_rtfFilter:1:cbx_op_sel_rtfFilter::content"
_F_VAL1_SEL = '[id*="table_rtfFilter:1"] input[type="text"]:visible'


async def _set_valor(pg, sel, valor):
    """Seta o campo de valor do filtro, LIMPANDO de forma confiável antes (Ctrl+A/Delete falha no
    campo ADF e concatena lixo → 0 resultados na 2ª iteração). Verifica que ficou só o valor novo."""
    v = pg.locator(sel).last
    await v.click()
    await v.fill("")                       # limpeza confiável (síncrona)
    await pg.wait_for_timeout(150)
    await pg.keyboard.type(str(valor), delay=90)
    try:
        if (await v.input_value()).strip() != str(valor):
            await v.fill(""); await pg.wait_for_timeout(150)
            await pg.keyboard.type(str(valor), delay=90)
    except Exception as exc:
        logger.debug("verificação do valor '%s' no campo de filtro falhou: %s", valor, exc)
    # COMMIT do valor: dispara o valueChange via o CLIENTE ADF (FUNCIONA no SIAFE 1 — campo sem autoSubmit —
    # e no SIAFE 2). Sem isso, no SIAFE 1 o filtro não aplica. Tab fica como reforço (SIAFE 2).
    try:
        await pg.evaluate(
            """(args)=>{const [sel,val]=args;
               const els=[...document.querySelectorAll(sel)].filter(e=>{const r=e.getBoundingClientRect();return r.width>0&&r.height>0;});
               const el=els[els.length-1]; if(!el)return;
               const id=el.id.replace(/::content$/,'');
               try{const c=AdfPage.PAGE.findComponentByAbsoluteId(id);
                   if(c){ if(c.setValue)c.setValue(val);
                          if(typeof AdfValueChangeEvent!=='undefined') new AdfValueChangeEvent(c, '', val).queue(true); }
               }catch(e){}}""",
            [sel, str(valor)])
    except Exception as exc:
        logger.warning("commit ADF do valor '%s' no filtro (%s) falhou — filtro pode não aplicar no SIAFE 1: %s", valor, sel, exc)
    await pg.keyboard.press("Tab")


async def coletar_por_ug_grande(exercicio=2026, ug="180100", headless=True, prefixos=None, maxn=20000) -> dict:
    """UG GRANDE (>1000/ano): combina UG Emitente (linha 0) + Número 'começa com' <prefixo> (linha 1),
    iterando prefixos {ano}OB0..9 (sub-divide se uma fatia ainda bater ~1000). Fura o teto p/ UGs grandes."""
    from playwright.async_api import async_playwright
    from compliance_agent.siafe_adf import AdfSync
    if not prefixos:
        prefixos = [f"{exercicio}OB{d}" for d in range(10)]
    async with async_playwright() as pw:
        b, pg = await _novo_browser(pw, headless)
        try:
            if not (await _login(pg, exercicio)).get("ok"):
                return {"ok": False, "etapa": "login"}
            if not (await _navegar(pg)).get("ok"):
                return {"ok": False, "etapa": "nav"}
            adf = AdfSync(pg); await adf.boot()
            if await pg.locator(f'[id="{_F_PROP}"]').count() == 0:
                await _click_real(pg, _F_DISC); await adf.wait()
            # linha 0 = UG Emitente igual <ug>  (uma vez)
            await _typeahead(pg, _F_PROP, "UG Emi"); await adf.wait()
            await _typeahead(pg, _F_OP, "começa com"); await adf.wait()  # vale SIAFE 1 e 2 (UG=6 dígitos)
            await _set_valor(pg, _F_VAL_SEL, ug); await adf.wait()
            # linha 1 = Número começa com (prop/op uma vez; valor por prefixo)
            await _typeahead(pg, _F_PROP1, "Número"); await adf.wait()
            await _typeahead(pg, _F_OP1, "começa com"); await adf.wait()
            # worklist com SUBDIVISÃO automática + CHECKPOINT por prefixo (RESUMÍVEL: se cair no meio de uma
            # UG enorme, retoma sem re-coletar as fatias já feitas). Ckpt: {done:[leaf ok], capped:[subdivididos]}.
            import json as _json
            ckp = _REPO / "data" / "sei_cache" / f"uggrande_{ug}_{exercicio}.json"
            try:
                _st = _json.loads(ckp.read_text()) if ckp.exists() else {}
            except Exception:
                _st = {}
            done = set(_st.get("done", [])); capped = set(_st.get("capped", []))

            def _save_ckpt():
                try:
                    ckp.write_text(_json.dumps({"done": sorted(done), "capped": sorted(capped)}, ensure_ascii=False))
                except Exception as exc:
                    logger.warning("falha ao gravar checkpoint da UG %s (exercício %s) em %s: %s", ug, exercicio, ckp, exc)

            try:
                from compliance_agent import siafe_runner as _sr
            except Exception:
                _sr = None
            por_prefixo, tot, work = {}, 0, list(prefixos)
            while work:
                if _sr:
                    _sr.refresh_lock()                 # heartbeat por sub-prefixo (UG grande pode levar >30min)
                pref = work.pop(0)
                if pref in done:                       # já coletado numa execução anterior
                    continue
                if pref in capped:                     # já se sabe que estoura → subdivide sem re-consultar
                    work[:0] = [f"{pref}{d}" for d in range(10)]
                    continue
                await _set_valor(pg, _F_VAL1_SEL, pref); await adf.wait(); await pg.wait_for_timeout(2200)
                vistos, linhas = set(), []
                await _colher(pg, maxn, vistos, linhas, None)
                n = len(linhas)
                capou = n >= 990
                if capou and len(pref) - len(str(exercicio)) - 2 < 7:   # subdivide (limite de profundidade)
                    capped.add(pref); _save_ckpt()
                    work[:0] = [f"{pref}{d}" for d in range(10)]
                    print(f"  {ug} {exercicio} pref {pref}: {n} (CAP) → subdividindo", flush=True)
                else:
                    if linhas:                          # ingere fatia COMPLETA
                        tot += ingerir(exercicio, _COLS_SIAFE, linhas).get("ingeridas", 0)
                    done.add(pref); _save_ckpt(); por_prefixo[pref] = n
                    print(f"  {ug} {exercicio} pref {pref}: {n} OBs ✓", flush=True)
            return {"ok": True, "exercicio": exercicio, "ug": ug, "ingeridas": tot,
                    "fatias": len(por_prefixo), "por_prefixo": por_prefixo}
        finally:
            await b.close()


async def coletar_por_data(exercicio=2026, data="", headless=True, maxn=20000) -> dict:
    """VERIFICADOR/COMPLETADOR de DIA: coleta todas as OBs com Data Emissão = <data> (DD/MM/AAAA).
    Se o dia tiver >1000 OBs (cap), subdivide por Número 'começa com' prefixo (Data na linha 0 + Número
    na linha 1). Detecta o estouro (algum dia com >1000) E coleta o dia completo. Idempotente.
    ⚠️ Formato do campo de data (in_date) a validar ao vivo — assume DD/MM/AAAA. Ver doc §verificador-dia."""
    from playwright.async_api import async_playwright
    from compliance_agent.siafe_adf import AdfSync
    async with async_playwright() as pw:
        b, pg = await _novo_browser(pw, headless)
        try:
            if not (await _login(pg, exercicio)).get("ok"):
                return {"ok": False, "etapa": "login"}
            if not (await _navegar(pg)).get("ok"):
                return {"ok": False, "etapa": "nav"}
            adf = AdfSync(pg); await adf.boot()
            if await pg.locator(f'[id="{_F_PROP}"]').count() == 0:
                await _click_real(pg, _F_DISC); await adf.wait()
            # linha 0 = Data Emissão igual <data>  (campo é in_date, não in_value)
            await _typeahead(pg, _F_PROP, "Data Emi"); await adf.wait()
            await _typeahead(pg, _F_OP, "igual"); await adf.wait()
            datasel = '[id*="table_rtfFilter:0"] input[id*="in_date"]:visible, [id*="table_rtfFilter:0"] input[type="text"]:visible'
            await _set_valor(pg, datasel, data); await adf.wait(); await pg.wait_for_timeout(2500)
            n0 = await _contar_linhas(pg)
            estouro = n0 >= 990
            # coleta direta (sem subdividir) se < cap
            if not estouro:
                vistos, linhas = set(), []
                await _colher(pg, maxn, vistos, linhas, None)
                ing = ingerir(exercicio, _COLS_SIAFE, linhas) if linhas else {"ingeridas": 0}
                return {"ok": True, "data": data, "estouro": False, "colhidas": len(linhas),
                        "ingeridas": ing.get("ingeridas")}
            # ESTOURO: >1000 no dia → subdivide por Número (linha 1)
            await _typeahead(pg, _F_PROP1, "Número"); await adf.wait()
            await _typeahead(pg, _F_OP1, "começa com"); await adf.wait()
            try:
                from compliance_agent import siafe_runner as _sr
            except Exception:
                _sr = None
            tot, work = 0, [f"{exercicio}OB{d}" for d in range(10)]
            while work:
                if _sr:
                    _sr.refresh_lock()
                pref = work.pop(0)
                await _set_valor(pg, _F_VAL1_SEL, pref); await adf.wait(); await pg.wait_for_timeout(2000)
                vistos, linhas = set(), []
                await _colher(pg, maxn, vistos, linhas, None)
                n = len(linhas)
                if n >= 990 and len(pref) - len(str(exercicio)) - 2 < 7:
                    work[:0] = [f"{pref}{d}" for d in range(10)]
                elif linhas:
                    tot += ingerir(exercicio, _COLS_SIAFE, linhas).get("ingeridas", 0)
            return {"ok": True, "data": data, "estouro": True, "ingeridas": tot,
                    "detalhe": f">1000 OBs no dia {data} — coletado completo por subdivisão de Número"}
        finally:
            await b.close()


async def coletar_por_ug(exercicio=2026, ug="133100", headless=True, maxn=20000) -> dict:
    """Coleta TODAS as OBs de uma UG num exercício (fura o teto de 1000 filtrando por UG Emitente).
    Login → nav → filtra UG → colhe (scroll) → ingere. Ver docs/SIAFE-RIO2-GUIA-AUTOMACAO.md §8b."""
    from playwright.async_api import async_playwright
    from compliance_agent.siafe_adf import AdfSync
    async with async_playwright() as pw:
        b, pg = await _novo_browser(pw, headless)
        try:
            lg = await _login(pg, exercicio)
            if not lg.get("ok"):
                return {"ok": False, "etapa": "login", **lg}
            if not (await _navegar(pg)).get("ok"):
                return {"ok": False, "etapa": "navegacao"}
            adf = AdfSync(pg); await adf.boot()
            fr = await _filtrar_ug(pg, ug)
            if not fr.get("ok"):
                return {"ok": False, "etapa": "filtro", **fr}
            vistos, linhas = set(), []
            header = await _colher(pg, maxn, vistos, linhas, None)
            ing = ingerir(exercicio, header, linhas) if linhas else {"ingeridas": 0}
            return {"ok": True, "exercicio": exercicio, "ug": ug,
                    "colhidas": len(linhas), "ingeridas": ing.get("ingeridas")}
        finally:
            await b.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--exercicio", type=int, default=2025)
    ap.add_argument("--max", type=int, default=300)
    ap.add_argument("--ingerir", action="store_true", help="grava as OBs colhidas na compliance.db (SIAFE prepondera)")
    ap.add_argument("--resiliente", action="store_true", help="coordena via Telegram e retoma se a sessão cair")
    ap.add_argument("--por-numero", action="store_true", help="sweep por filtro Número 'começa com' (fura o teto de 1000)")
    ap.add_argument("--por-ug", default="", help="coleta TODAS as OBs de uma UG Emitente (ex: 133100 p/ ITERJ); fura o teto de 1000")
    ap.add_argument("--ug-grande", action="store_true", help="UG grande (>1000/ano): combina UG + Número 'começa com' por prefixo")
    ap.add_argument("--prefixos", default="", help="prefixos custom p/ --por-numero, separados por vírgula (ex: 2026OB0,2026OB1)")
    a = ap.parse_args()
    if a.por_ug:
        fn = coletar_por_ug_grande if a.ug_grande else coletar_por_ug
        res = asyncio.run(fn(a.exercicio, a.por_ug.strip()))
        print(json.dumps(res, ensure_ascii=False, indent=1)); return
    if a.por_numero:
        pref = [p.strip() for p in a.prefixos.split(",") if p.strip()] or None
        res = asyncio.run(coletar_filtrado(a.exercicio, pref, maxn=a.max))
        print(json.dumps(res, ensure_ascii=False, indent=1)); return
    elif a.resiliente:
        res = asyncio.run(coletar_resiliente(a.exercicio, a.max))
    else:
        res = asyncio.run(coletar(a.exercicio, a.max))
    if not res.get("ok"):
        print(json.dumps(res, ensure_ascii=False, indent=1)); return
    print(f"OK — {res['n']} OBs colhidas (exercício {res['exercicio']})")
    if a.ingerir:
        ing = ingerir(res["exercicio"], res.get("header", []), res.get("linhas", []))
        print(f"INGESTÃO: {ing.get('ingeridas')} OBs gravadas | total na tabela: {ing.get('total_tabela')}")
    print("HEADER:", res.get("header"))
    for r in res.get("linhas", [])[:5]:
        print("  ", r[:10])


if __name__ == "__main__":
    main()
