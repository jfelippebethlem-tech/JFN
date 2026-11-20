# Decision log — passada final do untangle, repositório inteiro (20/11/2026)

Escopo: o que nenhuma das 19 áreas via sozinha — fronteiras entre áreas, pendências que os logs deixaram "para a
passada final", e a **poda de testes** (o dono deixou-a para cá). Base: `af86ddd7`. Commits locais, sem push.
Restrições cumpridas: nenhuma coleta real (SEI/SIAFE/sites), `data/` real só em leitura, nenhum LLM pago, crontab e
serviços intocados, eleição (`tools/eleicao2026_*`, `tse_*`) não lida nem tocada.

Formato igual aos outros logs: o conserto fica acima dos problemas que resolve. `[feito]` = aplicado; `[dono]` =
muda número publicado, é escolha de produto ou conteúdo jurídico; `[anotado]` = registrado só.

## 0. Validação

Suíte inteira na VM-2, cópia limpa por rodada (`git archive`/`git ls-files` → diretório próprio, índice git local
para as catracas, mesmo venv nas duas rodadas). Números em §8.

Cada mudança de lógica foi medida antes × depois sobre `data/compliance.db` real, só leitura; os números estão em
cada item.

## 1. O squash das áreas perdeu remoções — o log dizia "apagado", a árvore dizia que não  `[feito — 33f7c2d0]`

Os commits originais da área 15 e de `tools/sei_*` não são ancestrais da branch; o squash levou o conteúdo novo e
deixou a origem de cada remoção/renomeação. Achado por `git log --all --not af86ddd7 --diff-filter=D/R` cruzado com
o que ainda existe. 14 arquivos, reconferidos um a um (nenhum chamador em código, shell, yaml, units instaladas,
`crontab -l`):
- `tools/enviar_forense_telegram.py`, `tools/enviar_sessao_telegram.py` — envios de uso único. O primeiro gerava PDF
  **e mandava Telegram ao ser importado**: `test_import_nao_executa_trabalho` estava vermelho no baseline por isso
  (a exceção nomeada tinha sido esvaziada junto com a remoção que se perdeu).
- `tools/painel_extrair.py` — migração de julho concluída.
- `deploy/systemd/massare-{daily,market}.{service,timer}` — Massare fora da VM (decisão do dono).
- `deploy/jfn-fisc-refresh.{service,timer}`, `deploy/jfn-sei-noturno.{service,timer}` — cópias da raiz; as vigentes
  estão em `deploy/systemd/`.
- `tools/sei_docs_to_telegram.py`, `sei_login_retry.py`, `sei_reocr_backfill.py` — idênticos byte a byte às cópias
  em `tools/_arquivo/sei_debug_superado/`.
- Consequência medida: a catraca de `except Exception` chegou **vermelha em 1.545** contra a baseline 1.534 (a
  baseline já contava o ganho dos três scripts).
- `[anotado]` só as remoções foram conferidas; conteúdo modificado que o squash possa ter perdido não tem como ser
  provado por este método (as branches das áreas divergem da ponta em outros arquivos).

## 2. OB paga pela régua da casa (`cruzamentos_intel._ob_paga`), nas cópias que atravessavam áreas  `[feito]`

- **Cópias parciais do filtro** (status + "Erro no Pagamento", sem Pagamento Complementar, reemitida e OB sem
  número) — `ec68a138`:
  - `rotas/investigacao.api_painel`, KPI "último dia pago": 19/11/2026 de 871 OB · R$ 215.717.175,33 para
    **866 OB · R$ 215.710.834,82**.
  - `empresa_fantasma.perfil_do_cnpj` (total recebido): 155 de 111.478 credores mudam; soma
    R$ 427.471.729.179,87 → R$ 427.159.615.777,42.
  - `lex.py` (UG da perícia de serviço contínuo): UG principal muda para 53 de 14.412 fornecedores; 51 ficam sem
    OB paga.
