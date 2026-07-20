# PARECER JURÍDICO PRELIMINAR — SNAPSHOT ENGENHARIA E SERVICOS LTDA
### Avaliação fático-jurídica de contratação, licitação e pagamentos

*Tomada de contas preliminar — Direito Administrativo e Controle Externo (TCU/TCE-RJ)*

**CNPJ:** 11.222.333/0001-81  |  **Data:** 2026-07-06  |  **Analista:** Controle Externo (automatizado)
**Classificação (modelo CGE-RJ — Decreto 47.408/2020):** Nota Técnica **SEM Achado**.
**Grau de atenção:** 🟢 **VERDE** — sem indícios relevantes nos dados disponíveis — presunção de regularidade mantida.

---

## I. IDENTIFICAÇÃO

- **Fornecedor:** SNAPSHOT ENGENHARIA E SERVICOS LTDA (CNPJ 11.222.333/0001-81)
- **Processos SEI vinculados (origem das OBs):** 0 identificado(s) na base correlacionada (SIAFE); **0 lido(s) na íntegra** nesta análise.

## II. FATOS — processos administrativos

> Ainda não há processos SEI correlacionados a este CNPJ na base. **Diligência:** rodar a coleta SIAFE (tela OB Orçamentária) e a correlação para puxar os processos.

## II-B. LEITURA DOS PROCESSOS SEI (íntegra)

> Não houve leitura de íntegra nesta execução (sem processos correlacionados ou leitura desabilitada).

## II-C. CONTRATOS E COMPRAS DIRETAS — TCE-RJ (Dados Abertos)

> Não há contratos nem compras diretas deste CNPJ na base de Dados Abertos do TCE-RJ. Isso pode ocorrer quando a contratação é municipal, federal, ou ainda não publicada — **diligência:** confirmar no PNCP e no próprio processo SEI.

## II-E. INVESTIGAÇÃO DE DUE DILIGENCE — empresa de fachada / laranja

*Bateria de hipóteses investigativas (cadastro Receita + base de OBs + OSINT). Base legal: controle externo e fiscalização (CF art. 70-71; LGPD art. 7º,II e 23). **Honesto:** indício merece apuração, nunca acusação; **INDISPONÍVEL ≠ ausência de risco**; CPF de pessoa física mascarado (LGPD).*

**Grau da investigação:** 🟢 · score 0/100 · 0 fato(s) confirmado(s), 0 indício(s) a apurar.

Nenhum indício de fachada/laranja identificado nas hipóteses verificáveis (não exclui achados em fontes não disponíveis nesta varredura).

> Nenhuma hipótese de fachada/laranja se confirmou nas fontes verificáveis nesta varredura.

> **Cobertura da investigação (honestidade):** endereco residencial: verificado (sem marcador); geocode: não solicitado; coendereco: verificado (nenhum); capital: INDISPONIVEL; recencia: verificado; situacao cadastral: verificado; porte: verificado; pep: INDISPONIVEL (sem chave PORTAL_TRANSPARENCIA_KEY); beneficio social: INDISPONIVEL (sem chave PORTAL_TRANSPARENCIA_KEY).

> **Veredito raciocinado (IA):** veredito LLM desligado (JFN_VEREDITO_LLM_DISABLED) — os sinais determinísticos acima permanecem válidos por si (degradação honesta).

## II-H. ANÁLISE FORENSE QUANTITATIVA (contabilidade forense)

*Técnicas de auditoria forense sobre a série de OBs do alvo. Regra de leitura: cada teste isolado é RÉGUA, não prova — o valor probatório nasce da convergência (ver Triangulação, IV-B).*

### Lei de Benford (1º dígito)

> Não aplicado: amostra insuficiente (3 < 100 OBs) — o teste perde potência estatística e afirmá-lo seria fabricar precisão (INDISPONÍVEL ≠ 0).

### Valores redondos

Das **3** OBs ≥ R$ 1.000,00: **100,0%** fecham em milhar exato (3 OBs) e **100,0%** em centena exata. Medições reais raramente fecham redondo; estimativas, arbitramentos e faturas combinadas fecham. Tarifas públicas, aluguéis e parcelas contratuais fixas são exceções LEGÍTIMAS — interpretar junto com o objeto.

### Sazonalidade (valor pago por ano × mês)

| Ano | jan | fev | mar | abr | mai | jun | jul | ago | set | out | nov | dez | Total |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2023 | — | — | **120,00k** | — | — | — | — | — | — | — | — | — | R$ 120.000,00 |
| 2025 | — | **2.400,00k** | — | — | — | — | — | **1.800,00k** | — | — | — | — | R$ 4.200.000,00 |

*Células em **negrito** concentram ≥25% do ano. Dezembro forte recorrente = corrida de empenho (conferir liquidação real — arts. 62-63 da Lei 4.320/64).*

### Cadência por órgão (regularidade da execução)

