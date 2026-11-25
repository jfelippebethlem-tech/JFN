# -*- coding: utf-8 -*-
"""Estágios SINTÉTICOS do teste do ensaio O8.5 (tests/test_ensaio_o85.py) — importados pelo processo-filho do ensaio
(`tools.ensaio_o85 filho`, cfg `estagios_extra`) e registrados no REGISTRO do motor. Nada de produção usa isto.

  · `t_ler`  — lê UM documento pelo ponto real de leitura (`sei.acervo_texto.ler`) e grava um marcador; idempotente pela
              chave: com o marcador presente NÃO lê de novo (é o que a 2ª passada tem de provar). Emite `t_ler/pronto`.
              `payload.reler=True` apaga o marcador antes (a releitura injetada que o sensor tem de pegar).
  · `t_usar` — consome `t_ler/pronto` (a saída do anterior): grava o seu marcador com o sha do texto do anterior;
              `payload.falhar_efeito=True` declara um efeito que não houve (o efeito conferido tem de recusar).
"""
import hashlib
import json
from pathlib import Path

from compliance_agent.aplicacao.estagios import REGISTRO, Estagio
from compliance_agent.fluxo.fila import Resultado
from compliance_agent.sei import acervo_texto

VERSAO = "t-1"


def _ler(payload, ctx):
    pasta, doc = Path(payload["pasta"]), payload["doc"]
    marca = pasta / f"{doc}.lido"
    if payload.get("reler") and marca.exists():
        marca.unlink()
    if marca.exists():                                       # idempotente pela chave: nada é relido
        return Resultado(efeito={"doc": doc, "sha": marca.read_text(), "lido_agora": False}, eventos=[])
    texto = acervo_texto.ler(pasta, {"texto": f"{doc}.txt"})
    sha = hashlib.sha256(texto.encode()).hexdigest()
    marca.write_text(sha)
    return Resultado(efeito={"doc": doc, "sha": sha, "lido_agora": True},
                     eventos=[{"fonte": "t_ler", "tipo": "pronto", "chave": doc, "detalhe": {"sha": sha,
                                                                                             "pasta": str(pasta)}}])


def _ler_ok(payload, ctx, r):
    marca = Path(payload["pasta"]) / f"{payload['doc']}.lido"
    return marca.exists() and marca.read_text() == r.efeito.get("sha")


def _usar(payload, ctx):
    pasta, doc = Path(payload["pasta"]), payload["doc"]
    (pasta / f"{doc}.usado").write_text(json.dumps({"sha": payload["sha"]}))
    declarado = "x" * 64 if payload.get("falhar_efeito") else payload["sha"]
    return Resultado(efeito={"doc": doc, "sha": declarado}, eventos=[])


def _usar_ok(payload, ctx, r):
    f = Path(payload["pasta"]) / f"{payload['doc']}.usado"
    return f.exists() and json.loads(f.read_text())["sha"] == r.efeito.get("sha")


REGISTRO["t_ler"] = Estagio(handler=_ler, efeito=_ler_ok)
REGISTRO["t_usar"] = Estagio(handler=_usar, efeito=_usar_ok)
