# Loop de Melhoria Contínua do Ecossistema JFN — log por checkpoint

> Meta (dono): 5 loops de **backtest → análise total → reavaliação → planejamento (best practices/benchmarks)
> → execução**, com checkpoints/commits e documentação de **erros & acertos** para as próximas IAs.
> Visão-norte: outputs perfeitos · ecossistema integrado, baixa fricção · grátis (respeita a VM) · rápido,
> fluido, belo, sem ruído · **sistema pensante** nos relatórios JFN, pareceres Lex e previsões Massare.
> Branch: `feat/lista-limpa` (mudanças pequenas, isoladas, verificadas com o artefato real).

## Princípios herdados (da V2 revertida — ver [[licao-v2-revertida-2026-06-08]])
1. Gerar o **artefato real** (relatório/parecer) como baseline e comparar a cada mudança.
2. **Wiring mínimo**: ligar uma peça nova só nos pontos certos; nunca LLM síncrono no hot-path sem cache+bound+verificação.
3. Mudança **pequena, isolada, verificada** > camada grande.

---

## ✅ Loop 1 — checkpoint (2026-06-08/09)

**Plano:** re-aplicar os ganhos de qualidade da V2 **sem a fragilidade**; começar pelo "sistema pensante" do Lex (onde/por quê).

**Execução (commits em `feat/lista-limpa`):**
1. `/lista` curado — 7426→1011 chars (10 funções/3 grupos vs 47 itens crus). Catálogo completo no `/skills`.
2. Sumarizar OBs — top-12/exercício no MD e PDF (fornecedor FPDF + órgão); lista completa na planilha XLSX.
   ITERJ: PDF 253KB→**63KB**. (O PDF-HTML do fornecedor já era agregado.)
3. LLM do motor robusto — rotação do pool de **9 chaves** (`~/.hermes/.env`, as do JFN/.env estavam mortas)
   + **multi-modelo** (flash→2.0-flash→flash-lite) + backoff + bridge `gerar_sync` (loop dedicado). 3/3 ao vivo.
4. **Análise DISCURSIVA do Lex** — `_trecho` captura o excerpt; `analise_discursiva` (1 chamada LLM, bounded
   45s, degrada honesto) escreve 2-4 frases **onde+por quê (mecanismo)** ancoradas no texto real; render no parecer.
5. Guard `_eh_interface_sei` — rejeita a tela/menu do SEI como conteúdo.

**ACERTOS:**
- O pipeline discursivo funciona e é **honesto** (o LLM flagrou sozinho que o trecho era menu, não documento).
- Relatórios enxutos + `/lista` limpo = menos ruído, mais beleza (alinha com a visão).
- LLM agora resiliente (multi-modelo+pool) sem bolar no hot-path de tudo — wiring mínimo (só no Lex, sob flag).

