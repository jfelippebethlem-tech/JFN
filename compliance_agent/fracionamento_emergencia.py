# -*- coding: utf-8 -*-
"""Emergência RECORRENTE — o art. 75, VIII exige imprevisibilidade, e ela não se repete 245 vezes.

POR QUE ISTO EXISTE. O sweep de fracionamento (`sweep_fracionamento_tcerj`) mede dispensa por
VALOR — soma contratações que, juntas, ultrapassam o teto do inciso II. Ele é cego para o outro
caminho de fuga à licitação, que na base do Estado é muito maior: a dispensa EMERGENCIAL do
inciso VIII, cujo teto é o próprio valor da urgência.

Medido em 2026-07-28, sobre `compras_diretas_tcerj`:

    contratações com objeto EMERGENCIAL ......... 1.638 · R$ 1.963.745.047,92

REMEDIDO EM 2026-08-11, e o número de cima estava errado nos DOIS sentidos:

    grupos (unidade × exercício) com 5+ emergências .... 27 · R$ 3.467.504.016,02
      FSERJ 2024 ....................................... 414 · R$ 1.727.774.208,83
      DER-RJ 2024 ........................................ 9 · R$   343.085.852,46
      SEEDUC 2024 (100% AGILE CORP) ...................... 8 · R$   159.742.703,70

1. **Cego pela metade.** A régua lia só o texto do OBJETO. Objeto e enquadramento coincidem em
   apenas 613 das 1.504 dispensas do art. 75, VIII: **891 contratações emergenciais pela LEI**
   (R$ 2,60 bi) tinham objeto "PEITO DE FRANGO", "CESTA ALIMENTOS", "MEDICAMENTO VETERINÁRIO" e
   ficavam fora. Somando o art. 24, IV da Lei 8.666/93 — o mesmo instituto na lei anterior, vivo
   em 514 linhas —, são 1.001 e R$ 2,80 bi. (Foi assim que o DER-RJ, cujos objetos são "OBRAS DE
   CONTENÇÃO", nunca apareceu.)
2. **Inflado por contar LINHA.** A tabela tem uma linha por ITEM e repete o TOTAL do processo em
   cada uma: de 1.486 processos com 2+ linhas, 1.485 têm `valor` idêntico em todas. Somar linha a
   linha infla o acervo em 2,30× (R$ 39,65 bi contra R$ 17,20 bi). No DETRAN/2025 isso virava "6
   emergências, R$ 148,8 mi" onde há UM processo de R$ 24,8 mi com seis itens de vigilância.

Apareceu ao avaliar o grupo de topo do sweep de fracionamento: SEDSODH/2024, cuja composição
real era **LOCALMED com 147 contratações emergenciais, R$ 8,5 milhões** — matéria do inciso
VIII, não do II. A régua de valor via o grupo e chamava de outra coisa.

O QUE ESTA RÉGUA NÃO FAZ. Não chama emergência de irregular: ela é instrumento legal, e um
hospital sem insumo precisa dela. O indício é a RECORRÊNCIA, e ela é medida — não presumida.
Emergência que se repete todo ano, sempre com o mesmo fornecedor, não descreve o imprevisível;
descreve planejamento ausente, que a jurisprudência do TCU trata como emergência fabricada
(desídia administrativa não legitima a dispensa).

O julgamento fino (o objeto era mesmo urgente? houve fato superveniente?) é do card P5 sobre o
processo. Aqui é a TRIAGEM em lote que diz onde olhar primeiro.
"""
from __future__ import annotations

import collections
import re

# O objeto do TCE-RJ vem em caixa alta e sem padronização; `emergenc` cobre emergencial,
# emergência e emergencia. `urgen` fica de fora de propósito: "atendimento de urgência" é
# NOME DE SERVIÇO de saúde, não fundamento de contratação — casá-lo encheria a fila de
# pronto-socorro contratado por licitação normal.
_RE_EMERGENCIA = re.compile(r"emergenc|emerg[êe]ncia", re.IGNORECASE)