- **Sem filtro nenhum** — `lex_conflito` (`6b2f1656`): "pagou depois da sanção". Sanções do SIGA: das 1.433 linhas
  com OB posterior, 756 mudam (R$ 73.734.513.696,79 → R$ 72.401.548.635,29) e **em 5 o "pagou depois" vinha só de
  OB que não é pagamento**. Lista suja do MTE: 0 casos hoje.
- **Espelho TFE → SIAFE** (`c4b5c96e`), pendência de `tools-investigacao.md` §10:
  - `socios_dump_sweep.materializar_rede` (`rede_socios_fornecedores.total_recebido`): das 2.795 pessoas, 1.769
    mudam (1.026 sobem, 641 descem, 102 só tinham OB em 2019–2020, fora da cobertura do SIAFE da casa); soma
    R$ 155.353.956.166,75 → R$ 136.907.074.138,16. Vale na próxima materialização; `rede_fachada` passa a escrever
    "OB paga à rede, SIAFE 2021+" (é piso).
  - `fachada_b2_sync` (UG que mais pagou, no manifesto das fotos): 208 fotos, 14 mudam de UG, 15 ficam sem UG
    (vazio honesto). O espelho só empresta o nome da UG.
- `[anotado — não migrado, com motivo]`
  - `tools/lex_aprendizado_cruzado` (`_ubiquo`, `_cnpj_pleno_da_raiz`): não afirma pagamento — conta UGs e escolhe o
    CNPJ pleno da raiz. Medido: o CNPJ escolhido difere em 30 de 12.915 raízes; 1.628 raízes só existem no espelho
    (2019–2020) e ficariam sem resposta. Fica no espelho. O `length(favorecido_cpf)=14` dali deixa passar CPF
    mascarado (14 caracteres), sem efeito porque a busca é por raiz de 8 dígitos.
  - `reporting/detector_tac` (C9): a marca "TAC" só existe na observação do espelho. O molde é o de
    `tools/tac_ranking_ugs` (valor do SIAFE, observação do espelho por número+UG), mas são seis consultas que
    alimentam C9, `/orgao` e `/relatorio` — pede rodada comparada dos três produtos. `[dono]`
  - ~40 somas de `ordens_bancarias.valor` ainda apresentadas como pago (inventário por arquivo:linha feito nesta
    passada): `relacoes`, `cruzamento.cidades_de_orgao`, `grafo_poder`, `dossie._resumo_ob`, `lex_base_empirica`,
    `investigacao_orgao_dd`, `fachada_doubt.candidatos`, `correlacao_sei`, `reporting/intel_dados`
    (`favorecido_resumo.total_pago`), `reporting/inteligencia_orgao`, `reporting/intel_md._sede_total_pago`,
    `rotas/investigacao` (grafo, perfil), `rotas/vinculos.api_patrimonio`, `rodizio_temporal`, `rules/engine`,
    `analysis/anomaly_detector`, `tools/sweep_full.sh`, `tools/enriquecer_favorecidos_top`. É troca de fonte dos
    produtos `/relatorio` e `/orgao` (reporting.md §2.1). `[dono]`
  - Sem filtro, ordenando fila ou estatística bruta: `varredura_orgaos.ugs_com_pagamento`, `rotas/sistema`
    (`valor_total`, `por_ano` — mostra o pago certo ao lado), `tools/pos_sweep_analise` ("Total OBs" inclui anulada).
  - `governo_couto_regras` e `pericia_contabil` têm régua própria (devolução abatida em Python); não são cópia.

## 3. LGPD — uma máscara de CPF  `[feito — 97860023]`

- `osint/vinculos.chave_publica` e `territorio/api._doc` mostravam D1–D3 + DV (`123.***.***-01`); o resto da casa
  mostra D4–D9 (PAD-04). O mesmo CPF pelas duas janelas ficava inteiro. Passam a `cpf_cnpj`. No território: 24
  contratos de pessoa física (de 39.360) mudam de máscara. A cópia `osint/vinculos.mascarar_cpf` sai.
