# -*- coding: utf-8 -*-
"""Termo de retificação / rerratificação / apostila que MUDA VALOR ("onde se lê R$ A … leia-se R$ B"), e valor em
número que discorda do extenso no próprio termo.

ORIGEM (perícias integrais 18/11/2026): INEA × Brasform, SEI-070002/006481/2024 — "Leia-se ... R$ 20.617.970,44"
replicando na renovação o acréscimo de 2024; INEA × Lytoranea, 006627/2024 doc 254 — apostila "Onde lê-se … R$
1.293.367,35" → "R$ 5.715.379,35"; INEA × Geo Ambiental, 005897/2024 doc 472 — "R$ 1.815.002,86 (cinco milhões,
setecentos e quinze mil, trezentos e setenta e nove reais e trinta e cinco centavos)".

POR QUE IMPORTA. Valor de contrato só muda por termo aditivo (L8 art. 65; L14.133 art. 124); apostila serve a
reajuste previsto e empenho (L8 art. 65 §8º; L14.133 art. 136). Retificação que troca o número é alteração de valor
sem o rito do aditivo; e número × extenso divergente deixa o valor juridicamente incerto (prevalece o extenso, CC
art. 1.025 por analogia de praxe) — o pago pode ter seguido o número errado.

GRAU: medio para ambos (indício; pede a memória de cálculo); fraco = nunca emitido. Não há "forte" automático:
erro material corrigido é explicação inocente frequente.
EXPLICAÇÕES INOCENTES: correção de erro de digitação sem efeito financeiro (pede conferir NL/OB); reajuste
apostilado (permitido) — o achado registra se o termo cita reajuste.
"""
from __future__ import annotations

import re

from compliance_agent.padroes import _aditivos_comum as C

ID = "retificacao_altera_valor"
_RE_TIT = re.compile(r"retifica|rerratifica|re-ratifica|apostil|aditivo|aditamento", re.I)
_RE_TIT_NAO = re.compile(r"minuta|rascunho|parecer|despacho|of[íi]cio|memorando|e-?mail|solicita|publica[çc]|extrato|"
                         r"check|an[áa]lise|informa[çc]", re.I)
_RE_ONDE = re.compile(r"onde\s+(?:se\s+)?l[êe](?:-se)?\s*[:,]?", re.I)
_RE_LEIA = re.compile(r"leia-?\s*se\s*[:,]?", re.I)
_RE_REAJ = re.compile(r"reajust|repactua|IPCA|INCC|IGP-?M|anivers[áa]rio", re.I)


def onde_le_leia_se(texto: str) -> list[dict]:
    """Pares "onde se lê" × "leia-se" cujos valores em R$ diferem. Função pura."""
    out = []
    for m in _RE_ONDE.finditer(texto):
        if not C.no_corpo(texto, m.start()):
            continue
        ml = _RE_LEIA.search(texto, m.end(), m.end() + 3000)
        if not ml:
            continue
        antes = [C.num_br(v) for v in C._RE_VALOR.findall(texto[m.end():ml.start()])]
        fim = _RE_ONDE.search(texto, ml.end(), ml.end() + 3000)
        depois = [C.num_br(v) for v in C._RE_VALOR.findall(texto[ml.end(): fim.start() if fim else ml.end() + 1500])]
        antes, depois = [v for v in antes if v], [v for v in depois if v]
        if not antes or not depois or set(antes) == set(depois):
            continue
        out.append({"onde": antes, "leia": depois, "aumenta": max(depois) > max(antes),
                    "reajuste": bool(_RE_REAJ.search(texto[max(0, m.start() - 800): ml.end() + 800])),
                    "trecho": C.trecho(texto, m.start(), min(len(texto), ml.end() + 160), 40)[:500]})
    return out


def varrer(limite: int | None = None) -> dict:
    idx = C.indice(limite=limite)["processos"]
    funil = {"processos": len(idx), "com_termo": 0, "termos_lidos": 0, "retificacoes_de_valor": 0, "extenso_divergente": 0}
    cob = {"termos_sem_texto": 0, "termos_alheios": 0}
    achados = []
    for tag, p in idx.items():
        docs = [d for d in p["docs"] if _RE_TIT.search(d["titulo"] or "") and not _RE_TIT_NAO.search(d["titulo"] or "")]
        if not docs:
            continue
        funil["com_termo"] += 1
        provas, extra, vistos = [], {"retificacoes": [], "extenso": []}, set()
        for d in docs:
            if d.get("alheio"):
                cob["termos_alheios"] += 1
                continue
            t = C.sem_rodape(C.ler(d))
            if not t.strip():
                cob["termos_sem_texto"] += 1
                continue
            funil["termos_lidos"] += 1
            for r in onde_le_leia_se(t):
                k = ("r", tuple(r["onde"]), tuple(r["leia"]))
                if k in vistos:
                    continue
                vistos.add(k)
                funil["retificacoes_de_valor"] += 1
                extra["retificacoes"].append({"doc": d["i"], **{x: r[x] for x in ("onde", "leia", "aumenta", "reajuste")}})
                provas.append(f"doc {d['i']} ({d['titulo'][:60]}) — \"{r['trecho']}\"")
            for x in C.divergencias_extenso(t):
                if not C.no_corpo(t, x["pos"]):
                    continue
                k = ("e", x["valor"], x["valor_extenso"])
                if k in vistos:
                    continue
                vistos.add(k)
                funil["extenso_divergente"] += 1
                extra["extenso"].append({"doc": d["i"], "valor": x["valor"], "valor_extenso": x["valor_extenso"]})
                provas.append(f"doc {d['i']} ({d['titulo'][:60]}) — \"{x['trecho']}\" [número R$ {x['valor']:,.2f} × "
                              f"extenso R$ {x['valor_extenso']:,.2f}]")
        if not provas:
            continue
        partes = []
        if extra["retificacoes"]:
            partes.append(f"{len(extra['retificacoes'])} retificação(ões) que trocam valor em R$"
                          + (" (alguma cita reajuste — apostila de reajuste é permitida)" if any(r["reajuste"] for r in extra["retificacoes"]) else ""))
        if extra["extenso"]:
            partes.append(f"{len(extra['extenso'])} valor(es) com número ≠ extenso")
        achados.append(C.achado(
            C.chave_de_tag(tag), "medio", prova="; ".join(provas[:5]),
            porque=("; ".join(partes) + ". Valor de contrato só muda por termo aditivo; erro material corrigido é a "
                    "explicação inocente a afastar com a memória de cálculo e a NL/OB do período."),
            fonte=f"termos/apostilas/retificações do processo ({docs[0]['fonte']})", **extra))
    return C.resultado(ID, funil["com_termo"], cob, achados, funil)
