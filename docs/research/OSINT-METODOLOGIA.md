# OSINT para o JFN — Metodologia, Ferramental e Fontes (pesquisa citada, 2024-2026)

> Pesquisa encomendada (2026-06-08) para fundamentar as Ondas 4 (Grafo/Dossiê), 6 (Radar), 2 (conflito/PNCP),
> 5 (SEI) do JFN 2.0. **Invariante:** todas as ferramentas/fontes 100% GRATUITAS. Fonte primária deste resumo:
> agente de pesquisa multi-fonte (10 buscas + fetches de fontes primárias).

## 1. Framework de OSINT investigativo
**Ciclo de inteligência (espinha dorsal):** (1) Direção/Planejamento → (2) Coleta → (3) Processamento →
(4) Análise/corroboração → (5) Disseminação. Transforma dado bruto não-estruturado em inteligência acionável
([Ethos Risk](https://ethosrisk.com/blog/osint-the-intelligence-cycle/), [Springer](https://link.springer.com/chapter/10.1007/978-3-031-30592-4_4)).

**Pivoting:** de um identificador conhecido, pivotar para fontes adjacentes (sócio→empresas, endereço→empresas
no mesmo endereço, telefone/e-mail→outros registros). Tendência 2024-26: **entity resolution automatizada**.

**Link analysis:** entidades = nós, relações = arestas; visualização + algoritmos para achar conexões ocultas
(paradigma Maltego).

**Corroboração e cadeia de custódia:** evidência só vale se verificável. Padrão **ISO/IEC 27037**; regra prática
**screenshot + hash SHA-256 + timestamp**, arquivar para não poder ser apagado, registro de acesso
([osint.industries](https://www.osint.industries/post/handling-digital-evidence-our-ultimate-guide-to-forensic-osint)).

## 2. Técnicas por alvo
- **(a) Empresa:** percorrer a cadeia até o **UBO (beneficiário final — pessoa física real)**. Sinais de fachada:
  dados de registro inconsistentes, operação sem funcionários, mudanças inexplicadas de propriedade, faturamento
  duplicado. Cruzamentos: **co-endereço, contador/representante comum, telefone/e-mail compartilhado**
  ([osint.industries shells](https://www.osint.industries/post/cracking-the-shells-a-guide-to-osint-and-shell-companies)).
- **(b) Pessoa:** classificar **PEP** (cargo público relevante, últimos 5 anos); status **estende-se a familiares
  até 2º grau** ("PEP por relacionamento"). Pivotar p/ filiação partidária, bens, vínculos societários
  ([Coaf](https://www.gov.br/coaf/pt-br/assuntos/informacoes-as-pessoas-obrigadas/o-que-sao-pessoas-expostas-politicamente-peps),
  [AgeRio](https://www.agerio.com.br/pep-por-relacionamento/)).
- **(c) Rede/cartel:** **OECD Guidelines for Fighting Bid Rigging (update 2025)** — red flags: padrões anômalos de
  preço/lance, **rodízio de vencedores**, **propostas de cobertura**, divisão de mercado. "Screens" = estatísticas
  que sinalizam anomalia. UK CMA lançou IA (jan/2025) p/ detectar conluio em escala
  ([OECD 2025](https://www.oecd.org/en/publications/2025/09/oecd-guidelines-for-fighting-bid-rigging-in-public-procurement-2025-update_127880ea.html)).

## 3. Fontes OSINT gratuitas — prioridade BRASIL
| Fonte | Extrai | Acesso |
|---|---|---|
| Receita/CNPJ (BrasilAPI, dumps RFB) | QSA, endereço, CNAE, situação, capital | API REST (JFN já usa); dumps p/ bulk |
| **TSE Dados Abertos** | Doações, candidaturas, **filiação partidária**, prestação de contas | dadosabertos.tse.jus.br (CSV/TXT) |
| **Portal da Transparência — API** | CEIS, CNEP, CEPIM, CEAF, contratos, servidores, **PEP** | API REST chave grátis; PEP em download-de-dados |
| CEIS/CNEP (sanções) | Inidôneas/suspensas/punidas (Lei 12.846) | API Portal Transparência |
| **PNCP** (Lei 14.133) | Editais, contratos, atas, plano anual | API REST/JSON pública (swagger) |
| **Querido Diário** (DOs municipais) | Nomeações, dispensas, contratos (350+ municípios) | API `/gazettes` **sem auth**, ~60 req/min, `territory_ids` (IBGE) |
| **GDELT** (adverse media) | Mídia negativa global, GKG (pessoas/orgs/temas), tom −100..+100 | DOC 2.0 API + BigQuery; 15 min |
| **OCCRP Aleph** | 1bi+ registros (corp, sanções, leaks, tribunais) | grátis p/ jornalismo |
| **OpenSanctions** | Sanções globais (formato ftm) | datasets abertos |
| TCU/TCE-RJ, JusBrasil | Acórdãos, processos | scrape/consulta |

## 4. Adverse media / news monitoring
GDELT GKG: consultar entidade em todas as fatias de 15 min, rastrear tom, **alertar em spike negativo**. Pipeline:
DOC 2.0 API por entidade → **dedup** (mesma notícia em N veículos, agrupar por similaridade) → filtro de **tom** →
relevância. Bulk via BigQuery; tempo real via API.

## 5. Ferramentas OSINT → equivalente Python grátis (a replicar, não comprar)
| Ferramenta | Faz | Equivalente JFN grátis |
|---|---|---|
| Maltego | link analysis via transforms (pivots) | `networkx` + coletores JFN como transforms; viz `pyvis`/Gephi (GEXF) |
| SpiderFoot | automação OSINT, 200+ módulos (Python) | arquitetura de coletores plugáveis idempotentes |
| Aleph (OCCRP) | indexa docs+entidades, cross-reference | **followthemoney (ftm)** — modelo Person/Company/Asset/Address; `ftm export-gexf` → networkx |
| Linkurious | viz/análise de grafo fincrime | networkx + **Louvain/Leiden** (`python-louvain`/`igraph`/`leidenalg`) |

**Anéis de conluio/lavagem:** grafo + **Louvain/Leiden** (modularidade) p/ clusters + centralidade p/ atores-ponte;
ciclos pequenos = indício de layering (FATF 2024 recomenda advanced analytics).

## 6. Cuidados
- **LGPD (crítico):** base legal correta p/ o Poder Público em controle/anticorrupção = **cumprimento de obrigação
  legal/exercício de atribuição** (art. 7/23), **NÃO legítimo interesse** (Guia ANPD fev/2024). Documentar
  finalidade + proporcionalidade.
- **Anti-falso-positivo:** score = indício, nunca acusação. Exigir **corroboração ≥2 fontes** antes de "achado".
  Co-endereço/contador comum são sinais FRACOS isolados (contabilidades hospedam centenas de CNPJs) — ponderar por
  raridade/concentração. Registrar procedência de cada aresta.

## MAPA PARA O JFN (técnica → onda → lib grátis → aceite)
| Técnica/Fonte | Onda/módulo | Lib grátis | Critério de aceite |
|---|---|---|---|
| Grafo de Poder (sócios+servidores+doações+contratos+nomeações) | **4 Grafo+Dossiê** | `networkx`; `followthemoney`; export `pyvis`/GEXF | CNPJ semente → ≤2 hops sócios→empresas→servidores; GEXF abre no Gephi |
| Entity resolution (mesmo nome/CPF em fontes distintas) | **4** | **Splink** (DuckDB); fallback `recordlinkage`/`dedupe` | dedup da base de sócios; precision ≥0,9 em amostra de 200 pares |
| Pivoting/co-endereço/contador/tel-email comum | **4 Dossiê** | `networkx`+`pandas` | "empresas no endereço X" / "CNPJs do contador Y" corretos; sinal FRACO por padrão |
| Doação↔contrato (doador↔fornecedor) | **2 conflito/PNCP** | TSE CSV + PNCP API (`requests`); join DuckDB | cruzar doadores TSE × fornecedores PNCP de uma UG (ex. ITERJ 133100) e listar coincidências |
| Cartel (rodízio/screens/cobertura) | **2 PNCP** | `networkx` + `pandas`; `leidenalg`/`python-louvain` | matriz licitante×edital de uma UG → flag rodízio quando co-bidding/HHI > limiar (reproduzível) |
| PEP + parentesco 2º grau | **4 Dossiê** / 2 | download PEP Portal Transp. (`requests`) | servidor/sócio → flag PEP + vínculo de parentesco quando presente |
| CEIS/CNEP (sanções) | **2** | API Portal Transp. (chave grátis) | fornecedor sancionado flagueado com data/órgão |
| Diários Oficiais (nomeações/dispensas) | **5 SEI** + 4 | Querido Diário `/gazettes` (`requests`) | busca por nome/CNPJ num município (IBGE) → excertos datados; respeita rate-limit |
| Adverse media 24/7 por entidade | **6 Radar** | GDELT DOC 2.0 (`requests`); dedup `rapidfuzz` | alvo → coleta+dedup+tom → alerta Telegram quando tom<limiar |
| Community detection / anéis | **6 Radar** + 4 | `python-louvain`/`igraph`+`leidenalg`; centralidade `networkx` | Louvain → comunidades estáveis; top-centralidade lista pontes (seed determinístico) |
| Sanções globais / leaks | **4** (enriquecimento) | datasets **OpenSanctions** (ftm) offline | ingestão casa ≥1 entidade conhecida da base |
| Cadeia de custódia | transversal | `hashlib` SHA-256 + timestamp | cada coleta grava {url,sha256,ts,fonte}; re-hash reproduz |
| Guard LGPD | transversal | metadado de finalidade/base legal | cada pipeline declara base legal; ausência bloqueia ingestão |

### Prioridades de implementação (do agente)
1. **followthemoney (ftm)** como modelo canônico de entidades do Grafo (Onda 4) — interopera com Aleph/OpenSanctions, exporta p/ networkx/Gephi.
2. **Splink sobre DuckDB** (já no stack) p/ entity resolution sem dados de treino.
3. **Onda 6 Radar = GDELT DOC 2.0** p/ adverse media, dedup `rapidfuzz`, alerta via Yoda/Telegram.
4. **Cartel screens (Onda 2)** começam simples: matriz licitante×edital em pandas antes de ML.

> Bibliotecas novas a avaliar (todas grátis/OSS): `followthemoney`, `splink`, `python-louvain`/`leidenalg`/`igraph`,
> `pyvis`, `rapidfuzz`. Confirmar instalação CPU-only e pin em `requirements.txt` na onda que as usar.