- `[dono]` `contasrio_fiscal.fiscal_doc` chega da FONTE já na janela D1–D3 + DV (`123.***.***-01`) e sai assim em
  `acervo.py:451` e `lai/fatos.py:126`. Com a PAD-04 do mesmo fiscal em outra tela, o CPF fecha. Decidir: omitir o
  documento do fiscal ou exibir só o nome.

## 4. Constantes normativas e direção de dependência  `[feito]`

- E1 e E7 leem 10% (capital/PL), 50% (atestado) e 1% (garantia) de `limites_habilitacao` (`9005eaca`). Mesmo valor
  em ponto flutuante; nenhum resultado muda. A citação divergente (art. 69 §3º × Súmula 275) fica: conferência
  jurídica. `[dono]`
- Art. 86 (adesão a ata) vira `limites_adesao` (`c60fe282`): `padroes/carona_acima_do_limite` importava o detector
  X4 só para ler a norma.
- `pcrj/universo.DB` e `pcrj/esfera.construir_mapa`: caminho do módulo dono (`db.COMPLIANCE_DB`), não o cwd
  (`f2e1d719`). Todos os chamadores de cron fazem `cd ~/JFN`.
- `[anotado]` já resolvidos por outras áreas (os logs antigos ainda os listam): natureza 2011/2038 (só
  `credor_institucional.NATUREZA_ESTATAL`), validador de DV de CNPJ (restam `cerebro_fts`, proposital, e duas cópias
  idênticas em 20.000 entradas aleatórias: `tools/lentes_pcrj_execucao`, `sei/extrair_cpf`), tetos de dispensa
  (nenhum literal fora da régua).
- `[anotado]` 25% do art. 125 escrito à mão sem distinguir reforma: `governo_couto_regras.py:1339`,
  `lex_analise_conteudo.py:365`, `execucao_fatos.py:148`, `tools/_triagem_bombeiros.py:64`.
  `nucleo/parametros.py:170` é segunda cópia de `acima_do_teto.TETO_CF_37_XI`.
- `[anotado]` caminho de banco ainda relativo ao cwd (iguais em produção; os serviços e crons fazem `cd ~/JFN`):
  `varredura_orgaos.py:39`, `varredura_execucao.py:74`, `ug_nomes.py:46`, `empresa_fantasma.py:326`,
  `reporting/capitulos_dossie.py:196`, `investigacao_dd.py` (9 pontos; base ausente vira `("", None)` calado),
  `rotas/produtos.py:516`, `tools/sei_cpf_sweep.py:25`, `tools/sei_analise_em_serie.py:46`,
  `tools/sei_agentes_sweep.py:36`, `tools/sei_inventario_captura.py:41`.
- `[anotado]` privados que viraram API de fato: `cruzamentos_intel._ob_paga` (53 importadores em outras áreas),
  `reporting.intel_base._DB` (17), `database.models._resolver_db` (6), `tools.lex_execucao._chave_processo` (5,
  de `tools/` para o pacote). Renomear é mecânico, mas toca ~80 arquivos e os testes que os trocam por monkeypatch.

## 5. Defeitos consertados de passagem  `[feito]`

- `analysis/graph_analyzer` apagado (`2a212695`): o sócio virava nó `PJ:{empresa_id}` e o favorecido `PJ:{cnpj}` —
  o triângulo servidor-sócio-UG nunca fechava; 0 alertas dos três tipos no banco; se fechasse, gravaria CPF inteiro e
  "configura nepotismo". Só o `scheduler` legado o chamava (sem cron, unit ou processo).
- `/api/hermes/parar` (`ed96daa4`): chamava `empty()`/`dequeue_nowait()`, que `MissionQueue` não tem; o
  `AttributeError` ia para log debug e a fila nunca foi esvaziada. `[anotado]` a fila continua sem consumidor.
