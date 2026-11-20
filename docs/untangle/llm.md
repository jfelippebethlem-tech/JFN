# Untangle — pacote `llm/` (registro de decisões)

| | |
|---|---|
| **Escopo** | `compliance_agent/llm/` — núcleo: `claude_motor`, `claude_api`, `contingencia`, `ritmo_assinatura`, `comotor`, `conferencia_opus`, `cruzamento`, `json_resposta`; régua compartilhada de `free_llm` (requisição OpenAI-compatível, guarda `:free`, classificação de erro). Periféricos (`groq_agent`, `hermes_agent`, `orquestrador`, `router`, `memoria`, `auto_melhoria`, `visao`, `openrouter_catalogo`) só levantados |
| **Data** | 20/11/2026 — worktree `agent-a80b3327db3960fdd`, base `a94f3d56` |
| **Opções** | Comentários = SIM (mantida medição datada, decisão do dono e porquê de workaround) · Testes = NÃO (nenhum teste removido; só renome mecânico onde o símbolo mudou de casa) |
| **Pergunta única** | "Estas peças devem mudar juntas?" |
| **Regras da casa que não mudam** | juiz/conferência só pela assinatura (`backend="cli"`) · modelo barato não decide · Opus nunca pela API paga · `:free` guardado no nível BAIXO · contingência → cascata + fila do Opus · teto diário e ritmo semanal (`RESERVA_OPUS`) · parse JSON único (`json_resposta.parse_json_llm`) |

Legenda: **FEITO** (commit) · **MANTIDO** (caso especial que o sistema ainda precisa, com o motivo) · **ANOTADO**
(fora do escopo desta frente, ou exigiria prova de paridade/teste que esta frente não escreve).

---

## 1. Consertos, com os problemas que cada um resolve

### 1.1 O estado local do Claude tem um dono: `llm/arquivo_estado` — FEITO (`c68745fd`)
`dados()`, `trava()` (flock de arquivo), `ler_json`/`gravar_json`/`mutar_json` atômicos, `sob_pytest()`. Não importa
nada do pacote; motor, API, contingência, ritmo, orçamento, fila e cruzamento dependem dele.
- três `_dados()` (`claude_motor:100`, `contingencia:106`, `ritmo_assinatura:51`) e `claude_api:141` importando o do motor;
- três jeitos de gravar estado (`claude_motor:162–201`, `contingencia:114–136`, `ritmo_assinatura:128,151`);
- `claude_api:142,161,167` importando privados do motor (ciclo motor ↔ API desfeito);
- oito guardas `PYTEST_CURRENT_TEST` → `arquivo_estado.sob_pytest()`.
- **MANTIDO**: `mutar_json(espera=10)` grava mesmo sem a trava curta (contador de uso um pouco torto vale mais que o
  juízo parado); a contingência usa `espera=None` (bloqueia), como antes.

### 1.2 Um id por modelo, e o "Opus nunca pela API" pela família — FEITO (`c68745fd`)
`claude_api` é o dono dos ids (`MODELO_JUIZO/VOLUME/BARATO`); o motor importa de lá. `_sem_opus` rebaixa qualquer id com
"opus", não só o igual à cópia local.
- `claude_api:43–45` × `claude_motor:55–56` (cópia); `_sem_opus` por igualdade.

### 1.3 A régua de cada tarefa num módulo próprio — FEITO (`415acbbc`)
`llm/normalizadores.py` (`NORMALIZADORES`, `norm_*`). Co-motor (na hora) e conferência do Opus (depois) leem a mesma
tabela.
- `conferencia_opus:90` lia `comotor.NORMALIZADORES` (ciclo com `comotor:237,310`); a régua da perícia integral
  morava no co-motor genérico.

### 1.4 O contrato JSON tem os dois lados no mesmo módulo — FEITO (`415acbbc`)
`json_resposta` = parse único + `instrucao_schema` (o pedido) + `chaves_exigidas`/`chaves_faltando` (a conferência).
- texto do pedido copiado em `claude_motor:328` e `contingencia:283`; regra de chaves divergente.
- **Divergência deliberada**: resposta que não é OBJETO JSON passa a ser descartada também no motor (antes uma lista
  passava se o schema não tinha `required`); a cascata passa a exigir as chaves de schema-exemplo como o motor.
  Todos os schemas reais (`ESQUEMA_H`, `cerebro_consolidacao.ESQUEMA`, `vm2_lote._SCHEMA`) pedem objeto; nas 304
  respostas reais do Opus na fila, 0 eram lista.

