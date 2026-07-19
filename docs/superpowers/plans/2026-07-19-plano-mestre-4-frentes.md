# Plano-Mestre — 4 Frentes (fantasma sem Google · benchmarks · painel novo · camada heurística de contratos)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) ou superpowers:executing-plans para implementar tarefa-a-tarefa. Steps usam checkbox (`- [ ]`).

**Goal:** Elevar o JFN em quatro eixos — detecção de empresa fantasma/fachada a custo R$0 sustentável (sem Google Maps API), redesign total do painel para nível Palantir/Linear, uma camada de análise heurística/contextual de certames além do determinístico, tudo ancorado em benchmarks pesquisados.

**Architecture:** Reusar o que já existe (97 tabelas em `compliance.db`, motor E7/enxame de 5 lentes, cruzamentos_intel, comparador_precos, conluio_propostas, Hermes 19-elos, hermes_rag Cohere) e preencher os gaps com: (F1) novos detectores SQL + camada física OSM self-hosted + enriquecimento setorial; (F3) reescrita do `static/jfn-painel.html` com design system disciplinado + libs leves self-hosted (uPlot, sigma.js); (F4) um `Índice de Direcionamento de Certame` (score contextual agregado) + lente LLM de síntese, persistido em `caso`/`contrato_dossie`. Todo contrato JSON das ~130 rotas é preservado.

**Tech Stack:** Python 3.12, FastAPI, SQLite (`sqlite3` via `python3` — CLI ausente, usar `.venv/bin/python`), Playwright (CDP 9222), HTML/CSS/JS vanilla, OKLCH, uPlot + sigma.js self-hosted, Docker (Nominatim), Overpass, RDAP, Querido Diário API, SpiderFoot, LLMs grátis (Groq/Gemini/Cohere).

## Global Constraints

- **Nunca sair do Fable 5.** Se cair no Opus, avisar e voltar (memória `fable5-modelo-obrigatorio`).
- **R$ 0,00 sustentável.** Nenhuma API paga ou com billing latente. Mapbox VETADO (cobra no cartão). Google Maps API só o embed iframe grátis (`output=svembed`). Gemini free-tier religado — monitorar. (§4.1 CLAUDE.md, `nunca-assumir-free-tier`).
- **VM 2 vCPU:** um pesado por vez; checar `uptime`/`free` antes de sweep; browser/OCR sempre via `tools/vm_guard.py`, serial, foreground. Nunca crashar.
- **Honestidade forense:** indício ≠ acusação; INDISPONÍVEL ≠ 0; CPF mascarado; nunca inventar número. Reconstruir CPF/endereço por fragmento = prova ilícita (art. 157 CPP) — só comparação de fragmento.
- **Estética impecável (regra absoluta do dono):** nível consultoria; números com separador de milhar e 2 casas; PDF Kroll é sistema separado (não mexer sem pedido).
- **Preservar contrato das rotas:** o front consome ~90 endpoints; nenhuma resposta JSON muda de forma sem atualizar o consumidor.
- **`sqlite3` CLI não existe na VM** — usar `~/JFN/.venv/bin/python` com `import sqlite3`, sempre `mode=ro`/`-readonly` para leitura, e conexões fechadas (evitar "database malformed", memória `compliance-db-malformed-e-restart`).
- **Git:** branch atual `feat/fiscalizacao-emendas-pcrj`. Commits semânticos. Não force-push.

---

## FRENTE 1 — Detecção de empresa fantasma/fachada sem Google Maps

Estado atual: `/fantasma` com 8 sinais (`empresa_fantasma.py`), fachada via embed grátis (`tools/fachada_capturar.py`), Street View pago inerte (sem chave). Gaps: cadastro Receita raso (5.719 ricos), sem hub telefone/e-mail (falta dump Estabelecimentos), sem enriquecimento setorial, sem camada física OSM, SpiderFoot ocioso.

### Task 1.1: Ingerir dump Receita "Estabelecimentos" (telefone/e-mail/endereço)

**Files:**
- Create: `compliance_agent/receita/ingest_estabelecimentos.py`
- Modify: `data/receita_dump/` (baixar `Estabelecimentos0..9.zip` da fonte oficial que já alimenta Empresas/Socios — ver `_dl_empresas.log`)
- Test: `tests/receita/test_ingest_estabelecimentos.py`

**Interfaces:**
- Produces: tabela `estabelecimentos(cnpj TEXT PK, cnpj_basico, matriz_filial, nome_fantasia, situacao_cadastral, data_situacao, motivo_situacao, cnae_principal, cnae_secundarios, tipo_logradouro, logradouro, numero, complemento, bairro, cep, uf, municipio_cod, ddd1, telefone1, ddd2, telefone2, correio_eletronico, endereco_norm)`; função `normalizar_endereco(row) -> str`.