- Excepts que escondiam a causa (`80c85d40`): `pos_sweep_analise._q` (erro → `[]` → `IndexError`),
  `pericia_bombeiros_reconcilia` (tolerava "tabela inexistente" e engolia `database is locked`),
  `pericia_aprendizado` (falha do vault calada).

## 6. Poda de testes

### 6.1 Testes que tocavam o mundo real  `[feito]`
- **Login real no SIAFE a cada rodada da suíte** (`714146fa`): `test_rota_fila_fiscal` e `test_server_snapshot`
  abrem `with TestClient(app)`; o ciclo de vida do servidor chama `get_agent()` (navegador + login com as
  credenciais do `.env`, que o próprio import do `server` carrega) e agenda aquecimento na Receita/PNCP. Fixture
  `servidor_sem_boot_externo` no conftest troca as duas chamadas.
- **Cache de benefícios de produção sujo por teste** (`846b6149`): o cache do coletor é global e grava em
  `data/beneficios_cache.json`. Fixture autouse isola arquivo e memória; 5 testes de `investigacao_dd` passam
  `usar_beneficios=False`. `[dono]` apagar a chave `pep:…` de teste (nome "X") do arquivo real — é escrita em `data/`.
- `test_hermes_metacognicao` (`a8ecce32`): lia `compliance.db` e `nucleo_memoria.db` reais; agora fixture, e a
  rotação de backups passa a ser exercitada.
- `test_offline::test_envfile_carrega_env` apagado (`691a1d8d`): só `isinstance(list)`, e carregava o `.env` real no
  ambiente da sessão inteira.

### 6.2 Testes que não podiam falhar por regressão / falhavam sem defeito  `[feito]`
- `test_sei_contexto_unico::test_todos_os_logins…` (`b681db3f`): contava a string `await login(pg` — vermelho desde a
  sessão fixa. A regra segue coberta pelos outros três testes do arquivo.
- `test_fila_captura_prioriza_sinal`: função com `skipif(True)` e corpo `pass`.

### 6.3 Código sem chamador que só teste segurava  `[feito — 57bd8739, c7476554; devoluções em deb044cc e seguinte]`
Prova de cada um: nenhuma ocorrência fora de `tests/` em `compliance_agent/`, `rotas/`, `tools/`, `siafe_agent/`,
`config/*.yaml`, `deploy/`, `*.sh`, `capabilities.yaml`, golden/BASE-FALHAS e `crontab -l`.

| Apagado | Testes | Por que não era só "nunca ligado" |
|---|---:|---|
| `editais/certame_tcerj` | 7 | `contexto_j4` duplicava `collectors/tcerj_licitantes.contexto_certame`, que é o que J4/CRI leem |
| `osint/qsa_certame` + `osint/direcionamento_consumado` | 31 | handoff de 06/08 já os dava como "ligar ou apagar"; medido zero par com sócio comum; rotulavam documento mascarado como `cpf` e fundiam homônimos com força 0,95 |
| `sei/dossie_fracionado.prompt_reduce` (+ `_sistema_reduce`), `sei/indice.ja_indexado` | 1 função + 2 asserts | encanamento órfão: o `reduzir()` que usava o prompt já não existia |
| `limites_de_fonte.explica_vazio`, `cpf_externo.ProviderSituacaoCadastral` | 0 | idem |

Total podado: **42 funções de teste** (38 dos três módulos + `prompt_reduce` + as 2 da §6.2 +
`test_envfile_carrega_env`), mais 2 asserts e o teste reescrito do Hermes; 2 testes novos (rede pela OB paga, fila de
missões). Nenhum `test_regra_*`, `test_catraca_*`, nem teste de moeda/CPF/OB foi tocado.