### 1.5 A cascata da casa é pública na contingência — FEITO (`415acbbc`)
`contingencia.gerar_cascata` / `modelo_da_cascata`.
- `contingencia:280,299` e `pericia_integral:660` importavam `comotor._gerar_sync_padrao/_modelo_da_cascata`
  (privados; ciclo comotor → motor → contingência → comotor).

### 1.6 O limite da conta mora só na contingência; kill-switch por estado; marca `@api` num lugar — FEITO (`d527171d`)
- `claude_motor:266,514` gravava/lia `bloqueado_ate` em paralelo ao `ate` da contingência (dois arquivos, mesmo fato;
  `sair()` não liberava o motor). Agora o motor só pergunta `contingencia.motivo_bloqueio`.
- `claude_motor:513` × `contingencia:153`: pausa padrão calculada nos dois → só `contingencia.entrar`.
- `claude_motor:362,376` (`_SEM_API`): API paga barrada por PREFIXO DO TEXTO do motivo → `_motivo_kill_switch()`;
  vale também para `backend="api"` (o comentário prometia, o código não fazia).
- "`@api`" reconhecido à mão em 5 consumidores → `claude_api.SUFIXO_API` + `pela_api()` (mora na API: o
  `rotina_base` aceita motor dublê sem esse símbolo, e a marca é proveniência da API).
- `contingencia:188`, `triagem_alertas:417` importavam `claude_motor._avisar_telegram` → `avisar_dono` público.

### 1.7 `free_llm`: uma porta de requisição, com a guarda `:free` dentro — FEITO (`31c0d012`)
`_requisicao()` monta cabeçalho + payload + `_sem_raciocinio` + guarda `:free` (OpenRouter) para as TRÊS portas.
- `free_llm:295,352` (retry síncrono e assíncrono) montavam a requisição sem a guarda — provado sem rede: id pago
  passava cru nas duas na base; agora sai `:free` nas três, Groq intocado.
- payload copiado 3× (`:130,304,361`), backoff assíncrono reescrito (`:389,399`) → `_espera_backoff`.
- 402 permanente no erro embutido e retentado no HTTP (`:180` × `:264`) → um conjunto só.
- sem chamador: `coder_chat_async`, `classificar_contrato`, `resumir_doerj`, `analisar_red_flags_contrato` (levava
  `knowledge/` para dentro do pool), `cooldowns_ativos`, e o que só eles usavam.

### 1.8 Orçamento diário do Claude em módulo próprio — FEITO (`c388a2d1`)
`llm/orcamento.py`: tetos do dono (com os comentários datados), arquivo de uso do dia, `motivo_teto`.
- `contingencia:197` lia o orçamento importando o motor (ciclo motor ↔ contingência): a regra de cota muda por
  decisão do dono; o CLI muda por versão do Claude Code.

---

## 2. Levantamento (antes de mexer)

