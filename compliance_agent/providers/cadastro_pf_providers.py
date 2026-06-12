# -*- coding: utf-8 -*-
"""Provider de CONSULTA CADASTRAL PF (nome→CPF) via bureau LEGÍTIMO/PAGO (BigDataCorp, Serpro Datavalid,
Assertiva, Serasa/Experian, Boa Vista…). É LÍCITO (LGPD: legítimo interesse/cumprimento de função pública;
dever de fiscalização do Deputado) — NÃO é base de vazamento. Genérico e key-driven: o dono configura a URL
e a chave do bureau que tiver; o parser tenta formatos JSON comuns.

Honesto: o candidato devolvido SÓ vira CPF resolvido depois de `resolucao_cpf.confirmar_cpf` (bate o middle6
da máscara pública do QSA = anti-homônimo). Sem URL/chave → INDISPONÍVEL (nunca fabrica).

Config (env / .env):
  CADASTRO_PF_API_URL   ex.: https://api.bigdatacorp.com.br/.../pessoas   (use {nome} se for GET com query)
  CADASTRO_PF_API_KEY   chave do bureau
  CADASTRO_PF_METHOD    GET|POST (default GET)
  CADASTRO_PF_AUTH_HEADER  nome do header de auth (default 'Authorization'); valor = a chave
  CADASTRO_PF_BODY_NOME nome do campo do body p/ o nome (POST; default 'nome')
"""
from __future__ import annotations

import os
import re

import httpx

_CPF = re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b")


def _digitos(s) -> str:
    return re.sub(r"\D", "", str(s or ""))


def _extrair_pares(obj, _prof=0) -> list[dict]:
    """Varre o JSON do bureau e coleta pares {nome, cpf} de formatos comuns (resultados[], data[], etc.)."""
    out: list[dict] = []
    if _prof > 6 or obj is None:
        return out
    if isinstance(obj, dict):
        # heurística: dict com cpf + algum nome
        cpf = obj.get("cpf") or obj.get("CPF") or obj.get("numeroCpf") or obj.get("nrCpf")
        nome = (obj.get("nome") or obj.get("Nome") or obj.get("nomeCompleto") or obj.get("name") or "")
        if cpf and len(_digitos(cpf)) == 11:
            out.append({"nome": str(nome), "cpf": _digitos(cpf)})
        for v in obj.values():
            out += _extrair_pares(v, _prof + 1)
    elif isinstance(obj, list):
        for v in obj:
            out += _extrair_pares(v, _prof + 1)
    return out


def consultar_cpf_por_nome(nome: str, *, timeout: int = 20) -> dict:
    """Consulta o bureau cadastral por NOME e devolve candidatos {nome, cpf}. INDISPONÍVEL sem config.
    Retorna {ok, candidatos:[{nome,cpf}], fonte, motivo}. NÃO confirma identidade — use confirmar_cpf depois."""
    nome = (nome or "").strip()
    base = {"ok": False, "candidatos": [], "fonte": "bureau cadastral PF (serviço legítimo/pago)"}
    if len(nome) < 6:
        return {**base, "motivo": "nome curto"}
    url = (os.environ.get("CADASTRO_PF_API_URL") or "").strip()
    key = (os.environ.get("CADASTRO_PF_API_KEY") or "").strip()
    if not url or not key:
        return {**base, "motivo": "INDISPONÍVEL: configure CADASTRO_PF_API_URL + CADASTRO_PF_API_KEY "
                                  "(bureau legítimo: BigDataCorp/Serpro/Assertiva/Serasa). Nada foi fabricado."}
    metodo = (os.environ.get("CADASTRO_PF_METHOD") or "GET").upper()
    hdr_name = os.environ.get("CADASTRO_PF_AUTH_HEADER") or "Authorization"
    headers = {hdr_name: key, "Accept": "application/json"}
    try:
        if metodo == "POST":
            campo = os.environ.get("CADASTRO_PF_BODY_NOME") or "nome"
            r = httpx.post(url, json={campo: nome}, headers=headers, timeout=timeout)
        elif "{nome}" in url:
            r = httpx.get(url.replace("{nome}", nome), headers=headers, timeout=timeout)
        else:
            r = httpx.get(url, params={"nome": nome}, headers=headers, timeout=timeout)
    except Exception as e:  # noqa: BLE001
        return {**base, "motivo": f"erro no bureau: {str(e)[:80]}"}
    if r.status_code != 200:
        return {**base, "motivo": f"bureau HTTP {r.status_code}"}
    try:
        cand = _extrair_pares(r.json())
    except Exception:  # noqa: BLE001
        # fallback: regex de CPF no texto cru (sem nome associado)
        cand = [{"nome": "", "cpf": _digitos(m)} for m in _CPF.findall(r.text)]
    # dedup por cpf
    vis, dedup = set(), []
    for c in cand:
        if c["cpf"] not in vis and len(c["cpf"]) == 11:
            vis.add(c["cpf"]); dedup.append(c)
    return {**base, "ok": True, "candidatos": dedup,
            "motivo": "" if dedup else "sem candidato retornado pelo bureau"}
