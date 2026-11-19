# Padrões de irregularidade — achado num processo vira varredura em TODOS

Dono, 18/11/2026: "sempre que achar uma irregularidade, aplique a todos os outros também pra saber".

## Ciclo
1. Perícia (agente, Lex, humano) acha um vício com prova primária num processo → **padrão** com id.
2. O padrão vira detector determinístico em `compliance_agent/padroes/<id>.py` + ficha `config/padroes/<id>.yaml`.
3. Detector roda no acervo inteiro (SEI `data/sei_arquivo/*` + `data/sei_cache/integra_*`, SIAFE, PNCP) →
   `data/padroes/<id>.json`.
4. Os achados são conferidos por amostra (os 5 primeiros e todos os que forem relatados) antes de ir ao painel;
   falso positivo vira regra + teste negativo. Achado conferido vira caso (vault/brain) e fila de perícia.

## Contrato de cada detector
```python
ID = "carona_aderente_vedado"           # == nome do arquivo
def varrer(limite: int | None = None) -> dict:
    """{"id": ID, "gerado_em": iso, "universo": N avaliados, "cobertura": {...o que não pôde ser avaliado...},
        "achados": [{"processo": "SEI-…", "grau": "forte|medio|fraco", "prova": "doc i — \"trecho literal\"",
                     "valor_pago_ob": float|None, "porque": "explicação inocente avaliada", "fonte": "…"}]}"""
```
Ficha `config/padroes/<id>.yaml`: `id, nome, origem (processo + caso do vault), norma, sinal, explicacoes_inocentes,
controle_positivo (processo onde o vício foi provado), controle_negativo (processo parecido e regular)`.
Teste obrigatório `tests/test_padrao_<id>.py`: controle positivo acende, negativo não.
Rodar todos: `nice -n 19 .venv/bin/python -m tools.padroes_varrer [--id X]`.

## Regras
Indício ≠ acusação; INDISPONÍVEL ≠ 0; valor pago só OB do SIAFE com `_ob_paga`; CPF mascarado; taxa alta =
defeito de leitura até abrir os casos; ato vizinho do DOERJ e pasta contaminada não contam como prova do processo.
