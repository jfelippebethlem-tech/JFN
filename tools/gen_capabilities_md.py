# -*- coding: utf-8 -*-
"""
gen_capabilities_md — gera a SEÇÃO DE CAPACIDADES (markdown) a partir do capabilities.yaml (JFN 2.0, Onda 1).

Saídas (derivadas — NÃO editar à mão; rodar no pre-commit p/ não divergir):
  - docs/CAPACIDADES.md            : tabela legível das capacidades (p/ o PLAYBOOK referenciar).
  - data/yoda_capabilities_prompt.txt : trecho enxuto p/ injetar no system prompt do Yoda (só PRONTO,
    formato "id(args) — quando_usar"), garantindo que o roteador conheça exatamente o registro.

Uso: cd ~/JFN && PYTHONPATH=. .venv/bin/python -m tools.gen_capabilities_md
"""
from __future__ import annotations

from pathlib import Path

import yaml

_REPO = Path(__file__).resolve().parent.parent
_YAML = _REPO / "capabilities.yaml"
_MD = _REPO / "docs" / "CAPACIDADES.md"
_PROMPT = _REPO / "data" / "yoda_capabilities_prompt.txt"


def gerar() -> dict:
    doc = yaml.safe_load(_YAML.read_text(encoding="utf-8"))
    caps = doc.get("capacidades", [])
    meta = doc.get("meta", {})

    # 1) tabela markdown
    linhas = ["# CAPACIDADES (gerado de capabilities.yaml — NÃO editar à mão)", "",
              f"Versão {meta.get('versao')} · base HTTP `{meta.get('base_http')}` · "
              f"CLI `{meta.get('cli_prefixo')}`", "",
              "| id | agente | tipo | rota/comando | status | quando usar |", "|---|---|---|---|---|---|"]
    for c in sorted(caps, key=lambda x: (x.get("dominio", ""), x.get("id", ""))):
        alvo = c.get("rota") or c.get("comando") or ""
        linhas.append(f"| `{c['id']}` | {c.get('agente','')} | {c.get('tipo','')} | `{alvo}` | "
                      f"{c.get('status','')} | {c.get('quando_usar','')} |")
    linhas += ["", "> Regra do roteador: o Yoda só chama `id` com status **PRONTO**. Fora do registro = erro "
               "explícito ('não tenho ferramenta para isso'), nunca invenção."]
    _MD.write_text("\n".join(linhas) + "\n", encoding="utf-8")

    # 2) snippet enxuto p/ system prompt (só PRONTO)
    plinhas = ["FERRAMENTAS DISPONÍVEIS (chame SÓ estas pelo id; se não houver ferramenta para o pedido, "
               "diga honestamente que não tem).",
               "COMO CHAMAR: base HTTP = http://127.0.0.1:8000 — use EXATAMENTE o método e a rota entre "
               "[colchetes]. GET → curl -s 'http://127.0.0.1:8000<rota>?param=valor'. POST → "
               "curl -s -X POST 'http://127.0.0.1:8000<rota>' -H 'Content-Type: application/json' -d '{\"param\":\"valor\"}'. "
               "NUNCA use POST numa rota marcada [GET ...] (dá 405).",
               ""]
    for c in caps:
        if c.get("status") != "PRONTO":
            continue
        args = ",".join((c.get("args") or {}).keys())
        if c.get("tipo") == "http" and c.get("rota"):
            chamada = f"[{c.get('metodo', 'GET')} {c['rota']}]"
        elif c.get("comando"):
            chamada = f"[cli: {c['comando']}]"
        else:
            chamada = ""
        plinhas.append(f"- {c['id']}({args}) {chamada} — {c.get('quando_usar', '')}")
    _PROMPT.write_text("\n".join(plinhas) + "\n", encoding="utf-8")

    return {"md": str(_MD), "prompt": str(_PROMPT),
            "prontas": sum(1 for c in caps if c.get("status") == "PRONTO"), "total": len(caps)}


if __name__ == "__main__":
    r = gerar()
    print(f"✅ gen_capabilities_md: {r['prontas']}/{r['total']} PRONTO → {r['md']} + {r['prompt']}")
