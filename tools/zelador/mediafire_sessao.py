#!/usr/bin/env python3
"""Renova SOZINHO a sessão do MediaFire no OpenList (remoto `mediafire:` do rclone) — dono, 23/11/2026: "só
mantém se a renovação for automática e sem mim".

O driver MediaFire do OpenList só aceita COOKIE (sem e-mail/senha nem token renovável) e o session_token que ele
tira do cookie expira em horas sem se renovar (medido 22-23/11: listou 22:11, 500 às 00:10). Por isso, todo dia:
  1. recarrega o storage com session_token vazio → o driver pega um token novo do cookie;
  2. se o remoto não lista: login headless (patchright + Chromium em xvfb, e-mail/senha de ~/.config/jfn/nuvens.env)
     → cookie novo em ~/.config/jfn/mediafire.cookie (0600) → /api/admin/storage/update → lista de novo;
  3. não voltou → suspende `mediafire` em ~/.zelador/nuvens_suspensas.json (sai da 2ª cópia, ver
     armazenamento.configurar); voltou → tira a suspensão. Sem aviso ao Yoda: o registro vai para o log.
Credenciais nunca em argv/log. Um navegador por vez (flock no cron)."""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from compliance_agent import armazenamento as A  # noqa: E402

CFG = Path.home() / ".config" / "jfn"
COOKIE = CFG / "mediafire.cookie"
OL = "http://127.0.0.1:5244"
MONTAGEM = "/mediafire"
CHROME = Path.home() / ".cache" / "ms-playwright" / "chromium-1228" / "chrome-linux" / "chrome"
NOMES_SESSAO = {"ukey", "user", "session", "skey"}


def _env(p: Path) -> dict:
    d = {}
    for linha in p.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if linha and not linha.startswith("#") and "=" in linha:
            k, v = linha.split("=", 1)
            d[k.strip().removeprefix("export ").strip()] = v.strip().strip("\"'")
    return d


def _api(caminho: str, dados=None, token: str | None = None) -> dict:
    r = urllib.request.Request(OL + caminho, data=None if dados is None else json.dumps(dados).encode(),
                               headers={"Content-Type": "application/json", **({"Authorization": token} if token else {})})
    return json.load(urllib.request.urlopen(r, timeout=60))


def _token() -> str:
    e = _env(CFG / "openlist.env")
    return _api("/api/auth/login", {"username": e["OL_ADMIN_USER"], "password": e["OL_ADMIN_SENHA"]})["data"]["token"]


def recarregar(cookie: str | None = None) -> str:
    """Storage do MediaFire com session_token vazio (e cookie novo, se vier). Devolve o status do OpenList."""
    t = _token()
    s = next(x for x in _api("/api/admin/storage/list", token=t)["data"]["content"] if x["mount_path"] == MONTAGEM)
    a = json.loads(s.get("addition") or "{}")
    a["session_token"] = ""
    if cookie:
        a["cookie"] = cookie
    s["addition"] = json.dumps(a)
    msg = _api("/api/admin/storage/update", s, token=t).get("message", "")
    s = next(x for x in _api("/api/admin/storage/list", token=t)["data"]["content"] if x["mount_path"] == MONTAGEM)
    return f"{msg}/{s.get('status', '')[:120]}"


def lista() -> bool:
    try:
        r = subprocess.run([A._binario_rclone(), "lsf", "--max-depth", "1", "mediafire:"], capture_output=True,
                           text=True, timeout=180)
    except subprocess.TimeoutExpired:
        return False
    return r.returncode == 0


async def _login() -> str | None:
    from patchright.async_api import async_playwright
    e = _env(CFG / "nuvens.env")
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=False, executable_path=str(CHROME))
        try:
            ctx = await b.new_context()
            pg = await ctx.new_page()
            await pg.goto("https://www.mediafire.com/login/", timeout=90_000)
            await pg.wait_for_timeout(4000)
            await pg.fill("#widget_login_email", e["MEDIAFIRE_EMAIL"])
            await pg.fill("#widget_login_pass", e["MEDIAFIRE_SENHA"])
            if not await pg.is_checked("#login_remember"):
                await pg.check("#login_remember", force=True)
            await pg.click("#widget_login_submit, button[type=submit]")
            await pg.wait_for_timeout(15_000)
            cks = [c for c in await ctx.cookies() if "mediafire.com" in c.get("domain", "")]
        finally:
            await b.close()
    if not NOMES_SESSAO <= {c["name"] for c in cks}:
        return None                       # captcha/2FA/senha errada: sem os cookies de sessão
    return "; ".join(f"{c['name']}={c['value']}" for c in cks)


def login_headless() -> str | None:
    try:
        from patchright.async_api import Error as ErroNavegador
    except ImportError as ex:
        print(f"  login impossível: {type(ex).__name__}")
        return None
    try:
        cookie = asyncio.run(asyncio.wait_for(_login(), 240))
    except (ErroNavegador, OSError, KeyError, asyncio.TimeoutError) as ex:   # registra a classe, nunca o conteúdo
        print(f"  login falhou: {type(ex).__name__}")
        return None
    if cookie:
        COOKIE.write_text(cookie, encoding="utf-8")
        COOKIE.chmod(0o600)
    return cookie


def marcar(ok: bool, motivo: str = "") -> None:
    p = A.caminho_suspensas()
    s = A.suspensas()
    if ok:
        s.pop("mediafire", None)
    else:
        s["mediafire"] = f"{dt.datetime.now().isoformat(timespec='seconds')} {motivo}"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")


def main(argv=None) -> int:
    forcar = "--forcar-login" in (argv if argv is not None else sys.argv[1:])
    agora = dt.datetime.now().isoformat(timespec="seconds")
    passo = "recarregar"
    try:
        st = recarregar()
        ok = lista() and not forcar
        if not ok:
            passo = "login"
            cookie = login_headless()
            st = recarregar(cookie) if cookie else "sem cookie de sessão (captcha/2FA/senha?)"
            ok = bool(cookie) and lista()
    except (OSError, KeyError, ValueError, StopIteration) as ex:      # URLError é OSError
        ok, st = False, f"{passo}: {type(ex).__name__}"
    marcar(ok, st)
    print(f"{agora} mediafire {'ok' if ok else 'SUSPENSO'} ({passo}: {st})")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