- [ ] **Step 1: Escrever teste que falha** — dado um CSV-fixture com 3 linhas do layout Estabelecimentos (separador `;`, latin-1, aspas), `ingest_estabelecimentos.parse_linha(campos)` retorna dict com `telefone1`, `correio_eletronico` e `endereco_norm` preenchidos e CEP só dígitos.

```python
def test_parse_linha_estabelecimento():
    from compliance_agent.receita.ingest_estabelecimentos import parse_linha, LAYOUT
    campos = ["12345678","0001","55","LOJA X","02","20200101","0","4712100","",
              "RUA","DAS FLORES","100","SALA 2","CENTRO","20040002","33","RJ","6001",
              "21","33334444","","","contato@lojax.com.br"]
    row = parse_linha(campos)
    assert row["cnpj"] == "12345678000155"
    assert row["telefone1"] == "2133334444"
    assert row["correio_eletronico"] == "contato@lojax.com.br"
    assert row["cep"] == "20040002"
    assert "FLORES" in row["endereco_norm"] and "100" in row["endereco_norm"]
```

- [ ] **Step 2: Rodar e ver falhar** — `Run: ~/JFN/.venv/bin/python -m pytest tests/receita/test_ingest_estabelecimentos.py -v` → FAIL (módulo inexistente).
- [ ] **Step 3: Implementar** `parse_linha` (mapear as 30 colunas do layout oficial da Receita; concatenar telefone = ddd+numero; `endereco_norm` = upper, sem acento, colapsa espaço, `tipo+logradouro+numero+bairro+cep`), `LAYOUT` (lista de nomes), e `ingerir(zip_glob, db_path)` que descompacta em streaming, parseia e faz `INSERT OR REPLACE` em lotes de 5000 dentro de transação, índices em `endereco_norm`, `telefone1`, `correio_eletronico`, `cnae_principal`.
- [ ] **Step 4: Rodar e ver passar.**
- [ ] **Step 5: Rodar ingestão real** (só depois de baixar os zips) com `vm_guard` (é pesado — checar load antes): `~/JFN/.venv/bin/python -m compliance_agent.receita.ingest_estabelecimentos --zip 'data/receita_dump/Estabelecimentos*.zip' --db data/compliance.db`. Verificar `SELECT COUNT(*), SUM(telefone1!=''), SUM(correio_eletronico!='') FROM estabelecimentos`.
- [ ] **Step 6: Commit** — `data: ingere Estabelecimentos da Receita (telefone/email/endereço p/ hub de fantasmas)`.

### Task 1.2: Detector "hub compartilhado" (endereço/telefone/e-mail)

**Files:**
- Modify: `compliance_agent/cruzamentos_intel.py` (nova função após `conluio_qsa`)
- Modify: `rotas/investigacao.py` (novo endpoint `/api/intel/hub_compartilhado`)
- Test: `tests/intel/test_hub_compartilhado.py`

**Interfaces:**
- Consumes: `estabelecimentos.endereco_norm/telefone1/correio_eletronico` (Task 1.1).
- Produces: `hub_compartilhado(min_cnpjs=5, chave='endereco'|'telefone'|'email') -> list[dict]` com `{chave_valor, n_cnpjs, cnpjs:[...], n_ativos, n_recebem_ob, total_recebido, risco}`.

- [ ] **Step 1: Teste que falha** — banco-fixture com 6 CNPJs no mesmo `endereco_norm`, 4 deles com OB; `hub_compartilhado(min_cnpjs=5, chave='endereco')` retorna 1 grupo com `n_cnpjs==6`, `n_recebem_ob==4`. Guard: grupos com nome de coworking/galeria conhecido (lista `_ENDERECOS_MASSA_LEGITIMA`) são marcados `risco='baixo'`.
- [ ] **Step 2: Rodar e ver falhar.**
- [ ] **Step 3: Implementar** `GROUP BY chave HAVING COUNT(DISTINCT cnpj) >= min_cnpjs`, join com `favorecido_resumo`/`ob_orcamentaria_siafe` para materialidade; ordenar por `total_recebido`; guard anti-FP por lista de endereços de massa legítima e por `situacao != 'ATIVA'` majoritária.
- [ ] **Step 4: Rodar e ver passar.**
- [ ] **Step 5: Endpoint** `/api/intel/hub_compartilhado?chave=endereco&min=5` retornando `{grupos:[...], gerado_em}`; adicionar ao `_RADAR_PESOS` (`hub_massa`: 12).
- [ ] **Step 6: Commit** — `feat(intel): detector hub compartilhado (endereço/telefone/email) — assinatura de ninho de fantasmas`.

