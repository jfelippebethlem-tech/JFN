# Yoda — modo Claude Code direto · Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** O dono fala (PT/EN misturados) com o Yoda no Telegram e conversa direto com uma sessão contínua do Claude Code: resposta literal em texto + voz, alterações só após ✅, `/cc_desfaz` volta tudo, e o Gemini/Hermes ficam proibidos de programar.

**Architecture:** Estende o plugin `~/.hermes/plugins/jfn-claude` com módulos pequenos: estado persistido, executor `claude -p --resume` em stream-json, orquestrador do fluxo plano→✅→execução (interceptado no hook `pre_llm_call` com `block`, antes do Gemini), Telegram (texto, edição, voz, botões via `register_telegram_handler`), TTS Piper local e pontos de restauração git. A trava "Gemini não programa" vai no `jfn-guardas` (`pre_tool_call`).

**Tech Stack:** Python 3 (venv do Hermes, só stdlib no plugin), Claude Code CLI 2.1.x (assinatura), python-telegram-bot (já no Hermes, só dentro da factory), Piper (`~/tts-venv`, já instalado, voz `~/tts-venv/vozes/pt_BR-faber-medium.onnx`), faster-whisper (`~/stt-venv`), ffmpeg, pytest.

**Spec:** `~/JFN/hermes-yoda/docs/2026-11-07-yoda-modo-claude-code-design.md` (ler inteiro, especialmente 5.8).

## Global Constraints

- Custo de API zero: nenhuma chamada a API paga; Claude Code pela assinatura (sem `ANTHROPIC_API_KEY` no env do subprocesso).
- Env mínimo no subprocesso do Claude Code (`_env_min()` existente): chaves do gateway nunca vazam.
- Nada de segredo em código/log/mensagem/áudio; id do chat do dono vem de `TELEGRAM_ALLOWED_USERS` (1º item) no `~/.hermes/.env`, nunca hardcoded.
- Matar processo só por PID/PGID; nunca `pkill -f`.
- Nada no core do Hermes (`hermes update` apaga): só `~/.hermes/plugins/*`, `~/.hermes/config.yaml`, `~/tts-venv`, `~/stt-venv`.
- Testes rodam em diretórios temporários (`tmp_path`); nenhum teste toca `~/JFN` real, o Telegram real ou o estado real.
- VM 2 vCPU: um Claude Code por vez; TTS/STT/execução sempre fora da thread do gateway; `nice -n 10`.
- Mensagens ao dono em PT-BR.
- Versionamento: `git init` local em `~/.hermes/plugins/jfn-claude` e `~/.hermes/plugins/jfn-guardas` (sem remoto); spec e plano no `~/JFN` (commit+push na branch atual, `git branch --show-current`).
- Rodar testes: `cd ~/.hermes/plugins/jfn-claude && ~/.hermes/installs/1bfccf49951fecd0/environments/7603fa9bf8b741ab923255de4c0ce5d4/venv/bin/python -m pytest tests -q` (abreviado abaixo como `PYTEST`).

## Review Focus

1. Voz transcrita chega como `"texto"` (entre aspas) ou com prefixo `[The user sent a voice message: …]\n\n`, ou como aviso de áudio vazio — "ok" falado precisa ser reconhecido e o aviso vazio nunca vira pedido. (Task 4: `test_normalizar_*`)
2. Mensagem chega enquanto plano espera ✅ e ela NÃO é aprovação (ex.: "na verdade muda o arquivo Y") → plano cancelado, nada executa, vira novo pedido. (Task 4: `test_texto_qualquer_cancela_plano_pendente`)
3. Clique ✅ duplicado / ✅ de plano expirado (>30 min) / ✅ depois de `/cc_nova` → não executa duas vezes nem plano velho. (Task 4: `test_aprovacao_idempotente_e_expirada`)
4. Gateway reinicia no meio: estado `ativo`/sessão sobrevive; tarefa em curso morreu → estado não fica preso em "rodando". (Task 1: `test_estado_rodando_orfao_e_liberado`)
5. Claude Code falha (rc≠0, cota, saída ilegível, prazo) → aviso claro ao dono, nenhum fallback ao Gemini, fila segue. (Task 2: `test_falha_vira_aviso`; Task 4: `test_falha_nao_trava_fila`)

---

