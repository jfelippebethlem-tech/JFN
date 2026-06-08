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

## ✅ BLOQUEADOR REINVESTIGADO (2026-06-08) — o reader FUNCIONA; o "0 docs" era diagnóstico errado
**Depurado ao vivo (login itkava/ITERJ via chromium próprio, que vence o WAF; o Chrome `:9222` NÃO serve p/ SEI —
WAF derruba a conexão dele, `ERR_CONNECTION_CLOSED`).** Resultado decisivo:
- **`SEI-520003/000026/2025` → 8 docs + conteúdo + 1 CNPJ + 1 valor.** O reader busca→abrir **funciona** para
  processos no **escopo de acesso da ITERJ**. (A URL final `procedimento_controlar` é normal — a árvore vive num
  frame-filho.)
- **`SEI-520002/001366/2025` → 0 docs, SEM cadeado, SEM texto de restrição.** Screenshot (ground truth) mostrou
  **"Nenhum resultado encontrado"** no rodapé da busca. **Não é "busca não resolve" (premissa antiga ERRADA), nem
  timing, nem acesso restrito:** o processo simplesmente **não é localizado pela busca autenticada da ITERJ** —
  porque é de **outra unidade** (520002) que nunca tramitou pela ITERJ (escopo de acesso do SEI) e/ou o `numero_sei`
  da OB é **ruidoso**.
- **Bug pequeno corrigido:** o detector `_JS_TEM_RESULTADO` (sei_cdp) procurava `nenhum registro`/`não encontrado`,
  mas o texto real do SEI-RJ é **"Nenhum resultado encontrado"** → não casava. Agora casa, e `navegador` retorna
  `motivo_zero=nenhum_resultado` (honesto: processo não localizado/acessível), distinto de `busca_nao_resolveu`.
- **Tentativa que REGRIDIU (revertida):** forçar o modo "Processos" clicando o rótulo "Processos" — clicava o item
  de **menu** "Processos" (vai p/ `procedimento_controlar`) e zerou o caso bom (520003→0). REVERTIDO. Se um dia
  quiser fixar o modo da busca, mirar o **radio real** dentro do form, nunca o texto "Processos" (colide com o menu).

**Implicação ESTRATÉGICA p/ o sweep (corrige o plano):** **NÃO** dá para varrer os 41k `numero_sei` às cegas pela
ITERJ — só rende para processos **no escopo da ITERJ**. Próximo passo certo (Onda 2): alimentar o reader pela
**cadeia `relacionados`** a partir de processos JÁ no escopo, e/ou um login de unidade com acesso mais amplo, e/ou
a **pesquisa pública** do SEI. `numero_sei` ruidosos ("0", "000 048 0 26") são descartados de saída.

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

---
# MAPA DETALHADO — estado, arquivos, comandos, validações (para retomar sem repetir nada)

## Commits desta frente (branch `sei-precos-onda5`, base `linux`)
- `89273dd` Onda A scaffolding SEI (na linux) · daí pra frente na branch:
- `46d2bf9` Onda F coletor receita TFE · `5c710e6` Onda C validada (tipo do doc) ·
- `e48deff` índice compacto `sei/indice.py` · `d9f3743` captura processos relacionados ·
- `fcbcd62` política valor_doc/parecer_juridico · `d8a807e`+`3c11d69` detector conluio (+fix) ·
- `a7b3735` cadeado (ícone) de acesso restrito · `8a8b102` /lista gerado da skilltree (na linha de base).
  (`git log --oneline linux..sei-precos-onda5` p/ ver tudo.)

## Arquivos criados/alterados (o que cada um faz)
- `compliance_agent/sei/navegador.py` — `abrir_processo(numero)` reusa o leitor itkava (`sei_cdp.ler_processo_sei`),
  devolve `{ok, docs:[DocSEI(titulo=TIPO,tipo_bruto=número,url,formato,conteudo)], relacionados:[{numero,titulo,url}],
  acesso_restrito, cadeado, n_docs_restritos, motivo_zero, texto, cnpjs, valores}`. `baixar(doc)`=texto.
- `compliance_agent/sei/classificador_doc.py` — `classificar_doc(titulo)` (parecer_juridico, homologacao, ata_rp,
  contrato, mapa_lances, planilha_preco, pesquisa_precos, etp, tr, edital, empenho, liquidacao, autorizacao_despesa,
  tramitacao, outros). `tem_preco`, `valor_doc`(alto|medio|baixo), `deve_guardar_texto`.