### Task 1.3: Camada física OSM self-hosted (Nominatim + Overpass) — geocoding grátis

**Files:**
- Create: `compliance_agent/geo/osm_local.py`
- Create: `deploy/nominatim/docker-compose.yml` (extrato RJ Geofabrik, `.pbf`)
- Modify: `compliance_agent/verificacao_endereco.py:120` (`_geocodificar` — provider OSM local como primário quando disponível)
- Test: `tests/geo/test_osm_local.py`

**Interfaces:**
- Produces: `geocodificar(endereco) -> {lat, lon, precisao, fonte}` (fonte='nominatim_local'); `edificacao_no_ponto(lat, lon, raio_m=60) -> {tem_building, tem_shop, tem_office, tags:[...]}` (Overpass local ou público com throttle).

- [ ] **Step 1: Teste que falha** — com Overpass mockado, `edificacao_no_ponto(-22.9,-43.2)` retorna `tem_building=True` quando o mock devolve um `way` com `building=yes`; retorna tudo `False` para resposta vazia (endereço sem edificação = sinal de fantasma). `geocodificar` retorna `precisao='rooftop'|'street'|'city'` conforme `osm_type`.
- [ ] **Step 2: Rodar e ver falhar.**
- [ ] **Step 3: Implementar** cliente httpx com `User-Agent` identificado, cache SQLite (`providers_cache.db`), throttle (1 req/s público; ilimitado se `NOMINATIM_LOCAL_URL` setado), query Overpass `[out:json];(way(around:R,lat,lon)[building];node(around:R,lat,lon)[shop];...);out tags;`. `docker-compose.yml` documentado para subir sob demanda (não roda por padrão — VM 2 vCPU).
- [ ] **Step 4: Rodar e ver passar.**
- [ ] **Step 5: Fiar em `verificacao_endereco`** — quando `NOMINATIM_LOCAL_URL` ausente, cai no comportamento atual (honesto: INDISPONÍVEL); quando presente, usa local. Sem regressão.
- [ ] **Step 6: Commit** — `feat(geo): camada física OSM self-hosted (Nominatim+Overpass) p/ existência de edificação sem Google`.

### Task 1.4: Enriquecimento setorial (âncora regulatória por CNAE)

**Files:**
- Create: `compliance_agent/enriquecimento/ancora_setorial.py`
- Test: `tests/enriquecimento/test_ancora_setorial.py`

**Interfaces:**
- Produces: `checar_ancora(cnpj, cnae, objeto) -> {esperado_em:'CNES'|'RNTRC'|'ANVISA'|None, presente:bool|None, fonte, detalhe}`. `None` presente = INDISPONÍVEL (não baixado ainda), nunca `False` sem dado.

- [ ] **Step 1: Teste que falha** — CNPJ com CNAE de saúde (86xx) e objeto "serviços hospitalares" mapeia `esperado_em='CNES'`; se o dump CNES local não contém o CNPJ → `presente=False, risco='alto'`; CNAE sem regulador → `esperado_em=None`.
- [ ] **Step 2: Rodar e ver falhar.**
- [ ] **Step 3: Implementar** mapa `_CNAE_REGULADOR` (saúde→CNES, transporte carga→RNTRC, farma/alimentos→ANVISA), leitura de dumps locais (`data/cnes.db` etc. — quando existirem), fallback INDISPONÍVEL. (O download dos dumps é operação separada, documentada; a lógica é testável com fixtures.)
- [ ] **Step 4: Rodar e ver passar.**
- [ ] **Step 5: Commit** — `feat(enriquecimento): âncora setorial por CNAE (CNES/RNTRC/ANVISA) — presta serviço regulado sem estar no cadastro`.

### Task 1.5: Detector "atestado cruzado intra-grupo" + metadados de PDF (proxy Adele)

**Files:**
- Modify: `compliance_agent/detectores/coletor_ata.py` (extrair CNPJ emissor de atestados quando presentes no texto)
- Create: `compliance_agent/detectores/j_atestado_cruzado.py`
- Create: `compliance_agent/forense/pdf_metadados.py` (pdfinfo/exiftool sobre propostas já baixadas)
- Test: `tests/detectores/test_atestado_cruzado.py`, `tests/forense/test_pdf_metadados.py`

