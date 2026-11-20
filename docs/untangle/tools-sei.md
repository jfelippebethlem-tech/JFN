# Decision log — untangle de `tools/sei_*` (20/11/2026)

Escopo: as 56 ferramentas `tools/sei_*.py` e os `.sh` delas (captura e arquivo das íntegras, sweeps e
filas, leitura e análise, OCR/manutenção/sessão/busca). Fora: `tools/sei_compactar.py` e
`tools/sei_fotos_frio.py` (recém-entrados, 16dc5863); `tools/sei_integra_fila.py` e
`tools/sei_integra_vm2.py` só anotados (frente aberta no quadro, 1113-1612). Escolhas do dono:
**Comentários = sim** (ficam medição datada, decisão do dono e norma), **Testes = não**. A porta do
acervo é a do untangle de `compliance_agent/sei` (`docs/untangle/sei.md`): `acervo_texto.RAIZ`,
`numero_para_pasta`/`pasta_para_numero`, `manifesto`, `declarados`.

Formato igual a `sei.md`: o fix fica acima dos problemas. `[feito]` = aplicado; `[pendente]` = precisa
do dono, muda número publicado, mexe em arquivo de outra frente ou tem risco de memória/CPU que pede
medição antes; `[anotado]` = só registro.

**Prova.** Nenhum acesso ao SEI/SIAFE. Cada lote rodou o código BASE (cópia de 1236606d com `data/`
apontando para o acervo e o banco reais) e o DEPOIS sobre o mesmo dado, só leitura (`compliance.db`
aberto `mode=ro`). Testes casados (158 arquivos: todo teste que cita `tools/sei_*` + catracas
`test_catraca_*`, `test_regra_*`, `test_divida_*`, `test_ferramenta_tem_quem_a_rode`,
`test_sei_contexto_unico`), rodados na VM-2: **antes 1.233 passam, 12 pulados, 1 falha** (a
`test_sei_contexto_unico`, conhecida — ver §6); **depois 1.232 passam, 12 pulados, 2 falhas**: a mesma
conhecida e `test_catraca_excepts::test_baseline_atualizada_quando_melhora`, que só pedia travar a
queda (baseline 1562 → 1536; local, com o índice final, a catraca passa).

## 1. Uma porta para achar a pasta do processo  `[feito]`

Toda ferramenta acha a pasta por `acervo_texto.numero_para_pasta`/`pasta_para_numero` e a raiz por
`acervo_texto.RAIZ`; os apelidos de módulo (`ARQUIVO`, `ACERVO`, `_ARQ`, `_certame_do_processo`,
`numero_da_pasta`) ficam, apontando para a porta (os testes os redirecionam).

Medido sobre 319.678 números reais da casa (OB SIAFE, `sei_fila_captura`, `sei_arvore`,
`lex_execucao`, `sei_ficha`, nomes do cache) e as 10.780 pastas do acervo:

- `sei_consultar._tag` trocava todo não-dígito por `_`: `SEI-270131/000548/2023` virava
  `____270131_000548_2023` e a ferramenta que o CLAUDE.md manda usar primeiro respondia **"processo não
  arquivado"** com o formato que a própria ajuda sugere. **9.996 números `SEI-` da casa só acham a
  pasta pela porta.** Conferido: a saída com e sem prefixo agora é idêntica (md5).
- `sei_arquivar_do_cache._slug_processo`, `sei_fila_por_dinheiro._slug`, `sei_zeros_por_causa._tem_arquivo`
  e `sei_ocr_gpu_fila.tags_risco_alto` (`replace("SEI-")`/`replace("/")` à mão): iguais para todo
  `SEI-…` bem formado; só a porta acha a pasta das **13** grafias minúsculas (`sei-080001/000744/2024`).
  No `arquivar_do_cache`, que CRIA a pasta, a cópia antiga criaria `sei_080001_…` ao lado da certa.
- `sei_confronto_llm` (`re.sub(\D)` sem colapsar): 24 números malformados mudam de nome; nenhum acha
  pasta antes nem depois.
- `sei_cpf_sweep`, `sei_ficha_acervo.numero_da_pasta` (split por `_`) e `sei_propostas_sweep._certame_do_processo`:
  iguais em 10.778 das 10.780 pastas; as duas fora do padrão (`_orfaos_residuo`, `SEI_330020_0007`)
  deixam de virar `SEI-/orfaos/residuo` e `SEI-SEI/330020/0007`.
