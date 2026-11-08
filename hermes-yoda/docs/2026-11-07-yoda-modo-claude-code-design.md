# Yoda ⇄ Claude Code por voz — "modo Claude Code direto" (design)

*07/11/2026 · aprovado pelo dono em conversa (decisões marcadas **[dono]**; escolhas minhas marcadas **[minha]**)*

## 1. Intenção e porquê

O dono quer **controlar o Claude Code da VM-1 pela voz, pelo Telegram (Yoda/Hermes)**, com atrito mínimo:
"voz perfeitamente entendida, que o Code me obedeça pelo Yoda e que o Yoda dê a mesma resposta que o Claude Code".

Hoje o Gemini (cérebro do Yoda) fica no meio: decide se chama o Claude Code (às vezes não chama), e reescreve a
resposta com as palavras dele. Cada pedido abre um Claude Code novo, sem memória do anterior, só leitura, 20 min.

## 2. Objetivos

1. **Resposta idêntica**: no modo direto, o que chega ao dono é o texto do Claude Code **literal**, sem passar pelo Gemini.
2. **Conversa contínua**: áudios sucessivos continuam a mesma sessão do Claude Code (`claude -p --resume <id>`).
3. **Obediência com trava dupla** **[dono]**: antes de alterar qualquer coisa, o Claude Code **mostra o que vai fazer e
   espera o ✅ do dono**; depois de executar, `/cc_desfaz` volta tudo ao ponto anterior.
4. **Resposta também em voz** **[dono]**: toda resposta final vem em texto **e** em áudio.
5. **Voz bem entendida**: eco da transcrição ("🎙️ entendi: …") e Claude Code instruído a corrigir erro fonético pelo contexto.
6. **Só o Claude Code programa** **[dono]**: "o Gemini não pode, em hipótese nenhuma, codar, nem o Hermes".
7. **Custo zero de API**: Claude Code na assinatura (login em `~/.claude/.credentials.json`, sem `ANTHROPIC_API_KEY`
   — conferido), STT local (faster-whisper), TTS local (Piper). Nenhuma API paga é ligada.

## 3. Não-objetivos

- Não trocar o cérebro do Yoda fora do modo direto (segue Gemini para conversa geral, só sem poder de escrita).
- Não dar acesso à VM-2 (só se o dono pedir explicitamente no próprio pedido; regra `vm2-nao-atuar-sem-pedido`).
- Não ter fallback para outro modelo quando o Claude Code falhar.

## 4. Anti-objetivos (falha mesmo que "funcione")

- O Yoda resumir/parafrasear a resposta do Claude Code no modo direto.
- **Executar qualquer alteração antes do ✅** — inclusive por ambiguidade de transcrição.
- Claude Code indisponível (cota, erro, timeout) e o Gemini "quebrar o galho" programando. Deve avisar e parar.
- Perder trabalho sem volta (force push, reescrita de histórico já publicado, `rm` em massa).
- Credencial em código, log, mensagem ou áudio.

## 5. Comportamento

### 5.1 Ligar/desligar **[minha]**
- `/cc` liga o modo direto no chat do dono; `/yoda` volta ao Yoda normal; `/cc_nova` encerra a sessão e começa outra.
- Estado persistido em arquivo (sobrevive a reinício do gateway). Só o dono (sender id autorizado, lido de config/env,
  não hardcoded no repo público) pode usar; outros remetentes são ignorados pelo modo.

### 5.2 Fluxo de cada mensagem (texto ou voz)
1. Voz → transcrição local (já existente) → eco "🎙️ entendi: …" (`stt_echo_transcripts`, conferir que está ligado).
2. Plugin intercepta o turno **antes do Gemini** (hook `pre_llm_call` com `{"action":"block","message":…}` — o turno
   acaba sem inferência; confirmado no código do Hermes, `agent/turn_context.py`). O texto já vem transcrito nesse ponto.
