# -*- coding: utf-8 -*-
"""
SEI - leitor de sessao via ponte CDP do Chrome (porta 9222).
Uso LEGITIMO: Mestre Jorge loga no SEI no proprio Chrome; aqui apenas
reaproveitamos a sessao (cookies) para pesquisar no RITMO HUMANO.
NUNCA quebra captcha, NUNCA se passa por terceiros, NUNCA burla TLS.
Credenciais ficam so no ~/.hermes/.env (nao aqui).
"""
import sys, json, time, random, urllib.request
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import websocket  # websocket-client
import requests

CDP = "http://127.0.0.1:9222"
SEI_BASE = "https://sei.rj.gov.br"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36")


def _http(path):
    return urllib.request.urlopen(CDP + path, timeout=8).read().decode()


def achar_aba_sei():
    """Retorna (ws_url, page_url) da aba do SEI, ou (None,None)."""
    tabs = json.loads(_http("/json/list"))
    for t in tabs:
        if t.get("type") == "page" and "sei.rj.gov.br" in (t.get("url") or ""):
            return t.get("webSocketDebuggerUrl"), t.get("url")
    # senao, pega qualquer page
    for t in tabs:
        if t.get("type") == "page":
            return t.get("webSocketDebuggerUrl"), t.get("url")
    return None, None


def _cdp(ws_url, method, params=None, _id=1):
    ws = websocket.create_connection(ws_url, timeout=10, suppress_origin=True)
    try:
        ws.send(json.dumps({"id": _id, "method": method, "params": params or {}}))
        while True:
            msg = json.loads(ws.recv())
            if msg.get("id") == _id:
                return msg
    finally:
        ws.close()


def ler_cookies():
    ws_url, page_url = achar_aba_sei()
    if not ws_url:
        return None, "Nenhuma aba do Chrome encontrada na ponte (porta 9222)."
    res = _cdp(ws_url, "Network.getCookies", {"urls": [SEI_BASE]})
    cookies = res.get("result", {}).get("cookies", [])
    return cookies, page_url


def status():
    cookies, page_url = ler_cookies()
    if cookies is None:
        print("ERRO:", page_url)
        return
    nomes = [c["name"] for c in cookies]
    url = (page_url or "")
    print("Aba atual:", url[:90])
    print("Cookies do SEI:", len(cookies), "->", ", ".join(nomes[:12]))
    # logado de verdade = saiu da pagina de login (entrou no controlador)
    logado = ("controlador.php" in url) or ("/sei/" in url and "login.php" not in url)
    if "login.php" in url:
        print("Estado: na TELA DE LOGIN -> faca login no Chrome (sua credencial ITERJ).")
    elif logado:
        print("Estado: LOGADO no SEI. Pronto para pesquisar no ritmo humano.")
    else:
        print("Estado: indefinido -> abra/atualize a aba do SEI.")
    return cookies


def jar_de(cookies):
    s = requests.Session()
    s.headers.update({"User-Agent": UA})
    for c in cookies:
        s.cookies.set(c["name"], c["value"], domain=c.get("domain", "sei.rj.gov.br").lstrip("."))
    return s


def _eval(ws_url, expr, _id=2):
    res = _cdp(ws_url, "Runtime.evaluate",
               {"expression": expr, "returnByValue": True}, _id=_id)
    return res.get("result", {}).get("result", {}).get("value")


def _ler_env(chave):
    import os
    # 1) variável de ambiente tem prioridade (padrão multiplataforma do projeto)
    val = os.environ.get(chave)
    if val:
        return val.strip()
    # 2) fallback portável: JFN_ENV_FILE > ~/.hermes/.env > .env do Hermes no Windows > <repo>/.env
    win = r"C:\Users\socah\AppData\Local\hermes\.env"
    repo_env = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    for env in (os.environ.get("JFN_ENV_FILE"),
                os.path.expanduser("~/.hermes/.env"),
                win if os.path.exists(win) else None,
                repo_env):
        if not env or not os.path.exists(env):
            continue
        with open(env, "r", encoding="utf-8", errors="replace") as f:
            for ln in f:
                ln = ln.strip()
                if ln.startswith(chave + "="):
                    return ln.split("=", 1)[1].strip()
    return None


def login():
    """Preenche o login do SEI no ritmo humano (credencial do .env)."""
    ws_url, page_url = achar_aba_sei()
    if not ws_url:
        print("ERRO: ponte CDP nao encontrou a aba do SEI (porta 9222).")
        return
    if "login.php" not in (page_url or ""):
        print("A aba nao esta na tela de login. URL:", (page_url or "")[:80])
        print("Se ja estiver logado, nao preciso logar de novo.")
        return
    usuario = _ler_env("SEI_USUARIO")
    senha = _ler_env("SEI_SENHA")
    orgao_val = "71"  # ITERJ
    if not usuario or not senha:
        print("ERRO: SEI_USUARIO/SEI_SENHA nao encontrados no .env")
        return
    print("Preenchendo usuario...", usuario)
    _eval(ws_url, "document.getElementById('txtUsuario').value=%r;" % usuario, _id=10)
    time.sleep(random.uniform(1.2, 2.2))
    print("Selecionando orgao ITERJ (71)...")
    _eval(ws_url, "document.getElementById('selOrgao').value=%r;" % orgao_val, _id=11)
    time.sleep(random.uniform(1.0, 2.0))
    print("Preenchendo senha (oculta)...")
    # json.dumps escapa a senha com seguranca; nao imprime a senha
    _eval(ws_url, "document.getElementById('pwdSenha').value=" + json.dumps(senha) + ";", _id=12)
    time.sleep(random.uniform(1.5, 3.0))
    print("Enviando login...")
    _eval(ws_url, "document.getElementById('frmLogin').submit();", _id=13)
    time.sleep(4.0)
    status()


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "status":
        status()
    elif cmd == "login":
        login()