**Critério que valeu:** encanamento órfão e duplicata saem; detecção ou conteúdo curado que foi desenhado e nunca
ligado fica para o dono. Por isso quatro itens chegaram a ser apagados (`57bd8739`, `c7476554`) e **voltaram
idênticos**: `editais/dosimetria` e `analysis/curva_abc` (entregas H.4 e D.3.3 de `docs/HANDOFF-2026-07-29.md`),
`motivo_inabilitacao.classificar_com_rubrica` (o gabarito determinístico manda o caso ambíguo "à rubrica LLM") e
`screens_conluio.vetores_unitarios_similares`. As mensagens daqueles dois commits contam testes a mais (63 e 9);
vale a tabela acima.

### 6.4 Sem chamador, NÃO apagado — ligar ou apagar é do dono  `[dono]`
Todos conferidos com a mesma prova (nenhum uso de produção):
- Entregas do plano de hermenêutica: `editais/dosimetria` (18 testes; cita "Lei 8.443/1992, art. 250", que não
  existe — corrigir antes de ligar), `analysis/curva_abc` (17), `reporting/matriz_achados` (17),
  `reporting/qualificacao_juridica` (16), `reporting/quesitos_diligencia` (16), `osint/timeline` (23),
  `knowledge/doutrina` (12), `knowledge/subsuncao` (20; só o hash em `nucleo/prompt_versao`),
  `nucleo/autoconsistencia` (14), `detectores/x13_sub_rogacao` (17; registrado, sem produtor de contexto).
- `motivo_inabilitacao.classificar_com_rubrica` (5 testes) e `screens_conluio.vetores_unitarios_similares` (2).
- `editais/cri` (18 + 4): único uso é `tcerj_licitantes.ranking_por_ente`, que não tem chamador.
- `editais/narrativa_certame.narrar*` (5), três screens de `screens_participacao` (14), `contratos/estado.py` (3),
  `execucao_cerebro.py` (12), `enriquecimento/footprint_alvo.py` (9), `collectors/tfe_receita.py` (2; `tasks/todo.md`
  M4 ainda o prevê), `base.painel_adversarial` (10; ninguém passa `painel=True`).
- Conteúdo curado: `sei/classificador_doc.deve_guardar_texto` (política de storage pedida pelo dono, nunca ligada),
  `lex_sancoes.calcular_multa_mora`/`MULTA_MORA` (Decreto RJ 3.149/80).
- Sem teste e sem chamador: `c8.montar_ctx_servidores`, `tools/calibrar_indice`, `tools/confronto_caso`,
  `tools/fotos_acervo`. CLIs só com teste (podem ser de uso manual): `hermes_model_router`, `baseline_achados`,
  `experimento_ia_fraca`, `gabarito_claude`, `itcampo_degraus`, `memoria_indice`, `pericia_agentes_aplicar`.
- `thoughts.t_execucao_financeira` tem chamador (`thoughts.rodar`) e devolve sempre `[]`.

### 6.5 Testes — o que ficou  `[anotado]`
- Ainda leem a máquina real e pulam quando falta: ~30 arquivos (`data/sei_arquivo/<processo>`, `intel_base._DB`,
  `data/tcu_juris.db`, `crontab -l`, units instaladas). São controles sobre o acervo real; isolar é reescrever cada
  um com fixture.
- `test_pericia_peca_bate_com_evidencia.py:34` abre `file:data/compliance.db` relativo ao cwd sem conferir se existe.
- `test_autoaprimoramento_ciclo.py:97` chama `L._regras_calibracao()` sem `JFN_DB`: na VM roda `create_all` no banco
  de produção; em checkout limpo cria `data/compliance.db` vazio (a origem do "banco vazio na raiz" de
  reporting.md §3 — o `lifespan` do server também o cria ao segurar o WAL).