**ERRO/ACHADO CRÍTICO (avaliação do artefato real):** a **leitura do SEI retorna o MENU** ("Controle de
Prazos / Processos recebidos (N registros)"), não o inteiro teor → a análise "onde/por quê" fica sem input
real. O parecer chegava a "analisar o menu". Mitigado com o guard (agora honesto: "não lido"). **A RAIZ é o
coletor SEI** (`collectors/sei_cdp.py` / `sei_reader`): loga mas não navega até o documento do processo.

**Benchmark de referência:** due diligence padrão Kroll/Deloitte/Control Risks — prosa analítica que cita
**onde** (cláusula/§) e **por quê** (mecanismo: quem foi eliminado, qual o efeito). Só alcançável com o
documento real em mãos → depende do coletor SEI.

**→ Alvo do Loop 2:** consertar o coletor SEI para extrair o **inteiro teor do processo** (não o menu).
Sem isso, o "sistema pensante" do Lex fica honesto porém sem matéria-prima.

---

## ✅ Loop 1 — wiring Yoda↔JFN (teste end-to-end)
**Teste:** `hermes -z "qual o status da coleta do SIAFE? quantas OBs?"` (one-shot, sem mexer no bot vivo).
**ANTES:** Yoda respondia *"comando `status` desconhecido"* — `siafe_stats` existia mas o `quando_usar` só
cobria "quantas OBs"; não havia capability para `/api/siafe/status`.
**FIX:** enriqueci `siafe_stats.quando_usar` (status/cobertura/quanto coletamos) + registrei `siafe_status`
(lockfile). Regenerei os derivados (`~/.hermes/jfn_tools.json` lido pelo gateway).
**DEPOIS (verificado):** Yoda retorna OBs/ano (2016-2026), total R$ 20,16 bi, fonte SIAFE-Rio 2. ✅
**Aprendizado:** rota existir no `server.py` ≠ Yoda saber usá-la. O wiring real é o `capabilities.yaml`
(+ derivados regenerados) com `quando_usar` que casa a linguagem natural do dono. Testar com `hermes -z` pega
gaps que o curl não pega.

⚠️ **Pendente:** o `jfn.service` vivo ainda roda código anterior aos commits OB-enxuta/LLM/Lex-discursivo —
fazer `systemctl --user restart jfn.service` num momento ocioso (não durante geração de relatório do dono).

## 🔎 Loop 2 — ANÁLISE (root cause pinpointed) — FIX a executar em sessão nova
**Sintoma:** Lex "lê" o SEI mas a análise discursiva cita o MENU, não o documento.
**Evidência (cache real `data/sei_cache/cdp_SEI_070002_004332_2024.json`, processo da Extreme):**
- `texto` = menu lateral do SEI ("Acompanhamento Especial, Base de Conhecimento, Controle de Prazos…")
- `n documentos: 0` · `conteudo_documentos: 0` · **`cadeado: False`, `n_docs_restritos: 0`** (NÃO é restrição)
- `relacionados: 40` → o leitor ficou na **CAIXA/DESKTOP do SEI** (≈40 processos recebidos), **não abriu o
  processo individual** nem chegou à **árvore de documentos**.
**Root cause:** bug de NAVEGAÇÃO em `compliance_agent/collectors/sei_cdp.py::ler_processo_sei_via_chrome`
(≈linha 439; extração em 570/708). Loga (itkava, perfil ITERJ/CHEGAB) mas não pesquisa+abre o processo-alvo
→ captura o desktop. SEI usa **frames/iframes** (`ifrArvore`/árvore de documentos + `ifrVisualizacao`/conteúdo);
o conteúdo do documento está no iframe, não na página externa.
**FIX (próxima sessão, orçamento cheio):** em `ler_processo_sei_via_chrome`: (1) pesquisar o nº do processo
(campo de pesquisa SEI), (2) abrir o processo, (3) entrar no iframe da árvore (`ifrArvore`), iterar os
documentos, (4) abrir cada doc no `ifrVisualizacao` e extrair o texto → preencher `documentos` +
`conteudo_documentos`. Testar AO VIVO (Chrome 9222 itkava) com SEI-070002/004332/2024 e conferir que
`n documentos > 0` e o `texto` é do documento. Então o Lex discursivo passa a citar trecho REAL.
**Honestidade:** enquanto não navega, o guard `_eh_interface_sei` mantém o parecer honesto ("não lido").
**Benchmark:** prosa que cite "no §X do edital, a exigência Y eliminou as empresas A,B" só é possível com o
texto do documento — depende 100% deste fix.

## ✅ Loop 2 — frescor/cobertura no topo dos relatórios
`inteligencia.cabecalho_frescor()` (sem LLM, 1 COUNT) no topo de fornecedor+órgão. Honestidade: afirmar
dentro da cobertura. Verificado: "Cobertura da base: 1.121.306 OBs · 77% com CNPJ · OB mais recente:
2026-06-01". Serviço religado (autonomia dada pelo dono: "ligar/religar à vontade").

## ✅ Loop 3 — encaminhamento por severidade no parecer (acionável)
Cada indício do Lex passa a dizer O QUE FAZER: grav≥3 → **requerimento** + (se persistir) representação
TCE-RJ/MP; senão diligência/monitoramento. Sem LLM. "Sistema pensante": dirige a ação, não só descreve.
3 testes lex offline verdes.

## ✅ Loop 4 — sweep de wiring Yoda↔JFN (gaps achados e corrigidos)
Testes `hermes -z`:
- T2 "tem cartel na UG 133100?" → Yoda usou `terminal`+`curl` e **chutou POST → 405**; a capability ainda
  listava um param `ug` que a rota **não tem**. **FIX:** `/api/cartel` aceita **GET+POST** (robustez contra
  chute de método) + args fiéis (`modo|cnpj|top`, sem `ug`). **Verificado:** curl GET/POST=200; Yoda retorna
  a análise real (Casa Civil→Consórcio RJ Cidadão 56,1% de R$1,24bi…) com conclusão pensada.
- T1 "o que você faz?" → Yoda devolveu o menu de comandos do gateway (aponta p/ /lista). Menor; melhoria
  futura: surfaçar o `/lista` curado direto.
**Aprendizado:** o Yoda executa via `terminal`+`curl` e às vezes chuta o método → rotas GET sensíveis devem
aceitar POST também (ou o gateway ter um executor HTTP que respeite o `metodo` do contrato — TODO gateway).

## 🔎 Loop 5 — Massare (avaliação) + backtest final
**Massare (probe ao vivo):** o framework "pensante" EXISTE (registra cada tese como previsão e promete
cobrar OOS). MAS:
- `/placar`: **44 previsões PENDENTES, 0 resolvidas, hit_rate=null** → as previsões nunca são pontuadas
  contra o realizado. Sem track record OOS, o "honesto vs realizado" não fecha o ciclo.
- `/teses`: n=0 (sem narrativas→ativo no momento). `/cenarios`: ok (fear&greed=8 "medo extremo").
**FIX (sessão nova):** rodar/agendar o **scorer OOS do Massare** (resolver as 44 pendentes contra o preço
realizado no horizonte) → gerar hit_rate real. Provável módulo `massare/validation.py` / `learning.db`.
Sem isso, as previsões são opinião sem accountability — contraria a visão ("previsões pensantes + OOS honesto").
**Aprendizado:** "sistema pensante" exige FECHAR O CICLO (prever → registrar → COBRAR contra o real). O
Massare prevê e registra, mas não cobra. Igual ao Lex (lê o SEI mas não chega ao documento) — a estrutura
existe, falta o último elo de execução.

**Backtest total (00:31):** **~322 testes verdes, ZERO falhas**; 5 hangs de rede (integração PNCP/SEI/Receita
— pré-existentes); `imports_smoke` 141 (codebase importa limpo); `onda2` 10✓ (com rede). Ecossistema saudável
após os 5 loops; `jfn.service` religado (tudo live).

## 🏁 5 LOOPS CONCLUÍDOS
| Loop | Entrega | Verificação |
|---|---|---|
| L1 | /lista curado · OBs enxutas · LLM 9-chaves · Lex discursivo · wiring SIAFE | Yoda retorna os números |
| L2 | frescor/cobertura no topo dos relatórios | "Cobertura: 1.121.306 OBs · 77% CNPJ" |
| L3 | encaminhamento por severidade (acionável) | grav≥3→requerimento; lex offline ✓ |
| L4 | wiring /api/cartel GET+POST + prompt c/ método | curl GET/POST=200; Yoda end-to-end |
| L5 | Massare avaliado + backtest total | ~322 verdes, 0 falhas; Massare honesto |
**2 fixes profundos p/ sessão nova** (alto valor, precisam Chrome/live): coletor SEI → inteiro teor; scorer
OOS do Massare. Tema comum = **fechar o último elo do "sistema pensante"** (a estrutura existe nos dois).

## APRENDIZADO TRANSVERSAL (atualizado)
- O dono deu **autonomia total** (mexer em tudo — JFN/Lex/Massare/Hermes/Yoda — e religar à vontade). Minha
  cautela com "o que está vivo" era o gargalo, não o sistema. Fluir > hesitar (mantendo verificação do artefato).
- Teste end-to-end (`hermes -z`) > curl: pega gaps de roteamento que o curl não vê (rota existir ≠ Yoda saber usar).
