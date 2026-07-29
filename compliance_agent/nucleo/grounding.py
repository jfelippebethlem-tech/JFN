# -*- coding: utf-8 -*-
"""Âncora de citação — o trecho citado existe MESMO na fonte?

POR QUE ESTE MÓDULO EXISTE. Todo prompt de julgamento da casa exige "trecho literal", e quase
todo consumidor confere apenas que a string não está vazia. `direcionamento_cerebro` aceita
qualquer texto em `exigencias_restritivas[].trecho`; `narrativa_certame` descarta a dimensão sem
citação, mas não confere a citação que veio; `enxame/lentes` guarda a citação sem olhar. O único
ponto do repositório que confere de verdade é `editais/motivo_inabilitacao.py:134`
(`trecho[:40].lower() in motivo.lower()`), e é dele que este módulo nasce.

POR QUE `in` NÃO BASTA. O texto da casa vem de OCR de PDF do SEI. A mesma frase aparece com
hifenização de fim de linha ("capaci-\\ndade"), espaços múltiplos, quebras no meio, acentuação
perdida, aspas curvas e travessão tipográfico. Um `in` cru reprova citação legítima — e um
detector que reprova o achado verdadeiro é tão ruim quanto o que aceita o falso.

ONDE ESTÁ A LINHA. Tolerar ruído de OCR, sim; tolerar PARÁFRASE, não. Paráfrase com as mesmas
palavras-chave é exatamente o que o gate existe para pegar: o modelo "lembra" do documento e
escreve algo plausível que ninguém disse. O limiar padrão foi posto onde a troca de uma
preposição passa e a reescrita da frase não.
"""
from __future__ import annotations

import difflib
import re
import unicodedata
from typing import Any

# Abaixo disto, a "citação" casa com qualquer texto e não prova nada.
MIN_CARACTERES = 12
# Similaridade mínima na janela. 0.82 separa cópia-com-ruído de paráfrase — calibrado nos casos
# de `tests/test_grounding.py`, que são as formas reais do OCR do SEI.
LIMIAR_PADRAO = 0.82

_TRAVESSOES = {"–": "-", "—": "-", "‒": "-", "−": "-"}
_ASPAS = {"“": '"', "”": '"', "„": '"', "‟": '"', "’": "'", "‘": "'", "«": '"', "»": '"'}


def normalizar(texto: Any) -> str:
    """Forma canônica para comparação: sem acento, sem hífen de quebra, espaço único, minúsculo.

    A ordem importa: a hifenização é desfeita ANTES de colapsar o espaço em branco, senão
    "capaci-\\ndade" vira "capaci- dade" e o hífen deixa de ser reconhecível como quebra.
    """
    if not isinstance(texto, str):
        return ""
    t = texto
    for de, para in {**_TRAVESSOES, **_ASPAS}.items():
        t = t.replace(de, para)
    t = re.sub(r"-\s*\n\s*", "", t)          # hifenização de fim de linha do OCR
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode()
    t = re.sub(r"\s+", " ", t)
    return t.strip().lower()


def _mapa_de_offsets(original: str) -> tuple[str, list[int]]:
    """Normaliza guardando, para cada caractere normalizado, seu índice no texto ORIGINAL.

    Sem isso não dá para devolver o trecho como ele aparece na fonte — e é o texto da FONTE que
    vai para a peça, não o que o modelo digitou.
    """
    norm_chars: list[str] = []
    offsets: list[int] = []
    i, n = 0, len(original)
    ultimo_espaco = True
    while i < n:
        c = original[i]
        # hífen de quebra: consome o hífen e o branco que o segue
        if c == "-" and re.match(r"-\s*\n", original[i:]):
            j = i + 1
            while j < n and original[j].isspace():
                j += 1
            i = j
            continue
        if c.isspace():
            if not ultimo_espaco:
                norm_chars.append(" ")
                offsets.append(i)
                ultimo_espaco = True
            i += 1
            continue
        ultimo_espaco = False
        c = _TRAVESSOES.get(c, _ASPAS.get(c, c))
        sem_acento = unicodedata.normalize("NFKD", c).encode("ascii", "ignore").decode()
        for ch in (sem_acento or ""):
            norm_chars.append(ch.lower())
            offsets.append(i)
        i += 1
    return "".join(norm_chars).strip(), offsets[:len("".join(norm_chars).strip())]