### Task 1: Estado persistido + repo local

**Files:**
- Create: `~/.hermes/plugins/jfn-claude/estado.py`
- Test: `~/.hermes/plugins/jfn-claude/tests/test_estado.py`

**Interfaces:**
- Produces:
  - `@dataclass Estado: ativo: bool=False; sessao_id: str|None=None; plano: dict|None=None` (`{"texto": str, "pedido": str, "criado": float, "arquivos": list[str], "id": str}`); `fila: list[str]=field(default_factory=list)`; `rodando: dict|None=None` (`{"pid": int, "fase": str, "inicio": float}`); `ultimo_ponto: str|None=None`
  - `carregar(caminho: Path = ESTADO) -> Estado` — arquivo ausente/corrompido → `Estado()`; se `rodando.pid` não existe mais (`os.kill(pid, 0)` → `ProcessLookupError`) zera `rodando`.
  - `salvar(e: Estado, caminho: Path = ESTADO) -> None` — escrita atômica (tmp + `os.replace`).
  - `ESTADO = Path.home()/".hermes/state/jfn-claude-cc.json"`
  - `PLANO_VALIDADE_S = 30*60`

- [ ] **Step 1:** `cd ~/.hermes/plugins/jfn-claude && git init -q && printf '__pycache__/\n' > .gitignore && git add -A && git commit -qm "chore: estado inicial do plugin jfn-claude"` (idem em `~/.hermes/plugins/jfn-guardas`).
- [ ] **Step 2: testes que falham** — `test_ida_e_volta(tmp_path)` (salva Estado com plano/fila e carrega igual); `test_arquivo_corrompido_vira_padrao(tmp_path)` (`"{x"` → `Estado()`); `test_estado_rodando_orfao_e_liberado(tmp_path)` (rodando com pid 999999 → `carregar().rodando is None`).
- [ ] **Step 3:** `PYTEST tests/test_estado.py` → FAIL (módulo não existe).
- [ ] **Step 4:** implementar `estado.py`.
- [ ] **Step 5:** `PYTEST tests/test_estado.py` → PASS. Commit `feat: estado persistido do modo Claude Code`.

### Task 2: Executor do Claude Code (sessão contínua, stream-json, duas fases)

**Files:**
- Create: `~/.hermes/plugins/jfn-claude/executor.py`
- Modify: `~/.hermes/plugins/jfn-claude/__init__.py` (o `_trava` passa a ser `executor.TRAVA`; `_env_min`, `_com_rtk`, `_LEITURA`, `_NEGADO_SEMPRE` movem para `executor.py` e são reimportados — os testes antigos continuam passando)
- Test: `tests/test_executor.py`

**Interfaces:**
- Consumes: `_env_min()`, `_com_rtk()`, `_LEITURA`, `_NEGADO_SEMPRE` (existentes).
- Produces:
  - `TRAVA: threading.Lock` (única para `/claude`, ferramenta e modo direto)
  - `MARCADOR = "[[PRECISA_OK]]"`
  - `@dataclass Resultado: ok: bool; texto: str; sessao_id: str|None; precisa_ok: bool; arquivos: list[str]; negadas: int; seg: int`
  - `montar_comando_cc(texto: str, fase: Literal["plano","execucao"], sessao_id: str|None) -> list[str]`
  - `rodar_cc(texto, fase, sessao_id, ao_progresso: Callable[[str], None], ao_iniciar: Callable[[int], None] = lambda pid: None, prazo_s: int = 1800) -> Resultado`
  - `ler_arquivos(texto: str) -> list[str]` — itens da linha `ARQUIVOS: a, b` (expande `~`); vazio se ausente.
  - `cancelar(pid: int) -> None` — SIGTERM no PGID, SIGKILL após 30 s.

