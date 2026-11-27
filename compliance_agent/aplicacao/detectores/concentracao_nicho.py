# -*- coding: utf-8 -*-
"""E10 · `e10.c_concentracao_nicho` — um fornecedor domina um NICHO de objeto na mesma unidade e exercício (SOMBRA ⚖️).

Porta a regra única #14 do mapa O1.2, que só existia em `tools/_triagem_bombeiros.py` (FUNESBOM) e somia com ele
(auditoria de 27/11/2026): vencedor com mais de 60% do valor contratado de um nicho de objeto, com o nicho acima de
R$ 5.000.000,00; monopólio legítimo (concessionária, Correios, imprensa oficial) não é sinal. Generalizada para
QUALQUER unidade do espelho TCE-RJ (nada por órgão, decisão 4 do dono), por exercício.

Diferenças declaradas em relação ao script (régua mais conservadora, nunca mais frouxa):
  · grupo = unidade × exercício × nicho (o script juntava 2024 em diante de uma unidade só);
  · o nicho precisa de ao menos 3 contratos — com 1 ou 2 a "dominância" é aritmética, não concentração;
  · monopólio legítimo AFASTA o disparo (o script só limitava a pontuação a 8: priorizar ≠ indiciar);
  · nicho "OUTROS" (objeto sem palavra-chave) nunca dispara.

Valor = valor CONTRATADO do espelho (o que se mede é a fatia da contratação), deduplicado pela chave canônica
(`troca_gestao.contratos_espelho`); contrato cancelado fora. Pago (OB) não entra aqui.
Elegibilidade (invariante 3): só conta o contrato com veredito 'E' na exigência `fornecedor` da E9 (`contrato_tcerj`).
Concentração é LEGAL: o indício é a dominância medida num mercado com mais de um contrato, nunca o fornecedor em si.
"""
from __future__ import annotations

import re
import sqlite3
from collections import Counter, defaultdict
from decimal import Decimal

from compliance_agent.aplicacao.detectores import Carga, Disparo, elegivel
from compliance_agent.aplicacao.detectores.troca_gestao import contratos_espelho
from compliance_agent.cpf_cnpj import digitos as dig
from compliance_agent.dominio.achado import Fato, Papel
from compliance_agent.reporting.intel_base import reais

ID = "e10.c_concentracao_nicho"
UNIDADE = "contrato_tcerj"
VERSAO = "e10-cnicho-1"
FATIA_MIN = 0.60                 # do script: meu / total do nicho > 60%
NICHO_MIN = 5 * 10**6             # do script: total do nicho > R$ 5 mi (régua de concentração, NÃO teto de dispensa)
CONTRATOS_MIN = 3                # régua nova (conservadora): abaixo disso a dominância é aritmética
# palavras-chave do script (ordem importa: a primeira que casa define o nicho)
NICHOS = ("VIATURA", "AMBUL", "APROXIMA", "COMBUST", "UNIFORME", "FARDAMENT", "ALIMENT", "LIMPEZA", "VIGIL",
          "MANUTEN", "LOCACAO", "MEDICAMENT", "HOSPITAL", "OXIGEN", "PNEU", "SEGURO", "HELICOPT", "CAPACETE",
          "MASCARA", "EPI", "COMUNICA", "SOFTWARE", "TECNOLOG", "RADIO")
OUTROS = "OUTROS"
# do script: monopólio/utilidade — inexigibilidade e alto valor são ESPERADOS
MONOPOLIO_LEGITIMO = ("CORREIO", "TELEGRAFO", "ECT", "LIGHT", "AMPLA", "ENEL", "CEG", "CEDAE", "AGUAS", "AGUA DE",
                      "ENERGISA", "HELICOPTEROS DO BRASIL", "PETROBRAS", "IMPRENSA OFICIAL")
RESSALVA = ("Concentração não é ilegal: mercado restrito, único habilitado e contrato guarda-chuva são hipóteses "
            "inocentes a afastar no processo.")


def nicho(objeto: str | None) -> str:
    o = (objeto or "").upper()
    return next((k for k in NICHOS if k in o), OUTROS)


def monopolio_legitimo(fornecedor: str | None) -> bool:
    f = (fornecedor or "").upper()
    return any(re.search(rf"\b{re.escape(k)}", f) for k in MONOPOLIO_LEGITIMO)


def _grupo(unidade, exercicio, nch) -> str:
    return f"{unidade or '?'}|{exercicio}|{nch}"


def _itens(linhas) -> list[dict]:
    out = []
    for proc, num, _sei, val, uni, dc, obj, st, cnpj, forn in linhas:
        if str(st or "").strip() == "Cancelado":
            continue
        ex = str(dc or "")[:4]
        if not ex.isdigit():
            continue
        n = nicho(obj)
        out.append({"chave_e9": f"{proc}|{num}", "processo": proc, "unidade": uni, "exercicio": int(ex),
                    "nicho": n, "grupo": _grupo(uni, int(ex), n), "valor": float(val or 0), "objeto": obj,
                    "cnpj": dig(cnpj), "base": dig(cnpj)[:8], "fornecedor": forn})
    return out


