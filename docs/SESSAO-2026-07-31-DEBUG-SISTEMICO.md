# Sessão 2026-07-31 — Debugging sistemático do ecossistema JFN

> **Método.** Protocolo de causa-raiz antes de qualquer correção: reproduzir, instrumentar a
> fronteira, formular uma hipótese, medir. Toda correção nasceu de um teste que **falhava antes**
> e passa depois. Nenhum número aqui é estimado — todos foram medidos nesta VM, nesta data.

---

## 1. Sumário executivo

| # | Defeito | Antes (medido) | Depois (medido) | Arquivo |
|---|---|---|---|---|
| 1 | Ficha SEI truncava no teto de tokens | 3.137 tentativas, **0 sucessos** | 3/3 refichados, 0 erros | `tools/sei_ficha.py` |
| 2 | Refichador cego ao cache comprimido | via **232 de 5.973** blobs (3,9%) | vê 6.428 | `tools/sei_refichar.py` |
| 3 | Ingestão `sei_ficha` cega ao `.zst` | via **564 de 6.428** arquivos | vê 6.428 | `tools/sei_depurar_db.py` |
| 4 | Ingestão completa não cabia no `timeout` | 502–587 s contra `timeout 300` | incremental por mtime | `tools/sei_depurar_db.py` |
| 5 | RAG do Hermes descartava progresso | **28 rodadas sem avançar 1 chunk** | preservou 3.767 vetores | `tools/hermes_rag.py` |
| 6 | Chat do Hermes devolvia JSON cru na tela | `{\n "resposta": …}` | prosa | `compliance_agent/direcionamento_cerebro.py` |
| 7 | Frescor de fonte com idade **negativa** | `−1d` no painel | piso 0, fuso respeitado | `rotas/investigacao.py` |

**Suíte:** 5.127 testes passando, 9 pulados, zero falhas (4 lotes, protocolo da casa).
**Testes novos:** 6 arquivos, 32 casos — todos falhavam antes da respectiva correção.

---

## 2. A cadeia que estava quebrada (defeitos 1 → 2 → 3)

Os três primeiros defeitos são **o mesmo pipeline**, quebrado em três pontos seguidos. Vale ler em
ordem, porque corrigir só um não produziria efeito nenhum.

### 2.1 O modelo nunca terminava a ficha

Instrumentando a fronteira do nous no processo real `SEI-030001/109183/2024`:

| teto de tokens | `finish_reason` | `completion_tokens` | resultado |
|---|---|---|---|
| **8.000** (vigente) | `length` | 8.000 (estourou) | `content` VAZIO, 26.407 chars de raciocínio → falha |
| 16.000 | `stop` | 11.184 | parseia |
| 20.000 | `stop` | 11.289 | parseia |
| 32.000 | `stop` | 13.963 | parseia |

O `stepfun` é modelo de **raciocínio**: gastava os 8.000 tokens inteiros pensando e o JSON nunca
começava. Pagava-se 8.000 tokens por **zero** resultado, 100% das vezes.

Pior que o bug: a **cegueira**. `extrair_ficha` já capturava o `_raw` da resposta, mas o log
imprimia só `_erro[:60]` — `"JSON inválido"`, que aponta o dedo para o cache (íntegro) e esconde o
corte. O `finish_reason` vinha na resposta e era descartado.

**Correção:** teto padrão 20.000 (o mesmo já provado em `sei_propostas_sweep`) **e** erro falante
que nomeia o corte, os tokens gastos e a variável a girar.

### 2.2 e 2.3 A compressão amputou o pipeline em silêncio

`data/sei_cache/` tem **6.028 blobs**, dos quais **5.795 em `.json.zst`** (compressão feita para
caber 23 GB). Duas ferramentas continuaram usando `glob("cdp_*.json")` cru:

* `sei_refichar` — enxergava **232 de 5.973** (3,9%);
* `sei_depurar_db` — o **único** que escreve em `sei_ficha`, a tabela que o painel lê — enxergava
  **564 de 6.428**.