3. **Fase PLANO (só leitura)**: `claude -p --resume S` com ferramentas só de leitura (como o modo leitura atual).
   O prompt do sistema manda: investigar; responder; se o pedido exigir alterar algo (arquivo, git, serviço,
   config, banco, processo), **não alterar** — descrever o plano concreto (arquivos, comandos, efeito, risco) e
   terminar com o marcador `[[PRECISA_OK]]`.
   - Sem marcador → é resposta final: entregue literal (texto + voz). Fim.
   - Com marcador → plano entregue literal + botões **✅ Executar / ❌ Cancelar**.
4. **Aprovação**: botão ✅, ou texto "ok"/"pode"/"executa", ou voz cuja transcrição inteira seja uma dessas palavras
   (lista fechada, curta) **[minha]**. Qualquer outra mensagem com plano pendente = **cancela o plano** e vira novo
   pedido na mesma sessão (o dono pode estar corrigindo). Plano pendente expira em 30 min **[minha]**.
5. **Ponto de restauração** antes de executar (ver 5.4).
6. **Fase EXECUÇÃO**: `claude -p --resume S` com escrita liberada, instruído a executar **só o plano aprovado**;
   se precisar sair dele, parar e voltar com novo plano `[[PRECISA_OK]]`.
7. Resultado final literal (texto + voz) + "↩️ /cc_desfaz desfaz isto".

### 5.3 Progresso e controle
- Saída `--output-format stream-json`; uma única mensagem de status editada a cada ~5 s ("lendo X", "rodando Y").
- "para" / `/cc_para` interrompe (mata o grupo de processos, como o plugin já faz).
- Uma tarefa por vez; mensagem que chega durante uma tarefa entra em **fila** (avisa "na fila, posição N").
- Limite por fase: 30 min **[minha]** (configurável).

### 5.4 `/cc_desfaz`
- Antes da execução, em cada repositório git tocado (no mínimo o cwd da sessão, `~/JFN` por padrão): registrar HEAD e
  um snapshot do working tree incluindo não rastreados (`git stash create` + ref própria `refs/cc-desfaz/<ts>`).
- Fora de git (ex.: `~/.hermes/config.yaml`): copiar o arquivo para backup antes — o Claude Code deve listar no
  plano os arquivos fora de git que vai tocar; o plugin faz o backup deles.
- `/cc_desfaz` restaura o último ponto. Commits **já enviados** (push) são desfeitos com `git revert`, nunca reescrita
  de histórico. Desfaz também precisa de ✅ (mostra o que vai voltar).
- Limite honesto: efeitos fora de arquivo (mensagem enviada, serviço reiniciado, chamada externa) não se desfazem —
  o plano deve marcá-los como **irreversíveis**.

### 5.5 Proibições do Claude Code pelo Yoda (sempre, mesmo com ✅)
`git push --force*`, `git reset --hard` em branch publicada, `rm -rf` fora do scratch, `pkill -f`, `sudo`,
mexer em `~/yt-login`, `.env`/credenciais (ler ou imprimir), ssh para VM-2 sem pedido explícito, ligar API paga.
Via `--disallowedTools` + texto no prompt do sistema.

### 5.6 Voz na resposta
- TTS **Piper local**, voz pt-BR (o Hermes já suporta provider `piper`) **[minha]**; `edge` não (serviço externo).
- Lê o texto integral, exceto blocos de código, caminhos longos e hashes (trocados por "código omitido no áudio").
  **[dono] texto e voz simultâneos, em TODA resposta** (resposta final, plano e avisos): o TTS começa no mesmo
  instante em que a resposta existe, em paralelo; o texto sai na hora e a voz logo em seguida (segundos — o tempo
  de síntese do Piper). Nunca só um dos dois, salvo falha do TTS, que nunca bloqueia nem atrasa o texto.

### 5.7 Gemini/Hermes proibidos de programar (global, todas as plataformas e crons)
Trava determinística em `pre_tool_call` (plugin `jfn-guardas`), como a já existente:
- **Bloqueados sempre**: `write_file`, `patch`, `execute_code`, `delegate_task`, `skill_manage` (criação/edição).
- `terminal`: só comandos de leitura numa **lista permitida** (`tail`, `cat`, `grep`, `ls`, `systemctl status`,
  `journalctl`, `git status/log/diff`, `sqlite3 -readonly`…); redirecionamento `>`/`>>`, `sed -i`, `tee`, `rm`, `mv`,
  `cp`, `git commit/push`, instaladores etc. → bloqueado com mensagem "peça ao Claude Code (`pedir_ao_claude_code`)".