**Interfaces:**
- Produces: `atestado_cruzado(certame) -> list[{licitante, emissor_cnpj, vinculo:'qsa'|'endereco'|'telefone', evidencia}]`; `metadados_pdf(path) -> {author, producer, creation, moddate}`; `mesma_origem(paths:list) -> list[{grupo, campo_comum}]`.

- [ ] **Step 1: Teste que falha (atestado)** — texto de habilitação onde licitante A apresenta atestado emitido por B, e A/B compartilham sócio (reusa QSA) → 1 achado `vinculo='qsa'`.
- [ ] **Step 2: Rodar e ver falhar.**
- [ ] **Step 3: Implementar** regex de CNPJ emissor em blocos de "atestado de capacidade técnica"; cruzar com `socios_reverso`/`estabelecimentos` (endereço/telefone).
- [ ] **Step 4: Ver passar.**
- [ ] **Step 5: Teste que falha (PDF)** — 3 PDFs-fixture, 2 com mesmo `Producer`+minuto de criação → `mesma_origem` agrupa os 2. Implementar via `pdfinfo` (poppler) ou `exiftool` se presente; degradar a `[]` se binário ausente (checar import como em `ocr-deps-sumidas`).
- [ ] **Step 6: Commit** — `feat(detectores): atestado cruzado intra-grupo (Ac. TCU 725/2026) + metadados de PDF (proxy IP do Adele)`.

### Task 1.6: Integrar SpiderFoot como enriquecimento de alvo de alto score

**Files:**
- Create: `compliance_agent/enriquecimento/spiderfoot_bridge.py`
- Test: `tests/enriquecimento/test_spiderfoot_bridge.py`

**Interfaces:**
- Produces: `footprint(dominio_ou_email) -> {n_achados, tem_site, tem_mx, tem_redes, resumo}`; `score_footprint(f) -> 0..1` (footprint vazio = 1.0 = mais suspeito).

- [ ] **Step 1: Teste que falha** — parse de um JSON-fixture de saída do SpiderFoot (`sf.py -o json`) conta achados por tipo; footprint vazio → `score_footprint==1.0`.
- [ ] **Step 2: Rodar e ver falhar.**
- [ ] **Step 3: Implementar** wrapper subprocess do `~/spiderfoot/sf.py` (venv próprio dele) com timeout e `vm_guard`; só roda sob demanda para CNPJ com `radar_risco >= limiar`; alimenta o dossiê. Nunca em sweep de massa (custo/tempo).
- [ ] **Step 4: Ver passar.**
- [ ] **Step 5: Commit** — `feat(enriquecimento): ponte SpiderFoot p/ footprint digital de alvos de alto risco`.

### Task 1.7: Consolidar frente 1 no RADAR e no dossiê

**Files:**
- Modify: `compliance_agent/cruzamentos_intel.py` (`_RADAR_PESOS` + `radar_risco` somam novos sinais)
- Modify: `compliance_agent/empresa_fantasma.py` (`_SINAIS` ganha `hub_massa` e `sem_edificacao_osm` quando disponíveis, com peso e degradação honesta)
- Modify: dossiê (`rotas/produtos.py` `/api/dossie` / `abrirDossie` no front) para exibir os novos sinais com proveniência.
- Test: `tests/test_radar_novos_sinais.py`

- [ ] **Step 1..5** TDD: novo sinal só pontua quando o dado existe; INDISPONÍVEL não penaliza nem beneficia; teste garante que score de CNPJ sem os novos dados é idêntico ao anterior (não-regressão).
- [ ] **Step 6: Commit** — `feat(intel): RADAR e /fantasma incorporam hub, OSM e âncora setorial com degradação honesta`.

---

## FRENTE 2 — Benchmarks e inspirações (entregável de referência, não código)

Já coletado pelos agentes de pesquisa (ver `scratchpad/benchmarks-design.md`, `pesquisa-osint-fantasma.md`, e o relatório de risk-scoring pendente). Consolidar em documento vivo do repo.

### Task 2.1: Escrever `docs/BENCHMARKS.md` consolidado

**Files:**
- Create: `docs/BENCHMARKS.md`

- [ ] **Step 1:** Consolidar as 3 pesquisas em 3 seções: (A) Detecção de fantasma/fachada — 12 sinais R$0 com fonte/URL, ordenados por impacto×facilidade; (B) Design de painel — 12 referências (Palantir/Blueprint, Territory Studio, Linear, Vercel/Geist, Raycast, Bloomberg, Chainalysis, Maltego, Recorded Future, Pencil&Paper, Godly, Domo UX) + stack self-hosted + tipografia; (C) Risk-scoring heurístico — ARACHNE, OCP red flags, CRI/Fazekas, screens de conluio OCDE, rubrica LLM-judge (do agente pendente).
- [ ] **Step 2:** Cada item: o que extrair + como aplica ao JFN + link.
- [ ] **Step 3: Commit** — `docs: BENCHMARKS.md — referências de fantasma, design e risk-scoring`.

