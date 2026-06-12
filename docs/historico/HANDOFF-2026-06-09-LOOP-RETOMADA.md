# HANDOFF / RETOMADA — Sessão longa 2026-06-08/09 (ler PRIMEIRO)

> Escrito para a próxima IA continuar SEM PERDA. Estado vivo, branches, o que fazer, erros & acertos.
> Diretriz do dono: loop contínuo de melhoria (5 loops); outputs perfeitos; ecossistema integrado/baixa
> fricção; grátis (respeita VM); rápido/fluido/belo/sem ruído; **sistema pensante** em JFN/Lex/Massare.

## ⏯️ ESTADO VIVO AGORA
- **Branch de trabalho:** `feat/lista-limpa` (off `sei-precos-onda5`). **NÃO pushado.** Tudo commitado (sem perda).
- **`jfn.service` é USER service:** `systemctl --user restart jfn.service` (NÃO `sudo`). Roda do dir `~/JFN`.
  - ⚠️ O serviço vivo foi reiniciado em `feat/lista-limpa` AINDA NO COMMIT DO `/lista` — os commits
    posteriores (OB-enxuta, LLM, Lex discursivo, guard SEI) **NÃO estão live** até um novo restart.
    Para ativar tudo: `systemctl --user restart jfn.service` (aguardar ~25s; evita restart enquanto o dono
    gera relatório — interrompe a entrega no Telegram, erro já cometido nesta sessão).
- **Bot vivo:** `hermes-gateway.service` (Yoda, `~/hermes-agent`, venv = `venv/` não `.venv/`). One-shot:
  `cd ~/hermes-agent && PYTHONPATH=. venv/bin/python -m hermes_cli.main -z "mensagem"`.
- **Enviar arquivo ao Telegram do dono** (quando a entrega falhar): carregar `.env` primeiro —
  `from compliance_agent.envfile import carregar_env; carregar_env()` → setar `tg.BOT_TOKEN/CHAT_ID` de
  `os.environ` → `await tg.enviar_arquivo(path, caption)`. (Foi assim que reenviei os relatórios.)

## 🧭 O ARCO DESTA SESSÃO (resumo honesto)
1. Construí uma **camada V2 "perfeição"** enorme (branches `feat/v2-perfeicao` + `feat/v2-wiring`, ~25 commits).
2. O 1º `/relatorio` real saiu PIOR → o dono mandou **REVERTER** ao estado anterior (`sei-precos-onda5`).
   Lição em [[licao-v2-revertida-2026-06-08]]: **gerar o artefato real cedo**; **wiring mínimo**; nunca LLM
   síncrono no hot-path sem cache+bound; mudança pequena/isolada/verificada > camada grande.
3. Reapliquei os ganhos REAIS da V2 como mudanças pequenas e verificadas em `feat/lista-limpa` (Loop 1).

## ✅ FEITO em `feat/lista-limpa` (commits, do mais antigo ao novo)
- `/lista` curado (10 funções/3 grupos vs 47 itens crus; `/skills`=completo) — `skilltree.py:render_menu` + `_MENU_PUBLICO`.
- OB enxuta: top-12/exercício no MD e PDF (FPDF fornecedor+órgão); completo na planilha XLSX. ITERJ 253→63KB.
- LLM robusto: `direcionamento_cerebro` — `_gemini_keys()` (pool 9 chaves de `~/.hermes/.env`; as do JFN/.env
  estão MORTAS), `gerar_gemini` multi-modelo+backoff, bridge `gerar_sync` (loop dedicado p/ chamar de sync).
- Lex **análise discursiva** (onde+por quê): `_trecho` (excerpt), `analise_discursiva` (1 chamada LLM, bound 45s,
  flag `JFN_LEX_DISCURSIVO=1`), render no `parecer_md`. Wiring em `lex.gerar`.
- Guard `_eh_interface_sei`: rejeita a tela/menu do SEI como conteúdo.
- `docs/LOOP-MELHORIA-2026-06-09.md` (log dos loops).

## 🐞 ACHADO CRÍTICO (Loop 1→2) — DIAGNÓSTICO PRECISO, FIX a executar
**A leitura do SEI retorna o MENU/desktop, NÃO o inteiro teor.** Evidência no cache real
`data/sei_cache/cdp_SEI_070002_004332_2024.json` (processo da Extreme): `texto`=menu lateral do SEI;
`n documentos:0`; `conteudo_documentos:0`; **`cadeado:False`, `n_docs_restritos:0` (NÃO é restrição)**;
`relacionados:40` → o leitor ficou na **CAIXA/DESKTOP** (≈40 processos recebidos) e **não abriu o processo**.
**Root cause:** bug de NAVEGAÇÃO em `collectors/sei_cdp.py::ler_processo_sei_via_chrome` (≈L439; extração
L570/708): loga (itkava, perfil ITERJ/CHEGAB) mas não pesquisa+abre o processo-alvo → captura o desktop.
SEI usa **frames** — conteúdo do doc no iframe (`ifrArvore` árvore + `ifrVisualizacao` conteúdo), não na página.
**FIX (Loop 2, sessão nova):** pesquisar nº → abrir processo → entrar no `ifrArvore` → iterar docs → abrir no
`ifrVisualizacao` → extrair texto (preencher `documentos`+`conteudo_documentos`). Testar AO VIVO (Chrome 9222
itkava) com SEI-070002/004332/2024 até `n documentos>0`. Aí o Lex discursivo cita trecho REAL.
Mitigação atual: guard `_eh_interface_sei` mantém o parecer honesto ("não lido"). Ver [[sei-login-itkava]].

