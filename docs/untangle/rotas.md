# Decision log — untangle das rotas (20/11/2026)

Escopo: `rotas/` (15 arquivos, a API do painel e do Yoda). `server.py` e `static/js`: só anotados.
Escolhas do dono: **Comentários = sim** (saem só os que repetem o código ou descrevem uma restrição que já
não existe; medição datada, decisão do dono e porquê de workaround ficam), **Testes = não**.
Restrições da casa, acima da skill: caminho, método, parâmetros e JSON de cada rota **não mudam** (o painel
e o Yoda leem); **chave de cache não muda** (senão o painel abre frio); comportamento igual salvo defeito
provado.

Formato: o fix fica acima dos problemas que resolve. `[feito — lote N]` = aplicado; `[pendente]` = precisa
de decisão do dono, de mexer em teste (Testes = não) ou é redesenho maior que esta passada;
`[fora do escopo]` = anotado só.

Verificação de cada lote: (1) comparação EMPÍRICA do JSON de cada rota tocada — o módulo de antes
(`git show 6f333676:rotas/X.py`, carregado lado a lado) e o de depois chamados com os MESMOS argumentos sobre
os bancos reais de `~/JFN/data` (só leitura), cache desligado nos dois, carimbos de tempo ignorados
(`tools`-less harness em scratchpad, descrito na seção final); (2) `tools/painel_ponte_check.py`;
(3) os 63 arquivos de teste que citam `rotas` (inclui `test_rotas_sem_orfa.py`, `test_server_snapshot.py`
com o golden `tests/golden/server_rotas.txt`, catracas de regra e de except).

## Mapa do problema (o que a passada achou)

O desenho atual é "um arquivo por domínio, cada rota um adaptador fino sobre uma função de
`compliance_agent`". Isso está certo e fica. O que está errado é o que as rotas fazem POR FORA desse
adaptador — cada uma resolve sozinha onde fica `data/`, como abrir o banco, como guardar resultado, como
pausar os sweeps e qual Python chamar — e as cópias divergiram.

## 1. Banco de leitura aberto por UM caminho em cada módulo  `[feito — lote 1 e 3]`

- `rotas/investigacao.py::_ro(banco, **kw)` abre `RAIZ/data/<banco>` em `mode=ro` (com `row_factory` quando
  pedido); lê o `RAIZ` do módulo NA CHAMADA, que é o que os testes já redirecionam (`monkeypatch R.RAIZ`).
  - 23 cópias de `_sq.connect(f"file:{RAIZ / 'data' / 'compliance.db'}?mode=ro", uri=True)` (+ 3 de `pcrj.db`)
    em `investigacao.py` (`_grafo_rede_completa`, `api_fachada_revisar`, `api_sugestoes`×2, `api_pncp`,
    `api_certames_lista`, `api_pncp_conluio`, `api_nomeados_candidatos`, `api_laranjas`, `api_pericias`,
    `api_perfil`, `api_doerj_tac_recorrente`, `api_imprensa_orgaos`, `api_sancoes_detalhar`,
    `api_pcrj_comissionados_candidatos`, `api_pcrj_fantasmas`, `api_pcrj_gastos_achados`,
    `api_pcrj_aditivos`, `_siafe_pago_total`, `api_fontes_frescor`×2), cada uma com seu `import sqlite3 as _sq`
    local e o módulo ainda com um `import sqlite3 as _sqlite3` no meio do arquivo.
  - `_con_integras()` abria `"data/compliance.db"` RELATIVO AO CWD, em leitura-escrita, ao contrário de todas as
    vizinhas — no serviço o cwd é `~/JFN` e dá o mesmo arquivo; fora dele (teste, VM-2) criava banco vazio.
  - `str(RAIZ / "data" / "compliance.db")` repetido como `db_path=` para `gerar_pdf_intel` e `grafo_familias`.
