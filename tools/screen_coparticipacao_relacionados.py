#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Duas empresas do MESMO comando disputando o MESMO certame — competição simulada (E.3.2).

O QUE ISTO FECHA. O `resolver_nome_cnpj` foi escrito para desbloquear exatamente esta pergunta e
disse por escrito o que faltava: *"sem CNPJ não há quadro societário, e sem QSA o E.3.2 (cruzamento
vencedor × perdedoras) fica de fora — que é exatamente o eixo que o volume de coleta existia para
alimentar"*. A ponte foi construída (21.141 nomes resolvidos) e **ninguém a atravessou**: nenhum
módulo cruzava `tcerj_licitante` com o QSA. Esta é a travessia.

A DATA É O ACHADO OU O ANACRONISMO. Sócio que entrou DEPOIS do certame não descreve o certame. Sem
o filtro de vigência, os dois maiores pares da lista eram ROMA×MEDKA (16 certames) e
DROGAFONTE×LYF (10) — e em ambos o administrador comum entrou no ano SEGUINTE. Com o filtro, os
dois somem e sobe quem tem elo vigente. É a mesma lição de `situacao-cadastral-vigencia-na-data`,
onde 78,7% das acusações de "empresa não-ativa" eram anacrônicas.

O QUE O SCREEN NÃO DIZ:

  · **Coparticipar não é crime.** A Lei 14.133 não veda que relacionadas disputem o mesmo certame;
    o que se pune é fraudar o caráter competitivo (art. 90). O indício é a repetição do padrão,
    e o julgamento é dos autos — ata da sessão, propostas, desistências.
  · **`tcerj_licitante` é por PROCESSO, não por item.** Em registro de preços a mesma empresa
    ganha itens e perde outros, e por isso aparece como VENCEDOR *e* PERDEDOR no mesmo processo.
    Ler isso como "o grupo venceu e perdeu" é ler artefato de granularidade.
  · **O elo vem do CPF mascarado**, que colide (medido na casa: 977 de 24.448 documentos carregam
    mais de um nome). Por isso o par sai com a PREVALÊNCIA do elo: pessoa presente em muitas
    empresas não individualiza ninguém e o par é rebaixado.
  · **Cobertura:** 68,5% das linhas de licitante resolvem a CNPJ. O que não resolve fica invisível
    — o número de pares é **piso, nunca teto**.

    python -m tools.screen_coparticipacao_relacionados
    python -m tools.screen_coparticipacao_relacionados --md --gravar
