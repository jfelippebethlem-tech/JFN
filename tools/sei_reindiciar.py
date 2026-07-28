#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Reavalia os indícios das notas já gravadas, com as réguas de HOJE.

    .venv/bin/python tools/sei_reindiciar.py            # só relata (não escreve)
    .venv/bin/python tools/sei_reindiciar.py --gravar   # regrava as notas que mudaram

POR QUE ISTO EXISTE. Melhorar uma régua não conserta o que ela já escreveu. Em 2026-07-28
às 14:34 o indício DV parou de contar o rótulo do roteiro como achado; às 13:50 daquele dia
a nota de SEI-420001/004984/2025 já tinha sido gravada afirmando "4 divergência(s)" — e três
eram falsas: duas inconsistências que o próprio texto declara **corrigidas por Termo de
Rerratificação**, e uma "cláusula de contraditório e defesa prévia", que casou porque
*contraditório* contém `contradi`. Medido: **81 das 145 notas** nasceram antes do conserto.

O vault é a memória permanente do órgão. Falso positivo esquecido lá não é ruído: é um
fiscal abrindo a nota e vendo quatro divergências onde há uma.

CUSTO ZERO. O dossiê extraído está em `output/dossies/` e as réguas são código sobre o texto
já citado — nenhuma chamada de modelo, nenhum browser, nenhuma sessão SEI. É a divisão da
casa: a IA leu uma vez, o código reavalia quantas vezes for preciso.

O QUE NÃO FAZ. Não reextrai o dossiê: se a leitura foi parcial, ela continua parcial e a nota
continua dizendo qual é a cobertura. Reindiciar é reavaliar o que se leu, não ler de novo.
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys

RAIZ = pathlib.Path(__file__).resolve().parent.parent
DOSSIES = RAIZ / "output" / "dossies"
NOTAS = pathlib.Path.home() / "vault" / "processos"

_RE_DECLARADOS = re.compile(r"^indicios:\s*(\d+)\s*$", re.MULTILINE)


def indicios_declarados_na_nota(texto: str) -> int | None:
    """Quantos indícios a nota afirma ter. `None` quando a nota não declara."""
    m = _RE_DECLARADOS.search(texto or "")
    return int(m.group(1)) if m else None


def precisa_regravar(texto_nota: str, n_agora: int, *, texto_novo: str | None = None) -> bool:
    """Regrava quando o conteúdo recalculado difere do que está no vault.

    A 1ª versão comparava só o NÚMERO de indícios, e deixou passar o caso que motivou a
    ferramenta: SEI-420001/004984/2025 tinha 3 indícios antes e 3 depois, mas o DV dentro
    dela caiu de 4 divergências para 1 — a nota seguiu afirmando "4 divergência(s)". Contagem
    igual não é conteúdo igual.

    Com `texto_novo`, compara os textos ignorando `analisado_em` (carimbo do gerador, não
    conteúdo). Sem ele, cai na contagem — e não saber quantos eram é razão para reavaliar.
    """
    if texto_novo is not None:
        return _sem_data(texto_nota) != _sem_data(texto_novo)
    declarados = indicios_declarados_na_nota(texto_nota)
    return declarados is None or declarados != n_agora


def _sem_data(texto: str) -> str:
    return _RE_DATA_ANALISE.sub("analisado_em: -", texto or "").strip()


_RE_DATA_ANALISE = re.compile(r"^analisado_em:\s*(\S+)\s*$", re.MULTILINE)


def preservar_data_de_analise(nota_nova: str, nota_antiga: str) -> str:
    """Devolve a nota recalculada com a data em que o processo FOI LIDO, não a de hoje.

    `_nota_vault` carimba `analisado_em` com a data corrente, o que está certo para uma
    análise nova e errado para uma reavaliação: reindiciar é reavaliar o que já se leu, e
    dizer que o processo foi lido hoje seria mentir sobre a leitura. Sem data antiga
    conhecida, mantém a nova — inventar data seria pior.
    """
    antiga = _RE_DATA_ANALISE.search(nota_antiga or "")
    if not antiga:
        return nota_nova
    return _RE_DATA_ANALISE.sub(f"analisado_em: {antiga.group(1)}", nota_nova, count=1)


