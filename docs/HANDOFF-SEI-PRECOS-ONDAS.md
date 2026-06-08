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
- **Onda D — paralelizar enrichers OSINT do render** (opensanctions/aleph/midia/links são sequenciais no
  `render_pdf_html`); ganho de rapidez. Pura, sem browser.

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
