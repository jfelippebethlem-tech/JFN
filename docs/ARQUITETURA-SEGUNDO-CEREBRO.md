# ARQUITETURA DO SEGUNDO CÉREBRO — JFN

| | |
|---|---|
| **Documento** | Diagnóstico medido, arquitetura-alvo e plano de implantação do segundo cérebro do ecossistema |
| **Pedido do dono** | 18/11/2026 — "o motor e a arquitetura de automelhoria funciona e registra no second brain? khoj, obsidian, gitnexus, graphify" · "faça também a melhor arquitetura para segundo cérebro" |
| **Medição** | 18/11/2026, 22:10–23:00 (BRT), VM-1 `jfn-core` e VM-2 `JFN-Agent-2` (somente leitura na VM-2) |
| **Estado** | Ponte automelhoria/perícias → cérebro **implantada** (`compliance_agent/cerebro_ponte.py`); demais itens são proposta com custo (§7) |
| **Sucessor** | `docs/ARQUITETURA-SEGUNDO-CEREBRO-ALVO.md` (19/11/2026) — mediu a busca (recall@10 33/56 → 56/56), conferiu o estado da arte na fonte e **substitui** o §3 e as linhas "Khoj" e "hermes_rag" do §4.3 deste documento |
| **Irmãos** | `docs/ARQUITETURA-DE-CERTEZA.md` (fatos numéricos) · `docs/AUTOAPRIMORAMENTO-JFN.md` (laço da perícia) · `config/propagacao.yaml` (mapa de dependências) |

---

## 1. Resposta direta

> **A automelhoria registrava no segundo cérebro só pela metade.** A automelhoria GERAL (sensores de engenharia)
> registra: escreve uma nota por rodada no Obsidian e o jfn-brain a indexa em até 10 min. A automelhoria DA PERÍCIA
> (lição → portão → campeão) **não registrava nada por código**: 7 versões de rubrica e 2 reprovações no portão
> existiam só em `data/autoaprimoramento/auto.db`. As 78 perícias por agente de hoje tinham 78 lições e nenhuma
> entrada governada. Khoj está parado; GitNexus e graphify são grafos de código e documentação — não recebem lição
> nem fato de caso, e não devem receber.