| Órgão | OBs | Total (R$) | Meses ativos | Média/mês ativo (R$) | Maior OB (R$) | Janela |
|---|---:|---:|---:|---:|---:|---|
| SEC ESTADUAL DE OBRAS | 5 | 2.520.000,00 | 5 | 504.000,00 | 2.400.000,00 | 2023-03→2025-02 |
| FUNDACAO SAUDE | 1 | 1.800.000,00 | 1 | 1.800.000,00 | 1.800.000,00 | 2025-08→2025-08 |

*Serviço contínuo saudável = muitos meses ativos com média estável. Poucos meses com OBs gigantes = surto (obra/aquisição pontual ou pagamento acumulado a examinar).*

### Linha do tempo forense

| Data | Evento |
|---|---|
| 2022-11-01 | Abertura do CNPJ na Receita Federal |
| 2023-03-10 | Primeira OB estadual observada (R$ 120.000,00) |
| 2024-06-01 | Entrada de sócio/administrador: FULANO SNAPSHOT |
| 2025-02-15 | Maior OB do período (R$ 2.400.000,00) |
| 2025-08-20 | Última OB observada (R$ 1.800.000,00) |

*A cronologia é a espinha da prova indiciária: sócio que entra DEPOIS do dinheiro, primeira OB colada na abertura do CNPJ e picos sem contrato novo são os nós a puxar.*

## III. MATRIZ DE ACHADOS (anatomia do achado de auditoria)

*Modelo TCU/ISSAI/CGU: **critério × condição → causa → efeito**, com evidência e recomendação (metodologia de controle externo).*

> **Nota Técnica SEM Achado** — não há indício que sustente um achado. Mantém-se a presunção de regularidade dos atos administrativos.

## III-B. DETALHAMENTO DOS INDÍCIOS (red flags do controle externo)

Nenhum indício automático disparou a partir dos dados financeiros nem da leitura documental disponível. Mantém-se a presunção de regularidade.

## IV. MATRIZ DE RISCO (P × I — metodologia TCU)

| Indício | P (1-5) | I (1-5) | Score | Faixa |
|---|---:|---:|---:|---|
| — | — | — | — | — |

## III-C. TRIAGEM POR INDICADORES DE RISCO DE FRAUDE

> Metodologia de indicadores de risco em licitações (B. V. Mondo). **Indício para priorização/diligência — nunca prova nem acusação.**

_Nenhum indicador de risco disparado a partir dos dados disponíveis._

## IV-B. ANÁLISE DE MÉRITO

> **Régua empírica (aprendida da base histórica):** Base: 1.138.236 OBs (chave única numero_ob+ug+exercício), 152 UGs, 74.782 fornecedores, exercícios 2019–2026. p90 do valor de OB ≈ R$ 148.953,29.

**1. Perfil do fornecedor e aderência cadastral.** Trata-se de empresa fornecedora do Estado, com exposição de **R$ 4.320.000,00** em 6 ordens bancárias junto a 2 órgão(s) no período (janela observada: 2023-03-10 a 2025-08-20). A pulverização entre órgãos, isoladamente, não indica irregularidade.

No plano cadastral, a empresa recebeu a primeira OB estadual **0,4 ano(s)** após a abertura do CNPJ (2022-11-01) — contratação de pessoa jurídica recém-constituída não é vedada (livre iniciativa, art. 170 CF/88), mas desloca o exame para a **demonstração concreta de capacidade técnica e econômico-financeira** exigível na habilitação (arts. 62, 66-69 da Lei 14.133/2021); histórico operacional inexistente somado a exposição dessa ordem é indício clássico de interposição a apurar; a exposição equivale a **432×** o capital social registrado (R$ 10.000,00) — razão dessa ordem não é ilícita per se, porém esvazia a função de garantia do capital e reforça a necessidade de aferir a qualificação econômico-financeira efetivamente exigida e demonstrada (art. 69 da Lei 14.133/2021: balanço patrimonial, certidões, capital mínimo ou garantia).

**2. Padrão temporal.** No eixo do tempo, o valor pago saltou **3.400%** de 2023 (R$ 120.000,00) para 2025 (R$ 4.200.000,00) — escalada dessa magnitude pede confronto com os instrumentos que a lastrearam (novos contratos? aditivos? — teto de 25%/50% do art. 125 da Lei 14.133/2021; sucessivos aditivos que dobram o objeto configuram burla ao dever de licitar).

**5. Triangulação (análise cruzada).** Linhas examinadas — Financeira (OBs SIAFE/TFE): ✓ padrão de pagamento sem disparo. **nenhuma linha** de evidência disparou — as fontes independentes se corroboram no sentido da regularidade; a presunção de legitimidade sai REFORÇADA do cruzamento.

