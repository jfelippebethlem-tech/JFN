# BENCHMARKS EXTERNOS — Referências de Elite para o JFN

> Consolidado da pesquisa de 2026-07-19 (3 varreduras profundas: detecção de fantasma/fachada · design de painel · risk-scoring de licitações). Cada item traz **o que extrair** e **como aplica ao JFN**. Documento vivo — atualizar quando um benchmark for incorporado ou superado. (Avaliações internas de IA: ver `BENCHMARKS.md`.)

---

## 1. DETECÇÃO DE EMPRESA FANTASMA / FACHADA — R$ 0 sustentável, sem Google Maps

### 1.1 Taxonomia oficial (o que os órgãos de controle usam)

| Fonte | Sinais objetivos | Aplicação JFN |
|---|---|---|
| **ALICE** (TCU/CGU) | ~40 tipologias regex+NLP sobre editais/atas; 3 classes: proibição de contratar, **empresas fantasmas**, baixa competitividade; filtro de materialidade | Motor E7 já espelha; CGU oferece **adesão estadual desde 2024** — pedir via gabinete |
| **ADELE** (TCU) | Dinâmica de lances + **mesmo IP entre licitantes** | Proxy público: metadados de PDF das propostas (`forense/pdf_metadados.py`) |
| **SOFIA / MONICA / ÁGATA / CARINA** | CNPJ→sanções/histórico; concentração UASG×fornecedor; ML refinando alertas (corta FP); crawler DOU | Radar/Lex já cobrem; ÁGATA inspira o retro/lift |
| **Receita "noteira"** | Faturamento alto × estrutura zero (sem funcionários, sem sede, capital irrisório) | Assinatura = OB SIAFE alta + CRF/FGTS ausente + capital ínfimo |
| **COAF (Casos e Casos, 87 tipologias)** | **Fachada** = operante, mescla ilícito (incompatibilidade de volume) ≠ **fantasma** = só papel (endereço inexistente/residencial) | Usar a distinção nos relatórios (rigor conceitual) |
| **TCU Ac. 725/2026 + Referencial 2ª ed.** | **Atestado emitido por empresa do mesmo grupo**; sucessão de sancionada (mesmos sócios, empresa nova) | `detectores/j_atestado_cruzado.py`; sinal "sucessão" no grafo QSA |

### 1.2 Matriz de 12 sinais (impacto × facilidade, todos R$ 0)

