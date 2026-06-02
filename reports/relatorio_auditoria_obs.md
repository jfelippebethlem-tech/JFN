# Relatório de Auditoria das OBs — JFN

Configuração padrão aplicada a partir de `compliance_agent/rules/default_audit_config.py`

Total de OBs analisadas: 258
Valor total: R$ 33.782.099,38
Valor médio: R$ 130.938,37
Sem SEI: 100

Análises aplicadas:
1. Sem processo SEI/SEI associado
2. Valores redondos suspeitos
3. Concentração de pagamentos para mesmo favorecido em UG
4. Fracionamento suspeito
5. Pendências complementares conforme TCU 6.100/2022 e TCU 3.654/2020

Quantitativo de alertas por tipo:
- sem_sei: 100
- valor_redondo: 175
- concentracao_favorecido_ug: 15
- fracionamento_suspeito: 12
- pendencias_investigacao: 1

Observação:
- Cerca de 38,8% das OBs não possuem número de SEI associado.
- Houve 175 valores redondos suspeitos, indicando risco de direcionamento.
- 15 casos com concentração de pagamentos para o mesmo fornecedor e UG merecem revisão prioritária.
- 12 casos com possível fracionamento de despesas indicam risco de burla ao limite de dispensa.
- Há 1 bloco de pendências complementares pendente de base integrada.

Parâmetros adotados:
- Limite dispensa obras: R$ 119.812,02
- Limite dispensa compras/serviços comuns: R$ 59.906,02
- UGs comuns consideradas: 300100 (SEFAZ) e 200100 (Casa Civil)
- Critério de alerta: 3 ou mais pagamentos para mesmo favorecido em uma UG

Referência de regras adicionais:
- Lei 14.133/2021, art. 8, paragrafo 1: vedação ao fracionamento de despesas.
- Lei 14.133/2021, art. 75, I e II: limites de dispensa de licitação.
- TCU 6.100/2022: empresa irregular por capital, CAGED, tempo de existência e endereço.
- TCU 3.654/2020: conflito de interesse por doação de campanha a gestor licitante.
