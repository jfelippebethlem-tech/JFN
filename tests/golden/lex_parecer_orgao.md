# PARECER REFERÊNCIA — ÓRGÃO ORGAO SNAPSHOT DE TESTES (UG 999999)
### Avaliação jurídica, financeira, contábil e de integridade da execução da despesa

**UG:** 999999  |  **Data:** 2026-07-06  |  **Analista:** Controle Externo (automatizado)
**Grau de atenção:** 🟡 **AMARELO** · índice 16/100 — indícios pontuais a esclarecer mediante diligência.
**Base de pagamentos:** SIAFE · ob_orcamentaria_siafe (régua _ob_paga).

---

## 1. SUMÁRIO EXECUTIVO

- **Grau consolidado:** 🟡 **AMARELO** · índice **16/100** — 1 indício(s), gravidade máxima 4/5.
- **Fatos mais relevantes:**
  - Total pago pela UG (OB SIAFE, valor > 0): **R$ 9.000.000,00** — fonte SIAFE · ob_orcamentaria_siafe (régua _ob_paga) · VERIFICADO.
  - Nº de OBs pagas: **3** — fonte SIAFE · ob_orcamentaria_siafe (régua _ob_paga) · VERIFICADO.
  - Favorecidos distintos: **2** — fonte SIAFE · ob_orcamentaria_siafe (régua _ob_paga) · VERIFICADO.
  - Indício **R8** (Concentração de fornecedor / risco de captura (bid rigging), grav. 4/5): EMPRESA A LTDA concentra 66,7% dos pagamentos do órgão (R$ 6.000.000,00 de R$ 9.000.000,00; HHI 5555,6 — alta). Concentração ≥60% em um único fornecedor é *red flag* clássico de captura/cartel (ACFE/O…
- **Não verificado:** contratos, certames e medições do órgão não examinados (só pagamentos e cadastro dos favorecidos); empenho e liquidação da UG não confrontados com o pago neste parecer.
- **Diligências prioritárias:**
  - Requisitar à UG 999999 os contratos, certames e medições dos pagamentos a **EMPRESA A LTDA** (R$ 6.000.000,00).
  - Requisitar à UG 999999 os contratos, certames e medições dos pagamentos a **EMPRESA B LTDA** (R$ 3.000.000,00).
  - Indício **R8** — teste discriminante: atas dos certames: nº de propostas VÁLIDAS, cascata de desclassificações e QSA/endereços dos derrotados (derrotado-fantasma que nunca vence em lugar nenhum = cartel de cobertura).

## 2. OBJETO, ESCOPO E METODOLOGIA

Execução da despesa da UG examinada pelos eixos financeiro, contábil, jurídico e de integridade, a partir da **OB paga do SIAFE** (régua `_ob_paga`; o espelho TFE não é usado como pago). Camada determinística apenas; indício ≠ acusação; INDISPONÍVEL ≠ 0. Régua do grau: 🟢 sem indício; 🟡 indício pontual; 🔴 convergência de 3+ indícios com um grave; ⚪ sem base.

## 3. BASE DE FATOS

| Fato | Valor | Fonte (tabela/consulta) | Estado |
|---|---|---|---|
| Total pago pela UG (OB SIAFE, valor > 0) | R$ 9.000.000,00 | SIAFE · ob_orcamentaria_siafe (régua _ob_paga) | **VERIFICADO** |
| Nº de OBs pagas | 3 | SIAFE · ob_orcamentaria_siafe (régua _ob_paga) | **VERIFICADO** |
| Favorecidos distintos | 2 | SIAFE · ob_orcamentaria_siafe (régua _ob_paga) | **VERIFICADO** |
| Maior favorecido | EMPRESA A LTDA — R$ 6.000.000,00 (66,7%) | SIAFE · ob_orcamentaria_siafe (régua _ob_paga) | **VERIFICADO** |
| Concentração por favorecido (HHI) | 5555,6 (ALTA) | derivado de SIAFE · ob_orcamentaria_siafe (régua _ob_paga) | **VERIFICADO** |
| OB de valor zero (regularização) | 0 | SIAFE · ob_orcamentaria_siafe (régua _ob_paga) | **VERIFICADO** |
| OB registradas e NÃO pagas | 0 — R$ 0,00 | SIAFE · ob_orcamentaria_siafe (régua _ob_paga) | **VERIFICADO** |
| Última coleta das OBs da UG | 2026-07-05 10:00:00 | SIAFE · ob_orcamentaria_siafe (régua _ob_paga) | **VERIFICADO** |

## 4. EIXO FINANCEIRO

*Critério: Lei 4.320/64, arts. 58-65; competitividade (Lei 14.133/2021, art. 11).*

| Ano | OBs | Total (R$) |
|---|---:|---:|
| 2025 | 3 | 9.000.000,00 |
| **Total** | **3** | **9.000.000,00** |

| Favorecido | Pago (R$) | % do pago |
|---|---:|---:|
| EMPRESA A LTDA | 6.000.000,00 | 66,7% |
| EMPRESA B LTDA | 3.000.000,00 | 33,3% |

#### R8 — Concentração de fornecedor / risco de captura (bid rigging) (gravidade 4/5)
- **Condição (fato):** **EMPRESA A LTDA** concentra **66,7%** dos pagamentos do órgão (R$ 6.000.000,00 de R$ 9.000.000,00; HHI 5555,6 — alta). Concentração ≥60% em um único fornecedor é *red flag* clássico de captura/cartel (ACFE/OCDE) — exige comprovar a competitividade.
- **Critério:** Art. 37 CF/88; Art. 36 §3º I 'd' Lei 12.529; ACFE/OCDE
- **Explicação inocente:** A concentração/co-ocorrência pode refletir um mercado regional naturalmente concentrado ou um ramo de poucos players (ex.: engenharia/consórcio legítimo), sem qualquer conluio. → os dados a **refutam** (convergência/gravidade): sustenta **requisição de documentos**.

**Conclusão do eixo financeiro:** 🟡 **AMARELO** — 1 indício(s) (R8); P×I somado 16.

## 5. EIXO CONTÁBIL

*Critério: Lei 4.320/64, arts. 62-65 (pagamento após liquidação; OB devolvida não é pago).*

> Nenhum indício contábil.

**Conclusão do eixo contábil:** 🟢 **VERDE** — sem indícios relevantes nos dados disponíveis — presunção de regularidade mantida.

## 6. EIXO JURÍDICO

*Critério: Lei 14.133/2021, arts. 72-75 (contratação direta) e 147-149 (nulidade e indenização); LINDB, arts. 20-22 e 28.*

> Nenhum indício jurídico nas fontes lidas.

**Conclusão do eixo jurídico:** 🟢 **VERDE** — sem indícios relevantes nos dados disponíveis — presunção de regularidade mantida.

## 7. EIXO COMPLIANCE / INTEGRIDADE

*Critério: Lei 12.846/2013; Lei 14.133/2021, arts. 14 e 156.*

> Nenhum indício de integridade nos favorecidos.

**Conclusão do eixo compliance / integridade:** 🟢 **VERDE** — sem indícios relevantes nos dados disponíveis — presunção de regularidade mantida.

## 8. INSTRUÇÃO NO FORMATO DE TRIBUNAL DE CONTAS

### 8.1 Matriz de achados

| # | Eixo | Critério | Condição | Causa provável | Efeito potencial |
|---|---|---|---|---|---|
| R8 | Financeiro | Art. 37 CF/88; Art. 36 §3º I 'd' Lei 12.529; ACFE/OCDE | EMPRESA A LTDA concentra 66,7% dos pagamentos do órgão (R$ 6.000.000,00 de R$ 9.000.000,00; HHI 5555,6 — alta). Concentr… | baixa rotatividade/captura de fornecedor por um órgão | risco de cartel/sobrepreço e dependência do prestador |

### 8.2 Passo exculpatório

| Indício | Explicação inocente | Refutada? | Encaminhamento |
|---|---|---|---|
| R8 | A concentração/co-ocorrência pode refletir um mercado regional naturalmente concentrado ou um ramo de poucos players (ex.: engenharia/consór… | Sim | **representação** |

### 8.3 Matriz de risco (P × I)

| Indício | P | I | P×I | Faixa |
|---|---:|---:|---:|---|
| R8 Concentração de fornecedor / risco de captura (bid rigging) | 4 | 4 | 16 | Extremo |

### 8.4 Proposta de encaminhamento

| Medida proposta | Fundamento | Achados que a sustentam |
|---|---|---|
| Requisição de documentos ao órgão (diligência) | CF/88 arts. 70-71; Lei 14.133/2021, arts. 169-171 | R8 |
| Representação ao TCE-RJ/MP-RJ se a resposta não afastar o indício | Deliberação TCE-RJ 279/2017 (elementos que indiquem) | R8 |

> Encaminhamento a outro órgão só para achado cuja explicação inocente os dados afastaram; a tipificação (improbidade, crime) é do MP-RJ e do Judiciário, após contraditório (art. 5º, LV, CF/88).

## 9. CAMADA SUBJETIVA

> **INDISPONÍVEL** — o parecer de órgão não aciona a camada subjetiva; vale a camada determinística.

## 10. CONCLUSÃO — GRAU CONSOLIDADO

| Eixo | Grau | Indícios |
|---|---|---:|
| Financeiro | 🟡 AMARELO | 1 |
| Contábil | 🟢 VERDE | 0 |
| Jurídico | 🟢 VERDE | 0 |
| Compliance / integridade | 🟢 VERDE | 0 |
| **Consolidado** | **🟡 AMARELO** | **1** |

> 🟡 **AMARELO** — indícios pontuais a esclarecer mediante diligência.

## 11. RESSALVAS

1. Baseado em pagamentos (OB paga do SIAFE) e no cadastro dos favorecidos, sem exame documental dos contratos.
2. Indícios a verificar, não conclusão de irregularidade; vigora a presunção de legitimidade.
3. Controle externo competente: Tribunal de Contas do Estado do Rio de Janeiro (TCE-RJ).
