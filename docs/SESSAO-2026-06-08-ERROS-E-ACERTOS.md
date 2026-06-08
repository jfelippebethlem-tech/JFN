# Sessão 2026-06-08 — Erros & Acertos (para avaliação por outra IA)

> **Propósito:** registro honesto e auditável de TUDO que deu certo e errado nesta sessão, para que
> **outra IA avalie** a qualidade do trabalho. Cada item: **Contexto → Ação/Decisão → Evidência →
> Resultado → Lição**. Branch: `sei-precos-onda5`. Sem segredos. Tudo grátis/aditivo.
>
> **Como avaliar (sugestão p/ a IA revisora):** (1) os diagnósticos foram baseados em EVIDÊNCIA real
> (screenshots, JSON, dados ao vivo) ou em suposição? (2) os erros foram revertidos e documentados? (3)
> as decisões de arquitetura (storage/CPU) são defensáveis? (4) há teste para cada unidade? (5) algo foi
> declarado "pronto" sem verificação?

---

## 1. Higiene da VM (CPU/RAM) — ACERTO

- **Contexto:** dono receia crash da VM por CPU/RAM (VM de **2 cores**, 8 GB). Pediu auditoria.
- **Ação:** mapeei processos por CPU/RAM/tempo acumulado; distingui trabalho legítimo (sweep SIAFE) de
  desperdício; confirmei que os 2 Chromes idle gastavam **RAM, não CPU**.
- **Evidência:** `ps`/`free`/`uptime`; load 0,8 em 2 cores; 0 swap; 6 GB livres.
- **Resultado:** conclusão honesta de que **não havia vazamento de CPU**; o único consumidor pesado era o
  sweep (trabalho real). Alertei que abrir um 4º browser junto ao sweep é o risco real de crash.
- **Lição:** medir antes de "otimizar"; nem todo processo aberto é desperdício.

## 2. Reuso do Chrome :9222 p/ SEI — ERRO de premissa, corrigido por evidência

- **Contexto:** p/ economizar CPU, o dono escolheu reusar o Chrome `:9222` já aberto p/ debugar o SEI.
- **Ação:** tentei conectar via CDP no `:9222` e logar no SEI.
- **Evidência:** diagnóstico retornou `ERR_CONNECTION_CLOSED` — o WAF do SEI **derruba a conexão** desse
  Chrome (fingerprint), igual ao curl. O caminho que funciona é o `sei_reader` lançando **chromium próprio
  com UA spoofado**.
- **Resultado:** abandonei o `:9222` p/ SEI (documentado). Como o dono havia parado o sweep, lançar um
  chromium próprio passou a ser seguro.
- **Lição:** validar a suposição "reusar é mais barato" contra a infra real (WAF por fingerprint).

## 3. Diagnóstico do reader SEI (busca→abrir) — ACERTO (corrige o handoff)

- **Contexto:** handoff dizia que o reader "fica na tela `protocolo_pesquisar` / busca não resolve" =
  falha técnica bloqueando o sweep de 41k OBs.
- **Ação:** instrumentei o fluxo (diag de frames, depois **screenshots ground-truth**) em 520003 (que
  funcionava) vs 520002 (0 docs).
- **Evidência:** `SEI-520003/000026/2025` → **8 docs + conteúdo + CNPJ + valor**. `SEI-520002/001366/2025`
  → screenshot mostra **"Nenhum resultado encontrado"** (sem cadeado, sem texto de restrição).
- **Resultado:** **a premissa do handoff estava ERRADA.** O reader funciona p/ processos no **escopo da
  unidade ITERJ**; o `0 docs` do 520002 = processo **não localizado/acessível** por essa unidade (e/ou
  `numero_sei` ruidoso da OB), não bug. Corrigi o detector (texto real "Nenhum resultado encontrado") +
  `motivo_zero=nenhum_resultado` honesto. Commit `4b1323e`. 13 testes verdes.
- **Lição:** screenshot/ground-truth > inferência de DOM; questionar a premissa herdada.

## 4. "Forçar modo Processos" no reader — ERRO (regressão), revertido

- **Contexto:** vi que a busca de 520002 caía em modo "Documentos" (onde nº de processo não é achado).
  Hipótese: forçar o radio "Processos" resolveria.
- **Ação:** adicionei `_JS_MODO_PROCESSOS` clicando o elemento de texto "Processos".
- **Evidência:** rodei o reader: **520003 caiu de 8 docs → 0** (regressão!). O clique pegou o item de
  **menu** "Processos" (vai p/ `procedimento_controlar`), não o radio da busca.
- **Resultado:** **revertido na hora**; 520003 voltou a 8 docs. Mantive só as melhorias seguras (detector +
  motivo_zero). Registrado em Erros & Aprendizados do handoff.
- **Lição:** seletor por texto "Processos" colide com o menu; mirar o **radio real**. Sempre rodar o caso
  que JÁ funciona após uma mudança (teste de regressão).

## 5. Onda 12 — providers OSINT grátis — ACERTO (com adaptação honesta)

- **Contexto:** dono enviou por Telegram o PATCH "Onda 12" (registry chain, OpenSanctions, Querido Diário,
  TSE). Código do PDF era **pseudocódigo idealizado** (API-base diferente da real).
