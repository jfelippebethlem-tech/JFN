"""Auto-atualização zero-downtime do Mestre Yoda.

Fluxo por modo de execução:

Docker (produção recomendada):
  O código foi copiado para dentro da imagem em build time, por isso o
  /atualizar mostra o que chegou de novo via git, mas instrui o operador
  a reconstruir a imagem do lado do host. Zero-downtime: o container atual
  continua ativo durante o `docker compose build`; a troca leva < 5 s.

Bare-Python (Windows/Linux sem Docker):
  Faz git pull + pip install no processo ativo. Pede reinício manual.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)

_Send = Callable[[str], Awaitable[None]]


def _inside_docker() -> bool:
    """True quando o processo roda dentro de um container Docker."""
    return os.path.exists("/.dockerenv")


async def _run(cmd: str) -> tuple[bool, str]:
    proc = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    stdout, _ = await proc.communicate()
    return proc.returncode == 0, stdout.decode(errors="replace").strip()


async def run_update(send: _Send, *, repo_path: str = ".") -> None:
    """Verifica e aplica atualizações do GitHub."""
    await send("🔄 Verificando atualizações no GitHub...")

    ok, out = await _run(f'git -C "{repo_path}" fetch --quiet origin')
    if not ok:
        await send(
            f"❌ git fetch falhou:\n```\n{out[:500]}\n```\n"
            "Verifique conexão com o GitHub."
        )
        return

    # Mostra quantos commits novos há sem ainda fazer pull.
    _, behind = await _run(
        f'git -C "{repo_path}" log HEAD..origin/HEAD --oneline'
    )
    if not behind.strip():
        await send("✅ Já estou na versão mais recente. Nada a fazer.")
        return

    total = len(behind.strip().splitlines())
    await send(f"📦 {total} commit(s) novo(s):\n```\n{behind[:400]}\n```")

    if _inside_docker():
        await _update_docker_mode(send, repo_path)
    else:
        await _update_bare(send, repo_path)


async def _update_docker_mode(send: _Send, repo_path: str) -> None:
    """Instrui o operador a reconstruir a imagem do lado do host."""
    await send(
        "🐳 Bot está em container Docker.\n\n"
        "Para aplicar a atualização *sem derrubar o bot agora*, rode no host:\n"
        "```\n"
        f"cd {repo_path}\n"
        "docker compose build yoda\n"
        "docker compose up -d --no-deps yoda\n"
        "```\n"
        "O container atual fica ativo durante o build. A troca leva < 5 s.\n"
        "Após a troca, o bot enviará 'Despertei' automaticamente. 🎉"
    )


async def _update_bare(send: _Send, repo_path: str) -> None:
    """Modo bare-Python: git pull + pip install."""
    await send("⬇️ Aplicando git pull...")
    ok, out = await _run(f'git -C "{repo_path}" pull --ff-only')
    if not ok:
        await send(f"❌ git pull falhou:\n```\n{out[:500]}\n```")
        return

    await send("🐍 Atualizando dependências Python...")
    ok, out = await _run(
        f'"{sys.executable}" -m pip install -q -r "{repo_path}/requirements.txt"'
    )
    if not ok:
        await send(f"⚠️ pip com avisos:\n```\n{out[:400]}\n```")

    await send(
        "✅ Código e dependências atualizados.\n\n"
        "⚠️ Para aplicar, reinicie o bot:\n"
        "```\nscripts\\hermes-start.cmd\n```\n"
        "O bot atual fica ativo até reiniciar."
    )
