# -*- coding: utf-8 -*-
"""E.3.2 municipal — vencedor × perdedoras com sócio em comum, sobre os certames do TCE-RJ.

O CAMINHO QUE FOI PRECISO ABRIR. O E.3.2 existia e devolvia zero, e a causa nunca foi o motor: eram
**114 certames** com classificado além do 1º lugar em todo o acervo (0,66% de 17.242). A cadeia que
mudou isso, medida em cada degrau:

    coleta TCE-RJ (nunca havia rodado) ......... 15.436 certames · 82.941 perdedores nominados
    resolução nome → CNPJ (catálogo nacional) ..  60,3% dos 21.141 nomes  (era 13,9% no catálogo local)
    certames com vencedor E perdedora resolvidos  5.220
    desses, com QSA nos dois lados .............  4.074   ← o universo real do cruzamento
    pares com sócio em comum ...................     42, em 31 certames (0,76%)

Taxa de 0,76% é o que se espera de um sinal que discrimina — não é o laranja que marcava 55% da base.

TRÊS RESSALVAS QUE VIAJAM COM O ACHADO, e sem elas ele engana:

  · **Pregão multi-item.** Num certame de 45 participantes a MESMA empresa aparece como vencedora de
    um item e perdedora de outro. "Vencedor × perdedora no certame" não significa que disputaram o
    MESMO item — e é a disputa pelo mesmo item que caracteriza concorrência fictícia. A fonte do
    TCE-RJ não traz item; o veredito daqui é `indicio_a_confirmar_no_item`, nunca fechado.
  · **CPF mascarado.** O sócio é casado por nome + os seis dígitos centrais que a Receita publica.
    A colisão medida dessa combinação é de ~4%: em 42 pares, espera-se um ou dois homônimos.
  · **Sócio comum entre concorrentes NÃO é ilícito por si.** Holding com duas operações, sócio
    investidor e empresa familiar com dois CNPJs são lícitos. O que o achado pede é a diligência que
    separa isso de proposta de cobertura — nunca a imputação.
"""
from __future__ import annotations

import sqlite3
from collections import defaultdict
from typing import Any

from compliance_agent.osint.vinculos import TIPOS_ARESTA

__all__ = ["cruzar_certames", "cobertura_cruzamento", "RESSALVAS"]

RESSALVAS = (
    "Pregão multi-item: a mesma empresa aparece como vencedora de um item e perdedora de outro, e a "
    "fonte do TCE-RJ não publica o item. O achado é de CERTAME, não de item — e é a disputa pelo "
    "mesmo item que caracteriza concorrência fictícia.",
    "O sócio é casado por nome mais os seis dígitos centrais que a Receita publica; a colisão medida "
    "dessa combinação nesta base é de ~4%.",
    "Sócio em comum entre concorrentes não é ilícito: holding com duas operações, sócio investidor e "
    "empresa familiar com dois CNPJs são lícitos. O achado pede diligência, nunca imputação.",
)


def _normalizar(nome: str) -> str:
    from tools.resolver_nome_cnpj import normalizar
    return normalizar(nome)


def _mapa_resolvido(con: sqlite3.Connection) -> dict[str, str]:
    try:
        return {n: c for n, c in con.execute(
            "SELECT nome_norm, cnpj_basico FROM nome_cnpj_resolvido "
            "WHERE cnpj_basico IS NOT NULL")}
    except sqlite3.OperationalError:
        return {}


def _qsa_por_raiz(con: sqlite3.Connection) -> dict[str, set[str]]:
    """`{raiz: {chave_do_socio}}`. A chave é nome + documento mascarado — ver ressalva de colisão."""
    qsa: dict[str, set[str]] = defaultdict(set)
    try:
        linhas = con.execute(
            "SELECT cnpj_basico, nome_socio, doc_socio FROM socios_receita WHERE ident='2'")
    except sqlite3.OperationalError:
        return qsa
    for raiz, nome, doc in linhas:
        qsa[raiz].add(f"{(nome or '').strip().upper()}|{(doc or '').strip()}")
    return qsa


