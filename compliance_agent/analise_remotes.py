#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""analise_remotes — STORAGE DURÁVEL e VERSIONADO das análises de processos SEI (R2→B2).

Diretriz do dono (2026-07-24): "as análises dos processos precisam ficar guardadas porque esses processos
SEI são alterados e podem surgir novos documentos". Um veredito de hoje pode não valer amanhã — então cada
análise vira um SNAPSHOT IMUTÁVEL, versionado pelo HASH do conteúdo capturado (árvore/manifesto do processo):

  • objeto  = `anexos/analises/<numero_sei>/<versao_hash>.json`  (sob o prefixo do anexos_remotes)
  • mesma captura (mesmo hash) → MESMA versão (idempotente, não re-sobe)
  • captura mudou (doc novo/alterado) → hash NOVO → NOVA versão; o histórico anterior FICA (imutável)
  • ponteiro canônico = `remote:bucket/objeto` (como todo anexo), guardável numa coluna do dono

**Reusa** integralmente a política provada de `anexos_remotes` (R2 primário → transbordo B2, degrada honesto
p/ None se o rclone falha). NÃO duplica regra de transbordo nem credencial. As primitivas de upload/existência
são injetáveis (teste sem rede).
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile

from compliance_agent import anexos_remotes as _ar

CATEGORIA = "analises"


def hash_versao(conteudo_capturado) -> str:
    """Assinatura ESTÁVEL (sha1[:16]) da versão do processo, a partir do conteúdo capturado (texto da árvore
    OU manifesto dict). É o que muda quando surge/altera um documento — a chave da versão do snapshot.
    dict é serializado com chaves ordenadas (determinístico)."""
    if isinstance(conteudo_capturado, str):
        s = conteudo_capturado
    else:
        s = json.dumps(conteudo_capturado, sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:16]


def objeto_analise(numero_sei: str, versao_hash: str) -> str:
    """Caminho do objeto (sem `remote:bucket`): 'anexos/analises/<numero_sei>/<versao_hash>.json'."""
    n = _ar._safe(numero_sei)
    v = _ar._safe(versao_hash)
    return f"{_ar.PREFIXO}/{CATEGORIA}/{n}/{v}.json"


def mudou(versao_atual: str, versoes_conhecidas) -> bool:
    """True se a versão atual (hash da captura de agora) NÃO está entre as já guardadas — i.e., o processo
    mudou (documento novo/alterado) e merece nova análise + novo snapshot. Honesto: só compara hashes."""
    return versao_atual not in set(versoes_conhecidas or ())


def guardar_analise(numero_sei: str, veredito: dict, *, versao_hash: str, criado_em: str,
                    loc_conhecida: str | None = None, subir=None, existe=None) -> str | None:
    """Guarda um SNAPSHOT imutável da análise no storage (R2→B2) e devolve o ponteiro canônico
    `remote:bucket/objeto`. IDEMPOTENTE: se a versão já está no remote (`loc_conhecida` existe), NÃO
    re-sobe — devolve o ponteiro conhecido. `subir`/`existe` injetáveis (default = anexos_remotes; teste sem
    rede). Degrada HONESTO: None se o upload falha (o chamador loga e segue; nunca inventa ponteiro)."""
    subir = subir or _ar.subir_anexo
    existe = existe or _ar.existe_anexo
    # idempotência: versão já persistida → não re-sobe
    if loc_conhecida and existe(loc_conhecida):
        return loc_conhecida
    objeto = objeto_analise(numero_sei, versao_hash)
    pacote = {"numero_sei": numero_sei, "versao_hash": versao_hash, "criado_em": criado_em,
              "veredito": veredito}
    tmp = None
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(pacote, f, ensure_ascii=False)
            tmp = f.name
        return subir(tmp, objeto)
    except Exception:  # noqa: BLE001 — falha de I/O/serialização: degrada honesto
        return None
    finally:
        if tmp and os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass


def ler_analise(loc: str, *, ler=None) -> dict | None:
    """Lê um snapshot de análise do ponteiro canônico (`remote:bucket/objeto`). None se incompleto/erro.
    `ler` injetável (default = anexos_remotes.ler_anexo)."""
    ler = ler or _ar.ler_anexo
    raw = ler(loc)
    if not raw:
        return None
    try:
        return json.loads(raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else raw)
    except (json.JSONDecodeError, ValueError, UnicodeDecodeError):
        return None