O módulo criado justamente para impedir isso (`compliance_agent/sei/cache_arquivo`) existia desde a
compressão, com `glob_cache`/`ler_json`, e **nenhum dos dois o adotou**.

Faltava só a **escrita** transparente: `escrever_json` (novo), que grava na mesma forma em que o
arquivo está no disco. Sem ela, a correção óbvia (`write_text` no caminho vindo do glob) gravaria
texto puro por cima de um `.zst` e **corromperia o blob**. Verificado em blob real copiado:
continua `.zst`, `zstd -t` íntegro, acentos preservados, sem `.json` órfão ao lado.

### 2.4 O efeito colateral que quase passou

Com a cegueira corrigida, a ingestão passou a ler 6.428 blobs: **502–587 s**. O chamador
(`tools/sweep_sei.sh`) roda a cada 30 min com **`timeout 300`**. A correção teria trocado *"não
enxerga"* por *"é abortada no meio"* — que é pior, porque parece funcionar.

**Correção:** ingestão **incremental por mtime** (rodada normal = segundos), com duas travas —
tabela vazia ou `--tudo` forçam passada completa — e teto do chamador em 900 s para a completa.
A marca d'água mora **fora** de `sei_cache/`, senão a manutenção a comprimiria e ela sumiria calada.

---

## 3. Cobertura de captura do SEI (medida)

| Medida | Valor |
|---|---|
| Fila de captura priorizada (derivada das OBs) | 3.228 |
| Desses, já com ficha | **3.228 (100%)** |
| Processos varridos pelo sweep | 8.728 |
| Blobs de processo em cache | 6.028 |
| Blobs **com ficha utilizável** | 4.001 |
| Blobs **sem ficha** | **2.388** |

O universo priorizado está **100% capturado**. Os 2.388 sem ficha são consequência direta do
defeito 1 (refichador com 0% de sucesso) somado ao defeito 2 (via 3,9% do acervo). Com 1 e 2
corrigidos, o cron os processa; com 3 corrigido, o resultado chega à tabela que o painel lê.

---

## 4. Achados **não** corrigidos — decisão do dono

### 4.1 Yoda "burro": pool de 8 chaves é configuração morta

`~/.hermes/.env` define `GEMINI_API_KEYS` com **8 chaves**. `grep` em todo o `hermes-agent`:
a variável **nunca é lida**. O código só conhece `GOOGLE_API_KEY`/`GEMINI_API_KEY` no singular
(`plugins/model-providers/gemini/__init__.py:55`).

O Yoda roda com **1 chave free tier, limite 5 req/min** — e o próprio log dele diz *"Hermes
typically makes 3-10 API calls per user turn"*. Estoura a cota **no meio do turno**, o laço do
agente degrada e ele responde raso: sem terminal, sem acionar o JFN, sem trazer documento.

**Descartados por medição** (não são a causa):

| Hipótese | Medição que a derrubou |
|---|---|
| Conectividade Telegram | `httpx` do Hermes: HTTP 302 em 0,7 s; `getaddrinfo` entrega IPv4 primeiro |
| Resolução de nomes | 12/12 órgãos e 6/7 empresas por nome **parcial**; ambíguo devolve `{ambiguo, pergunta, candidatos}` corretamente |
| Ferramenta terminal indisponível | `check_terminal_requirements` **não** está entre as desabilitadas (só GUI: preview, react, kanban, computer_use) |
| Manifesto de capacidades defasado | `~/.hermes/jfn_tools.json` e `data/jfn_tools.json` com **md5 idêntico** |
| `tirith` quebrado | É binário **x86-64 numa VM aarch64** (nunca executa), mas `tirith_fail_open: True` — não bloqueia. Efeito real: varredura de segurança desligada em silêncio |

> **Não mexi** porque envolve custo (regra §4.1) e/ou patch em repositório de terceiro.

