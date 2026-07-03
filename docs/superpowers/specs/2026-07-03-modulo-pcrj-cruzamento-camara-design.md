# Módulo PCRJ v1 — Cruzamento de Vínculos Câmara × Prefeitura do Rio

**Data:** 2026-07-03 · **Status:** implementado (v1) · **Autor:** JFN (Claude) · **Owner:** jfelippebethlem

## Norte
Início do **Módulo de Análise da Prefeitura do Rio (PCRJ)**. v1 responde ao pedido do dono:
*"cruze todas as folhas e identifique quem já foi nomeado na câmara-prefeitura; quem é de qual
gabinete ou já passou por cada gabinete."* Alimenta o caso aberto de **acúmulo de cargos**,
agora no eixo municipal.

## Realidade dos dados (verificada na fonte)
- **Câmara RJ** — CSV em massa por ano de ingresso: `aplicsc.camara.rj.gov.br/.../Cons_Relacao_Servidores_API_csv/?ANOINGRESSO=<ano>`
  (ScriptCase: a chamada regenera `/scriptcase/tmp/Relacao_Servidores.csv`). ISO-8859-15, sem
  cabeçalho: **Nome · Vínculo · Símbolo · Cargo · Lotação · data(ato) · data(pub) · nº**. A
  **Lotação** já traz o gabinete ("Gabinete Parlamentar Nº 48"). **Sem CPF.** Anos 1990→2026.
- **Gabinete→Vereador** — planilha `.xls` "núcleos dos gabinetes"
  (`transparencia.camara.rj.gov.br/996-tabela-atual-de-nucleos-dos-gabinetes/file`): 51 gabinetes.
- **Prefeitura RJ** — `contrachequeapi.rio.gov.br` (JSF/PrimeFaces). Consulta **por nome** (substring)
  + competência (mês/ano, 2021→2026). **Sem CSV em massa.** O `ViewState` é client-side (gzip) →
  a busca é replicável por **POST puro** (sem browser); resultado traz Matrícula · Nome · Cargo ·
  **Lotação(órgão)** · Vantagens · Descontos · Líquido · Admissão · Exoneração · Inativação.
- **Certificado TLS incompleto** nas duas fontes → `verify=False` (dado público, read-only; nenhuma credencial).

## Decisão de arquitetura
Cruzamento **direcional** (a Prefeitura não é listável em massa): monta o cadastro completo da
Câmara (com gabinete) e consulta **cada nome** na Prefeitura. **Sem CPF em nenhuma base → match
por NOME normalizado é INDÍCIO, nunca prova** (homônimo possível). Banco **dedicado `data/pcrj.db`**
(isola da `compliance.db`; join por ATTACH quando cruzar com OB no futuro).

### Componentes (`compliance_agent/pcrj/`)
- `nomes.py` — normalização de nome (sem acento, MAIÚSC, ordinais removidos) + blocagem.
- `db.py` — schema de `pcrj.db` (WAL + busy_timeout, padrão dos writers da casa).
- `camara_servidores.py` — coleta todos os anos; deriva gabinete da lotação.
- `camara_gabinetes.py` — mapa Gabinete Nº → vereador (parse do .xls).
- `pcrj_remuneracao.py` — `Sessao` HTTP: POST JSF por nome/competência; parser de linhas; backoff.
- `cruzamento.py` — orquestra; níveis de confiança; persiste consultas + vínculos.
- `relatorio.py` — produto Kroll (md+pdf) via `reporting/render_html`.

### Níveis de confiança (honestidade dura)
- `indicio_nome_unico` — 1 matrícula PCRJ com o nome → duplo vínculo provável (homônimo ainda possível).
- `homonimo_ambiguo` — 2+ matrículas com o mesmo nome → não isolável sem CPF.
- `nao_encontrado` — nenhum servidor PCRJ com o nome.
- `indisponivel` — erro de consulta (**≠ 'nada encontrado'**; corrige bug de honestidade).

Sinal mais forte: vínculo **efetivo/carreira** no Executivo (Guarda Municipal, professor, concursado)
sobreposto a posto comissionado na Câmara → indício de acumulação vedada (**CF art. 37, XVI/XVII**),
a apurar por CPF no RH — jamais acusação.

## Rate-limiting (lição aprendida em execução)
O portal da Prefeitura bloqueia rajada (~500 req rápidas → ~60s de bloqueio, respondendo 200 com
partial-response curto SEM `divResultados`). Fixes: (1) detectar ausência de `divResultados` = erro
→ backoff+retry, **nunca** tratar como zero-resultado; (2) `workers=2 · pausa=0.4` → **0 bloqueios**
na calibração. Cobertura histórica = competências-amostra (gestão atual + 06/2024 + 06/2021).

## Limitações declaradas
Match por nome (homônimo); busca por substring; só competências-amostra; sem CPF a confirmação é no RH.

## OCR (frente paralela — "atacar em segunda passada")
Causa-raiz: libs de OCR (`pytesseract`/`fitz`/`pdfminer`) sumiram no rebuild do venv ARM →
`ocr_documento` era **no-op silencioso** em todo lugar (inclusive no sweep vivo). **Reinstaladas**
(provado: recupera 2.5k+ chars onde antes dava ""). Cap do caminho *cracked* alinhado ao normal
(`SEI_MAX_DOCS=40`) → anexos de NF agora entram no OCR. Backfill do acervo em disco = **inviável**
(PDFs-fonte em branco/ausentes: 373 sem PDF + 39 brancos de 412); recuperação só por **re-leitura
in-session** (`tools/sei_reocr_backfill.py`, browser_lock, bounded).

## Testes
`tests/pcrj/test_pcrj.py` — normalização, derivação de gabinete, níveis de confiança, parser JSF (17 casos).

## Entregáveis
`data/pcrj.db` (consultável) + `reports/pcrj_camara_cruzamento_<data>.pdf|html` (Kroll).
Fora do v1 (YAGNI): comando `/pcrj` no Yoda, cruzamento com OB/despesa, secretarias por árvore.