Comando (ambas as fases): `nice -n 10 <claude> -p <texto> --output-format stream-json --verbose --permission-mode dontAsk [--resume <sessao_id>] --allowedTools … --disallowedTools … --append-system-prompt <PROMPT>`; `cwd=~/JFN`, `env=_env_min()`, `start_new_session=True`.
- plano: allowed = `_com_rtk(_LEITURA)` + `"WebFetch"`; disallowed = `_com_rtk(_NEGADO_SEMPRE)`.
- execucao: allowed = `["Read","Grep","Glob","Edit","Write","Bash","WebSearch","WebFetch"]` (escopo "igual ao terminal", spec 5.8); disallowed = `_com_rtk(PROIBIDOS)` com `PROIBIDOS = [segredos de _NEGADO_SEMPRE] + ["Bash(git push --force:*)","Bash(git push -f:*)","Bash(git push --force-with-lease:*)","Bash(sudo:*)","Bash(pkill:*)","Bash(rm -rf:*)","Bash(rm -fr:*)","Edit(//home/ubuntu/yt-login/**)","Write(//home/ubuntu/yt-login/**)","Edit(**/.env*)","Write(**/.env*)","Bash(ssh:*)","Bash(scp:*)"]` (VM-2: ssh só pedindo no terminal; meu call, mais restritivo que a spec).

Prompts (texto exato decidido aqui, o resto do tom fica com o implementador):
- BASE: "O Mestre Jorge fala com você pelo Telegram, por VOZ transcrita automaticamente, misturando português e inglês: interprete erros fonéticos pela intenção ('cloud code'/'De Code' = Claude Code, 'brente'/'brand' = branch, 'Jotapin'/'JPN' = JFN, 'comitar' = commit). Sua resposta vai literal para o Telegram e é lida em voz alta: PT-BR, direta e completa, sem tabelas largas, até ~3500 caracteres. Siga o CLAUDE.md. Proibido sempre: force push, sudo, apagar em massa, pkill -f, ler/imprimir credenciais, mexer em ~/yt-login, VM-2, ligar API paga."
- PLANO: "FASE PLANO (só leitura). Investigue e responda. Se o pedido exigir ALTERAR qualquer coisa (arquivo, git, serviço, config, banco, processo), NÃO altere: descreva o plano concreto — o que muda, comandos, efeito esperado, riscos, e o que é IRREVERSÍVEL — inclua a linha `ARQUIVOS: <caminho absoluto>, …` com todo arquivo que vai tocar, e termine com [[PRECISA_OK]]."
- EXECUCAO: "FASE EXECUÇÃO: o dono aprovou o plano acima. Execute SÓ esse plano; git push comum permitido, force nunca. Se precisar sair do plano, pare e devolva novo plano com ARQUIVOS e [[PRECISA_OK]]. Termine com o que foi feito e como verificar."

Progresso a partir do stream-json: evento `type=="assistant"` com `content[].type=="tool_use"` → `ao_progresso(f"{name}: {resumo}")` (resumo = `command`/`file_path`/`pattern` truncado em 80); evento `type=="result"` → resultado final (`result`, `is_error`, `session_id`, `permission_denials`). `precisa_ok = MARCADOR in texto`; o marcador é removido do texto entregue.

- [ ] **Step 1: testes que falham**
  - `test_plano_so_leitura`: `montar_comando_cc("x","plano",None)` → sem `Edit`/`Write`/`Bash` puro em allowed; `--resume` ausente; `"stream-json"` e `"--verbose"` presentes.
  - `test_execucao_igual_terminal_com_proibidos`: `"Bash"` e `"Edit"` em allowed; `"Bash(git push --force:*)"`, `"Bash(rtk git push --force:*)"`, `"Bash(sudo:*)"` em disallowed; `"Bash(git push:*)"` NÃO em disallowed.
  - `test_resume_quando_ha_sessao`: `cmd[cmd.index("--resume")+1] == "abc"`.
  - `test_rodar_cc_le_stream(monkeypatch)`: troca o binário por um script fake (`tmp_path/claude` imprimindo 1 linha tool_use Bash `ls` + 1 linha result com `"result":"feito\nARQUIVOS: /tmp/a\n[[PRECISA_OK]]","session_id":"s1"`) → `progresso == ["Bash: ls"]`, `r.precisa_ok`, `"[[PRECISA_OK]]" not in r.texto`, `r.arquivos == ["/tmp/a"]`, `r.sessao_id == "s1"`.
  - `test_falha_vira_aviso`: fake sai rc=1 sem result → `not r.ok` e `r.texto` não vazio.
  - `test_prazo_mata_grupo`: fake `sleep 60`, `prazo_s=1` → `not r.ok`, "prazo" em `r.texto`, processo morto.