---

## FRENTE 3 — Redesign total do painel (`static/jfn-painel.html`)

Alvo: 1 arquivo, ~1824 l. Preservar os ~90 fetches e a lógica de negócio (R$/OB, dossiê, SSE, filtros). Trocar CSS (362 l) e a camada de apresentação; endurecer a implementação para o que DESIGN.md/PRODUCT.md já pregam. Direção: "instrumento de precisão noturno" (Palantir/Linear), não "nave sci-fi".

### Task 3.1: Fundação — design tokens, fontes self-hosted, reset

**Files:**
- Create: `static/assets/fonts/` (Inter var + JetBrains Mono, ou IBM Plex — baixar .woff2, self-host)
- Create: `static/assets/tokens.css` (extraído e disciplinado a partir do `:root` atual)
- Modify: `static/jfn-painel.html` (head: `@font-face`, link tokens.css)
- Verify: screenshot antes/depois via CDP.

**Interfaces:**
- Produces: escala tipográfica FIXA (`--fs-1..--fs-7`, razão 1.2), espaçamento `--s1..--s6` de fato usado, cor com orçamento (1 acento cian + âmbar risco + vermelho crítico + neutros hue 250), sombras multicamada (`--shadow-card` com inner-highlight), `tabular-nums` global em `.num`.

- [ ] **Step 1:** Baixar fontes (woff2) para `static/assets/fonts/` e escrever `@font-face` (corrige o bug: hoje Inter/JetBrains nunca carregam). `font-feature-settings: "cv01","ss03","zero"; font-variant-numeric: tabular-nums` em números.
- [ ] **Step 2:** `tokens.css` com paleta OKLCH revista (base `oklch(0.14 0.012 255)` linha Raycast; elevação por luminosidade; hairlines; sombras Vercel-like), escala tipográfica e de espaçamento fixas, semântica de cor estrita.
- [ ] **Step 3:** Trocar todos os `font-size`/`gap`/cor ad-hoc do CSS por tokens (varredura). Remover: 2 auras blur animadas, `#netbg` canvas, `veilbg`, lightsaber por aba, glow do hero. Manter Conduíte/Kyber/Holofeed (motion que significa estado) porém sóbrios.
- [ ] **Step 4:** Substituir emoji de ícones por um sprite SVG monocromático inline (`static/assets/icons.svg`, `<use>`), ~30 ícones (esferas, abas, KPIs).
- [ ] **Step 5: Verify** — subir/usar jfn.service, screenshot `/painel` via CDP (script `scratchpad/shot_painel.py`), comparar com baseline; confirmar fontes carregadas e zero emoji.
- [ ] **Step 6: Commit** — `feat(painel): fundação — fontes self-hosted, tokens disciplinados, ícones SVG, remove clichês sci-fi`.

### Task 3.2: Arquitetura de informação — unificar /painel e /cockpit, navegação por casos

**Files:**
- Modify: `static/jfn-painel.html` (SPHERES/TABS, header, navegação)
- Modify: `server.py:360` (`/cockpit` redireciona ou vira uma aba do painel)
- Create: `static/assets/rotulos.js` (dicionário snake_case → rótulo humano; mata `sancao_a_epoca` etc. da UI)

- [ ] **Step 1:** Definir hierarquia narrativa: topo = uma tese ("Economia potencial identificada" + o alvo mais forte), depois RADAR priorizado, depois esferas. Um número hero, não sopa de KPIs.
- [ ] **Step 2:** `rotulos.js` — mapa de todos os IDs de detector/sinal para rótulo PT-BR legível + tooltip do glossário; aplicar em toda renderização de lista.
- [ ] **Step 3:** Ticker do Conduíte sem cortar palavras (ellipsis/scroll suave real).
- [ ] **Step 4:** Unificar cockpit como aba "Início" (remover duplicação); `/cockpit` → 308 para `/painel#inicio`.
- [ ] **Step 5: Verify** — screenshots de 4-5 abas representativas; nenhum snake_case visível; hierarquia clara.
- [ ] **Step 6: Commit** — `feat(painel): IA unificada, navegação por tese/casos, rótulos humanos (sem snake_case na UI)`.