### 4.2 Folhas de pessoal — lacunas medidas

| Fonte | Linhas | CPFs distintos | Competência |
|---|---|---|---|
| `dprj_transparencia` | 257.354 | 5.162 | 2016-10 → **2025-10** |
| `tjrj_anexo8` | 21.767 | **1** | 2026-05 |
| `camara_csv` | 2.286 | **1** | **"1978" → "2026"** |
| `gesperj_estado` | 575 | 556 | 2026-06 |
| `pcrj_folha_pref` (PCRJ) | 12.103.391 | — | robusta |

Três defeitos: **(a) ALERJ não tem fonte alguma**; **(b)** TJRJ e Câmara com **1 CPF distinto** —
o CPF não está sendo coletado; **(c)** a coluna `competencia` mistura formatos (`2026-05`, `2026`,
`1978`), o que quebra `MAX()` e qualquer ordenação — mesma família do defeito de data-como-texto do
SIAFE já catalogado.

### 4.3 Painel — CORRIGIDO na segunda rodada (ver §7)

Captura real em desktop (1600×1000) e mobile (390×844), com console e métricas:

| Medida | Desktop | Mobile |
|---|---|---|
| **FPS** | **1,1** | 7,2 |
| CLS (tremor de layout) | 0,023 | 0,041 — **bom** (limite 0,1) |
| Faixa vazia no fim | 0 px | 0 px |
| Rolagem horizontal | não | não |
| `pageerror` | 0 | 0 |
| Console | **2× 404** + `GPU stall due to ReadPixels` | idem |

* **"Sambando"** = os **1,1 FPS** no desktop, com `GPU stall due to ReadPixels` no console. **Não**
  é layout pulando: o CLS está dentro do bom.
* **"Branco embaixo quando puxa"** — não reproduzi no headless (0 px de faixa vazia). A pista forte:
  `background` de `<html>` e `<body>` é **`rgba(0,0,0,0)` (transparente)** com
  `overscroll-behavior: auto`. No celular, ao puxar além do fim, o navegador mostra o **branco
  padrão** atrás do conteúdo. Bate com o sintoma.
* **Cabeçalho sobrepõe o conteúdo no mobile** — texto de seções aparece embolado atrás da barra fixa.
* **2 recursos dando 404** em ambas as viewports.
* Card vermelho da capa exibe `R$ —` (travessão) aos 7 s — dado ausente, não zero.

### 4.4 `/api/pncp` e `/api/sei/direcionamento` travam durante queda da fonte

Na varredura das 120 rotas (às 09:34) ambas deram **timeout aos 60 s**; o PNCP estava fora (503
`text/html` em 0,2 s). Às 09:37 a fonte voltou e responderam em 3,7 s e 5,7 s com 150 registros.

O defeito é o **backoff cego**: `_consulta_retry` (`collectors/pncp.py:453`) dorme 20 s + 40 s = 60 s
mesmo diante de um 503 instantâneo, porque `_get_consulta` engole o status e devolve `None` igual
para timeout e para 5xx. Com `modalidade=0` (4 modalidades) chega a ~240 s.

