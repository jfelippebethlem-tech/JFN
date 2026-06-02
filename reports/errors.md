# Erros detectados na auditoria — JFN

## Resumo
- Total de OBs analisadas: 258
- Alertas gerados: 302
- Tipo mais frequente: sem_sei (100), valor_redondo (175)

## Concentrações relevantes (prioridade alta)
- Comercial Milano Brasil Ltda|404400: 17 pagamentos, R$ 704.862,71
- REDE SOL FUEL DISTRIBUIDORA S/A|261100: 8 pagamentos, R$ 2.245.181,66
- AGILE CORP SERVIÇOS ESPECIALIZADOS LTDA.|266500: 7 pagamentos, R$ 251.352,35

## O mais grave
- 100 OBs sem SEI: alta gravidade por afrontar publicidade e rastreabilidade.
- 12 casos com possível fracionamento.

## Ajuste necessário no agente
- URL correta do SIAFE: https://siafe2.fazenda.rj.gov.br/Siafe/
- Não usar https://siafe.rj.gov.br/
- O coletor precisa chegar à tela de OB para evitar perda de registros.

Referência: C:\JFN\jfn\reports\relatorio_auditoria_obs.md