- Raízes relativas ao DIRETÓRIO CORRENTE (`Path("data/sei_arquivo")`) em `sei_dossie_md`,
  `sei_analise_em_serie`, `sei_agentes_sweep`, `sei_inventario_captura`; raízes surdas a
  `JFN_SEI_ARQUIVO` em `sei_consultar` (tinha a sua própria leitura do env), `sei_arquivar_do_cache`,
  `sei_fila_por_dinheiro`, `sei_zeros_por_causa`, `sei_ficha_acervo`, `sei_propostas_sweep`,
  `sei_confronto_llm`. Iguais quando rodadas da raiz do repo (todas as chamadas de cron o fazem).

## 2. O cache comprimido existe  `[feito em 1 · pendente em 4]`

`manutencao.comprimir_cache_sei` guarda o blob lido como `cdp_*.json.zst`. Hoje: **2.353 `.json` contra
9.516 `.json.zst`** na raiz do cache (+958 em `_truncados/`). A leitura canônica é
`cache_arquivo.glob_cache`/`ler_json`/`nome_logico`.

- `[feito]` `sei_fila_por_dinheiro.levantar` montava "já lido" só com `cdp_*.json`: processo lido e
  comprimido virava **NUNCA TOCADO** (cron semanal; a fila vai para a VM-2). Só nomes, sem ler o blob.
  Base × depois no banco e acervo reais: arquivados 5.481 → 5.493 · lidos não arquivados **57 → 2.117**
  · nunca tocados 273.968 → 271.896 · dinheiro nunca tocado R$ 122.433.376.609,58 →
  **R$ 117.277.318.866,71** · recapturar 0 → **396 (R$ 194.539.576,79)**.
- `[pendente — medir pico de memória antes]` os quatro que LEEM o blob e só veem o `.json`:
  - `sei_pais.iter_resumos` (pais citados em `.zst` nunca detectados; pai já lido em `.zst` volta à fila);
  - `sei_arvore_build` (`CACHE.glob("*.json")`: `sei_arvore` — `total_pago`, `ultima_ob`, `encerrado` —
    não se atualiza para ~80% dos processos);
  - `sei_sweep._unidades_legiveis`; `sei_reparar_truncados.encontrar_truncados`;
  - e `sei_reader` ao reler o próprio cache (`:1081`, `:1225`) e `sei_sweep._ficha_e_storage`/`_salvar_cadeia_no_cache`
    (caminho `.json` cru; a cadeia pode criar um `.json` stub que passa a sombrear o `.zst`).
  Por que não feito: `sei_pais` já derrubou a VM por OOM (11× em 27/07) e limita por `st_size` — num
  `.zst` o tamanho em disco subestima o descomprimido; ligar os `.zst` quadruplica o volume lido no
  cron de 30 min do `sweep_sei.sh`. O conserto é o mesmo nos quatro (`glob_cache` + `ler_json`, limite
  pelo tamanho LÓGICO — `cache_arquivo._tamanho_logico` precisa virar público), mas pede uma rodada
  medida na VM-2.

## 3. O manifesto é lido pela régua, não por `bool()`  `[feito]`

`acervo_texto.foi_ocr(doc)` (nova): `str(doc.get("ocr")) == "True"` — a regra que `compliance_agent/acervo`
e `propostas_sei_extrair` já usavam.

- `sei_arquivar_do_cache` grava `"ocr": "True"/"False"`, `"chars"`/`"i"` e `"fotos": "[]"` como TEXTO
  (**6.640 manifests, 83.409 documentos**); `bool("False")` é verdadeiro. Três leitores erravam:
  `sei_ocr_gpu_integrar._posto` dava **posto 1 (Tesseract) a documento nativo** — o Surya podia
  substituir o texto do próprio PDF nas 229 dessas pastas que têm `integra_*` no cache —;
  `sei_ocr_gpu_fila.montar` os enfileirava como "tess"; `sei_resgatar_escaneados` (morta) os pulava.
  Com o frio aceitando tudo: fila **220.054 → 136.645** (−83.409, exatamente esses nativos); posto 4
  (nativo) 195.799 → 279.208.
