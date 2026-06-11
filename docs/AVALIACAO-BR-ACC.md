# Avaliação & agregação do br-acc (enioxt/br-acc) — para o JFN

> Repo de referência: grafo Neo4j de dados públicos BR anticorrupção (~26 labels, 25+ relações, 44 fontes,
> 83M nós). **Decisão-mãe (dono): NÃO adotar Neo4j** — JFN segue SQLite + networkx (grátis, VM-safe). Daqui
> levamos (a) a **lista de fontes** p/ ativar OSINT dormente e (b) o **modelo/técnicas de resolução de
> entidade**. Avaliado em 2026-06-11. Clone efêmero em `/tmp/br-acc` (não versionar).

## 1. Gap de fontes (br-acc × providers do JFN)

JFN **já cobre** (em `compliance_agent/providers/`): registry (brasilapi/opencnpj/cnpjws/cnpjpw), sanctions
(CEIS/CNEP + **opensanctions**), ownership (**gleif**/opencorporates), leaks (**offshoreleaks**), eleitoral
(**tse_doador_contrato**), gazettes (querido_diario), links. Benefício/PEP CGU agora wired no DD (Loop 2).

**Dormentes a ativar** (provider existe, falta ligar no produto): GLEIF (ownership cadeia societária),
OffshoreLeaks (ICIJ), OpenSanctions (PEP global, complementa o PEP/CGU), TSE×contrato (doador↔fornecedor).

**Novas (lacuna real no JFN)** — todas grátis/sem auth, fonte confirmada no br-acc:
| Fonte | Endpoint | Rende | Valor p/ JFN |
|---|---|---|---|
| **CGU Leniência** | portaldatransparencia.gov.br/download-de-dados/acordos-leniencia | acordo, empresa, termos | red flag direto de fornecedor |
| **CEPIM** (convênios) | …/download-de-dados/cepim | convênio, impedimento | já citado no JFN; confirmar ingestão |
| **PGFN dívida ativa** | …/download-de-dados | débito tributário PJ/PF | capacidade econômica (anti-fachada) |
| **IBAMA embargos** | …/download-de-dados | embargo ambiental | "embargada que vence contrato" |
| **DataJud (CNJ)** | cnj.jus.br/sistemas/datajud (Bearer `DATAJUD_API_KEY`) | processos judiciais | litígios do fornecedor |
| **CPGF / Cartão** | …/download-de-dados/cpgf | gasto com cartão público | desvio de cartão corporativo |
| **Renúncias fiscais** | …/download-de-dados/renuncias/{ano} | benefício fiscal por PJ | exposição fiscal |
| **CAGED/RAIS** | MTE | nº de empregados por CNPJ | **anti-laranja: muito contrato × ~0 empregados** |

> Priorização (alavancagem × custo): CAGED/RAIS (anti-laranja por headcount), PGFN, Leniência. Todas
> entram como `providers/*` com `Resultado` padronizado (proveniência/INDISPONÍVEL — roadmap P0).

## 2. Modelo de grafo & resolução de entidade (o que vale copiar)

- **Não-destrutivo + confiança + método**: ligações como aresta com `{confidence, method, evidence,
  run_id}`, preservando os nós-fonte (auditável). Adotar no grafo networkx do JFN.
- **★ Ponte de CPF mascarado (middle-6)** — `scripts/link_partners_probable.cypher`. O QSA público mascara
  o CPF como `***.XXX.XXX-**`, **expondo os 6 dígitos do meio** (pos. 4-9). Cruzando `(nome + middle6)`
  contra um corpus de CPFs completos conhecidos, **par 1:1 = identidade** (confiança 0,85; guarda de
  ambiguidade por frequência de nome). **ADOTADO** no JFN: `compliance_agent/resolucao_cpf.py` (corpus =
  `ordens_bancarias.favorecido_cpf/nome`, 59,6k PF), wired no DD p/ destravar H-BENEFICIO de sócio mascarado.
- **Splink (P0 do roadmap, confirmado)** — `entity_resolution/config.py`: dedupe com Jaro-Winkler no nome
  (limiares 0,9/0,8) + ExactMatch em CPF e data de nascimento; blocking por `cpf` e `name`; backend **duckdb**
  (não precisa Neo4j). É o blueprint direto p/ a resolução de entidade do JFN (manter duckdb/SQLite).
- **Score** — `services/score_service.py`: percentis log-scale de volume financeiro (100k→p25 … 1B→p99) +
  bônus por evidência (sancionada+contrato → +60; embargada+contrato → +50; emenda+contrato → +20). Útil como
  referência p/ calibrar o ensemble de anomalia do JFN (PyOD/SHAP, roadmap).
- **Regras de cruzamento** (livres/VM-safe): co-endereço (já no JFN H-COEND); **sócio→doação→contrato**
  (triangulação temporal — alvo do TSE×contrato dormente); **sancionada/embargada que ainda vence licitação**.

## 3. Decisões

- **NÃO** Neo4j/Redis/React stack — JFN fica SQLite/networkx/FastAPI atual.
- **Adotado já:** ponte CPF mascarado (`resolucao_cpf.py`) — destrava H-BENEFICIO (Loop 2).
- **Próximo (P0):** Splink (config br-acc como base) + padronizar `providers/base.Resultado`; depois ativar
  os providers dormentes nos produtos e ingerir CAGED/RAIS (anti-laranja por headcount) e PGFN.
