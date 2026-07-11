#!/usr/bin/env python3
"""Gera skills do Yoda a partir de capabilities.yaml (roteador por progressive disclosure).

Problema (auditoria 2026-06-18): o Yoda só "enxerga" ~12 das 57 capacidades porque só
12 viram skill em ~/.hermes/skills/yoda-commands/. As demais (anomalias avançadas,
grafo_poder, conflito_doador_contrato, família Massare, etc.) ficam invisíveis e o modelo
tem de adivinhar a rota/curl — fonte clássica de erro de tool-use.

Este gerador emite UMA skill por capacidade PRONTA que ainda não tem skill (ADITIVO: nunca
sobrescreve as skills curadas à mão). Assim o Yoda passa a ver todas as funções no próximo
reload do gateway, com quando_usar + como chamar (rota HTTP / comando CLI). Re-rodar quando
capabilities.yaml mudar. NÃO toca comportamento live (só gera arquivos).

Uso:  python tools/gen_skills.py [--force] [--all]
  --force : regera mesmo as que já existem (cuidado: sobrescreve curadas)
  --all   : inclui capacidades com status != PRONTO (marcadas como experimental)
"""
import os
import sys
import re
import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
CAPS = os.path.join(HERE, "..", "capabilities.yaml")
SKILLS = os.path.expanduser("~/.hermes/skills/yoda-commands")
FORCE = "--force" in sys.argv
ALL = "--all" in sys.argv


def slug(s):
    return re.sub(r"[^a-z0-9_-]", "", str(s or "").lower().replace(" ", "-"))[:48]


def yaml_str(s):
    return '"' + str(s or "").replace('"', "'").replace("\n", " ").strip()[:240] + '"'


def como_chamar(c):
    tipo = c.get("tipo", "http")
    if tipo == "http":
        metodo = c.get("metodo", "GET").upper()
        rota = c.get("rota", "")
        return f"Chamar a API do JFN (mesma VM):\n```\n{metodo} http://127.0.0.1:8000{rota}\n```"
    cmd = c.get("comando") or c.get("rota") or c.get("id")
    return f"Comando: `{cmd}`"


def gerar(c):
    cid = slug(c.get("id"))
    if not cid:
        return None
    d = os.path.join(SKILLS, cid)
    skill_path = os.path.join(d, "SKILL.md")
    if os.path.exists(skill_path) and not FORCE:
        return ("skip", cid)
    status = (c.get("status") or "").upper()
    if status and status != "PRONTO" and not ALL:
        return ("pula-nao-pronto", cid)
    os.makedirs(d, exist_ok=True)
    desc = c.get("descricao") or c.get("quando_usar") or cid
    dominio = slug(c.get("dominio"))
    agente = slug(c.get("agente"))
    tags = [t for t in ["yoda", agente, dominio, cid] if t]
    exp = "" if status == "PRONTO" else "\n> ⚠️ **Experimental** (status: %s) — pode não estar 100%%." % (status or "?")
    corpo = f"""---
name: {cid}
description: {yaml_str(desc)}
version: 1.0.0
author: gen_skills (capabilities.yaml)
platforms: [linux]
metadata:
  hermes:
    tags: {tags}
    category: yoda-commands
    gerado_de: capabilities.yaml
---

# {cid} — {desc}{exp}

**Quando usar:** {c.get('quando_usar') or desc}

**Domínio:** {c.get('dominio') or '—'} · **Agente:** {c.get('agente') or '—'}

**Como acionar:**
{como_chamar(c)}

{('**Args:** ' + str(c.get('args'))) if c.get('args') else ''}
{('**Retorno:** ' + str(c.get('retorno'))) if c.get('retorno') else ''}

> Honestidade: indício ≠ acusação · INDISPONÍVEL ≠ 0 · empenho ≠ pago (OB = pagamento).
"""
    open(skill_path, "w", encoding="utf-8").write(corpo)
    return ("criado", cid)


def main():
    d = yaml.safe_load(open(CAPS, encoding="utf-8"))
    caps = d.get("capacidades") or d.get("capabilities") or []
    os.makedirs(SKILLS, exist_ok=True)
    criados, skip, naopronto = [], [], []
    for c in caps:
        r = gerar(c)
        if not r:
            continue
        {"criado": criados, "skip": skip, "pula-nao-pronto": naopronto}[r[0]].append(r[1])
    print(f"capacidades: {len(caps)}")
    print(f"  ✓ skills criadas: {len(criados)}  {criados[:8]}{'…' if len(criados) > 8 else ''}")
    print(f"  • já existiam (preservadas): {len(skip)}")
    print(f"  • puladas (não-PRONTO; use --all): {len(naopronto)}  {naopronto}")
    total_skills = len([x for x in os.listdir(SKILLS) if os.path.isdir(os.path.join(SKILLS, x))])
    print(f"  → total de skills agora em yoda-commands: {total_skills}")


if __name__ == "__main__":
    main()
