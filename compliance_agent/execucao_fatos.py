# -*- coding: utf-8 -*-
"""Ponte TEXTO → FATOS para os detectores da fase de execução (plano #4, itens 2.1 e 2.2).

Ao executar o plano descobriu-se que a regra jurídica **já existe e está madura** no projeto:
  • `detectores/x1_crescimento_aditivo.py` — teto do art. 125 (25% / 50% reforma), reajuste e aditivo de
    só-prazo fora do teto, aditivo precoce, rubricas de justificativa/pertinência;
  • `detectores/x3_execucao_financeira.py` — pagamento ANTES do atesto, tríade comprimida, dezembro, fila;
  • `detectores/p4_fracionamento.py` + `limites_dispensa.py` — fracionamento por grupo de objeto.
Reescrever isso seria duplicar doutrina (e divergir dela na primeira manutenção). O que FALTAVA era a
ponte: alguém que leia o processo SEI e produza `{valor_inicial, aditivos[]}` e `{pagamentos[]}` — sem
eles os detectores respondem `nao_avaliavel` para sempre.

**Nenhum limiar legal mora aqui.** Este módulo só EXTRAI e CLASSIFICA o fato, com o trecho literal que o
sustenta. Quem julga é o detector.

HONESTIDADE: dado ausente → `None`/`[]` (nunca 0 — INDISPONÍVEL ≠ zero); §2 — sem Ordem Bancária não há
`data_pagamento` (empenho é compromisso, não pagamento), logo não se acusa antecipação do que não foi pago.
"""
from __future__ import annotations

from datetime import date

import re

_RE_VALOR = re.compile(r"R\$\s*([\d.]+,\d{2})")
_RE_DATA = re.compile(r"\b(\d{2})/(\d{2})/(\d{4})\b")
_RE_PERC = re.compile(r"(\d{1,3}(?:,\d+)?)\s*%")

# marcadores de cada natureza de aditivo. ORDEM IMPORTA: reajuste e prazo são testados ANTES de
# acréscimo, porque "reajuste ... no valor de R$" e "prorrogação ... sem acréscimo de valor" citam valor
# e seriam classificados como acréscimo quantitativo (o falso positivo clássico da família).
_NATUREZA = (
    ("reajuste", r"reajust|repactua|reequil[íi]brio|revis[ãa]o\s+de\s+pre[çc]|corre[çc][ãa]o\s+monet|"
                 r"\bIPCA\b|\bINCC\b|\bIGP-?M\b"),
    ("prazo", r"prorroga|prazo\s+de\s+vig[êe]ncia|dilata[çc][ãa]o\s+de\s+prazo"),
    ("valor", r"acr[ée]scim|acrescer|supress[ãa]o|suprimir|aditamento\s+de\s+valor|majora|"
              r"altera[çc][ãa]o\s+quantitativ"),
)
_RE_ADITIVO = re.compile(
    r"(primeiro|segundo|terceiro|quarto|quinto|sexto|s[ée]timo|oitavo|nono|d[ée]cimo|\d+[ºo°]?)?\s*"
    r"termo\s+aditivo", re.I)
_RE_VALOR_INICIAL = re.compile(
    r"valor\s+(?:inicial|original|global\s+inicial|do\s+contrato)\s*(?:de|:)?\s*R\$\s*([\d.]+,\d{2})", re.I)
_RE_SUPRESSAO = re.compile(r"supress[ãa]o|suprimir", re.I)
# tipo de objeto que muda o teto do art.125 (quem aplica é o X1 — aqui só se classifica o objeto)
_RE_REFORMA = re.compile(r"reforma\s+(?:de\s+)?(?:edif[íi]cio|pr[ée]dio|im[óo]vel|equipamento|cobertura)|"
                         r"reforma\s+d[ao]\s", re.I)