- `[anotado]` o escritor continua gravando texto: trocar o formato do manifesto mudaria 6.640 arquivos
  e os leitores que já fazem `str()==`; a régua cobre os dois.

## 4. Gravação que apaga trabalho alheio  `[feito em 1 · pendente no resto]`

- `[feito]` `sei_inventario_captura` (cron diário, `fila_analise_sei.sh sigilo`) era o único dos sete
  escritores de `sei_fila_captura` com `INSERT OR REPLACE`: trocava `laudo de execução…`,
  `parecer cita…`, `busca_credor` por `nunca_capturado`, e o motivo é a prioridade em
  `sei_integra_fila` (`_fila_execucao`, `_MOTIVOS_EM_MASSA`). Agora upsert: valor/nº de docs/visto_em
  se atualizam; motivo só se for um dos três do inventário. Hoje **0** linhas mudariam (2.780
  conhecidos sem texto, chave exata) — a próxima gravação sai idêntica; conferido em banco de memória.
- `[pendente]` read-modify-write sem reler o disco ou sem tmp+rename:
  - `sei_reparar_vazios` (L219–231) lê o manifesto, faz OCR documento a documento (minutos) e regrava
    sem reler e sem atomicidade — o caso grave;
  - `sei_refichar` (L66–87) lê o blob, ~60 s de LLM, grava sem reler: documentos que o sweep gravou
    no intervalo somem;
  - sem atomicidade: `sei_arquivar` L372, `sei_arquivar_do_cache` L291/L298/L364,
    `sei_reparar_manifestos` L70/L108, `sei_descontaminar` L146, `sei_integra_vm2._tirar_da_fila`;
  - `sei_cpf_sweep` marca, `sei_analise_em_serie.gravar_indice_mesclado`, `sei_fila_por_dinheiro`
    SAIDA (lida pela VM-2), `sei_ocr_gpu_integrar` (manifest sem reler contra o `sei_arquivar`).
  Fazem certo e servem de molde: `sei_integra_completa._grava`, `sei_reconciliar_orfaos`,
  `sei_reparar_truncados._gravar_progresso`, `sei_restritos._save`, `sei_ocr_reserva` (`_Trava`).
- `[anotado]` `sei_fila_captura` tem **659 processos com duas linhas** (`SEI-030001/005302/2026`
  `nunca_capturado` × `030001/005302/2026` `parecer cita…`): `tools/fila_recaptura_por_parecer.py`
  (fora do escopo) grava sem o prefixo. A chave devia ser `pasta_para_numero(numero_para_pasta(x))`.

## 5. Defeitos de efeito no dado consertados de passagem  `[feito]`

- `sei_depurar_pdfs`: a releitura de segurança era `tmp.read_text() != texto`; `read_text` troca `\r`
  por `\n` e **26 de 57** nativos amostrados têm `\r` — nunca viravam `.txt`, eram reclassificados de
  hora em hora (log do `sei_arquivo_frio.sh`: 1.357–2.142 "nativos" por rodada, 0,00–0,06 GB) e
  iam para o frio como escaneados. Agora compara bytes.