- Exceção existente a preservar: o acréscimo em `process_documentation.md` vira tarefa do Claude Code ou do próprio
  plugin (Python determinístico), não do Gemini.
- **Antes de ligar**: inventariar crons/skills/plugins do Hermes que hoje dependem dessas ferramentas (ex.:
  automelhoria) e reportar ao dono o que deixaria de funcionar. Código Python de plugin não é "Gemini programando".

### 5.8 Decisões fechadas após a revisão do construtor
- **Escopo da EXECUÇÃO = igual ao terminal** **[dono]**: após ✅, Claude Code pode editar qualquer arquivo do dono,
  rodar comandos, reiniciar serviços, mexer na config do Hermes. As proibições do 5.5 seguem (via
  `--disallowedTools` + prompt). Limite assumido: veto por prefixo é contornável; a trava real é o plano lido e o ✅.
  Backup prévio de todo arquivo fora de git citado no plano.
- **`git push` comum** é permitido na EXECUÇÃO, após ✅ (regra da casa: "todo código JFN → commit+push"); force push nunca.
  `/cc_desfaz` de commit já enviado = `git revert` + push do revert, também com ✅. **[dono, regra existente]**
- **Trava 5.7 entra LIGADA nesta entrega** ("em hipótese nenhuma" **[dono]**). Antes de ligar, o inventário é
  feito e o que quebrar é migrado: a instrução do `jfn-guardas` que manda o modelo usar `printf >>` vira uma
  ferramenta determinística do plugin (`registrar_no_processo`, só acréscimo). O que não der para migrar é
  reportado ao dono no fim da entrega. **[minha, a partir da regra do dono]**
- **Formas antigas** **[minha]**: `/claude` e `pedir_ao_claude_code` seguem (só leitura). `/claude_edita` passa a
  usar o fluxo novo plano→✅ (o `/claude_ok CÓDIGO` some). Uma única fila/trava para tudo.
- **Voz**: o texto do turno chega entre aspas/com prefixo de mídia — normalizar antes de comparar com a lista de
  aprovação. O hook não tem `chat_id`: respostas assíncronas pela API do Telegram (como hoje), destino = chat do dono.
- **Botões**: via `ctx.register_telegram_handler` (peça nova no plugin).
- **Piper**: venv próprio `~/tts-venv` (fora do Hermes, sobrevive a `hermes update`), voz `pt_BR-faber-medium`
  (instalada e testada 07/11: 6 s de fala em ~8 s). Dicionário de pronúncia (Claude Code, branch, JFN, commit…).

## 6. Restrições
- VM de 2 vCPU: um Claude Code por vez; `nice -n 10` como hoje; transcrição + TTS não podem travar o gateway (thread).
- Nada de segredo em código/log; JFN é repositório **público** (não versionar ids de chat, tokens).
- Não usar `pkill -f`; matar por PID/grupo.
- `hermes update` destrói patches locais → tudo em plugin, nada no core do Hermes.

## 7. Critérios de aceite (verificáveis)
1. Modo direto: pergunta por voz → resposta no Telegram **byte-idêntica** ao `result` do Claude Code (log compara hash).
2. Segundo áudio "e o que mais?" responde com contexto do primeiro (mesmo `session_id`).
3. Pedido de alteração → plano + botões; **nenhum arquivo muda** até o ✅ (teste: mtime/`git status` antes/depois).
4. ✅ executa; `/cc_desfaz` + ✅ volta o repo ao estado anterior (diff vazio contra o snapshot).
5. Resposta chega também em áudio pt-BR, gerado localmente.
6. No modo normal, pedir ao Yoda "edite o arquivo X" → ferramenta bloqueada; ele encaminha ao Claude Code.
7. Claude Code fora (simulado) → aviso claro, Gemini não programa.

## 8. Deixado ao construtor
Nomes internos, formato do estado, layout dos testes, texto exato dos prompts, como detectar repositórios tocados,
temporização do status. Construir no plugin `jfn-claude` existente (estender, não reescrever o que funciona).