def carregar(con: sqlite3.Connection, exercicio: int | None = None) -> Carga:
    linhas, dedup = contratos_espelho(con)
    itens = [c for c in _itens(linhas) if exercicio is None or c["exercicio"] == exercicio]
    return Carga(itens=itens, contexto={"dedup_espelho": dedup})


def grupo_de(d: Disparo) -> str:
    return d.grupo


def carregar_grupo(con: sqlite3.Connection, grupo: str, exercicio: int | None = None) -> Carga:
    linhas, _ = contratos_espelho(con)
    return Carga(itens=[c for c in _itens(linhas) if c["grupo"] == grupo])


def _avaliar(ms: list[dict]) -> dict | None:
    """Mede o grupo (já só elegíveis). None se não há o que medir."""
    tot = sum(c["valor"] for c in ms)
    if not ms or tot <= 0:
        return None
    por = defaultdict(float)
    nome = {}
    for c in ms:
        k = c["base"] or c["cnpj"] or str(c["fornecedor"] or "?")
        por[k] += c["valor"]
        nome.setdefault(k, c["fornecedor"])
    dom, v = max(por.items(), key=lambda kv: (kv[1], kv[0]))
    return {"total": tot, "dominante": dom, "fornecedor": nome[dom], "valor_dominante": v, "fatia": v / tot,
            "n_contratos": len(ms), "n_fornecedores": len(por)}


def detectar(itens: list[dict], contexto: dict | None = None) -> list[Disparo]:
    grupos: dict[str, list[dict]] = defaultdict(list)
    for c in itens:
        if elegivel(c) and c["nicho"] != OUTROS:
            grupos[c["grupo"]].append(c)
    out = []
    for g in sorted(grupos):
        ms = grupos[g]
        m = _avaliar(ms)
        if (m is None or m["n_contratos"] < CONTRATOS_MIN or m["total"] <= NICHO_MIN or m["fatia"] <= FATIA_MIN
                or monopolio_legitimo(m["fornecedor"])):
            continue
        dom = sorted((c for c in ms if (c["base"] or c["cnpj"] or str(c["fornecedor"] or "?")) == m["dominante"]),
                     key=lambda c: (-c["valor"], str(c["processo"])))
        u, ex, nch = g.split("|")
        obs = (f"Na unidade {u}, exercício {ex}, o nicho {nch} somou {reais(m['total'])} em {m['n_contratos']} "
               f"contrato(s) de {m['n_fornecedores']} fornecedor(es); {m['fornecedor']} ficou com "
               f"{reais(m['valor_dominante'])} ({m['fatia']:.0%}). Valor contratado (espelho TCE-RJ), não pago. "
               f"{RESSALVA}")
        fatos = [Fato(papel=Papel.SUPORTE, tipo="contrato", fonte="contratos_tcerj", referencia=str(c["processo"]),
                      valor=Decimal(str(round(c["valor"], 2))), descricao=str(c["objeto"] or "")[:240],
                      dados={"unidade": c["unidade"], "fornecedor": c["fornecedor"], "veredito_e9": c.get("e9")})
                 for c in dom[:50]]
        out.append(Disparo(
            chave=g, grupo=g, estado="INDICIO", observacao=obs, processo=str(dom[0]["processo"]) if dom else None,
            entradas={"grupo": g, "fatia_min": FATIA_MIN, "nicho_min": NICHO_MIN, "contratos_min": CONTRATOS_MIN,
                      "contratos": sorted(c["chave_e9"] for c in ms)},
            evidencias=fatos,
            valores={"total": round(m["total"], 2), "valor_dominante": round(m["valor_dominante"], 2),
                     "fatia": round(m["fatia"], 4), "n_contratos": m["n_contratos"],
                     "n_fornecedores": m["n_fornecedores"], "fornecedor_dominante": m["fornecedor"]}))
    return out


def resumo(itens: list[dict], disparos: list[Disparo]) -> dict:
    por = Counter(c.get("e9") or "?:SEM_LINHA_E9" for c in itens)
    indet = sum(n for k, n in por.items() if k.startswith("?"))
    return {"universo_contratos": len(itens), "fora_de_nicho": sum(1 for c in itens if c["nicho"] == OUTROS),
            "elegiveis": sum(1 for c in itens if elegivel(c)), "indeterminados": indet,
            "por_veredito": dict(sorted(por.items())),
            "cobertura": round(1 - indet / len(itens), 4) if itens else None,
            "disparos": len(disparos), "soma_dominante": round(sum(d.valores["valor_dominante"] for d in disparos), 2)}
