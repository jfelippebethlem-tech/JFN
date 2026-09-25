#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PERÍCIA TRIPLA — o mesmo processo lido por três olhares: jurídico, forense e financeiro.

**A pergunta que isto responde.** As oito lentes anteriores ordenam FORNECEDORES por sinal
(porte, sanção, dependência, controle). Esta ordena **PROCESSOS** por *lacuna probatória*, que é o
que um perito de controle externo procura: **o que deveria estar nos autos e não está**.

**A fonte é `interpretacao.o_que_falta`** — campo da leitura dupla presente em 89,2% das leituras,
nunca minerado. Ele não descreve o problema em abstrato: **nomeia o documento ausente**
(*"Cópia do Contrato nº 206/2023"*, *"Edital de licitação e respectivos atos de homologação"*,
*"Certidões de regularidade fiscal e trabalhista atualizadas, nos termos do Enunciado PGE nº 08"*).

**O CORTE QUE TORNA O NÚMERO DEFENSÁVEL.** Lacuna apontada pela IA pode ser **da nossa captura**,
não dos autos — e confundir as duas produz acusação falsa. Por isso a lente só considera processo
com **CAPTURA COMPLETA**: manifesto com `docs >= docs_na_arvore` e **sem lacuna declarada**. Eram
2.066 de 3.259 lidos (63,4%). Nos demais, a resposta honesta é INDISPONÍVEL, não "falta documento".

**AS TRÊS LENTES** (medidas nos 2.066 com captura completa):

    JURÍDICA   instrumento (contrato/ARP) ....... 1.133 (54,8%)
               licitação (edital/homologação) ....  525 (25,4%)
               parecer jurídico/PGE
    FORENSE    atesto / prova de execução ........  421 (20,4%)
               fiscal designado
               cadeia documental (doc citado e não juntado)
    FINANCEIRA habilitação fiscal (CND/FGTS) .....  355 (17,2%)
               pesquisa de preços ................   80 ( 3,9%)
               empenho / liquidação / nota fiscal

**A gradação importa mais que a contagem.** Falta de *pesquisa de preços* (3,9%) é rara e cara: sem
ela não se demonstra vantajosidade, e o TCU trata isso como vício autônomo. Falta de *instrumento*
(54,8%) é comum e frequentemente lícita (Lei 14.133, art. 95 dispensa termo em entrega imediata) —
vale como contexto, não como fila. **Sinal raro ordena; sinal comum descreve.**

RESSALVAS que viajam com o número:
  · é a leitura da IA sobre os autos, com o documento nomeado — a conferência é do humano;
  · "não consta nos autos" ≠ "não existe": o documento pode viver em processo apenso;
  · só vê o que foi lido — 3.259 de 221.130 processos com OB paga (1,5%);
  · a lente ORDENA fila de apuração; não acusa.

Uso:
    .venv/bin/python tools/pericia_tripla.py
    .venv/bin/python tools/pericia_tripla.py --lente financeira --limite 30
    .venv/bin/python tools/pericia_tripla.py --sem-corte-de-captura   # conferência: inclui parciais
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from compliance_agent.reporting.intel_base import moeda

RAIZ = Path(__file__).resolve().parent.parent
DB = RAIZ / "data" / "compliance.db"
ARQUIVO = RAIZ / "data" / "sei_arquivo"

# Cada entrada: (lente, rótulo, regex, peso). O PESO reflete raridade × gravidade, não a contagem:
# pesquisa de preços é rara (3,9%) e é o vício que impede aferir vantajosidade; instrumento é comum
# (54,8%) e muitas vezes lícito. Sinal raro ordena a fila; sinal comum descreve o contexto.
LENTES: tuple[tuple[str, str, str, int], ...] = (
    ("financeira", "pesquisa de preços",
     r"pesquisa de pre|cota[çc][ãa]o|or[çc]amento estimativo|planilha de custo|"
     r"composi[çc][ãa]o de pre|vantajosidade", 5),
    ("forense", "fiscal designado",
     r"fiscal do contrato|designa[çc][ãa]o de fiscal|portaria de fiscal|gestor do contrato", 5),
    ("forense", "atesto / prova de execução",
     r"atesto|termo de recebimento|comprova[çc][ãa]o (da|de) (efetiv|execu|entrega)|"
     r"relat[óo]rio de (execu|fiscal)|medi[çc][ãa]o", 4),
    ("juridica", "licitação (edital/homologação)",
     r"edital|preg[ãa]o|homologa|adjudica|justificativa de (dispensa|inexigib)", 3),
    ("financeira", "habilitação fiscal (CND/FGTS)",
     r"certid[ãa]o|regularidade fiscal|trabalhista|FGTS|\bCND\b", 3),
    ("juridica", "parecer jurídico / PGE",
     r"parecer|\bPGE\b|assessoria jur|an[áa]lise jur|Enunciado", 2),
    ("forense", "cadeia documental (citado e não juntado)",
     r"c[óo]pia (autenticada|do)|documento (que comprove|referenciado)|n[ãa]o (foi )?apresentad", 2),
    ("financeira", "empenho / liquidação / nota fiscal",
     r"nota de empenho|refor[çc]o de empenho|liquida[çc][ãa]o|nota fiscal|ordem banc", 1),
    ("juridica", "instrumento (contrato/ARP)",
     r"contrato|ata de registro|\bARP\b|instrumento contratual|conv[êe]nio", 1),
)