**Não corrigido:** o backoff longo é deliberado para os coletores em lote (*"o PNCP devolve timeout
transitório sob volume"*). Mexer nele afeta sweeps que querem essa paciência. A escolha é entre dar
um **deadline à rota** (não ao coletor) ou distinguir 5xx de timeout.

### 4.5 RAG: ressalva honesta

O índice foi de **4.809 vetores obsoletos e congelados** (28/07, sem chance de avançar) para **3.767
consistentes com o corpus atual**. Os 1.042 a menos eram chunks cujo texto **não existe mais** no
corpus — devolviam acerto para conteúdo já editado. Faltam 2.089, presos na cota Cohere (a rodada de
hoje conseguiu embeddar **0** — cota seca). O `corpus_hash` **não** foi gravado, então o cron retoma
sozinho. **Se a cota for teto mensal já estourado, o índice fica em 3.767 até virar o mês** — trocar
o embedder é decisão do dono.

---

## 5. Verificações que passaram (nada a fazer)

* **`stepfun:free` não cobra.** Catálogo do nous: `pricing {prompt: "0", completion: "0"}`. A
  variante paga (sem `:free`) custaria US$ 0,92/M de completion e **nenhum código a referencia**.
  Os normalizadores (`agent.py:414`, `free_llm.py:87`) **acrescentam** `:free`, nunca removem.
* **`pericia_sweep`**: as 2.423 falhas `database is locked` do log são **históricas**; as 6 últimas
  execuções fecharam 6.647/6.647 limpas.
* **API**: 120 rotas varridas, 107 respondendo 200. Os 11 `400` são rotas que exigem parâmetro —
  resposta honesta, não defeito.

---

## 6. Próximos passos sugeridos

1. **Yoda** (§4.1) — decidir entre apontar `GEMINI_API_KEY` para chave com folga, trocar o provedor
   do gateway (Cerebras/Groq já estão no `.env`) ou patchar o `hermes-agent` para girar o pool.
2. **Painel** (§4.3) — pintar `background` sólido em `html, body` e `overscroll-behavior: none`;
   caçar os 2 × 404; investigar o `ReadPixels` que derruba o desktop a 1,1 FPS; corrigir o
   `z-index`/`padding-top` do cabeçalho no mobile.
3. **Folhas** (§4.2) — criar coletor da ALERJ; corrigir a coleta de CPF de TJRJ e Câmara;
   normalizar `competencia` para `AAAA-MM` com teste de formato.
4. **PNCP** (§4.4) — dar deadline à rota.
5. **Rodar `sei_refichar` no acervo** agora que ele funciona: 2.388 blobs esperam ficha.

---

## 7. Segunda rodada — painel e PNCP

### 7.1 O que a segunda captura revelou (e que a primeira não viu)

Capturando as **URLs** das requisições (a primeira passada só via o console), apareceram **seis
HTTP 500** que eu havia lido como rotas saudáveis — porque na varredura de rotas eu as chamei sem
parâmetro e num momento em que o banco respondia:

```
500  /api/compliance/painel      500  /api/comparador/economia
500  /api/comparador/vedada      500  /api/comparador/dossie
500  /api/intel/lift             500  /api/intel/fenix
```

Todas com o mesmo corpo: **`database disk image is malformed`**. O arquivo estava **íntegro**
(`quick_check: ok`); o que estava morto era o WAL-index (`-shm`) cacheado **dentro do processo**
`jfn.service` — causa já diagnosticada pela casa em 23/07 e vigiada por `guardiao_db_malformed.sh`.

**É por isso que os cards da capa mostravam `R$ —`.** Não era dado ausente: era rota em erro.

Frequência medida em `data/guardiao_db_malformed.log`: **7 a 14 vezes por dia** (4 hoje). Cada
ocorrência = até 5 min de painel com cards em erro **mais** um restart do serviço. Registrado como
pendência (§4.6) — a hipótese simples já foi descartada: o servidor mantém 12 descritores abertos
para o banco, então não é "ninguém segura o arquivo".

### 7.2 O modo sóbrio media a máquina, recuava — e não parava os canvas

O canto do cabeçalho anunciava `modo sóbrio · 0 fps`: `_medirFps` mediu, concluiu que a máquina não
sustenta animação e ligou `body.fps-baixo`. Só que a regra aplica `animation:none !important`, que
mata `@keyframes` de CSS e **não toca `requestAnimationFrame`**.

`#rjbg` e `#netbg` são canvas de tela cheia desenhados por JS a cada quadro. O `netbg` é **O(n²)**
(até 76 pontos, ~2.900 cálculos e traços por quadro, DPR até 2). O `rjbg` era pior: reagendava
**incondicionalmente**, redesenhando a malha inteira mesmo sob `prefers-reduced-motion`. O painel
media o orçamento, dizia "não cabe", e gastava igual.

Junto saiu o `backdrop-filter` (blur de fundo obriga o navegador a **ler de volta o framebuffer** —
o `GPU stall due to ReadPixels` do console). Enumerar seletor a seletor deixou **10 elementos para
trás** numa verificação com `getComputedStyle`; a regra passou a ser universal sob `fps-baixo`. As
superfícies de vidro ficam **opacas** no mesmo golpe: `--glass` é 76% opaco, então tirar o blur
sozinho faria o conteúdo de trás aparecer nítido através do cabeçalho — que era exatamente o texto
embolado no topo da captura mobile.

**Medido, renderizando de verdade (antes × depois):**

| | Antes | Depois |
|---|---|---|
| FPS desktop | 1,1 | **5,0** |
| FPS mobile | 7,2 | **9,6** |
| CLS desktop | 0,023 | **0,001** |
| Falhas de rede na carga | 11 | **4** |
| Elementos com `backdrop-filter` em modo sóbrio | 10 | **0** |

> **Ressalva:** os números de FPS vêm de Chromium headless com renderização por software em 2 vCPU.
> Servem para comparar antes/depois **na mesma caixa**, não para prever a máquina do dono.

### 7.3 Os "404" eram quase todos intencionais

Correção do que este documento afirmava antes. Das 4 falhas restantes, **nenhuma é defeito**:

- `no-energia.png` — sonda `HEAD` de detecção de recurso. O comentário do código é explícito:
  *"404 hoje significa 'segue procedural', sem erro"*.
- `portal-hero.mp4` e `nucleo-holo-rj.mp4` — "falham" porque o navegador passou a usar o `webm` e
  abandona o `mp4`. Comportamento correto.

Havia **um** 404 real: `portal-hero.webm`. O código lista o `webm` como **primeira** `<source>`
("harness sem H.264") e o arquivo não existia — 404 garantido a cada carga, e a abertura ficava no
JPG parado onde não há H.264. Gerado com ffmpeg (VP9, 1,0 MB), no mesmo padrão do
`nucleo-holo-rj.webm` que já existia.

### 7.4 PNCP: 60 s de sono contra quem respondeu em 0,2 s

Corrigido. `_get_consulta` passa a devolver `(json|None, motivo)` com motivo em `ok`/`http`/`rede`;
`_consulta_retry` usa a espera longa (20 s/40 s) **só** para falha de rede e curta (2 s/4 s) para
erro HTTP. A paciência dos coletores em lote — escrita de propósito para o timeout transitório sob
volume — fica preservada.

---

## 8. Terceira rodada — folha, promessas, hermes update e cadeia de fallback

### 8.1 A folha do Estado tinha 0,06% do que existe

`registros_folha` tinha **575 linhas** do Executivo estadual contra `totalElements = 909.916` na
competência. A API **congela a paginação na página 10.000**: dali em diante devolve HTTP 200 com a
MESMA fatia de 50 registros. Medido: páginas 12825 · 12826 · 12840 · 12864 · 17000 com overlap
**50/50**; páginas 2000–9000 com conteúdo distinto. Rendimento de 40 páginas em cada faixa:
**0 novos** na congelada, **458 novos** na válida.

Corrigido com `_PAGINA_MAX = 10.000` e a distinção entre "acabou a competência" (marca `completa`)
e "bateu no teto da fonte" (**não** marca — senão congelaria em 55% para sempre).

### 8.2 CPF: a intuição do dono não se confirmou, e o número diz por quê

TJRJ e Câmara **não publicam CPF**, nem mascarado — está escrito nos dois coletores. Cruzar por
NOME contra os 78.071 nomes com CPF conhecidos recupera **3,2% (764 de 24.053)**; 96,6% não têm
correspondência alguma. Servidor de tribunal e de câmara em geral não é favorecido de OB.

**Onde o CPF existe de verdade:** a API do Estado traz **CPF mascarado (middle-6)** — o insumo exato
do `resolucao_cpf`. Destravar a coleta (§8.1) é o que abre essa porta, não cruzar nome.

### 8.3 A promessa agora tem disco

`/api/relatorio/orgao`, `/api/relatorio/inteligencia` e `/api/dossie` prometem *"te envio em ~1–2
min"* e delegam a um `asyncio.create_task`. Se o processo morre, a tarefa morre com ele — sem aviso.
Com o serviço reiniciando 7–14×/dia (§7.1), cada restart virava uma promessa quebrada.

`compliance_agent/promessas.py`: a promessa é anotada ANTES de prometer, apagada quando a entrega
termina, e o que sobrar no arquivo depois do boot é re-despachado pelo lifespan.

### 8.4 `hermes update`: o que quebrou e a lição

O update (97 commits, config v25→v33) fez **checkout para `origin/main`**, não merge — e **apagou as
quatro customizações do JFN** no adaptador do Telegram, mesmo estando **commitadas**.

> **Commitar não basta.** O que salvou foi ter guardado os diffs em ARQUIVO antes de rodar. Ambos
> aplicaram limpos depois com `git apply --3way`.

Marcadores a conferir sempre: `_JFN_MENU_TEXT`, `_JFN_MENU_HINTS`, `_aplicar_orcamento_de_imagem`,
`_ORCAMENTO_IMAGEM_TURNO`.

**Sobreviveu:** `config.yaml` inteiro (`force_ipv4`, `environment_hint`, modelo), `credential_pool`.
**Melhorou:** ferramentas 31 → 37. **Prompt de sistema e índice de skills: idênticos.**

### 8.5 Cadeia de fallback auditada: 6 dos 20 degraus estavam mortos

Cada degrau testado com requisição real:

| Morto | Motivo |
|---|---|
| `github-models/gpt-4o-mini` | **HTTP 410 — serviço aposentado** |
| `nvidia/llama-3.3-70b` | ReadTimeout |
| `openrouter/llama-3.3-70b:free` | 404 indisponível |
| `nous/inclusionai/ring-2.6-1t:free` | 404 modelo inexistente |
| `nous/tencent/hy3-preview:free` | 404 modelo inexistente |
| `aion/aion-1.0-mini` | 400 modelo desconhecido |

Entraram dois que respondem e estavam de fora: **huggingface/Llama-3.3-70B** (0,8s) e
**groq/gpt-oss-120b** (0,3s). **Venice ficou fora: HTTP 402, saldo insuficiente** — é paga (§4.1).

A ordem segue os critérios da casa, não força bruta: janela grande primeiro (o catálogo do JFN são
18k tokens por requisição), **visão antes** (gemini 1M e stepfun 262k text+image+video, ambas
verificadas no catálogo do provedor) e **Groq no fim** (o teto de 12.000 TPM é da CONTA).

Cópia de referência do config versionada em `deploy/hermes-config.yaml.referencia` — o
`~/.hermes/config.yaml` não é versionado e já foi perdido uma vez.

### 8.6 CORREÇÃO ao §7.1 — o `-shm` **não** está resolvido

A conexão guardiã (`fcdf9949`) elimina **um** mecanismo, comprovado no flagrante: o servidor chegava
a **zero conexões** (16:14:31) e o SQLite desvinculava os arquivos-irmãos (16:17:42). Depois do fix,
os descritores nunca mais zeram.

**Mas houve nova queda às 17:42**, com o fix já no ar desde 16:30. E o vigia flagrou:

```
19:09:28   shm=AUSENTE   fds=33   deletados=8
```

`shm` ausente **com 33 descritores abertos** e 8 apontando para arquivos já deletados. O inode do
`-wal` mudou de 2345988 para 2346266. Ou seja: **alguém apaga/recria o `-shm` com conexões vivas**, e
a guardiã não impede isso.

**Suspeito principal:** `tools/pos_sweep_analise.py:76` faz *"VACUUM + checkpoint"* no
`compliance.db` (chamado por `tools/siafe_supervisor.sh` depois do sweep). VACUUM reconstrói o banco
e pode resetar o WAL-index de quem já o tem mapeado.

**Próximo passo:** instrumentar `pos_sweep_analise` para registrar o inode do `-shm` antes e depois
do VACUUM — se mudar, está achado; a cura seria serializar o VACUUM com uma janela em que o servidor
solte as conexões, ou trocá-lo por `wal_checkpoint(PASSIVE)`.

Quedas medidas hoje: 00:17 · 03:22 · 10:22 · 13:24 · **17:42**. As de 10:22 e 13:24 foram causadas
pelas minhas próprias escritas de teste.

---

## 9. Quarta rodada — `PERSIST_WAL` para a casa inteira

### 9.1 A bandeira é consultada por quem FECHA

Instalado `apsw 3.53.4` (wheel nativo aarch64, sem compilar). Medido, com ninguém mais segurando o
banco:

| Fechador | Resultado |
|---|---|
| `sqlite3` puro | `wal=AUSENTE shm=AUSENTE` |
| `apsw` com `PERSIST_WAL` | **`wal=existe shm=existe`** |

**Premissa minha que caiu na medição** — fica registrada para ninguém repetir: eu afirmava que
*"qualquer conexão aberta impede o desvínculo"*. Vale quando o outro processo só **lê** (foi o que
enganou o primeiro experimento). Um **escritor** que fecha por último desvincula mesmo com a
guardiã aberta **e** com a bandeira nela.

### 9.2 A alavanca: por PROCESSO, não por conexão

188 arquivos da casa abrem o banco com `sqlite3` cru (91 escrevem) e a stdlib não expõe file
controls. Migrar 91 call-sites quebraria API (o `apsw` tem semântica própria de transação).

A bandeira é por conexão, mas a **proteção é por processo**: basta **uma** sentinela `apsw` com a
bandeira, viva enquanto o processo viver. Instalada no `__init__` do pacote, **todo processo que
toca o banco herda, com zero mudança de chamador**. Verificado num tool real: importar
`tools.sei_depurar_db` já sobe a sentinela com `PERSIST_WAL=True`.

**Efeito de segunda ordem verificado ANTES de fiar:** a sentinela aberta **não** bloqueia
`wal_checkpoint(TRUNCATE)`, `VACUUM` nem `ANALYZE` no mesmo processo — era o risco de trocar um
defeito por `database is locked` na manutenção. Tem teste guarda-costas.

`JFN_SENTINELA_WAL=0` desliga.

### 9.3 Três catracas da casa me pegaram — e as três tinham razão

| Catraca | O que pegou | Remédio aplicado |
|---|---|---|
| `except-pass` mudo | 153 > teto 151 | os dois `pass` viraram `logger.debug` com contexto |
| `except Exception` | 1601 > baseline 1596 (mão única) | especializei em `_ERROS = (sqlite3.Error, OSError) + (apsw.Error,)`; 2 ocorrências restantes estavam em **comentário** meu — a catraca conta a string crua |
| modo sóbrio | vermelho | **o teste é que estava velho**: amarrava a forma da chamada (`classList.add`) em vez da propriedade |

O terceiro caso merece registro: outro trabalho refatorou `_medirFps` em `_sobrioAplicar(lig, fps)`
e **estendeu** o recuo para pausar os vídeos da nebulosa, do núcleo e do holograma (v51/v53/v55) —
construindo em cima da minha mudança. O código melhorou; o teste é que amarrava forma em vez de
propriedade. Agora trava o que importa: os dois eixos (CSS e JS) mudam juntos.

### 9.4 Estado final

**Suíte: 5.163 passando, 6 pulados, zero falhas** (4 lotes).
Rotas da capa que devolviam 500: **todas em 200**. Quedas do painel desde a sentinela: **zero**.