def valor_br(s: str) -> float | None:
    """'R$ 1.234.567,89' → 1234567.89. Sem valor no texto → None (nunca 0.0: ausência ≠ zero)."""
    m = _RE_VALOR.search(s or "")
    if not m:
        return None
    return float(m.group(1).replace(".", "").replace(",", "."))


def _data_iso(s: str) -> str | None:
    m = _RE_DATA.search(s or "")
    if not m:
        return None
    d, mth, y = m.groups()
    return f"{y}-{mth}-{d}"


def _sentencas(texto: str) -> list[str]:
    return [t.strip() for t in re.split(r"(?<=[.;])\s+", texto or "") if t.strip()]


# A DATA TEM DE ESTAR PERTO DO TERMO. `_sentencas` corta em ponto-e-vírgula, e num PDF de nota
# fiscal ou de detalhamento do SIAFE isso devolve blocos de página inteira: medido em 2026-08-04,
# as "frases" que davam a data do atesto tinham 780 e 506 caracteres e nenhuma data no formato
# dd/mm/aaaa — a data saía de outro canto do bloco, sem relação provada com a palavra "atesto",
# e o X3 anunciava "pago ANTES do atesto" com atesto 20 meses no futuro. A janela é o idioma que
# a casa já usa em `instrumento_assinatura._identificador` (160 chars): o dado que qualifica um
# termo mora ao lado dele, não em qualquer lugar da página.
_JANELA_MARCO = 160


_RE_QUALQUER_VALOR = re.compile(r"R\$\s*([\d.]{1,18},\d{2})")


def _num(s: str) -> float:
    return float(s.replace(".", "").replace(",", "."))


# QUEM DECLARA O VALOR, E COM QUE FORÇA. O padrão antigo era um só e pegava a PRIMEIRA ocorrência
# num monte de dezenas de documentos — no SEI-070002/001289/2022 colheu "VALOR DO CONTRATO:
# R$ 46.866,00" de uma *Publicação Errata 01* e o X1 anunciou acréscimo de 10.024%. O contrato é
# de R$ 105.988.095,41, declarado dezesseis vezes nos autos com fórmulas que o padrão não
# alcançava: "O valor total do presente Contrato é de", "com valor inicial contratual de" e o
# par "Valor Original / Valor Total" das telas do SIAFE.
#
# Ordem = FORÇA DA DECLARAÇÃO, não posição no texto. A cláusula do contrato e a justificativa do
# aditivo dizem o valor do contrato; um "VALOR DO CONTRATO:" solto numa errata de edital diz o
# valor de um item. Dentro da mesma força, vence o mais repetido — e aí a frequência é legítima,
# porque compara declarações do MESMO tipo (a lição do G2 foi não adivinhar entre coisas
# diferentes). (2026-08-04)
_PADROES_VALOR_INICIAL = (
    re.compile(r"valor\s+(?:total\s+)?(?:inicial\s+)?contratual\s*(?:de|:)?\s*R\$\s*([\d.]+,\d{2})", re.I),
    re.compile(r"valor\s+total\s+do\s+presente\s+contrato\s*(?:é\s*)?(?:de|:)?\s*R\$\s*([\d.]+,\d{2})", re.I),
    re.compile(r"valor\s+original\s*[\s\S]{0,40}?R\$\s*([\d.]+,\d{2})", re.I),
    re.compile(r"valor\s+(?:inicial|global\s+inicial)\s*(?:de|:)?\s*R\$\s*([\d.]+,\d{2})", re.I),
    _RE_VALOR_INICIAL,          # o mais fraco: "valor do contrato" solto (pegou a errata)
)


def extrair_valor_inicial(texto: str) -> float | None:
    """Valor inicial do contrato (a base do teto do art. 125). Ausente → None.

    Escolhe pela FORÇA da declaração (ver `_PADROES_VALOR_INICIAL`) e, dentro da mesma força,
    pelo valor mais repetido nos autos.
    """
    from collections import Counter
    for rx in _PADROES_VALOR_INICIAL:
        achados = Counter(_num(m.group(1)) for m in rx.finditer(texto or ""))
        if achados:
            # mais repetido; empate desfeito pelo maior (o valor do contrato, não o de um item)
            return max(achados.items(), key=lambda kv: (kv[1], kv[0]))[0]
    return None


