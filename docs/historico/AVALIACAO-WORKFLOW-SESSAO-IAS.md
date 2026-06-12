# Avaliação de Workflow para as IAs — sessão 2026-06-06/07 (erros e lições)

> Objetivo deste doc: que as próximas IAs (inclusive as mais simples) **não repitam os erros** desta sessão.
> Cada erro abaixo custou tempo/cota. A regra de ouro: **verificar empíricamente e buscar no repo ANTES de
> "resolver" do zero.** Complementa [[diretriz-workflows-para-ias]] e os docs SIAFE/SEI de evolução.

## 1. O que a sessão entregou (resumo)
- **Cruzamento** sócio × OB(SIAFE) × SEI × **endereço** + cidade-sede + **co-endereço** (red flag de fachada) +
  descoberta de **clusters de mesma sede** + 3 endpoints no barramento (`/api/cruzamento`, `/api/orgao/cidades`,
  `/api/coendereco/clusters`). Ver `docs/...` e `compliance_agent/cruzamento.py`.
- **SEI RESOLVIDO da VM**: login `itkava` via Chromium (WAF é fingerprint, não IP) + Pesquisa Avançada → extração
  da íntegra (`tools/sei_reader.py`, `cdp_*.json` que o Lex consome). Validado em processo real.
- **SIAFE mapeado**: VM acessa; teto de 1000; filtro ADF via `keyboard.type` (não `fill`); docs de evolução +DOM.
- **Lex enriquecido** (2 deep-research): doutrina, improbidade pós-14.230, **penal (CP/14.133)**, **controle RJ**;
  parecer com **análise de mérito** em prosa, **tabelas que cabem no PDF** e **fracionamento** no conceito do TCU.

## 2. ERROS COMETIDOS + LIÇÕES (o mais importante)
1. **SEI — premissa falsa "WAF bloqueia por IP".** Conclusão precoce (curl/Playwright caíam) mandou a equipe p/
   GitHub Actions e proxy residencial por dias. **Real:** o WAF bloqueia por **FINGERPRINT** — `curl` cai, mas
   **Chromium real passa** (intermitente). **Lição:** ao ver "bloqueio", testar com **navegador real + retry**
   antes de concluir "é IP"; distinguir fingerprint × IP × flap.
2. **SIAFE — reinventar o filtro que já existia.** Gastei uma sessão tentando `fill()`/`select_option`/
   `dispatchEvent` no campo de valor (não dispara o PPR do ADF). **A solução já estava no repo** há dias
   (`siafe_contratos.py`: `keyboard.type`+Enter, validado em 41 contratos). **Lição:** `git log`/`grep` no repo
   e nos docs ANTES de "resolver" um problema — provavelmente já foi resolvido.
3. **SIAFE — construir sobre mecanismo não verificado (`selUg`).** Implementei um sweep por `selUg` e rodei 205
   UGs antes de descobrir que `selUg` **não filtra** a grade. **Lição:** validar o mecanismo num teste mínimo
   (1-2 casos, conferindo o efeito real nos dados) ANTES de escalar.
4. **deep-research — retomar sem `args`.** `resumeFromRunId` sem repassar o `args` aborta em ~128ms e queima o
   lançamento. **Lição:** ao retomar, **sempre** repassar o `args` idêntico. Ver [[deep-research-relancar]].
5. **Lex — lógica de domínio por heurística frágil.** O R2 acusava "fracionamento" por nº de OBs/órgãos —
   **conceitualmente errado** (várias OBs = parcelas de 1 contrato; vários órgãos ≠ fracionamento). **Lição:**
   aterrar regra de domínio na **definição real** (TCU: múltiplas dispensas do mesmo objeto/UG/exercício sob o
   teto) — pesquisar a fonte, não chutar.
6. **`asyncio.run()` aninhado.** Chamar `inteligencia.gerar()` (que faz `asyncio.run`) de dentro de uma corrotina
   estoura "cannot be called from a running event loop". **Lição:** dentro de `async`, usar `await montar(...)`.
7. **Lex — render de PDF não testado visualmente.** Tabelas markdown saíam como texto cru (overflow/"fora da
   margem"). **Lição:** validar a SAÍDA real (PDF/Telegram), não só "rodou sem erro".

## 3. Padrões de workflow que FUNCIONARAM (manter)
- **Pesado em background** (`nohup`/`run_in_background`) + **watcher** (`until grep ... done`) p/ não gastar cota
  pollando — login SEI/SIAFE flaky, ingestões, VACUUM, deep-research.
- **Verificar antes de agir** (`ls`/`grep`/`curl`/teste mínimo) — pegou o briefing alucinado de outra IA
  ([[briefing-outra-ia-verificar]]) e o `selUg` que não filtra.
- **deep-research → sintetizar em doc citável → fundir no Lex** (com caveats; confirmar nº/data no texto oficial).
- **Memória entre runs** para travar aprendizados (SEI/SIAFE/fracionamento) e não repetir besteira.
- **Commits pequenos e descritivos** + handoff no topo + `.txt` de evolução enviados ao Mestre.

## 4. Recomendações para IAs mais simples (executar bem)
1. Leia primeiro: este doc, `MEMORY.md`, `docs/HANDOFF-*`, `docs/SIAFE-EVOLUCAO-TENTATIVAS.txt`,
   `docs/SEI-EVOLUCAO-TENTATIVAS.txt`. Não comece sem ler.
2. Antes de codar uma solução: `git log --all --grep=<tema>` e `grep -ri <tema>` — a solução pode já existir.
3. Teste o **efeito real** (dados/saída), não só "sem exceção". Para browser ADF/SEI: navegador real + retry,
   `keyboard.type` no filtro do SIAFE, mesma sessão no SEI.
4. Tarefa longa/flaky → **background + watcher**. Nunca pollar em loop no foreground.
5. Regra de domínio (jurídico/fiscal) → **fonte oficial** (TCU/CGU/lei), nunca heurística solta. Tudo é
   **indício**, jamais acusação.

## 5. Racionalização de storage (feito nesta sessão)
- `screenshots/` 32M → 20K (PNGs de debug do SIAFE, regeneráveis, limpos). `diagnostic_screenshots` idem.
- `reports/` podado p/ ~12 por formato (md/pdf/xlsx) — são regeneráveis sob demanda.
- `manutencao --tudo`: checkpoint do WAL + VACUUM da `compliance.db` + gzip dos CSV regeneráveis.
- **Sugestão de código** (futuro): gatilhar os screenshots do coletor SIAFE atrás de `JFN_DEBUG=1` p/ não
  acumular em produção (cada varredura gerava centenas de PNGs).
- Nada disso está no git (já ignorado) — o `.git` (120M) não incha por caches/relatórios.
