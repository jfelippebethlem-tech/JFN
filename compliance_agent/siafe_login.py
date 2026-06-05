# -*- coding: utf-8 -*-
"""
SIAFE-Rio 2 — login DIRETO da VM Linux (Playwright headless).

DESCOBERTA (2026-06-05): a VM GCP acessa o SIAFE direto (o WAF não bloqueia este IP). Logo a coleta
de OBs pode rodar na VM 24/7, sem GitHub Actions. Este módulo faz o login (a etapa que valida tudo).

Credenciais: SIAFE_USER (CPF) e SIAFE_PASS, lidas SÓ do ambiente/.env (nunca hardcoded). Se ainda
estiverem com os placeholders do .env.example (SEU_CPF/SUA_SENHA), o script NÃO submete nada ao
servidor do governo — apenas confirma que a página está acessível e avisa que faltam credenciais.

Trata os popups aprendidos: nunca clicar no btnConfirmar do form de login indevidamente; popup de
"sistema aberto em outra janela" → clicar "Sim"; tecla de submit é "Enter" (não "Return"). MFA: se
detectado, retorna status 'mfa' para a IA pedir o código ao Mestre Jorge.

Uso: python -m compliance_agent.siafe_login [--exercicio 2025]
"""
import os
import sys

LOGIN_URL = "https://siafe2.fazenda.rj.gov.br/Siafe/faces/login.jsp"
EXERCICIOS = {2027: "0", 2026: "1", 2025: "2", 2024: "3", 2023: "4"}


def _creds():
    u = (os.environ.get("SIAFE_USER") or "").strip()
    p = (os.environ.get("SIAFE_PASS") or "").strip()
    placeholder = (not u or not p or u.upper().startswith("SEU_") or p.upper().startswith("SUA_"))
    return u, p, placeholder


def login(exercicio=2025, headless=True, timeout_ms=45000):
    """Tenta logar no SIAFE. Retorna dict {status, detail}.
    status: 'ok' | 'mfa' | 'erro_credencial' | 'sem_credencial' | 'pagina_inacessivel' | 'erro'."""
    u, p, placeholder = _creds()

    # 1) a página está acessível desta VM?
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        return {"status": "erro", "detail": f"playwright ausente: {e}"}

    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=headless, args=["--no-sandbox", "--ignore-certificate-errors"])
        pg = b.new_page(ignore_https_errors=True)
        try:
            resp = pg.goto(LOGIN_URL, timeout=timeout_ms, wait_until="domcontentloaded")
            if not resp or resp.status >= 400:
                return {"status": "pagina_inacessivel", "detail": f"HTTP {resp.status if resp else '?'}"}
            tem_user = pg.locator("input[type=text]").count() > 0
            tem_pass = pg.locator("input[type=password]").count() > 0
            if not (tem_user and tem_pass):
                return {"status": "pagina_inacessivel", "detail": "formulário de login não encontrado"}

            if placeholder:
                return {"status": "sem_credencial",
                        "detail": "Página do SIAFE acessível da VM e formulário OK. "
                                  "Faltam SIAFE_USER/SIAFE_PASS reais no ~/JFN/.env (estão com placeholder)."}

            # 2) preenche e submete (só com credenciais reais)
            pg.locator("input[type=text]").first.fill(u)
            pg.locator("input[type=password]").first.fill(p)
            # seleciona exercício, se houver dropdown
            try:
                sel = pg.locator("select").first
                if sel.count():
                    sel.select_option(label=str(exercicio))
            except Exception:
                pass
            pg.keyboard.press("Enter")
            pg.wait_for_timeout(6000)

            # 3) trata popup "sistema aberto em outra janela" → Sim
            for _ in range(3):
                txt = (pg.inner_text("body") or "").lower()
                if "outra janela" in txt or "deseja acess" in txt:
                    for lbl in ["Sim", "OK", "Ok"]:
                        try:
                            btn = pg.get_by_text(lbl, exact=True)
                            if btn.count():
                                btn.first.click(); pg.wait_for_timeout(3000); break
                        except Exception:
                            pass
                else:
                    break

            body = (pg.inner_text("body") or "").lower()
            if any(k in body for k in ["token", "código", "codigo", "verificação", "autenticação de dois"]):
                return {"status": "mfa", "detail": "SIAFE pediu MFA — pedir o código ao Mestre Jorge."}
            if any(k in body for k in ["usuário ou senha", "senha inválida", "inválido", "não autorizado"]):
                return {"status": "erro_credencial", "detail": "Usuário/senha rejeitados pelo SIAFE."}
            # heurística de sucesso: saiu da tela de login
            if "esqueceu sua senha" not in body:
                return {"status": "ok", "detail": "Login aparentemente bem-sucedido (saiu da tela de login)."}
            return {"status": "erro", "detail": "Estado pós-login indeterminado — inspecionar."}
        except Exception as e:
            return {"status": "erro", "detail": f"{type(e).__name__}: {str(e)[:120]}"}
        finally:
            b.close()


if __name__ == "__main__":
    ex = 2025
    if "--exercicio" in sys.argv:
        ex = int(sys.argv[sys.argv.index("--exercicio") + 1])
    import json
    print(json.dumps(login(exercicio=ex), ensure_ascii=False, indent=1))