def base_contraditada(texto: str, base: float | None, acrescimos: float) -> float | None:
    """Existe, NO MESMO texto, um valor de contrato que desmente a base extraída?

    Por que existe (medido em 2026-08-04). `extrair_valor_inicial` devolve a PRIMEIRA ocorrência
    do padrão num monte de dezenas de documentos concatenados, sem noção de qual deles é o
    contrato. No SEI-070002/001289/2022 ela colheu **R$ 46.866,00 de uma "Publicação Errata 01"**
    e o X1 anunciou acréscimo de **10.024%**; o contrato é o 38/2023, de R$ 105.988.095,41,
    declarado seis vezes nos autos, e o aditivo de R$ 4.697.858,84 é **4,4%** — dentro do teto.
    Não havia achado nenhum, e o processo liderava a fila de risco.

    A refutação NÃO é um limiar arbitrário: é o próprio processo dizendo outro número. Se algum
    valor declarado no texto torna o acréscimo compatível com o teto legal, a base extraída está
    contradita pelos autos e o X1 não pode afirmar estouro sobre ela. Devolve o candidato que
    desmente (o menor que basta), ou None quando nada no texto contradiz.

    Nota de método: a casa já se queimou "adivinhando o dono por frequência" no G2. Aqui não se
    adivinha — declara-se contradição e o detector devolve `nao_avaliavel`, que é o honesto
    quando duas leituras do mesmo processo não fecham.
    """
    if not base or base <= 0 or acrescimos <= 0:
        return None
    if acrescimos / base <= 1.0:           # dentro do plausível: nada a contraditar
        return None
    candidatos = sorted({_num(m) for m in _RE_QUALQUER_VALOR.findall(texto or "")})
    for v in candidatos:
        if v > base and acrescimos / v <= 0.25:
            return v
    # Segunda forma da contradição, medida em 070002/004135/2025: o "acréscimo" (R$ 103,9 mi)
    # é MAIOR que o maior valor declarado em todo o processo (R$ 87,1 mi). Nada nos autos é
    # grande o bastante para ser o contrato que cresceu tanto — o que se somou não são aditivos
    # de um mesmo contrato. Devolve o maior declarado, que é o que desmente a base.
    if candidatos and acrescimos > candidatos[-1] > base:
        return candidatos[-1]
    return None


# "prorrogação do prazo SEM RENÚNCIA DE REAJUSTE" é ressalva, não natureza: a palavra "reajuste" classificava a
# prorrogação como recomposição (Contrato INEA 34/2023, aditivos 71/2024 e 80/2025, lidos em 25/09/2026).
_RE_RESSALVA_REAJUSTE = re.compile(r"sem\s+ren[úu]ncia\s+(?:a[oa]?|de|do|ao\s+direito\s+de)\s+reajust\w*", re.I)


def _natureza(frase: str) -> str:
    frase = _RE_RESSALVA_REAJUSTE.sub(" ", frase or "")
    for nome, pat in _NATUREZA:
        if re.search(pat, frase, re.I):
            return nome
    return ""


# ── aditivo lido POR DOCUMENTO ──────────────────────────────────────────────────────────────────────────
# `extrair_aditivos` lê FRASES da concatenação dos documentos — e a página coletiva do D.O. traz aditivos de
# OUTROS contratos (INEA 34/2023 recebeu o 06/2023 da Dimensional e um do HUPE), e o valor mora noutra frase
# ("Dá-se ao termo aditivo o valor de R$ …") que não cita "termo aditivo" de novo — os 4 aditivos do INEA 34/2023
# saíam SEM valor. Aqui cada Termo Aditivo é o próprio documento: natureza pela cláusula de OBJETO, valor e total
# pelas cláusulas de valor. Não substitui `extrair_aditivos` (o X1 continua nele).
_RE_T_ADITIVO = re.compile(r"^\s*termo\s+aditivo|^\s*\d+[ºo°]?\s*termo\s+aditivo", re.I)
_RE_OBJETO_AD = re.compile(r"(?:constitui\s+objeto\s+do\s+presente\s+instrumento|tem\s+por\s+objeto)\s+(.{0,260})",
                           re.I | re.S)