# O OBJETO NÃO É A ÚNICA PROVA — E É A PIOR DELAS. Medido em 2026-08-11 nas 20.113 linhas de
# `compras_diretas_tcerj`: 1.800 objetos dizem "emergencial", 1.504 contratações têm enquadramento
# no art. 75, VIII, e apenas **613 são as mesmas**. Ou seja, **891 dispensas emergenciais pela LEI
# ficavam fora da régua** (R$ 2,60 bi), porque o objeto delas diz "PEITO DE FRANGO", "CESTA
# ALIMENTOS", "AQUISIÇÃO DE MEDICAMENTO DE USO VETERINÁRIO". Somando o art. 24, IV da Lei 8.666/93
# — o mesmo instituto na lei anterior, vivo em 514 linhas do acervo — são 1.001 e R$ 2,80 bi.
#
# O caso que revelou: a AGILE CORP × SEEDUC tem contratos emergenciais em 2023 sob a 8.666 e em
# 2024 sob a 14.133. Régua presa a uma redação enxerga metade da cadeia.
#
# `\D{0,4}` entre o artigo e o inciso absorve a pontuação irregular do espelho ("Art. 75º, VIII",
# "Art. 75. VIII", "art.24, inciso IV"). Os OUTROS incisos ficam de fora de propósito: o inciso II
# é dispensa por VALOR e tem régua própria; misturá-los devolveria a confusão que este módulo
# existe para desfazer.
_RE_ENQ_EMERGENCIA = re.compile(
    r"(?:art\.?\s*)?75\D{0,6}VIII"                      # Lei 14.133/2021, art. 75, VIII
    r"|(?:art\.?\s*)?24\D{0,10}IV(?![IVX])",             # Lei 8.666/93, art. 24, IV
    re.IGNORECASE)

RESSALVA = ("indício a apurar, não afirmação de irregularidade: a dispensa emergencial é "
            "legal (art. 75, VIII); o que se mede aqui é a RECORRÊNCIA, que o inciso não "
            "prevê — imprevisibilidade não se repete todo exercício")


def eh_emergencial(objeto: str | None, enquadramento: str | None = None) -> bool:
    """A contratação é dispensa EMERGENCIAL — pelo objeto ou pelo dispositivo invocado?

    `enquadramento` é opcional para não quebrar o chamador antigo, mas quem tem a coluna deve
    passá-la: ela é a prova documental, e o texto do objeto é só o indício de linguagem.
    """
    if _RE_EMERGENCIA.search(str(objeto or "")):
        return True
    return bool(_RE_ENQ_EMERGENCIA.search(str(enquadramento or "")))


def agrupar_emergencias(linhas, *, minimo: int = 5) -> list[dict]:
    """Agrupa contratações EMERGENCIAIS por unidade × exercício.

    `linhas` = iterável de `(unidade, exercicio, fornecedor, valor, objeto)` ou, melhor, de
    `(unidade, exercicio, fornecedor, valor, objeto, enquadramento_legal)` — com o enquadramento,
    a régua alcança as 891 dispensas emergenciais cujo objeto não diz "emergencial".
    `minimo` = quantas emergências no mesmo exercício para o grupo virar indício. Uma
    emergência isolada é o uso legítimo do inciso; o padrão é o que interessa.

    Cada grupo traz o fornecedor DOMINANTE e a concentração nele: repetir emergência sempre
    com o mesmo contratado é fuga à licitação, enquanto emergências pulverizadas entre muitos
    fornecedores sugerem um serviço realmente sob pressão.
    """
    grupos: dict[tuple, dict] = {}
    for linha in linhas or []:
        unidade, exercicio, fornecedor, valor, objeto = linha[:5]
        enq = linha[5] if len(linha) > 5 else None
        if not eh_emergencial(objeto, enq):
            continue
        chave = (str(unidade or "?"), exercicio)
        g = grupos.setdefault(chave, {"unidade": chave[0], "exercicio": exercicio, "n": 0,
                                      "total": 0.0, "_por_forn": collections.Counter()})
        g["n"] += 1
        g["total"] += float(valor or 0)
        g["_por_forn"][str(fornecedor or "?")] += float(valor or 0)

    saida = []
    for g in grupos.values():
        if g["n"] < minimo:
            continue
        por_forn = g.pop("_por_forn")
        dominante, valor_dom = por_forn.most_common(1)[0]
        g["fornecedor_dominante"] = dominante
        g["n_fornecedores"] = len(por_forn)
        g["concentracao_dominante"] = round(valor_dom / g["total"], 4) if g["total"] else 0.0
        g["ressalva"] = RESSALVA
        saida.append(g)
    saida.sort(key=lambda g: -g["total"])
    return saida