### 2.1 Ligações escondidas
- `claude_motor.py:100`, `contingencia.py:106`, `ritmo_assinatura.py:51`: três cópias de `_dados()` (`JFN_CLAUDE_DADOS` ou `<repo>/data`); `claude_api.py:141` importava a do motor.
- `claude_motor.py:162–201` (`_flock`, `_ler_json`, `_gravar_json`), `contingencia.py:114–136` (`_ler`, `_mutar` com flock próprio), `ritmo_assinatura.py:128,151` (leitura e escrita atômica próprias): três jeitos de gravar o mesmo tipo de arquivo de estado.
- `claude_api.py:43–45` repetia os ids `MODELO_JUIZO`/`MODELO_VOLUME` de `claude_motor.py:55–56`. `claude_api._sem_opus` comparava por IGUALDADE com a cópia local: mudar o id do Opus no motor deixava o "Opus nunca pela API" sem efeito.
- `claude_motor.py:328` (`_instrucao_schema`) e `contingencia.py:283`: o mesmo texto "Responda SOMENTE com um objeto JSON…" copiado; e a checagem de chaves divergia — o motor aceitava schema-exemplo (`_chaves_exigidas`), a cascata só `required`; o motor aceitava lista onde se pediu objeto, a cascata não.
- `claude_motor.py:266` (`bloqueado_ate` em `claude_motor_estado.json`) e `contingencia.py:217` (`ate` em `claude_contingencia.json`): o MESMO limite da conta gravado em dois arquivos por `_tratar_tipo`. `contingencia.sair()` limpava um e o motor seguia barrado pelo outro — o "estado único" do CLAUDE.md não era único.
- `claude_motor.py:513` e `contingencia.py:153`: a pausa padrão `JFN_CLAUDE_PAUSA_LIMITE_S` (3600) calculada nos dois.
- `claude_motor.py:362,376` (`_SEM_API`): a decisão "kill-switch também barra a API paga" era tomada por PREFIXO DO TEXTO do motivo ("desligado (JFN_CLAUDE_MOTOR", "pausado", "sob pytest"). Reescrever a mensagem de `motivo_desligado` faria o motor pausado passar a gastar dólar.
- Marca "`@api`" (Claude barato pela API) criada em `claude_motor.py:399` e reconhecida por `endswith("@api")`/`"@api" in` em `comotor.py:307`, `rotina_base.py:157`, `cerebro_consolidacao.py:170`, `triagem_alertas.py:238`: convenção que cada consumidor precisa saber.
- `conferencia_opus.py:90` lia `comotor.NORMALIZADORES`; `comotor.py:237,310` lia `conferencia_opus` — ciclo; e a régua da perícia integral morava no co-motor genérico.
- `contingencia.py:280,299` importava `comotor._gerar_sync_padrao` e `comotor._modelo_da_cascata` (privados, ciclo comotor → claude_motor → contingencia → comotor); `pericia_integral.py:660` também usava `comotor._modelo_da_cascata`.
- Guardas `PYTEST_CURRENT_TEST` espalhadas: `claude_motor.py:409`, `contingencia.py:184,278`, `conferencia_opus.py:62,176`, `claude_api.py:376,442`, `cruzamento.py:69` — mesma regra ("teste nunca chama provedor, nunca manda mensagem, nunca suja dado real"), oito grafias.
- `free_llm.py:295,352`: as duas variantes com retry (`_openai_compat_chat_sync_retry`, `_openai_compat_chat_retry`) montavam a requisição sem a guarda `:free`; a guarda só estava em `_openai_compat_chat_sync` (`:142`). Hoje todo chamador põe `_forcar_free` à mão (`free_llm.py:482,505,534`, `hermes_agent.py:131`) — a guarda era convenção de novo, exatamente o defeito de 25/07 (memória `openrouter-guard-free-nivel-baixo`).
- `free_llm.py:130–151, 304–317, 361–374`: cabeçalho + payload + `_sem_raciocinio` copiados três vezes; backoff da versão assíncrona (`:389,:399`) reescrito em vez de usar `_sleep_backoff`.
- `free_llm.py:180` (`RespostaProvedorErro._PERMANENTES` com 402) × `free_llm.py:264` (`_PERMANENTE_STATUS` sem 402): o mesmo "não melhora esperando" com dois conjuntos — 402 (pagamento exigido) embutido em 200 falhava rápido, 402 HTTP era retentado 4×.
- `conferencia_opus.py:248` monta `<repo>/data/compliance.db` à mão (ignora `JFN_DATA_DIR`).

### 2.2 Ligações desnecessárias
- `claude_api.py:142,161,167` importava privados do motor (`_dados`, `_ler_json`, `_flock`, `_gravar_json`) — o backend de baixo dependia do de cima (ciclo claude_motor ↔ claude_api).
- `contingencia.py:188` e `triagem_alertas.py:417` importavam `claude_motor._avisar_telegram` (privado).
- `contingencia.py:197` (`_uso`) lê o orçamento do motor; o motor lê `contingencia.motivo_bloqueio` — ciclo por import tardio.
- `free_llm.py:1086` (`analisar_red_flags_contrato`) importava `knowledge.fraudes_licitacao` — o pool de provedores dependendo de base de conhecimento.

### 2.3 Sobra
- `free_llm.py:1031` `classificar_contrato`, `:1049` `resumir_doerj`, `:1081` `analisar_red_flags_contrato`, `:852` `cooldowns_ativos`, `:516` `coder_chat_async`: zero chamadores (grep no repo inteiro, `.py/.js/.yaml/.sh`).
- `contingencia.py:12`: "TRÊS ORIGENS" listando quatro.

### 2.4 Casos especiais
- `claude_motor.py:227,243` (`_mutar_uso`, `_mutar_estado`): se a trava curta não vem em 10 s, grava SEM trava (ignora `pegou`).
- `rotina_base.py:131–145`: `getattr(claude_motor, "pensar")`, "algumas versões devolvem `(resultado, motivo)`", `ULTIMO_MOTIVO` — generalidade para versões do motor que não existem.
- `autoaprimoramento/__main__.py:37`: decide "tentar de novo" por prefixo do texto de `ultimo_motivo` ("ocupado", "passou do prazo").
- `free_llm.py:828–833`: `_classificar_erro` casa "429"/"permission" em qualquer lugar do texto.

