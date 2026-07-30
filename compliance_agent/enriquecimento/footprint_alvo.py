# -*- coding: utf-8 -*-
"""Caller do SpiderFoot — resolve CNPJ → domínio próprio e mede o footprint digital.

POR QUE O SPIDERFOOT ESTAVA PARADO. A ponte (`spiderfoot_bridge`) estava implementada, testada, com
o binário instalado, e **sem um único caller** — porque ela recebe domínio/e-mail/IP e a casa não
tinha o campo. Passou a ter com o item I.1.2: `data/receita_estab.db` traz `correio_eletronico` em
69,0% dos 6,17 milhões de estabelecimentos.

A MEDIÇÃO QUE DESENHOU ESTE MÓDULO, sobre os **4.258.994 e-mails do dump inteiro** — e vale registrar
que a primeira medição, por `LIMIT 400000`, deu 83,2%, e a de `LIMIT 100000` deu 59,8%: `LIMIT` sem
ordenação pega uma fatia contígua por rowid, que é enviesada por faixa de CNPJ. O número da contagem
completa é outro:

    provedor LIVRE .... 87,3%  (3.720.153)   ·   domínio PRÓPRIO ... 12,7%  (538.841)
    top: gmail.com ~54% · hotmail.com ~16% · yahoo.com.br ~5% · outlook/bol/uol/ig ~4%

Duas consequências, e as duas são recusas:

  · **E-mail de provedor livre não é domínio da empresa.** Escanear `gmail.com` mediria o footprint
    do Google. O domínio só entra quando é próprio.
  · **Não ter domínio próprio NÃO é sinal de fachada.** Atinge 87,3% do país — é a norma da micro e
    pequena empresa brasileira. Um score que tratasse ausência de domínio como "footprint vazio =
    máximo suspeito" acusaria SETE em cada oito empresas, que é o defeito do laranja em 55% da base
    repetido em escala maior. Sem domínio próprio o resultado é **INDISPONÍVEL**, com `score=None` —
    nunca 1.0.

O guarda de custo de `spiderfoot_bridge.elegivel` continua valendo: cada scan são minutos e dezenas
de requisições externas, e só alvo com `radar_risco >= 50` justifica. Nunca em sweep de massa.
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any

from compliance_agent.enriquecimento.spiderfoot_bridge import (
    elegivel,
    footprint,
    score_footprint,
)

__all__ = ["PROVEDORES_LIVRES", "dominio_proprio_do_cnpj", "avaliar_footprint", "cobertura_dominio"]

_ESTAB = Path(__file__).resolve().parent.parent.parent / "data" / "receita_estab.db"
_RE_DIG = re.compile(r"\D")

# Provedores de e-mail livre: 87,3% do dump (3.720.153 de 4.258.994). Escanear qualquer um destes
# mediria o footprint do provedor, não o da empresa.
PROVEDORES_LIVRES = frozenset({
    "gmail.com", "hotmail.com", "hotmail.com.br", "yahoo.com", "yahoo.com.br", "outlook.com",
    "outlook.com.br", "bol.com.br", "uol.com.br", "terra.com.br", "ig.com.br", "live.com",
    "icloud.com", "msn.com", "globo.com", "r7.com", "oi.com.br", "globomail.com", "zipmail.com.br",
    "aol.com", "protonmail.com", "me.com", "gmail.com.br",
})


def _dominio(email: Any) -> str:
    e = str(email or "").strip().lower()
    return e.rsplit("@", 1)[-1] if "@" in e else ""


def dominio_proprio_do_cnpj(cnpj: str, *, db_estab: str = "") -> dict[str, Any]:
    """Domínio PRÓPRIO da empresa, ou o motivo de não haver.

    Devolve `{dominio, email, motivo}`. `dominio` vazio nunca significa "empresa sem presença": ou o
    e-mail é de provedor livre (87,3% do país), ou a Receita não publicou o campo (31%).
    """
    caminho = db_estab or str(_ESTAB)
    d = _RE_DIG.sub("", str(cnpj or ""))
    if len(d) != 14:
        return {"dominio": "", "email": "", "motivo": "CNPJ inválido"}
    if not Path(caminho).exists():
        return {"dominio": "", "email": "", "motivo": f"base de estabelecimentos ausente ({caminho})"}

    con = sqlite3.connect(f"file:{caminho}?mode=ro", uri=True)
    try:
        r = con.execute(
            "SELECT correio_eletronico FROM estabelecimentos WHERE cnpj=?", (d,)).fetchone()
    finally:
        con.close()
    if not r:
        return {"dominio": "", "email": "",
                "motivo": "CNPJ sem registro no dump de estabelecimentos — lacuna de captura"}
    email = (r[0] or "").strip().lower()
    if not email or "@" not in email:
        return {"dominio": "", "email": "",
                "motivo": ("a Receita não publicou e-mail para este CNPJ (o campo falta em 31% dos "
                           "estabelecimentos) — INDISPONÍVEL, não ausência de presença digital")}
    dom = _dominio(email)
    if dom in PROVEDORES_LIVRES:
        return {"dominio": "", "email": email,
                "motivo": (f"e-mail de provedor livre ({dom}) — 87,3% do país usa provedor livre, e "
                           "escanear o provedor mediria o footprint dele, não o da empresa. Não ter "
                           "domínio próprio é a NORMA da micro e pequena empresa, não indício")}
    return {"dominio": dom, "email": email, "motivo": ""}


def avaliar_footprint(cnpj: str, *, radar_score: float | None = None,
                      db_estab: str = "", timeout_s: int = 300) -> dict[str, Any]:
    """Footprint digital do CNPJ, com os dois guardas — elegibilidade e domínio próprio.

    `score` é `None` sempre que não se pôde medir. Um footprint vazio de verdade (domínio existe e o
    scan não achou nada) vale 1.0; a ausência de domínio **não** vale 1.0, e essa distinção é o que
    separa este módulo de um acusador de sete em cada oito empresas.
    """
    base: dict[str, Any] = {"cnpj": cnpj, "score": None, "footprint": None,
                            "estado": "INDISPONIVEL"}

    if not elegivel(radar_score):
        return {**base, "motivo": (
            f"alvo não elegível (radar_score={radar_score}): o scan leva minutos e faz dezenas de "
            "requisições externas, e só alvo de risco alto o justifica. Nunca em sweep de massa.")}

    res = dominio_proprio_do_cnpj(cnpj, db_estab=db_estab)
    if not res["dominio"]:
        return {**base, "email": res.get("email", ""), "motivo": res["motivo"]}

    f = footprint(res["dominio"], timeout_s=timeout_s)
    if f is None:
        return {**base, "dominio": res["dominio"],
                "motivo": ("SpiderFoot indisponível, com timeout ou saída malformada — "
                           "INDISPONÍVEL, e INDISPONÍVEL não é footprint vazio")}
    s = score_footprint(f)
    return {
        "cnpj": cnpj, "dominio": res["dominio"], "email": res["email"],
        "estado": "MEDIDO", "score": s, "footprint": f,
        "leitura": _leitura(s, f),
        "ressalva": ("Footprint digital é INDÍCIO de existência operacional, nunca prova de fachada. "
                     "Empresa real de setor tradicional pode ter presença mínima; e presença rica "
                     "pode ser comprada. O sinal serve para ordenar a fila, não para concluir."),
    }


def _leitura(score: float | None, f: dict) -> str:
    if score is None:
        return "não medido"
    n = int(f.get("n_achados", 0) or 0)
    if score >= 0.9:
        return (f"Domínio existe e o rastro é quase nulo ({n} achado(s)): indício de estrutura de "
                "papel, a confrontar com a verificação de sede e o porte declarado.")
    if score >= 0.5:
        return f"Rastro digital escasso ({n} achado(s)) — abaixo do esperado para operação ativa."
    return f"Rastro digital consistente ({n} achado(s)): a empresa existe on-line."


def cobertura_dominio(db_estab: str = "") -> dict[str, Any]:
    """Quanto do dump tem domínio PRÓPRIO — o denominador que impede ler 'sem domínio' como achado.

    CONTA, não amostra. A versão por `LIMIT` deu 83,2% em 400 mil e 59,8% em 100 mil, contra 87,3%
    na contagem completa: `LIMIT` sem ordenação pega uma fatia contígua por rowid, enviesada por
    faixa de CNPJ. Denominador errado é pior que denominador ausente.
    """
    caminho = db_estab or str(_ESTAB)
    if not Path(caminho).exists():
        return {"ok": False, "erro": f"base ausente ({caminho})"}
    ph = ",".join("?" * len(PROVEDORES_LIVRES))
    con = sqlite3.connect(f"file:{caminho}?mode=ro", uri=True)
    try:
        n = con.execute(
            "SELECT COUNT(*) FROM estabelecimentos WHERE correio_eletronico LIKE '%@%'"
        ).fetchone()[0] or 1
        livres = con.execute(
            f"SELECT COUNT(*) FROM estabelecimentos WHERE correio_eletronico LIKE '%@%' "
            f"AND lower(substr(correio_eletronico, instr(correio_eletronico,'@')+1)) IN ({ph})",
            tuple(PROVEDORES_LIVRES)).fetchone()[0]
    finally:
        con.close()
    return {
        "ok": True, "e_mails_no_dump": n,
        "provedor_livre": livres, "pct_livre": round(100.0 * livres / n, 1),
        "dominio_proprio": n - livres, "pct_proprio": round(100.0 * (n - livres) / n, 1),
        "nota": ("Não ter domínio próprio é a NORMA — 87,3% do dump inteiro. Tratar isso como "
                 "footprint vazio acusaria sete em cada oito empresas. Atenção: `LIMIT` sem "
                 "ordenação pega fatia contígua por rowid e enviesa — a contagem completa deu 87,3%, "
                 "e amostras de 400 mil e 100 mil deram 83,2% e 59,8%."),
    }
