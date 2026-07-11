#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Entry-point do loop de AUTO-MELHORIA do Hermes (meta-cognição).
Wrapper de compliance_agent.llm.auto_melhoria. Uso: hermes_auto_melhoria.py {seed|run}.
- seed: semeia as auto-correções fundacionais (categoria `metodo`).
- run : semeia + roda a crítica metacognitiva (confronta outputs do Hermes com veredittos)."""
import sys
import json
import asyncio
from pathlib import Path
sys.path.insert(0, "/home/ubuntu/JFN")
from compliance_agent.llm.auto_melhoria import seed_metodos, auto_melhorar


def _episodio_pericia() -> str:
    """Monta o episódio da perícia ITERJ×MGS recém-concluída (nota do caso + cadeia SEI/reajustes)."""
    partes = []
    for p in ["/home/ubuntu/vault/casos/iterj-mgs-clean-pagamentos.md",
              "/home/ubuntu/vault/notas/iterj-mgs-processos-sei.md"]:
        f = Path(p)
        if f.exists():
            partes.append(f"### {f.stem}\n" + f.read_text(encoding="utf-8", errors="ignore"))
    return "\n\n".join(partes)


if __name__ == "__main__":
    args = sys.argv[1:]
    cmd = args[0] if args else "run"
    if cmd == "seed":
        print(f"{seed_metodos()} métodos fundacionais semeados.")
    else:
        seed_metodos()
        ep = _episodio_pericia() if ("--pericia" in args or "pericia" in args) else ""
        if ep:
            print(f"[episódio: perícia ITERJ×MGS — {len(ep)} chars]", flush=True)
        print(json.dumps(asyncio.run(auto_melhorar(episodio=ep)), ensure_ascii=False, indent=1))
