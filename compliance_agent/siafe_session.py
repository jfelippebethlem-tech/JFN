# -*- coding: utf-8 -*-
"""
SIAFE-Rio 2 — login com MFA + persistência de sessão (coleta automática 24/7 sem repetir MFA).

Estratégia: a tela de MFA do SIAFE tem a opção "Dispensar código neste dispositivo por 30 dias".
Ao logar UMA vez com o código e MARCAR essa caixa, salvamos o estado do navegador
(`data/sei_cache/siafe_state.json`). As coletas seguintes REUSAM esse estado → sem MFA por ~30 dias.
Quando expirar, basta um novo login com código.

Fluxo do código MFA (sem interação direta): este script aguarda o código aparecer no arquivo
`data/sei_cache/.mfa_code` (a IA pergunta ao Mestre Jorge e grava ali). Polling com timeout.

Uso:
    python -m compliance_agent.siafe_session --login [--exercicio 2025]   # login+MFA, salva sessão
    python -m compliance_agent.siafe_session --check                      # sessão salva ainda vale?
"""
import os
import sys
from pathlib import Path

LOGIN_URL = "https://siafe2.fazenda.rj.gov.br/Siafe/faces/login.jsp"
_REPO = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("JFN_DATA_DIR", _REPO / "data")) / "sei_cache"
STATE = DATA / "siafe_state.json"
CODE_FILE = DATA / ".mfa_code"

ID_USER = '[id="loginBox:itxUsuario::content"]'
ID_PASS = '[id="loginBox:itxSenhaAtual::content"]'
ID_MFA = '[id="loginBox:frmTokenMfa:itxTokenMfa::content"]'
ID_TRUST = '[id="loginBox:frmTokenMfa:ckTrustDevice::content"]'


def _launch(pw, headless=True):
    return pw.chromium.launch(headless=headless, args=["--no-sandbox", "--ignore-certificate-errors"])


def login_with_mfa(exercicio=2025, wait_code_s=300):
    U = os.environ.get("SIAFE_USER", ""); P = os.environ.get("SIAFE_PASS", "")
    if not U or not P or U.upper().startswith("SEU_"):
        return {"status": "sem_credencial"}
    DATA.mkdir(parents=True, exist_ok=True)
    if CODE_FILE.exists():
        CODE_FILE.unlink()
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        b = _launch(pw)
        ctx = b.new_context(ignore_https_errors=True)
        pg = ctx.new_page()
        try:
            pg.goto(LOGIN_URL, timeout=45000, wait_until="domcontentloaded")
            pg.locator(ID_USER).fill(U)
            pg.locator(ID_PASS).fill(P)
            try:
                sel = pg.locator("select").first
                if sel.count():
                    sel.select_option(label=str(exercicio))
            except Exception:
                pass
            pg.keyboard.press("Enter")
            pg.wait_for_timeout(6000)

            # MFA?
            if pg.locator(ID_MFA).count():
                print("[SIAFE] MFA solicitado — pedindo o código ao Mestre Jorge no Telegram…", flush=True)
                # Fluxo codificado (mfa_telegram): envia o pedido no Telegram e captura a resposta do dono
                # passivamente do state.db do Yoda (+ fallback no arquivo .mfa_code). Import lazy p/ evitar
                # custo/circular no load do módulo.
                from compliance_agent.mfa_telegram import pedir_codigo_mfa
                code = pedir_codigo_mfa("SIAFE", timeout_s=wait_code_s)
                if not code:
                    return {"status": "timeout_mfa", "detail": f"sem código em {wait_code_s}s"}
                pg.locator(ID_MFA).fill(code)
                # marca "dispensar por 30 dias" (device trust) -> evita MFA futuro
                try:
                    if pg.locator(ID_TRUST).count():
                        pg.locator(ID_TRUST).check()
                except Exception:
                    pass
                # submete clicando o "Ok" DO FORM DE MFA (frmTokenMfa) — Enter não basta no ADF
                clicked = False
                try:
                    mfa_ok = pg.locator('[id^="loginBox:frmTokenMfa"]').get_by_text("Ok", exact=True)
                    if mfa_ok.count():
                        mfa_ok.first.click(); clicked = True
                except Exception:
                    pass
                if not clicked:
                    for sel in ['[id*="frmTokenMfa"] a', '[id*="frmTokenMfa"] button', '[id*="frmTokenMfa"] [role=button]']:
                        try:
                            loc = pg.locator(sel)
                            for i in range(loc.count()):
                                el = loc.nth(i)
                                if (el.inner_text() or "").strip().lower() in ("ok", "confirmar", "enviar"):
                                    el.click(); clicked = True; break
                        except Exception:
                            pass
                        if clicked:
                            break
                if not clicked:
                    pg.locator(ID_MFA).press("Enter")
                pg.wait_for_timeout(8000)

            body = (pg.inner_text("body") or "").lower()
            if "código de autenticação" in body or pg.locator(ID_MFA).count():
                return {"status": "mfa_falhou", "detail": "código rejeitado ou MFA persistiu"}
            if any(k in body for k in ["usuário ou senha", "inválid", "não autorizado"]):
                return {"status": "erro_credencial"}
            if "esqueceu sua senha" in body and not pg.locator(ID_MFA).count():
                return {"status": "login_incompleto", "detail": "voltou à tela de login"}
            # sucesso: salva sessão
            ctx.storage_state(path=str(STATE))
            return {"status": "ok", "sessao_salva": str(STATE)}
        except Exception as e:
            return {"status": "erro", "detail": f"{type(e).__name__}: {str(e)[:140]}"}
        finally:
            b.close()


def check_session():
    """Abre o SIAFE com a sessão salva e diz se ainda está autenticado."""
    if not STATE.exists():
        return {"status": "sem_sessao"}
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        b = _launch(pw)
        ctx = b.new_context(ignore_https_errors=True, storage_state=str(STATE))
        pg = ctx.new_page()
        try:
            pg.goto("https://siafe2.fazenda.rj.gov.br/Siafe/faces/", timeout=45000, wait_until="domcontentloaded")
            pg.wait_for_timeout(4000)
            body = (pg.inner_text("body") or "").lower()
            logado = "esqueceu sua senha" not in body and "usuário" not in body[:200]
            return {"status": "valida" if logado else "expirada"}
        except Exception as e:
            return {"status": "erro", "detail": str(e)[:100]}
        finally:
            b.close()


if __name__ == "__main__":
    import json
    ex = 2025
    if "--exercicio" in sys.argv:
        ex = int(sys.argv[sys.argv.index("--exercicio") + 1])
    if "--check" in sys.argv:
        print(json.dumps(check_session(), ensure_ascii=False))
    else:
        print(json.dumps(login_with_mfa(exercicio=ex), ensure_ascii=False))
