# RELATÓRIO DE INTELIGÊNCIA DE FORNECEDOR
### SNAPSHOT ENGENHARIA E SERVICOS LTDA

*Due Diligence de Integridade · Exposição Financeira · Risco & Compliance*

**CNPJ:** 11.222.333/0001-81  |  **Data:** 2026-07-06  |  **Analista:** Controle Externo (automatizado)
**Metodologia:** due diligence de integridade (padrão Kroll/Deloitte) · matriz de risco TCU P×I · OB = pagamento (fonte de verdade)
**Classificação de fonte:** OBs/Contratos = **REAL** (SIAFE/TFE) · Perfil/Sanções/Rede = **INDISPONIVEL**

---

> _Cobertura da base: 1.138.236 OBs · 77% com CNPJ (PJ) · OB mais recente: 2026-07-01. OB = pagamento definitivo (SIAFE/TFE-RJ); afirmações limitadas a esta cobertura._

## SUMÁRIO EXECUTIVO

SNAPSHOT ENGENHARIA E SERVICOS LTDA (CNPJ 11.222.333/0001-81) Pagamentos (OBs) — 2023: R$ 120.000,00, 2025: R$ 4.200.000,00. Total pago no período: R$ 4.320.000,00 em 4 OBs, 2 órgãos. Concentração (HHI): 0.51 (alto; maior órgão = None%). Rating de risco corporativo: MÉDIO (score 42/100).

### Exposição financeira — pagamentos por exercício

| Exercício | Nº de OBs | Valor pago (R$) |
|---|---:|---:|
| 2023 | 2 | 120.000,00 |
| 2025 | 2 | 4.200.000,00 |
| **Total** | **4** | **4.320.000,00** |

## 1. PERFIL CADASTRAL

> ⚠️ Perfil cadastral **INDISPONIVEL** (enriquecimento não disponível). Os dados financeiros abaixo (OBs/contratos) são REAIS e independem desta seção.
- **Realidade da sede:** ainda não verificada (sweep de endereços em andamento) — INDISPONÍVEL não é prova de inexistência.

## 1-B. REDE SOCIETÁRIA — CRUZAMENTO SÓCIO × OB × SEI × ENDEREÇO

> Cruza o **quadro societário** (QSA/Receita) com **as OBs do SIAFE**, os **processos SEI** de origem dos pagamentos e o **endereço (sede)** das empresas. Empresas que compartilham sócio — e sobretudo as que compartilham a mesma sede — recebendo recursos do mesmo Estado são indício de grupo econômico/empresas-irmãs a verificar (art. 337-F CP; art. 11 Lei 8.429/92). **Indício, nunca acusação.**

**Pegada do alvo no SIAFE:** 0 OBs · R$ 0,00 pagos · 0 processo(s) SEI vinculado(s).

> Sem rede societária ingerida para este CNPJ. Para habilitar o cruzamento por sócio: `python -m compliance_agent.rede_societaria --ingerir `.

## 1-C. BENEFÍCIOS SOCIAIS DOS SÓCIOS/ADMINISTRADORES (INDÍCIO DE LARANJA)

> Cruza o **CPF dos sócios/administradores** do QSA com os **benefícios de subsistência** por CPF (Bolsa Família, BPC, Auxílio Emergencial, PETI, Garantia-Safra, Seguro-Defeso — Portal da Transparência/CGU). Ser **dono/gestor** de empresa que recebe recursos públicos **e** receber benefício de subsistência é **indício clássico de testa-de-ferro (laranja)** — interposição de pessoas (art. 337-F CP; art. 11 Lei 8.429/92). CPF mascarado (LGPD); resolvido por fontes oficiais (favorecidos PF + TSE). **INDISPONÍVEL ≠ ausência de benefício.**

_Sem sócios/administradores com CPF mascarado no QSA deste fornecedor (ou QSA público não ingerido) — **INDISPONÍVEL** (não equivale a ausência de benefício)._
## 1-D0. EMENDAS PARLAMENTARES — RECURSO PÚBLICO POR INDICAÇÃO

> Recursos que chegaram à entidade por **emenda parlamentar** (individual, de bancada ou relator), com o **autor** de cada uma. Para ONG/OSC, é a principal via de financiamento e o ponto onde a captura política se materializa: o parlamentar indica → o recurso é repassado → a entidade executa, muitas vezes por **termo de fomento/colaboração sem licitação** (Lei 13.019/2014). Concentração de muitas emendas numa única entidade e execução por OSC recém-relacionada são **indícios de direcionamento** — Lei 14.133 art. 5º; MROSC art. 30; presunção de legitimidade, **nunca acusação**.

