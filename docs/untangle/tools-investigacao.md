# Decision log — untangle de `tools/` das famílias de investigação e dados (20/11/2026)

Escopo: os ~217 `tools/*.py` de investigação/dados (`pcrj_*`, `siafe_*`, `pericia_*`, `lex_*`, `fachada_*`,
`screen_*`, `sweep_*`, `relatorio_*`, `socios_*`, `resolver_*`, `lentes_*`, `empresas_*`, `coletar_*`, `siga_*`,
`bombeiros_*`, `auditar_*`, `varredura_*`, `processo_*`, `padroes_*` e os avulsos). Fora: `sei_*`, `painel_*`/`v6*`/
`gen_*`/`hermes_*`/`vm2_*`/`enviar_*`/`gerar_*`/`backfill_*` (outro agente) e `eleicao2026_*`/`tse_*` (não tocados).
Escolhas do dono: **Comentários = sim** (ficam medição datada, decisão do dono, norma), **Testes = não podar**.
Restrições: nenhuma coleta real (SIAFE/SEI/sites); validação só-leitura sobre `data/compliance.db`; sem LLM pago.

Formato igual a `raiz.md`: o fix fica acima dos problemas que resolve. `[feito]` = aplicado nesta passada;
`[pendente]` = muda número/saída, pede decisão do dono ou é redesenho; `[anotado]` = registrado só.

Ponto de partida: as ferramentas já importam o pacote (`from compliance_agent…` em 209 de 217) — a ideia de que
"`tools/` não importa o pacote" (raiz §3/§10) não vale para esta família; a fonte única é alcançável daqui.

Testes casados (26 arquivos + catracas `test_moeda_padrao_brasileiro`, `test_divida_except_pass`,
`test_regra_catracas`, `test_ferramenta_tem_quem_a_rode`): **antes 312 passed / 3 skipped; depois 312 / 3**.
Extras dos lotes 3–6 (10 arquivos: lentes, bateria, benefícios, CPF, catraca de excepts): ver §7.

## 1. R$ sai sempre pela régua da casa (`reporting/intel_base.moeda`/`reais`)  `[feito]`

- **Defeito — R$ no padrão americano** (lote 1). A catraca `test_moeda_padrao_brasileiro` só pega `:,.2f` na mesma
  linha do `R$`; `:,.0f`, `:,.1f` e o valor sem `R$` na linha passavam. Saíam `R$ 1,234,567`:
  - `bombeiros_alerta_telegram` — **mensagem ao Telegram do dono** (`R$ {val:,.0f}`);
  - `pericia_obras` (tabela md "R$ contrato"; com `valor_contrato` NULL levantava `TypeError` — agora `n/d`),
    `fachada_vet_progressivo` (anotado, não tocado: script datado de 24/06 com caminhos fixos e sem caller);
  - logs: `fachada_b2_sync` (2: tabela HTML e log), `fachada_streetview_sweep`, `fachada_visual_sweep`,
    `enriquecer_favorecidos_top`, `cadastro_enrich_sweep`, `tac_ranking_ugs` (`mi` com `:,.1f`).
  Todos passam por `moeda`. A catraca NÃO foi ampliada: no pacote ainda há ~14 linhas `R$ {x:,.0f}` (algumas
  em título de alerta — `rules/engine.py:793`, `cruzamentos_intel.py:602`), e título não muda nesta passada (§8).
- **Cópias do formatador** (lote 2): 15 funções/expressões com o mesmo `f"{v:,.2f}".replace(",", "X")…` passam a
  importar `moeda`/`reais` com o nome local que já tinham (nenhuma linha de uso muda): `cerebro_sync.brl`
  (mantém `n/d` para `None`), `dossie_emendatio._brl`, `emendas_pericia._brl`, `pcrj_pericia_gastos._brl`,
  `relatorio_bombeiros.brl`, `pcrj_emergencia_incumbente` (inline), `sweep_emergencia_recorrente._moeda`,
  `pcrj_ocp_redflags._brl`, `resolver_duplicidade_nf._br`, `relatorio_contrato_mobiliza_iterj.brl`,
  `relatorio_trajetoria_financas_rj.brl` (o parâmetro `casas` nunca era passado), `sweep_fracionamento_tcerj`
  (lambda), `lex_execucao._bloco_siafe` (inline).
