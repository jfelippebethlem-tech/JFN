# Relatório de Auditoria das OBs — JFN

Configuração padrão aplicada a partir de `compliance_agent/rules/default_audit_config.py`

Total de OBs analisadas: 258
Valor total: R$ 33.782.099,38
Valor médio por OB: R$ 131.010,16

## Alertas por tipo
- Sem SEI: 100
- Valores redondos: 175
- Concentração favorecido+UG: 15
- Fracionamento suspeito: 12
- Empresa irregular (pendência investigação): 1
- Conflito de interesse (pendência investigação): 1
- Publicidade PNCP (pendência investigação): 1

## Última coleta
- Fonte: SIAFE2 (https://siafe2.fazenda.rj.gov.br/Siafe/)
- Registros novos na última leitura: 50
- Erros na coleta: 0

## Hipóteses prioritárias
- H1: Pagamentos sem rastreabilidade processual (100 OBs sem SEI)
- H2: Direcionamento por concentração de contratos (15 grupos com 3+ pagamentos)
- H3: Valores redondos com perfil de estimativa sem cotação (175 casos)

## Recomendação
Priorizar H1 e H2 na próxima fase de investigação e iniciar cruzamento com CEIS/CNEP + PNCP.