_Nenhuma emenda parlamentar localizada para o CNPJ na base ingerida — **INDISPONÍVEL / sem registro** (≠ inexistência; a base cobre emendas federais coletadas)._

## 1-D. DOAÇÕES ELEITORAIS — CONFLITO DOADOR ↔ CONTRATO (TSE)

> Cruza as **doações eleitorais** (TSE) da empresa **e de seus sócios** com os contratos/pagamentos do Estado, fechando a cadeia **doador → fornecedor → candidato → UG pagadora → processo SEI**. Doar a campanha e contratar com o poder público é **indício de relação política / conflito de interesse** a verificar (Lei 9.504/97; Lei 14.133 art. 14) — presunção de legitimidade, **nunca acusação**.

_Nenhuma doação eleitoral (TSE) localizada para a empresa ou seus sócios na base — **INDISPONÍVEL / sem registro** (não equivale a inexistência de doação fora do período/base ingerida)._

## 1-E. RODÍZIO DE VENCEDORES / CARTEL (BID ROTATION)

> Verifica se este fornecedor é um dos **'campeões' que se revezam no topo** das UGs que mais o pagam — padrão de **bid rotation** (rodízio de vencedores), *red flag* de cartel/conluio (OCDE *Guidelines*; Lei 12.529/11 art. 36; Lei 8.666 art. 90). A OB expõe o **vencedor**, não os licitantes — corroborar no SEI/PNCP. **Indício, não prova.**

_Sem UGs suficientes para avaliar rodízio, ou avaliação indisponível nesta execução — **INDISPONÍVEL**._

## 1-F. CONFLITO DE PESSOAL — SÓCIO/ADMINISTRADOR NA FOLHA DO ESTADO

> Cruza os sócios/administradores do QSA com a **folha do Estado** (servidores/terceirizados/bolsistas — `registros_folha`) por **nome + 5 dígitos do CPF** (a sobreposição entre a máscara do QSA e a da folha) — cobre **todos** os sócios mascarados, sem depender de resolver o CPF. Ser sócio/gestor de empresa contratada pelo poder público **e** integrar sua folha é indício de **conflito de interesse / incompatibilidade** (CF art. 37; Lei 8.429/92 art. 11; Lei 14.133/21 art. 9º). **INDISPONÍVEL ≠ ausência**. Indício, **nunca acusação**.

Não há sócios/administradores com CPF mascarado no QSA para cruzar com a folha deste fornecedor — **INDISPONÍVEL** (não equivale a ausência de conflito).

## 1-G. EXECUÇÃO CONTRATUAL — PROVA DE ENTREGA (OB PAGA × PERÍCIA SEI)

> Cruza os **processos pagos** (Ordem Bancária) deste fornecedor com a **perícia de execução** (lex_execucao): há prova de entrega/fiscalização nos autos? Pagar sem execução comprovada é *red flag* (Lei 4.320/64 art. 63 — a liquidação exige a comprovação; Lei 14.133/2021 arts. 117/140). **Indício, não prova** — INDISPONÍVEL ≠ irregular (pode faltar só no recorte coletado).

_Nenhum processo SEI deste fornecedor foi periciado quanto à execução ainda — **INDISPONÍVEL** (a perícia documental SEI roda por sweep; este fornecedor pode não ter sido alcançado)._

## 2. PAGAMENTOS (ORDENS BANCÁRIAS) POR ANO

> Fonte: SIAFE/TFE-RJ (Ordem Bancária = dado **definitivo de pagamento**). Por exercício, as **maiores OBs** (materiais); a **lista completa** de cada pagamento está na **planilha XLSX** deste relatório. OBs de R$ 0,00 são estornos/regularizações (entram na contagem, não somam ao total).

> **Nota conceitual (cadeia da despesa):** a **OB (Ordem Bancária) é o pagamento** — a verdade financeira, porém **uma parcela**, não um contrato. Um **contrato** gera **várias OBs** (parcelas/medições/aditivos); um **processo SEI** (licitação ou **Registro de Preços/SRP**) pode gerar **vários contratos**, **aditivos** e **muitas OBs**. Portanto **nº de OBs ≠ nº de contratos ≠ nº de processos** — os contadores abaixo são distintos e honestos quanto à cobertura (a vinculação OB→processo só existe onde o SIAFE/SEI a preencheu).

### Exercício 2023 — 2 OBs — Total pago: R$ 120.000,00

| # | Nº OB | Data pagamento | Órgão (UG) | Valor (R$) |
|---:|---|---|---|---:|
| 1 | 2023OB00101 | 2023-03-10 | SEC ESTADUAL DE OBRAS | 120.000,00 |
| 2 | 2023OB00150 | 2023-05-02 | SEC ESTADUAL DE OBRAS | 0,00 |
| | | | **Total 2023 (2 OBs)** | **120.000,00** |

