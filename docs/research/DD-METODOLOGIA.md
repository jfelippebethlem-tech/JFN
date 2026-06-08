# Due Diligence de classe mundial p/ auditoria de finanças públicas (RJ) — metodologia + mapa JFN

> Pesquisa encomendada (2026-06-08) para elevar o JFN ao padrão Kroll/Deloitte/Control Risks. Foco 2024-2026,
> fontes primárias. **Invariante:** ferramentas/fontes 100% gratuitas. **Altitude:** no setor público BR, "DD" =
> avaliação de **indícios sob contraditório**, nunca acusação (presunção de regularidade; dolo Lei 14.230/2021).

## 1. Tipos de DD (calibrados por risco — risk-based tiering)
- **Integrity/Reputational:** quem está por trás + reputação — sócios/administradores, litígios, criminal/cível,
  mídia adversa, PEP, idoneidade.
- **Financial:** capacidade econômica real — faturamento vs. valor dos contratos, porte, situação fiscal,
  substância. No público: **o que recebeu (OBs) vs. capacidade de executar** (porte, funcionários, capital).
- **Third-party/Vendor (FCPA/UK Bribery Act):** **>90% do enforcement FCPA em 40 anos veio de terceiros** → DD de
  fornecedor é o coração. Checa perfil, **beneficial ownership**, localização, sanções/PEP/mídia.
- **EDD (Enhanced):** acionada por gatilho (PEP, mídia adversa, jurisdição/estrutura opaca, sanção próxima, alto
  valor). Adiciona UBO multicamada, fonte de recursos, registros profundos, fontes humanas.

| Nível | Gatilho | Adiciona |
|---|---|---|
| Básica (screening) | toda contraparte | listas restritivas + cadastro |
| Padrão | risco médio | + UBO 1 nível, mídia, situação fiscal |
| **EDD** | PEP/opacidade/sanção/alto valor | + UBO multicamada, rede de sócios, fonte de recursos, fontes humanas |