| Camada | Automelhoria geral (engenharia) | Automelhoria da perícia (portão) | Perícias por agente (78 laudos) |
|---|---|---|---|
| **Obsidian** (`~/vault`) | SIM — `aprendizados/automelhoria/<data>.md`, última 18/11 21:42 | NÃO → **SIM** (`jfn/automelhoria-licoes.md`) | parcial (notas de caso feitas à mão) → **SIM** (`jfn/pericias-agente/`) |
| **jfn-brain — busca** (notas) | SIM — a nota de 18/11 é devolvida por `brain_search` | NÃO → **SIM** (via nota) | parcial → **SIM** (via nota) |
| **jfn-brain — memórias** (fatos com id) | NÃO | NÃO por código (2 memórias gravadas à mão, #460 e #464) → **SIM** (`autoaprimoramento:<versão>`) | à mão, casos 🔴 (ids ~476–485) → **SIM** (`pericia-agente:<tag>`, `licao-pericia:<tag>`) |
| **Khoj** | NÃO (serviço parado) | NÃO | NÃO |
| **GitNexus** | não se aplica (código) | não se aplica | não se aplica |
| **graphify** | não se aplica (só o `GRAPH_REPORT.md` vai ao cérebro) | não se aplica | não se aplica |

"→ **SIM**" = passou a registrar com a ponte implantada neste trabalho (§6).

---

## 2. Diagnóstico medido — camada por camada

| # | Camada | Onde roda | Vivo? (medido) | Volume | Papel real hoje | Problema |
|---|---|---|---|---|---|---|
| 1 | **jfn-brain** (API + MCP) | VM-2, `brain-api.service`, porta 8443 (Tailnet), Postgres 16 | SIM — ativo; indexador a cada 10 min (última indexação 18/11 21:57 BRT) | 853 notas · 7.106 trechos · 4.363 arestas · 417 memórias ativas | Memória comum dos agentes: busca híbrida nas notas + memórias com `supersedes` e `valid_to` | Grafo só de wikilinks e de `subject`; sem índice por entidade (CNPJ/processo/UG) |
| 2 | **Registro de envio** (`cerebro_compartilhado`, `data/propagacao.db`) | VM-1, despachante `*/5` | SIM — último envio 18/11 19:32 | 351 chaves: 347 gravadas, 0 pendentes, 4 recusadas (aparência de segredo) | Fila idempotente por CHAVE estável; correção vira `supersedes`; barra CPF/e-mail/segredo | 214 das 351 são `conferencia-opus:*`; nenhuma de automelhoria ou perícia por agente |
| 3 | **Obsidian** (`~/vault`) | VM-1 + Syncthing + backup git 03:25 | SIM | 828 notas; 111 casos; 107 aprendizados; 199 notas tocadas em 18/11 | Curadoria humana + retratos gerados (`jfn/`) | Três geradores escrevem em pastas diferentes; `processos/` (169 notas) é de outro produtor |
| 4 | **Khoj** (piloto) | VM-2, `khoj-piloto.service` | **NÃO — parado desde 18/11 11:40 BRT** (SIGTERM; vigia parou junto). Postgres do piloto (5433) e o timer de reindexação seguem ligados | — | Busca semântica do vault, sem LLM | **Duplica** a busca do jfn-brain sobre o mesmo vault; hoje é só custo (Postgres + reindexação noturna de um serviço parado) |
| 5 | **hermes_rag** | VM-1, `data/rag/embeddings.npy` | SIM — 895 arquivos, 9.056 vetores (reindexa se mudou) | 9.056 trechos | Recuperação para o Hermes/Yoda (lei + vault) | **Terceiro índice** do mesmo vault (jfn-brain, Khoj, hermes_rag) |
| 6 | **GitNexus** | VM-1, `.gitnexus/`, MCP vivo há 23 h | **Índice de 08/11/2026 — 508 commits atrás.** A reindexação semanal (dom 04:00) aborta em `native-worker-abort` | 29.042 símbolos · 66.506 relações · 664 fluxos | Grafo de CÓDIGO (quem chama, impacto) | Respostas de impacto estão cegas para 10 dias de código (inclui `certeza/`, `autoaprimoramento/`) |
| 7 | **graphify** | VM-1, `graphify-out/` | SIM — grafo de 18/11 19:59 (47,6 MB) | `GRAPH_REPORT.md` 511 KB → cérebro a cada 3 h (1 nota) | Conceitos e comunidades de código/documentação | Sobrepõe o GitNexus em código; o valor próprio é documentação/conceito |
| 8 | **Memória dos agentes** (`~/.claude/.../memory`) | VM-1 | SIM | 352 arquivos; `MEMORY.md` com 203 linhas (limite 200 — 3 cortadas) | Diretrizes e decisões do dono, carregadas toda sessão | Só 33 das 352 chegaram ao cérebro (a sonda só vê arquivo alterado desde 14/11); índice estourado |
| 9 | **GEP** (genes no prompt) | VM-1, hook `UserPromptSubmit` | SIM — 1.437 eventos; **`genes.json` sem mudança desde 10/09/2026** | 40 genes | Injeta até 3 lições por prompt | Lições congeladas, fora de qualquer portão |
| 10 | **Certeza** (`data/certeza/certeza.db`) | VM-1, derivado da propagação | SIM — última rodada 18/11 21:38 | registro só-acréscimo de fatos NUMÉRICOS | Fonte da verdade de número publicado (id, nível, P1–P8) | Só cobre o que está declarado em `fatos:` no mapa |
| 11 | **Automelhoria geral** | VM-1, cron `40 */3` | SIM — relatório 18/11 21:42 | fila única aberto/curado/REINCIDIU | Saúde de engenharia | — |
| 12 | **Automelhoria da perícia** (`auto.db`) | VM-1, **sem agendamento** | Último ciclo 18/11 17:41 (manual) | 7.720 laudos-versão · 1.091 conferências · 7 versões (1 campeã, 4 candidatas, 2 reprovadas) · **0 laudos em sombra** · fila da fonte: 30 itens sem consumidor | Laço lição → portão → sombra → campeão | O laço não fecha (avaliação independente de 18/11); nada ia ao cérebro |
| 13 | **Metacognição** (`jfn-metacognicao.timer`) | VM-1, diário 06:51 | SIM | backup `hermes-memoria/` 16 MB em 18/11 | Lições `pericia:*` para o Hermes | Segunda via de lição no prompt, sem portão |

**Sobreposições:** três índices semânticos do mesmo vault (linhas 1, 4, 5); dois grafos de código (6, 7); três vias de
lição para prompt (9, 12, 13) e só uma com portão. **Órfãos:** Khoj (parado com satélites ligados); `fila_fonte.json`
(sem consumidor); `laudo_sombra` (vazio); 319 arquivos de memória fora do cérebro.

---

## 3. Estado da arte — o que vale para esta casa

Referências conceituais, citadas de conhecimento do modelo e **não reconferidas na fonte nesta sessão** (não citar
externamente sem conferir):

| Linha | Ideia central | O que o JFN adota | O que não adota |
|---|---|---|---|
| **MemGPT / Letta** (2023) | Memória em camadas: núcleo sempre no contexto, arquivo sob demanda | `MEMORY.md` = núcleo (≤ 200 linhas); cérebro = arquivo | Agente reescrevendo o próprio núcleo sem portão |
| **A-MEM / Zettelkasten** (2025) | Nota atômica, ligada, que evolui quando chega nota nova | Um fato por memória, chave estável, `supersedes` | Evolução automática por LLM de fato de caso (risco de deriva) |
| **GraphRAG** (2024) | Grafo de entidades + resumos por comunidade para pergunta global | Índice de entidade determinístico (CNPJ, processo, UG) | Extração de entidade por LLM sobre todo o acervo (custo e alucinação de aresta) |
| **Zep / Graphiti** (2025) | Grafo temporal: cada aresta tem validade; fato novo invalida o antigo sem apagar | `valid_to` + `supersedes` no cérebro; `fato_versao` só-acréscimo na certeza | Servidor de grafo dedicado (Neo4j) numa VM de 2 vCPU |
| **LLM-wiki (Karpathy)** | A fonte reescreve a página existente; a wiki é o artefato | `~/vault/jfn/` regerado pela fonte; nota só é regravada se mudou | Página de caso reescrita por modelo sem conferência |
| **ACE — Agentic Context Engineering** (2025) | Gerador → refletor → curador; o manual cresce por deltas pequenos, nunca por reescrita inteira | Lição = item com id na taxonomia; entra no prompt só pela versão campeã | Curador que é o próprio modelo (aqui o curador é o portão determinístico) |

O que a casa já tem e a literatura não dá de graça: **nível de prova** (0 modelo de volume · 1 leitura por agente ·
2 fonte primária conferida por código) e **portão determinístico** antes de qualquer lição chegar a um prompt.

---

## 4. Arquitetura-alvo

### 4.1 Uma fonte da verdade por tipo de conhecimento

| Tipo de conhecimento | Fonte da verdade (única) | Identidade | Versão / tempo | Nível de prova | Quem escreve |
|---|---|---|---|---|---|
| **Número publicado** (valor, contagem, percentual) | `certeza.db` › `fato_versao` | `familia:chave:medida` | Só-acréscimo; versão anterior fica com a data em que valia | `nivel_prova` + estado, julgados por P1–P8 | Declaração `fatos:` no mapa de propagação |
| **Fato de caso** (o que se sabe de processo/empresa) | Laudo/derivado de origem (`data/…`) → memória no jfn-brain | Chave estável (`pericia-agente:<tag>`, `derivado:<id>` …) | `supersedes` + `valid_to` | Medido por código na ponte (citação literal no processo; OB no SIAFE) | Só código (`cerebro_compartilhado.registrar`) ou `brain_remember` de sessão |
| **Narrativa de caso** (dossiê, hipótese, próximo passo) | `~/vault/casos/` (curado) e `~/vault/jfn/` (gerado) | Caminho da nota | git diário do vault | Citação por id de fato (`<!--fato:ID-->`) | Humano/sessão em `casos/`; gerador em `jfn/` |
| **Lição / armadilha da perícia** | `autoaprimoramento/armadilhas.py` + registro `versao` | id da armadilha; `rubrica_vN_<hash>` | candidato → sombra → campeão → aposentado, com evento | Portão R1–R6 contra rótulo de nível 2 | Só o portão; promoção é ato humano |
| **Lição de engenharia** | `~/vault/aprendizados/CATALOGO-DE-FALHAS.md` | família do catálogo | git do vault | catraca `tests/test_regra_*` | Sessão |
| **Decisão do dono** | `~/.claude/.../memory/<slug>.md` → memória `decisoria` | `memoria:<slug>` | `supersedes` | palavra do dono (data) | Sessão; propagação envia |
| **Código** | git + GitNexus | símbolo | commit | — | — |
| **Conceito / documentação** | graphify | comunidade | snapshot (3 mantidos) | — | — |

Regra de ouro: **cada fato vive em UMA fonte; as outras camadas guardam ponteiro** (chave, id de fato, wikilink).

### 4.2 Caminhos de leitura

| Pergunta | Caminho | Comando |
|---|---|---|
| "O que já se sabe sobre X?" | recall + busca híbrida | `python -m compliance_agent.cerebro_compartilhado caso "<termo>"` · `brain_recall` / `brain_search` |
| "Tudo desta empresa / processo / UG" (cruzar todos com todos) | índice de entidade | `python -m compliance_agent.cerebro_ponte entidade <CNPJ \| nº SEI \| UG>` |
| "Que empresa aparece em mais de um processo, e em que papel?" | cruzamento | `python -m compliance_agent.cerebro_ponte cruzar` · nota `[[jfn/pericias-agente]]` |
| "O que liga esta nota às outras?" | grafo de notas | `brain_neighbors` |
| "Qual é o número vigente e de onde veio?" | registro de fatos | `python -m compliance_agent.certeza …` · `/api/sistema/certeza` |
| "Quem chama esta função?" | grafo de código | MCP `gitnexus` |
| "Que lição vale para o prompt da perícia?" | versão campeã | `data/autoaprimoramento/campeao.json` (único arquivo que a produção lê) |

Entidades do índice hoje: **CNPJ** (papel: credor, licitante vencedor, licitante perdedor), **processo SEI**, **UG
pagadora**, **versão da rubrica**. Pessoa física **não entra** (CPF e e-mail são mascarados antes de qualquer saída;
sócio e agente público continuam nas tabelas próprias do `compliance.db`, com máscara).

### 4.3 Papel de cada ferramenta

| Ferramenta | Papel único | Destino |
|---|---|---|
| **jfn-brain** | Memória comum e ponto de leitura de TODOS os agentes (recall, busca, vizinhança) | **Manter — é o canônico de leitura** |
| **Obsidian** | Curadoria humana (`casos/`, `aprendizados/`, `decisoes/`) e vitrine gerada (`jfn/`) | **Manter** — `jfn/` só por gerador; `casos/` só por autor |
| **Certeza** | Fonte da verdade de número | **Manter e ampliar** (pago por OB das perícias por agente — §7) |
| **Paleta de órgãos** (`cores_orgaos`) | Uma cor por órgão/UG em toda visualização (grafo do Obsidian, galáxia) | **Implantada** |
| **Ponte** (`cerebro_ponte`) | Levar automelhoria e perícias ao cérebro, com nível medido e índice de entidade | **Implantada** |
| **GitNexus** | Grafo de código | **Manter e consertar** (índice de 08/11) |
| **graphify** | Conceitos de documentação; `GRAPH_REPORT.md` no cérebro | **Manter só para docs**; código fica com o GitNexus |
| **Khoj** | Busca semântica do vault | **Aposentar** — o jfn-brain já faz, com memórias e `supersedes` que o Khoj não tem |
| **hermes_rag** | Recuperação do Hermes | **Fundir**: Hermes passa a ler o jfn-brain; o índice local fica só para o corpus legal |
| **GEP / metacognição** | Lição em prompt | **Fundir no portão**: a única via de lição para prompt é a versão campeã |

### 4.4 Invariantes (valem para toda camada)

1. **WhatsApp não entra em nenhuma camada** — a ponte barra o texto que o cite; nada lê `mcp__whatsapp`.
2. **CPF, e-mail e segredo não saem da máquina** — máscara na ponte + `recusar()` no envio.
3. **Indício ≠ acusação; INDISPONÍVEL ≠ conferido** — texto do processo ausente = nível 1, dito assim.
4. **Nada é sobrescrito** — correção é versão nova (`supersedes`, `fato_versao`).
5. **Modelo não aprova a própria lição** — só o portão; promover a campeão é ato humano.

---

## 5. A arquitetura em dez linhas

1. O **jfn-brain** é o único ponto de leitura dos agentes; tudo o mais alimenta ou é citado por ele.
2. **Número** mora na certeza; **fato de caso** no laudo de origem e na memória com chave; **narrativa** no vault.
3. **Lição** mora na taxonomia de armadilhas e só chega a prompt pela versão campeã do portão.
4. **Decisão do dono** mora na memória dos agentes e é espelhada como memória `decisoria`.
5. **Código** é do GitNexus; **conceito de documentação** é do graphify; nenhum dos dois guarda fato de caso.
6. Toda escrita no cérebro passa pelo registro de chave estável: mesma chave + texto novo = `supersedes`.
7. **Nível de prova é medido por código** (citação literal no processo, OB no SIAFE), nunca declarado pelo agente.
8. O **índice de entidade** (CNPJ, processo, UG) cruza empresa ↔ processo ↔ órgão sem LLM.
9. Quem dispara é o **mapa de propagação** (fonte mudou → derivado sujo), não cron novo.
10. Khoj sai, hermes_rag se funde, GEP e metacognição passam pelo portão: **uma busca, um grafo de código, uma via de lição**.

---

## 6. Implantado em 18/11/2026

| Item | O que faz | Onde | Prova |
|---|---|---|---|
| **Ponte** | Lê `auto.db` (só leitura) e `data/pericia_agentes/*.json`; registra fatos com chave estável; grava índice de entidade; gera notas no vault | `compliance_agent/cerebro_ponte.py` | `tests/test_cerebro_ponte.py` — 8 testes |
| **Nível medido** | Achado só vai ao cérebro com grau se o trecho citado entre aspas (≥ 20 caracteres alfanuméricos) existir no texto arquivado do processo; OB conferida por número e valor no SIAFE | `conferir`, `citacao_conferida` | controle positivo e negativo nos testes |
| **Veredito do portão → cérebro** | Uma memória por versão (`autoaprimoramento:<versão>`); mudança de status vira correção com `supersedes` | `fatos_da_automelhoria` | teste `…mudanca_de_status_vira_correcao` |
| **Lição governada** | Cada `aprendizado` entra como `licao-pericia:<tag>`, marcada CANDIDATA — não validada, não entra em prompt | `fatos_do_laudo` | — |
| **Índice de entidade** | `ponte_entidade` (CNPJ/processo/UG × fato × papel) em `data/propagacao.db` | `entidade`, `cruzar` | teste `…entidades_e_vault…` |
| **Vault** | `jfn/pericias-agente/<tag>.md`, índice `jfn/pericias-agente.md`, `jfn/automelhoria-licoes.md`; só regrava o que mudou | `_nota_laudo`, `sincronizar` | idem |
| **Disparo** | Fontes `pericia_agentes` e `autoaprimoramento_registro` + derivado `cerebro_ponte` (leve) no mapa de propagação; envio pelo despachante `*/5` | `config/propagacao.yaml` | Sistema › Propagação |
| **Cor por órgão / UG** | Paleta única e determinística: 20 UGs principais com cor fixa, as demais por hash, cinza para indeterminado. Notas de `casos/`, `processos/` e `jfn/pericias-agente/` ganham `ug`, `orgao` e as tags `ug/<código>` + `orgao/<sigla>`; `colorGroups` do grafo do Obsidian gerados da mesma paleta; galáxia do painel recebe `cor` em cada nó | `config/cores_orgaos.yaml`, `compliance_agent/cores_orgaos.py`, `compliance_agent/galaxia.py` (`leve`) | `tests/test_cores_orgaos.py` — 6 testes; `tests/test_galaxia.py` |

**Sem agendamento novo de cron:** o disparo é do despachante da propagação, que já existe (regra 10 do `CLAUDE.md`).
O laudo novo ou o veredito novo suja o derivado `cerebro_ponte`; ele roda em até ~15 min e o envio ao cérebro sai
no ciclo seguinte.

### 6.1 Cor por órgão — regras

| Regra | Detalhe |
|---|---|
| Fonte da UG de uma nota | O que a nota já declara (autor ou bloco gerado) **vence**. Nota de `processos/` sem UG: a UG que emitiu a maioria estrita das OB do processo no SIAFE. Laudo por agente: maioria estrita das UGs das OB do laudo |
| Sem UG conhecida | `orgao/indeterminado` (cinza `#8A8F98`). Empate entre UGs também fica indeterminado — nunca se escolhe uma para ganhar cor |
| Tag do órgão | Sigla curada no yaml (10 UGs) → sigla do nome canônico ("ITERJ — …") → slug do nome canônico (`data/ug_canonico.json`) |
| Estabilidade | A ordem de `paleta` e `principais` é contrato: item novo só no fim. A cor de um órgão não muda quando o ranking de pagamento muda |
| O que não é tocado | Corpo da nota e demais chaves do frontmatter; nota editada há menos de 2 min é pulada |
| Galáxia | O dado já leva `cor`; o desenho (`static/`) é de outra sessão — a troca exata está em nota no quadro (frente 1118-0004). Vale após reinício do `jfn.service` (não reiniciado aqui) |

Resultado da primeira carga: ver §8.

---

## 7. Proposta — o que falta, com custo

| # | Item | Por quê | Custo | Decisão |
|---|---|---|---|---|
| P1 | **Agendar o ciclo da automelhoria da perícia** (linha de cron já escrita em `docs/AUTOAPRIMORAMENTO-JFN.md` §8) | Sem agenda o laço só anda à mão; o ciclo não chama LLM | Zero de LLM; ~30 s de CPU por dia | **Dono** (o documento do módulo reserva a instalação a ele; há reexecução de outra frente no mesmo banco nesta noite) |
| P2 | **Aposentar o Khoj** (parar Postgres 5433, desabilitar 3 unidades na VM-2) | Parado desde 18/11, duplica o jfn-brain | Zero; libera memória na VM-2 | Dono (mexe em serviço da VM-2) |
| P3 | **Consertar o GitNexus** (reinstalar binário nativo e reindexar fora de pico) | Índice 508 commits atrás; análise de impacto cega | ~20–40 min de CPU com `nice`, domingo de madrugada | Pode ser feito sem custo de LLM; requer janela |
| P4 | **Pago por OB das perícias por agente como fato da certeza** (`fatos:` no nó `cerebro_ponte`) | Número de pagamento com id, nível 2 e histórico | Zero de LLM; ~1 h de trabalho | Depois de a frente 5580 publicar a mudança dela no mapa |
| P4b | **Galáxia desenhar a cor do órgão** (névoa e disco do órgão por `n.cor`; fornecedor mantém a régua do Radar) | O dado já chega; falta o front | Sem LLM; edição de `static/js/src/galaxia/render.js` + rebuild | Sessão dona de `static/` (nota no quadro) + reinício do painel |
| P5 | **Lições recorrentes → taxonomia de armadilhas** (soma de OB por subconta; OB de regularização/devolução; carta de crédito ≠ entrega; 0,65 × repasse exato; acréscimo medido pelo objeto) | 78 lições candidatas; só entram em prompt se virarem armadilha e passarem pelo portão | Agrupar: 1 sessão; validar: ~40 chamadas por candidata pela assinatura | Dono decide o teto |
| P6 | **Gabarito de nível 2** — de 7 para ≥ 30 casos na validação | O portão sai inconclusivo por R1 enquanto houver 7 | As perícias por agente com citação conferida são candidatas a rótulo de nível 2 (sem LLM): ligar a ponte ao `ledger` | 1 sessão; sem LLM |
| P7 | **Uma via de lição para prompt** — metacognição (`pericia:*`) e GEP passam a ler só a versão campeã | Três vias, uma com portão | Sem LLM; mexe em `tools/hermes_metacognicao.py` e no hook | Dono |
| P8 | **Hermes lê o jfn-brain** em vez do `hermes_rag` para o vault | Terceiro índice do mesmo vault | Sem LLM; 1 sessão | Dono |
| P9 | **Carga inicial das 319 memórias antigas** no cérebro e poda do `MEMORY.md` (203 → ≤ 200 linhas) | Decisões anteriores a 14/11 fora do recall | Sem LLM; ~320 envios | Pode ser feito |
| P10 | **Consumidor da `fila_fonte.json`** (30 itens) e alimentação de `laudo_sombra` | Sem eles nenhuma versão chega a 50 laudos em sombra | Leitura na fonte por agente (assinatura) | Dono decide o ritmo |

---

## 8. Primeira carga — números

Medido em 18/11/2026 às 23:44 (`data/cerebro_ponte_estado.json`; duração ~50 min com a VM-1 em carga 25–30 —
o custo é a primeira leitura dos textos; as rodadas seguintes só releem laudo novo ou alterado). A pasta
`data/pericia_agentes/` cresceu durante a carga (78 → 188 laudos): a carga pegou os 117 que existiam quando
listou; os demais entram pelo derivado `cerebro_ponte`.

| Medida | Valor | Estado |
|---|---:|---|
| Laudos por agente registrados | 117 | VERIFICADO (tabela `ponte_laudo`) |
| Laudos com ao menos um achado de nível 2 | 112 de 117 | VERIFICADO |
| Laudos sem texto do processo na máquina | 0 | VERIFICADO |
| Achados com citação literal localizada no processo (nível 2) | 335 de 400 | VERIFICADO por código |
| Achados com citação **não** localizada | 9 de 400 | ficam só na nota, marcados nível 1 |
| Achados sem trecho conferível (sem aspas ou trecho < 20 caracteres) | 56 de 400 | ficam só na nota, marcados nível 1 |
| OB dos laudos conferidas no SIAFE por número, UG e valor | 1.153 de 1.210 (95,3%) | VERIFICADO; as 57 restantes não foram localizadas com o mesmo valor (PENDENTE de exame) |
| Fatos registrados na fila do cérebro | 241 (117 casos + 117 lições candidatas + 7 versões da rubrica) | 0 recusados |
| Enviados ao jfn-brain até 23:45 | 176 de 241 | o restante sai nos ciclos seguintes do despachante (20 por ciclo) |
| Índice de entidade | 69 CNPJ · 117 processos · 35 UG · 7 versões | VERIFICADO |
| CNPJ presentes em mais de um processo | 22 | lista em `[[jfn/pericias-agente]]` |
| Notas geradas no vault | 119 (117 laudos + índice + lições/portão) | — |
| Notas com `ug`/`orgao`/tags de cor | 420 examinadas; 302 regravadas; 86 `orgao/indeterminado` | — |
| Grupos de cor no grafo do Obsidian | 46 (45 UG + indeterminado) | `~/vault/.obsidian/graph.json` |

Prova ponta a ponta: `brain_recall "Costa Verde Diesel locação de máquinas"` devolve a memória #499 (gravada pela
ponte); `python -m compliance_agent.cerebro_ponte entidade 00.482.487/0001-96` devolve o mesmo fato pelo CNPJ.

**Pendências observadas na carga:** (a) 2 notas novas de `casos/` têm frontmatter YAML inválido (dois-pontos sem
aspas no texto do autor) — o Obsidian não lê as propriedades delas; a ponte não as corrige porque o texto é do autor.
(b) O `git push` foi bloqueado pelo portão de pre-push: as catracas não terminaram no prazo com a carga em 25
(nenhuma falha listada); os commits ficaram locais.
