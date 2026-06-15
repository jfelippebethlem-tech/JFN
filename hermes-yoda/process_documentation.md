# process_documentation.md — Mestre Yoda (Hermes)

> Documento de processo que o **Mestre Jorge** pediu para o Yoda manter em tempo real,
> para outras IAs avaliarem cada etapa. Este arquivo é a sede canônica (versionada) dessa
> documentação. Sessões futuras do Yoda devem **acrescentar** aqui (append), nunca apagar histórico.

---

## 2026-06-05 — Remediação do funcionamento do Yoda (por Claude Code, VM Linux GCP)

Origem: o Mestre Jorge pediu para resolver tudo que ficou documentado na sessão dele com o Yoda
(DM Telegram, sessão `20260604_160915_991bf5c3`) e melhorar o funcionamento do agente.
Abaixo, cada problema **documentado na sessão** com a causa-raiz e a correção aplicada.

### Problema 1 — Yoda é prolixo (verbosidade)
- **Evidência:** o Mestre Jorge repetiu ≥3× ("está escrevendo muito", "diminua ruído ao máximo",
  "pare de me explicar tudo antes do resultado final. Racionalize tokens da Gemini").
- **Causa-raiz:** a diretriz de concisão **não estava sendo salva** na memória do usuário por causa
  do Problema 2 (loop de memória) — então o comportamento não mudava entre sessões.
- **Correção:** diretriz de concisão gravada diretamente em `~/.hermes/memories/USER.md`:
  *"respostas CONCISAS, diretas, ruído mínimo; ao codificar, etapas em uma linha e resultado final
  sem explicações longas antes; documentação detalhada vai para process_documentation.md, não no chat."*

### Problema 2 — Loop/bug no sistema de memória
- **Evidência:** no dump da sessão, a ferramenta `memory` falhou 4× seguidas (aviso de
  `same_tool_failure_warning`) tentando substituir entradas por correspondência de texto exata,
  e batendo no limite de caracteres ("Memory at 1,357/1,375 chars").
- **Causa-raiz:** `user_char_limit: 1375` em `~/.hermes/config.yaml` era pequeno demais; a memória
  do usuário encheu e o Yoda entrou em loop tentando liberar espaço com `replace` de match exato.
- **Correção (`~/.hermes/config.yaml`):**
  - `user_char_limit: 1375 → 4000`
  - `memory_char_limit: 2200 → 6000`
  - Backups: `config.yaml.bak.2026-06-05`, `memories/USER.md.bak.2026-06-05`.
- **Observação:** a exigência de *match exato* para `replace` (limitação do core do Hermes, já
  citada no README-AGENTES) permanece; aumentar o limite remove a pressão que disparava o loop.

### Problema 3 — `process_documentation.md` nunca foi criado
- **Evidência:** o Mestre Jorge pediu 3× ("Coloque sempre um doc de tudo o que vc esta fazendo").
- **Causa-raiz:** Yoda registrou a intenção na memória mas, preso no loop do Problema 2, não chegou a
  criar o arquivo.
- **Correção:** este arquivo. Convenção: Yoda acrescenta aqui a cada tarefa relevante.

### Problema 4 — Yoda caiu no reset da VM e não reiniciou sozinho
- **Investigação (pergunta literal do Mestre Jorge: "foi problema seu, da VM, do Hermes?"):**
  o gateway rodava **manualmente dentro de um `tmux`** (`python -m hermes_cli.main gateway run`,
  PID 646, sessão tmux `hermes`). Não havia serviço de boot. Quando a VM reiniciou, o tmux morreu
  com a sessão e **nada ressubiu o gateway** → Yoda ficou fora até religarem na mão.
  Conclusão: não foi bug do Hermes nem da VM — foi **ausência de supervisão/auto-start**.
- **Correção:** instalado o serviço systemd **oficial** do Hermes:
  `hermes gateway install` → `hermes-gateway.service` (user-level), `enabled` (sobe no boot),
  `Restart` automático, `TimeoutStopSec=3m30s` (respeita o `drain_timeout=180s`), **linger ligado**
  (sobrevive a logout/reboot). Agora, se a VM reiniciar ou o processo cair, o Yoda volta sozinho.
- **Operar:**
  ```bash
  hermes gateway status
  systemctl --user status hermes-gateway
  journalctl --user -u hermes-gateway -f
  ```

### Problema 5 — Geração de vídeo sem GPU
- **Decisão do Mestre Jorge:** "Cancela esse vídeo. Já vimos que sem GPU vai dar problema."
- **Estado:** experimento cancelado. Os scripts (`generate_spaceship_*.py`, `compose_video_audio.py`,
  `generate_space_sound.py`, `run_all.py`) ficaram na raiz do JFN como sandbox cancelado — não
  versionados, não usados pelos agentes.
