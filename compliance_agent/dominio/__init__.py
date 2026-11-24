# -*- coding: utf-8 -*-
"""Domínio puro do JFN — as funções ÚNICAS das 5 chaves canônicas e os estados (plano mestre v2, §3.1, §3.9, §3.10).

Regra da camada (contrato do `.importlinter` na raiz + `tests/test_dominio_sem_io.py`): nada aqui importa I/O —
sem FastAPI, ORM, requests/httpx, LLM, navegador nem `compliance_agent.rotas`. A única ponte com o legado é
`pagamento.ob_paga_sql`, que importa `cruzamentos_intel` DENTRO da função (lista `ignore_imports`, que só encolhe).

  digitos       so_digitos, cpf_valido, cnpj_valido, mascarar_cpf (reexporta `compliance_agent.cpf_cnpj`)
  processo_id   chave do processo: `NNNNNN/NNNNNN/AAAA` (SEI-RJ) ou `PCRJ:<nº>` (SEI.RIO)
  documento_id  `sei:<nº>` / `pos:<i>` + `#2` para número repetido no mesmo processo
  contrato_id   `(orgao, numero_normalizado, exercicio)`
  pagamento     invariante "pago = OB paga do SIAFE" (`ob_paga_sql`)
  estados       estados de saída (AUSENTE … ABSTEVE) e saúde operacional

Estado (24/11/2026, O4.1): criado com testes de paridade contra as cópias antigas; os chamadores antigos ainda NÃO
foram trocados (estrangulamento posterior).
"""
