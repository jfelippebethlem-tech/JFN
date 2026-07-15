# Captação de Licitações da Prefeitura do Rio — Harvester Municipal (Saúde + PPPs, 2021+)

**Data:** 2026-07-15
**Autor:** Claude (fiscalização JFN) · **Norte:** controle externo — Deputado Estadual RJ
**Caso-piloto de validação:** PPP do Complexo Hospitalar Souza Aguiar (CCPAR)

---

## 1. Objetivo

Levantar, de forma sistemática e sustentável (sem API paga), **toda a matéria licitatória da Prefeitura do Rio** para permitir perícia/fiscalização, começando por **Saúde + PPPs a partir de 2021** (gestão Eduardo Paes). Construir um **harvester amplo** reusável, e um **módulo novo de acesso ao processo municipal** (`sei_prefeitura`), tendo o **Souza Aguiar** como primeiro dossiê ponta-a-ponta que valida a infraestrutura.

## 2. Escopo (1ª leva)

- **Domínio:** Saúde (SMS, hospitais, RioSaúde, Organizações Sociais) **+ PPPs/concessões**.
- **Recorte temporal:** `ano ≥ 2021`.
- **Fora de escopo agora:** demais órgãos da Prefeitura (entram depois, reusando a mesma infra); histórico pré-2021.
- **Chave de escopo aplicada em TODA fonte:** lista de CNPJs/UGs de Saúde do **Município** (não do Estado, não federal) + filtro de ano. Elimina a contaminação atual (ver §3).

## 3. Diagnóstico do estado atual (o gap real)

Levantado direto do `data/compliance.db`:

| Tabela | Linhas | Origem | Problema |
|---|---|---|---|
| `pcrj_licitacoes` | 14.015 | 100% PNCP | PNCP só cobre **2024+**; contaminada com **federal (FURNAS)** e **Estado/SES-RJ** |
| `pcrj_contratos` | 4.219 | 100% PNCP | idem; mistura Estado/Município |
| `pcrj_despesa` | 78.595 | ContasRio (CSV) | Só o **dinheiro** (empenho/liq/pago) 2021–23; não traz o processo |
| `processos_sei` | **0** | — | **SEI municipal nunca captado** — buraco principal |
| PPP/concessão | inexistente | — | **Souza Aguiar não existe** em nenhuma tabela |

**Conclusão:** o gap não é "coletar licitação nenhuma". É: (1) **escopar/limpar** o PNCP ao Município-Saúde; (2) cobrir **2021–2023** (pré-PNCP obrigatório); (3) captar o **processo completo** (edital, pareceres PGM/CGM, atas); (4) criar a **camada PPP**.

## 4. Recon técnica de acesso (o "captcha" era um fantasma)

| Sistema | Natureza real | Captcha? | Rota |
|---|---|---|---|
| **`acesso.processo.rio`** | **SIGA-Doc** (não SEI), app JSF | **Sem imagem de captcha** na consulta pública | GET p/ cookie+token → POST número `SSSPPPAAAA/XXXXX`; só andamento |
| **`sei.rio`** (novo, TRF4) | SEI padrão nacional | **Nativo de imagem** (`captcha.php`), configurável, muitas vezes **desligado**. **Nunca reCAPTCHA** | `md_pesq_processo_pesquisar.php`; captcha (se houver) → OCR local via `captcha_solver.py` |
| **`doweb.rio.rj.gov.br`** | Diário Oficial | **Nenhum** — API JSON aberta | `/apifront/portal/edicoes/...` (confirmado ao vivo) |
| **`ccpar.rio`** | Portal de PPPs (CCPAR) | Nenhum | scrape de documentos publicados |

**Confirmado ao vivo (2026-07-15):** `doweb .../edicoes_from_data/` retorna JSON de edições; página CCPAR do Souza Aguiar no ar com edital.

**Repos de referência (não instalar; cherry-pick de padrão):** `okfn-brasil/querido-diario` (arcabouço de diário), `dfalbel/captchaReceita2` e tese `jtrecenti` (CNN p/ captcha de imagem gov — prova de >90%/caractere), `SEI-Pro/mcp-seipro` (API REST `mod-wssei` — **exige credencial**, só serve acesso autenticado, não anônimo).

## 5. Arquitetura

Harvester municipal multi-fonte, escopado, gravando em `data/pcrj.db` (base dedicada já existente; cruza com `compliance.db` por `ATTACH` só na leitura — não escreve na base grande).

