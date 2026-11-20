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
  - `[feito — §9.4]` `sei_reparar_vazios` (L219–231) lê o manifesto, faz OCR documento a documento (minutos) e regrava
    sem reler e sem atomicidade — o caso grave;
  - `[feito — §9.4]` `sei_refichar` (L66–87) lê o blob, ~60 s de LLM, grava sem reler: documentos que o sweep gravou
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

1. `[feito na fila e no trabalhador — §10; ligar: ver §10]` **Fila de OCR cega ao frio novo.** Desde 16/11 `sei_arquivo_frio.sh` grava em
   `vm2:~/arquivo_frio/sei_pdfs`; `sei_ocr_gpu_fila.pdfs_no_frio`, `sei_ocr_reserva`, o worker GPU
   (`deploy/itcampo/ocr_gpu/ocr_gpu_worker.py:182`), `ocr_cpu.sh` e `pool_nativo.py` leem
   `~/arquivo_frio/sei_cache`. **1.602 pastas** do índice `sei_arquivo_frio.jsonl` estão em `sei_pdfs`:
   os escaneados delas não entram na fila. O conserto atravessa `deploy/` e o it-campo (frente GPU
   1118-0004) — avisado no quadro.
2. `[feito em 5 — §9.1; restam sei_sweep.run_pais e sei_direcionamento_varre]` **OB do espelho TFE onde a regra é SIAFE com `_ob_paga`** (CLAUDE.md, NÃO REINVENTAR 1):
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
3. `[feito — §9.3]` **Treze réguas de "arquivado/completo/vazio"** (limiares 40, 50, 80, 200 bytes, 500 chars;
   `total_arvore` × `docs_na_arvore` para o mesmo fato) — `sei_integra_fila._arquivado_ok`,
   `_captura_vazia`, `manifesto_norm.captura_integra`, `sei_arquivar_do_cache._ja_arquivado`,
   `sei_triagem_pericia` (60% por arquivo em disco, conta órfão e etiqueta: falha de captura vira
   lacuna do processo), `sei_inventario_captura.textos_locais`… A fonte devia ser
   `manifesto_norm.captura_integra` + `acervo_texto.docs_com_conteudo`. Mexe na fila viva (frente 1113).
   Efeito já visível: processo descontaminado tem `total_arvore` contando as peças alheias e
   `_arquivado_ok` devolve False para sempre (recaptura eterna).