### 2.5 Periféricos (levantamento por subagente só-leitura; ver §4)
JSON à mão em `hermes_agent.py:261,385,609`, `memoria.py:290`, `auto_melhoria.py:59`; segundo cliente Groq em `groq_agent.py:71–120`; URL/variável de ambiente divergentes (`CLOUDFLARE_API_TOKEN` × `CLOUDFLARE_API_KEY`, `NVIDIA_API_KEY` × `NVIDIA_NIM_API_KEY`); `visao.py:72–83` fora do teto mensal `_cap_inc`; `free_llm.py:693` caminho absoluto `/home/ubuntu/JFN/data/.llm_month_cap.json`; `groq_agent.rodar_analise_groq` grava `Alerta` com severidade do modelo barato e manda 🔴/🟡 sem fila de conferência; `orquestrador.py:252` promove a "alto" por casamento de substring; `compliance_agent/agent.py:443` e `siafe_agent/agent.py:100` caem no Opus pela API paga quando só há `ANTHROPIC_API_KEY`.

---

### 1.9 Sobras do núcleo — FEITO (lote 6)
- `json_resposta._reparar` repetia linha a linha `_reparar_cauda` → chama a função.
- `claude_motor._pensar_cli` lia o uso e calculava o teto duas vezes na pré-checagem.

---

## 3. Lotes (commits) e validação

| Lote | Commit | Conteúdo |
|---|---|---|
| 1 | `c68745fd` | `arquivo_estado`; ids únicos; `_sem_opus` pela família; guardas de pytest |
| 2 | `415acbbc` | `normalizadores`; contrato JSON em `json_resposta`; cascata da casa pública |
| 3 | `d527171d` | limite só na contingência; kill-switch por estado; `pela_api`; `avisar_dono` |
| 4 | `31c0d012` | `free_llm._requisicao` com guarda `:free` nas 3 portas; 402 permanente; código morto |
| 5 | `c388a2d1` | `orcamento` |
| 6 | (este) | sobras do núcleo + este registro |

**Testes casados** (`/tmp/.../llm_tests.txt`, 30 arquivos): 405 verdes na base → 451 verdes ao fim (os 46 a mais são
os 5 arquivos acrescentados no lote 3 — consolidação, ficha do acervo, radar). Testes de `free_llm` + catraca: 102
verdes, 1 pulado. Lote amplo (129 arquivos que tocam o pacote e seus consumidores): verde.

**Impressão digital empírica, sem LLM** (script `llm_empirico.py`, retrato congelado dos dados reais de 20/11 06:2x,
relógio congelado; base extraída de `a94f3d56` por `git archive`):
- `parse_json_llm` em 4.969 respostas reais (fila do Opus `resposta`/`resposta_opus` + memória da API): 1 sem JSON,
  144 recuperadas de corte — hash idêntico em todos os lotes;
- réguas (`normalizadores`) em 4.437 respostas de 4 tarefas — idênticas;
- `claude_motor.classificar_erro`, `contingencia.eh_limite`/`hora_de_volta`, `free_llm._classificar_erro` e
  `tools.sei_ficha.modelo_morto` sobre 327 mensagens reais de erro (log do motor, contingência, fila, `llm_trace`) —
  idênticos (28 limite, 11 com hora legível; 23 rate-limit/6 server/5 timeout no pool);
- `ritmo_assinatura.classificar` em 626 medições reais + 68 estados sintéticos — idêntico; estado real atual:
  CONTIDO (74% × linha 71,6%);
- `contingencia.motivo_bloqueio` em 362 estados (4 contingências × 5 usos × 6 ritmos × 3 estados do motor + forçada +
  motor desligado) × 21 tarefas — **idêntico em todos**; `claude_motor.motivo_desligado` idêntico exceto nos 120
  estados sintéticos com `bloqueado_ate` vivo e contingência apagada (agora igual ao estado sem a cópia — §1.6) e no
  "forçada" com essa cópia (passa a citar a forçada). Estado real atual: mesma decisão.
- Guarda `:free`: prova sem rede (`guarda_free.py`, httpx interceptado) — base deixava `google/gemini-2.5-flash-lite`
  cru no `sync_retry` e no `async_retry`; agora `:free` nas três portas.