_RE_VALOR_AD = re.compile(r"d[áa]-se\s+ao\s+termo\s+aditivo\s+o\s+valor\s+de\s+R\$\s*([\d.]+,\d{2})", re.I)
_RE_TOTAL_AD = re.compile(r"totalizando\s+o\s+contrato\s+o\s+valor\s+(?:de\s+)?R\$\s*([\d.]+,\d{2})", re.I)
_RE_NUM_AD = re.compile(r"termo\s+aditivo\s+n?[º°o.]*\s*(\d{1,4}/\d{4})", re.I)
_RE_CONTRATO_AD = re.compile(r"aditivo\s+ao\s+contrato\s+(?:[A-Z]{2,8}\s+)?n?[º°o.]*\s*(\d{1,4}/\d{4})", re.I)


# o próprio aditivo ENQUADRA o objeto como contínuo ("prestação de serviços contínuos de …") — medido em 25/09/2026:
# sem este corte a regra acendia em 65 de 213 processos (30%), quase todos serviço contínuo declarado.
_RE_CONTINUO = re.compile(r"servi[çc]os?\s+(?:de\s+natureza\s+)?cont[íi]nu|natureza\s+continuad|regime\s+continuad|"
                          r"servi[çc]os?\s+continuados?", re.I)


def _moeda(v: float) -> str:
    return "R$ " + f"{float(v or 0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _br(v: str) -> float:
    return float(v.replace(".", "").replace(",", "."))


def aditivos_por_documento(docs: list[dict]) -> list[dict]:
    """[{titulo, numero, contrato, tipo, valor, total_apos}] — um por documento-aditivo (não extrato/publicação)."""
    out = []
    for d in docs or []:
        t = str(d.get("titulo") or "")
        if not _RE_T_ADITIVO.search(t):
            continue
        x = str(d.get("texto") or "")
        m = _RE_OBJETO_AD.search(x)
        objeto = re.sub(r"\s+", " ", m.group(1)) if m else ""
        tipo = _natureza(objeto) or _natureza(x[:1500])
        mv, mt = _RE_VALOR_AD.search(x), _RE_TOTAL_AD.search(x)
        mn, mc = _RE_NUM_AD.search(x) or _RE_NUM_AD.search(t), _RE_CONTRATO_AD.search(x[:2000])
        out.append({"titulo": t, "numero": mn.group(1) if mn else None, "contrato": mc.group(1) if mc else None,
                    "tipo": tipo, "valor": _br(mv.group(1)) if mv else None,
                    "total_apos": _br(mt.group(1)) if mt else None, "objeto": objeto[:200],
                    "declara_continuo": bool(_RE_CONTINUO.search(x))})
    return out


# natureza TIPICAMENTE contínua, mesmo sem a palavra "contínuo" no texto (SEGOV 001/2020: locação de 165
# motocicletas com manutenção — contínuo por natureza). O que sobra fora daqui e sem declaração é juízo.
_RE_CONTINUO_TIPICO = re.compile(
    r"loca[çc][ãa]o,?\s+(?:com\s+manuten[çc][ãa]o,?\s+)?de\s+(?:\d+\s*\(?[^)]*\)?\s*)?(?:ve[íi]culos|motocicletas|"
    r"equipamentos|impressoras|m[áa]quinas|im[óo]ve)|vigil[âa]ncia|limpeza\s+(?:e\s+conserva|predial|hospitalar)|"
    r"conserva[çc][ãa]o\s+predial|manuten[çc][ãa]o\s+(?:predial|preventiva|corretiva)|portaria|copeiragem|"
    r"recep[çc][ãa]o|apoio\s+administrativo|fornecimento\s+de\s+(?:refei|alimenta)|transporte\s+de\s+(?:pacientes|"
    r"servidores|alunos)|f[áa]brica\s+de\s+software|outsourcing", re.I)