4. `[feito — §9.2/§9.3]` **"Cada documento citado veio?" não é perguntado na captura.** Nenhuma ferramenta de captura chama
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
6. `[feito em agentes e busca_credor — §9.5]` **Cortes por posição**: `sei_agentes_sweep` `[:60]` documentos e `relacionados_de(...)[:3]` (art. 117
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
8. `[feito na leitura dupla — §9.6; sei_ficha.MODELO_BARATO segue anotado]` **Custo**: `sei_leitura_dupla._gerar_cadeia_curta` faz `setdefault("FREE_LLM_ONLY", "cerebras,zai,cohere,gemini")`
   (Gemini desligado por cobrança; Cerebras fora desde 09/11) e `sei_ficha.MODELO_BARATO` diz "free tier
   generoso" — conferir billing antes de volume.

## 8. Fora do escopo  `[anotado]`

`sei_compactar.py`/`sei_fotos_frio.py`: nada do grupo duplica o que fazem. `sei_integra_fila.py` e
`sei_integra_vm2.py`: duas filas com regras diferentes (a da VM-2 tem tetos por fonte, `dinheiro`,
restritos e quarentena; a local não), 8 cópias de `replace("/", "_")`, 4 leituras de manifest à mão,
9 privados importados de um pelo outro. `fila_recaptura_por_parecer.py` grava a fila sem prefixo.

## 9. Rodada de 20/11/2026 (tarde) — itens 2, 3, 4, 6 e 8 do §7  `[feito]`

Prova: mesmo harness só-leitura (código BASE f7772701 × DEPOIS, `data/` real, `compliance.db` `mode=ro`); manifest
só gravado no 9.3, depois do ensaio, por `acervo_texto.mutar_manifesto` (reler-mesclar-gravar sob trava), pulando
pasta mexida há < 2 h. Nenhum acesso ao SEI/SIAFE.

### 9.1 OB do SIAFE pela régua `_ob_paga`
`correlacao_sei.pago_siafe_por_processo` (agregado, chave canônica `SEI-UUUUUU/NNNNNN/AAAA`, grafias do mesmo processo
somadas) e `obs_siafe_por_processos` (camadas de `ob_processo`, GD descontada; `obs_por_processo` virou seu atalho).
- Fila de íntegras (`_valor_por_processo`, logo `_fila_geral`, releitura e `montar_fila` da VM-2): processos com valor
  184.133 → **297.368**; soma R$ 41.133.302.204,77 → **R$ 173.525.473.114,10**; **116.762** processos saem do zero.
  Fila geral (285 cdp `.json` não arquivados): zerados 199 → 175; top 20 reordenado (1º: SEI-330001/000568/2025,
  R$ 76.286.238,23, antes fora do top). `montar_fila(300)` igual (as 300 vagas são de execução/indeterminado/bombeiros/
  dinheiro, esta já SIAFE). Releitura por OB: só OB paga do SIAFE (TFE e cancelada saíram); 5 dos 10 mudaram.
- `sei_leitura_dupla.pagamento_do_processo` (acervo, 10.777 processos): com OB 4.939 → **6.281**; total R$ 17,16 bi →
  R$ 63,16 bi; 24 processos só tinham OB no TFE (sem pagamento no SIAFE) e deixam de ter.
- `sei_arvore_build` (818 dossiês com ficha): com pagamento 356 → **443**; `total_pago` R$ 2.113.816.741,75 →
  R$ 3.983.847.323,58.
- `sei_zeros_por_causa` (painel `/api/fiscal/zeros_sem_causa`): `credor_generico.classificar_por_processo(so_pagas=True)`;
  valor da fila R$ 10.298.617.530,53 → **R$ 10.134.681.718,43**; sem causa R$ 8.371.704.937,33 → R$ 8.210.797.840,05;
  fornecedor R$ 2.396.610.065,41 → R$ 2.355.043.376,57 (contagens iguais: 7.339 zeros, 1.842 sem causa).
- `sei_analise_em_serie`: soma da fila R$ 14.708.396.626,49 → R$ 14.288.676.119,55 (com valor 5.193 → 5.237); credor
  dominante por valor, não `MIN(nome_credor)`.
- `[pendente]` `sei_sweep.run_pais --cnpj`, `sei_direcionamento_varre.total_pago`, `sei_sweep` L355 (`'Contabilizado'`).

### 9.2 Retomada da íntegra pelo `id_documento`
`sei_integra_completa.preparar_retomada`/`arquivo_retomado`/`registrar_dono`: `NNN.pdf` só fica no lugar se o dono
(manifesto anterior + `_retomada/donos.json`) é o documento atual da posição; o resto vai para `_retomada/<id>.pdf`
(nada apagado) e volta quando o seu documento aparece. Manifesto ganha `id_documento`; `sei_arquivar` só reaproveita
`.txt` cuja etiqueta é do mesmo título. Defeito reproduzido em lista sintética reordenada (teste).
Acervo real: 416.830 documentos com nº no título; 167.526 conferíveis pelo "código verificador" do próprio texto;
12.596 trazem outro verificador — **10.851 de documento de OUTRO processo** (anexo com cópia: portaria publicada,
contrato assinado antes — legítimo), **1.745 de um irmão** do mesmo processo (277 processos; suspeito, não provado) e
**30 com corpo idêntico ao do irmão** em **4 processos** (deslocamento constante: 070002/005517/2022, 070002/017819/2023,
070002/017821/2023, 260004/000355/2022) — PDF trocado provado. Os 4 já estavam em `sei_fila_captura`; marcados
`recaptura: PDF trocado` (motivo antigo preservado em `| antes:`), que `_fila_execucao` relê mesmo arquivado.

### 9.3 Conferência documento a documento — régua única
`manifesto_norm.conferir_documentos(pasta)`: cada documento veio (texto com teor ou imagem)? Faltantes com
`i/id_documento/numero_sei/titulo/motivo` (`nao_capturado`, `declarado_sem_teor`, `sem_conteudo`, `so_etiqueta`,
`sem_texto`); árvore = maior de `total_arvore`/`docs_na_arvore` menos peças alheias tiradas; `captura_completa` só com
árvore medida e nada faltando. Derivam dela: `captura_integra` (tamanho da árvore), `_arquivado_ok`, os dois
`_ja_arquivado`, `textos_locais`, `sei_triagem_pericia`, `pericia_tripla.captura_completa`; `sei_arquivar` grava a
conferência a cada arquivamento; `sei_arquivar --conferir-acervo [--gravar]`.
- Acervo (10.786 manifests): árvore medida 9.355 (1.431 sem medida); antes 2.635 com `captura_completa=True` →
  **7.497 completos** e **1.858 incompletos**; 422.079 documentos, 417.032 vieram, **5.047 faltantes identificados**
  (nao_capturado 3.292 · declarado_sem_teor 1.177 · so_etiqueta 578) e **42.661 faltando sem identificação** (árvore
  maior que o manifesto — quais, só pela árvore do cache `.zst`: sábado).
- Efeito nas réguas: `_arquivado_ok` 8.757 → 8.767 (+7 com teor no disco e `chars` velho; mais 3 pastas novas);
  `captura_integra` 8.131 → 8.124 (12 perdem: `total_arvore` agora conta, ex. 030001/045095/2024 com 169 de 292; 2
  ganham: descontaminados); `pericia_tripla` completos 5.481 → 5.539.
- Conferidos à mão: 270131/000548/2023 (65 de 65, completo); 030001/045095/2024 (169 de 292 — o cache diz
  `completo: False`, 123 sem identificação); 030001/020694/2025 (34 de 34 listados, faltam o i=12 "PD PDs zipadas
  (98511108)" e o i=30 "Fiscalização Mensal (93758868)" — `ok: False` no cache, sem PDF).

### 9.4 Reler-mesclar-gravar
`acervo_texto.mutar_manifesto` e `cache_arquivo.mutar_json` (trava `fcntl`, releitura, gravação atômica; não recriam
manifesto não-objeto). `sei_reparar_vazios` e `sei_refichar` passam por eles; `sei_arquivar` grava sob a mesma trava.
Teste com dois escritores concorrentes e reprodução do apagamento (falha no código base).

### 9.5 Corte "os N primeiros"
`sei_agentes_sweep`: processo inteiro e todos os relacionados inteiros; relacionado fora do acervo ou captura
incompleta → lacuna `*_leitura_parcial` (ausência não afirmada); lacunas do processo recalculadas a cada passada.
Amostra de 100 pastas (`--so-conta`, só leitura): processos com fiscal 32 → 34; lacuna do art. 117 afirmada **55 → 16**,
e 37 passam a sair como leitura parcial. Custo: 145 s → 909 s na amostra (lê os relacionados inteiros; o pai é
guardado entre processos) — não tem cron; varredura inteira estimada em ~1 dia de VM-1.
`sei_busca_mgs` devolve `fim_paginacao`/`parcial`; `sei_busca_credor` grava `com_resultado_parcial` e refaz com 25
páginas; `resolver_duplicidade_nf` não aceita "candidato único" de lista parcial. As 10 buscas anteriores (8
`com_resultado`, 2 `sem_resultado` — uma com 1 candidato) não sabiam se a lista era inteira: tratadas como parciais e
refeitas uma vez.

### 9.6 Custo da leitura dupla
Cadeia fechada `zai, cohere, openrouter` (teto mensal server-side / guarda `:free`), chamada provedor a provedor, sem
`FREE_LLM_ONLY` e sem cair na cascata geral; Gemini e Cerebras nunca; nenhum disponível → `indisponivel`.

### 9.7 Sábado (medido)
Cache `.zst` em `sei_pais`/`sei_arvore_build`/`sei_sweep`/`sei_reparar_truncados` (e `sei_integra_fila._fila_geral`,
que também só vê `cdp_*.json`); identificar os 42.661 faltantes pela árvore do cache; fila do OCR ver o frio da VM-2.

## 10. Fila do OCR vê o frio novo — item 1 do §7  `[feito · ligar: abaixo]`

**Medido (20/11 18h40, GPU do it-campo a 0% com "pendentes 0").** O frio tem TRÊS lugares, não dois: `vm2:~/arquivo_frio/sei_cache`
(15/11, 54.488 PDFs), `vm2:~/arquivo_frio/sei_pdfs` (desde 16/11, 274 pastas, 9.099 PDFs, 19 GB) e o disco do PRÓPRIO
it-campo `C:\JFN-Arquivo\sei_pdfs` (15–16/11, 1.019 pastas, 27.438 PDFs, 46 GB; 339 dessas entradas do índice com rc=12).
As "1.602 pastas" do índice somam as duas últimas. Fila (mesma régua `montar`, `foi_ocr`, sem nativo, sem aplicado):

| origem | documentos | pastas |
|---|---:|---:|
| antes (só `sei_cache` da VM-2) | 57 | 13 |
| + `sei_pdfs` da VM-2 | **4.830** (+4.773) | 226 (+213) |
| + disco do it-campo (`--itcampo-local`) | **14.749** (+9.919) | 1.007 |

**Como.** `sei_ocr_gpu_fila` lista `sei_cache` e `sei_pdfs`; o PDF que só mora em `sei_pdfs` ganha LINK FÍSICO em
`sei_cache/<mesmo caminho>` (mesmo disco: mesmo inode, zero byte, nada apagado nem sobrescrito; conferido por
`samefile`) antes de entrar na fila — o trabalhador VIVO da GPU, a reserva da VM-2 e os nós de CPU do it-campo leem
sem mudar uma linha nem reiniciar. `--medir` só conta. O trabalhador novo lê primeiro `C:\JFN-Arquivo\sei_pdfs` (sem
baixar), confere o md5 de cada `.ocr_gpu.*` nas duas pontas (como a reserva; só o conferido sai de `out/`) e tem
lote avulso (`OCR_BASE=… OCR_UMA_VEZ=1`). O disco do it-campo só entra com `--itcampo-local`: o trabalhador antigo
marcaria esses PDFs como falha. O integrador grava o manifesto por `acervo_texto.mutar_manifesto` (reler-mesclar
sob trava; trava ocupada → nada gravado nem registrado, `manifesto_ocupado`, volta na próxima).

**Lote real (20 documentos de 20 processos, só `sei_pdfs` da VM-2, 5 sem texto + 15 notas fiscais lidas pelo
Tesseract)**: link de 20/20; trabalhador novo avulso no it-campo, mesmo vLLM; 138 páginas em 162 s = **1,17 s/página**
(0 nativas, 0 falhas); entrega md5 20/20 conferida; integrador (sob trava) 2 preenchidos + 15 substituídos, 3 fotos
com < 40 caracteres não entraram (regra antiga: entrega apagada e não registrada).

**Conferência à mão (3 documentos contra a imagem)** — documento e página certos nos 3, mas:
- NFS-e de Cabo Frio (`020001_003960_2024` #0, R$ 100.033,95): o Surya devolveu BLOCOS VAZIOS (página torta, brasão)
  — sumiram razão social, CNPJ do prestador e a discriminação que o Tesseract tinha; valores e retenções certos.
- DANFE (`020001_000500_2025` #0, R$ 799.806,00): valores, datas, CNPJ do destinatário certos; bloco do emitente (CNPJ
  30.082.317/0001-85, chave) vazio.
- Planilha de refeições (`210108_000574_2023` #686, preenchida — antes 37 caracteres): estrutura certa, mas 4 números
  errados num scan ruim (ALMOÇO 1.548,20 por 1.649,20; total 2.553,90 por 2.553,60; 280 e 360 por 380) e tokens
  `<|30|>` vazados do modelo.
Nas 15 substituições, **4 de 28 CNPJ com DV válido sumiram (3 documentos)**. O bench de 18/11 (páginas nativas
"sujadas") não media bloco perdido. Guarda novo no integrador: substituição só entra se todo CNPJ com DV válido do
texto atual continua no novo (`mantido_perderia_cnpj`); as 3 substituições do lote foram desfeitas sob a trava (texto
do Tesseract de volta; registro `revertido_perderia_cnpj`). Preencher documento sem texto não muda.

**Ligar (dono):** (1) integrar os commits — a propagação `sei_ocr_gpu_fila` passa a pôr o `sei_pdfs` da VM-2 na fila
e o trabalhador VIVO já consome na próxima puxada (de hora em hora, quando a fila dele acaba); (2) para o disco do
it-campo: depois do `git pull` no `~/JFN-worker`, copiar `deploy/itcampo/ocr_gpu/ocr_gpu_worker.py` para
`C:\Users\iterj\` e encerrar SÓ o processo `ocr_gpu_worker.py` (o laço `jfn_ocr_gpu.ps1` relança em 120 s; o
`vllm_surya.sh` não reinicia o vLLM que está no ar); então acrescentar `--itcampo-local` ao comando de
`sei_ocr_gpu_fila` em `config/propagacao.yaml`. Antes do (2), a reserva da VM-2 não alcança o disco do it-campo
(falha → o item volta à fila da GPU).
**Pendente:** bloco vazio do Surya (o guarda só protege CNPJ; razão social/discriminação sem CNPJ podem sumir em
substituição) e o token `<|NN|>` no texto; foto com < 40 caracteres volta à fila para sempre.
