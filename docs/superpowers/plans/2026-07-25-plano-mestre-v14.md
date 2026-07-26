# Plano-mestre v14 — seis frentes

> **Para agentes:** este documento **não se executa**. Ele indexa seis planos independentes,
> fixa a ordem, as dependências e os critérios que valem para todos. Cada plano filho é que
> tem tarefas com checkbox e roda por `superpowers:subagent-driven-development`.

**Data:** 2026-07-25 · **Branch de origem:** `feat/painel-v8-melhorias` (último commit `8bf14c67`)
**Pedido do dono, na íntegra:** (1) visual muito mais ultratech na UI, templates, botões e em
todas as abas, com as referências já dadas; (2) painel mais vivo, animado, detalhado e desenhado
em tudo, usando o Adobe Express, com referências de Jarvis / Star Wars / holocrons / cyberpunk;
(3) avaliar, melhorar e analisar todos os processos, retestar cada linha de código, testar como
humano e criar novas funções no JFN, Lex, Hermes e Yoda; (4) criar novas funções no painel;
(5) separar direito Estado do RJ × Prefeitura do Rio × outros órgãos federais/municipais;
(6) melhorar MUITO cada uma das análises jurídicas. Reforço posterior: usar todas as skills boas
disponíveis, **ultratech / nebulosa / Jarvis / Star Wars / lightsaber, sem regredir**.

---

## 0 · Por que seis planos e não um

A skill `writing-plans` manda quebrar quando o pedido cobre subsistemas independentes. Estes
cobrem: uma folha de estilo, um conjunto de rotas novas, uma taxonomia de dados, um motor
jurídico, uma fila de 18.843 processos e uma suíte de testes com quatro produtos. Cada um
produz software funcionando e testável sozinho; misturá-los num plano só produziria um
documento que ninguém consegue revisar nem executar por partes.

| # | Plano | Arquivo | Depende de | Estado |
|---|---|---|---|---|
| **P1** | **Painel v14 "HOLOCRON"** — UI, templates, botões, 45 abas, vida, Express | `2026-07-25-painel-v14-holocron.md` | — | **escrito, pronto para executar** |
| **P2** | Esferas estanques — Estado × Prefeitura × outros entes | `2026-07-26-esferas-estanques.md` | — | a escrever (precisa de leitura de código) |
| **P3** | Qualidade jurídica — vícios, flags, escalada, Lex | `2026-07-26-qualidade-juridica.md` | P2 (recorte por ente muda o parecer) | a escrever (precisa de brainstorming) |
| **P4** | Fila SEI — avaliar e analisar os processos | `2026-07-27-fila-sei.md` | P3 (o parecer é o produto) | a escrever (precisa de brainstorming) |
| **P5** | Funções novas no painel | `2026-07-27-funcoes-novas-painel.md` | P1 (chrome), P2 (recorte) | a escrever (precisa de brainstorming) |
| **P6** | Reteste linha a linha + funções novas em JFN/Lex/Hermes/Yoda | `2026-07-28-reteste-e-ecossistema.md` | P1–P5 | a escrever |

**Ordem recomendada:** P1 → P2 → P3 → P4 → P5 → P6.
P1 primeiro porque é o único que já tem decisão do dono fechada e não bloqueia ninguém.
P2 antes de P3/P4/P5 porque **o recorte por ente muda o que cada aba mostra e o que cada
parecer afirma** — construir 45 assinaturas de aba e depois descobrir que a aba não existe
naquela esfera é retrabalho garantido.

---

## 1 · Constraints globais (valem para os seis planos)

Copiadas literalmente das leis já escritas da casa. Todo plano filho herda esta seção.

### 1.1 Honestidade (não negociável)
- **OB (Ordem Bancária) = pagamento.** Empenho ≠ liquidação ≠ OB. Nunca apresentar empenho
  como "total pago".
- **INDISPONÍVEL ≠ 0.** Silêncio ≠ INDISPONÍVEL. Zero grave **não** é alarme.
- **Indício ≠ acusação.** Presunção de regularidade. Score é indício interno.
- **Nunca inventar número.** Dado sintético é proibido no painel (o gerador `Math.random` foi
  removido no v10 e não volta). Vida visual só com dado ou evento real.
- CPF de sócio mascarado (LGPD).
- Fonte de OB: **sempre SIAFE**, nunca o espelho TFE.

### 1.2 Não regredir (o pedido explícito do dono)
- Camadas de CSS são **aditivas**: v7 → v8 → v9 → v10 → v11 → v12 → v13 → **v14**. A cascata
  vence. **Nunca reescrever bloco antigo.** Bloco novo vai ao FIM do `<style>`.