- **Recomendação (solução gratuita/qualidade FORA da VM, sem processar localmente):** usar serviços
  hospedados com free tier em vez de renderizar nesta VM sem GPU — p.ex. **Hugging Face Spaces**
  (modelos de texto→vídeo como LTX-Video/CogVideoX rodando em GPU da nuvem) ou geradores web gratuitos.
  Para imagem, o fluxo Stable Diffusion já existe; para vídeo, evitar render local sem GPU.

### Problema 6 — Como adicionar um novo usuário ao Yoda
- **Mecanismo:** o `config.yaml` usa `allowed_users_env: TELEGRAM_ALLOWED_USERS`. Para liberar acesso:
  1. Descobrir o **ID numérico** do Telegram do novo usuário (ele manda `/start` ao bot, ou via @userinfobot).
  2. Em `~/.hermes/.env`, acrescentar o ID em `TELEGRAM_ALLOWED_USERS` (lista separada por vírgula):
     `TELEGRAM_ALLOWED_USERS=45338178,NOVO_ID`
  3. Reiniciar: `systemctl --user restart hermes-gateway`.

---

### Resumo das mudanças desta remediação
| Onde | Mudança | Reversível |
|---|---|---|
| `~/.hermes/config.yaml` | limites de memória ↑ (1375→4000, 2200→6000) | sim (backup `.bak.2026-06-05`) |
| `~/.hermes/memories/USER.md` | + diretriz de concisão | sim (backup `.bak.2026-06-05`) |
| systemd `--user` | `hermes-gateway.service` instalado (oficial), boot + restart | `hermes gateway uninstall` |
| este repo | `hermes-yoda/process_documentation.md` (novo) | — |

> Nada de credencial neste arquivo. Token do bot e IDs ficam só em `~/.hermes/.env` (fora do git).

---

## 2026-06-05 (adendo) — Fix de verdade do bug de memória do Hermes (para outra IA avaliar)

Investiguei o código do Hermes (`~/hermes-agent/tools/memory_tool.py`). **Causa-raiz do loop:**
`replace`/`remove` localizavam a entrada por **substring exata** (`old_text in e`); modelos mais
fracos **parafraseiam** o texto e a substring não casa, e o erro `No entry matched` não mostrava as
entradas reais → o agente chutava de novo (loop, como o Yoda fez 4×).

**Correção (branch dedicada, NÃO aplicada em produção ainda):**
- Repo: `~/hermes-agent` (clone do NousResearch/hermes-agent).
- Branch: **`claude/fix-memory-resolve-for-weaker-models`** (commit `d8d62b5`). A `main` está intacta.
- O quê: endereçamento por índice `#N`; erros que listam entradas reais com `#index` + `closest`;
  sem fuzzy silencioso; schema atualizado. **76 testes passam** (7 novos, incl. regressão do loop).
- Como avaliar/aplicar/reverter: ver `~/hermes-agent/PROPOSAL-memory-resolve-fix.md` (passo a passo).

> Pendente: outra IA validar a branch e, se aprovar, `git merge` na `main` + `systemctl --user restart hermes-gateway`.
> Diretriz eterna do Mestre Jorge: workflows/propostas devem assumir IAs mais simples — passos
> explícitos, comandos prontos, resultado esperado e rollback (foi o padrão usado na PROPOSAL).

---

## 2026-06-05 (adendo 2) — Rotina BOM DIA + Yoda mais inteligente e menos prolixo

### Rotina BOM DIA do Mestre Jorge
- Cronjob **existia** (`81cae9684db0`, 07:30 BRT = cron `30 10 * * *`, entrega Telegram, skill
  `gold-morning-brief`), mas o prompt era genérico. **Enriquecido** via `hermes cron edit` com o
  formato canônico: elogio de 1 palavra + clima Barra da Tijuca + piada do dia (não repetir) +
  versículo + MERCADO (dólar/Bovespa/ouro/petróleo, links completos) + 10 notícias (5 Brasil + 5 Rio),
  URLs completas, nunca encurtar.
- **Yoda lembra das rotinas a cada início:** registrei todas as rotinas ativas em
  `~/.hermes/memories/MEMORY.md` (injetado no system prompt no início de cada sessão). Inclui a
  nota de que jobs são por **perfil** (causa do sumiço do job original `676c8988952a`).
  Conferir sempre com `hermes cron list`.

### Modelo do Yoda — mais inteligente e menos prolixo
Causa do "burro/prolixo": `reasoning_effort: low` cortava o raciocínio do gemini-2.5-flash, e não
havia personalidade de concisão.
- `agent.reasoning_effort: low → medium` (raciocínio de volta; modelo continua gemini-2.5-flash).
- `display.personality: '' → concise` (instrução de brevidade no system prompt).
- `agent.environment_hint`: corrigida info **desatualizada** (dizia "Qwen principal"; o real é
  gemini-2.5-flash) e adicionada regra de estilo: responder direto, sem preâmbulo, sem narrar.
