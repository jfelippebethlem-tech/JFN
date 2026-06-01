"""
Agente de Compliance & Auditoria — CLI.

Uso:
    python compliance.py                    # modo interativo
    python compliance.py --query "..."      # consulta única
    python compliance.py --scheduler        # roda ciclo diário agora
    python compliance.py --scheduler --loop # fica em loop diário às 7h
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path


def _load_env():
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            if key.strip() and key.strip() not in os.environ:
                os.environ[key.strip()] = value.strip()


async def run(args):
    from compliance_agent.database.models import init_db
    from compliance_agent.agent import ComplianceAgent

    init_db()
    agent = ComplianceAgent()

    if args.query:
        response = await agent.chat(args.query)
        print(response)
    else:
        await agent.run_interactive()


async def run_scheduler(loop: bool):
    from compliance_agent.scheduler import rodar_ciclo_diario, loop_diario
    if loop:
        await loop_diario()
    else:
        await rodar_ciclo_diario()


def main():
    _load_env()

    parser = argparse.ArgumentParser(description="Agente de Compliance & Auditoria RJ")
    parser.add_argument("--query",     type=str,  help="Consulta única")
    parser.add_argument("--scheduler", action="store_true", help="Executa ciclo diário de coleta")
    parser.add_argument("--loop",      action="store_true", help="Mantém o scheduler em loop diário")
    args = parser.parse_args()

    if args.scheduler:
        asyncio.run(run_scheduler(args.loop))
    else:
        asyncio.run(run(args))


if __name__ == "__main__":
    main()