- Culpa atribuída ao WAF em mensagem de diagnóstico: `sei_reader` ("login itkava não autenticou
  (WAF/credencial)") e `sei_busca_mgs` ("pode ser sessão caída, WAF…"). Os comentários históricos
  datados ("PROVADO ao vivo 2026-06-06 … vence o WAF") ficam — são memória do método.

## 6. Código morto  `[feito em parte]`

- `[feito]` `sei_proc_paginado.docs_da_pagina`/`clicar_proxima` e `MAX_PAG` (o próprio comentário dizia
  "substitui"); `sei_integra_completa.MAX_PAG` sem uso.
- `[feito]` para `tools/_arquivo/sei_debug_superado/` (convenção da casa; sem chamador em código,
  `crontab -l`, `deploy/`, `config/`, testes): `sei_docs_to_telegram` (lia o token do Telegram no
  import e enviava por fora do enviador da casa, sem conferir `message_id`), `sei_login_retry`
  (login e arquivo de estado próprios), `sei_reocr_backfill` (relia o SEI ao vivo).
- `[pendente]` mortas que só testes chamam (Testes = não, então ficam): `sei_compactar_cache` — **a
  única que APAGA PDF** (peças `integra_*/NNN.pdf`) contra a ordem "nada é apagado" —,
  `sei_comprimir_pdfs` (Ghostscript medido como pior pelo próprio `sei_arquivo_frio.sh`),
  `sei_resgatar_escaneados`. Também: `sei_pais.construir_denylist`/`_freq_relacionados`/`_cache_path`,
  `sei_arvore_build.arvores_encerradas`, `sei_ficha.extrair_ficha_producao`/`_chamar_cerebras`,
  `sei_reader.abrir_pesquisa`/`_dec_sei`, `sei_dossie_md._consolidacao_utilizavel`,
  `sei_analise_em_serie._gravar_indice`, `sei_sweep --diario`.
- `[anotado]` `sei_supervisor.sh` tem `exit 1` na linha 5, mas `rotas/sistema.py:359,731` ainda
  perguntam se está vivo. `sei_serie_continua.sh` não tem agendador e conta erro como progresso.
- `[anotado]` `test_sei_contexto_unico` falha antes e depois: só lê `sei_sweep.py`, onde sobrou um
  `await login(pg` (`run_recaptura`, L1535); os outros dois caminhos já usam `navegador_sei`+`entrar`.
  Fora do sweep, `sei_session` (viva, via `sei_busca_mgs`), `sei_proc_paginado`,
  `sei_processo_integral` montam contexto e UA à mão.

## 7. Pendente — por prioridade  `[pendente]`

1. **Fila de OCR cega ao frio novo.** Desde 16/11 `sei_arquivo_frio.sh` grava em
   `vm2:~/arquivo_frio/sei_pdfs`; `sei_ocr_gpu_fila.pdfs_no_frio`, `sei_ocr_reserva`, o worker GPU
   (`deploy/itcampo/ocr_gpu/ocr_gpu_worker.py:182`), `ocr_cpu.sh` e `pool_nativo.py` leem
   `~/arquivo_frio/sei_cache`. **1.602 pastas** do índice `sei_arquivo_frio.jsonl` estão em `sei_pdfs`:
   os escaneados delas não entram na fila. O conserto atravessa `deploy/` e o it-campo (frente GPU
   1118-0004) — avisado no quadro.
2. **OB do espelho TFE onde a regra é SIAFE com `_ob_paga`** (CLAUDE.md, NÃO REINVENTAR 1):
   - `sei_integra_fila._valor_por_processo` soma `ordens_bancarias` sem `_ob_paga` e ordena a fila
     geral, a releitura (`[:10]`) e a fila exportada à VM-2. Medido: TFE tem 184.133 processos, o SIAFE
     pago 279.504; **96.482 processos com OB paga no SIAFE têm score 0** nessa fila (frente 1113).
   - `sei_leitura_dupla.pagamento_do_processo` (árbitro `_ob_arbitra`) e `sei_arvore_build`
     (`total_pago`, `ultima_ob`, `encerrado`) via `correlacao_sei.obs_por_processo` — só TFE.
   - `sei_zeros_por_causa` usa `status='Contabilizado'` (cópia divergente de `_ob_paga`: entram erro
     no pagamento, complementar, reemitida) — número no painel (`/api/fiscal/zeros_sem_causa`).
   - `sei_analise_em_serie._pagos_por_chave`/`natureza_do_pagamento` somam sem filtro de status e
     escolhem o credor por `MIN(nome_credor)` (defeito que a fila por dinheiro já corrigiu); vai para a
     nota do vault e o `sei_reindiciar` propaga.
   - `sei_sweep.run_pais --cnpj` tira o universo de `ordens_bancarias` e, sem casamento, `or pais`
     devolve TODOS os pais em silêncio.
   - `sei_direcionamento_varre.total_pago` é soma de valores da ficha, não OB.
   Mudam número publicado: precisam do ok do dono.
3. **Treze réguas de "arquivado/completo/vazio"** (limiares 40, 50, 80, 200 bytes, 500 chars;
   `total_arvore` × `docs_na_arvore` para o mesmo fato) — `sei_integra_fila._arquivado_ok`,
   `_captura_vazia`, `manifesto_norm.captura_integra`, `sei_arquivar_do_cache._ja_arquivado`,
   `sei_triagem_pericia` (60% por arquivo em disco, conta órfão e etiqueta: falha de captura vira
   lacuna do processo), `sei_inventario_captura.textos_locais`… A fonte devia ser
   `manifesto_norm.captura_integra` + `acervo_texto.docs_com_conteudo`. Mexe na fila viva (frente 1113).
   Efeito já visível: processo descontaminado tem `total_arvore` contando as peças alheias e
   `_arquivado_ok` devolve False para sempre (recaptura eterna).
4. **"Cada documento citado veio?" não é perguntado na captura.** Nenhuma ferramenta de captura chama
   `conferencia_captura.conferir`; quatro marcas para "não veio" (`nao_capturado`,
   `declarado_sem_teor`, `sem_conteudo`, lacuna `captura_truncada`) e só a primeira entra em
   `nao_capturados`. A retomada do `sei_integra_completa` (L304) é POSICIONAL (`{i:03d}.pdf`) sobre
   uma enumeração que a própria docstring diz não ser determinística: pode colar o PDF de um documento
   no título de outro ("6 de 7 PDFs errados" medido pelo `sei_reparar_vazios`). Chavear por
   `id_documento` é o pedido do dono — mexe no fluxo vivo de captura.
5. **Leitura do acervo à mão** (órfãos + etiqueta para regex e IA): `sei_confronto_llm.texto_do_processo`
   (alimenta toda a leitura dupla; corte por ordem de nome de arquivo, embora a docstring diga "do mais
   informativo"), `sei_consultar._ler_texto` (o `--grep` casa a etiqueta), `sei_cpf_sweep`
   (`texto/*.txt` com órfãos), `sei_ficha_acervo._bytes_texto`, `sei_dossie_md._maiores`. Trocar por
   `acervo_texto.declarados` + `ler` muda texto que vai à IA e os placares: pede rodada comparada.
6. **Cortes por posição**: `sei_agentes_sweep` `[:60]` documentos e `relacionados_de(...)[:3]` (art. 117
   falso — o mesmo defeito que `relacionados.textos_do_relacionado` já corrigiu), `sei_ficha._prompt`
   `texto[:4500]`, `sei_processo_integral` `[:500]` com PDF dizendo "instrução completa",
   `sei_integra_fila._fila_inscrita` `LIMIT limite*4` antes do filtro, `sei_direcionamento_llm` (três
   árvores por número, não por valor), `sei_busca_credor`/`sei_busca_mgs` (teto de páginas gravado
   como `com_resultado` final, `n_total` = colhido — o resolvedor pode aceitar "candidato único" de
   lista cortada).
7. **Falha que vira "não tem"**: `sei_analise_em_serie` grava `{"erro": …}` no índice e o processo
   nunca é refeito; `sei_direcionamento_llm` congela `pendente_*` por 30 dias; `sei_sweep._unidades_sem_acesso`
   pula uma unidade inteira para sempre após 6 zeros (antes até dos enfileirados à mão) e o comentário
   chama isso de "falta de ACESSO"; `sei_reader._montar_resultado_cracked` grava `cdp_*.json` sem as
   guardas de leitura truncada/caixa do caminho normal; `sei_descontaminar._integra` só aceita o
   manifesto de cache no formato lista antigo; `sei_restritos` tem `REPO=/home/ubuntu/JFN` cravado
   (no worker da VM-2 o registro diverge do que `sei_integra_vm2` lê).
8. **Custo**: `sei_leitura_dupla._gerar_cadeia_curta` faz `setdefault("FREE_LLM_ONLY", "cerebras,zai,cohere,gemini")`
   (Gemini desligado por cobrança; Cerebras fora desde 09/11) e `sei_ficha.MODELO_BARATO` diz "free tier
   generoso" — conferir billing antes de volume.

## 8. Fora do escopo  `[anotado]`

`sei_compactar.py`/`sei_fotos_frio.py`: nada do grupo duplica o que fazem. `sei_integra_fila.py` e
`sei_integra_vm2.py`: duas filas com regras diferentes (a da VM-2 tem tetos por fonte, `dinheiro`,
restritos e quarentena; a local não), 8 cópias de `replace("/", "_")`, 4 leituras de manifest à mão,
9 privados importados de um pelo outro. `fila_recaptura_por_parecer.py` grava a fila sem prefixo.