- Backup: `~/.hermes/config.yaml.bak.pre-model-2026-06-05`.
- **Teste (one-shot):** "3 aditivos sucessivos 10%/15%/8%, acréscimo composto?" → respondeu
  **36,62%** (composto correto; "burro" diria 33%) em **uma linha**, 8s. Inteligente + conciso. ✅

> Rollback do modelo: `cp ~/.hermes/config.yaml.bak.pre-model-2026-06-05 ~/.hermes/config.yaml && systemctl --user restart hermes-gateway`.
> Upgrade opcional futuro: `model.default: gemini-2.5-pro` (mais inteligente, porém mais lento e
> com cota free mais restrita — avaliar impacto na rotina diária antes).

---

## 2026-06-06 — Yoda-maestro + barramento JFN + /relatorio de inteligência + correção de UGs

**Autor:** Claude Code (Opus 4.8) a pedido do Mestre Jorge. Branch JFN: `claude/ambiente-e-relatorio`.

### Problema de origem
Yoda não entendia "gere um relatório do JFN sobre o fornecedor MGS": pedia esclarecimento, tentava uma
ferramenta inexistente (`web_search`) e perguntava "como ativo o JFN agente auditor?". Causa estrutural:
os agentes não sabiam o ambiente (system prompt do Yoda dizia que o JFN ficava em `c:/JFN/jfn` — caminho
Windows que não existe na VM Linux) e o Yoda não sabia acionar o JFN.

### O que foi feito (visão geral)
1. **Fase 0 — infra/boot:**
   - Desabilitado o `yoda.service` (systemd de SISTEMA) que duplicava e brigava com `hermes-gateway.service`
     (user) pelo bot do Telegram (causava loop de FAILURE/restart). Gateway canônico = `hermes-gateway.service`.
   - Instalados **Google Chrome 149** + **Chromium 149**; criado `chrome-jfn.service` (user) = ponte CDP
     headless na porta 9222 (habilita coleta TFE/SIAFE ao vivo do JFN).
2. **Fase 1 — fonte única de verdade do ambiente:** criados `AMBIENTE.md` + `ambiente.json` (VM GCP Ubuntu,
   4 agentes, workflow de boot, barramento). Corrigido o system prompt do Yoda (`~/.hermes/config.yaml`):
   `c:/JFN/jfn` → `/home/ubuntu/JFN`, + mapa de capacidades (rotas da API do JFN), + "não existe
   web_search". Ponteiros para `AMBIENTE.md` em CLAUDE.md, README-AGENTES.md, SOUL.md (Hermes) e massare/README.md.
3. **Fase 2 — barramento de agentes no JFN (FastAPI :8000):**
   - `POST /api/relatorio/inteligencia` → "Relatório de Inteligência de Fornecedor" (due diligence de
     integridade + exposição financeira + risco). Motor: `compliance_agent/reporting/inteligencia.py`.
     Resolve por **nome (parcial) ou CNPJ**; se ambíguo, devolve `{ambiguo:true, pergunta, candidatos}`
     para o Yoda perguntar ao Mestre Jorge. Gera `.md` + `.pdf` (fonte Unicode DejaVu) em `reports/`.
     Inclui **uma tabela de OBs pagas POR ANO** (2023/2024/2025/2026) com pagamentos individuais (>12/ano).
   - Massare exposto: `GET /api/massare/placar`, `GET /api/massare/cenarios`, `POST /api/massare/prever`.
   - **Massare como agente de pregão:** `massare/market.py` (cenários multi-horizonte curtíssimo/curto/médio/
     longo + notícias via Google News RSS + snapshot) e `massare-market.timer` (dias úteis 12:50–21:00 UTC =
     09:50–18:00 BRT, a cada 15min). Não polui o placar (record=False); o `massare-daily` segue registrando a
     previsão oficial.
   - Testes: `tests/test_relatorio_inteligencia.py` (12 passam).
4. **Fase 3 — Yoda-maestro:** convenção `/relatorio <empresa|cnpj>` + roteamento de mercado no `USER.md`;
   mapa de capacidades no `MEMORY.md`. Gateway recarregado.

### APRENDIZADO IMPORTANTE — UGs (ITERJ)
Mestre Jorge apontou: "pagamentos do ITERJ saíram como Secretaria de Infraestrutura e Obras". Verificado:
no espelho TFE (`compliance.db`), **ITERJ = UG `133100`** (SIAFE-Rio 2 = 270042). As OBs rotulavam a UG 133100
com o nome do ÓRGÃO SUPERIOR ("Secretaria de Infraestrutura..."), diluindo o ITERJ. A `despesa_execucao.nome_ug`
tem o nome correto. Implementado `compliance_agent/ugs.py` (mapa canônico `data/ug_canonico.json` + overrides
curados); relatórios passam a resolver o órgão pelo CÓDIGO da UG. Agora o ITERJ aparece separado (R$ 3,16M, 2,4%).