- [ ] **Step 2:** `PYTEST tests/test_executor.py` → FAIL.
- [ ] **Step 3:** implementar; ajustar `__init__.py` (importa de `executor`; `disparar` usa `executor.TRAVA`).
- [ ] **Step 4:** `PYTEST tests` → todos PASS (inclui os 8 antigos).
- [ ] **Step 5: prova real (leitura, custo só de assinatura):** script de verificação chama `rodar_cc("Diga em uma linha a branch atual do JFN.","plano",None, print)` e depois `rodar_cc("E qual foi o último commit?","plano",r.sessao_id, print)` → 2ª resposta coerente com a 1ª, mesmo `sessao_id`. Commit `feat: executor do Claude Code com sessão contínua e duas fases`.

### Task 3: Telegram (texto, edição, voz, botões) + voz Piper

**Files:**
- Create: `~/.hermes/plugins/jfn-claude/telegram_io.py`, `~/.hermes/plugins/jfn-claude/voz.py`
- Test: `tests/test_voz.py`, `tests/test_telegram_io.py`

**Interfaces:**
- Produces (`telegram_io`): `dono() -> str` (1º de `TELEGRAM_ALLOWED_USERS`); `enviar(texto: str, botoes: list[tuple[str,str]]|None=None) -> int|None` (fatia em 3900; botões `(rotulo, callback_data)` só na última fatia; devolve `message_id`); `editar(message_id: int, texto: str) -> None`; `enviar_voz(ogg: Path) -> None` (multipart `sendVoice` só com stdlib); `responder(texto: str, botoes=None) -> int|None` — dispara `voz.sintetizar` numa thread **no mesmo instante** e envia o texto sem esperar; a thread envia o áudio quando pronto (spec 5.6 [dono]: simultâneo; falha do TTS só loga). Função interna `_api(metodo, campos, arquivo=None) -> dict` é o único ponto que faz rede (mockável).
- Produces (`voz`): `preparar_fala(texto: str) -> str`; `sintetizar(texto: str, destino_dir: Path) -> Path|None` (`~/tts-venv/bin/piper -m <voz> -f x.wav` com stdin, depois `ffmpeg -c:a libopus -b:a 32k x.ogg`; timeout 300 s; `nice -n 10`; None em erro).
- Pronúncia (`PRONUNCIA`, troca por palavra inteira, sem caixa): Claude Code→"Clód Côud", Claude→"Clód", branch→"brântch", commit→"comít", push→"púch", JFN→"jota efe ene", SIAFE→"siáfe", Yoda→"Iôda", Hermes→"Érmes", Gemini→"Djêmini", git→"guít", deploy→"diplói", VM→"vê ême", OK→"ôquei".

- [ ] **Step 1: testes que falham**
  - `test_preparar_fala_omite_codigo`: texto com bloco ```` ```py\nx=1\n``` ```` → contém "código omitido no áudio" e não contém "x=1".
  - `test_preparar_fala_omite_hash_e_caminho_longo`: `"commit 3f9a1c2e em /home/ubuntu/JFN/compliance_agent/x.py"` → sem "3f9a1c2e", sem "compliance_agent", com "comít".
  - `test_pronuncia`: `preparar_fala("Claude Code na branch do JFN") == "Clód Côud na brântch do jota efe ene"`.
  - `test_sintetizar_real(tmp_path)` (marcado `@pytest.mark.skipif(not Path("~/tts-venv/bin/piper").expanduser().exists())`): gera `.ogg` > 1 KB.
  - `test_responder_texto_nao_espera_voz(monkeypatch)`: `voz.sintetizar` dorme 2 s; `responder("oi")` retorna em < 0,5 s com `_api` chamado com `sendMessage`; após join, `sendVoice` chamado.
  - `test_fatias_e_botoes_na_ultima(monkeypatch)`: texto de 8000 chars com botões → 3 `sendMessage`, só a última com `reply_markup`.
- [ ] **Step 2:** FAIL. **Step 3:** implementar. **Step 4:** PASS. **Step 5:** commit `feat: resposta em texto e voz simultâneos (Piper local)`.

### Task 4: Orquestrador do modo direto (plano → ✅ → execução, fila, desfaz)

**Files:**
- Create: `~/.hermes/plugins/jfn-claude/modo_direto.py`, `~/.hermes/plugins/jfn-claude/desfaz.py`
- Test: `tests/test_modo_direto.py`, `tests/test_desfaz.py`