### Exercício 2025 — 2 OBs — Total pago: R$ 4.200.000,00

| # | Nº OB | Data pagamento | Órgão (UG) | Valor (R$) |
|---:|---|---|---|---:|
| 1 | 2025OB00007 | 2025-02-15 | SEC ESTADUAL DE OBRAS | 2.400.000,00 |
| 2 | 2025OB00930 | 2025-08-20 | FUNDACAO SAUDE | 1.800.000,00 |
| | | | **Total 2025 (2 OBs)** | **4.200.000,00** |

## 3. CONCENTRAÇÃO POR ÓRGÃO CONTRATANTE (HHI)

**HHI:** 0.51 — concentração **alto** (maior órgão = None% do valor pago).

| Órgão (UG) | Valor pago (R$) | % do total |
|---|---:|---:|
| SEC ESTADUAL DE OBRAS | 2.520.000,00 | 58.3% |
| FUNDACAO SAUDE | 1.800.000,00 | 41.7% |

## 4. CARTEIRA DE CONTRATOS (SIAFE)

_Nenhum contrato oficial vinculado na base local._

## 4-B. CONTRATOS E COMPRAS DIRETAS — TCE-RJ (Dados Abertos)

_Sem contratos ou compras diretas deste CNPJ na base de Dados Abertos do TCE-RJ (pode ser contratação municipal/federal ou ainda não publicada)._

## 5. SINAIS DE RISCO CORPORATIVO

> Sinais corporativos **INDISPONIVEL** (—).

## 6. VERIFICAÇÃO EM LISTAS RESTRITIVAS (CEIS/CNEP/CEPIM)

> **INDISPONIVEL**.

## 7. MATRIZ DE RISCO — METODOLOGIA TCU P×I

Escala P (probabilidade) × I (impacto), 1–9 cada. Faixas: Baixo 1–9 | Médio 10–39 | Alto 40–79 | Extremo 80–81.

| Fator de risco | P | I | Score | Faixa |
|---|---:|---:|---:|---|
| Dispersão de pagamentos entre órgãos | 2 | 4 | 8 | Baixo |
| Sinais de risco corporativo (perfil/rede) | 4 | 5 | 20 | Médio |
| Crescimento abrupto de pagamentos (2023→2025) | 5 | 6 | 30 | Médio |

## 8. RED FLAGS DE COMPLIANCE

### RF-02 — Ordens bancárias com valor zero
1 OB(s) com valor R$ 0,00 (estornos/regularizações). Volume elevado de estornos pode indicar retrabalho de execução ou ajustes — vale conferir o motivo.
**Fundamento:** Boa prática de controle interno (CGE-RJ); rastreabilidade da execução (Lei 4.320/64).

## 8-B. ANÁLISE ESTATÍSTICA DOS VALORES (LEI DE BENFORD)

> A Lei de Benford prevê a frequência do **1º dígito** em populações de valores naturais (pagamentos). Um desvio relevante (MAD de Nigrini) é **indício** estatístico de fracionamento, valores fabricados ou direcionamento — **nunca prova**; amostras pequenas (n<50) são pouco confiáveis. Triagem, a confirmar nos documentos.

**1º dígito** (n=3 OBs): **MAD de Nigrini = 0.1162** → **NÃO CONFORMIDADE**.
> ⚠️ Amostra pequena (n=3 < 50) — resultado **pouco confiável**, informativo apenas.

| Dígito | Esperado (Benford) | Observado | Δ (pp) |
|---:|---:|---:|---:|
| 1 | 30.1% | 66.7% | +36.6 |
| 2 | 17.6% | 33.3% | +15.7 |
| 3 | 12.5% | 0.0% | -12.5 |
| 4 | 9.7% | 0.0% | -9.7 |
| 5 | 7.9% | 0.0% | -7.9 |
| 6 | 6.7% | 0.0% | -6.7 |
| 7 | 5.8% | 0.0% | -5.8 |
| 8 | 5.1% | 0.0% | -5.1 |
| 9 | 4.6% | 0.0% | -4.6 |

> 🟡 **Não conformidade** — a distribuição se afasta do esperado; **indício** estatístico a verificar (fracionamento, valores fabricados, direcionamento). Confirmar nos contratos/OBs — Benford é triagem, não prova.

## 8-C. ANOMALIAS NAS ORDENS BANCÁRIAS (MODELO DE DETECÇÃO)

> Um modelo de detecção de anomalias (ensemble não supervisionado) pontua cada OB de **0 a 1** por quanto ela destoa do padrão (valor, frequência do fornecedor, dia/mês, UG). Score alto é **indício** de pagamento atípico a inspecionar — **nunca prova** (pode ser contrato grande legítimo, sazonalidade, parcela única).