```
 REUSAR ── A. PNCP        (collectors/pncp.py)      → escopar+limpar (2024+ metadados)
       └── B. ContasRio   (pcrj/contasrio.py)       → dinheiro 2021-23 (empenho/liq/pago)
 CRIAR ─── C. D.O. Rio    (pcrj/doweb.py) NOVO       → editais/extratos/atos/PPP 2021+  [BACKBONE]
       ├── D. SEI-Pref.   (pcrj/sei_prefeitura.py) NOVO → processo completo (SIGA + SEI.RIO)
       └── E. PPP/CCPAR   (pcrj/ppp_ccpar.py) NOVO   → modelagem/consulta/edital/contrato
                                   ↓
                     data/pcrj.db  (novas tabelas §7)
                                   ↓
             Souza Aguiar = dossiê piloto que exercita C+D+E
```

### 5.1 Componentes (o que cada um faz, como se usa, do que depende)

- **C. `pcrj/doweb.py` — coletor do Diário Oficial (BACKBONE).**
  - *Faz:* busca por termo/órgão/período na API `doweb`; baixa o texto do ato (`imprimir_materia`/`publicacoes_ver_conteudo`) e/ou o PDF (`pdf_diario`); extrai **nº de processo**, extrato de contrato, homologação, atos de PPP.
  - *Usa:* `coletar_por_termo(termo, dt_ini, dt_fim)`, `coletar_edicao(id)`.
  - *Depende de:* `httpx`, `pcrj/db.py`. Sem captcha, sem login.
  - *Nota de implementação:* o endpoint real da busca por termo (por trás de `/buscanova/`) precisa ser capturado por inspeção de rede; `edicoes_from_data` sozinho lista edições, não busca conteúdo.

- **D. `pcrj/sei_prefeitura.py` — acesso ao processo municipal.** Dois back-ends atrás de uma interface só:
  - `siga_consultar(numero)` → `acesso.processo.rio` (SIGA/JSF): andamento/tramitação.
  - `seirio_pesquisar(termo|interessado|numero)` → `sei.rio` (`md_pesq_processo_pesquisar.php`): metadados e, quando público, inteiro teor. Captcha nativo (se presente) resolvido por `captcha_solver.py` (OCR local; retry N vezes).
  - *Interface única:* `consultar_processo(numero) -> ProcessoMunicipal` decide o back-end pelo padrão do número / disponibilidade.
  - *Depende de:* `httpx` (SIGA/SEI HTTP puro), `captcha_solver.py`, `vm_guard.py` se precisar de browser headless (fallback quando o JSF exigir JS).

- **E. `pcrj/ppp_ccpar.py` — coletor de PPP/concessão.**
  - *Faz:* varre `ccpar.rio` (mapa de projetos + `/transparency/bids/`), lista projetos de PPP, baixa documentos (edital, minuta, anexos, relatório de consulta pública), extrai fases/datas/valores/vencedor.
  - *Usa:* `listar_projetos()`, `coletar_projeto(slug)`.
  - *Depende de:* `httpx`, extrator de PDF já existente no repo.

- **A/B. Reuso escopado.** `pncp.py` e `contasrio.py` recebem a **lista de CNPJs Saúde-Município** e filtro `ano≥2021`; um passo de limpeza remove o que já entrou fora de escopo (federal/estadual) das tabelas atuais (marcação, não delete cego).

## 6. Fluxo de dados (Souza Aguiar como exemplo)

1. **E (CCPAR):** coleta o projeto Souza Aguiar → documentos, fases, valores, vencedor (Smart Hospital, R$ 191 mi, 30 anos, ~R$ 850 mi).
2. **C (doweb):** busca "Souza Aguiar" / "CCPAR" no D.O. → **nº do processo administrativo**, extrato de edital e de contrato, atos de consulta/audiência pública.
3. **D (SEI-Pref.):** com o nº do processo, puxa andamento (SIGA) e inteiro teor público (SEI.RIO): pareceres PGM/CGM, atas.
4. **A/B:** cruza com PNCP/ContasRio (empenho→pagamento; contraprestação efetivamente paga).
5. **Dossiê** renderizado no padrão da casa (`render_html`/PDF), com honestidade: `INDISPONÍVEL ≠ 0`, indício ≠ acusação, nº nunca inventado.

## 7. Armazenamento (`data/pcrj.db` — tabelas novas)

