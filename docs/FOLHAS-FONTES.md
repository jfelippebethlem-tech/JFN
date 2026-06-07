# Folhas de pagamento — fontes por órgão (RJ) — descoberta 2026-06-07

Objetivo: popular `registros_folha` (compliance.db) com a remuneração de servidores/membros
dos 6 órgãos, 2023→agora. Schema pronto: cpf, nome, orgao_codigo/nome, cargo, vinculo,
competencia, remuneracao_bruta/liquida, abonos, descontos, fonte.

## Sistema comum RJ: `ConsultaRemuneracao` (SEPLAG)
Vários órgãos do RJ usam o MESMO sistema de consulta (por nome/CPF):
- **Central (Executivo, SEPLAG):** https://consultaremuneracao.rj.gov.br/ConsultaRemuneracao
  → provável fonte de UERJ/UENF (autarquias do Executivo) e demais servidores estaduais.
- **Defensoria (DPRJ):** https://transparencia.rj.def.br/ConsultaRemuneracao
- **TCE-RJ:** https://tce.rj.gov.br/consulta-processo/ConsultaRemuneracao
⚠️ Esses são de CONSULTA individual (nome/CPF → 1 pessoa). Para BULK, ver os relatórios/dados-abertos abaixo.

## Por órgão
- **TJRJ** (Judiciário): Portal da Transparência > Gestão de Pessoas — anexos CNJ Res. 102/2009,
  incl. **Anexo VIII (Detalhamento da Folha de Pagamento)** em **csv/json/xml** (BULK).
  https://www.tjrj.jus.br/pagina-inicial/portal-da-transparencia/gestao-de-pessoas
- **MPRJ** (MP): Novo Portal da Transparência — estruturado:
  https://transparencia.mprj.mp.br/contracheque/remuneracao-de-todos-os-membros-ativos
  https://transparencia.mprj.mp.br/gestao-de-pessoas/estrutura-remuneratoria/servidores
- **TCE-RJ**: ConsultaRemuneracao (acima) + estrutura_remuneratoria:
  https://www.tcerj.tc.br/portalnovo/pagina/estrutura_remuneratoria
- **Defensoria (DPRJ)**: **Relatório Mensal de Remuneração** (BULK, 12 meses) +
  ConsultaRemuneracao: https://transparencia.rj.def.br/gastos-com-pessoal/relatorio-mensal-de-remuneracao
- **UERJ** (autarquia): consulta por nome/CPF (bruto/líquido/descontos/benefícios), padrão TCE/PGE;
  provável via central SEPLAG. https://www.uerj.br/transparencia/
- **UENF** (autarquia): https://uenf.br/reitoria/transparencia/ — menos estruturado; possível só via SIC;
  servidores também na central SEPLAG.

## Plano de coleta (próxima fase — build dos coletores)
1. **Alvo de maior ROI primeiro:** fontes BULK (TJRJ Anexo VIII CSV/JSON; DPRJ Relatório Mensal) →
   parse direto, sem CAPTCHA, 1 coletor cada → grava em `registros_folha` (fonte por órgão).
2. **ConsultaRemuneracao (SEPLAG/TCE/DPRJ):** mapear o POST/endpoint (provável .NET/JSF) — pode exigir
   iterar por nome/letra ou ter export. Reusar o aprendizado de PPR/HTTP do SIAFE se for JSF.
3. **UERJ/UENF:** confirmar se estão na central SEPLAG (consultaremuneracao.rj.gov.br) — se sim, 1 coletor cobre os 2.
4. Período: 2023→2026 por competência mensal. Idempotência: `_registro_existe(fonte, competencia)`
   (já existe em collectors/terceirizados.py).

STATUS: fontes IDENTIFICADAS (esta descoberta). Coletores: A CONSTRUIR (fase seguinte).
