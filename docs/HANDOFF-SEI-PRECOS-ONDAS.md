# HANDOFF — Ondas SEI/Preços (branch `sei-precos-onda5`)

> **RETOMADA (ler se a sessão caiu por session-limit / crash de CPU da VM / limite de contexto).**
> Branch de trabalho: **`sei-precos-onda5`** (base `linux`@`3fdbb5d`). `pytest -q` antes de cada commit;
> **checar `uptime`/`free -m` antes de tarefa pesada** (a sessão já caiu por contenção de CPU — ver
> memória `diretriz-cpu-nao-crashar-vm`). NÃO tocar módulos SIAFE com o sweep rodando
> (`pgrep -f 'siafe_sweep_full 2'`). Tudo grátis. Documentar cada checkpoint (o quê/como/porquê + erros).

## Contexto (de onde viemos)
Pacote de 3 specs do dono (no cache do Hermes): `JFN-HANDOFF-CLAUDE-CODE` (guia + Fase 0),
`JFN-SPEC-SEI-PRECOS` (Onda 5 + extrator de preço unitário), `JFN-PILOTO-SEI-10` (piloto). Diário-mestre:
`docs/JFN-2.0-IMPLEMENTACAO.md` (blocos do fim têm o detalhe). Estado base já em produção (branch `linux`):
relatório com risco recalibrado, consolidação matriz+filial, DD keyless (mídia adversa GDELT+DDG, ExifTool,
camada `providers/`), 121 testes verdes, 4/6 chaves ativas.

## Fase 0 (descobertas — FEITAS)
- OB do SIAFE **não tem** objeto/natureza/subitem/CNAE → classificação de gastos depende do **SEI (objeto) +
  CNAE (BrasilAPI)**. `processos_sei` **vazia** → varredura sai de `ordens_bancarias.numero_sei` (41.545 c/ SEI,
  campo **ruidoso**). pdfplumber instalado (grátis). **`JFN-SPEC-AVALIARGASTOS-RJ` NÃO foi enviado.**

## Plano de ondas (e estado)
- **Onda A — scaffolding SEI ✅** (`compliance_agent/sei/{navegador,classificador_doc,extrator_precos}.py`,
  commit `89273dd` na `linux`; 6 testes). Honesto: parser em camadas, `falha`/0 quando não extrai.
- **Onda B — piloto empírico ✅** (`tools/pilot_sei_avaliar.py`, commit `3fdbb5d`; 2 testes). Rodou ao vivo:
  abertura 100%, mas **DESCOBERTA P0.2/P0.3: os títulos da árvore vêm como IDs numéricos** ("132513499"),
  não como tipo → `classificador_doc` cai em "outros".
- **Onda C — capturar o TIPO do documento (EM ANDAMENTO nesta branch).** Enriquecer o scraper da árvore
  (`collectors/sei_cdp.py::_JS_LE_ARVORE_E_TEXTO`) para capturar `title`/`aria-label`/texto do nó pai (onde o
  SEI-RJ põe o tipo), validar com 1 leitura ao vivo (CPU: 1 leitura só, não sweep), recalibrar
  `classificador_doc` com os rótulos reais. **Sem isso, a extração de preço não mira homologação/ata.**