def declara_continuo(docs: list[dict]) -> bool:
    """Contrato, TR, edital ou aditivo do processo enquadram o objeto como serviço contínuo (declarado ou típico)?"""
    return any(_RE_CONTINUO.search(str(d.get("texto") or "")) or _RE_CONTINUO_TIPICO.search(str(d.get("texto") or ""))
               for d in docs or [] if re.search(r"contrato|termo\s+de\s+refer|edital|projeto\s+b[áa]sico|aditivo",
                                                str(d.get("titulo") or ""), re.I))


def prorrogacao_renova_valor(aditivos: list[dict], *, continuo_nos_autos: bool = False) -> dict:
    """Prorrogação que RENOVA o valor anual e multiplica o contrato — só é lícita em serviço CONTÍNUO.

    Lei 8.666/1993, art. 57, II (e Lei 14.133/2021, arts. 106-107): prorrogar com novo valor pressupõe natureza
    continuada; em serviço de escopo definido é contratação nova sem licitação. Caso: INEA 34/2023 (Lytorânea),
    de R$ 48.491.100,00 a R$ 177.178.293,72 com duas prorrogações de R$ 57.011.710,08 e R$ 60.083.291,82.
    Veredito: 🟡 a conferir (a natureza contínua é questão jurídica que o texto do aditivo nem sempre declara)."""
    renov = [a for a in aditivos or [] if a.get("tipo") == "prazo" and (a.get("valor") or 0) > 0]
    totais = [a["total_apos"] for a in aditivos or [] if a.get("total_apos")]
    ac_valor = [a for a in aditivos or [] if a.get("tipo") == "valor" and a.get("valor") and a.get("total_apos")]
    inicial = None
    if ac_valor:                                   # 1º acréscimo: total − acréscimo = valor inicial (atualizado)
        a0 = min(ac_valor, key=lambda a: a["total_apos"])
        inicial = round(a0["total_apos"] - a0["valor"], 2)
    elif renov and renov[0].get("total_apos"):
        inicial = round(renov[0]["total_apos"] - renov[0]["valor"], 2)
    if not renov:
        return {"grau": "verde" if aditivos else "nao_aplicavel", "renovacoes": [], "multiplicador": None}
    final = max(totais) if totais else None
    mult = round(final / inicial, 2) if (final and inicial) else None
    relevante = bool((mult and mult >= 2) or sum(a["valor"] for a in renov) >= (inicial or 0) * 0.5)
    # declarado contínuo = enquadramento FORMAL correto: atributo (verde); se desassoreamento/obra é mesmo contínuo
    # é juízo — vai para a camada de parecer, não para a regra
    # basta UM aditivo da série enquadrar como contínuo: os posteriores costumam ter texto curto e não repetem
    # (SEGOV 007/2019: 9 aditivos em 7 anos, os 3 primeiros declaram, os últimos não)
    continuo = continuo_nos_autos or any(a.get("declara_continuo") for a in aditivos or [])
    grau = "amarelo" if relevante and not continuo else "verde"
    return {"grau": grau, "renovacoes": [{"titulo": a["titulo"], "valor": a["valor"], "total_apos": a["total_apos"]}
                                          for a in renov],
            "valor_inicial": inicial, "valor_final": final, "multiplicador": mult,
            "diz": (f"{len(renov)} prorrogação(ões) com valor novo somando {_moeda(sum(a['valor'] for a in renov))}"
                    + (f"; o contrato foi de {_moeda(inicial)} a {_moeda(final)} ({str(mult).replace('.', ',')}×)"
                       if mult else "")
                    + (". O aditivo declara serviço contínuo (enquadramento formal do art. 57, II)." if continuo else
                       ". O aditivo NÃO declara serviço contínuo — só é lícito se o objeto for de natureza continuada: "
                       "conferir a natureza e o parecer jurídico.")),
            "declara_continuo": continuo,
            "fundamento": "Lei 8.666/1993, art. 57, II · Lei 14.133/2021, arts. 106-107"}