**Interfaces:**
- Consumes: `estado.*`, `executor.rodar_cc/cancelar/TRAVA/ler_arquivos/Resultado`, `telegram_io.responder/enviar/editar`.
- Produces (`desfaz`):
  - `criar_ponto(arquivos: list[str], base: Path) -> str` — repos = `{~/JFN}` ∪ toplevels git dos `arquivos`; por repo grava HEAD, upstream (`@{u}` se existir) e snapshot do working tree **com não rastreados** (índice temporário via `GIT_INDEX_FILE`, `git add -A`, `write-tree`, `commit-tree` → ref `refs/cc-desfaz/<id>`); arquivos fora de git são copiados para `base/<id>/`. Grava `base/<id>.json`, devolve `<id>`.
  - `descrever(id: str, base: Path) -> str` — por repo: commits novos desde o ponto (já enviados ou não), arquivos alterados; arquivos fora de git a restaurar.
  - `desfazer(id: str, base: Path) -> str` — commits novos **não enviados**: `git reset --hard <head>` e restaura o snapshot (`git read-tree`/`checkout` do tree + `git reset` para desindexar; remove não rastreados criados depois); commits **já enviados**: `git revert --no-edit <head>..HEAD` + `git push` (nunca force), depois restaura o não-commitado do snapshot. Copia de volta os arquivos fora de git.
- Produces (`modo_direto`):
  - `normalizar(msg: Any) -> str` — aceita str ou lista multimodal; remove prefixo `[The user sent a voice message: …]` e aspas envolventes `"…"`; aviso de áudio vazio/não transcrito → `""`.
  - `e_aprovacao(texto: str) -> bool` — minúsculo, sem acento/pontuação, ∈ `{"ok","okay","pode","pode fazer","pode executar","executa","executar","sim","manda","confirmo","aprovado"}`.
  - `e_parada(texto) -> bool` — ∈ `{"para","pare","parar","cancela","cancelar","stop"}`.
  - `receber(texto: str) -> str` — devolve o recibo curto (vira a resposta do turno); o trabalho real roda em thread e responde por `telegram_io.responder`. Regras: plano pendente + aprovação → `aprovar(plano_id)`; plano pendente + parada → cancela; plano pendente + outro texto → cancela plano ("plano anterior cancelado") e trata como pedido novo; tarefa rodando + parada → `executor.cancelar`; tarefa rodando + outro → entra na `fila` ("na fila, posição N"); livre → fase plano.
  - `aprovar(plano_id: str) -> str` — só se `estado.plano.id == plano_id` e não expirado; consome o plano (idempotente), `desfaz.criar_ponto(plano.arquivos)`, roda fase execução; resposta final + "↩️ /cc_desfaz desfaz isto".
  - `ao_llm(user_message=None, sender_id="", platform="", **_) -> dict|None` — hook `pre_llm_call`: só age se `platform=="telegram"`, `sender_id == telegram_io.dono()` e `estado.ativo`; texto vazio → `{"action":"block","message":"🎙️ Não entendi o áudio — pode repetir?"}`; senão `{"action":"block","message": receber(texto)}`.
  - Comandos (strings de retorno): `cmd_cc` (liga), `cmd_yoda` (desliga), `cmd_nova` (zera `sessao_id` e plano), `cmd_para`, `cmd_status`, `cmd_desfaz` (mostra `descrever` + botões ✅/❌ `cc:dz:<id>`/`cc:no`), `cmd_edita(raw)` (força o fluxo plano mesmo com modo desligado).
  - Callback: `ao_botao(data: str, user_id: str) -> str` — ignora se `user_id != dono()`; `cc:ok:<plano_id>` → `aprovar`; `cc:no` → cancela; `cc:dz:<id>` → `desfazer`.
  - Progresso: uma mensagem "⏳ Claude Code trabalhando…" criada no início, editada no máx. a cada 5 s com as 3 últimas ações; ao fim vira "✔️ concluído em Xs" / "⚠️ …".
  - Ao terminar qualquer tarefa: libera `TRAVA`, `rodando=None`, e se a `fila` tiver item, processa o próximo.

