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

## STATUS DE COLETA (2026-06-07)
- ✅ **DPRJ FEITO**: collectors/folha_dprj.py → 257.354 registros, 2016→2025, 5.384 pessoas.
  Caso FÁCIL: arquivos CSV/XLSX diretos (uploads/arquivos), sem JS.
- ⏳ **TJRJ**: portal Liferay JS — a página de anexos CNJ NÃO entrega links de arquivo via curl
  (renderiza por JS). Precisa Playwright (abrir o Anexo de folha e baixar) OU achar o endpoint XHR.
- ⏳ **MPRJ**: SPA JS (transparencia.mprj.mp.br) — carrega via JSON de uma API não-óbvia (action="#",
  sem /api público). Precisa capturar o XHR no browser.
- ⏳ **TCE-RJ / UERJ / UENF**: sistema `ConsultaRemuneracao` (SEPLAG) — consulta por NOME/CPF, não-bulk;
  para varrer tudo precisa iterar (ou achar export). UERJ/UENF provavelmente na central SEPLAG.
CONCLUSÃO: dos 6, só a DPRJ tinha download direto. Os outros 5 exigem browser/API por órgão
(build maior). Recomendo priorizar por valor/risco: MPRJ e TJRJ (volume + relevância), depois SEPLAG
(cobre UERJ/UENF/estaduais de uma vez se houver export).

## ENGENHARIA-REVERSA (2026-06-07, capturas Playwright)
- **MPRJ**: Liferay **JSONWS** — dados via POST a `/api/jsonws/invoke` (serviço+params), disparado
  por interação (selecionar competência + buscar). Próximo passo: capturar o BODY do POST (método+args)
  interagindo na página, depois replicar em httpx. (Liferay JSONWS é documentável.)
- **TJRJ**: também Liferay (mesma família) — Anexo VIII de folha é documento Liferay carregado por JS.
- **Centrais FORA DO AR (2026-06-07):** dados.rj.gov.br sem resposta; consultaremuneracao.rj.gov.br
  → www.rj.gov.br/remuneracao = HTTP 503. Sem bulk central no momento.
VEREDITO: das 6, só DPRJ tinha arquivo direto (FEITO, 257k). As outras 5 exigem captura de XHR/POST
por interação (Liferay JSONWS no MPRJ/TJRJ; .NET por CPF no ConsultaRemuneracao p/ TCE/UERJ/UENF) —
1 build focado por órgão. Não é "colar script"; é reverse-engineering de portal.

## MPRJ — API CNMP115 (cracking parcial, 2026-06-07) — reutilizável
- Liferay proxeia (ods.exportods/get-json-api) p/ API REST: BASE
  `https://api-transparencia.mprj.mp.br:8280/cnmp115/1.0.0` (gateway WSO2; padrão CNMP Res.115).
- OAuth FUNCIONA: POST `https://api-transparencia.mprj.mp.br:8280/token` Authorization Basic
  `cERmaFZtNUpOS1VfSjFCcUNSak1IMGN6dGpVYTpwb2dVS2Fta2kzZjN3UXZWWjJXdmtpSXRYazhh`
  (client `pDfhVm5JNKU_J1BqCRjMH0cztjUa`), grant_type=client_credentials → access_token (200).
- Recurso CONFIRMADO no gateway: `/anos` (lista anos; deu backend-404 numa tentativa, mas é resource
  definido). Os de dados (remuneração por ano/mês) ainda NÃO descobertos — os widgets de ano/mês são
  JS custom (sem <select>); "pesquisar" sem setá-los só chama /anos.
- PRÓXIMO PASSO (rápido c/ isto): (a) achar o spec CNMP115 (Modelo Nacional de Dados CNMP) p/ os nomes
  dos endpoints, OU (b) Playwright: setar os widgets de ano/mês e capturar o param api= do POST de dados.
  Depois: httpx com o token → paginar por ano/mês → registros_folha (fonte=mprj). Auth já resolvida.