def extrair_aditivos(texto: str) -> list[dict]:
    """Aditivos no formato que o X1 consome: [{data, tipo, valor, justificativa, trecho}].

    `tipo`: 'valor' (acréscimo/supressão — entra no teto) · 'prazo' (não entra) · 'reajuste' (recomposição,
    não entra). Supressão vem com valor NEGATIVO (o art. 125 as computa separadamente — quem separa é o X1).
    """
    out: list[dict] = []
    for frase in _sentencas(texto):
        if not _RE_ADITIVO.search(frase):
            continue
        nat = _natureza(frase)
        if not nat:
            continue
        valor = valor_br(frase)
        if nat == "prazo":
            valor = None                      # prorrogação: mesmo citando "sem acréscimo de valor"
        elif nat == "valor" and valor is not None and _RE_SUPRESSAO.search(frase):
            valor = -valor
        perc = _RE_PERC.search(frase)
        out.append({"data": _data_iso(frase), "tipo": nat, "valor": valor,
                    "percentual_citado": float(perc.group(1).replace(",", ".")) if perc else None,
                    "justificativa": frase, "trecho": frase[:400]})
    # O MESMO EVENTO, CONTADO DUAS VEZES. O texto que chega aqui é a CONCATENAÇÃO dos documentos
    # de contrato/aditivo do processo, e a mesma frase costuma aparecer em mais de um deles —
    # o despacho que relata o aditivo, a publicação que o extrata, o parecer que o cita. Medido em
    # 2026-08-05 no SEI-070002/001289/2022, o processo de MAIOR score do acervo (90,2): das 6
    # "recomposições" que sustentavam o X7 crítico, duas eram a MESMA frase — "Em 19/12/2025, foi
    # celebrado o 1º Termo Aditivo ao contrato, que promoveu o reequilíbrio econômico-financeiro"
    # — repetida em dois documentos. Contar o mesmo fato duas vezes infla a reiteração e pode
    # inventar a "dupla correção" do X7, que é justamente ver mais de uma recomposição no mesmo
    # exercício. A chave é (data, tipo, frase normalizada): eventos distintos com a mesma data
    # continuam distintos, porque a frase difere.
    vistos: set[tuple] = set()
    unicos: list[dict] = []
    for a in out:
        chave = (a["data"], a["tipo"], " ".join(str(a["justificativa"]).split())[:200])
        if chave in vistos:
            continue
        vistos.add(chave)
        unicos.append(a)
    return unicos


def contexto_x1(texto: str, *, tipo_objeto: str | None = None) -> dict:
    """Contexto pronto para `X1CrescimentoAditivo`. `tipo_objeto` explícito vence a inferência do texto
    (é ele que define o teto de 25% ou 50% — a decisão é do X1, o insumo é daqui)."""
    tipo = tipo_objeto or ("reforma" if _RE_REFORMA.search(texto or "") else None)
    return {"valor_inicial": extrair_valor_inicial(texto), "aditivos": extrair_aditivos(texto),
            "tipo_objeto": tipo, "fonte": "execucao_fatos (extração do texto do processo)",
            # o TEXTO vai junto para o detector poder conferir a própria base contra os autos
            # (ver `base_contraditada`) — a base sai da 1ª ocorrência num monte de documentos e
            # já foi colhida de uma errata, produzindo "acréscimo de 10.024%".
            "_texto_fonte": texto or ""}