### Task 3.3: Componentes densos — tabelas, matriz de risco S×V, sparklines honestas

**Files:**
- Create: `static/assets/uplot.iife.min.js` + `uPlot.min.css` (self-hosted)
- Modify: `static/jfn-painel.html` (componente `tabela()` denso Pencil&Paper; `matrizSV()`; sparklines uPlot com eixo/escala reais)

- [ ] **Step 1:** Componente de tabela densa: header sticky, `content-visibility`, coluna identidade fixa, densidade via `--row-h` (3 níveis persistidos em localStorage), ações não só-hover, célula valor+Δ%.
- [ ] **Step 2:** Matriz Severidade×Verossimilhança (reusa a que existe no `relatorio_direcionamento._matriz_risco`) como grid 5×5 clicável.
- [ ] **Step 3:** Trocar sparklines decorativas por uPlot com dados reais e escala; onde não há série real, remover (honestidade dataviz).
- [ ] **Step 4: Verify** — screenshot de aba com tabela densa e matriz.
- [ ] **Step 5: Commit** — `feat(painel): tabelas densas, matriz S×V, sparklines honestas (uPlot self-hosted)`.

### Task 3.4: Grafo societário/conluio de nível investigativo (sigma.js)

**Files:**
- Create: `static/assets/sigma.min.js` + `graphology.umd.min.js` (self-hosted)
- Modify: `static/graph.html` (ou nova aba do painel) consumindo `/api/intel/grafo_familias` e `/api/intel/comunidades_grafo`

- [ ] **Step 1:** Grafo com setas de fluxo de valor (empenho→OB→favorecido), nós com ícone+badge de risco, expansão progressiva por clique (não despeja tudo), painel lateral sincronizado com a seleção (estilo Chainalysis/Linkurious), cluster por QSA.
- [ ] **Step 2:** "Transforms" estilo Maltego: botões de cruzamento aplicáveis ao nó selecionado (rodar conluio_qsa, ver sanções, ver hub).
- [ ] **Step 3: Verify** — screenshot do grafo com um cluster real.
- [ ] **Step 4: Commit** — `feat(painel): grafo investigativo sigma.js (fluxo de valor, expansão progressiva, transforms)`.

### Task 3.5: Motion com significado + polish final por superfície

**Files:**
- Modify: `static/jfn-painel.html`

- [ ] **Step 1:** Conduíte SSE = pulso discreto (frescor/severidade codificados); microtransições 120-180ms ease-out; `prefers-reduced-motion` honrado (já é).
- [ ] **Step 2:** Passar a skill `impeccable` como juiz por superfície (home, aba de lista, dossiê, grafo), iterando por screenshot até "impecável".
- [ ] **Step 3: Verify** — bateria de screenshots (desktop + mobile) comparada ao baseline `screenshots/painel-2026-07-18/`.
- [ ] **Step 4: Commit** — `feat(painel): motion com significado + polish impecável por superfície`.

---

## FRENTE 4 — Camada heurística/contextual de certames

Estado: motor E7 determinístico + 5 lentes por cláusula/fornecedor. Gaps: sem score contextual agregado por certame; cross-análise de concorrentes rasa (ata_documento=30); sem dossiê contextual do certame persistido; sem síntese narrativa de nível certame; `caso`/`contrato_dossie` vazias.

### Task 4.1: Coletar propostas dos concorrentes em massa → tabela `proposta_item`

**Files:**
- Create: `compliance_agent/editais/coletor_propostas.py`
- Modify: `compliance_agent/detectores/coletor_ata.py` (persistir o que hoje é efêmero)
- Test: `tests/editais/test_coletor_propostas.py`

**Interfaces:**
- Produces: tabela `proposta_item(certame, item, fornecedor_cnpj, fornecedor_nome, valor_unitario, valor_total, classificacao, marca, fonte, sha_evidencia)`; `coletar_certame(certame) -> int` (nº de linhas persistidas).

- [ ] **Step 1: Teste que falha** — ctx de ata com 3 licitantes × 2 itens → `proposta_item` recebe 6 linhas; só o que é literal (sem valor não entra).
- [ ] **Step 2: Rodar e ver falhar.**
- [ ] **Step 3: Implementar** juntando `coletor_ata._extrair_propostas` + `sei/extrator_precos` (3 camadas OCR) → persistência idempotente por `(certame,item,cnpj)`.
- [ ] **Step 4: Ver passar.**
- [ ] **Step 5:** Runner de backfill serial (vm_guard) sobre os certames com edital baixado.
- [ ] **Step 6: Commit** — `feat(editais): tabela proposta_item — propostas de concorrentes por item (cross-análise)`.