- `rotas/sistema.py::_ro(**kw)` faz o mesmo para `sistema.py`, respeitando `JFN_DATA_DIR` como o
  `/siafe/stats` já fazia (no serviço `JFN_DATA_DIR = ~/JFN/data`, o mesmo arquivo).
  - `sistema.py:71, 362, 716, 774` abriam o compliance.db em LEITURA-ESCRITA só para ler, três deles com o
    `close()` fora de `finally` (conexão vaza na exceção); `:362` ignorava `JFN_DATA_DIR`.
- Não unificado ENTRE módulos (ver pendência 9.1): cada módulo resolve `data/` de um jeito (`RAIZ`,
  `JFN_DATA_DIR`, `intel_base._DB`, `JFN_DB`) e os testes fixam cada jeito pelo nome.

## 2. `sys.path` e a raiz do repositório não são recalculados por requisição  `[feito — lote 1 e 2]`

- `tools.*` é importável no serviço (o diretório do `server.py` é a raiz) e nos testes; as outras 15 rotas
  que importam `tools.*` nunca mexeram no `sys.path`.
  - `investigacao.py::api_restritos`, `api_flags` e `vinculos.py::api_resolucao_nome_cnpj` faziam
    `sys.path.insert(0, raiz)` a CADA chamada: o `sys.path` do servidor crescia uma entrada por visita.
  - `investigacao.py::pagina_controle` e `vinculos.py::api_fiscal_fila` recalculavam a raiz por
    `Path(__file__).resolve().parent.parent` com o `RAIZ` do módulo ao lado.

## 3. Um só "Python do repositório" para quem chama script  `[feito — lote 2]`

- `rotas/apoio.py::python_do_repo()` (`.venv` do repo quando existe, senão o intérprete que serve a rota).
  - `produtos.py::_python_do_repo` e o bloco inline de `vinculos.py::api_fiscal_fila` eram a mesma regra
    escrita duas vezes; o próprio comentário de `produtos` dizia "mesmo conserto de rotas/vinculos.py".

## 4. Pausa dos sweeps: um protocolo, um dono, e relatório não desfaz pausa manual  `[feito — lotes 3 e 4]`

- `rotas/apoio.py` guarda os nomes das flags (`data/.pause_*`, as que `tools/sei_sweep.py`,
  `tools/siafe_supervisor.sh` e `sei_supervisor.sh` leem) e as duas operações:
  `pausar_para_relatorio()` / `retomar_apos_relatorio()` (produtos) e `pausar_pelo_painel()` /
  `retomar_pelo_painel()` / `sei_pausado()` (sistema). O relatório só remove as flags que ELE criou.
  - **Defeito**: `/api/sweeps/pausar` (botão do painel) cria `.pause_sweeps` + `.pause_sei_sweep`; ao fim de
    QUALQUER relatório, `produtos._retomar_sweeps_se_ocioso` apagava `.pause_sei_sweep` (estava na lista
    dele) — a pausa manual do SEI (botão do painel, `tools/ler_medviva_fserj.sh`, `tools/vm2_integras.sh`)
    sumia sem ninguém pedir. Agora o relatório grava `relatorio` no CONTEÚDO das flags que cria e só apaga
    essas; a do painel grava `painel` (sobrescreve a marca de um relatório em curso e vira dona); `touch` de
    script deixa a flag vazia, que o relatório também não apaga. Os leitores (sweeps, `*.sh`) só olham
    existência — nada muda para eles. Marca em arquivo e não em memória porque `retomar_promessas` refaz o
    relatório depois de um restart.
  - `produtos.py:53` usava as flags RELATIVAS AO CWD (`Path("data/.pause_sweep_2")`); `sistema.py` usava
    `RAIZ/data`. Mesma lista de nomes em dois arquivos (+ `sistema.api_sweeps_status:357`).
  - `produtos._pausar_sweeps_para_relatorio` matava os sweeps com `pkill -f` — a regra 8 da casa é
    `pgrep` + `kill` por PID, nunca `pkill -f`. Mesmo sinal (SIGTERM), mesmos padrões com colchete.