# ───────────────────────────── X3: tríade da despesa × atesto ─────────────────────────────
_ETAPAS = (
    ("data_empenho", r"(?:nota\s+de\s+)?empenho[^.;]{0,80}?", r"20\d{2}NE\d+"),
    ("data_liquidacao", r"(?:nota\s+de\s+)?liquida[çc][ãa]o[^.;]{0,80}?", r"20\d{2}NL\d+"),
    ("data_pagamento", r"ordem\s+banc[áa]ria[^.;]{0,80}?", r"20\d{2}OB\d+"),
    ("data_atesto", r"atest[oa][^.;]{0,80}?", None),
)


def _data_da_etapa(texto: str, padrao: str, codigo: str | None,
                   *, exigir_codigo: bool = False) -> str | None:
    """Data da 1ª sentença que fala da etapa. Casa pelo termo OU pelo código do SIAFE (2024OB000789).

    `exigir_codigo` existe para o PAGAMENTO, e sai direto da regra-mãe da casa: só a Ordem
    Bancária é pagamento. Medido em 2026-08-04 nos 80 processos de maior risco: apenas **3**
    tinham o código de uma OB; **9** tinham só as palavras "ordem bancária" perdidas num bloco de
    OCR de nota fiscal ou de "Detalhamento de Empenho" — e era dessa data que o X3 dizia "pago
    ANTES do atesto", chamando de pagamento o que era EMPENHO. O código `2024OB000789` é o único
    marco que identifica uma OB sem ambiguidade; sem ele não se afirma que houve pagamento.
    """
    for frase in _sentencas(texto):
        casou = (re.search(codigo, frase, re.I) if (exigir_codigo and codigo)
                 else (re.search(padrao, frase, re.I) or (codigo and re.search(codigo, frase, re.I))))
        if casou:
            d = _data_iso(frase[max(0, casou.start() - _JANELA_MARCO):
                                casou.end() + _JANELA_MARCO])
            if d:
                return d
    return None


def extrair_pagamentos(texto: str) -> list[dict]:
    """Tríade empenho→liquidação→OB + data do atesto, no formato que o X3 consome.

    §2: `data_pagamento` só existe se houver ORDEM BANCÁRIA — empenho/liquidação não são pagamento.
    Devolve uma entrada por processo (o texto de um processo de pagamento traz um ciclo); vazio se não há
    nenhuma etapa identificável."""
    reg = {nome: _data_da_etapa(texto, pat, cod, exigir_codigo=(nome == "data_pagamento"))
           for nome, pat, cod in _ETAPAS}
    # ATESTO NÃO TEM DATA NO FUTURO. Ele certifica o que JÁ foi entregue; data posterior a hoje é,
    # por definição, outra coisa — validade de certidão, fim de vigência, cronograma. Medido em
    # 2026-08-05 nos 3 achados X3 do acervo, todos "pago ANTES do atesto": as datas de atesto eram
    # **2025-09-30, 2026-03-31 e 2026-09-30** — 14, 20 e 21 meses DEPOIS do pagamento, e a última
    # ainda no futuro em relação a hoje. Todas em fim de trimestre, que é a assinatura de validade
    # de CND, não de atesto.
    #
    # A janela de 160 caracteres (`_JANELA_MARCO`, 2026-08-04) reduziu esse erro mas não o
    # eliminou: dentro da janela ainda cabe a data errada. Esta guarda é de outra natureza e não
    # depende de distância no texto — é o calendário que decide.
    if reg.get("data_atesto") and reg["data_atesto"] > date.today().isoformat():
        reg["data_atesto"] = None
    if not any(reg.values()):
        return []
    reg["valor"] = valor_br(texto or "")
    reg["trecho"] = (texto or "")[:400]
    return [reg]