- [ ] **Step 1: testes que falham** (`rodar_cc`, `responder`, `enviar`, `editar`, `criar_ponto` trocados por fakes; `ESTADO` em `tmp_path`; threads com `join` no teste)
  - `test_normalizar_voz_com_aspas_e_prefixo`: `'"ok"'`→`"ok"`; `'[The user sent a voice message: /x.ogg]\n\n"pode fazer"'`→`"pode fazer"`.
  - `test_normalizar_audio_vazio`: texto começando com `"[The user sent a voice message but it came through empty"` → `""`; `"[voice message could not be transcribed automatically; …]"` → `""`.
  - `test_pergunta_sem_alteracao_entrega_literal`: fake devolve `Resultado(ok=True, texto="A branch é X.", precisa_ok=False, …)` → `responder` chamado com texto exatamente `"A branch é X."` e sem botões; nenhuma fase execução.
  - `test_alteracao_pede_ok_e_nao_executa`: fake plano com `precisa_ok=True` → `responder` com botões `("✅ Executar", "cc:ok:<id>")`, `("❌ Cancelar","cc:no")`; nenhuma chamada com `fase="execucao"`.
  - `test_ok_por_voz_executa_com_ponto`: depois do anterior, `receber("ok")` → `criar_ponto` chamado com os `arquivos` do plano, depois `rodar_cc(..., "execucao", sessao_id)`.
  - `test_texto_qualquer_cancela_plano_pendente`: plano pendente, `receber("na verdade muda o Y")` → plano `None`, nova fase plano com esse texto, nenhuma execução.
  - `test_aprovacao_idempotente_e_expirada`: dois `ao_botao("cc:ok:<id>")` → 1 execução; plano com `criado` há 31 min → recusa ("expirou"); id diferente → recusa.
  - `test_fila_e_parada`: tarefa rodando → `receber("outra")` diz "posição 1"; `receber("para")` chama `executor.cancelar`; ao terminar, a fila roda "outra".
  - `test_falha_nao_trava_fila`: fake devolve `ok=False` → dono recebe "⚠️" e o próximo da fila roda; nenhum caminho chama Gemini/ferramenta do Hermes.
  - `test_hook_so_para_o_dono_e_modo_ligado`: outro `sender_id` → `None`; modo desligado → `None`; ligado → dict `block`.
  - `test_botao_de_outro_usuario_ignorado`.
  - `test_desfaz_repo_local(tmp_path)` (git real em `tmp_path`): ponto; altera arquivo rastreado + cria não rastreado + commit; `desfazer` → árvore idêntica à do ponto (diff vazio, não rastreado novo removido, não rastreado antigo mantido).
  - `test_desfaz_commit_enviado_usa_revert(tmp_path)`: repo com remoto bare; commit + push após o ponto; `desfazer` → histórico do remoto preserva o commit e ganha um revert (sem force).
  - `test_desfaz_arquivo_fora_de_git(tmp_path)`.
- [ ] **Step 2:** FAIL. **Step 3:** implementar `desfaz.py` e `modo_direto.py`. **Step 4:** `PYTEST tests` → PASS. **Step 5:** commit `feat: modo Claude Code direto (plano, ok, execução, fila, desfaz)`.

### Task 5: Registro no Hermes + migração das formas antigas

**Files:**
- Modify: `~/.hermes/plugins/jfn-claude/__init__.py` (`register`), `plugin.yaml` (versão 2.0.0, descrição), docstring do módulo (travas novas)
- Modify: `~/.hermes/config.yaml` (environment_hint: frase nova; backup `config.yaml.bak-cc-direto-20261107`)
- Test: `tests/test_jfn_claude.py` (ajustar), `tests/test_registro.py`