def regravar_nota(pasta: str, dossie: str, nota_antiga: str,
                  monta_nota, varrer, confronto, natureza=None) -> int:
    """Escreve a nota recalculada preservando a data de leitura. Devolve 1 se escreveu.

    `monta_nota` (`_nota_vault`) devolve o TEXTO da nota, não o caminho, e não escreve nada —
    quem grava é o chamador. As três funções entram por parâmetro para que este passo, o
    único que toca o vault, seja testável sem o pipeline inteiro.
    """
    m = re.search(r"^pago_ob_siafe:\s*([\d.]+)", nota_antiga, re.MULTILINE)
    pago = float(m.group(1)) if m else 0.0
    credor, prop = natureza(pasta) if natureza else (None, 0.0)
    texto = monta_nota(pasta, pago, dossie, varrer(dossie), confronto(pasta, dossie),
                       credor=credor, prop_nao_fornecedor=prop)
    NOTAS.mkdir(parents=True, exist_ok=True)
    (NOTAS / f"{pasta}.md").write_text(preservar_data_de_analise(texto, nota_antiga),
                                       encoding="utf-8")
    return 1


def _reavaliar(pasta: str) -> dict | None:
    """O que muda neste processo, ou `None` se faltar dossiê ou nota.

    Monta a nota que as réguas de HOJE produziriam e compara com a que está no vault — a
    comparação é do texto, não da contagem (ver `precisa_regravar`).
    """
    from compliance_agent.sei.indicios_dossie import varrer
    from tools.sei_analise_em_serie import (_nota_vault, confronto_responsaveis,
                                            natureza_do_pagamento)

    arq_dossie, arq_nota = DOSSIES / f"{pasta}.md", NOTAS / f"{pasta}.md"
    if not arq_dossie.exists() or not arq_nota.exists():
        return None
    dossie = arq_dossie.read_text(encoding="utf-8", errors="ignore")
    antiga = arq_nota.read_text(encoding="utf-8", errors="ignore")
    m = re.search(r"^pago_ob_siafe:\s*([\d.]+)", antiga, re.MULTILINE)
    indicios = varrer(dossie)
    credor, prop = natureza_do_pagamento(pasta)
    nova = _nota_vault(pasta, float(m.group(1)) if m else 0.0, dossie, indicios,
                       confronto_responsaveis(pasta, dossie),
                       credor=credor, prop_nao_fornecedor=prop)
    return {"pasta": pasta, "dossie": dossie, "antiga": antiga,
            "antes": indicios_declarados_na_nota(antiga), "agora": len(indicios),
            "muda": precisa_regravar(antiga, len(indicios), texto_novo=nova)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--gravar", action="store_true",
                    help="regrava as notas cujo número de indícios mudou (padrão: só relata)")
    ap.add_argument("--limite", type=int, default=None)
    a = ap.parse_args()

    pastas = sorted(p.stem for p in DOSSIES.glob("*.md"))[:a.limite]
    mudaram, iguais = [], 0
    for pasta in pastas:
        r = _reavaliar(pasta)
        if r is None:
            continue
        if not r["muda"]:
            iguais += 1
            continue
        mudaram.append(r)

    so_conteudo = sum(1 for r in mudaram if r["antes"] == r["agora"])
    caiu = sum(1 for r in mudaram if (r["antes"] or 0) > r["agora"])
    subiu = sum(1 for r in mudaram if (r["antes"] or 0) < r["agora"])
    print(f"notas avaliadas : {iguais + len(mudaram)}")
    print(f"  inalteradas   : {iguais}")
    print(f"  mudaram       : {len(mudaram)}  (indícios a menos: {caiu} · a mais: {subiu} · "
          f"mesmo número, conteúdo diferente: {so_conteudo})")
    for r in mudaram[:20]:
        marca = " (só conteúdo)" if r["antes"] == r["agora"] else ""
        print(f"    {r['pasta']:24s} {str(r['antes']):>3s} -> {r['agora']:3d}{marca}")
    if not a.gravar:
        print("\n(nada foi escrito — use --gravar para regravar as notas que mudaram)")
        return 0

    from compliance_agent.sei.indicios_dossie import varrer
    from tools.sei_analise_em_serie import (_nota_vault, confronto_responsaveis,
                                            natureza_do_pagamento)

    escritas = sum(regravar_nota(r["pasta"], r["dossie"], r["antiga"], _nota_vault, varrer,
                                 confronto_responsaveis, natureza_do_pagamento)
                   for r in mudaram)
    print(f"\nnotas regravadas: {escritas}")
    return 0


if __name__ == "__main__":   # importar este módulo NÃO pode disparar o trabalho
    sys.exit(main())