- **Nunca dessaturar o que já brilha** (o v6 foi regressão declarada).
- Comparar suíte por **nome**, não por contagem: `comm -13 tests/BASE-FALHAS-VM2.txt /tmp/agora.txt`
  vazio = sem regressão. Base atual: 2.524 passando · 50 falhas de ambiente da VM-2 · 6 puladas.
- Gate `compliance_agent/reporting/neutralidade.garantir_neutro` em todo entregável.

### 1.3 Armadilhas de CSS já pagas (repetir custa rodadas)
- **Nunca escrever os dois caracteres de fecha-comentário dentro de um comentário CSS.** Escreva
  "fecha-comentario" por extenso. Um órfão engole o `@media` inteiro abaixo, sem erro no console.
  `tests/test_painel_css_integro.py` trava isso em 0,1 s.
- **Regra em lote nunca impõe `position` a quem já é posicionado.** Já mordeu duas vezes
  (`.nu-chip`, `.search .az`). Ao criar regra em lote, **liste quem NÃO pode receber `position`**.
- **Nunca decorar o `background` de quem carrega TEXTO.** O scan no `thead tr` fez o auditor ler
  "Fornecedor" a 1,02:1.
- **`flex:1;min-width:0` em strip horizontal = sobreposição no celular.** Use `flex:0 0 auto`.
- **`background-clip:padding-box,border-box` exige DUAS camadas de `background-image`.** Com uma
  só, o gradiente inunda o elemento.
- Uma regra com `animation:` **sobrescreve em silêncio** a animação de regra menos específica.
  Ao adicionar animação a quem já tem, componha as duas na mesma declaração.
- Margem **não** se aplica a `display:table-cell`.

### 1.4 Medição (transformar "está bonito" em critério verificável)
- **FPS nesta VM não mede nada** (≈4 fps com todos os canvas parados: SwiftShader, 2 vCPU). O
  instrumento válido é **A/B na mesma aba**, alternando ida e volta, com `<style disabled>`
  desligando só o que acabou de entrar. Medir **ms/quadro**, orçamento 16,6 ms.
- **Auditoria por CDP sem desligar o cache não vale nada.** Sempre:
  `cmd("Network.enable"); cmd("Network.setCacheDisabled",{"cacheDisabled":True})` antes do
  `Page.navigate`. Conexão com `websocket.create_connection(..., suppress_origin=True)`, porta 9222.
- **As variantes é que revelam o defeito:** `Emulation.setEmulatedMedia` com
  `prefers-reduced-motion:reduce` e `setDeviceMetricsOverride` a 390px.
- **CSS que "não pegou": pergunte ao elemento.** `getComputedStyle` no DOM vivo antes de levantar
  qualquer hipótese. Propriedade no valor inicial com a media query casando = problema de PARSE.
- Contraste ≥ 4.5:1 — `tools/auditar_contraste.py` com **0 violações e 0 não medidos**.
- Geometria — `tools/auditar_layout.py` com 0 violações de norma (WCAG 2.5.8, alvo ≥24px).

### 1.5 Máquina e custo
- VM `jfn-core`: **2 vCPU**, 11,6 GB, 4 GB swap. **Um pesado por vez.** Checar `load`/`free`
  antes de qualquer sweep ou DuckDB.
- Enxame (`editais_direcionamento --so-rj`) **só off-hours** — escrever no `compliance.db` trava
  as rotas de leitura do painel.
- **Nunca assumir free tier.** Qualquer API paga cobra até prova documentada do contrário.
  OpenRouter só `:free`. Jina só com permissão explícita.
- Zero CDN: toda lib self-hosted em `static/assets/`.

### 1.6 Git
- Mensagem semântica (`feat:`, `fix:`, `data:`, `docs:`, `ci:`), commit por unidade.
- Sem force-push sem confirmação.
- Trailer `Co-Authored-By:` conforme `CLAUDE.md` §4, com o modelo da sessão que executar.
- `gitnexus_detect_changes()` antes de commitar mudança em Python.

### 1.7 Estética (regra absoluta do dono)
Padrão Kroll/Deloitte em todo entregável: capa, seções numeradas, tabelas alinhadas,
rating 🔴🟡🟢 + score, R$ com separador de milhar e duas casas, fontes citadas. Nada feio.
Relatório é **produto da casa** (`render_html`/`html_to_pdf`), nunca `.txt` à mão.

---

## 2 · O que cada plano ainda pendente precisa antes de ser escrito

