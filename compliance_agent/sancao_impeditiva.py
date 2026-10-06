# -*- coding: utf-8 -*-
"""FONTE ÚNICA do que é sanção IMPEDITIVA de contratar — e do que não é.

POR QUE EXISTE. Nem toda sanção impede contratar. **Multa** do CNEP e **publicação extraordinária
da decisão condenatória** (Lei 12.846/2013, art. 6º) são penalidades reais que **não vedam** a
contratação; impedem quem as sofreu de pagar, não de contratar. Tratar as duas como impeditivas
transforma penalidade cumprida em acusação de contratação irregular.

Medido em 2026-08-10 nos 60 casamentos favorecido × sanção **vigentes à época** do detector de
emendas: **10 (16,7%) não eram impeditivos** — 5 multas e 5 publicações extraordinárias. Saíam com
o mesmo risco 9 dos 32 impedimentos e das 5 inidoneidades.

A regra já existia CERTA em `nucleo/adaptador_db._tem_sancao_vigente` e em
`cruzamentos_intel._SQL_IMPEDITIVA` — duas cópias idênticas em SQL, ainda não divergidas. Este
módulo é o lugar de as duas apontarem antes que divirjam, como `limites_aditivo` fez com o teto do
art. 125 (que estava em cinco cópias, com valores diferentes, dentro de detectores de risco alto).

O QUE ESTE MÓDULO **NÃO** DECIDE. O ALCANCE da vedação — se atinge o órgão sancionador, o ente
federativo ou toda a Administração — é outra pergunta, e mora em `sancao_abrangencia`. Aqui só se
responde *"esta categoria veda contratar?"*.

E a VIGÊNCIA é uma terceira pergunta, igualmente obrigatória: sanção impeditiva que começou depois
do ato não macula o ato (ver `situacao-cadastral-vigencia-na-data`, e os 87,9% de anacronismo
medidos no mesmo dia). Impeditiva **e** vigente na data — as duas, sempre.
"""
from __future__ import annotations

# Os cinco radicais que a casa usa desde sempre, agora num lugar só. Radical, não palavra inteira:
# a fonte escreve "Impedimento", "impedida", "Suspensão", "suspensao", "Inidoneidade", "inidônea",
# "proibição", "Declaração de Inidoneidade" — e o acento é inconstante entre CEIS e CNEP.
RADICAIS_IMPEDITIVOS: tuple[str, ...] = ("imped", "suspens", "inid", "proib", "declara")

# Fragmento SQL equivalente, para quem filtra no banco. Mantido AQUI para não voltar a existir em
# duas cópias soltas; quem consome deve importar, nunca reescrever.
SQL_IMPEDITIVA: str = "(" + " OR ".join(
    f"lower(categoria) LIKE '%{r}%'" for r in RADICAIS_IMPEDITIVOS) + ")"


def e_impeditiva(categoria: str | None) -> bool:
    """A categoria da sanção veda CONTRATAR?

    Categoria vazia/desconhecida devolve ``False`` — e isso é deliberado: sem saber qual é a
    sanção, a casa não afirma que ela impede. Quem precisa tratar o desconhecido de outro jeito
    declara a lacuna, em vez de presumir gravidade.
    """
    cat = str(categoria or "").lower()
    return any(r in cat for r in RADICAIS_IMPEDITIVOS)