GitNexus: o índice não conhece os símbolos deste worktree (`impact` → "not found"); a análise de impacto foi feita
por grep do repositório inteiro (`.py/.js/.yaml/.sh`, sem `.claude/`) e confirmada por subagente revisor.

## 4. Pendências, defeitos achados e riscos

### 4.1 Defeitos fora do escopo (ANOTADO — decisão do dono / outra frente)
- **Laudo do Haiku pela API vira VERIFICADO sem o Opus**: `correlacao_sei.estado_do_laudo:169` dá VERIFICADO a todo
  `modelo` com "claude" — inclui `claude:claude-haiku-5-5@api …`. Medido em `lex_execucao` (leitura): 495 de 9.387
  laudos têm `@api` no modelo, ~420 deles ainda SEM conferência (o resto traz "(conferência; antes …@api)").
  Conserto proposto: `claude_api.pela_api(m.split(" (conferência")[0])` ⇒ PENDENTE, ou perguntar
  `conferencia_opus.pendente(tarefa, item)` (hoje sem chamador em produção). Muda estado visível no painel: não
  aplicado aqui.
- `vinculo_ob_contrato.py:433`: duas leituras Haiku em lote viram VERIFICADO sem entrar na fila do Opus.
- `compliance_agent/agent.py:405,444,625` e `siafe_agent/agent.py:100`: caem no Opus pela API paga
  (`claude-opus-4-8`) quando só há `ANTHROPIC_API_KEY` — fora do `_sem_opus`.
- `tools/automelhoria_executor.py:107–111`: `claude -p --model opus` sem `ambiente_limpo()`, sem a trava do motor, sem
  contar no orçamento e com cópia de `_bin()`.
- `groq_agent.rodar_analise_groq`: `Alerta` com severidade do modelo barato e 🔴/🟡 no Telegram sem fila de conferência;
  `orquestrador.py:252` promove a "alto" por substring; `auto_melhoria.py:136` deixa a cascata gratuita gravar regra
  de método permanente.
- `siafe_agent/agent.py:77–80,159`: modelo do OpenRouter vindo do `.env` sem `_forcar_free`.

### 4.2 Pendências dentro do pacote (ANOTADO)
- Decisões por TEXTO do motivo: `autoaprimoramento/__main__.py:37`, `cerebro_consolidacao.py:162` (`"ocupado" in`).
  Conserto: `claude_motor.ultimo_tipo` ("ocupado", "prazo", "limite", "teto", "desligado") ao lado de `ultimo_motivo`.
- Co-motor grava o Haiku `@api` como lado "claude" no cruzamento (`comotor.py:189`): vira referência de few-shot e
  de placar. Precisa de decisão: lado próprio ("claude_api") ou fora do placar.
- `rotina_base.py:161` enfileira sem `instrucao_schema` (chave da fila ≠ entrada que o modelo viu) e com `item=None`
  (o aplicador nunca regrava); `rotina_base.py:137–143` aceita tupla/`ULTIMO_MOTIVO` que não existem.
- Ciclos tardios que sobraram: contingência → motor (só `avisar_dono`), contingência ↔ fila (`cascata` × `painel`),
  fila → motor → contingência → fila. Nenhum no topo.
- `conferencia_opus.py:248` (`compliance.db` montado à mão), `conferencia_opus`/`cruzamento` com caminho próprio fora de
  `JFN_CLAUDE_DADOS`; `free_llm.py` caminho absoluto do teto mensal; JSON à mão em `hermes_agent`/`memoria`/`auto_melhoria`
  (trocar por `parse_json_llm` exige prova de paridade — memória `parse-json-llm-unico-provado`).
- `pericia_integral` lê a tabela `fila` e descomprime `entrada` por conta própria; liga `JFN_CLAUDE_CONTINGENCIA` por
  `os.environ` para forçar a cascata.

### 4.3 Riscos desta frente
- §1.4: resposta-lista com schema de objeto agora é descartada no motor (antes passava sem `required`). Nenhum schema
  real pede lista; 0 de 304 respostas reais do Opus eram lista.
- §1.6: `contingencia.sair()` agora libera o motor de fato; `claude_motor_estado.json` antigo ainda tem
  `bloqueado_ate` (ignorado).
- §1.6: kill-switch vale também para `backend="api"` (sem chamador hoje).
- §1.7: 402 HTTP deixa de ser retentado (falha rápida, cooldown do provedor cuida).
- `arquivo_estado.gravar_json` engole erro de disco com aviso (a contingência levantava; o efeito no chamador é o
  mesmo: o motor devolve `None`).