Declarado para que ninguém escreva plano no escuro — a lei da casa é ler código e dado real
antes de doc e handoff.

### P2 · Esferas estanques
**Precisa ler:** `compliance_agent/sancao_abrangencia.py`, `compliance_agent/lex_orgao.py`,
`compliance_agent/cruzamentos_intel.py`, `compliance_agent/comparador_precos.py`, e como
`ug_index` separa as UGs (memória: Soberano 226300 ≠ Previdência 123400 ≠ Fundo Saúde 294200).
**Pergunta em aberto:** hoje "esfera" é filtro de UI ou invariante de dado? Se for só UI, o
plano tem que criar a coluna/derivação de ente e migrar, não pintar botão.
**Critério de aceite candidato:** nenhum registro de Prefeitura aparece em rota de Estado e
vice-versa, provado por teste que conta o cruzamento contra o acervo real; entes federais
ganham rótulo próprio em vez de caírem em "Estado" por omissão.

### P3 · Qualidade jurídica
**Precisa ler:** `compliance_agent/knowledge/catalogo_vicios.py` (40 vícios, `lacunas()`),
`compliance_agent/editais/flags.py` (`grau_flag`), `compliance_agent/editais/escalada.py`,
e os dez módulos `compliance_agent/lex_*.py`.
**Skill obrigatória:** `analise-clausulas-br` (classificação por desvio, redline com
redação-conforme, matriz Severidade × Verossimilhança, gatilhos de escalada).
**Fatos que o plano tem que respeitar:** 59% das red flags eram queixa de **captura**, não vício;
LLM nunca produz flag CERTO; o motor E7 está validado com 0 falso positivo — não mexer nele sem
medir contra o acervo.

### P4 · Fila SEI
**Precisa ler:** `tools/sei_fila_por_dinheiro.py` (18.843 processos nunca tocados, R$ 2,11 bi),
`tools/sei_ficha.py`, `tools/sei_triagem_flags`, `docs/PLAYBOOK-SEI.md`.
**Fatos que o plano tem que respeitar:** arquivo compacto primeiro (`tools/sei_consultar.py`),
browser/IA só depois; `insert_textbox` calado já produziu 11.901 documentos em branco — o SEI
tinha servido; 20% do arquivo sem texto é, na maioria, vazio de verdade.

### P5 · Funções novas no painel
**Precisa de brainstorming com o dono** — "novas funções" sem lista é o único item do pedido
sem conteúdo verificável. Candidatas que o repositório já sustenta, para servir de pauta:
fila SEI por dinheiro na UI · linha do tempo INAPTA × vigência × OB · comparador entre esferas ·
painel de escalada ao TCE · árvore SEI navegável · export do dossiê completo por CNPJ.

### P6 · Reteste e ecossistema
**Precisa de:** base nome a nome já gravada (`tests/BASE-FALHAS-VM2.txt`, existe), e decisão
sobre o que "retestar cada linha" significa em critério — cobertura medida, mutação, ou revisão
dirigida pelos módulos que mais mudaram. Sem esse critério o plano não fecha.

---

## 3 · Skills que os planos filhos devem usar

| Skill | Onde |
|---|---|
| `site-3d-premium` | P1 — pipeline de 8 papéis; para elevar existente começa pelo papel 8 (Auditor) |
| `frontend-design` | P1 — rigor de execução visual |
| `ui-ux-pro-max` | P1, P5 — estilos, paletas, pares tipográficos, presets de motion |
| `dataviz` | P1, P5 — todo gráfico, medidor, KPI e dashboard |
| `analise-clausulas-br` | P3 — método cláusula a cláusula, Lei 14.133/2021 |
| `superpowers:test-driven-development` | P2–P6 |
| `superpowers:systematic-debugging` | qualquer bug encontrado no caminho |
| `superpowers:verification-before-completion` | todos, antes de dizer "pronto" |
| `python-testing`, `python-patterns` | P2–P6 |

---

## 4 · Critério de "acabou" do conjunto

O plano-mestre fecha quando, simultaneamente:

1. Os seis planos filhos estão executados e cada um passou no próprio critério.
2. `comm -13 tests/BASE-FALHAS-VM2.txt /tmp/agora.txt` sai **vazio**.
3. `tools/auditar_contraste.py` e `tools/auditar_layout.py` saem limpos nas **45 abas** a 1440 e 390.
4. O A/B de ms/quadro mostra o painel dentro do orçamento de 16,6 ms.
5. `DESIGN.md` e um handoff novo em `docs/superpowers/specs/` descrevem o estado real — não o
   pretendido.