**6. Síntese e standard probatório.** Não há indícios relevantes nos dados disponíveis. Reitere-se o standard: os apontamentos são **indícios** sob **presunção de legitimidade** dos atos administrativos (o ônus de provar o vício recai sobre quem o invoca — Meirelles); na interpretação das condutas valem os arts. 20-22 da LINDB (consequências práticas da decisão; obstáculos e dificuldades REAIS do gestor; primazia da realidade sobre o formalismo) e só o **erro grosseiro** responsabiliza o agente público (art. 28 LINDB). A confirmação de qualquer achado depende de diligência documental nos processos SEI (edital/TR, pesquisa de preços, atas, atestos, medições) e de **contraditório** (art. 5º, LV, CF/88). Este parecer **não** constitui juízo de irregularidade, improbidade ou crime.

## IV-D. DEFESA CONTRA SI MESMO — PASSO EXCULPATÓRIO

*Para cada indício, a **explicação inocente mais plausível** e se os dados a refutam. Achado cuja defesa **não é refutada** pelos dados fica apenas como **monitoramento** — não representação (presunção de legitimidade; a dúvida sobre a economicidade favorece o gestor).*

> Sem indícios a submeter ao passo exculpatório — presunção de regularidade mantida.

## IV-C. Proposta preliminar de sanção administrativa

> **Não se propõe sanção nesta fase.** Todos os indícios tiveram a explicação inocente considerada **plausível** (passo exculpatório) e permanecem como **monitoramento**, não representação. Sanção administrativa pressupõe achado com defesa **afastada pelos dados** e, para multa, **dano efetivo mensurado** ou **dolo indiciado** — ausentes aqui. Indício ≠ acusação.

## V. CONCLUSÃO — GRAU DE ATENÇÃO

**🟢 VERDE.** Sem indícios relevantes nos dados disponíveis — presunção de regularidade mantida.

## VI. RECOMENDAÇÕES DE ENCAMINHAMENTO

> **Destinatário recomendado:** nenhum encaminhamento específico — sem achado que indique competência de controle externo, MP, CADE ou CGE (presunção de regularidade).

- **Diligência documental:** confrontar, nos processos SEI, o edital/TR (especificações), a pesquisa de preços (cesta — Acórdão 1875/2021-TCU), o mapa de licitantes (sócios/endereços) e os atestos/medições.
- **Controle externo:** havendo indício de dano, representar ao **TCE-RJ** (jurisdição sobre a despesa estadual).
- **Demais órgãos:** ciência ao **MP-RJ** (improbidade) e ao **CADE** (conluio/bid rigging, Lei 12.529) se cabível; PAR (Lei 12.846) e ciência à **CGE-RJ** (controle interno).
  > Cautela na qualificação de improbidade (Lei 8.429/92 pós-Lei 14.230/2021): exige-se **dolo** nos arts. 9/10/11 (**STF Tema 1199, ARE 843989/PR**) e, no **art. 10**, **dano efetivo** — fim do dano presumido (**STJ REsp 1.929.685/TO**, 1ª T., 2024). Aponta-se o indício; a tipificação é do MP-RJ/Judiciário.
  > Esfera penal (referência, não imputação): desvios podem tangenciar **CP arts. 312 (peculato), 316 (concussão), 317 (corrupção passiva), 333 (corrupção ativa)** e os crimes licitatórios da **Lei 14.133, arts. 337-E a 337-P**. Dispensa/inexigibilidade irregular hoje é **art. 337-E CP** (ex-art. 89/8.666 — *continuidade típica*, STJ REsp 2.069.436, não abolitio). Confirmar conduta e dolo antes de qualquer juízo.
  > Base normativa estadual (RJ): Lei 14.133 regulamentada pelo **Decreto 47.680/2021** + **Resoluções SEPLAG 179/180/2023** e **PGE 4.937/2023**; controle interno na **CGE-RJ** (Lei 7.989/2018); o rito de Tomada de Contas é a **Deliberação TCE-RJ 279/2017**, cujo **art. 7º** exige apenas *elementos que indiquem* — o mesmo limiar de **indício** deste parecer.

## VII. RESSALVAS

> 1. Os apontamentos são **INDÍCIOS**, sujeitos a contraditório e ampla defesa. 2. Vigora a **presunção de legitimidade** dos atos administrativos (dúvida sobre economicidade favorece o gestor — TCE-RJ, Proc. 101.922-9/12). 3. **Não se afirma crime, improbidade ou dolo** — competência do TCE-RJ, MP-RJ e Judiciário. 4. Conclusões limitadas aos dados/documentos analisados; lacunas geram **diligência**, não condenação. 5. A leitura automática do SEI extrai texto público; trechos podem faltar por OCR/restrição — sempre confirmar na fonte.

_Parecer gerado automaticamente por sistema de controle externo em 2026-07-06. Fundamentação em doutrina de Direito Administrativo e controle externo (doutrina, improbidade pós-14.230, controle e RJ — CERJ arts. 122-123). Não substitui parecer jurídico formal._