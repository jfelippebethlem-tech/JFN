# -*- coding: utf-8 -*-
"""Roster de deputados federais do RJ (API Dados Abertos da Câmara, sem chave).

POR QUE 2 legislaturas: emendas 2019–2026 = legislaturas 56 e 57; ex-deputados
autores de emendas antigas precisam constar para o recorte AUTOR_RJ funcionar.
"""
from __future__ import annotations

import time
import unicodedata

import httpx

API = "https://dadosabertos.camara.leg.br/api/v2"
_TIMEOUT = 30
_TENTATIVAS = 4  # a API da Câmara devolve 504 esporádico; backoff resolve
# POR QUE UA de navegador: o CDN da Câmara devolve 504 "upstream request timeout"
# para o UA padrão python-httpx (curl passa). Mesma lição do SEI: UA obrigatório.
_HEADERS = {"accept": "application/json",
            "user-agent": "Mozilla/5.0 (X11; Linux aarch64) JFN-fiscalizacao/1.0"}


def _get_json(cli: httpx.Client, url: str) -> dict:
    for i in range(_TENTATIVAS):
        try:
            r = cli.get(url)
            if r.status_code >= 500:
                raise httpx.HTTPStatusError(f"HTTP {r.status_code}", request=r.request, response=r)
            r.raise_for_status()
            return r.json()
        except (httpx.HTTPStatusError, httpx.TransportError):
            if i == _TENTATIVAS - 1:
                raise
            time.sleep(5 * (i + 1))
    raise RuntimeError("unreachable")


def norm_nome(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return " ".join(s.upper().split())


def listar_deputados_rj(legislaturas: tuple[int, ...] = (56, 57)) -> dict:
    """{"verificado", "deputados", "motivo"} — INDISPONÍVEL ≠ 0."""
    deputados: dict[int, dict] = {}
    try:
        with httpx.Client(timeout=_TIMEOUT, headers=_HEADERS) as cli:
            for leg in legislaturas:
                url = f"{API}/deputados?siglaUf=RJ&idLegislatura={leg}&itens=100&ordem=ASC&ordenarPor=nome"
                while url:
                    j = _get_json(cli, url)
                    for d in j["dados"]:
                        d["idLegislatura"] = leg
                        prev = deputados.get(d["id"])
                        if prev:
                            prev["_legs"].add(leg)
                        else:
                            d["_legs"] = {leg}
                            deputados[d["id"]] = d
                    url = next((l["href"] for l in j.get("links", []) if l["rel"] == "next"), None)
    except (httpx.HTTPError, ValueError, KeyError) as e:
        return {"verificado": False, "deputados": [], "motivo": f"API Câmara: {e}"}
    return {"verificado": True, "deputados": list(deputados.values()), "motivo": None}


def gravar_roster(con, deputados: list[dict]) -> int:
    vistos: dict[int, dict] = {}
    for d in deputados:
        legs = sorted(d.get("_legs") or {d.get("idLegislatura")})
        if d["id"] in vistos:
            legs = sorted(set(vistos[d["id"]]["legs"]) | set(legs))
        vistos[d["id"]] = {"d": d, "legs": legs}
    for v in vistos.values():
        d = v["d"]
        con.execute(
            """INSERT INTO deputados_federais_rj (id_camara, nome, nome_norm, partido, legislaturas)
               VALUES (?,?,?,?,?)
               ON CONFLICT(id_camara) DO UPDATE SET nome=excluded.nome, nome_norm=excluded.nome_norm,
                 partido=excluded.partido, legislaturas=excluded.legislaturas""",
            (d["id"], d["nome"], norm_nome(d["nome"]), d.get("siglaPartido"),
             ",".join(map(str, v["legs"]))))
    con.commit()
    return len(vistos)
