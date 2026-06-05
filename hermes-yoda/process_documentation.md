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