- `sistema.py::_vivo(padrao)` — um só "processo vivo?" por `pgrep -f` (padrões com colchete).
  - `api_sweeps_status::_alive` e `api_sistema_atividade::_alive` eram cópias; `_bus_sampler::_pgrep` a
    terceira (com `timeout=3`, que as outras não tinham — agora as três têm).

## 5. Produtos da casa saem do `cwd`: o banco PCRJ é o do módulo dono  `[feito — lote 4]`

- `produtos.py` deixa de passar `db_path="data/pcrj.db"` (relativo ao cwd) a `pericia_mestre.gerar_pdf`,
  `ppp_ccpar.coletar_projeto/ingerir_edital`, `dossie_ppp.montar_dossie/gerar`, `triagem_ppp.triar_lote` —
  todas caem em `compliance_agent.pcrj.db.DB_PATH` (absoluto) quando não recebem nada.
  - Com cwd ≠ raiz, `db.conectar` faz `mkdir` e criava um `data/pcrj.db` VAZIO no cwd (já anotado em
    `docs/untangle/pcrj.md`).

## 6. Cache de `vinculos` não guarda falha  `[feito — lote 2]`

- `vinculos.py::_cache` não grava resultado `{"ok": False}`; `ttl` (nunca passado por ninguém) sai.
  - **Defeito**: `api_zeros_sem_causa` guardava o `medir()` mesmo com `ok=False` e servia o erro por 1 h
    (`investigacao.api_conflito` e `sistema.api_siafe_stats` já não guardavam erro, com teste).
  - `api_cobertura_grafo` (dentro de `api_elos_ocultos`) reabria o banco copiando o corpo de `_db_ro`.

## 7. Comentários e docstrings que mentem  `[feito — lotes 1 a 5]`

- Cabeçalhos de `investigacao.py`, `sistema.py`, `produtos.py`, `hermes.py`: "Handlers idênticos aos
  originais; só o decorador mudou" — não é verdade há meses.
- `vinculos.py:4`: "investigacao.py já tem 2.291 linhas e 98 rotas" (são 3.072).
- Comentários que só repetem o código: `sistema.py` `# SEI`, `# tabela ainda não existe nesta base`,
  `vinculos.py` `# já inclui sqlite3.Error`, `# caminho único p/ nome de unidade`.
- Imports locais que repetem os do topo (`sys`, `sqlite3`, `json`, `time`, `Path`, `os`, `asyncio`, `re`).
- `hermes.py`: `import` no meio do bloco depois do `logger`, `import asyncio` repetido dentro de
  `api_hermes_definir_missao`, e em `api_hermes_parar` um `for` de 20 itens seguido de um `while` que fazia a
  mesma coisa (e nenhum dos dois funciona — ver pendência 10).

## 8. Casos especiais que FICAM (o sistema ainda precisa deles)

- `@router.get` + `@router.post` em `/api/cartel` e `/api/rodizio` (o Yoda chuta o método).
- `_com_teto` em `/api/pncp` e `/api/sei/direcionamento` (fonte viva sem teto travava a aba — medido).
- Retentativa única em `/api/compliance/buscar` (conexão envenenada do SQLAlchemy — medido).
- `_NC_CORPO` (corpo gzip pronto de 4 MB do `nomeados_candidatos` — medido).
- `except Exception: return {"ok": False, "erro": …}, 500` por rota: é o idioma de borda da casa (a catraca
  `test_catraca_excepts`/`test_divida_except_pass` o cobra); a forma do erro é contrato do painel e do Yoda
  (`{"error"}` legado em `/api/compliance/*`, `{"ok": False, "erro"}` no resto) — não muda.
- `_PERICIAS_MESTRE` / `_PPP_SLUGS` com um único hospital: é o único que tem perícia mestre hoje.

## 9. Pendências

