# CONSTITUIÇÃO DO ECOSSISTEMA — Mestre Jorge

> Regras OBRIGATÓRIAS para Hermes, Yoda (bot) e JFN. Leia ANTES de mexer em qualquer arquivo.
> Objetivo: nunca bagunçar nem apagar o trabalho validado. Pode CRIAR e TESTAR — só não DESTRUIR.

## 1. ZONAS (blocos fechados)
- **`_PROTEGIDO/`** → trabalho validado (cópia-ouro). **NUNCA editar, apagar, mover ou sobrescrever.**
  Só o Mestre Jorge (ou o Claude, quando ele pedir) altera. Os arquivos vivos equivalentes
  estão marcados como SOMENTE-LEITURA no Windows.
- **`_SANDBOX/`** → área de experimentos. Os agentes PODEM criar/testar à vontade aqui.
  É onde coisas novas nascem e são validadas antes de "promover" pro repositório.
- **Resto do repo** → código de produção do JFN. Mudanças só com commit (ver regra 3).

## 2. REGRA DE OURO
- **Adicionar e testar = SIM** (sempre em `_SANDBOX/` ou arquivo novo).
- **Apagar/sobrescrever trabalho validado = NÃO.** Se algo precisa mudar, crie uma CÓPIA
  nova no `_SANDBOX/`, teste, e só então o Mestre Jorge valida e promove.

## 3. GIT (rede de segurança)
- **Sempre commitar** antes de mudanças grandes. Mensagens claras.
- **NUNCA** `git reset --hard`, `git clean -fdx`, `git push --force` em branch protegida.
- `.pem`, `.env`, segredos: **NUNCA commitar** (já estão no `.gitignore`).
- Branch de trabalho: `claude/rj-finance-agent-BYlhJ`.

## 4. INFRA (proibições que já causaram estrago)
- **NUNCA** `hermes update` / `--force` → já destruiu o venv. Use `hermes-yoda/scripts/atualizar-hermes.cmd`.
- **NUNCA** `taskkill` solto nem matar por nome → use `hermes-yoda/scripts/bot-control.ps1`.
- **NUNCA** editar `config.yaml` "no chute". Há a cópia-ouro em `_PROTEGIDO/config/config.golden.yaml`
  para restaurar se quebrar. Conferir o par provider/model/base_url certo.
- Subir bot+painel: launchers em `hermes-yoda/scripts/` (com auto-retry, ocultos).

## 5. SE ALGO QUEBRAR
1. Não entre em pânico nem apague nada.
2. Restaure do `_PROTEGIDO/` (cópia-ouro) ou do git.
3. Avise o Mestre Jorge no Telegram: "a ação X causou o erro Y; restaurei do backup Z".

## 6. MODELOS / IAs
- Time com fallback automático em `config.yaml` (Gemini 8 chaves em rodízio → grátis de reserva).
- Modelo limitado? Dê instruções simples e diretas. Se uma IA falha/limite, a próxima assume.

## 7. SEGREDOS
- Tudo em `~/.hermes/.env` (fora do git). Chaves Gemini, token Telegram, GitHub, SEI.
- Nunca expor segredo em chat, log ou commit.

---
*Esta constituição é a fonte de verdade das regras. Atualize-a só com o aval do Mestre Jorge.*