def _participantes_por_certame(con: sqlite3.Connection,
                               resolvido: dict[str, str]) -> dict[str, dict[str, set[str]]]:
    cert: dict[str, dict[str, set[str]]] = {}
    try:
        linhas = con.execute(
            "SELECT ente, ano, processo, participante, resultado FROM tcerj_licitante")
    except sqlite3.OperationalError:
        return cert
    for ente, ano, proc, part, resultado in linhas:
        raiz = resolvido.get(_normalizar(part or ""))
        if not raiz:
            continue
        chave = f"{ente}|{ano}|{proc}"
        lado = "vencedores" if (resultado or "").upper().startswith("VENCEDOR") else "perdedoras"
        cert.setdefault(chave, {"vencedores": set(), "perdedoras": set()})[lado].add(raiz)
    return cert


def cruzar_certames(con: sqlite3.Connection, *, limite: int = 0) -> dict[str, Any]:
    """Vencedor × perdedora com sócio em comum, sobre todos os certames municipais resolvidos.

    Devolve os achados **e** os denominadores de cada degrau — sem eles, 42 achados poderiam ser
    lidos como "o acervo é limpo" ou como "há epidemia", e não são nenhum dos dois.
    """
    resolvido = _mapa_resolvido(con)
    if not resolvido:
        return {"ok": False, "motivo": "nenhum nome resolvido — rode tools/resolver_nome_cnpj",
                "achados": []}
    qsa = _qsa_por_raiz(con)
    certames = _participantes_por_certame(con, resolvido)

    com_disputa = cruzaveis = 0
    achados: list[dict] = []
    for chave, lados in certames.items():
        venc, perd = lados["vencedores"], lados["perdedoras"]
        if not venc or not perd:
            continue
        com_disputa += 1
        v_qsa = [r for r in venc if r in qsa]
        p_qsa = [r for r in perd if r in qsa]
        if not v_qsa or not p_qsa:
            continue
        cruzaveis += 1
        for vr in v_qsa:
            for pr in p_qsa:
                if vr == pr:
                    continue          # multi-item: a mesma empresa nos dois lados não é par
                comum = qsa[vr] & qsa[pr]
                if not comum:
                    continue
                achados.append({
                    "certame": chave,
                    "vencedor_raiz": vr,
                    "perdedora_raiz": pr,
                    "socios_em_comum": [s.split("|")[0] for s in sorted(comum)],
                    "n_socios_em_comum": len(comum),
                    "forca_aresta": TIPOS_ARESTA["mesmo_socio_doc_parcial"].forca,
                    "tipo_aresta": "mesmo_socio_doc_parcial",
                    "veredito": "indicio_a_confirmar_no_item",
                    "explicacao_inocente": TIPOS_ARESTA["mesmo_socio_doc_parcial"].exculpatoria,
                })
                if limite and len(achados) >= limite:
                    break
    n_cert_achado = len({a["certame"] for a in achados})
    return {
        "ok": True,
        "achados": achados,
        "n_pares": len(achados),
        "n_certames_com_achado": n_cert_achado,
        "cobertura": {
            "certames_na_base": len(certames),
            "com_vencedor_e_perdedora_resolvidos": com_disputa,
            "cruzaveis_com_qsa_dos_dois_lados": cruzaveis,
            "taxa_de_achado_pct": round(100.0 * n_cert_achado / cruzaveis, 2) if cruzaveis else 0.0,
            "nota": ("Certame fora de `cruzaveis` não é certame limpo: ou o nome do licitante não "
                     "resolveu para CNPJ, ou o CNPJ não tem QSA na base. INDISPONÍVEL, não ausência "
                     "de vínculo."),
        },
        "ressalvas": list(RESSALVAS),
    }


def cobertura_cruzamento(con: sqlite3.Connection) -> dict[str, Any]:
    """Só os denominadores, sem rodar o cruzamento — para o painel e o handoff."""
    resolvido = _mapa_resolvido(con)
    qsa = _qsa_por_raiz(con)
    certames = _participantes_por_certame(con, resolvido)
    com_disputa = [k for k, v in certames.items() if v["vencedores"] and v["perdedoras"]]
    cruzaveis = [k for k in com_disputa
                 if any(r in qsa for r in certames[k]["vencedores"])
                 and any(r in qsa for r in certames[k]["perdedoras"])]
    return {
        "nomes_resolvidos": len(resolvido),
        "certames_com_participante_resolvido": len(certames),
        "com_vencedor_e_perdedora": len(com_disputa),
        "cruzaveis": len(cruzaveis),
        "antes": "114 certames com classificado além do 1º lugar em todo o acervo (0,66%)",
    }
