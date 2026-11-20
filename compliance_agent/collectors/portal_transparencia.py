# -*- coding: utf-8 -*-
"""Cliente da API de dados do Portal da Transparência (CGU) — UMA leitura para sanções e benefícios.

`ceis._consultar` e `beneficios_sociais._get` eram a mesma função copiada, e carregavam o mesmo defeito:
HTTP 200 com corpo que não é a lista (página de bloqueio, JSON de erro) virava "consultado, nada
encontrado" — empresa "não sancionada", CPF "não recebe benefício" — e ia para o cache de 7 dias.
"""
from __future__ import annotations

import os

import httpx

BASE = "https://api.portaldatransparencia.gov.br/api-de-dados"
TIMEOUT = 20


def chave() -> str:
    return (os.environ.get("PORTAL_TRANSPARENCIA_KEY", "")
            or os.environ.get("TRANSPARENCIA_API_KEY", "")).strip()


async def consultar(client: httpx.AsyncClient, endpoint: str, params: dict, chave_api: str) -> tuple[bool, list, str]:
    """(ok, lista, motivo). ok=False → INDISPONÍVEL (não dá para afirmar nada). Só a 1ª página."""
    try:
        r = await client.get(f"{BASE}/{endpoint}", params={**params, "pagina": 1},
                             headers={"chave-api-dados": chave_api, "Accept": "application/json"},
                             timeout=TIMEOUT)
    except httpx.TimeoutException:
        return False, [], "timeout"
    except Exception as exc:  # noqa: BLE001 — qualquer falha de transporte é INDISPONÍVEL, nunca "vazio"
        return False, [], str(exc)[:80]
    if r.status_code == 200:
        try:
            data = r.json()
        except ValueError:
            return False, [], "HTTP 200 sem JSON (página de bloqueio?)"
        if isinstance(data, list):
            return True, data, ""
        if isinstance(data, dict) and ("data" in data or "content" in data):
            return True, (data.get("data") or data.get("content") or []), ""
        return False, [], f"HTTP 200 fora do formato esperado: {str(data)[:60]}"
    if r.status_code in (401, 403):
        return False, [], f"chave inválida/sem permissão (HTTP {r.status_code})"
    if r.status_code == 400:  # expõe o motivo (a API explica o que falta: competência, CPF válido, etc.)
        try:
            msg = str((r.json() or {}).get("Erro na API") or "")[:90]
        except Exception:  # noqa: BLE001
            msg = ""
        return False, [], f"HTTP 400{(': ' + msg) if msg else ''}"
    return False, [], f"HTTP {r.status_code}"
