#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""QUANTITATIVO DE POSTOS nas planilhas de custos — quanta gente a empresa se obrigou a manter.

PEDIDO DO DONO (2026-08-16): "extrai o quantitativo de postos das planilhas de custos".

É o dado que mais se aproxima de "quantos funcionários" sem sair de fonte oficial: número de
empregados por CNPJ é sigiloso (RAIS identificada, eSocial) e o CAGED público não traz CNPJ. O POSTO
CONTRATADO, ao contrário, está nos autos — é o que a empresa se obrigou a manter naquele contrato, e
pode ser confrontado com o que recebeu.

COMO O DADO APARECE DE VERDADE, e por que a primeira tentativa falhou. A planilha é o Anexo IV do
modelo da IN 05/2017, uma TABELA — e a extração de PDF a ACHATA, jogando os rótulos primeiro e os
valores depois:

    Tipo de Serviço | Unidade de Medida | Quantidade total a contratar
    ENFERMEIRO GERAL 30H | POSTO | 116

Procurar o número logo após "QUANTIDADE TOTAL A CONTRATAR" devolve ZERO em 29 de 29 planilhas — o
rótulo fica órfão do valor. A âncora certa é a UNIDADE DE MEDIDA (`POSTO`), com a categoria na
linha anterior e a quantidade na seguinte.

DUAS ARMADILHAS MEDIDAS, ambas encontradas prototipando antes de escrever o extrator:
  · "postos de trabalho" também aparece na cláusula de COTA DE PCD ("5% dos postos com beneficiários
    reabilitados") — boilerplate de edital, não quantitativo;
  · a maioria das planilhas anexas ao edital é MODELO EM BRANCO (salário "0", quantidade vazia).
    Modelo não é declaração: só entra quem tem número.

Uso:
    .venv/bin/python tools/postos_contratados.py
    .venv/bin/python tools/postos_contratados.py --detalhe 080002/017006/2024
"""
from __future__ import annotations

import argparse
import collections
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ARQUIVO = Path(__file__).resolve().parent.parent / "data" / "sei_arquivo"

# `POSTO` como unidade de medida, entre a categoria (linha antes) e a quantidade (linha depois).
RE_POSTO = re.compile(r"\n\s*([^\n|]{3,60}?)\s*\n\s*(?:POSTO|Posto|POSTOS|Postos)\s*\n\s*(\d{1,5})\s*\n")

# O rótulo tem de estar no documento: sem ele, `POSTO` isolado pode ser qualquer coisa.
ANCORA = "quantidade total a contratar"


def postos_do_texto(texto: str) -> list[tuple[str, int]]:
    """(categoria, quantidade) de cada linha de posto — vazio se não for planilha preenchida."""
    if ANCORA not in (texto or "").lower():
        return []
    saida = []
    for cat, qtd in RE_POSTO.findall(texto):
        c = re.sub(r"\s+", " ", cat).strip(" |")
        # a linha anterior às vezes é o próprio cabeçalho, não a categoria
        if not c or c.lower().startswith(("quantidade", "unidade", "tipo de", "função da")):
            c = "(categoria não identificada)"
        n = int(qtd)
        if 0 < n <= 5000:          # acima disso não é posto, é valor colado na coluna errada
            saida.append((c, n))
    return saida


def varrer(base: Path = ARQUIVO) -> dict:
    """Processo -> {postos, linhas, categorias} lendo só documentos de planilha/custo."""
    out: dict = {}
    for d in sorted(base.iterdir()):
        td = d / "texto"
        if not td.is_dir() or d.name.startswith("_"):
            continue
        linhas: list[tuple[str, int]] = []
        # SEM filtrar por NOME de arquivo: a âncora textual já garante que é planilha, e o nome
        # engana. Medido: filtrando por "planilha|custo" no nome, 4 processos e 163 postos; sem o
        # filtro, 9 processos e 219 postos — mais da metade dos casos estava em documento com
        # outro nome (anexo, termo de referência, resposta a diligência).
        for f in td.glob("*.txt"):
            try:
                linhas += postos_do_texto(f.read_text(errors="ignore"))
            except OSError:
                continue
        if linhas:
            proc = d.name.replace("_", "/", 2) if d.name.count("_") >= 2 else d.name
            out[proc] = {"postos": sum(n for _, n in linhas), "linhas": len(linhas),
                         "categorias": linhas}
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--detalhe", default="", help="mostra as categorias de UM processo")
    ap.add_argument("--limite", type=int, default=20)
    a = ap.parse_args()

    dados = varrer()
    if a.detalhe:
        alvo = a.detalhe.replace("-", "/")
        d = dados.get(alvo)
        if not d:
            print(f"sem postos extraídos para {alvo}")
            return 1
        print(f"{alvo} — {d['postos']} postos em {d['linhas']} categorias\n")
        for cat, n in sorted(d["categorias"], key=lambda x: -x[1]):
            print(f"   {n:5d}  {cat}")
        return 0

    total = sum(v["postos"] for v in dados.values())
    print(f"processos com quantitativo de postos extraído: {len(dados)}")
    print(f"total de postos declarados: {total:,}".replace(",", "."))
    print("\nO POSTO É O QUE A EMPRESA SE OBRIGOU A MANTER NAQUELE CONTRATO — não é o quadro de\n"
          "pessoal da empresa, que não é dado público.\n")
    print(f"{'postos':>7} {'linhas':>6}  processo             maior categoria")
    for proc, v in sorted(dados.items(), key=lambda x: -x[1]["postos"])[:a.limite]:
        maior = max(v["categorias"], key=lambda x: x[1])
        print(f"{v['postos']:7d} {v['linhas']:6d}  {proc:20} {maior[0][:38]} ({maior[1]})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