**Interfaces:**
- Consumes: tudo de `modo_direto`.
- Produces: comandos `cc`, `yoda`, `cc-nova`, `cc-para`, `cc-status`, `cc-desfaz` (o gateway troca `_` por `-`); `claude-edita` → `modo_direto.cmd_edita`; `claude-ok` removido; hook `pre_llm_call` → `ao_llm`; `ctx.register_telegram_handler(factory)` onde `factory(app, adapter)` adiciona `CallbackQueryHandler(cb, pattern=r"^cc:")` (import do PTB **dentro** da factory; `cb` responde `answer()` e chama `ao_botao` numa thread); ferramenta `pedir_ao_claude_code` segue só leitura e sua descrição passa a dizer "para alterar algo, diga ao dono para usar /cc ou /claude_edita".
- Nova ferramenta `registrar_no_processo(texto)` (toolset `jfn-claude`): acrescenta `\n<texto>\n` ao fim de `~/.hermes/process_documentation.md` (só acréscimo, Python determinístico) — substitui a instrução de `printf >>` do `jfn-guardas` (spec 5.8).
- environment_hint: acrescentar "VOCÊ NÃO PROGRAMA NEM ALTERA O SISTEMA (regra do dono): editar arquivo, rodar código ou comando que muda algo é só do Claude Code — use pedir_ao_claude_code (leitura) ou diga ao dono para usar /cc (modo Claude Code direto)." (aspas simples dobradas no YAML; validar com `yaml.safe_load` antes de gravar).

- [ ] **Step 1: testes que falham** — `test_registro`: `register(FakeCtx)` registra os comandos acima, o hook `pre_llm_call`, um telegram handler e as 2 ferramentas; `claude-ok` ausente. `test_registrar_no_processo_so_acrescenta(tmp_path)`.
- [ ] **Step 2:** FAIL. **Step 3:** implementar + editar config (backup antes, `yaml.safe_load` depois). **Step 4:** `PYTEST tests` PASS.
- [ ] **Step 5:** `systemctl --user restart hermes-gateway`; esperar 40 s; `systemctl --user is-active hermes-gateway` = `active`; `journalctl --user -u hermes-gateway --since -2min | grep -i "jfn-claude\|error"` sem erro de carga do plugin. Commit `feat: registra modo Claude Code direto no Yoda`.

### Task 6: Trava "Gemini/Hermes não programa" + inventário

**Files:**
- Modify: `~/.hermes/plugins/jfn-guardas/__init__.py`
- Create: `~/.hermes/plugins/jfn-guardas/tests/test_guardas.py`
- Create (relatório): `~/.hermes/plugins/jfn-guardas/INVENTARIO-2026-11-07.md`