## 🎯 BACKTEST (estado atual, sei-precos-onda5 base)
- Suíte: ~28 arquivos verdes; 6 hangs de rede (integração: PNCP/SEI). `test_imports_smoke` 151 (imports OK).
- Lex offline (onda2/onda5): 3 passed com as mudanças. direcionamento: 6 passed. Rodar:
  `PYTHONPATH=. .venv/bin/pytest tests/test_jfn2_onda5.py -k "lex or sei" -p no:cacheprovider`.

## ✅ 5 LOOPS EXECUTADOS (2026-06-09) — detalhe em `docs/LOOP-MELHORIA-2026-06-09.md`
- **L1:** /lista curado · OBs enxutas · LLM robusto (9 chaves) · Lex discursivo · wiring SIAFE (Yoda retorna números).
- **L2:** frescor/cobertura no topo dos relatórios (verificado).
- **L3:** encaminhamento por severidade no parecer (acionável; grav≥3→requerimento/representação).
- **L4:** wiring `/api/cartel` GET+POST (Yoda chutava método→405) — verificado end-to-end (Yoda retorna análise).
- **L5:** avaliação Massare + backtest final (161 passed; corrigido o teste que forçava o /lista poluído).
- Autonomia dada pelo dono: religar/ajustar à vontade; "fazer melhorias em tudo, inclusive Hermes/Yoda".

## 🔜 2 FIXES PROFUNDOS p/ SESSÃO NOVA (orçamento cheio + teste ao vivo) — alto valor
1. **Coletor SEI → inteiro teor** (`collectors/sei_cdp.py::ler_processo_sei_via_chrome`): hoje fica na
   CAIXA/desktop (cache: `n documentos:0`, `relacionados:40`, `cadeado:False`). Navegar: pesquisar nº →
   abrir processo → `ifrArvore` → iterar docs → `ifrVisualizacao` → extrair. **Desbloqueia o "onde/por quê"
   do Lex** (a análise discursiva e o guard já estão prontos esperando o input real). Testar AO VIVO (Chrome
   9222 itkava) com SEI-070002/004332/2024 até `n documentos>0`.
2. **Scorer OOS do Massare**: 44 previsões PENDENTES, 0 resolvidas, hit_rate=null (`/api/massare/placar`).
   Rodar/agendar a cobrança contra o realizado (`massare/validation.py`/`learning.db`) → track record honesto.
**Padrão comum dos dois:** a estrutura existe, falta FECHAR O CICLO (Lex lê mas não chega ao doc; Massare
prevê mas não cobra). Esse é o tema do "sistema pensante" — execução do último elo.

## TODO menores (loops futuros)
- Yoda usa `terminal`+`curl` e chuta o método HTTP → ou aceitar GET+POST nas rotas GET sensíveis, ou dar ao
  gateway um executor HTTP que respeite o `metodo` do contrato (TODO gateway `~/hermes-agent`).
- "o que você faz?" no Yoda devolve o menu do gateway, não o `/lista` curado — surfaçar o /lista direto.
- Latência do /relatorio (60-90s): LLM discursivo é bounded+cacheável (cache não portado nesta branch).

## ⚠️ NÃO REPETIR (erros desta sessão)
- Não reiniciar `jfn.service` enquanto o dono usa (interrompe a entrega no Telegram).
- Não bolar LLM no hot-path sem cache+bound+verificação do artefato real.
- Não construir camadas grandes; pequeno/isolado/verificado.
- Verificar o PDF (artefato enviado), não só o MD — há 3 renderizadores (MD, FPDF, HTML).

## 🔑 FATOS-CHAVE
- DB real: `data/compliance.db`. `jfn.service` user. LLM válido só Gemini (9 chaves `~/.hermes/.env`); Groq/
  OpenRouter sem credencial/crédito. `favorecido_cpf`=CNPJ(14díg)/CPF(11). UG 133100=ITERJ.
- Branches: vivo=`sei-precos-onda5`+`feat/lista-limpa`(trabalho); abandonadas=`feat/v2-perfeicao`/`feat/v2-wiring`
  (resgatáveis). Cruzamento sócio×OB×SEI×endereço FUNCIONA (não era V2).
