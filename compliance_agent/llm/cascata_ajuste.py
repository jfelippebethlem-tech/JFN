# -*- coding: utf-8 -*-
"""cascata_ajuste — o arquivo que REBAIXA (por tarefa) ou TIRA (de todas) um modelo da cascata grátis/fraca.

Pedido do dono (22/11/2026): "faça a automelhoria atuar também nos modelos grátis e mais fracos que o Opus".
Quem escreve aqui é o loop da automelhoria (`tools/automelhoria_modelos.py`), sempre com o MOTIVO e o NÚMERO medido;
quem lê é a cascata (`direcionamento_cerebro`, `comotor`, `pericia_integral`). É dado, não código: desfazer é apagar a
entrada (`python -m compliance_agent.llm.cascata_ajuste desfazer <tarefa|*> <modelo>`), sem deploy.

Dois remédios, os dois reversíveis e nenhum deles PROMOVE ninguém (promoção exige bancada medida e o dono):
  · `rebaixados[tarefa][modelo]` — o modelo divergiu GRAVE do Opus acima do Sonnet naquela tarefa: vai para o FIM do
    seu degrau na cadeia daquela tarefa (continua lá se os outros falharem — "nunca ficar sem produzir");
  · `fora[modelo]` — o modelo deu 404 e não respondeu mais (sumiu do catálogo): sai das cadeias de todas as tarefas.

Chaves de modelo = o rótulo de proveniência que a casa já grava: `gemini:<id>`, `openrouter:<id>` (perícia integral),
ou o provedor puro da cascata padrão (`groq`, `openrouter`, `nvidia`…).

Sob pytest sem `JFN_CASCATA_AJUSTE` não se lê nem se grava o arquivo real (teste nenhum muda a cadeia de produção).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from compliance_agent.llm import arquivo_estado as arq


def caminho() -> Path:
    return Path(os.environ.get("JFN_CASCATA_AJUSTE") or (arq.dados() / "cascata_ajuste.json"))


def _inerte() -> bool:
    return arq.sob_pytest() and not os.environ.get("JFN_CASCATA_AJUSTE")


def ler() -> dict:
    if _inerte():
        return {}
    return arq.ler_json(caminho())


def _sem_free(m: str) -> str:
    return m[:-5] if m.endswith(":free") else m


def rebaixados(tarefa: str | None) -> set[str]:
    """Modelos rebaixados NA tarefa (a base: `pericia_integral:juridico` conta como `pericia_integral`)."""
    if not tarefa:
        return set()
    base = tarefa.split(":", 1)[0]
    return {_sem_free(m) for m in (ler().get("rebaixados") or {}).get(base, {})}


def fora() -> set[str]:
    return {_sem_free(m) for m in (ler().get("fora") or {})}


def ordenar(itens: list, tarefa: str | None = None, chave=lambda x: x) -> list:
    """Tira os `fora` e manda os rebaixados da tarefa para o fim (ordem estável). `chave(item)` dá o rótulo."""
    f, r = fora(), rebaixados(tarefa)
    if not f and not r:
        return list(itens)
    vivos = [x for x in itens if _sem_free(chave(x)) not in f]
    return sorted(vivos, key=lambda x: _sem_free(chave(x)) in r)


def _registrar(d: dict, evento: dict) -> None:
    d.setdefault("historico", []).append(evento)
    d["historico"] = d["historico"][-200:]


def rebaixar(tarefa: str, modelo: str, motivo: str, numeros: dict, *, agora: datetime | None = None) -> bool:
    """Grava o rebaixamento (idempotente). Devolve True só quando é novo."""
    if _inerte():
        return False
    em = (agora or datetime.now()).isoformat(timespec="seconds")
    base = tarefa.split(":", 1)[0]

    def fn(d):
        reb = d.setdefault("rebaixados", {}).setdefault(base, {})
        if modelo in reb:
            return False
        reb[modelo] = {"motivo": motivo, "numeros": numeros, "em": em}
        _registrar(d, {"acao": "rebaixar", "tarefa": base, "modelo": modelo, "motivo": motivo, "em": em})
        return True
    return arq.mutar_json(caminho(), fn, espera=30)


def tirar(modelo: str, motivo: str, numeros: dict, *, agora: datetime | None = None) -> bool:
    if _inerte():
        return False
    em = (agora or datetime.now()).isoformat(timespec="seconds")

    def fn(d):
        fo = d.setdefault("fora", {})
        if modelo in fo:
            return False
        fo[modelo] = {"motivo": motivo, "numeros": numeros, "em": em}
        _registrar(d, {"acao": "tirar", "modelo": modelo, "motivo": motivo, "em": em})
        return True
    return arq.mutar_json(caminho(), fn, espera=30)


def desfazer(tarefa: str, modelo: str) -> bool:
    """`tarefa='*'` devolve o modelo tirado (`fora`); senão desfaz o rebaixamento naquela tarefa."""
    if _inerte():
        return False
    em = datetime.now().isoformat(timespec="seconds")

    def fn(d):
        alvo = d.get("fora", {}) if tarefa == "*" else d.get("rebaixados", {}).get(tarefa.split(":", 1)[0], {})
        if alvo.pop(modelo, None) is None:
            return False
        _registrar(d, {"acao": "desfazer", "tarefa": tarefa, "modelo": modelo, "em": em})
        return True
    return arq.mutar_json(caminho(), fn, espera=30)


def _main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("ver")
    d = sub.add_parser("desfazer")
    d.add_argument("tarefa")
    d.add_argument("modelo")
    a = ap.parse_args(argv)
    if a.cmd == "desfazer":
        print("desfeito" if desfazer(a.tarefa, a.modelo) else "nada a desfazer")
        return 0
    print(json.dumps({k: v for k, v in ler().items() if k != "historico"}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(_main())