### Validação
- 12/12 testes; relatório MGS gerado (23 páginas) e enviado ao Telegram para o Mestre Jorge validar.
- Endpoints testados ao vivo (relatório ambíguo "clean" → desambiguação; massare placar/cenarios/prever OK).
- Dados REAIS do MGS: pago 2023–2026 = R$ 133.435.889,29 (1056 OBs, 13 órgãos; HHI ALTA 3897, maior órgão 59,5%).

### Regras respeitadas
Código em branch dedicada; honestidade (REAL vs CACHE/INDISPONÍVEL, nunca fabricar número); OB = pagamento.

### 2026-06-06 (continuação) — Base ampliada 2019–2026 (gestão Cláudio Castro)
Ingeridas as OBs de **2019, 2020, 2021 e 2022** a partir do ZIP do TFE (`data/tfe_cache/fornecedor_ob.zip`,
já continha 2017–2026) via `compliance_agent.collectors.tfe_ob.ingest(ano)`. Contagens: 2019=122.964,
2020=104.971, 2021=124.707, 2022=155.911 OBs. A base `ordens_bancarias` agora cobre **2019–2026**.
Timer `jfn-tfe-ob.service` atualizado para reingerir 2019–2026 (era 2023–2026). Relatórios passam a
refletir todos os anos com OB do favorecido (anos sem pagamento simplesmente não aparecem — normal).
Ex.: MGS CLEAN agora 2021–2026 (R$ 136.225.497,94; não há OB em 2019/2020).

### 2026-06-06 (continuação) — Planilha Excel interativa + relatório por órgão + integração Yoda
- **Planilha Excel** (`compliance_agent/reporting/planilha.py`): anexo PADRÃO de todo relatório. Tabela do
  Excel (autofiltro + zebra), painel congelado, moeda/data reais, abas Resumo/Pagamentos(OBs)/Concentração,
  formatação condicional (estornos em vermelho, barras de dados). `montar()` (fornecedor e órgão) agora
  retorna também `path_xlsx`. O Yoda envia SEMPRE PDF + XLSX no Telegram.
- **Relatório por ÓRGÃO** (`inteligencia_orgao.py`, `POST /api/relatorio/orgao`): quanto a UG pagou e a quem,
  por ano, com concentração por fornecedor + parecer. Título "Relatório de Inteligência de <órgão>".
- **Integração Yoda↔JFN**: `config.yaml` (environment_hint), `USER.md` e `MEMORY.md` do Yoda atualizados com
  as rotas (fornecedor/órgão), o fluxo de desambiguação e o envio PDF+XLSX. `AMBIENTE.md`/`ambiente.json`/HANDOFF idem.
- **Validação:** 17 testes passam; endpoints testados ao vivo (PDF+XLSX); MGS e ITERJ enviados ao Telegram
  (ITERJ já com 2019–2026: 2.457 OBs). Serviços hermes-gateway/jfn/chrome-jfn ativos.

### 2026-06-06 (continuação) — Coletor SIAFE (OB Orçamentária) integrado ao JFN
- **Coletor** `compliance_agent/siafe_ob_orcamentaria.py`: login real (Playwright) com seleção de exercício
  (logout-primeiro + retry; detecção de ano bloqueado — 2023 bloqueado p/ a conta, pula), navegação até
  "OB Orçamentária", detector de load (`tabela_pronta`), colheita rolando o container virtual `::scroller`
  (23 colunas ricas: NL, PD, Processo, Credor...). Resiliência: checkpoint + coordenação Telegram (sessão única).
- **Ingestão** `ingerir()`: grava na `compliance.db` tabela `ob_orcamentaria_siafe`, **SIAFE preponderando**
  (INSERT OR REPLACE por numero_ob). CLI: `--ingerir`. Validado: 237 OBs de 2025 ingeridas (230 com processo).
- **Barramento JFN:** `GET /api/siafe/stats`. **Yoda:** comandos `/siafe <ano>` e `/siafestats` (skills criadas).
- **APRENDIZADO PROFISSIONAL (guardado em docs/SIAFE-ARQUITETURA.md §8b):** o ADF/Trinidad **ignora eventos
  sintéticos** (select_option/dispatchEvent/clique de blur disparam ZERO requisições) — por isso o filtro rico
  não automatiza por Playwright (headless OU headed). Caminhos p/ varredura completa por UG: replay HTTP do
  request de filtro (capturar 1 cURL no Chrome) ou Computer Use (mouse/teclado reais). Documentado.
