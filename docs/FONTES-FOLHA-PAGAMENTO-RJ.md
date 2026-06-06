# Fontes de FOLHA DE PAGAMENTO — órgãos do Estado do RJ (levantamento 2026-06-06)

> Objetivo: coletar remuneração de servidores **discriminada por rubrica** (vencimento base/subsídio,
> gratificações, vantagens pessoais, verbas indenizatórias, descontos) para auditoria. Levantamento de
> fontes (sem código ainda). Órgãos: Executivo RJ, UERJ, UENF, UEZO, RIOPREVIDÊNCIA, TJRJ, MPRJ, TCE-RJ,
> ALERJ, Defensoria (DPRJ).

## Achado estrutural
O **Executivo** reformulou o portal (out/2025): **`https://consultaremuneracao.rj.gov.br/ConsultaRemuneracao`**
(SEPLAG) cobre **toda a Administração Direta e Indireta** — inclui **UERJ, UENF, UEZO e RIOPREVIDÊNCIA**
(autarquias/indireta) por **filtro de órgão**. UEZO foi incorporada à UERJ (2022). Poderes/autônomos
(TJRJ, MPRJ, TCE, ALERJ, Defensoria) têm portais próprios e separados.

## Por fonte
| Órgão | URL | Formato | Rubrica discriminada? | Histórico | Obstáculo | Método |
|---|---|---|---|---|---|---|
| **Executivo (+UERJ/UENF/UEZO/RIOPREV por filtro)** | consultaremuneracao.rj.gov.br/ConsultaRemuneracao | HTML + **CSV/XLS/PDF** | **SIM (melhor fonte)** | 12 meses móveis | SPA JS; já exigiu login gov.br | **Playwright p/ achar a API JSON interna**, baixar CSV por órgão/mês |
| **MPRJ** | transparencia.mprj.mp.br/contracheque | export CSV/XLS/PDF | Parcial ("outras verbas") | mensal | login gov.br em parte | Playwright c/ sessão |
| **TJRJ** | tjrj.jus.br/transparencia/.../servidor (Anexo V) | arquivos anuais (2021–2026) | layout CNJ, rótulos vagos | 2021–2026 | Anexo VIII atrás de login Liferay | requests p/ Anexo V; LAI p/ detalhe |
| **TCE-RJ** | tce.rj.gov.br/consulta-processo/ConsultaRemuneracao | HTML + planilhas | Agregada (fraca) | confirmar | 2 domínios (um inativo), instável | validar domínio, Playwright |
| **ALERJ** | transparencia.alerj.rj.gov.br/section/report/73 ; PDFs `folha-de-pagamento-AAAA-MM.pdf` | **só PDF mensal** | Fraca (bruto+teto) | **2016–2026 (maior histórico)** | PDF não-estruturado → OCR | requests + parser/OCR |
| **Defensoria (DPRJ)** | transparencia.rj.def.br/ConsultaRemuneracao | HTML (CPF+motivo) | Genérica | 12 meses | exige CPF + justificativa | Playwright |

## Fácil → Difícil
- **Fácil:** Executivo (CSV + rubrica boa; cobre 4 órgãos por filtro). 
- **Médio:** MPRJ (login), TJRJ (arquivo anual), TCE (instável), ALERJ (PDF+OCR, histórico enorme).
- **Difícil:** Defensoria (CPF+motivo), e histórico >12 meses de qualquer um → **LAI/e-SIC**.

## Recomendação de arquitetura
1. Coletor **Executivo** primeiro (Playwright → descobrir API JSON → baixar CSV por órgão/mês), que já entrega
   rubrica discriminada e cobre UERJ/UENF/UEZO/RIOPREV por filtro. Maior retorno por esforço.
2. Depois MPRJ (CSV c/ sessão), ALERJ (PDF+OCR pelo histórico 2016+).
3. TJRJ/TCE como coletores de arquivo. Defensoria e históricos antigos por último (LAI).
4. **Esquema na `compliance.db`:** guardar `rubrica_original` + `rubrica_normalizada` (normalizar os rótulos
   genéricos do TJ/MP/Defensoria) para não perder o problema de "transparência de fachada".

_Fonte: pesquisa web 2026-06-06 (ver links no relatório da sessão)._