1. **Hub endereço/telefone/e-mail** — dump Estabelecimentos (tel1/2 + email por CNPJ); ferramenta-referência: [rede-cnpj (rictom)](https://github.com/rictom/rede-cnpj). → `estabelecimentos` + detector `hub_compartilhado`.
2. **Grafo sócio-laranja / sucessão de sancionada** — arquivo Sócios (data_entrada!); QSA de nova ⊇ QSA de sancionada; sócio entra dias antes da licitação.
3. **Sem funcionários** — CRF/FGTS Caixa por CNPJ (sem cadastro ≈ sem folha); RAIS por CNPJ só até ~2021.
4. **Âncora setorial** — objeto de saúde e CNPJ ∉ [CNES](https://cnes.datasus.gov.br/) (dump aberto com endereço+equipe) = alerta grave; transporte→RNTRC/ANTT; farma→ANVISA AFE.
5. **Alvará PCRJ** — [pesquisa de alvará por CNPJ](https://carioca.rio/servicos/pesquisa-de-existencia-de-alvara-para-um-local/); sem alvará ou endereço ≠ Receita.
6. **Físico sem Google** — Nominatim **self-hosted** (Docker + .pbf RJ Geofabrik, ilimitado) → Overpass (`building/shop/office` raio 50 m) → fila humana com Street View **Embed** (permitido) + [ESRI Wayback](https://livingatlas.arcgis.com/) (satélite histórico: lote vazio na data do contrato).
7. **Pegada digital** — [RDAP registro.br](https://registro.br/rdap/): **busca reversa de domínios .br por CNPJ** (5 req/min, cache); e-mail gratuito vs domínio próprio; idade do domínio vs data do contrato.
8. **Querido Diário** — [API aberta](https://docs.queridodiario.ok.org.br/) (350+ municípios): rastro histórico da razão social; zero menção = sinal.
9. **QSA × TSE** — [dados abertos TSE](https://dadosabertos.tse.jus.br/): candidatos (CPF completo), bens, doadores E fornecedores de campanha → ciclo contrato→empresa→campanha.
10. **Metadados de PDF** (proxy do IP da ADELE) — mesmo Author/Producer/minuto entre "concorrentes" = indício aceito pelo TCU.
11. **Atestado cruzado intra-grupo** — CNPJ emissor do atestado × QSA/endereço/telefone do licitante.
12. **Footprint digital vazio** — SpiderFoot (instalado na VM) sobre domínio/e-mail do sinal 7; footprint vazio é computável como score.

**VETADOS por billing latente:** Mapbox (cartão obrigatório, overage automático — padrão Gemini). Nominatim público para bulk (política 1 req/s) — self-host.

### 1.3 Academia
- [EPJ Data Science 2025 — systematic mapping](https://link.springer.com/article/10.1140/epjds/s13688-025-00569-3) (features: concentração de vitórias, idade da empresa, distância sede↔órgão, redes de co-participação) · [Bots against corruption 2023](https://link.springer.com/article/10.1007/s10611-023-10091-0) (ALICE por dentro) · dataset [hackfestcc](https://github.com/hackfestcc/dados-hackfestcc) (MPPB+CGU). Não há benchmark rotulado padrão — o gabarito determinístico (8 sinais) segue estado da prática.

---

## 2. DESIGN DE PAINEL — "instrumento de precisão noturno"

### 2.1 Referências ranqueadas

| # | Referência | O que extrair |
|---|---|---|
| 1 | **Blueprint (Palantir)** — [blueprintjs.com](https://blueprintjs.com) | Dark #111418–#404854 (nunca preto puro), 1 azul de ação, elevação por luminosidade, linhas de tabela 24-30 px. High-tech = densidade organizada, ZERO decoração |
| 2 | **Territory Studio (BR2049)** — [territorystudio.com](https://territorystudio.com/project/blade-runner-2049/) | Poder comunicado por RESTRIÇÃO; quanto mais crítico o dado, mais limpo o tratamento; geometria fina 1 px, nunca scanline/glitch |
| 3 | **Linear** | Inter/features `cv01 ss03 zero`, hairlines no lugar de sombra, 1 acento saturado em sistema dessaturado, microtransições 100-150 ms |
| 4 | **Vercel/Geist** — [vercel.com/design.md](https://vercel.com/design.md) | Escala de cinza com degrau POR FUNÇÃO; sombras multicamada (borda+ambiente+profundidade+inner highlight) |
| 5 | **Raycast** | Canvas #07080a azulado frio; vermelho de assinatura raríssimo |
| 6 | **Bloomberg/"Fortress"** | `tabular-nums` à direita, âmbar=atenção, 3 densidades selecionáveis |
| 7 | **Chainalysis/Linkurious** | Grafo com setas de FLUXO DE VALOR (empenho→OB→favorecido), expansão progressiva, painel lateral sincronizado |
| 8 | **Maltego** | "Transforms": cada cruzamento é um verbo aplicável à entidade selecionada |
| 9 | **Recorded Future** | Score 0-99 SEMPRE com regras de evidência explícitas ("3 de 51 regras: X, Y, Z") |
| 10 | **Pencil&Paper (enterprise tables)** — [guia](https://www.pencilandpaper.io/articles/ux-pattern-analysis-enterprise-data-tables) | Densidade 3 níveis persistida; ações nunca só-hover; célula = valor+Δ% |
| 11 | **Godly/Awwwards dark** | Base #0E–#1A (halation em #000); UM momento de brilho por tela |
| 12 | **Domo UX (functional futuristic)** — [ensaio](https://medium.com/domo-ux/designing-a-functional-futuristic-user-interface-c27d617ce8cc) | Todo elemento animado/luminoso DEVE codificar estado real |

### 2.2 Decisões incorporadas no v6 "Lâmina" (2026-07-19)
- IBM Plex Sans + IBM Plex Mono self-hosted (exatidão forense, 1/l/0/O diferenciados); `tabular-nums` em todo valor.
- Paleta OKLCH hue 250; elevação por luminosidade + hairline; orçamento de cor: 1 acento (cian-aço), ouro=R$, âmbar=atenção, rosa=crítico.
- Assinatura única: **Conduíte** (lâmina SSE 1 px; pulso = evento real). Removidos: starfield, auras, malha, lightsaber, brackets, emoji-ícone, hero com glow, sparkline sintética.
- Stack self-hosted em `static/assets/`: uPlot 1.6.31, sigma.js 2.4 + graphology 0.25 (zero chamada externa).

---

## 3. RISK-SCORING HEURÍSTICO DE LICITAÇÕES

### 3.1 Frameworks e a lição central
- **ARACHNE+ (CE)**: 78 indicadores (reduzidos de 107 para cortar falso positivo) agregados por projeto/contrato/contratado; enriquece com Orbis+World Compliance (≡ nosso QSA+CEIS/CNEP). Lição de fracasso documentada: **score sem calibração local vira ruído** (percepção de eficácia 5,4/10 vs 9,0 da inspeção in loco).
- **OCP Red Flags 2024 (73 indicadores)** + **Cardinal** ([docs](https://cardinal.readthedocs.io/)): 6 famílias por fase; **outlier LOCAL (fences IQR) em vez de threshold universal**; triangular ≥2 flags do mesmo risco; ação de workflow por flag.
- **CRI (Fazekas/GTI)** + [IMF WP 2022/094](https://www.elibrary.imf.org/downloadpdf/view/journals/001/2022/094/article-A001-en.pdf): média de flags 0-1 no nível do contrato; componente só entra se **prediz single bidding e correlaciona com sobrepreço**.
- **Banca d'Italia (Decarolis-Giorgiantonio, [EPJ 2022](https://link.springer.com/article/10.1140/epjds/s13688-022-00325-x))** — a anti-intuição que obriga validação: flags "óbvios" (urgência, baixa publicidade) foram **não/negativamente correlacionados** com corrupção; os preditivos são de **discricionariedade** (critério multiparamétrico, procedimento negociado, desqualificações).
- **OCDE 2025 Bid-Rigging Detection List** + CADE (screens do Projeto Cérebro): indício ≠ prova (§3.6).

### 3.2 Agregação adotada (Índice de Direcionamento de Certame)
1. Flags agrupados em **famílias** (transparência, competição, conluio, fraude cadastral, preço, execução); **máximo por família** antes de ponderar (evita dupla contagem de correlacionados).
2. **Outlier local** (p10/p90 da categoria naquele ente), não threshold fixo.
3. **Materialidade = multiplicador de prioridade**, nunca componente do risco: `prioridade = score × log(valor OB)`.
4. Pesos **calibrados** contra desfechos verificáveis (vencedor depois sancionado; sobrepreço vs mediana; casos confirmados).

### 3.3 Screens de conluio (com preços unitários + concorrentes)
- **Intra-certame**: CV = σ/μ dos lances (baixo = coordenação) · **RD** = (b₂−b₁)/média(diferenças entre perdedores) (RD≫1 = cobertura) — os 2 preditores dominantes (>80% acerto, [Huber & Imhof](https://www.sciencedirect.com/science/article/abs/pii/S0167718719300219)); skewness negativa; lances idênticos/razões fixas; **vetores de preços unitários iguais ±k% = quase-prova de planilha compartilhada**; cartel incompleto = screens em subconjuntos de 3-4 lances ([Wallimann 2022](https://link.springer.com/article/10.1007/s10614-022-10315-w)).
- **Inter-certames**: rotação de vencedores (entropia), perdedor contumaz, licitante que some, divisão geográfica, teste do entrante (preço cai quando estreante vence), interdependência de pares.
- **Regra de decisão**: nunca 1 screen só — exigir **≥2 concordantes**.

### 3.4 Rubrica LLM-judge (6 dimensões, 0-4)
Regra responde "violou?"; LLM responde "**quão anômalo no contexto?**". Norma no prompt (Lei 14.133 + súmulas) pedindo DESVIOS; **citação verbatim obrigatória** (sem trecho → "não avaliável", nunca nota); JSON estrito; calibrar com 30-60 docs-ouro; tier por tarefa (triagem Groq/Gemini, adjudicação Claude, dupla-juiz pré-representação).
Dimensões: D1 restritividade contextual · D2 qualidade da motivação · D3 coerência objeto-quantidade-preço · D4 narrativa da disputa · D5 relação comprador-fornecedor · D6 integridade documental.
Integração: `score_final = score_det + α×(média_rubrica/4)`, **α ≤ 0,3, teto 1,0** — o LLM realça, nunca sozinho eleva caso limpo a crítico (auditabilidade perante o TC). Registrar flags, notas, citações e versão do prompt.

---

*Fontes completas com URLs: relatórios de pesquisa de 2026-07-19 (agentes de pesquisa web; principais links inline acima).*
