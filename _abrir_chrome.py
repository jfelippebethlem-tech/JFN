"""
_abrir_chrome.py — chamado pelo HERMES.bat para abrir o Chrome debug.

Usa exatamente o mesmo codigo do agente (hermes_goal.abrir_chrome_debug),
garantindo comportamento identico entre o launcher e o agente em si.
Sai com codigo 0 se a porta 9222 subiu, 1 se falhou.
"""
import asyncio
import os
import platform
import subprocess
import sys
from pathlib import Path


def _achar_chrome():
    if platform.system() == "Windows":
        for env in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
            base = os.environ.get(env, "")
            if base:
                p = Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe"
                if p.exists():
                    return str(p)
    else:
        import shutil
        for nome in ("google-chrome", "chrome", "chromium", "chromium-browser"):
            achado = shutil.which(nome)
            if achado:
                return achado
    return None


async def _checar_porta():
    import urllib.request
    try:
        urllib.request.urlopen("http://127.0.0.1:9222/json/version", timeout=2)
        return True
    except Exception:
        return False


async def main():
    if await _checar_porta():
        print("        OK - Chrome debug ja estava no ar (9222)")
        return 0

    exe = _achar_chrome()
    if not exe:
        print("        ERRO: Chrome nao encontrado no sistema.")
        return 1

    if platform.system() == "Windows":
        base = os.environ.get("LOCALAPPDATA", str(Path.home()))
        perfil = str(Path(base) / "JFN" / "ChromeDebug")
    else:
        perfil = str(Path.home() / ".config" / "jfn-chrome-debug")

    print(f"        Perfil JFN: {perfil}")
    print("        Abrindo Chrome com porta 9222...")

    args = [
        exe,
        "--remote-debugging-port=9222",
        f"--user-data-dir={perfil}",
        "--no-first-run",
        "--no-default-browser-check",
        "https://siafe2.fazenda.rj.gov.br/Siafe/",
    ]
    try:
        kwargs: dict = {}
        if platform.system() == "Windows":
            kwargs["creationflags"] = 0x00000008  # DETACHED_PROCESS
        else:
            kwargs["start_new_session"] = True
        subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **kwargs,
        )
    except Exception as e:
        print(f"        ERRO ao abrir Chrome: {e}")
        return 1

    for i in range(15):
        await asyncio.sleep(2)
        if await _checar_porta():
            print("        OK - Chrome debug no ar (9222) - faca login no SIAFE nessa janela")
            return 0
        if i == 7:
            print("        aguardando Chrome iniciar... (pode demorar ate 30s)")

    print("        AVISO: Chrome abriu mas a porta 9222 nao respondeu.")
    print("               -> O Hermes tentara abrir sozinho no proximo ciclo.")
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