### Task 4.2: Screens de conluio por propostas (OCDE) sobre `proposta_item`

**Files:**
- Modify: `compliance_agent/sei/conluio_propostas.py` (operar sobre `proposta_item` persistido; adicionar screens estatísticos)
- Create: `compliance_agent/editais/screens_conluio.py`
- Test: `tests/editais/test_screens_conluio.py`

**Interfaces:**
- Produces: `screens(certame) -> {cv_lances, spread_vencedor_2o, precos_cobertura:bool, markup_uniforme:bool, rodizio_suspeito:bool, score_conluio 0..1}`.

- [ ] **Step 1: Teste que falha** — propostas com CV<0.02 e vencedor exatamente 0,5% abaixo do 2º em todos os itens → `markup_uniforme=True`, `score_conluio` alto; propostas dispersas → score baixo.
- [ ] **Step 2..4:** Implementar coeficiente de variação, spread vencedor↔2º, preços de cobertura (perdedor absurdamente alto), rotação de vencedores entre certames (reusa `/api/pncp/conluio`). Fundamentar (OCDE bid-rigging screens, CADE).
- [ ] **Step 5: Commit** — `feat(editais): screens de conluio OCDE sobre propostas (CV, spread, cobertura, rodízio)`.

### Task 4.3: Índice de Direcionamento de Certame (score contextual agregado)

**Files:**
- Create: `compliance_agent/editais/indice_certame.py`
- Modify: `compliance_agent/editais/db.py` (tabela `certame_indice`)
- Test: `tests/editais/test_indice_certame.py`

**Método (dos benchmarks — CRI/Fazekas + OCP/Cardinal + ARACHNE):**
- Flags agrupados em **famílias** (transparência, competição, conluio, fraude cadastral, preço, execução); tomar **MÁXIMO por família** antes de ponderar → evita dupla contagem de flags correlacionados (single-bidding + poucos licitantes). Score CRI-like 0-1 = média ponderada das famílias.
- **Outlier LOCAL, não threshold universal** (Cardinal): "prazo curto" = p10 da categoria naquele ente; "sobrepreço" = vs mediana do item/região (reusa `comparador_precos`/`lex_base_empirica._percentil`).
- **Materialidade = multiplicador de PRIORIDADE, não de risco** (padrão TCU): `prioridade = score × log(valor_OB)`.
- Pesos calibráveis contra desfechos disponíveis (vencedor depois sancionado, sobrepreço, casos confirmados). Lembrar Banca d'Italia: discricionariedade do julgamento pesa mais que urgência/publicidade.

**Interfaces:**
- Consumes: `clausula_veredito` (restritividade), `proposta_item`+`screens_conluio` (concorrência/preço), `comparador_precos` (sobrepreço unitário), `radar_risco` do vencedor (fantasma/sanção).
- Produces: `calcular(certame) -> {score 0..100, prioridade, faixa, familias:{transparencia, competicao, conluio, fraude, preco, execucao}, drivers:[...], confianca, matriz_sv}`; persiste em `certame_indice`.

- [ ] **Step 1: Teste que falha** — certame com 3 categorias de cláusula restritiva forte + 1 único licitante + sobrepreço 2× + vencedor sancionado → `faixa='EXTREMO'`, `drivers` lista os 4 (um por família, sem inflar pelo correlacionado); certame limpo → `faixa='BAIXO'`. Máximo-por-família comprovado por teste (2 flags da mesma família não somam além do máximo). Pesos explícitos em `_PESOS_FAMILIA` com fonte.
- [ ] **Step 2: Rodar e ver falhar.**
- [ ] **Step 3: Implementar** máximo-por-família → média ponderada → normalização 0-100; `prioridade = score × log1p(valor_OB)`; `drivers` = famílias acima do limiar com evidência (flag + trecho); matriz S×V reaproveitada de `_matriz_risco`. INDISPONÍVEL não zera família — reduz `confianca` (fração de famílias com dado).
- [ ] **Step 4: Ver passar.**
- [ ] **Step 5:** Endpoint `/api/intel/indice_certame?certame=...` + coluna no painel (aba Comparador/Direcionamento).
- [ ] **Step 6: Commit** — `feat(editais): Índice de Direcionamento de Certame (score contextual agregado, drivers, matriz S×V)`.

### Task 4.4: Lente LLM de síntese narrativa de nível certame

