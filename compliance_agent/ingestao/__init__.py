# -*- coding: utf-8 -*-
"""Contrato de ingestão do JFN (O4.11 do plano Esteira Única; doc 2 §40).

    contrato.py    — `config/fontes_cobertura.yaml` validado por Pydantic (fonte, dono, SLO, chave, domínio)
    quarentena.py  — lote de ingestão: contagens recebidos/aceitos/rejeitados/duplicados/quarentena e o
                     registro inválido PRESERVADO (payload original) em `ingestao_quarentena`
    sensores.py    — os 6 sensores por fonte (completude, validade, unicidade, consistência, atualidade,
                     reconciliação origem×ingestão) como funções puras + o SQL que as alimenta

CLI só-leitura: `python -m compliance_agent.ingestao validar|medir` (ver __main__.py).
Nada aqui é chamado pelos coletores ainda: a ligação é a religação O9.0 (parada de obras de 24/11/2026).
"""
