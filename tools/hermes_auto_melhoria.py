#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Entry-point do loop de AUTO-MELHORIA do Hermes (meta-cognição).
Wrapper de compliance_agent.llm.auto_melhoria. Uso: hermes_auto_melhoria.py {seed|run}.
- seed: semeia as auto-correções fundacionais (categoria `metodo`).
- run : semeia + roda a crítica metacognitiva (confronta outputs do Hermes com veredittos)."""
import sys, json, asyncio
sys.path.insert(0, "/home/ubuntu/JFN")
from compliance_agent.llm.auto_melhoria import seed_metodos, auto_melhorar

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "seed":
        print(f"{seed_metodos()} métodos fundacionais semeados.")
    else:
        seed_metodos()
        print(json.dumps(asyncio.run(auto_melhorar()), ensure_ascii=False, indent=1))