**Files:**
- Modify: `compliance_agent/enxame/lentes.py` (nova lente `sintese_certame`)
- Modify: `compliance_agent/enxame/orquestrador.py` (síntese narrativa opcional pós-votação)
- Create: `compliance_agent/editais/narrativa_certame.py`
- Test: `tests/editais/test_narrativa_certame.py`

**Rubrica LLM-judge (dos benchmarks — 6 dimensões 0-4, citação verbatim obrigatória):** D1 restritividade contextual (soma de cláusulas), D2 qualidade da motivação, D3 coerência objeto-quantidade-preço, D4 narrativa da disputa (ata), D5 relação comprador-fornecedor (captura), D6 integridade documental. Regra="violou?" (determinístico já respondeu) / LLM="quão anômalo no contexto?". Norma como contexto (Lei 14.133+súmulas → pedir DESVIOS). Sem trecho literal → dimensão "não avaliável" (nunca nota — lição Hermes aterrado). Integração: `score_final = score_det + α×(média_rubrica/4)`, **α≤0,3, teto 1,0** (LLM realça, nunca sozinho eleva caso limpo a crítico — auditabilidade TC).

**Interfaces:**
- Produces: `narrar(indice, familias, evidencias) -> {tese, paragrafo, rubrica:{d1..d6}, alpha_aplicado, confianca, ressalvas, citacoes:[...], prompt_versao}` via LLM grátis (Groq llama-3.3-70b), com guard: não afirma além das evidências, recorta prompt <8k (limite dos 8B), degrada a template determinístico se LLM indisponível.

- [ ] **Step 1: Teste que falha** — com LLM mockado devolvendo rubrica válida, `narrar` produz `tese` não-vazia citando ≥1 driver e `score_final ≤ score_det+0.3`; dimensão sem citação → nota None (não avaliável); com LLM indisponível, cai no template determinístico (não quebra).
- [ ] **Step 2..4:** Implementar as 6 dimensões com âncoras 0/2/4, saída JSON estrito, parse honesto (malformado → None → template); registrar `citacoes` e `prompt_versao` (reprodutibilidade exigível em representação).
- [ ] **Step 5: Commit** — `feat(editais): síntese narrativa de certame por LLM (rubrica judge, degradação determinística)`.

### Task 4.5: Persistir em `caso`/`contrato_dossie` e expor no painel + relatório

**Files:**
- Modify: `compliance_agent/editais/indice_certame.py` (grava `caso` quando faixa ≥ ALTO)
- Modify: `rotas/produtos.py` (`/api/dossie` inclui índice + narrativa)
- Modify: `compliance_agent/reporting/relatorio_direcionamento.py` (seção "Contexto do certame" com índice, screens e narrativa)

- [ ] **Step 1..4:** TDD — índice ALTO cria linha em `caso` (`tipo_achado='direcionamento'`, `economia_potencial`, `evidencia_ids`) idempotente; dossiê e PDF Kroll ganham a seção; vault recebe caso (reusa fluxo veredito≥8).
- [ ] **Step 5: Commit** — `feat(editais): índice de certame persistido em caso + no dossiê e no PDF Kroll`.

---

## Ordem de execução recomendada

1. **F3 (painel)** primeiro nas Tasks 3.1-3.2 — impacto visual imediato e independente; o dono está incomodado com isso agora.
2. **F1 Tasks 1.2, 1.5** (só SQL sobre dados existentes — maior densidade de acerto por hora) em paralelo lógico.
3. **F4 Tasks 4.1-4.3** (camada contextual — o pedido mais "inteligente").
4. **F1 Tasks 1.1, 1.3, 1.4, 1.6** (dependem de dumps/serviços novos — mais pesadas na VM, agendar).
5. **F3 Tasks 3.3-3.5** (componentes ricos, dependem da fundação).
6. **F4 Tasks 4.4-4.5** e **F1 1.7** (consolidação).
7. **F2 Task 2.1** (doc) pode fechar a qualquer momento.

## Verificação global (definition of done)

- Suíte JFN passa (`~/JFN/.venv/bin/python -m pytest -q`) — hoje ~1.603 testes.
- Painel: screenshots impecáveis (desktop+mobile) aprovados pela skill impeccable; zero emoji, zero snake_case na UI, fontes carregadas, sem clichês sci-fi; ~90 endpoints ainda respondem.
- F1: novos sinais pontuam só com dado presente (não-regressão de score comprovada por teste); RADAR e dossiê os exibem com proveniência.
- F4: `certame_indice` populado; ao menos 1 certame com narrativa; caso persistido; PDF Kroll com a seção de contexto.
- `BENCHMARKS.md` no repo.
- Nada quebrou em produção (jfn.service healthy).
