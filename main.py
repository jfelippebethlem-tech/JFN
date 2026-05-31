"""
SIAFE2 / SEI Finance Agent — Entry point.

Usage:
    python main.py
    python main.py --visible          # Run with visible browser (non-headless)
    python main.py --query "..."      # Single query, non-interactive
    python main.py --export csv       # After extraction, auto-export as CSV
"""

import argparse
import asyncio
import getpass
import os
import sys

from rich.console import Console
from rich.prompt import Prompt

console = Console()


def parse_args():
    parser = argparse.ArgumentParser(
        description="Agente SIAFE2/SEI Rio de Janeiro",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--visible",
        action="store_true",
        help="Abre browser visível (não headless). Útil para depuração.",
    )
    parser.add_argument(
        "--query",
        type=str,
        help="Executa uma consulta única e sai.",
    )
    parser.add_argument(
        "--export",
        type=str,
        choices=["csv", "json", "both"],
        help="Exporta dados automaticamente após extração.",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="output",
        help="Diretório de saída para arquivos exportados (padrão: output/).",
    )
    parser.add_argument(
        "--api-key",
        type=str,
        default=None,
        help="Chave da API Anthropic (ou use ANTHROPIC_API_KEY env var).",
    )
    return parser.parse_args()


async def run(args):
    from siafe_agent.agent import SIAFEAgent

    api_key = args.api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        console.print("[bold red]Erro:[/bold red] ANTHROPIC_API_KEY não definida.")
        console.print("  Defina com: export ANTHROPIC_API_KEY=sk-ant-...")
        sys.exit(1)

    agent = SIAFEAgent(
        api_key=api_key,
        headless=not args.visible,
        output_dir=args.output_dir,
    )

    if args.query:
        # Single-shot mode
        await agent.start()
        try:
            response = await agent.chat(args.query)
            console.print(response)
        finally:
            await agent.stop()
    else:
        # Interactive mode
        await agent.run_interactive()


def main():
    args = parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