**Interfaces:**
- Produces: `antes_da_ferramenta(tool_name, args, **_)` (estende a atual; mantém a regra só-acréscimo); `comando_de_leitura(cmd: str) -> bool`.
  - Sempre bloqueadas: `write_file`, `patch`, `execute_code`, `delegate_task`; `skill_manage` quando `args.get("action")` ∉ `{"view","list","search"}` (conferir os nomes reais das ações no schema da ferramenta e casar).
  - `terminal` (`args["command"]`): permitido só se `comando_de_leitura` — remove antes `2>/dev/null`, `2>&1`, `>/dev/null`, `&>/dev/null`; rejeita se sobrar `>`, `` ` ``, `$(`, `<(`, `sed -i`, `-delete`, `-exec`, `xargs`, `tee`; quebra por `|`, `&&`, `||`, `;` e exige que o 1º token de cada segmento esteja em `LEITURA_OK = {tail, head, cat, grep, rg, ls, wc, du, df, free, uptime, ps, pgrep, date, whoami, hostname, stat, file, find, sort, uniq, cut, awk, jq, journalctl, echo, printf, tr, nl, column, diff, md5sum, sha1sum, basename, dirname, realpath, readlink, nproc, uname, lsblk, ss, crontab(-l só), systemctl(status/is-active/list-units/list-timers/show, com ou sem --user), git(status/log/diff/show/branch/rev-parse/remote), sqlite3(só com -readonly), curl(sem -X/-d/--data/-o/-O/-T/-F), tailscale(status)}`.
  - Mensagem de bloqueio: "BLOQUEADO: o Yoda não programa nem altera o sistema (regra do Mestre Jorge). Para investigar use pedir_ao_claude_code; para alterar, peça ao dono /cc."
- [ ] **Step 1: inventário antes de ligar** — listar o que hoje depende das ferramentas bloqueadas: `~/.hermes/cron/` (jobs e prompts), skills em `~/.hermes/skills/`, `SOUL.md`/`memories/USER.md`/environment_hint, plugins (`jfn-automelhoria`, `jfn-siafe`), e `grep` nos logs recentes do gateway por `tool=write_file|patch|execute_code|terminal` para ver comandos de escrita realmente usados nos últimos 7 dias. Escrever `INVENTARIO-2026-11-07.md`: item, o que faz, o que quebra, migração (Claude Code / plugin determinístico / perde).
- [ ] **Step 2: testes que falham** — parametrizado: permitidos `"tail -n 50 ~/.hermes/logs/x.log"`, `"ps aux | grep hermes"`, `"systemctl --user status hermes-gateway"`, `"git -C ~/JFN log -3"`, `"grep -c x f 2>/dev/null"`, `"sqlite3 -readonly db 'select 1'"`; bloqueados `"echo x > f"`, `"echo x >> ~/.hermes/process_documentation.md"`, `"sed -i s/a/b/ f"`, `"rm f"`, `"python3 x.py"`, `"git commit -m x"`, `"curl -X POST u"`, `"find . -delete"`, `"ls; rm f"`, `"cat $(echo f)"`, `"bash -c ls"`, `"sqlite3 db 'delete from t'"`; e `write_file`/`patch`/`execute_code`/`delegate_task` sempre bloqueados; regra só-acréscimo antiga continua.
- [ ] **Step 3:** FAIL → implementar → PASS (`…/venv/bin/python -m pytest tests -q` dentro de `jfn-guardas`).
- [ ] **Step 4:** migrar o que o inventário apontar como migrável (só instruções de prompt/skill; código Python de plugin não muda); restart do gateway e checagem como na Task 5. Commit `feat: Yoda proibido de programar (só Claude Code altera)`.

### Task 7: Voz PT/EN misturados (STT)

**Files:**
- Modify: `~/stt-venv/hermes_stt.py` (backup `hermes_stt.py.bak-bilingue-20261107`)
- Create: `~/stt-venv/bateria_bilingue.py` (medição, fica para reteste)

**Interfaces:** `hermes_stt.py` mantém a mesma interface de linha de comando que o Hermes usa.

- [ ] **Step 1: bateria** — 12 frases-alvo de comando real misturando PT/EN (ex.: "Claude Code, faz o rebase da branch main e roda os tests", "dá um git stash e depois um pull request", "checa o deploy no Tailscale e o status do gateway", "abre o pull request com o fix do parser"); gerar áudio com Piper (`pt_BR-faber-medium` para tudo — sotaque brasileiro lendo termos em inglês é o caso real) + os 3 áudios reais em `~/.hermes/cache/audio/*.ogg` (texto de referência na memória `yoda-voz-vocabulario-e-profundidade`). Medir WER por configuração: (a) atual (`language="pt"`, `initial_prompt=VOCAB`); (b) `language="pt"` + VOCAB ampliado com termos de dev em inglês (rebase, merge, pull request, stash, fix, bug, deploy, tests, parser, endpoint, log, script, cron, gateway, status, main, review); (c) `language=None` (auto) + VOCAB ampliado. Tempo por áudio também (limite: ≤ 1,5× o atual).
- [ ] **Step 2:** aplicar a configuração com menor WER que cumpra o limite de tempo; rodar a bateria de novo e gravar o resultado (tabela WER/tempo) no topo de `bateria_bilingue.py` como docstring. Prova pelo `transcribe_audio()` do Hermes num áudio da bateria → provider `local_command` e texto certo.

### Task 8: Verificação ponta a ponta, docs e memória

- [ ] **Step 1:** Critérios 1–7 da spec (§7): rodar o que for automatizável (1: hash do `result` no log == hash do texto enviado — adicionar ao log de `modo_direto` `sha_resultado`/`sha_enviado`; 3/4: já cobertos por testes; 6: `hermes chat -t hermes-telegram… -q "edite o arquivo /tmp/x"` → tool bloqueada). 2 e 5: pedir ao dono um áudio real ("/cc" e depois "Claude Code, qual a branch atual?" e "e o último commit?").
- [ ] **Step 2:** `PYTEST` completo nos dois plugins; `systemctl --user is-active hermes-gateway`.
- [ ] **Step 3:** memória: atualizar `yoda-ponte-claude-code.md` (modo direto, comandos, travas, Piper, desfaz) e `yoda-voz-vocabulario-e-profundidade.md` (resultado bilíngue + correção tool_search/toolset de 07/11); índice `MEMORY.md`.
- [ ] **Step 4:** commit+push no `~/JFN` da spec e do plano (`docs:`), branch atual, `tools/pre_push_gate.sh` antes do push.
