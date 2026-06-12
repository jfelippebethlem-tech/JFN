# -*- coding: utf-8 -*-
"""
Benefícios sociais (laranja) + PEP (relação política) — API do Portal da Transparência / CGU.

Dois sinais de Due Diligence, por pessoa física:
  • **Benefício social de subsistência** por **CPF** (param `codigo`): PETI, Garantia-Safra, Seguro-Defeso.
    Sócio/favorecido que recebe benefício de subsistência E é dono/recebe de fornecedor do Estado é indício
    clássico de **laranja** (interposição de pessoas — art. 337-F CP; art. 11 Lei 8.429/92).
    > Bolsa Família por-CPF foi DESCONTINUADO (Novo Bolsa Família só por NIS; não temos NIS → INDISPONÍVEL).
  • **PEP** (Pessoa Exposta Politicamente) por **CPF** ou por **NOME**: endpoint `/peps`. Como o CPF do QSA
    público vem MASCARADO (LGPD), a busca por **nome do sócio** (desmascarado) é o caminho útil p/ fornecedor PJ
    → sinal de **relação política**. PEP estende-se a familiares até 2º grau ("PEP por relacionamento").

Auth: header `chave-api-dados: <PORTAL_TRANSPARENCIA_KEY>` (mesma chave do CEIS/CNEP, ver `collectors/ceis.py`).

HONESTIDADE (regra-mãe): se não dá p/ verificar (sem chave/rede/HTTP≠200), retorna `verificado=False` + motivo
(INDISPONÍVEL) — nunca "limpo" silencioso. INDISPONÍVEL ≠ 0. Indício, nunca acusação. CPF mascarado nos produtos.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path

import httpx

_BASE = "https://api.portaldatransparencia.gov.br/api-de-dados"
_TIMEOUT = 20
_CACHE_FILE = Path("data") / "beneficios_cache.json"
_CACHE_TTL = 7 * 86400  # 7 dias

# (endpoint, rótulo, nome_do_param) — aceitam CPF (11) ou NIS no param `codigo`. Endpoints VERIFICADOS ao
# vivo (HTTP 200 com CPF, 2026-06-12): Bolsa Família e BPC são os sinais FORTES de laranja (subsistência).
# Auxílio Brasil por-CPF = 403 (sem permissão na chave); "sacado"/Novo Bolsa Família = só por NIS (não temos).
_BENEFICIOS = [
    ("bolsa-familia-disponivel-por-cpf-ou-nis", "Bolsa Família", "codigo"),
    ("bpc-por-cpf-ou-nis", "BPC", "codigo"),
    ("auxilio-emergencial-por-cpf-ou-nis", "Auxílio Emergencial", "codigo"),
    ("peti-por-cpf-ou-nis", "PETI", "codigo"),
    ("safra-codigo-por-cpf-ou-nis", "Garantia-Safra", "codigo"),
    ("seguro-defeso-codigo", "Seguro-Defeso", "codigo"),
]

_cache: dict | None = None


def _chave() -> str:
    return (os.environ.get("PORTAL_TRANSPARENCIA_KEY", "")
            or os.environ.get("TRANSPARENCIA_API_KEY", "")).strip()


def _carrega_cache() -> dict:
    global _cache
    if _cache is None:
        try:
            _cache = json.loads(_CACHE_FILE.read_text("utf-8")) if _CACHE_FILE.exists() else {}
        except Exception:
            _cache = {}
    return _cache


def _salva_cache() -> None:
    try:
        _CACHE_FILE.parent.mkdir(exist_ok=True)
        _CACHE_FILE.write_text(json.dumps(_cache, ensure_ascii=False), "utf-8")
    except Exception:
        pass


def _so_digitos(s: str) -> str:
    return re.sub(r"\D", "", str(s or ""))


async def _get(client: httpx.AsyncClient, endpoint: str, params: dict, chave: str) -> tuple[bool, list, str]:
    """(ok, lista, motivo). ok=False → INDISPONÍVEL (não dá p/ afirmar nada)."""
    try:
        r = await client.get(f"{_BASE}/{endpoint}", params={**params, "pagina": 1},
                             headers={"chave-api-dados": chave, "Accept": "application/json"},
                             timeout=_TIMEOUT)
    except httpx.TimeoutException:
        return False, [], "timeout"
    except Exception as exc:  # noqa: BLE001
        return False, [], str(exc)[:80]
    if r.status_code == 200:
        data = r.json()
        if isinstance(data, list):
            return True, data, ""
        if isinstance(data, dict):
            return True, (data.get("data") or data.get("content") or []), ""
        return True, [], ""
    if r.status_code in (401, 403):
        return False, [], f"chave inválida/sem permissão (HTTP {r.status_code})"
    return False, [], f"HTTP {r.status_code}"


async def verificar_beneficios(cpf: str, forcar_update: bool = False) -> dict:
    """Benefícios de subsistência (PETI/Safra/Seguro-Defeso) de um CPF — sinal de laranja.

    Retorna (honesto): {cpf, verificado, recebe_beneficio: bool|None, beneficios:[{tipo,...}], motivo, fonte}.
    verificado=False → INDISPONÍVEL (sem chave/rede/CPF inválido); NUNCA tratar como "não recebe".
    """
    cpf = _so_digitos(cpf)
    base = {"cpf": cpf, "fonte": "Portal da Transparência/CGU (Bolsa Família, BPC, Aux. Emergencial, PETI, Safra, Seguro-Defeso)",
            "coletado_em": datetime.now().isoformat(timespec="seconds")}
    if len(cpf) != 11:
        return {**base, "verificado": False, "recebe_beneficio": None, "beneficios": [],
                "motivo": "requer CPF completo (11 dígitos); QSA público vem mascarado (LGPD)"}
    chave = _chave()
    if not chave:
        return {**base, "verificado": False, "recebe_beneficio": None, "beneficios": [],
                "motivo": "sem chave — defina PORTAL_TRANSPARENCIA_KEY"}

    cache = _carrega_cache()
    ck = f"benef:{cpf}"
    ent = cache.get(ck)
    if ent and not forcar_update and (time.time() - ent.get("_ts", 0)) < _CACHE_TTL:
        return {**base, **{k: v for k, v in ent.items() if k != "_ts"}, "_cache": True}

    achados: list[dict] = []
    erros: list[str] = []
    consultados = 0
    async with httpx.AsyncClient() as client:
        for endpoint, tipo, param in _BENEFICIOS:
            if consultados:
                await asyncio.sleep(0.3)  # respeita o rate-limit do Portal
            consultados += 1
            ok, lista, erro = await _get(client, endpoint, {param: cpf}, chave)
            if ok:
                for it in lista:
                    achados.append({"tipo": tipo, "_raw": it if isinstance(it, dict) else {}})
            else:
                erros.append(f"{tipo}: {erro}")

    if consultados and len(erros) == consultados:  # tudo falhou → não dá p/ afirmar
        return {**base, "verificado": False, "recebe_beneficio": None, "beneficios": [],
                "motivo": "; ".join(erros)}
    resultado = {"verificado": True, "recebe_beneficio": len(achados) > 0, "beneficios": achados,
                 "motivo": ("parcial: " + "; ".join(erros)) if erros else ""}
    cache[ck] = {**resultado, "_ts": time.time()}
    _salva_cache()
    return {**base, **resultado, "_cache": False}


async def verificar_pep(cpf: str = "", nome: str = "", forcar_update: bool = False) -> dict:
    """PEP (Pessoa Exposta Politicamente) por CPF ou por NOME — sinal de relação política.

    Para fornecedor PJ, busque por NOME do sócio (o QSA público traz nome desmascarado). Retorna (honesto):
    {chave_busca, verificado, eh_pep: bool|None, peps:[{nome,funcao,orgao,...}], motivo, fonte}.
    """
    cpf = _so_digitos(cpf)
    chave_busca = cpf or (nome or "").strip()
    base = {"chave_busca": chave_busca, "fonte": "Portal da Transparência/CGU (PEP)",
            "coletado_em": datetime.now().isoformat(timespec="seconds")}
    if not chave_busca or (cpf and len(cpf) != 11) or (not cpf and len((nome or "").strip()) < 6):
        return {**base, "verificado": False, "eh_pep": None, "peps": [],
                "motivo": "requer CPF completo (11) ou nome com ≥6 caracteres"}
    chave = _chave()
    if not chave:
        return {**base, "verificado": False, "eh_pep": None, "peps": [],
                "motivo": "sem chave — defina PORTAL_TRANSPARENCIA_KEY"}

    cache = _carrega_cache()
    ck = f"pep:{cpf or nome.strip().lower()}"
    ent = cache.get(ck)
    if ent and not forcar_update and (time.time() - ent.get("_ts", 0)) < _CACHE_TTL:
        return {**base, **{k: v for k, v in ent.items() if k != "_ts"}, "_cache": True}

    params = {"cpf": cpf} if cpf else {"nome": nome.strip()}
    async with httpx.AsyncClient() as client:
        ok, lista, erro = await _get(client, "peps", params, chave)
    if not ok:
        return {**base, "verificado": False, "eh_pep": None, "peps": [], "motivo": erro}

    peps = [{"nome": _campo(it, "nome", "nomePep"), "funcao": _campo(it, "descricaoFuncao", "funcao"),
             "orgao": _campo(it, "nomeOrgao", "orgaoLotacao", "siglaFuncao"),
             "inicio": _campo(it, "dataInicioExercicio"), "fim": _campo(it, "dataFimExercicio")}
            for it in lista if isinstance(it, dict)]
    # busca por nome pode trazer homônimos — sinal a CONFIRMAR (não acusação)
    resultado = {"verificado": True, "eh_pep": len(peps) > 0, "peps": peps,
                 "motivo": "match por nome — confirmar identidade (possíveis homônimos)" if (nome and peps) else ""}
    cache[ck] = {**resultado, "_ts": time.time()}
    _salva_cache()
    return {**base, **resultado, "_cache": False}


def _campo(d: dict, *chaves: str) -> str:
    for k in chaves:
        v = d.get(k)
        if isinstance(v, dict):
            v = v.get("nome") or v.get("descricao") or ""
        if v:
            return str(v)
    return ""


async def investigar_pessoa(cpf: str = "", nome: str = "") -> dict:
    """Roda benefícios (se CPF completo) + PEP (CPF ou nome) p/ uma pessoa. Usado pelo motor de DD."""
    benef = await verificar_beneficios(cpf) if _so_digitos(cpf) else {
        "verificado": False, "recebe_beneficio": None, "motivo": "sem CPF completo"}
    pep = await verificar_pep(cpf=cpf, nome=nome)
    return {"cpf": _so_digitos(cpf), "nome": nome, "beneficios": benef, "pep": pep}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Benefícios sociais (laranja) + PEP (relação política) por pessoa")
    ap.add_argument("--cpf", default="")
    ap.add_argument("--nome", default="")
    a = ap.parse_args()
    print(json.dumps(asyncio.run(investigar_pessoa(a.cpf, a.nome)), ensure_ascii=False, indent=2))
