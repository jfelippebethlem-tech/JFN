"""
SIAFE2 / SEI Finance Agent — Entry point.

Credenciais padrão carregadas do arquivo .env (SIAFE_USER, SIAFE_PASS).
Podem ser sobrescritas via flags na linha de comando.

Uso:
    python main.py                         # Interativo com credenciais do .env
    python main.py --visible               # Browser visível (para acompanhar)
    python main.py --user CPF --pass SENHA # Sobrescreve credenciais
    python main.py --query "..."           # Consulta única, não-interativo
    python main.py --cliente NOME          # Define campo Cliente do login
    python main.py --exercicio 2025        # Define campo Exercício do login
"""

import argparse
import asyncio
import os
from pathlib import Path

from rich.console import Console

console = Console()


def _load_env():
    """Load .env file from project root if it exists."""
    env_path = Path(__file__).parent / ".env"
    if not env_path.exists():
        return
    try:
        from dotenv import load_dotenv
        load_dotenv(dotenv_path=env_path, override=False)
    except ImportError:
        for line in env_path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            if key and key not in os.environ:
                os.environ[key] = value


def parse_args():
    parser = argparse.ArgumentParser(
        description="Agente SIAFE2/SEI Rio de Janeiro",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--visible",
        action="store_true",
        help="Abre browser visível (não headless). Recomendado para uso normal.",
    )
    parser.add_argument(
        "--user",
        type=str,
        default=None,
        help="CPF/login SIAFE2. Sobrescreve SIAFE_USER do .env.",
    )
    parser.add_argument(
        "--pass",
        dest="password",
        type=str,
        default=None,
        help="Senha SIAFE2. Sobrescreve SIAFE_PASS do .env.",
    )
    parser.add_argument(
        "--cliente",
        type=str,
        default=None,
        help="Campo 'Cliente' no login (organização). Sobrescreve SIAFE_CLIENTE do .env.",
    )
    parser.add_argument(
        "--exercicio",
        type=str,
        default=None,
        help="Campo 'Exercício' no login (ano fiscal, ex: 2025). Sobrescreve SIAFE_EXERCICIO.",
    )
    parser.add_argument(
        "--query",
        type=str,
        help="Executa uma consulta única e sai (modo não-interativo).",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="output",
        help="Diretório de saída para arquivos exportados (padrão: output/).",
    )
    return parser.parse_args()


async def run(args):
    from siafe_agent.agent import SIAFEAgent

    # Resolve credentials: CLI flag > .env > prompt
    username = args.user or os.environ.get("SIAFE_USER") or ""
    password = args.password or os.environ.get("SIAFE_PASS") or ""
    cliente = args.cliente or os.environ.get("SIAFE_CLIENTE") or None
    exercicio = args.exercicio or os.environ.get("SIAFE_EXERCICIO") or None

    if not username:
        username = input("SIAFE2 Usuário (CPF): ").strip()
    if not password:
        import getpass
        password = getpass.getpass("SIAFE2 Senha: ")

    agent = SIAFEAgent(
        headless=not args.visible,
        output_dir=args.output_dir,
        default_username=username,
        default_password=password,
        default_cliente=cliente,
        default_exercicio=exercicio,
    )

    if args.query:
        await agent.start()
        try:
            response = await agent.chat(args.query)
            console.print(response)
        finally:
            await agent.stop()
    else:
        await agent.run_interactive()


def main():
    _load_env()
    args = parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
