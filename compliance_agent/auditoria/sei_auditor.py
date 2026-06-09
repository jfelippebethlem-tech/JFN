# -*- coding: utf-8 -*-
"""
SEI AUDITOR — ferramenta SIMPLES para o agente JFN (Gemini Flash).

USO (uma linha):
    python sei_auditor.py SEI-070026/001185/2020
ou:
    python sei_auditor.py 070026/001185/2020

O que ela faz SOZINHA:
  1) Garante o Chrome-ponte ligado (porta 9222).
  2) Garante login no SEI (reusa sessao; se cair, loga de novo com .env).
  3) Pesquisa o processo (SEM captcha, logado).
  4) Imprime um resultado LIMPO (e salva em data/sei_cache).

Regras: so LEITURA. Ritmo humano. Credenciais so no .env.
Uso legitimo do Mestre Jorge (deputado) para auditoria/compliance.
"""
import sys
import os
import json
import time
import random
import urllib.request
import subprocess

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import websocket  # websocket-client

# ---------- CONFIG ----------
CDP_PORT = 9222
CDP = "http://127.0.0.1:%d" % CDP_PORT
# Raiz do repo (este arquivo: <repo>/compliance_agent/auditoria/sei_auditor.py)
_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_DATA = os.environ.get("JFN_DATA_DIR", os.path.join(_REPO, "data"))
# Windows mantém os defaults antigos; Linux/Mac usa env ou fallback gracioso.
PROFILE = os.environ.get("CHROME_DEBUG_PROFILE", os.path.join(_DATA, "tmp", "chrome_debug_profile"))
CHROME = os.environ.get("CHROME_BIN", r"C:\Program Files\Google\Chrome\Application\chrome.exe")
# Windows continua lendo o .env do Hermes se existir; Linux/Mac usa o .env do repo.
_WIN_HERMES_ENV = r"C:\Users\socah\AppData\Local\hermes\.env"
ENV = os.environ.get("JFN_ENV_FILE") or (_WIN_HERMES_ENV if os.path.exists(_WIN_HERMES_ENV) else os.path.join(_REPO, ".env"))
CACHE = os.path.join(_DATA, "sei_cache")
ORGAO_VALOR = "71"  # ITERJ


def env(chave, default=None):
    try:
        with open(ENV, "r", encoding="utf-8", errors="replace") as f:
            for ln in f:
                ln = ln.strip()
                if ln.startswith(chave + "="):
                    return ln.split("=", 1)[1].strip()
    except Exception:
        pass
    return default


LOGIN_URL = env("SEI_LOGIN_URL",
                "https://sei.rj.gov.br/sip/login.php?sigla_orgao_sistema=ERJ&sigla_sistema=SEI&infra_url=L3NlaS8=")


def log(msg):
    print("[SEI]", msg, flush=True)


# ---------- CDP basico ----------
def _tabs():
    return json.loads(urllib.request.urlopen(CDP + "/json/list", timeout=8).read())


def chrome_ligado():
    try:
        urllib.request.urlopen(CDP + "/json/version", timeout=4).read()
        return True
    except Exception:
        return False