def captura_completa() -> set[str]:
    """Processos cujo arquivo tem TODOS os documentos da árvore e nenhuma lacuna declarada.

    Sem este corte, 'falta o edital' pode significar 'nossa captura não trouxe o edital' — e a
    lente acusaria a Administração de um vício que é nosso. 2.066 de 3.259 lidos passam.
    """
    ok: set[str] = set()
    if not ARQUIVO.is_dir():
        return ok
    for d in ARQUIVO.iterdir():
        m = d / "manifest.json"
        if not d.is_dir() or not m.exists():
            continue
        try:
            j = json.loads(m.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        n_docs = len([x for x in (j.get("docs") or []) if isinstance(x, dict)])
        na_arvore = j.get("docs_na_arvore")
        if n_docs and na_arvore and n_docs >= na_arvore and not (j.get("lacunas") or []):
            p = d.name.split("_")
            if len(p) == 3:
                ok.add(f"{p[0]}/{p[1]}/{p[2]}")
    return ok


def periciar(con: sqlite3.Connection, corte_de_captura: bool = True) -> list[dict]:
    """Processos ordenados por gravidade da lacuna probatória."""
    completos = captura_completa() if corte_de_captura else None

    achados: dict = {}
    for numero, ia in con.execute(
            "SELECT numero_sei, ia FROM sei_leitura_dupla WHERE ia IS NOT NULL"):
        if completos is not None and numero not in completos:
            continue
        try:
            d = json.loads(ia)
        except (ValueError, TypeError):
            continue
        interp = d.get("interpretacao") or {}
        falta = interp.get("o_que_falta")
        if not falta:
            continue
        itens = falta if isinstance(falta, list) else [falta]
        texto = " ".join(str(x.get("item") if isinstance(x, dict) else x) for x in itens)

        marcas, peso = [], 0
        for lente, rotulo, rx, p in LENTES:
            if re.search(rx, texto, re.I):
                marcas.append({"lente": lente, "falta": rotulo, "peso": p})
                peso += p
        if not marcas:
            continue
        achados[numero] = {
            "numero_sei": numero, "peso": peso, "marcas": marcas,
            "lentes": sorted({m["lente"] for m in marcas}),
            "o_que_e": str(interp.get("o_que_e") or "")[:200],
            "falta": texto[:400],
        }

    pago: dict = collections.defaultdict(float)
    obs: dict = collections.Counter()
    credor: dict = {}
    for processo, valor, nome in con.execute(
            "SELECT processo, valor, nome_credor FROM ob_orcamentaria_siafe "
            "WHERE status='Contabilizado' AND processo LIKE 'SEI-%'"):
        k = str(processo).replace("SEI-", "")
        if k in achados:
            pago[k] += valor or 0.0
            obs[k] += 1
            credor.setdefault(k, nome)

    saida = []
    for k, v in achados.items():
        saida.append({**v, "pago": pago.get(k, 0.0), "n_obs": obs.get(k, 0),
                      "credor": credor.get(k, "")})
    # ordena por PESO (gravidade) e, dentro dele, por dinheiro — sinal raro na frente.
    saida.sort(key=lambda x: (-x["peso"], -x["pago"]))
    return saida


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--lente", choices=("juridica", "forense", "financeira"),
                    help="filtra por olhar pericial")
    ap.add_argument("--sem-corte-de-captura", action="store_true",
                    help="inclui processos de captura parcial (conferência — NÃO é fila)")
    ap.add_argument("--limite", type=int, default=15)
    a = ap.parse_args()

    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    linhas = periciar(con, corte_de_captura=not a.sem_corte_de_captura)
    if a.lente:
        linhas = [x for x in linhas if a.lente in x["lentes"]]

    print("perícia tripla — jurídica · forense · financeira")
    print(f"  {len(linhas)} processos · R$ {moeda(sum(x['pago'] for x in linhas))} pagos")
    if not a.sem_corte_de_captura:
        print("  (só processos com CAPTURA COMPLETA — lacuna dos AUTOS, não da nossa coleta)")
    print("\n  Ordenado por GRAVIDADE, não por contagem: falta de pesquisa de preços (3,9% dos")
    print("  processos) pesa mais que falta de instrumento (54,8%), que é comum e às vezes lícita.\n")

    porlente: dict = collections.Counter()
    for x in linhas:
        for m in x["marcas"]:
            porlente[(m["lente"], m["falta"])] += 1
    for (lente, falta), n in sorted(porlente.items(), key=lambda kv: -kv[1]):
        print(f"   {lente:10s} {falta:40s} {n:5,}")

    print(f"\n{'peso':>4} {'pago':>16}  processo · o que falta")
    for x in linhas[:a.limite]:
        print(f"{x['peso']:4d} R$ {moeda(x['pago']):>13}  {x['numero_sei']}  "
              f"{x['credor'][:24]}")
        print(f"       [{'+'.join(x['lentes'])}] {x['falta'][:110]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
