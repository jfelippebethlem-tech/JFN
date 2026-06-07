# Aprendizados da sessão 2026-06-07 — erros & acertos (para NÃO repetir)

> Diretriz do Mestre Jorge: documentar cada erro e acerto para não tentarmos as mesmas coisas de novo.

## SIAFE — varredura da OB Orçamentária
**ACERTOS**
- A coleta FUNCIONA da VM: siafe2 acessível (HTTP 200); login em ~14s **reusando a sessão salva** (`data/sei_cache/siafe_state.json`) → **sem MFA** (device-trust); navega Execução > Execução Financeira > OB Orçamentária; colhe 23 colunas, **incluindo "Processo" (SEI)**.
- A 1ª execução foreground (redirect p/ arquivo) colheu 50 OBs em ~33s.

**ERROS / ARMADILHAS (não repetir)**
- `--max 100000` faz o `_colher` rolar a tabela ADF "infinitamente" → trava. Usar `--max` modesto.
- **A tela NÃO tem o checkbox que remove o teto de ~1000/consulta** ("checkbox ausente nesta tela"). Logo, scroll-sweep só pega ~1000/consulta. Para "tudo" é OBRIGATÓRIO iterar por **UG e/ou competência** (cada consulta < 1000). Esse é o gargalo §8b já conhecido.
- **Background TRAVA**: rodar via `nohup bash -c` OU `run_in_background` do harness → o chromium headless trava no launch em contexto **detached** (nunca imprime nem "login: iniciando"). Só **foreground via Bash tool** funciona.
- **`timeout` deixa o chromium ÓRFÃO vivo**: ao matar o python, o Chromium filho sobrevive e **segura a sessão única do SIAFE** → a PRÓXIMA execução trava no login. **SEMPRE matar o chromium leftover (por PID) ANTES de cada run.**
- `pkill -f "<padrão>"` **mata o próprio shell do Bash tool** quando o padrão (ex.: `siafe_ob_orcamentaria`, `playwright_chromiumdev_profile`) também casa a linha de comando atual → exit 144/1 e comando abortado. **Matar por PID numérico explícito (via `kill <pid>`), nunca por padrão que case o comando corrente.**
- O sweep faz **login fresco** (não carrega `storage_state` no `new_context`); só SALVA o estado após navegar. Depende de `SIAFE_USER/SIAFE_PASS` no `.env`.

**RECEITA QUE FUNCIONA (provável)**: matar chromium leftover por PID → rodar foreground, `--ingerir --resiliente --max ~1000`, redirect p/ arquivo (não pipe), 1 exercício por vez; para "tudo", loop por UG.

## Banco (compliance.db) — depuração
- **NÃO há duplicata real** em `ordens_bancarias` (1.121.303 linhas): a chave única é **`numero_ob + ug_codigo + exercicio`** (0 excedentes; 0 grupos com valor divergente). `numero_ob` sozinho "repete" porque cada UG tem sua sequência → deduplicar por `numero_ob` apagaria ~928k OBs legítimas. **NÃO deduplicar por numero_ob.**
- Correlação OB↔SEI: casar **numero_ob + ug** (SIAFE `ug_pagadora` = TFE `ug_codigo`); casar só por numero_ob "sobrecola" 1:N. Teto de dados = 496 OBs TFE casadas + 2.267 OBs SIAFE já com `processo` (TFE e SIAFE cobrem subconjuntos diferentes).

## Lex — instrumentalização
- Módulos novos: `lex_sancoes.py` (dosimetria; inidoneidade só com dolo), `lex_indicadores_fraude.py` (14 indicadores; +Benford +desconto-decrescente da pesquisa), `lex_base_empirica.py` (aprende de compliance.db → `memoria_aprendizado`). Integrados ao `parecer_md` (seções III-C, IV-C, régua empírica) best-effort.
- PDFs de fonte: alguns vêm **cifrados por fonte custom** (glifos deslocados). Decodificação: **+29 por byte** na faixa imprimível (ex.: "3XEOLFLGDGH"→"Publicidade"). pypdf não resolve sozinho; sem poppler/pymupdf na VM (Read de PDF não renderiza).

## Folhas de pagamento (PENDENTE)
- `registros_folha` está VAZIA (schema pronto). `terceirizados.py` usa o portal **federal** (terceirizados), não a folha estadual.
- Os 6 órgãos (TJRJ/MPERJ/TCERJ/Defensoria/UERJ/UENF) são **autônomos** → cada um tem portal próprio; Transparência RJ não expôs endpoint óbvio (`/servidores` etc. = 404). Precisa **descobrir a fonte por portal** (build à parte).

## Yoda/Hermes
- Em DM 1:1 o Hermes NÃO injeta a identidade do remetente no prompt (só em grupo). Patch em `gateway/run.py:8491` (reaplicar após `hermes update`). environment_hint id-keyed (sem marcação = admin Jorge).

## SIAFE — matriz de abordagens (análise consolidada 2026-06-07)
TENTADAS: Playwright fill/dispatch ❌ (PPR não dispara) | keyboard.type+Enter no filtro ✅ (contratos) | PPR HTTP replay (siafe_ppr.py) ✅ parcial (scroll, não filtro) | chkRemoveLimit ❌ ausente na tela OB | selUg ❌ não filtra | GitHub Actions (Azure IP) ✅ aceito | Computer Use ⏳ não testado.
NÃO TENTADAS (prioridade):
  1. **PPR HTTP com FILTRO replicado** (maior retorno): capturar o POST do ADF (javax.faces.partial.ajax=true, source=pt1:tblOBOrcamentaria:sdtFilter, cbx_col_sel=1 UG Emitente, cbx_op_sel=0 igual, in_value=<UG>) via page.on("request") numa execução manual, depois replicar via context.request.post() por UG. Sem browser. Evolução do siafe_ppr.py.
  2. **Faixa de Data Emissão por quinzena** (keyboard.type já validado, risco zero): ~50 consultas/ano, cada <200 OBs (sem teto).
  3. **Número da OB "começa com"** (Prop=0, Op=8): prefixo 2026OB0X → blocos de 1000; ~10 consultas/10k OBs.
  4. **btnImprimir** (tbrBotoes:btnImprimir): abre relatório de impressão SEM limite de linhas → parsear HTML. 5min de teste, possível jackpot.
  5. **"Pertence" com lista** (Op=10, separador ;): agrupar 5-10 UGs por query.
  6. ViewState via CDP + AdfPage.PAGE submit interno (experimental).
  7. **Delta-only**: já temos 1,12M OBs do TFE; o SIAFE só agrega a coluna Processo(SEI). Varrer só as OBs SEM SEI (filtro Número), zero desperdício de sessão.
RECOMENDAÇÃO: 1 (PPR+filtro) > 2 (data, fallback) > 4 (btnImprimir, teste rápido).