def ligar_chrome():
    if chrome_ligado():
        return True
    log("Ligando o Chrome-ponte...")
    try:
        subprocess.Popen([CHROME, "--remote-debugging-port=%d" % CDP_PORT,
                          "--user-data-dir=" + PROFILE, "--new-window", LOGIN_URL],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        log("ERRO ao abrir Chrome: %s" % e)
        return False
    for _ in range(15):
        time.sleep(1)
        if chrome_ligado():
            log("Chrome-ponte no ar.")
            return True
    return False


def aba_sei(tries=6):
    for _ in range(tries):
        try:
            cand = [t for t in _tabs() if t.get("type") == "page"
                    and "sei.rj.gov.br" in (t.get("url") or "")
                    and t.get("webSocketDebuggerUrl")]
            if cand:
                return cand[0]
        except Exception:
            pass
        time.sleep(1.5)
    return None


class Aba:
    """Conexao com a aba do SEI; reabre sozinha apos navegar."""
    def __init__(self):
        self.ws = None
        self._open()

    def _open(self):
        t = aba_sei()
        if not t:
            raise RuntimeError("Nenhuma aba do SEI encontrada na ponte.")
        self.ws = websocket.create_connection(t["webSocketDebuggerUrl"],
                                              timeout=25, suppress_origin=True)
        self.i = 0

    def ev(self, expr, tmo=25):
        self.i += 1
        mid = self.i
        self.ws.settimeout(tmo)
        try:
            self.ws.send(json.dumps({"id": mid, "method": "Runtime.evaluate",
                                     "params": {"expression": expr, "returnByValue": True,
                                                "awaitPromise": True}}))
            while True:
                m = json.loads(self.ws.recv())
                if m.get("id") == mid:
                    return m.get("result", {}).get("result", {}).get("value")
        except Exception:
            return None

    def go(self, url, espera=4):
        self.ev("location.href=%r;0" % url, tmo=8)
        time.sleep(espera)
        self.renew()

    def renew(self):
        try:
            self.ws.close()
        except Exception:
            pass
        time.sleep(1.5)
        self._open()

    def url(self):
        return self.ev("location.href") or ""


# ---------- LOGIN ----------
def esta_logado(aba):
    u = aba.url()
    return ("controlador.php" in u) and ("login.php" not in u)


def login(aba):
    u = aba.url()
    if "login.php" not in u:
        aba.go(LOGIN_URL)
    usuario = env("SEI_USUARIO")
    senha = env("SEI_SENHA")
    if not usuario or not senha:
        log("ERRO: SEI_USUARIO/SEI_SENHA ausentes no .env")
        return False
    log("Logando como %s / ITERJ..." % usuario)
    aba.ev("var u=document.getElementById('txtUsuario');u.focus();u.value=%r;u.dispatchEvent(new Event('input',{bubbles:true}));0" % usuario)
    time.sleep(random.uniform(1.0, 1.8))
    aba.ev("var o=document.getElementById('selOrgao');o.value=%r;o.dispatchEvent(new Event('change',{bubbles:true}));0" % ORGAO_VALOR)
    time.sleep(random.uniform(0.8, 1.5))
    aba.ev("var p=document.getElementById('pwdSenha');p.focus();p.value=" + json.dumps(senha) + ";p.dispatchEvent(new Event('input',{bubbles:true}));0")
    time.sleep(random.uniform(1.0, 1.8))
    aba.ev("document.getElementById('sbmAcessar').click();0", tmo=8)
    time.sleep(6)
    aba.renew()
    ok = esta_logado(aba)
    log("Login OK." if ok else "Login NAO entrou (confira a senha no .env).")
    return ok


def garantir_login(aba):
    if esta_logado(aba):
        return True
    return login(aba)


# ---------- PESQUISA ----------
def ir_para_pesquisa(aba):
    href = aba.ev("(function(){var a=[...document.querySelectorAll('a')].find(x=>(x.getAttribute('href')||'').includes('acao=protocolo_pesquisar'));return a?a.href:''})()")
    if href and href.startswith("http"):
        aba.go(href)
        return "protocolo_pesquisar" in aba.url()
    return False


def buscar(numero):
    numero = numero.strip().replace("SEI-", "").replace("sei-", "")
    if not ligar_chrome():
        return {"ok": False, "erro": "nao consegui ligar o Chrome-ponte"}
    aba = Aba()
    if not garantir_login(aba):
        return {"ok": False, "erro": "login falhou"}
    time.sleep(random.uniform(2, 4))  # ritmo humano
    if not ir_para_pesquisa(aba):
        return {"ok": False, "erro": "nao cheguei na pagina de pesquisa"}
    log("Pesquisando %s ..." % numero)
    aba.ev("var p=document.getElementById('txtProtocoloPesquisa');p.focus();p.value=%r;p.dispatchEvent(new Event('input',{bubbles:true}));0" % numero)
    time.sleep(random.uniform(1.5, 2.5))
    # confere que o campo foi preenchido
    val = aba.ev("var e=document.getElementById('txtProtocoloPesquisa');e?e.value:''")
    log("campo nº = %r" % val)
    aba.ev("(document.getElementById('sbmPesquisar')||document.querySelector('[name=sbmPesquisar]')).click();0", tmo=10)
    # espera os resultados aparecerem (poll ate 18s)
    txt = ""
    for _ in range(9):
        time.sleep(2)
        aba.renew()
        txt = aba.ev("document.body.innerText") or ""
        if ("Exibindo" in txt) or ("Nenhum registro" in txt) or ("não encontr" in txt.lower()):
            break
    # contagem
    import re
    mcount = re.search(r"Exibindo[^\n]{0,40}", txt)
    contagem = mcount.group(0).strip() if mcount else "(sem contagem)"
    # documentos (links procedimento_trabalhar com texto = numero)
    docs_raw = aba.ev("""JSON.stringify([...document.querySelectorAll('a')]
      .filter(a=>/procedimento_trabalhar/.test(a.getAttribute('href')||'') && a.innerText.trim())
      .map(a=>a.innerText.trim()).slice(0,30))""")
    try:
        docs = json.loads(docs_raw or "[]")
    except Exception:
        docs = []
    # bloco de texto dos resultados
    i = txt.find("Exibindo")
    bloco = txt[i:i + 3000] if i >= 0 else ""
    # salva
    os.makedirs(CACHE, exist_ok=True)
    safe = numero.replace("/", "_")
    open(os.path.join(CACHE, "busca_%s.txt" % safe), "w", encoding="utf-8").write(bloco)
    return {"ok": True, "numero": numero, "contagem": contagem,
            "qtd_documentos": len(docs), "documentos": docs,
            "arquivo": os.path.join(CACHE, "busca_%s.txt" % safe)}


def main():
    if len(sys.argv) < 2:
        print("Uso: python sei_auditor.py <NUMERO_DO_PROCESSO>")
        print("Ex.: python sei_auditor.py 070026/001185/2020")
        return
    numero = sys.argv[1]
    r = buscar(numero)
    print("\n========== RESULTADO ==========")
    if not r.get("ok"):
        print("FALHOU:", r.get("erro"))
        return
    print("Processo:", r["numero"])
    print(r["contagem"])
    print("Documentos encontrados:", r["qtd_documentos"])
    for d in r["documentos"][:12]:
        print("  -", d[:90])
    print("Detalhe salvo em:", r["arquivo"])
    print("===============================")


if __name__ == "__main__":
    main()