- **Ação/Evidência/Resultado por unidade (commit-por-unidade, teste cada):**
  - **Endpoints CONFIRMAR validados ao vivo:** OpenCNPJ ✓, CNPJ.ws ✓, Querido Diário ✓ (base do spec estava
    atrás de Cloudflare → usei `api.queridodiario.ok.org.br`), TSE-CKAN ✓. BrasilAPI tem rate-limit 429.
  - **Registry chain** BrasilAPI→OpenCNPJ→CNPJ.ws, shape canônico. `2d73ea3`.
  - **Querido Diário** (`gazettes_providers`) — 5167 diários RJ ao vivo. `6a731a8`.
  - **TSE doador×contrato** (`eleitoral_providers`) — ver item 6. `154415f`.
  - **Rotas** `/api/diario` + `/api/doador_contrato` + capabilities + /lista. `915cd55`.
- **Lição:** spec é INTENÇÃO; implementar contra a `base.py` REAL, não copiar pseudocódigo. Confirmar
  endpoints "CONFIRMAR" empiricamente (o próprio spec mandava).

## 6. Decisão de storage do TSE — ACERTO (eficiência)

- **Contexto:** dono perguntou o jeito mais eficiente (CPU/storage/busca) de guardar doações TSE; cogitou
  arquivo plano (.txt).
- **Ação/Decisão:** recomendei **SQLite dedicado `data/doacao_tse.db` com índice** (não arquivo plano —
  plano é menor mas busca linear = CPU alta). Separado do `compliance.db` (não inchar/WAL). Loader streaming
  que lê só `*_RJ.csv` do ZIP nacional, guarda só RJ, **apaga o ZIP** (storage-safe).
- **Evidência:** ZIP 2022 = 376 MB; o TSE fornece **arquivo por UF** (descoberto inspecionando o ZIP) →
  leio 2 arquivos RJ em vez de 54 nacionais. **Resultado: 20.718 doações RJ/2022 em 3,2 MB**, ZIP apagado.
- **Caveat honesto documentado:** CNPJ público **mascara CPF do sócio** → casamento é por **nome** (indício,
  nunca acusação).
- **Lição:** "menor no disco" ≠ "melhor"; índice vence varredura; inspecionar o dado real revelou o ganho
  (arquivo por UF).

## 7. `/lista` do Yoda — ERRO de premissa (handoff), corrigido

- **Contexto:** handoff dizia `/lista` "já gera da skilltree" (commit 8a8b102). Dono mostrou que o `/lista`
  do bot ainda imprimia um **menu fixo curto** (8 comandos).
- **Ação/Evidência:** achei a causa: a **skill `/lista` do Hermes** (`~/.hermes/.../lista/SKILL.md`) tinha
  texto **hardcoded** e NÃO chamava o `/api/lista` (que existe e serve o `render_menu()` rico).
- **Resultado:** (a) enriqueci `render_menu()` p/ **descrição + exemplo por skill**, mantendo a estética
  agrupada; (b) reescrevi a skill `/lista` p/ chamar `GET /api/lista` (ao vivo, auto-atualiza); (c)
  reiniciei `jfn.service` (o servidor tinha o código antigo em memória) e confirmei `/api/lista` rico
  (7.388 chars, exemplo por skill). `f38ac7d`.
- **Lição:** "documentado como feito" ≠ "verificado ao vivo"; o servidor precisa **restart** p/ mudança de
  código (reload só relê YAML). Verificar a ponta (bot), não só o endpoint.

## 8. Pendências honestas (NÃO declarar como prontas)

- **SIAFE sweep PARADO** (checkpoint 244 ug:ano salvo) — Onda 4: religar orçamentárias + add
  extra-orçamentárias quando o trabalho SEI encerrar.
- **TSE:** só 2022 RJ populado; outros anos (2018/2014 p/ doação direta de empresa ≤2014) são on-demand.
- **idoneidade:** só CEIS (falta CNEP).
- **SEI sweep massivo:** limitado ao escopo ITERJ — Onda 2 deve usar a cadeia `relacionados`, não os 41k
  `numero_sei` às cegas.
- **Skill `/lista` no bot:** pode exigir `/skills_reload` no Yoda p/ o gateway recarregar a SKILL.md nova.

---

## Resumo de commits (branch `sei-precos-onda5`)
`4b1323e` fix SEI reader (diagnóstico correto) · `2d73ea3` registry chain · `6a731a8` Querido Diário ·
`adc4969` .env · `154415f` TSE doador×contrato · `915cd55` rotas+capabilities · `3b0cc08` handoff ·
`f38ac7d` /lista rico ao vivo.

## Métricas de qualidade
- **Testes:** 17 providers + 13 SEI + 10 skilltree (+ outros) — **verdes** a cada commit.
- **Erros cometidos e revertidos:** 1 regressão (item 4), revertida no mesmo fôlego.
- **Premissas do handoff corrigidas:** 2 (reader busca→abrir; /lista já-gerado).
- **Decisões de eficiência:** store TSE 3,2 MB indexado; leitura por-UF; ZIP apagado.