# Empresa aberta há menos disto, concentrando emergência, é indício a APURAR — nunca prova.
# O mercado tem entrantes legítimos, e "nova" não é sinônimo de fachada; o que pesa é a
# combinação com a concentração e com o volume.
_ANOS_RECENTE = 5
_CONCENTRACAO_ALTA = 0.80


def sinais_do_dominante(grupo: dict, cadastro: dict | None) -> dict:
    """`{"sinais": [...], "lacunas": [...]}` sobre o fornecedor que concentra a emergência.

    A separação entre as duas listas é o ponto: **sinal** é o que sabemos sobre a empresa;
    **lacuna** é o que NÓS não temos. Ausência no cadastro não diz nada sobre o contratado —
    diz que o enriquecimento não chegou nele. Confundir as duas coisas transformaria buraco de
    dado em acusação, que é o erro que esta casa persegue (INDISPONÍVEL ≠ irregular).

    Medido em 2026-07-28, entre os dominantes dos 28 grupos: BRASVIP (aberta em 2020) com 92%
    de R$ 60,9 mi no DER-RJ; UP MED (2020) com 45% de R$ 120,1 mi no HU/UERJ; e quatro
    dominantes — entre eles a AGILE CORP, com 100% de R$ 159,7 mi — simplesmente ausentes do
    cadastro local.
    """
    import datetime

    sinais: list[str] = []
    lacunas: list[str] = []
    conc = float(grupo.get("concentracao_dominante") or 0)
    nome = str(grupo.get("fornecedor_dominante") or "?")

    if conc >= 0.999:
        sinais.append(f"concentração INTEGRAL (100%) da emergência em {nome}: nenhum outro "
                      "contratado no exercício")
    elif conc >= _CONCENTRACAO_ALTA:
        sinais.append(f"concentração de {conc:.0%} em {nome}")

    if not cadastro:
        lacunas.append(f"{nome} não consta no cadastro local — enriquecimento pendente; "
                       "ausência de dado NÃO é sinal contra a empresa")
        return {"sinais": sinais, "lacunas": lacunas}

    situacao = str(cadastro.get("situacao") or "").strip().upper()
    if situacao and situacao not in ("ATIVA",):
        sinais.append(f"situação cadastral {situacao} (irregular para contratar, a apurar na data "
                      "dos fatos — empresa pode ter sido baixada DEPOIS)")
    elif not situacao:
        lacunas.append("situação cadastral desconhecida")

    bruto = str(cadastro.get("data_abertura") or "").strip()
    try:
        abertura = datetime.date.fromisoformat(bruto[:10])
    except ValueError:
        lacunas.append(f"data de abertura ilegível ({bruto!r}) — idade da empresa não avaliada")
        abertura = None
    if abertura is not None:
        exercicio = int(grupo.get("exercicio") or abertura.year)
        idade = exercicio - abertura.year
        if idade <= _ANOS_RECENTE:
            sinais.append(f"empresa RECENTE: aberta em {abertura.isoformat()}, {idade} ano(s) antes "
                          f"do exercício {exercicio} — indício a apurar, não prova")
    return {"sinais": sinais, "lacunas": lacunas}