- Medição: as 5 variantes antigas (com/sem `or 0`, com/sem `R$`, `n/d`) × régua nova sobre 1.880 valores
  (1.371 `valor` reais de `ob_orcamentaria_siafe`, 500 aleatórios ±1e10, bordas 0/−0,004/0,005/999,995/1e12/
  None): **0 diferenças**. Única mudança possível: entrada `None` nas cópias SEM `or 0` deixa de levantar
  `TypeError` e vira `0,00` — nos 7 lugares tocados a entrada é soma/valor numérico (conferido no código).
- Ficam `[anotado]`: cópias em scripts que NÃO importam o pacote e rodam como `python tools/x.py` sem
  `PYTHONPATH` (`_triagem_bombeiros.br`, `comparar_releitura._moeda`, `siga_pca`, `flags_graves`,
  `lista_suja_mte`) e as que levantam em `None` onde virar `0,00` seria INDISPONÍVEL → 0
  (`triagem_amarelos._brl`, `relatorio_engeprat_yoda.brl`). Saída já é BR; só a cópia fica.

## 2. "Só dígitos" é `cpf_cnpj.digitos`  `[feito]`

- Lote 3: `fila_recaptura_por_parecer._norm`, `ingerir_cpf_oficial._digitos`, `lentes_pcrj_execucao._digitos`,
  `lex_aprendizado_cruzado._norm`, `lex_pesquisa_internet._norm_cnpj` e `cerebro_sync.digits` (lote 2) eram
  `re.sub(r"\D", "", …)` com nome próprio → `from compliance_agent.cpf_cnpj import digitos as <nome>` (o nome
  fica: `lex_pesquisa_internet` é importado por `compliance_agent/lex.py`). Corpo idêntico para texto; para
  não-texto a cópia `c or ""` levantava `TypeError`, a régua converte. Um `import re` ficou sem uso e saiu.
- Ficam `[anotado]`: ~40 `re.sub(r"\D", …)` inline (expressão, não função) em `lentes_pcrj*`, `pago_a_sancionado`,
  `porte_incompativel`, `fachada_*`… e `gabarito_claude._so_digitos` (módulo sem import do pacote).

## 3. Caminho do banco pela porta da casa (`collectors/arquivos`), não pelo diretório corrente  `[feito]`

- Lote 4, mesmo desenho de `raiz.md` §4: constante de módulo → `dir_dados() / …`; `JFN_DB` com cauda relativa →
  `caminho_db()` (mesma ordem: JFN_DB > JFN_DATA_DIR > `<repo>/data`).
  - `Path("data") / …`: `beneficios_sweep`, `desmascarar_cpf_externo` (banco e `cpf_fila_humana.json`),
    `ingerir_cpf_oficial`, `resolver_cpf_socios`, `sweep_sede_google`, `dd_sweep_orgao`/`endereco_sweep` (`dd_sweep/`);
  - `"data/compliance.db"`: `fracionamento_dispensa_pcrj`, `sweep_integra_contratos_pcrj`, `ocr_contratos_imagem`,
    `pncp_backfill_unidade` (no `__main__`);
  - `os.environ.get("JFN_DB", "data/compliance.db")`: `fracionamento_siafe_sweep`, `sweep_emergencia_recorrente`
    (dois `import os` ficaram sem uso e saíram).
- **Cópia do padrão de outro módulo:** `lentes_pcrj` (13×), `lentes_pcrj_contrato` (9×), `lentes_pcrj_execucao` (7×)
  e `bateria_pericia` repetiam `conectar(db_path or "data/compliance.db")` — o literal é o `DB` de
  `compliance_agent.pcrj.universo`, dono de `conectar`. Passam a usar `universo.DB` (29 literais → 1). O próprio
  `universo.DB` continua relativo ao cwd (§8, área `pcrj/`).
- **Defeito (cwd):** chamados de fora da raiz, abriam/criavam `data/…` relativo ao cwd. Medido com
  `JFN_DATA_DIR=/home/ubuntu/JFN/data` e cwd `/home/ubuntu`: os 9 caminhos conferidos resolvem para o banco real
  (`exists=True`); a regra antiga resolveria `/home/ubuntu/data/compliance.db` (inexistente). Em produção nada muda
  (cron faz `cd ~/JFN`; serviços exportam `JFN_DATA_DIR`).