_Sem OBs pontuadas pelo modelo para este fornecedor — **INDISPONÍVEL**._

## 9. ANÁLISE JURÍDICA E DE MÉRITO — PARECER PRELIMINAR

### Análise de mérito

A empresa **SNAPSHOT ENGENHARIA E SERVICOS LTDA** recebeu **R$ 4.320.000,00** do Estado do Rio de Janeiro no período analisado, em **4 ordens bancárias** distribuídas por **2 unidades gestoras**. Os pagamentos saltaram de R$ 120.000,00 (2023) ao pico de R$ 4.200.000,00 (2025) — fator pico/base de 35.0× entre exercícios (o primeiro e o último ano da série podem ser parciais; usa-se o pico para evitar distorção). O valor é **materialmente relevante** e, por si só, recomenda acompanhamento de controle.

Os pagamentos mostram **dispersão razoável** entre órgãos (maior fatia 0.0% em SEC ESTADUAL DE OBRAS; HHI 0.51), o que reduz — mas não elimina — o risco de captura institucional.

Registram-se **1 OB(s) de valor zero** (estornos/regularizações). Volume não trivial de estornos pode indicar retrabalho de liquidação ou ajustes de execução e merece conferência documental.

### Avaliação jurídica

Sob o prisma normativo, os pontos acima devem ser cotejados com:

- **CF/88, art. 37, *caput*** — princípios da impessoalidade, moralidade e eficiência na Administração;
- **Lei 14.133/2021** (nova Lei de Licitações) — dever de **competitividade** e de **publicidade** dos contratos no PNCP (art. 94); e **Lei 8.666/93** para contratos remanescentes sob sua vigência;
- **Lei 8.666/93, art. 65, §1º** — limites de aditivos (25%/50%), quando houver contratos aditivados;
- **Lei 4.320/64 e Decreto 93.872/86** — regularidade do ciclo empenho→liquidação→pagamento (vedação a pagamento antecipado sem amparo);
- **ACFE / TCU** — *red flags* de concentração de fornecedor e de pagamentos atípicos.

O rating de risco corporativo apurado (**MÉDIO**, score 42/100) reforça a necessidade de diligência sobre quadro societário e eventuais vínculos.

### Conclusão e grau de atenção

**Grau de atenção recomendado: MÉDIO.** Os achados configuram **indícios a verificar** — não conclusão de irregularidade. Recomenda-se: (i) obter a lista oficial de contratos e respectivos processos SEI dos maiores pagamentos; (ii) confirmar a modalidade licitatória; (iii) checar aderência entre objeto contratual e atividade-fim; e (iv) cruzar empenho×liquidação×OB para detectar gaps.

> **Ressalva metodológica:** análise baseada em **dados de pagamento (OB)** de fontes públicas; não examina o mérito documental de cada contrato. Não há, aqui, juízo de culpabilidade — vigora a presunção de regularidade dos atos administrativos até prova em contrário.

## 10. RECOMENDAÇÕES

**Imediato (0–30 dias):**
- Cruzar as OBs por ano (tabelas da Seção 2) com os empenhos/liquidações correspondentes no SIAFE.
- Validar a aderência objeto-contratual dos órgãos de maior concentração (Seção 3).

**Curto prazo (30–90 dias):** abrir os processos SEI dos maiores pagamentos; checar aditivos (>25%).

**Estrutural:** monitoramento contínuo automatizado (timers TFE/OB) e atualização trimestral deste relatório.

## 11. REFERÊNCIAS E FONTES

- **Dados primários:** SIAFE-Rio / Transparência Fiscal RJ (OBs e contratos) — `data/compliance.db`.
- **Perfil/sanções/rede:** Receita Federal, PNCP, CEIS/CNEP/CEPIM (via `relatorio_riscos`).
- **Normas:** Lei 14.133/2021; Lei 8.666/93; Lei 4.320/64; CF/88 Art. 37; metodologia TCU P×I; ACFE Report to the Nations 2024.

_Relatório gerado automaticamente em 2026-07-06. Não substitui análise jurídica especializada._


===RESUMO-EXECUTIVO===
SNAPSHOT ENGENHARIA E SERVICOS LTDA (CNPJ 11.222.333/0001-81) Pagamentos (OBs) — 2023: R$ 120.000,00, 2025: R$ 4.200.000,00. Total pago no período: R$ 4.320.000,00 em 4 OBs, 2 órgãos. Concentração (HHI): 0.51 (alto; maior órgão = None%). Rating de risco corporativo: MÉDIO (score 42/100).