- **Onda C — VALIDADA ✅ ao vivo (commit `5c710e6`).** Piloto em 4 processos SRP (UG 270060): **4/4 abertos**,
  scraper captura **rótulos reais** ("Nota de Empenho - NE", "Nota de Autorização de Despesa - NAD", "Despacho de
  Encaminhamento", "Recibo", "Ofício", "Anexo"). O 0-docs anterior era **transiente**. Classificador calibrado +
  tipos novos `planilha_preco` (carrega preço) e `autorizacao_despesa`. **DESCOBERTA-CHAVE:** os processos de
  **execução/empenho** (UG 270060) **NÃO têm a ARP/tabela de preço** — ela vive no **processo de LICITAÇÃO/pregão
  do SRP** (Lei 14.133 arts. 82-86). **Próximo passo p/ achar a tabela:** mirar o processo de pregão/ata (não o de
  empenho); candidatos: docs "Anexo"/"Planilha"/"Proposta" e processos cujo tipo de doc inclua ata_rp/homologacao.
  Árvores salvas em `data/pilot/calibracao/`.
- **Onda F — Receita TFE ✅ coletor (commit `46d2bf9`).** `collectors/tfe_receita.py` (CKAN `tfe-receita`): CSV
  mensal 2016→atual com **Previsão Inicial(LOA)·Atualizada·A Realizar·REALIZADA** por Poder/Categoria/Órgão/UG.
  Parser validado no dado real; **ingestão NÃO rodada** (evitar lock c/ sweep — rodar `tfe_receita.ingerir()` com
  sweep idle). Próximo: cruzar realizada×prevista (LOA) e receita×despesa no relatório de órgão.
- **Onda D — paralelizar enrichers OSINT do render** (opensanctions/aleph/midia/links sequenciais no
  `render_pdf_html`); rapidez. Pura, sem browser.
- **Pendência UX:** `/lista` mostra menos que `/capacidades` — unificar (o dono quer tudo junto). ✅ FEITO
  (commit `8a8b102`): `/api/lista` agora gera da skilltree (43 capacidades, agrupado por domínio).

## POLÍTICA SEI — o que GUARDAR e o que ANALISAR (decidido com o dono, calibrado em árvores reais + Lei 14.133)
**O que guardar** (`classificador_doc.valor_doc`/`deve_guardar_texto`): nem todo doc importa.
- **ALTO (extrai+guarda texto/itens):** parecer_juridico (PGE/assessoria — *aponta as FALHAS*, ouro p/ o Lex),
  homologacao, ata_rp, contrato, mapa_lances, planilha_preco, pesquisa_precos, etp, tr, edital.
- **MÉDIO (metadado+valor):** empenho, liquidacao, autorizacao_despesa.
- **BAIXO (só título+contagem, NÃO o texto):** tramitacao (despacho de encaminhamento, ofício, e-mail, recibo,
  anexo, memorando, capa) e outros. Storage compacto em `data/sei_indice.db` (`sei/indice.py`), PDFs em cache
  curto podado (`podar_cache`). ~1-3 KB/processo → ~80-120 MB p/ 41k OBs.

**O que analisar (red flags — análises que importam):**
- **Acesso restrito + processo concluído c/ OB paga = 🔴 RED FLAG** (deveria ser público) — `navegador` expõe
  `acesso_restrito`/`motivo_zero` (distingue de falha técnica).
- **Conluio em propostas** (`sei/conluio_propostas.py`): markup uniforme (B = A ±Y% em TODA a lista =
  proposta-cobertura), preços idênticos entre concorrentes, texto similar (mesmo redator). Art. 90 Lei 8.666/
  337-F CP; Art. 36 Lei 12.529 (CADE).
- **Cadeia** (`relacionados`): navegar execução→licitação→**ARP** (onde mora o preço unitário). SRP→ARP (Lei
  14.133 arts. 82-86).

## ⚠️ BLOQUEADOR do sweep massivo (a resolver ANTES de varrer as 41k OBs)
**O reader é instável na resolução da busca:** processos recentes (UG 520002/2025) **abrem mas retornam 0 docs
porque o reader fica na tela `protocolo_pesquisar`** (não navega para dentro do processo) — `motivo_zero=
busca_nao_resolveu`. Os SRP UG 270060 deram árvores cheias (NE/NAD/Despacho/Recibo/Ofício/Anexo). **Próximo passo
técnico:** debugar `sei_reader`/`sei_cdp` o fluxo busca→abrir (formato do número, clique no resultado, espera do
`ifrArvore`) — só então o sweep de 10 (e depois 41k) rende. Os `numero_sei` da OB tb são ruidosos ("0",
"000 048 0 26") → preferir SEI bem-formados (TCE-RJ) e a cadeia `relacionados`.

## Bloqueado / depende do dono
- 2 chaves grátis (`ALEPH_API_KEY`, `OPENCORPORATES_API_TOKEN`) → quando chegarem, **reavaliar tudo**.
- `/lista` fast-path (bot vivo — OK do dono).
- `/avaliargastos` + `gastos/*` (falta o spec AVALIARGASTOS-RJ).
- Travar o parser de preço (falta exemplo real de homologação/ata com tabela — SPEC §8).
- VACUUM/ANALYZE do compliance.db (só com sweep idle).

## Erros & Aprendizados (até aqui)
- **Construir scaffolding + medir no dado real > presumir.** O piloto revelou o título-numérico (P0.2) em vez
  de assumir que "classifica por título" funcionava — exatamente o tipo de "função sem sentido" que o dono
  pediu para evitar.
- **CPU:** sweep + suíte + Playwright juntos derrubaram a sessão (load 4,4). Serializar; checar load antes.
- **`data/*.out` é limpo por cron** — saída de teste importante vai p/ `/tmp` (estável), não `data/`.