- `relatorio_contrato_mobiliza_iterj` tinha `REPO = Path("/home/ubuntu/JFN")` fixo → `Path(__file__).parents[1]`.

## 4. Fila do `sweep_sede_real` pela régua `intel_base.SQL_FAVORECIDO_PJ`  `[feito]`

- **Defeito medido (compliance.db real, 20/11):** `_alvos` escolhia "fornecedor PJ" por `LENGTH(favorecido_cpf)=14`
  — o CPF mascarado do espelho (`999.***.***-99`) também tem 14 caracteres (286.869 linhas de `ordens_bancarias`).
  Fila pendente: **24.767 → 199**; os 24.568 mascarados iam todos para `perfil_sede` e saíam como "fora da base
  (INAPURÁVEL)" — trabalho jogado fora e um contador de inapurável inflado ~120×. Top 500 por valor (`--top`/
  `--refazer`): nenhum mascarado, saída igual. Mesmo defeito de `raiz.md` §7.
- `socios_dump_sweep._receb_raiz` e `sweep_sede_google._alvos` usam o mesmo filtro, mas o mascarado nunca casa no
  JOIN seguinte (raiz `123.***.` × `cnpj_basico`; `ef.cnpj` de 14 dígitos) — sem efeito na saída; `[anotado]`.

## 5. OB paga só pela régua `cruzamentos_intel._ob_paga`  `[feito]`

- `relatorio_contrato_mobiliza_iterj` filtrava "paga" à mão (`status.startswith("contabiliz")` e
  `status LIKE 'Contabiliz%'`) — cópia sem 'Erro no Pagamento', 'Pagamento Complementar' e OB reemitida.
- **Defeito medido:** no par ITERJ × Mobiliza (106 OB, R$ 8.847.780,70) nada muda; em "outras UGs do mesmo credor"
  a cópia contava **2025OB05565** (UG 243200, R$ 56.560,57, `status_envio='Erro no Pagamento'`, devolvida pelo
  banco) como paga: 138 OB / R$ 34.259.506,90 → **137 OB / R$ 34.202.946,33**.

## 6. Tabelas normativas copiadas  `[feito]`

- `fracionamento_dispensa_pcrj` (docstring) trazia uma tabela de tetos do art. 75, II que divergia de
  `limites_dispensa.LIMITES` (2023 = 59.906,02 "Dec. 11.317" — é 57.208,33; 2026 = 62.725,59 "fallback" — é
  65.492,11, Dec. 12.807). O código já usava `limite_dispensa`; a docstring passa a apontar a fonte única.
- `agente_publico_reverso.e_estatal`: `("2011", "2038")` → `credor_institucional.NATUREZA_ESTATAL` (o corte
  "1xxx + estatal, e PARA AÍ" é deliberado e fica; só o literal vem do dono). Pendência §10 de `raiz.md` fechada.
  Conjuntos iguais; só `in` é usado.

## 7. Validação

- Testes casados, antes × depois (mesmo conjunto): 312 passed / 3 skipped → 312 / 3 (lotes 1–2) e →
  312 / 3 (lotes 3–6). Extras (10 arquivos): base 117 passed / 6 skipped → 119 / 4 (as 2 de `test_catraca_excepts` pulam na cópia-base, que não tem
  repositório git; as 4 de `test_bateria_pericia` pulam nos dois lados — `compliance.db` ausente na árvore de teste).
  `agente_publico_reverso` + 3 casados: 58 passed / 1 skipped → 58 / 1.
- `ruff check` (config da casa) limpo em todos os arquivos tocados.
- Ensaio só-leitura com o código novo: `relatorio_contrato_mobiliza_iterj.dados()` e `sweep_sede_real._alvos()`
  sobre o banco real reproduzem os números de §4–§5.

## 8. Pendências por prioridade  `[pendente]`

1. **OB do espelho TFE somada como "pago"** (CLAUDE.md: OB é sempre SIAFE): `dossie_emendatio` (4 somas; o texto diz
   "pagamentos efetivos"), `relatorio_bombeiros` (`ob_ano`, `top`, `tot_ob`), `relatorio_engeprat_yoda` (rotula
   `ordens_bancarias` como "SIAFE"), `scorecard`, `fachada_b2_sync` (UG por valor), `sweep_sede_google`/
   `sweep_sede_real`/`socios_dump_sweep` (ordenação por recebido), `lex_aprendizado_cruzado`, `tac_ranking_ugs`
   (régua do TAC — mesma pendência de `detectores.md`/`reporting.md`). Migrar muda número publicado; os três
   primeiros são relatórios de caso datados (rodam à mão) — decisão do dono se refaz ou só marca "espelho TFE".