1. **O cache do painel mora em `investigacao.py` e outros 5 módulos importam o privado `_cache_calc` de
   lá** (`orcamento_orgao`, `periodo`, `governo_couto`, `sistema`×2). O lugar certo é um módulo próprio
   (`rotas/cache_painel.py`) que `investigacao` também importaria. Não foi feito porque 9 arquivos de teste
   fixam o estado pelo módulo `investigacao` (`monkeypatch inv._CACHE_DIR / inv._cache / inv._INVALIDAR /
   inv._cache_calc`, e `test_orcamento_orgao` troca `investigacao._cache_calc` para afetar OUTRO módulo):
   mover sem reapontar os testes deixaria o teste escrevendo no `data/cache_painel` real. Testes = não.
2. **Três caches à mão ao lado do `_cache_calc`**: `vinculos._cache` (memória, sem single-flight, sem disco,
   sem a marca `_invalidar.json` da propagação), `sistema._stats_cache`, `sistema._LIFT_CACHE`,
   `sistema._SIS_CACHE`, `acervo._EST`. Trocar por `_cache_calc` muda comportamento (passa a servir valor
   vencido enquanto recalcula, persiste em disco, obedece a propagação) e cria chaves novas em
   `data/cache_painel` — decisão do dono. Consequência hoje: a propagação automática NÃO vence o cache das
   telas de vínculos (até 1 h de número velho depois de uma coleta).
3. `sistema./api/eval/lift` e `investigacao./api/intel/lift` são "a mesma varredura" (docstring) com
   funções e caches diferentes (`painel_lift.montar` × `retro_auditoria.avaliar_lift`).
4. **Despacho de produto em 7 cópias** (`produtos._gerar_e_enviar_*` e o lado da rota): pedido do dono,
   pausa, `try/except` com aviso, `finally` com `discard`/`concluir`/retomar. PPP, dossiê completo e dossiê
   mestre chamam `_promessas.concluir` mas nunca `registrar` — **se o serviço reinicia no meio, essas três
   entregas se perdem** (as outras três voltam pelo `retomar_promessas`). Corrigir é mudar o que o Yoda
   recebe depois de um restart: decisão do dono.
5. `lai.py` importa o privado `produtos._enviar_docs_telegram`; `server.py:186` importa
   `produtos.retomar_promessas` (boot depende de uma rota). O nome privado é fixado por
   `tests/test_server_envia_md_telegram.py`.
6. Rotas que leem arquivo escrito por script com o nome escrito à mão: `vinculos` (5 JSON de `tools/`),
   `pericias_rotinas` (`pericia_contabil_resumo.json`, `cge_confronto.json` — os escritores têm `SAIDA`),
   `sistema` (`tac_ranking_ugs.json`). `vinculos.api_fiscal_fila` faz parse do STDOUT de
   `tools/processo_360_ranking.py` por regex.
7. `vinculos.api_detectores` abre `achados.db` relativo ao cwd e ignora `JFN_DB_ACHADOS`, que
   `pericias_rotinas._achados_db` respeita; `cge_confronto.DB_ACHADOS` é a terceira forma. O dono do caminho
   deveria ser um módulo de `compliance_agent` (hoje são três).
8. `PROVENIENCIA` de `compliance_agent/proveniencia_manchetes.py` é chaveada pela string do caminho, que a
   rota repete à mão em `anexar("/api/...", d)` (11 rotas). Renomear o caminho sem renomear a chave tira a
   proveniência em silêncio; a catraca `test_regra_inventario` cobre o inventário, não esse par.
   `api_painel` reaplica `anexar` no acerto de cache sobre um valor que já foi gravado com ela.
9. `hermes.py` responde erro com `200` e sem `ok` (`{"erro"}`), `{"ativo": False, "erro"}`; o painel do
   Hermes lê assim — contrato, não muda sem o front.
10. **Defeito achado, não corrigido (fora de `rotas/`)**: `/api/hermes/parar` "esvazia a fila de missões"
    chamando `mission_queue.dequeue_nowait()` e `mission_queue.empty()`, que `compliance_agent/hermes_goal.py::
    MissionQueue` NÃO tem (só `enqueue`, `get`, `qsize`). O `AttributeError` caía no `except` e ia para log de
    debug: a fila NUNCA foi esvaziada pelo "parar". Nesta passada saiu só o laço duplicado (o `for` de 20 itens
    antes do `while`, que fazia o mesmo); o conserto é dar a `MissionQueue` um `esvaziar()` — módulo fora do escopo.