- `compliance_agent/sei/extrator_precos.py` — `extrair_itens(conteudo, gerar=, ver_imagem=)` → (itens, metodo, conf);
  camadas tabela(pdfplumber)→llm_texto→visao; honesto ('falha',0).
- `compliance_agent/sei/conluio_propostas.py` — `detectar(propostas)`: markup_uniforme / precos_identicos /
  texto_similar (bid-rigging).
- `compliance_agent/sei/indice.py` — SQLite `data/sei_indice.db` (sei_processo/documento/relacionado/item_preco);
  `persistir(...)`, `ja_indexado(numero)`, `stats()`, `podar_cache(horas)`. ~1-3 KB/processo.
- `compliance_agent/collectors/tfe_receita.py` — `baixar()/parsear()/ingerir()` da receita mensal (CKAN tfe-receita).
- `collectors/sei_cdp.py` + `tools/sei_reader.py` — JS `_JS_LE_ARVORE_E_TEXTO` agora separa documentos×relacionados,
  captura tipo (title/aria-label/nó pai) e cadeado (ícone). Propagam relacionados/cadeado/n_docs_restritos.
- `tools/pilot_sei_avaliar.py` — piloto: `--processos "a,b"` ou `--auto`; salva árvores em `data/pilot/calibracao/`.
- Testes: `tests/test_jfn2_sei.py` (11), `_sei_indice.py` (2), `_conluio.py` (5), `_receita.py` (2). **Suíte total verde.**

## Comandos úteis
- Piloto SEI: `cd ~/JFN && PYTHONPATH=. .venv/bin/python -m tools.pilot_sei_avaliar --processos "SEI-..,SEI-.."`
  (rodar em background + guardar load; ver `data/pilot/ultimo_pilot.json` e `data/pilot/calibracao/arvore_*.json`).
- Receita: `python -c "from compliance_agent.collectors import tfe_receita as R; print(R.ingerir())"` (SÓ com sweep idle).
- Índice SEI: `python -c "from compliance_agent.sei import indice; print(indice.stats())"`.

## ⚠️ VALIDAÇÕES AINDA PENDENTES (heurísticas a confirmar em leitura ao vivo, quando CPU baixa)
1. **Reader busca→abrir** ✅ RESOLVIDO/REINVESTIGADO (2026-06-08): o reader FUNCIONA p/ processos no escopo ITERJ
   (520003→8 docs). O "0 docs" do 520002 = **"Nenhum resultado encontrado"** = fora do escopo de acesso/nº ruidoso,
   não bug do reader. Ver seção "BLOQUEADOR REINVESTIGADO". Confirmação pendente do escopo-vs-modo exige 1 leitura
   de processo que SE SABE estar no escopo ITERJ porém com o form em modo "Documentos" (não testei limpo).
2. **Tipo do doc** (Onda C) — validado nos SRP (NE/NAD/Despacho/Recibo/Ofício/Anexo) ✅, mas pouca variedade
   (faltou ver homologacao/ata_rp/parecer_juridico reais → ler um processo de LICITAÇÃO).
3. **relacionados** e **cadeado** — código pronto + testes mockados, mas NÃO confirmados em processo real
   (cache antigo não tem; leitura fresca deu 0 docs). Confirmar quando o reader (item 1) funcionar.

## SEQUÊNCIA DE RETOMADA recomendada
(1) checar load/sweep · (2) DEBUGAR o reader busca→abrir (item 1) — sem isso nada do SEI escala ·
(3) com o reader OK, ler ~10 processos de LICITAÇÃO recentes (Lei 14.133) e validar tipo/relacionados/cadeado/ARP ·
(4) achar 1 ARP com tabela → travar `extrator_precos` (calibrar mapa de colunas/prompt) ·
(5) ligar a cadeia: da OB→numero_sei→processo→relacionados→pregão→ARP→itens; persistir em `sei_indice.db` ·
(6) sweep incremental das OBs (resumível via `indice.ja_indexado`), guarda de CPU sempre ·
(7) rodar `conluio_propostas.detectar` sobre os itens por licitação · (8) ingerir receita + cruzar receita×despesa×LOA.

## Depende do dono
Spec `JFN-SPEC-AVALIARGASTOS-RJ` (p/ gastos/avaliargastos) · `/lista` fast-path no gateway (bot vivo) ·
(chaves Aleph/OpenCorporates: o dono coloca quando/se liberarem — NÃO rastrear).