```sql
CREATE TABLE pcrj_edital (            -- editais/licitações consolidados (multi-fonte)
  chave TEXT PRIMARY KEY,            -- nº controle PNCP | nº edital | nº processo
  fonte TEXT,                        -- pncp | doweb | sei | ccpar
  orgao_cnpj TEXT, orgao_nome TEXT,
  modalidade TEXT, objeto TEXT, valor_estimado REAL,
  numero_processo TEXT,              -- SSSPPPAAAA/XXXXX quando houver
  ano INTEGER, data_ref TEXT,
  bruto TEXT, coletado_em TEXT       -- json de proveniência
);
CREATE TABLE pcrj_processo (          -- processo administrativo (SIGA/SEI municipal)
  numero_processo TEXT PRIMARY KEY,
  sistema TEXT,                      -- siga | seirio
  interessado TEXT, assunto TEXT, orgao TEXT,
  andamento_json TEXT,               -- tramitação
  disponivel INTEGER,                -- 1 achou / 0 nada / NULL indisponível
  coletado_em TEXT
);
CREATE TABLE pcrj_processo_doc (      -- documentos do processo (inteiro teor)
  numero_processo TEXT, seq INTEGER, tipo TEXT, titulo TEXT,
  texto TEXT, url TEXT, coletado_em TEXT,
  PRIMARY KEY (numero_processo, seq)
);
CREATE TABLE pcrj_ppp (               -- projetos de PPP/concessão (CCPAR)
  slug TEXT PRIMARY KEY, nome TEXT, orgao_gestor TEXT,
  objeto TEXT, modalidade TEXT, fase TEXT,
  valor_investimento REAL, contraprestacao REAL, prazo_anos INTEGER,
  vencedor TEXT, numero_processo TEXT,
  datas_json TEXT, docs_json TEXT, coletado_em TEXT
);
CREATE TABLE pcrj_doe_materia (       -- atos do D.O. Rio (proveniência bruta)
  id_materia TEXT PRIMARY KEY, edicao TEXT, data TEXT,
  orgao TEXT, tipo TEXT, texto TEXT, url TEXT, coletado_em TEXT
);
```

Regra de proveniência: toda linha guarda `coletado_em` e `bruto/json` da fonte. Nunca sobrescrever dado bruto; `disponivel/encontrado` é tri-estado (1/0/NULL) — `INDISPONÍVEL ≠ 0`.

## 8. Fases de implementação (cada uma verificável)

1. **F1 — Escopo & base:** lista de CNPJs/UGs Saúde-Município; tabelas novas em `pcrj/db.py`. *Verif.:* `.schema` mostra tabelas; lista de CNPJs > 0.
2. **F2 — Coletor doweb (C):** busca por termo + download de matéria. *Verif.:* buscar "Souza Aguiar" retorna ≥1 matéria com texto e (idealmente) nº de processo.
3. **F3 — Coletor CCPAR (E):** projeto Souza Aguiar completo. *Verif.:* `pcrj_ppp` tem a linha do Souza Aguiar com vencedor e docs.
4. **F4 — Dossiê Souza Aguiar (piloto):** junta C+E (+D se o processo abrir). *Verif.:* PDF/HTML com fases, valores, documentos e proveniência.
5. **F5 — SEI-Pref. (D):** SIGA + SEI.RIO com OCR de captcha se necessário. *Verif.:* consultar um nº de processo real retorna andamento; captcha (se houver) resolvido.
6. **F6 — Harvester amplo:** varredura Saúde-Município 2021+ nas fontes, escopada e serial (respeitando VM 2 vCPU). *Verif.:* contagens por ano/órgão coerentes; PNCP limpo.

## 9. Restrições e riscos (honestidade first)

- **VM 2 vCPU:** coletores **seriais**, um pesado por vez; sem loop auto-reacionável; checar load antes de sweep.
- **Custo:** tudo local/gratuito. OCR de captcha = Tesseract local. Nenhum serviço pago. Sem premissa de "free tier".
- **`INDISPONÍVEL ≠ 0`, indício ≠ acusação, nº nunca inventado, CPF mascarado.**
- **SEI.RIO em migração:** processos antigos podem estar só no SIGA (`processo.rio`); os novos no `sei.rio`. O módulo tenta os dois.
- **Busca do doweb:** endpoint real por trás de `/buscanova/` precisa ser confirmado por inspeção de rede na F2.
- **Empenho ≠ Liquidação ≠ OB:** só a Ordem Bancária é "pago"; contraprestação de PPP idem — nunca apresentar empenho como pago.

## 10. Fora de escopo (YAGNI)

- Demais órgãos além de Saúde/PPP (fase futura, mesma infra).
- Acesso autenticado ao inteiro teor sigiloso (exigiria credencial; `mcp-seipro` fica como opção documentada, não implementada agora).
- Treinar CNN de captcha **antes** de confirmar que o captcha está sequer ligado no alvo (a recon indica que costuma estar desligado).

---