## 10. Fora do escopo (anotado)

- `server.py:888` serve `/reports/{arquivo}` de `Path("reports")` relativo ao cwd, como
  `investigacao.api_compliance_reports`/`api_relatorio_30d`/`reports/limpar` — os quatro dependem do
  `WorkingDirectory=%h/JFN` do `jfn.service`.
- `compliance_agent/reporting/intel_base._DB`, `database.models._resolver_db` (`JFN_DB`) e
  `JFN_DATA_DIR`: três variáveis de ambiente para dizer onde mora o compliance.db.

## 11. Verificação (antes × depois)

Testes casados (os 63 arquivos que citam `rotas`, inclui `test_server_snapshot` com o golden
`tests/golden/server_rotas.txt`, `test_rotas_sem_orfa`, catracas de except): **antes 588 passed / 26 skipped;
depois 588 passed / 26 skipped**. Extras rodados depois: `test_catraca_*`, `test_regra_catracas`,
`test_rotas_sem_superficie`, `test_promessas_sobrevivem_ao_restart`, `test_server_envia_md_telegram` — 49
passed (a catraca CNF-16 acusou a palavra "pkill -f" dentro da docstring nova de `apoio._encerrar`; reescrita).
`tools/painel_ponte_check.py`: OK antes e depois.

Comparação empírica: harness em scratchpad carrega o módulo de ANTES (cópia de `6f333676`) ao lado do de
DEPOIS, desliga o cache nos dois (`_cache_get/_cache_put/_cache_calc` e `vinculos._cache` viram passagem),
aponta `RAIZ` para `~/JFN` (bancos reais, só leitura, cwd `~/JFN`) e compara o JSON (status + corpo).

| Módulo | Chamadas | Resultado |
|---|---|---|
| investigacao | 27 (sugestões ×2, fachada/revisar, certames ×3 incl. 400, conluio, laranjas, perícias ×2, perfil ×2 incl. 400, TAC, imprensa, sanções, pcrj comissionados/fantasmas/gastos/aditivos/íntegras ×3, restritos, flags, frescor, graph, grafo_familias) | 27 iguais |
| vinculos | 20 (resolução, patrimônio, agente público, osint×processos, elos, cocontato, assinaturas, concentração ×2, detectores, zeros, leitura dupla, emergência, fila do fiscal ×2) | 20 iguais |
| sistema | /siafe/stats, /sweeps/status, /tac/ranking, /sistema/atividade | iguais (atividade: só `atividade_s`, idade em segundos, muda entre chamadas) |
| produtos | /api/responsaveis ×3 (incl. 400) | iguais |

Limites da comparação, declarados: (1) as rotas cujo código ANTES calculava a raiz por `__file__`
(`fiscal_fila`, `tac/ranking`) foram comparadas com a cópia antiga posta dentro do worktree, para as duas
raízes coincidirem; (2) rotas que ESCREVEM não foram chamadas contra o `data/` real — `/sweeps/pausar|retomar`
e a pausa do relatório foram verificadas em pasta temporária (relatório sozinho cria e apaga as 3 flags;
pausa do painel antes/durante sobrevive; `touch` de script sobrevive) e `_encerrar` contra um processo-isca
(SIGTERM por PID, só o alvo); (3) os produtos PPP/triagem (`db_path` relativo removido) não foram rodados:
`dossie_ppp`/`triagem_ppp` fazem DDL no `pcrj.db` ao abrir — equivalência por leitura (`db.conectar(None)` →
`DB_PATH = <raiz>/data/pcrj.db`, o mesmo arquivo que `data/pcrj.db` com o cwd `~/JFN` do `jfn.service`);
(4) `vinculos._cache` não guardar falha foi verificado direto (falha recalcula; sucesso e lista ficam).
`gitnexus detect_changes`: risco "critical" — os símbolos tocados são handlers HTTP (pontas de muitos fluxos);
a mitigação é a comparação acima.