- 9 arquivos importam `server`, cujo import carrega o `.env` real em `os.environ` para o resto da sessão.
- `test_esfera_estanque.py:58` × `tests/pcrj/test_esfera.py:21`: mesma asserção sobre `pcrj.esfera`, casos em parte
  sobrepostos — fundir.
- `test_jfn2_sei` está em `_MODULOS_REDE` (conftest), mas os testes de `classificador_doc` dali são puros e ficam
  fora da suíte diária.

## 7. Achado e não consertado — pede decisão  `[dono]`

1. **`contratos/dossie.sinais_fornecedor` consulta `rede_socios_fornecedores WHERE raiz=?` — a coluna não existe.**
   `sqlite3.Error` engolido: o sinal "sócio liga ≥2 fornecedores (rede)" nunca disparou no parecer de contratos
   (`tools/contratos_parecer`, `com_rede=True`; os testes só usam `com_rede=False`). `tools/editais_direcionamento`
   faz certo (`cnpjs_basicos LIKE`). Consertar acende o sinal para **1.360 dos 31.217 fornecedores** de
   `pcrj_contratos`, e `thoughts._sinais_lex` o converte em "coincidência de participantes" na triagem do Lex — um
   salto de inferência que ninguém validou. Não liguei em massa um sinal nunca medido.
2. `detector_tac` no espelho TFE (§2) e as ~40 somas do espelho nos produtos `/relatorio` e `/orgao`.
3. `fiscal_doc` do ContasRio na janela D1–D3 + DV (§3).
4. O que os 19 logs já deixaram para o dono e segue igual: três definições de "ente público", títulos de alerta com
   CPF inteiro ou R$ americano (título é identidade do alerta — `rotas/investigacao.py:466-493`,
   `anomaly_detector`, `rules/engine.py:638,793`, `c6_vinculo_politico`, `cruzamentos_intel.py:602`), `J()` do painel
   sem `ok:false` em falha de rede, `scheduler` legado (importa `pncp.verificar_contrato_pncp`, que não existe),
   bot de comandos do Telegram desativado, `motivo_inabilitacao` ainda diz "juízo à rubrica LLM" no fundamento do
   caso ambíguo.
5. `tools/pre_push_gate.sh:23` mede o checkout principal mesmo quando o push sai de um worktree.

## 8. Suíte (VM-2), antes × depois

Mesma receita nas duas rodadas: árvore inteira versionada num diretório próprio da VM-2, índice git local, mesmo
venv, `pytest tests/ -q --timeout=900 --ignore=tests/test_sei_pagina_de_unidade.py`, monolítica.

| | Coletados | Passaram | Falharam | Pulados |
|---|---:|---:|---:|---:|
| Antes (`af86ddd7`) | 10.001 | 9.823 | 5 | 173 |
| Depois (ponta desta passada) | 9.958 | 9.785 | 2 | 171 |

- As 5 falhas de antes: catraca de `except Exception` (1.545 > 1.534), `test_import_nao_executa_trabalho`
  (`enviar_forense_telegram` executando no import), `test_sei_contexto_unico::test_todos_os_logins…`, e duas do WAL.
- As 2 que ficam (`test_conexao_guardia_do_wal::test_guardia_liga_persist_wal`,
  `test_sentinela_wal_automatica::test_instalar_automatico_liga_a_sentinela`) são de AMBIENTE da VM-2 (a guardiã
  sobe sem PERSIST_WAL lá); na VM-1 os 17 testes dos dois arquivos passam. Iguais antes e depois.
- Coletados: −43 = −45 casos podados (42 funções; 3 eram parametrizações) + 2 testes novos.
- Catracas: `except Exception` 1.545 → **1.526** (baseline 1.534 → 1.526); `pass` mudo 150 → **145**.
- `[anotado]` sem índice git a cópia remota dá 10 `RuntimeError` em `test_regra_catracas` e pula a catraca de
  excepts; `tools/testar_na_vm2.sh` já cria o índice — rodar a suíte por ele, não por cópia crua.