## 11. Status de implementação (2026-07-15)

Construído, **testado como humano** (end-to-end ao vivo + unit tests) e com bugs corrigidos por ciclo teste→debug→reteste.

| Fase | Entrega | Testes | Status |
|---|---|---|---|
| F1 | Schema `pcrj_doe_materia`/`pcrj_processo`/`pcrj_processo_doc`/`pcrj_ppp` em `pcrj/db.py` | — | ✅ |
| F2 | `pcrj/doweb.py` — busca ES do D.O. + filtro `/y:anos` + extração de nº processo (SIGA/SEI.RIO) + classificação | `tests/pcrj/test_doweb.py` (7) | ✅ |
| F3 | `pcrj/ppp_ccpar.py` — projeto CCPAR (fases/datas/investimento/**14 docs** do Souza Aguiar) | `test_ppp_ccpar.py` (5) | ✅ |
| **INT** | `pcrj/analise.py` — **integração aos motores existentes** (E1–E7, direcionamento, Lex, fraude) | `test_analise.py` (5) | ✅ |
| F4 | `pcrj/dossie_ppp.py` — dossiê Kroll consolidando CCPAR+D.O.+análise | (via smoke) | ✅ |
| F5 | SEI-Prefeitura | — | ⚠️ **reavaliado** (ver abaixo) |
| F6 | Sweep amplo com filtro de data | — | 🔜 parcial (filtro `/y:` pronto; falta `/di:` + lista de CNPJs Saúde) |

Suíte `tests/pcrj/`: **79 passed**.

### Bugs achados e corrigidos por teste (disciplina teste→debug→reteste)
1. `extrair_processos` gerava submatch espúrio (`61/000.285/2023` dentro de `09/61/000.285/2023`) → filtro de substring.
2. `classificar` errava "HOMOLOGO" → regex `homologa` trocado por `homolog` (pega homologa/homologo/homologação).

### Reavaliação F5 (testando como humano, corrige a recon inicial)
- **`acesso.processo.rio` (SIGA) USA reCAPTCHA v2 do Google** (sitekey `6LdAQ…`, `recaptcha/api.js`) — **NÃO** é o captcha nativo. É bloqueio real para HTTP puro; serviço pago de captcha é **proibido** (regra do dono). → **não perseguir**.
- **`sei.rio`** (SEI novo) — pesquisa pública padrão retorna **404** (migração em curso; busca ainda não publicada).
- **Reajuste (rota melhor):** os motores analisam **TEXTO**, e há texto **sem captcha** por duas vias já implementadas — **D.O. Rio (doweb)** e **PDFs da CCPAR**. O inteiro teor interno do processo (SIGA/SEI) fica como pendência bloqueada por reCAPTCHA, **não** no caminho crítico.

### Integração aos motores (o pedido central do dono)
`pcrj/analise.analisar_edital(texto, …)` roda sobre o texto captado:
(i) `detectores.rodar_edital` (E1–E7 via `montar_ctx_de_sei`); (ii) `direcionamento_sinais.analisar_direcionamento_det`; (iii) `lex_analise_conteudo.analisar_texto_edital`; (iv) `knowledge.pattern_engine.analisar_contexto_completo` (catálogo `fraudes_licitacao`). Consolida num score de triagem (indício ≠ acusação). **Validado disparando em edital real** (município: Lex R5 + hipótese de fraude) e em edital dirigido sintético (🔴 vermelho, cascata, E7, R3/R7).

### Edital completo ingerido (dossiê "quente") ✅
`ppp_ccpar.ingerir_edital(slug)` baixa o doc EDITAL da CCPAR (ZIP 47 MB), extrai o PDF principal (`EDITAL PPP COMPLEXO SOUZA AGUIAR.pdf`, 53 pág, 128 mil chars) e guarda em `pcrj_processo_doc` (`tipo='edital_ccpar'`). O `dossie_ppp` passa a analisar as **cláusulas de habilitação reais**. Resultado no Souza Aguiar: **🔴 alto (score 0.85), 12 cláusulas restritivas** (atestado específico + certificações), **E7 confirmado**, **Lex R5/R7**. A triagem deixou de ser factual e virou analítica.

### Próximos passos
- **Lente PPP-específica** (a hipótese `consulta_ppp_privatizacao_manipulada` já existe no catálogo) — concessão não aciona todas as heurísticas de pregão comum.
- F6: `/di:AAAA-MM-DD` + lista de CNPJs/UGs Saúde-Município para o sweep 2021+.
- Escopar/limpar o PNCP atual (remover contaminação federal/estadual de `pcrj_licitacoes`).
