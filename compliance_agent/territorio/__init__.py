# -*- coding: utf-8 -*-
"""Motor `territorio` — onde o contrato é EXECUTADO.

(A) contratos do ESTADO do RJ (Poder Executivo) por MUNICÍPIO de execução;
(B) contratos da PREFEITURA DO RIO por Área de Planejamento (AP1…AP5).

Só lê `compliance.db` / `pcrj.db` (modo `ro`) e só escreve em `data/territorio.db`.
Entrada: `python -m compliance_agent.territorio.cli --full | --incremental`.
"""