Fontes: [GAN TPDD](https://www.ganintegrity.com/resources/blog/due-diligence/) · [GAN Levels](https://www.ganintegrity.com/resources/blog/levels-of-third-party-due-diligence/) · [Kroll Anti-Corruption](https://www.kroll.com/en/services/compliance-risk-and-diligence/screening-and-due-diligence/aml-compliance-due-diligence/anti-corruption) · [TI §13](https://www.antibriberyguidance.org/guidance/13-managing-third-parties/guidance) · [Ethisphere](https://ethisphere.com/wp-content/uploads/Third-Party-Due-Diligence-7.2.18.pdf)

## 2. Frameworks citáveis
| Framework | Recomenda | Uso no JFN |
|---|---|---|
| **ACFE Report to the Nations 2024** | corrupção em **48%** dos casos; **43%** detectado por **denúncia**; **84%** dos fraudadores ≥1 red flag; "associação próxima com fornecedor" (20%) = red flag mais correlato a corrupção; ~50% das fraudes = falha/burla de controle | calibra pesos do motor de risco; valida tese de concentração/sócio-comum |
| **OECD Good Practice / Anti-Bribery** | controles risk-based; DD de terceiros proporcional; monitoramento contínuo | justifica tiering risk-based |
| **FATF Rec. 24/25 + Guidance BO (2022-23)** | BO **adequado, preciso, atualizado**; combate a camadas/nominees/estruturas sem lógica | espinha dorsal do UBO/rede societária |
| **ISO 37001:2025** (2ª ed., 03/2025) | cl. **8.2 Due Diligence**; **conflito de interesse** com registro anual | seção COI + governança do parecer Lex |
| **Wolfsberg** | CDD/EDD bancária, BO | benchmark de processo |
| **TCU / TCE-RJ** | matriz **P×I**; anatomia do achado (situação→critério→causa→efeito→evidência→recomendação); red flags de licitação | já é a coluna do Lex (CERJ 122-123) |

Fontes: [ACFE RTTN 2024](https://www.acfe.com/-/media/files/acfe/pdfs/rttn/2024/2024-report-to-the-nations.pdf) · [OECD](https://www.justice.gov/sites/default/files/criminal-fraud/legacy/2010/05/07/oecd-good-practice.pdf) · [FATF BO 2023](https://www.fatf-gafi.org/content/dam/fatf-gafi/guidance/Guidance-Beneficial-Ownership-Legal-Persons.pdf.coredownload.pdf) · [ISO 37001:2025](https://www.iso.org/standard/37001) · [Wolfsberg](https://wolfsberg-group.org/resources)

## 3. Red flags → sinal de dado concreto (detector)
| Red flag | Detector computável | Fonte |
|---|---|---|
| **BO oculto** | cadeia PJ→PJ; UBO não fecha em PF; troca de sócios logo após constituição; vários sócios just-below-25% | FATF |
| **Shell/fachada** | sem funcionários (RAIS/eSocial vazio), capital ínfimo vs. contrato, CNAE incompatível, sede residencial/compartilhada | FATF + CGU |
| **Recém-criada** | `data_inicio_atividade` < N meses antes da 1ª OB; idade vs. valor | Receita CNPJ |
| **Concentração** | **HHI** por UG; share ≥60%; dependência mútua UG↔fornecedor | ACFE; CLAUDE.md |
| **Conflito de interesse** | sócio/admin = servidor da UG pagadora; parentesco com ordenador; CPF ∩ quadro | ISO 37001 8.2 |
| **PEP** | CPF de sócio/admin em agentes públicos/eleitos/parentes + mandato | Portal Transp. + TSE |
| **Laranja/nominee** | PF sócia de dezenas de empresas díspares; idade extrema; endereço baixa renda × capital alto; CPF recorrente em rede | FATF |
| **Endereço compartilhado** | N CNPJs no mesmo CEP+logradouro+nº (co-endereço) | **já feito** `cruzamento.py` |
| **Sobrepreço** | preço unit. > mediana/Painel p/ mesmo CATMAT, sem justificativa; outlier | TCU + dados abertos |
| **Fracionamento** | soma de dispensas mesmo objeto/fornecedor/UG em janela > teto; parcelas just-below-limite | Art. 89 Lei 8.666; já parcial |

Fontes: [FATF Concealment of BO](https://www.fatf-gafi.org/en/publications/Methodsandtrends/Concealment-beneficial-ownership.html) · [CNMP Fraudes Licitações](https://ojs.cnmp.mp.br/index.php/revistacnmp/article/download/88/32/227) · [Effecti](https://effecti.com.br/fraude-em-licitacao/)

## 4. Screening (3 trilhas; entrada + monitoramento contínuo)
- **Sanções BR (grátis, API):** CEIS, CNEP, CEPIM, CEAF — **Banco de Sanções CGU** via **API Portal da
  Transparência** (chave/token grátis) + download CSV. **Internacional:** OFAC SDN/Consolidated, ONU/UE. **RJ:**
  inabilitados TCE-RJ.
- **PEP:** CPF de sócios/admin × agentes públicos/eleitos (TSE) + parentes 1º grau; marcar mandato ativo.
- **Adverse media:** notícia negativa por nome/CNPJ classificada por severidade (aciona EDD); reusar
  `briefing.py`/GDELT.

Fontes: [Portal Transp. Sanções](https://portaldatransparencia.gov.br/sancoes) · [API](https://portaldatransparencia.gov.br/api-de-dados) · [Banco Sanções CGU](https://www.gov.br/corregedorias/pt-br/institucional/sistemas-correcionais/banco-de-sancoes-ceis-cnep)

## 5. Estrutura de relatório de classe mundial (JFN já ~80% aderente)
Capa/classificação → sumário executivo (top 5-10 riscos, 1-2 pág) → **rating P×I** (1-81, faixas) → findings matrix
(anatomia do achado) → áreas (cadastral/UBO, contratos/HHI/aditivos, financeiro OB vs. capacidade, litígios/sanções,
mídia) → **proveniência por dado (fonte+data+confiança)** [principal gap] → **scoring decomposto** (subescore por red
flag rastreável) → recomendações (imediato/curto/estrutural) → referências (TCU/TCE-RJ/ACFE/FATF/OECD/ISO 37001).
Princípio Kroll: declarar **qual nível de DD foi aplicado**.

Fontes: [Kroll risk-based](https://www.kroll.com/en/insights/publications/compliance-risk/due-diligence-safeguards-against-financial-crimes) · [Smartroom](https://smartroom.com/blog/due-diligence/how-to-write-a-due-diligence-report/) · [Aaron Hall risk matrix](https://aaronhall.com/due-diligence-risk-matrix/)

## 6. KYC/UBO/Beneficial Ownership
- **Limiar:** UBO = PF que possui/controla; convergência FATF/EU/FinCEN = **≥25%** direta ou indireta.
- **Apuração em camadas:** QSA direto → para cada sócio **PJ**, recursar até PF; **regra dos 50%** (PF com >50% de
  holding intermediária → rastrear proporcionalmente); participação efetiva = produto das frações; **controle além da
  propriedade** (voto, admin de fato, nominees informais — parentes/associados).
- **Fontes BR grátis:** QSA Receita (dados abertos); **Beneficiário Final** (IN RFB 2.119/2022, obrigação em 30
  dias); parentesco inferível (sobrenome+endereço+co-participação, heurística).

Fontes: [Moody's UBO](https://www.moodys.com/web/en/us/kyc/resources/insights/who-is-in-charge-here-brief-guide-to-ultimate-beneficial-owners-verification-legislation.html) · [25/50% rule](https://didit.me/blog/ubo-50-percent-rule/) · [IFC Review FATF 2024](https://www.ifcreview.com/articles/2024/april/ownership-vs-control-fatf-targets-soft-power/) · [Beneficiário Final IN 2.119](https://baptistaluz.com.br/guia-beneficiario-final/)

## MAPA PARA O JFN (técnica → onda/módulo → fonte BR grátis → aceite)
| # | Técnica | Onda/módulo | Fonte grátis | Critério de aceite |
|---|---|---|---|---|
| 1 | **Screening CEIS/CNEP/CEPIM/CEAF** | 10 Lex (`lex_sancoes.py`) + §3 relatório | API Portal Transp. (chave grátis)/CSV | CNPJ sancionado → 🔴 com processo/órgão/vigência; limpo → "sem registro"+data |
| 2 | Sanções internacionais (OFAC/ONU/UE) | 10 Lex | OFAC SDN CSV | match exato+fuzzy≥0,9 levanta flag; entidade SDN → positivo |
| 3 | **UBO multicamada + regra 50%** | 4 (`rede_societaria.py` recursão) | QSA Receita | sócio PJ → PF terminal + participação efetiva; soma PFs raiz ≈100%±tol |
| 4 | Nominee/laranja | 4 + 3 (grau no grafo) | QSA Receita | PF em ≥K empresas díspares sinaliza; top-N nominees no dossiê |
| 5 | Endereço compartilhado/fachada | 4 (`cruzamento.py` **já existe**) | `endereco_fornecedor` | `--clusters` agrupa co-endereço; regressão PLAZA/INOVA |
| 6 | Empresa recém-criada | 3 (regra) + 7 | Receita `data_inicio_atividade` | flag se 1ª OB < 6 meses pós-abertura; relatório mostra idade |
| 7 | Capacidade vs. recebimento | 7 + 3 | Receita (capital/porte/CNAE) + OBs | razão recebido/capital > P95 → incompatibilidade de porte |
| 8 | Concentração/HHI | 3 (`grafo_cartel.py` **já existe**) + 7 | OBs | HHI por UG; reproduz UG 316100 (99,8% num fornecedor) |
| 9 | PEP screening | 4 + 10 | Portal Transp. + TSE | CPF de sócio em agente público → PEP no dossiê |
| 10 | **Conflito de interesse** | 4 (QSA × quadro UG) + 10 | QSA + servidores Portal | interseção CPF (QSA ∩ servidores da UG) → COI (ISO 37001 8.2) |
| 11 | Fracionamento | 3 (`anomalias.py`/rules **parcial**) | OBs + contratos TCE-RJ | soma dispensas mesmo objeto+forn+UG em janela > teto; reproduz SCALLE |
| 12 | Sobrepreço | 3 + 7 | Painel Preços/TCU + CATMAT | preço unit > P90 sem justificativa → outlier; ≥1 item ponta-a-ponta |
| 13 | Adverse media | 4 (reuso `briefing.py`) + 10 | RSS/GDELT | notícia negativa por nome/CNPJ por severidade no dossiê; positivo → EDD |
| 14 | Matriz P×I + faixas | 7 (rating) | TCU (interno) | todo relatório imprime P×I (1-81)+faixa+heatmap reproduzível |
| 15 | Scoring decomposto | 3 (`anomalias.explicar_features` **já existe**) + 7 | interno | cada flag traz `porque` (sinal+peso); soma = score total |
| 16 | **Proveniência por dado (lineage)** — *gap principal* | 7 (refactor saída) + 4 | interno | cada achado carrega {fonte, URL/endpoint, data, confiança}; nada sem origem |
| 17 | Anatomia do achado | 10 Lex (**já existe**) | interno + TCE-RJ | cada achado: situação→critério→causa→efeito+evidência+recomendação |
| 18 | **Risk-based tiering** | 3 (`calibrar.py`) + 10 | interno | nível (Básica/Padrão/EDD) por gatilho; relatório declara o nível aplicado |

## Priorização
- **Quick wins:** #1 screening CEIS/CNEP (API grátis; já no backlog Onda 2), **#16 proveniência por dado** (maior
  salto de credibilidade Kroll), #10 conflito de interesse (interseção de CPF, dado já disponível).
- **Médio:** #3 UBO regra-50%, #9 PEP, #18 tiering, #6/#7 capacidade vs. porte.
- **Estrutural:** #12 sobrepreço, #2 sanções internacionais, #13 adverse media classificada.
- **Gap que mais separa do classe-mundial:** **#16 proveniência por dado + #18 declarar nível de DD**. O JFN já é
  forte em análise; falta cada afirmação ser rastreável à fonte e o relatório declarar a profundidade — exatamente
  o "indício a verificar, nunca acusação" que o projeto já adota.

> Nota: `mcp Bigdata.com` é orientado a mercado de capitais US/global, sem cobertura útil de fornecedores públicos
> BR — não usar p/ DD de fornecedor RJ.