def ancorar(trecho: Any, fonte: Any, *, limiar: float = LIMIAR_PADRAO,
            min_caracteres: int = MIN_CARACTERES) -> dict:
    """O trecho está na fonte? Devolve `{ancorado, similaridade, offset, trecho_na_fonte, ...}`.

    Nunca levanta: entrada estranha devolve `ancorado=False`. Um erro de tipo aqui não pode
    derrubar a geração de um parecer — mas também não pode virar "ancorado" por omissão.
    """
    base = {"ancorado": False, "similaridade": 0.0, "offset": -1, "trecho_na_fonte": "",
            "limiar": float(limiar), "motivo": ""}
    if not isinstance(trecho, str) or not isinstance(fonte, str):
        return {**base, "motivo": "entrada não textual"}

    alvo = normalizar(trecho)
    if len(alvo) < min_caracteres:
        return {**base, "motivo": f"citação curta demais (<{min_caracteres} caracteres)"}

    corpo, offsets = _mapa_de_offsets(fonte)
    if not corpo:
        return {**base, "motivo": "fonte vazia"}
    if len(alvo) > len(corpo):
        return {**base, "motivo": "citação maior que a fonte"}

    # 1) caminho barato: casamento exato depois de normalizar (cobre a maioria)
    pos = corpo.find(alvo)
    if pos >= 0:
        ini = offsets[pos] if pos < len(offsets) else 0
        fim = offsets[min(pos + len(alvo), len(offsets)) - 1] + 1
        return {**base, "ancorado": True, "similaridade": 1.0, "offset": ini,
                "trecho_na_fonte": fonte[ini:fim], "motivo": "casamento exato (normalizado)"}

    # 2) janela deslizante do tamanho do alvo — pega troca de palavra e ruído de OCR
    melhor_r, melhor_pos = 0.0, -1
    passo = max(1, len(alvo) // 8)
    matcher = difflib.SequenceMatcher(autojunk=False)
    matcher.set_seq2(alvo)
    for p in range(0, len(corpo) - len(alvo) + 1, passo):
        janela = corpo[p:p + len(alvo)]
        matcher.set_seq1(janela)
        # `real_quick_ratio` e `quick_ratio` são tetos baratos: se nem eles passam do melhor
        # já visto, a razão completa (cara) não vai passar.
        if matcher.real_quick_ratio() < melhor_r or matcher.quick_ratio() < melhor_r:
            continue
        r = matcher.ratio()
        if r > melhor_r:
            melhor_r, melhor_pos = r, p

    if melhor_r >= limiar and melhor_pos >= 0:
        ini = offsets[melhor_pos] if melhor_pos < len(offsets) else 0
        fim_idx = min(melhor_pos + len(alvo), len(offsets)) - 1
        fim = offsets[fim_idx] + 1 if fim_idx >= 0 else ini
        return {**base, "ancorado": True, "similaridade": round(melhor_r, 4), "offset": ini,
                "trecho_na_fonte": fonte[ini:fim],
                "motivo": f"casamento aproximado ({melhor_r:.2f} ≥ {limiar:.2f})"}

    return {**base, "similaridade": round(melhor_r, 4),
            "motivo": f"melhor similaridade {melhor_r:.2f} < limiar {limiar:.2f} — "
                      "provável paráfrase, não citação"}


def ancorar_muitos(trechos: list[Any], fonte: Any, **kw) -> dict:
    """Ancora uma lista e resume. `taxa_alucinacao` é a métrica que interessa medir no tempo."""
    resultados = [ancorar(t, fonte, **kw) for t in (trechos or [])]
    n = len(resultados) or 1
    ancorados = [r for r in resultados if r["ancorado"]]
    return {"n": len(resultados), "ancorados": len(ancorados),
            "taxa_alucinacao": 1 - len(ancorados) / n, "resultados": resultados}
