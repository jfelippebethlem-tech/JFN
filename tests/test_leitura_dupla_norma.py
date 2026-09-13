# -*- coding: utf-8 -*-
"""`art. 82` DE QUAL LEI?

Medido em 2026-08-15: dos **1.799** processos em que a régua extrai `dispositivo`, **100%** trazem
só `art. N` — nenhum traz a norma. A LLM, do outro lado, responde `Art. 149 da Lei nº 14.133/2021`.
Comparar os dois não mede discordância entre leitores: mede a ausência da lei num dos lados. `art.
82` da Lei 14.133 e `art. 82` da Lei estadual 287/79 são coisas distintas.

Por isso `dispositivo` é a 2ª maior categoria de `discordam` (465 linhas), e em **425 delas (91,4%)**
a LLM já nomeia a norma — a informação existe, faltava do lado da régua.

Campo NOVO, não mudança de formato: `comparar()` itera sobre `_FATOS`, não sobre `_PADROES`, então
`norma` é aditivo e não toca `_mesmo_dispositivo`, o placar nem o `--recomparar`. Trocar `art. 90`
por `Lei 287/79, art. 90` mexeria nos três de uma vez.
"""
from __future__ import annotations

from tools.sei_leitura_dupla import extrair_deterministico


def _norma(texto: str) -> str:
    return (extrair_deterministico(texto, ano_proc=2024).get("norma") or {}).get("valor") or ""


def test_norma_sai_junto_do_artigo_no_formulario():
    """O caso mais limpo do acervo: o formulário põe a LEI antes do artigo, em outra linha."""
    d = extrair_deterministico("Enquadramento Legal:\nLei n 14.133/2021, Art. 75, VIII", ano_proc=2024)
    assert (d["norma"]["valor"]) == "Lei n 14.133/2021"
    assert (d["dispositivo"]["valor"]) == "art. 75, VIII", "o campo antigo NÃO pode mudar de formato"


def test_norma_do_TAC_estadual():
    assert _norma("com fundamento nos arts. 90, 91 e 92 da Lei nº 287/79, autorizo") == "Lei nº 287/79"


def test_rodape_da_assinatura_NAO_e_norma():
    """Sem esta defesa o `Decreto nº 48.209` respondia por 239 das 347 normas colhidas numa amostra
    de 387 processos (69%) — o SEI carimba esse rodapé em TODO documento assinado."""
    assert _norma("Documento assinado eletronicamente por Fulano, com fundamento "
                  "nos art. 28 e 29 do Decreto nº 48.209") == ""


def test_norma_tributaria_da_retencao_NAO_e_norma_da_despesa():
    assert _norma("FUNDAMENTAÇÃO LEGAL: Art. 2º-A da Instrução Normativa RFB nº 1234") == ""