"""
from __future__ import annotations

import argparse
import collections
import itertools
import sqlite3
from functools import lru_cache
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parent.parent
# Elo presente em muitas empresas é administrador profissional ou colisão de máscara — não
# individualiza comando. Mesmo piso do grafo de grupos (`osint/grupo_economico`).
MAX_EMPRESAS_POR_ELO = 20


@lru_cache(maxsize=None)
def _norm(s: str) -> str:
    """Normaliza o nome do licitante — MEMOIZADO.

    A tabela tem 126.251 linhas para **25.361 participantes distintos**: normalizar por linha faz
    cinco vezes o trabalho necessário, e a normalização (unicode + regex) é o gargalo desta tela.
    Medido em 2026-08-09: a rota levava 171 s na primeira chamada e a API é single-process — uma
    rota pesada síncrona põe todas as outras na fila.
    """
    from tools.resolver_nome_cnpj import normalizar
    return normalizar(s)


def medir(db: str = "", min_certames: int = 2) -> list[dict[str, Any]]:
    # Piso de plausibilidade do valor: o mesmo do coletor, que é quem conhece o defeito da fonte
    # (homologado > 10× o estimado — 1,1% das linhas carregam 87,4% da soma do campo).
    from compliance_agent.collectors.tcerj_licitantes import MAX_HOMOLOGADO_SOBRE_ESTIMADO
    from compliance_agent.reporting.intel_base import _DB

    con = sqlite3.connect(f"file:{db or _DB}?mode=ro", uri=True, timeout=60)
    try:
        res = {n: c for n, c in con.execute(
            "SELECT nome_norm, cnpj_basico FROM nome_cnpj_resolvido "
            "WHERE COALESCE(cnpj_basico,'') <> ''")}
        linhas = con.execute(
            "SELECT ente, ano, processo, participante, resultado, qtd_participantes, "
            # homologado implausível vira NULL: 1,1% das linhas carregam 87,4% da soma do campo
            " CASE WHEN COALESCE(valor_estimado,0) > 0 "
            "      AND valor_homologacao > ? * valor_estimado THEN NULL "
            "      ELSE valor_homologacao END, data_homologacao FROM tcerj_licitante",
            (MAX_HOMOLOGADO_SOBRE_ESTIMADO,)).fetchall()
    except sqlite3.OperationalError:
        return []

    por: dict[tuple, set] = collections.defaultdict(set)
    nome_de: dict[str, str] = {}
    quando: dict[tuple, str] = {}
    valor: dict[tuple, float] = {}
    npart: dict[tuple, int] = {}
    for ente, ano, proc, nome, _res, qtd, val, dh in linhas:
        raiz = res.get(_norm(nome or ""))
        if not raiz:
            continue
        k = (ente, ano, proc)
        por[k].add(raiz)
        nome_de.setdefault(raiz, str(nome or ""))
        d = str(dh or "").replace("-", "")[:8]
        # sem homologação, o teto do ano — nunca uma data que faça o elo parecer mais antigo
        quando[k] = d if len(d) == 8 else f"{ano}1231"
        valor[k] = max(valor.get(k, 0.0), float(val or 0))
        npart[k] = max(npart.get(k, 0), int(qtd or 0))

    usados = {c for cs in por.values() for c in cs}
    if not usados:
        return []
    vinc: dict[str, dict[str, str]] = collections.defaultdict(dict)
    nome_doc: dict[str, str] = {}
    marcas = ",".join("?" * len(usados))
    try:
        for rz, doc, entrada, nm in con.execute(
                "SELECT cnpj_basico, doc_socio, MIN(data_entrada), MIN(nome_socio) "
                "FROM socios_receita WHERE COALESCE(doc_socio,'') <> '' "
                f"AND length(COALESCE(data_entrada,'')) = 8 AND cnpj_basico IN ({marcas}) "
                "GROUP BY 1, 2", sorted(usados)):
            vinc[doc][rz] = entrada
            nome_doc[doc] = str(nm or "")
    except sqlite3.OperationalError:
        return []
    finally:
        con.close()

    prevalencia = {doc: len(onde) for doc, onde in vinc.items()}
    # ÍNDICE INVERTIDO: raiz -> [(doc, data_entrada)]. A primeira versão varria TODOS os documentos
    # para cada certame — 14 mil certames × dezenas de milhares de sócios = centenas de milhões de
    # iterações, e a rota levava 171 s (memoizar a normalização não moveu; o laço é que era o
    # gargalo). Aqui só se olham os sócios das empresas QUE ESTÃO no certame.
    docs_por_raiz: dict[str, list[tuple[str, str]]] = collections.defaultdict(list)
    for doc, onde in vinc.items():
        if prevalencia[doc] > MAX_EMPRESAS_POR_ELO:
            continue                             # administrador profissional / colisão de máscara
        for rz, entrada in onde.items():
            docs_por_raiz[rz].append((doc, entrada))

    certames: dict[tuple, set] = collections.defaultdict(set)
    elos: dict[tuple, set] = collections.defaultdict(set)
    for k, cs in por.items():
        dt = quando[k]
        por_doc: dict[str, list[str]] = collections.defaultdict(list)
        for c in cs:
            for doc, entrada in docs_por_raiz.get(c, ()):
                if entrada <= dt:                # vínculo VIGENTE na data do certame
                    por_doc[doc].append(c)
        for doc, membros in por_doc.items():
            if len(membros) < 2:
                continue
            for a, b in itertools.combinations(sorted(membros), 2):
                certames[(a, b)].add(k)          # SET: dois elos no mesmo certame contam UMA vez
                elos[(a, b)].add(nome_doc.get(doc, doc))

    fora = []
    for (a, b), ks in certames.items():
        if len(ks) < min_certames:
            continue
        fora.append({
            "cnpj_a": a, "nome_a": nome_de.get(a, ""), "cnpj_b": b, "nome_b": nome_de.get(b, ""),
            "certames": len(ks), "municipios": len({k[0] for k in ks}),
            "valor": round(sum(valor.get(k, 0.0) for k in ks), 2),
            "elos": sorted(elos[(a, b)])[:3],
            "processos": [{"ente": k[0], "ano": k[1], "processo": k[2],
                           "participantes": npart.get(k, 0), "valor": valor.get(k, 0.0)}
                          for k in sorted(ks)],
        })
    fora.sort(key=lambda d: (-d["certames"], -d["valor"]))
    return fora


RESSALVA = (
    "Coparticipar não é vedado: a Lei 14.133/2021 pune fraudar o caráter competitivo (art. 90), "
    "não a presença de relacionadas no mesmo certame. O indício é a REPETIÇÃO, e quem decide são "
    "os autos — ata da sessão, propostas e desistências. O elo é o vínculo societário VIGENTE na "
    "data do certame; elo posterior foi descartado. A identificação do sócio usa CPF mascarado, "
    "que colide, e só 68,5% dos licitantes resolvem a CNPJ: a lista é piso, nunca teto."
)


def markdown(itens: list[dict]) -> str:
    from compliance_agent.reporting.intel_base import moeda
    L = ["# Coparticipação de empresas relacionadas no mesmo certame", "", f"> {RESSALVA}", "",
         "| Certames | Municípios | Empresa A | Empresa B | Elo vigente | Homologado |",
         "|---:|---:|---|---|---|---:|"]
    for x in itens:
        L.append(f"| {x['certames']} | {x['municipios']} | {x['nome_a'][:34]} ({x['cnpj_a']}) | "
                 f"{x['nome_b'][:34]} ({x['cnpj_b']}) | {'; '.join(x['elos'])[:40]} | "
                 f"R$ {moeda(x['valor'])} |")
    return "\n".join(L) + "\n"


def main(argv: list[str] | None = None) -> int:  # pragma: no cover
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-certames", type=int, default=2)
    ap.add_argument("--top", type=int, default=20)
    ap.add_argument("--md", action="store_true")
    ap.add_argument("--gravar", action="store_true")
    a = ap.parse_args(argv)
    itens = medir(min_certames=a.min_certames)[: a.top]
    if a.md or a.gravar:
        texto = markdown(itens)
        print(texto)
        if a.gravar:
            alvo = _REPO / "data" / "coparticipacao_relacionados.md"
            alvo.write_text(texto, encoding="utf-8")
            print(f"gravado: {alvo}")
    else:
        print(f"{len(itens)} par(es) de relacionadas no mesmo certame (elo vigente na data):")
        for x in itens:
            print(f"   {x['certames']:3d} certames · {x['municipios']:2d} mun. · "
                  f"{x['nome_a'][:28]:28} × {x['nome_b'][:28]:28} R$ {x['valor']:>13,.0f}")
            print(f"        elo: {'; '.join(x['elos'])[:60]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
