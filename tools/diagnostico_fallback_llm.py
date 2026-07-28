#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Diagnóstico do fallback de IA — degrau por degrau, no ambiente em que o cron roda.

    .venv/bin/python tools/diagnostico_fallback_llm.py [--json] [--cron]

POR QUE ESTA FERRAMENTA EXISTE. A camada 2 da fiscalização 24/7 degrada para string vazia
quando a cadeia grátis não responde, e o detector então marca `nao_avaliavel`. Isso é a
degradação HONESTA — mas é silenciosa: um `.env` que não carregou no cron produz exatamente
o mesmo resultado que uma cadeia saudável avaliando um caso sem dado. Sem esta ferramenta,
"o 24/7 está rodando" e "o 24/7 nunca chamou uma IA" são indistinguíveis de fora.

O QUE ELE MEDE, que `best_free_chat` sozinho não mostra: `best_free_chat` devolve na PRIMEIRA
resposta. Se o primeiro provedor está vivo, ela devolve `OK` mesmo que os outros seis estejam
todos mortos — e aí não existe fallback nenhum, existe um provedor só. Aqui cada degrau é
chamado isoladamente, e o veredito é quantos aguentam peso.

`--cron` reexecuta o próprio script sob `env -i` com o ambiente empobrecido do cron (sem as
variáveis da sessão interativa), carregando o `.env` como o `sweep_fiscalizacao_247.sh` carrega.
É a única forma de provar que funciona LÁ, e não só aqui.

Custo: 7 chamadas curtas na cadeia declaradamente grátis. Nenhuma chave paga é exercitada —
a lista abaixo é a mesma que `best_free_chat` percorre.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

_PERGUNTA = "Responda somente com a palavra OK."
_SISTEMA = "Você responde em uma única palavra."
# Mínimo de degraus vivos para a cadeia merecer o nome de fallback: um provedor não é cadeia.
MIN_SAUDAVEL = 2


def _provas():
    """(nome, disponivel_fn, chamar_fn) para cada degrau — na ordem real da cadeia."""
    from compliance_agent.llm import free_llm as F
    from compliance_agent.llm import local as L

    def _c(fn):
        return lambda: fn(_PERGUNTA, system=_SISTEMA)

    return [
        ("ollama", L.is_available, lambda: L.chat(_PERGUNTA, system=_SISTEMA)),
        ("cerebras", F.cerebras_available, _c(F.cerebras_chat)),
        ("gemini", F.gemini_available, _c(F.gemini_chat)),
        ("groq", F.groq_available, _c(F.groq_chat)),
        ("openrouter", F.openrouter_available, _c(F.openrouter_chat)),
        ("cloudflare", F.cloudflare_available, _c(F.cloudflare_chat)),
        ("github_models", F.github_models_available, _c(F.github_models_chat)),
    ]


def diagnosticar() -> dict:
    from compliance_agent.llm import free_llm as F

    resultado = {"ordem": list(F._get_provider_order()), "degraus": []}
    for nome, disponivel, chamar in _provas():
        item = {"provedor": nome, "estado": "?", "ms": None, "detalhe": ""}
        try:
            if not disponivel():
                item["estado"] = "sem_credencial"
                item["detalhe"] = "chave ausente no ambiente ou serviço local fora do ar"
                resultado["degraus"].append(item)
                continue
        except Exception as e:  # noqa: BLE001 — checagem de disponibilidade não pode derrubar
            item["estado"] = "erro_disponibilidade"
            item["detalhe"] = f"{type(e).__name__}: {e}"[:120]
            resultado["degraus"].append(item)
            continue

        t0 = time.monotonic()
        try:
            resp = (chamar() or "").strip()
            item["ms"] = int((time.monotonic() - t0) * 1000)
            item["estado"] = "ok" if resp else "vazio"
            item["detalhe"] = resp[:60]
        except Exception as e:  # noqa: BLE001 — o ponto do teste é justamente colher a falha
            item["ms"] = int((time.monotonic() - t0) * 1000)
            item["estado"] = "falha"
            item["detalhe"] = f"{type(e).__name__}: {e}"[:120]
        resultado["degraus"].append(item)

    vivos = [d["provedor"] for d in resultado["degraus"] if d["estado"] == "ok"]
    resultado["vivos"] = vivos
    resultado["n_vivos"] = len(vivos)
    resultado["saudavel"] = len(vivos) >= MIN_SAUDAVEL
    return resultado


def _rodar_como_cron() -> int:
    """Reexecuta este script com o ambiente empobrecido do cron.

    Replica o que `tools/sweep_fiscalizacao_247.sh` faz: bash (não dash), `cd`, `set -a; . ./.env`.
    A armadilha conhecida da casa é o inverso disto — `. .env` sob dash mata a linha inteira e o
    log nunca existe. Aqui se prova que o caminho usado de fato carrega as chaves.
    """
    raiz = pathlib.Path(__file__).resolve().parent.parent
    script = (f'cd {raiz} && [ -f .env ] && {{ set -a; . ./.env; set +a; }}; '
              f'export PYTHONPATH=.; .venv/bin/python tools/diagnostico_fallback_llm.py')
    print("→ reexecutando sob ambiente de cron (env -i, bash, .env via 'set -a')\n")
    return subprocess.call(
        ["env", "-i", "HOME=/home/ubuntu", "PATH=/usr/bin:/bin", "USER=ubuntu",
         "bash", "-lc", script])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--cron", action="store_true",
                    help="reexecuta sob o ambiente empobrecido do cron (env -i)")
    a = ap.parse_args()

    if a.cron:
        return _rodar_como_cron()

    r = diagnosticar()
    if a.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
        return 0 if r["saudavel"] else 1

    print(f"ordem da cadeia: {' → '.join(r['ordem'])}\n")
    rotulo = {"ok": "✅ responde", "vazio": "⚠️  respondeu vazio", "falha": "❌ falhou",
              "sem_credencial": "·  sem credencial", "erro_disponibilidade": "❌ erro"}
    for d in r["degraus"]:
        ms = f"{d['ms']:>6} ms" if d["ms"] is not None else "        "
        print(f"  {d['provedor']:<14} {rotulo.get(d['estado'], d['estado']):<20} {ms}  "
              f"{d['detalhe']}")

    print(f"\ndegraus vivos: {r['n_vivos']} ({', '.join(r['vivos']) or 'nenhum'})")
    if not r["saudavel"]:
        print(f"\n⚠️  ABAIXO DO MÍNIMO ({MIN_SAUDAVEL}). Com menos de dois degraus não há cadeia — "
              "há um provedor único, e a camada 2 do 24/7 fica a uma queda de virar "
              "'nao_avaliavel' em tudo, silenciosamente.")
    else:
        print("cadeia saudável: a queda de um provedor não desliga a camada 2.")
    if os.environ.get("JFN_TRIAGEM_PAUSE") or pathlib.Path("data/.pause_llm_triagem").exists():
        print("\nnota: data/.pause_llm_triagem existe — a camada 2 está PAUSADA de propósito.")
    return 0 if r["saudavel"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