2. **Catraca de moeda cega a `:,.0f`/`:,.1f`**: ampliar `PLACEHOLDER` pede antes consertar ~14 linhas do pacote,
   algumas em título de alerta (mudar título = decisão do dono, regra da casa).
3. **`compliance_agent.pcrj.universo.DB = "data/compliance.db"`** relativo ao cwd — default de `conectar`, agora a
   única cópia (área `pcrj/`).
4. **Ferramentas sem nenhum chamador** (código, shell, yaml, crontab, systemd), conferido por script: `_triagem_bombeiros`,
   `audit_fairness_pericia`, `benchmark_runner`, `check_gemini_key`, `comparar_releitura`, `comprimir_master`,
   `cruza_contratados_ajovem`, `direcionamento_telegram`, `endereco_sweep`, `enriquecer_favorecidos_top`,
   `express_ponte`, `extrai_folha_ajovem`, `fachada_vet_progressivo`, `flexvision_cdp`, `grupo_por_dominio`,
   `ingerir_cpf_oficial`, `ingest_cache`, `ouro_pareceres`, `pcrj_d7_verificar`, `pericia_ppp_souza_aguiar`,
   `pncp_backfill_unidade`, `postos_contratados`, `reavaliar_truncados`, `relatorio_bombeiros`,
   `relatorio_engeprat_yoda`, `relatorio_trajetoria_financas_rj`, `resolver_endereco_imagem`, `scorecard`,
   `screen_fornecedor_generalista`, `screen_perdedor_contumaz`, `siafe_sweep_ugs`, `siafe_ug_index`,
   `sweep_sem_google`, `vereditos_para_rag`. Só com teste: `baseline_achados`, `calibrar_indice`, `confronto_caso`,
   `experimento_ia_fraca`, `fotos_acervo`, `gabarito_claude`, `itcampo_degraus`, `memoria_indice`,
   `pericia_agentes_aplicar`. Quase todos são CLI de uso manual ou relatório de caso datado; podem rodar na VM-2/
   it-campo. **Não apagados** — decisão do dono (conferir as outras máquinas antes).
5. **`except: pass` mudo**: 39 no escopo (catraca global 150). Benignos em maioria (leitura de JSON de estado,
   `os.nice`, `/proc/meminfo`); a observar: `pericia_bombeiros_reconcilia:45` (`except Exception` para "tabela
   inexistente" engole também `database is locked`), `pos_sweep_analise._q` (erro vira `[]` e o `[0]` seguinte
   levanta `IndexError` — o "vazio" nunca chega a ser honesto), `pericia_aprendizado:146`.
6. **Máscara de CPF fora do formato PAD-04**: `cruza_contratados_ajovem.mask` dá `***456789**` (mesma janela 4–9, sem
   pontuação); `dossie_emendatio` exibe `cpf_mask[-4:]`. Trocar por `mascarar_cpf` muda o que o dossiê mostra.
   `desmascarar_cpf_externo._mask` monta PAD-04 a partir dos 6 dígitos do QSA — correto, não é cópia.
7. Caminhos fixos `/home/ubuntu/JFN` em scripts de caso (`bombeiros_alerta_telegram`, `digest_diario`,
   `garantir_obs_iterj_mgs`, `fachada_vet_progressivo`, `_triagem_bombeiros`, `criar_vm_oracle2`,
   `extrair_primarios_v3`): rodam só nesta VM; anotados.
8. `eleicao2026_*`/`tse_*`: fora do escopo por ordem do dono — não lidos nem tocados.

## 9. Riscos

- §1: quem lia os logs/Telegram com o número no formato antigo vê `R$ 1.234.567,00` (duas casas onde havia zero).
- §3: quem rodava essas ferramentas de fora da raiz SEM `JFN_DATA_DIR` contando com o `data/` do cwd passa a ler
  o banco do repositório. Nenhum caller assim foi achado.
- §4–§5 mudam saída de propósito (fila do sweep; total "outras UGs" do relatório Mobiliza).
- A etapa 5 da skill (subagentes procurando o que sobrou) não foi feita; o §8 é o que ficou visível nesta passada.