# A ATESTAÇÃO, AFIRMADA. O carimbo de praxe na nota fiscal — "ATESTAMOS QUE O MATERIAL FOI
# RECEBIDO EM CONDIÇÕES SATISFATÓRIAS" — é o atesto de verdade, e quase nunca traz data própria.
# Por isso a existência do atesto e a DATA dele são perguntas separadas: a segunda pode ser
# `nao_avaliavel` sem que a primeira o seja.
_RE_ATESTACAO_AFIRMADA = re.compile(
    r"atest(?:o|amos|a-se)\s+(?!a\s+ser)|atestad[oa]\s+(?:que|pel[ao])|"
    r"recebemos?\s+(?:definitiv|provisori)|termo\s+de\s+recebimento|"
    r"(?:material|servi[çc]os?|bens|objeto)\s+(?:foi|foram)\s+"
    r"(?:recebid|prestad|executad|entregu)|"
    # AS FÓRMULAS QUE A ADMINISTRAÇÃO USA DE VERDADE, e que a primeira versão perdia. Medido em
    # 2026-08-06 lendo os autos dos 118 disparos: o atesto de compra de material é o carimbo do
    # almoxarifado na própria nota — "Recebi, a contento, o(s) material(is) constante(s) desta
    # Nota Fiscal. Assinatura e Carimbo" — e o canhoto do DANFE, "Recebemos de <fornecedor> os
    # produtos/serviços constantes da Nota Fiscal". Acusar de "pagou sem atestar" quem tem canhoto
    # assinado é acusar o normal.
    r"receb(?:i|emos|ido)[,\s]+a\s+contento|"
    r"recebemos?\s+de\s+.{0,60}?\s+os\s+produtos", re.I)

# O RODAPÉ DO SEI NÃO É ATESTAÇÃO. "A autenticidade deste documento pode ser CONFERIDA no site
# sei.rj.gov.br" aparece em TODO documento assinado eletronicamente — é a prova da assinatura, não
# do recebimento. Não entra no vocabulário acima de propósito; fica aqui declarado para que a
# próxima ampliação não o inclua por engano.
_RUIDO_CONHECIDO = "autenticidade deste documento pode ser conferida"


def contexto_x3(texto: str) -> dict:
    """Contexto do `X3ExecucaoFinanceira` + o cruzamento que o dono pediu (pagamento ANTES do
    atesto) + a pergunta que faltava: **houve atestação?**

    `pagamento_anterior_ao_atesto` continua exigindo as DUAS datas — sem elas, `False`, nunca
    `True` por presunção.

    `atestacao_ausente` é a resposta à observação do dono em 2026-08-06: *"pagar algo sem
    atestação ou antes dela (antecipação de pagamento não pode) são irregularidades graves sim"*.
    Ele tem razão e a lei é dura — a antecipação é **vedada** (art. 5º da Lei 14.133/2021 e art. 38
    do Decreto 93.872/86) e a liquidação prévia é condição do pagamento (arts. 62 e 63 da Lei
    4.320/1964). Só que o motor ficava MUDO nesse caso: sem data de atesto ele devolvia `False` e
    nada mais, de modo que "paguei e não atestei" — a hipótese mais grave — não gerava sinal algum.
    Agora o fato é declarado; quem decide se ele pesa contra o processo é o gate de captura, como
    manda a casa (ausência sobre leitura parcial não é ausência).
    """
    pgs = extrair_pagamentos(texto)
    antes = any(p.get("data_pagamento") and p.get("data_atesto")
                and p["data_pagamento"] < p["data_atesto"] for p in pgs)
    tem_ob = any(p.get("data_pagamento") for p in pgs)
    tem_atestacao = bool(_RE_ATESTACAO_AFIRMADA.search(texto or ""))
    return {"pagamentos": pgs, "pagamento_anterior_ao_atesto": antes,
            "atestacao_ausente": bool(tem_ob and not tem_atestacao),
            "tem_atestacao": tem_atestacao, "tem_ordem_bancaria": tem_ob,
            "fonte": "execucao_fatos (extração do texto do processo)"}
