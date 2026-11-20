# Decision log — untangle de `compliance_agent/collectors/` (20/11/2026)

Escopo: os 34 arquivos de `compliance_agent/collectors/`. Escolhas do dono: **Comentários = sim** (saem só os
que repetem o código; medição datada, decisão do dono, fato externo e porquê de workaround ficam — nos
coletores eles são memória de falha), **Testes = não**. Regras da casa acima da skill: formato das tabelas
gravadas e dos JSON lidos por outros não muda; comportamento igual salvo defeito provado; validação empírica
antes × depois com dado já gravado (sem coleta de rede); um commit por lote.

Foco pedido: falha de fonte que vira 0 ou "ok" (INDISPONÍVEL ≠ 0), `except` que engole, retry sem limite,
caminho de banco/arquivo recalculado em vários lugares, parser copiado, gravação sem escrita atômica.

Formato: o fix fica acima dos problemas que resolve. `[feito]` = aplicado nesta passada; `[pendente]` =
precisa de decisão do dono, de coleta real para validar, ou é redesenho; `[fora do escopo]` = anotado só.

Validação empírica: as versões ANTIGAS dos coletores foram extraídas do commit-base (`3947271c`) e rodadas
lado a lado com as novas, sobre dado real já gravado (cache do TFE em `data/tfe_cache/`, só leitura).

## 1. Uma régua de leitura de célula: `collectors/formato.py`  `[feito]`

`valor_br` (planilha/tela BR: ponto é sempre milhar), `valor_br_ou_ponto` (fonte que mistura número de API
com texto BR) e `so_digitos`. As duas réguas devolvem **None** quando a célula não é número; o coletor que
historicamente grava 0.0 escreve `valor_br(x) or 0.0` à vista (ou um `_num` de uma linha com o porquê) —
o defeito fica nomeado no chamador, não escondido no parser.

- Treze cópias do parser de valor, cada uma com sua semântica (tirava "R$" ou não; 0.0 ou None na falha;
  ponto sempre milhar ou só com vírgula):
  - `tfe_aberto._money` (0.0), `tfe_ob._money` (None), `tfe_receita._num` (0.0, filtra lixo),
    `siafe_ob._parse_money` (None, filtra lixo), `tse._parse_value` (0.0), `transparency._parse_valor`
    (0.0, tira "R$"), `folha_dprj._num` / `folha_mprj._num` (ponto só com vírgula, 0.0),
    `folha_tjrj._num` (portão por regex, 0.0), `tcerj_aberto._fnum` (ponto só com vírgula, None),
    `tce._extract_valor_debito` (laço com `float(...)`), `alerj_transparencia._f` (levanta).
  - `siafe_ob._parse_money` e `tfe_receita._num` filtravam todo caractere não numérico antes de converter:
    "GREEN4T SOLUCOES TI SA" virava **4.0** e "Lei 1.234, art 5" virava 1234.5. A régua nova exige que o
    que sobra (sem "R$" e espaços) SEJA um número BR; senão None. **Exceção (§6):** o `siafe_ob` mantém o
    filtro antes da régua (`_valor_tela`) — a tela pode trazer sufixo/sinal ("1.234,56 D") e, sem o SIAFE
    (sessão única), não há como medir o que ela renderiza.
  - `folha_tjrj._num` recusava ",65" (centavos sem zero à esquerda, formato que o próprio TFE publica em
    2017) e gravava 0.0.
- Mantidos fora (não são cópia): `tcerj_licitantes._float` (número de API, `float()` puro), o parser inline
  de `caged.py:414` e `terceirizados._parse_remuneracao` (só em funções sem chamador — ver §4).

Validação: 336.532 células reais (Valor OB de 2017 e 2025 do `fornecedor_ob.zip`; empenhado/liquidado/pago
do `tfe_despesa_2025.csv`), 143.874 valores distintos, rodadas na cópia antiga e na régua nova como cada
chamador a usa: **0 divergências** em `tfe_aberto`, `tfe_ob`, `tse`, `transparency`, `folha_dprj`,
`folha_mprj`, `tcerj_aberto`, `tce`, `siafe_ob` (após §6); 1 em `tfe_receita` (o "GREEN4T…": 4.0 → None) e 81 em
`folha_tjrj` (",65" → 0,65; a TJRJ não tem esse dado, é a régua que melhorou). No sintético, as únicas
diferenças são entradas que antes falhavam ("R$ 1.234,56" → 1234.56; "nan" texto → None/0.0).
Por módulo: `tfe_aberto.resumo(2025)` idêntico (15.428 linhas, pago R$ 51.505.223.470,84);
`tfe_ob.parse_ano` + valor idênticos em 2017 (97.262 OB), 2021 (124.707) e 2025 (192.986).

Achado de dado (não é do código): o `fornecedor_ob2021.csv` tem 19 linhas e o `2025` tem 28 cujo "Valor OB"
não é número (colunas deslocadas — ex.: o nome do credor no lugar do valor). Elas já entravam com `valor`
NULL e continuam assim.

## 2. Onde e como o coletor grava: `collectors/arquivos.py`  `[feito]`

`caminho_db()` (argumento > `JFN_DB` > `JFN_DATA_DIR/compliance.db` > `<repo>/data/compliance.db`, resolvido
na CHAMADA), `dir_dados()`, `abrir_banco()` (conexão de escrita com `timeout=60`, a lição de 09/08 já cravada
em `tests/test_escritores_esperam_o_lock.py`) e `gravar_atomico()` (temporário ao lado + `os.replace`).

- Caminho do banco recalculado em 12 lugares, com 4 convenções:
  - `Path(__file__)…/data/compliance.db` em `folha_dprj`, `folha_mprj`, `folha_tjrj`, `folha_orquestrador`,
    `folha_estado`, `tfe_receita` (ignoravam `JFN_DB` — sob o conftest, escreveriam no banco de produção);
  - `JFN_DATA_DIR` em `tfe_ob` e `tfe_aberto` (este recalculava de novo dentro de `ingest_db`);
  - `JFN_DB` lido no IMPORT em `tcerj_aberto` (o monkeypatch do conftest chega tarde);
  - string relativa `"data/compliance.db"` em `atas_julgamento:267`, `pncp:989`, `pncp_resultados:348,609`
    (só acerta se quem chama fizer `cd ~/JFN`).
- Pastas de cache relativas ao cwd: `ceis` (`Path("data")`), `beneficios_sociais`, `sei_portal` e `sei_cdp`
  (`data/sei_cache`), `tse` (`data/tse_cache`), o dump de depuração do `sei_cdp` (`data/tmp`). `doerj` e
  `folha_estado` ancoravam no repo — a mesma pasta, por outra conta.
- Conexão de escrita sem `timeout` (desiste em 5 s): `folha_dprj`, `folha_mprj`, `tfe_ob`, `tfe_aberto`,
  `tfe_receita`, `tcerj_aberto`.
- Escrita não atômica de arquivo que alguém relê:
  - `sei_cdp` (`cdp_*.json`, 2 lugares) e `sei_portal` (`*.json` e `doc_*.txt`) — o cache é lido por
    `sei/relacionados.py` e `tools/bombeiros_integra_supervisor.py`; truncado, vira JSON inválido ou, no
    `doc_*.txt`, TEXTO PARCIAL servido como documento inteiro por 7 dias;
  - `tse` (zip reaproveitado se existe), `tfe_receita` (CSV em streaming reaproveitado se > 1.000 bytes —
    download interrompido virava cache);
  - `ceis`/`beneficios_sociais` (cache de 7 dias compartilhado), `doerj` (aprendizado e diagnóstico).
  - `folha_estado._salvar_progresso` já era atômico à mão: passa a usar a mesma função.

Validação: em configuração de produção (`JFN_DATA_DIR=/home/ubuntu/JFN/data`, sem `JFN_DB`) os 14 caminhos
resolvem para o mesmo arquivo de antes; `JFN_DB` passa a valer na chamada. Leitura real antes × depois:
`folha_orquestrador._total_por_orgao()` idêntico; `pncp_resultados.conluio_do_orgao` idêntico.

## 3. Falha de fonte que virava zero, vazio ou "ok"  `[feito]`

Uma régua só por família: **a leitura distingue "a fonte disse que não há" de "não consegui ler"**, e quem
grava/resume só afirma o primeiro. Onde havia cópias da leitura, ficou uma.

- `formato.csv_apos_preambulo` (CSV do TFE com linhas de título): sem o cabeçalho, levanta.
  - `tfe_ob.parse_ano` e `tfe_aberto._rows` caíam na linha 0 (`next(..., 0)`): layout novo ou página de
    erro virava dicionários sem colunas. No `tfe_ob` todas as OB eram puladas e o `ingest` APAGAVA o
    exercício inteiro, registrando cada OB em `ob_retirada` como "despublicada pela fonte" — e saía 0.
    Guarda extra: `ingest` com zero OB legível levanta antes do DELETE.
  - `tfe_aberto.baixar_ano` gravava o corpo sem olhar o status (403/WAF viravam `tfe_despesa_AAAA.csv`,
    reaproveitado para sempre por ter > 1.000 bytes). Agora `raise_for_status`, valida o cabeçalho e grava
    atômico.
- `folha_orquestrador.rodar` devolvia `"ok": True` fixo. Agora `ok` = nenhuma fonte fora do ar, com exceção
  ou com `ok=False`; a lista sai em `falhas`. **Reaplicado às 138 rodadas reais de
  `data/folha_orquestrador.log`: as 138 diziam ok; com a régua, 0 — MPRJ falhou em 138, TJRJ em 82,
  Executivo em 21.** (O SLO de `config/pipelines.yaml` vigia só o mtime do log — ver §6.)
  - `folha_dprj.coletar`: página do relatório sem checar status, e erro por arquivo só `print` → sempre
    `ok: True`. Agora `raise_for_status`, página sem links = `ok: False`, erros por arquivo listados.
- PNCP — `pncp_resultados._get_medido`: uma leitura com backoff para as três cópias (`_consulta`,
  `_resultado_item`, `_consulta_itens`); 204/404 = "não há" (None), 5xx/4xx/tentativas esgotadas =
  `PncpIndisponivel`. Antes as três devolviam o mesmo None/[] do "não há": página de contratações que
  falhava encerrava o mês × modalidade calada; item cujo resultado falhava entrava como item sem
  vencedor. Agora contados em `paginas_indisponiveis`, `certames_itens_indisponiveis`,
  `itens_resultado_indisponivel` (backfill: `indisponiveis`).
  - `gravados += con.total_changes and 1 or 0` (2 lugares): `total_changes` é cumulativo da conexão;
    depois da 1ª escrita contava toda linha processada. Agora `cur.rowcount`.
- PNCP — termos aditivos: `_termos_medidos` vira a única leitura e `_gravar_termos` o único gravador de
  `contrato_aditivo` (eram 3 cópias do INSERT; o próprio código registrava que uma quase ficou para trás).
  - `coletar_contratos_estado` usava `termos_contrato` ([] na falha) e marcava `aditivos_checados=1,
    num_aditivos=0`: contrato com leitura falha virava "medido, sem aditivo" e nunca mais era relido. A
    coleta municipal já distinguia (19/11); a estadual ficou para trás. Agora falha = pendente + `falhas`.
    `termos_contrato` saiu (sem outro chamador; `detectores/x8_aditivo_retroativo.py:105` ainda o cita em
    texto de proveniência — ver §7).
- `tcerj_aberto._fetch`: depois de 4 tentativas devolvia [] — o mesmo que "acabaram as páginas"; a carga
  parava no meio e o cron imprimia o parcial como base inteira. Agora levanta; o CLI marca a base como
  `INDISPONIVEL` e sai 1. `stats.cnt` deixava COUNT falho virar 0 (as tabelas acabam de ser criadas por
  `_ddl`; falha ali é erro). JSON que não é lista continua sendo "fim" (sem evidência do que a API devolve
  no fim da paginação).
- Portal da Transparência — `collectors/portal_transparencia.py` (`consultar`, `chave`): `ceis._consultar`
  e `beneficios_sociais._get` eram a mesma função copiada.
  - HTTP 200 com corpo que não é a lista (WAF, JSON de erro) virava "consultado, nada achado" — empresa
    "não sancionada", CPF "não recebe" — e ia para o cache de 7 dias. Agora INDISPONÍVEL.
  - Falha PARCIAL (um cadastro não respondeu) saía `verificado=True` + "parcial" e ia para o cache. Agora:
    sem achado e com erro = INDISPONÍVEL (não cacheia); com achado = verificado (achado é prova).
  - `ceis.atualizar_cache_sancoes` chamava `_consultar` com 4 argumentos (faltava `param`): o TypeError
    caía no except e o probe de saúde avisava ❌ no Telegram SEMPRE.
  - `vigente = data_fim >= hoje.strftime("%d/%m/%Y")` comparava TEXTO dd/mm/aaaa — pelo dia do mês
    ("05/01/2030" < "20/11/2026"). Agora `_vigente` compara data.

Validação (script com controle positivo e negativo, sem rede): `tfe_aberto._rows` no CSV real = 15.428
linhas (igual); CSV de WAF/vazio levanta; `tfe_ob.ingest` sem OB legível levanta e mantém o exercício num
banco temporário; `consultar` com 200-HTML e 200-JSON-estranho → INDISPONÍVEL; CEIS/benefícios parcial
sem achado → INDISPONÍVEL e com achado → verificado; `_vigente` com 05/01/2030 e 25/12/2025; PNCP 503 na
página → contado; `_gravar_certame` com item 500 → 2 gravados + 1 indisponível e a 2ª passada conta 2
(antes contaria o acumulado); contratos do Estado com termo ilegível ficam `aditivos_checados=0`;
`folha_dprj` sem links → `ok=False`.

Medido no banco (só leitura): 12.326 dos 13.455 contratos `pncp_estado` estão `aditivos_checados=1` com
0 aditivos. Quantos deles foram falha de rede gravada como "sem aditivo" não se sabe mais — ver §7.

## 4. Código sem chamador (sobra)  `[feito]`

Conferido por `grep -w` em `.py/.yaml/.sh/.json/.js` do repo inteiro (inclusive `capabilities.yaml` e o
despacho por nome do `agent.py`); o índice GitNexus não existe no worktree, então a prova é o grep.
Saíram ~1.300 linhas, nenhuma com chamador:

- `sei_captcha_crawler.py` (módulo inteiro; criava `data/tmp/sei_captchas` relativo ao cwd no IMPORT).
- `terceirizados`: os três coletores (`buscar_terceirizados_transparencia`, `buscar_bolsistas_faperj`,
  `buscar_estagiarios` — quase cópias entre si), `verificar_mei_e_clt`, `gerar_pedido_lai`,
  `cruzar_com_folha_principal`, `COMBINACOES_ILEGAIS`, `_parse_remuneracao` (só usado por eles; era o
  parser que lia `str(3200.5)` como 32005 — ×10), e os helpers/URLs que só eles usavam. Fica
  `detectar_cpf_duplicado_entre_fontes` (chamado por `rules/engine` e `agent`); a docstring do módulo
  passa a dizer que ele não coleta.
- `caged.verificar_clt_publico` (transformava `remuneracao_bruta == 0` — que o parser grava quando a célula
  é ilegível — em alerta de "fantasma") e `ACUMULACAO_PERMITIDA`.
- `pncp.monitorar_licitacoes_rj`, `buscar_licitacoes_orgao`, `ORGAOS_RJ` (seis CNPJs, dois diferindo só no
  último dígito — `…000103`/`…000104` — sem fonte).
- `siafe_ob.collect_ob_day` (duplicava a conexão CDP de `run_daily_collection`) e `_JS_OPEN_FIRST_OB`.
- `lexml_fetcher.buscar_artigo_planalto`, `texto_lei_resumido`; `tce.verificar_sancionados` (engolia tudo e
  devolvia parcial); `cnpj.buscar_varios_cnpjs`; `sei_cdp.ler_processo_sei_launch` (segundo leitor SEI
  que seguia sem captcha resolvido e cacheava o formulário 24 h); `sei_portal.cruzar_sei_siafe`;
  `transparency.buscar_folha_orgao`, `buscar_licitacoes`, `_parse_licitacoes`, `salvar_servidores`.
- `doerj._inferir_secao`: 7 linhas inalcançáveis depois do `return "I"` (a versão anterior da regra).

Mantidos de propósito: `folha_orquestrador._FONTES_MAPEADAS` (sem leitor, mas é o mapa de reconhecimento
de 16/07 pedido pelo dono — memória, não código); `datajud` (sem chamador de produção, mas é biblioteca com
testes próprios); `beneficios_sociais.investigar_pessoa` (usado pelo `__main__`).

Validação: todos os módulos de `collectors/` e os importadores (`agent`, `scheduler`, `rules.engine`,
`tools.contratos_parecer`) importam; 312 testes dos arquivos que importam `collectors` passam.

## 5. Busca que falha deixa de virar "nada encontrado" em dossiê e cron  `[feito]`

Mesma régua do §3, nos coletores cujo resultado vai para texto (dossiê, LLM, Telegram): a leitura medida
devolve `(ok, lista)`; a função pública que os testes fixam como "falha → [] com log" continua igual, e quem
AFIRMA ausência passa a usar a medida.

- `querido_diario.historico_empresa`: API fora → `total_publicacoes: 0, tem_sancao_historica: False`, que o
  dossiê (`tools/lex_pesquisa_internet`) publicava como "nada no DOERJ" — e a API não responde da VM-1 nem
  do it-campo (`tools/desmascarar_cpf_externo.py:50`), ou seja, era o caso comum. Agora levanta; os dois
  chamadores já têm `except` que registra o erro (`erros: querido_diario …`, `Querido Diário: …`).
  `buscar_historico` mantém "falha → []" (contrato de `tests/test_querido_diario.py`). `buscar_pessoa`
  (repasse sem chamador) saiu.
- `web_research.investigar`: busca DuckDuckGo com HTTP ≠ 200 ou rede fora virava `web: []` e o resumo
  "Nada de risco evidente encontrado na busca web" (chamadores: scheduler, orquestrador, Telegram, hermes).
  Agora `web_indisponivel=True`, o prompt do LLM recebe "INDISPONÍVEL" em vez de "nada" e o resumo sem LLM
  diz "Busca web INDISPONÍVEL — sem resultado não quer dizer sem risco".
- `doerj` (cron 06:50/12:40): CDP fora devolvia [] — igual a "dia sem diário" — e o `__main__` saía 0.
  `coletar_data` passa a expor `erros_ultima_coleta`; o `__main__` com 0 publicações E erro imprime
  `INDISPONIVEL` e sai 1. No `doerj_cron.log` atual não há nenhum "Avisos em" nem CDP fora: os 16 dias com
  0 publicações são domingos/feriados ("nenhuma edição encontrada") — comportamento igual para eles.

Validação (sem rede real; CDP apontado para porta fechada): Querido Diário fora → `buscar_historico` = []
e `historico_empresa` levanta; com resposta válida, resultado igual ao de antes; busca web fora → resumo
INDISPONÍVEL; busca ok e vazia → texto de antes; DOERJ com CDP fora → [] + `erros_ultima_coleta`.

## 6. Segunda volta (revisão independente, etapa 5 da skill)  `[feito]`

Um revisor sem acesso a este log leu o diff inteiro e o que sobrou em `collectors/`. Nenhuma referência
pendurada a símbolo removido. Regressões que ele achou nos lotes acima, corrigidas:

- `pncp._termos_medidos` só pegava `ValueError`: 200 com um dict no corpo iterava as chaves e
  `_parse_termo(str)` levantava `AttributeError`, derrubando a rodada INTEIRA (`coletar_aditivos` em
  `tools/contratos_parecer`, fase 2 do Estado) — o `termos_contrato` antigo engolia tudo. Agora corpo que
  não é lista de dicts = `(False, [])`.
- `pncp_resultados._get_medido`: 200 com HTML levantava `ValueError` (não `PncpIndisponivel`) e abortava a
  carga. Agora é `PncpIndisponivel`.
- `tools/pncp_backfill_unidade.backfill_bulk` chama `_consulta` sem tratar a nova exceção: passava a morrer
  na 1ª falha. Agora conta `paginas_indisponiveis` e segue (única linha fora de `collectors/` tocada).
- `querido_diario.enriquecer_obs_com_historico`: com `historico_empresa` levantando, a 1ª falha saía sem o
  `commit` dos alertas já feitos. Agora para o laço (os demais nomes falhariam igual), avisa quantos ficaram
  sem consulta e grava o que já tinha.
- `tce._extract_valor_debito`: o regex leva o ponto final da frase ("R$ 1.234,56."); a régua estrita
  devolvia None. `rstrip(".,")` antes.
- `siafe_ob`: ver exceção do §1 (`_valor_tela`). Antigo × novo sobre os 143.903 valores do corpus:
  0 divergências.
- `arquivos.gravar_atomico` usava `.{nome}.{pid}.tmp`: duas threads do mesmo processo (rotas no
  threadpool) dividiriam o temporário. Agora `mkstemp` (com `chmod 0644`, o modo de antes). Testado com 6
  threads × 50 gravações no mesmo destino: sem erro, arquivo inteiro, sem temporário sobrando.

Também apontado e anotado no §7 (não é regressão; é o que sobra).

## 7. Pendente — decisão do dono, coleta real para validar, ou redesenho  `[pendente]`

- **Dado já gravado com a falha antiga** (não mexido — apagar/recoletar dado é decisão do dono):
  - 12.326 de 13.455 contratos `pncp_estado` estão `aditivos_checados=1` com 0 aditivos; parte pode ser
    falha de rede gravada como "sem aditivo" (§3). Recoletar = `UPDATE pcrj_contratos SET
    aditivos_checados=0 WHERE fonte='pncp_estado' AND num_aditivos=0` + `coletar_contratos_estado
    --so-aditivos` (≈12 mil chamadas ao PNCP, ~1 h com a pausa de 0,3 s).
  - `data/beneficios_cache.json` tem uma entrada PEP de CPF de TESTE com nome "X" marcada `eh_pep: true`
    (gravada em 15/11): teste que não isola o cache escreveu no arquivo de produção (o caminho era relativo
    ao cwd; continua sendo `<repo>/data` quando a suíte roda sem `JFN_DATA_DIR`). Servida por 7 dias a
    quem consultar aquele CPF. Apagar a chave e fazer o conftest apontar `JFN_DATA_DIR` para tmp.
  - Entradas "parcial" antigas nos caches de sanção/benefício expiram sozinhas em 7 dias (hoje: 0 no
    `sancoes_cache.json`).
- **SLO da folha cego**: `config/pipelines.yaml` (folha-orquestrador) vigia o mtime do log, que é escrito
  em toda rodada. Com o `ok` honesto (§3), trocar por `consulta: SELECT MAX(created_at) FROM
  registros_folha` (a lição de 28/07 do siafe-runner). Fora do escopo `collectors/`.
- **`siafe_ob.run_daily_collection`** (chamado por `scheduler.py:472` e `hermes_goal.py`): o merge de
  detalhes busca `numero_ob + data_emissao=target_date`, mas a linha foi gravada com a data da própria OB
  (OB de outra data nunca recebe detalhe); e quando o JS de seleção não acha a linha, ainda clica
  "Visualizar" na linha que estiver selecionada — detalhe de uma OB gravado em outra. Exige o SIAFE para
  validar (sessão única por IP, coleta rodando): não mexido.
- **LGPD — CPF completo em título/descrição de alerta**: `terceirizados.detectar_cpf_duplicado_entre_fontes`
  (título "CPF em múltiplas fontes… — {cpf}") e `caged.cruzar_folhas_multiplas`. Título é identidade do
  alerta (regravar muda dedup e histórico); mascarar é decisão do dono, com regravação.
- **Credencial no código**: `folha_mprj._BASIC` (client id/secret OAuth do gateway CNMP115 em base64). Mover
  para `.env` exige o dono pôr a variável lá antes (senão o coletor para); já está no histórico do git.
- `folha_tjrj`: dedup por `(nome, cargo)` em TODAS as competências (mês novo de servidor antigo nunca entra)
  e `lotação` gravada na coluna `vinculo`. Corrigir muda o conteúdo da tabela — decisão do dono.
- `tse.importar_doacoes`: chave de dedup sem o valor (doações repetidas do mesmo doador ao mesmo
  candidato no ano se perdem) e falha de download → 0 importados com HTTP 200 na rota.
- `caged.buscar_servidor_federal`: falha devolve `found: False` e o cruzamento rebaixa a severidade de
  "alta" para "média" como se a pessoa não fosse federal.
- `folha_estado.ultima_competencia`: falha da API é tratada como "competência sem registro" e o coletor
  pode recuar para o mês anterior.
- `atas_julgamento`: 200 com HTML no lugar do PDF vira `texto_vazio` (não transitório, 30 dias sem
  revisitar).
- `lexml_fetcher`: `buscar_tcu` devolve [] para o 200-WAF conhecido do TCU; `buscar_tce_rj` troca a busca
  online pela base local e `formatar_resultado_juridico` rotula como "online"; `_RE_WAF` inclui "senado
  federal", que aparece em JSON legítimo. Os chamadores (Telegram, scheduler, mandato) não leem
  `status_lexml()`. Corrigir pede mudar o contrato com 4 chamadores fora de `collectors/`.
- `transparency` (tools do agente LLM): nenhum método olha o status HTTP; 403/500/WAF viram [] ou
  `[{"error": …}]` com cara de linha de dado. Idem `tce.buscar_decisoes_tce` → "nenhuma decisão".
- `sei_portal`/`sei_cdp`: página de WAF com 200 sem `erro`, captcha não resolvido sem `erro`, e TODO
  resultado (inclusive erro) cacheado por 24 h; `submit_sei_search` devolve `ok: True` com captcha
  recusado. O SEI tem leitor canônico (`tools/sei_consultar`/`sei_reader`); estes caminhos são legado
  com 2 chamadores — aposentar ou consertar é decisão.
- `doerj.coletar_data`: página de edição não reconhecida é gravada como publicação "Página de edição"
  (0 linhas assim no banco hoje — sem prova de dano, não mexido).
- Números de processo SEI: ~8 normalizadores/regex diferentes no repo (`doerj.extrair_processos_sei` é o
  mais completo e testado). Unificar atravessa `sei/`, `correlacao_sei`, `pericia_contabil`, `tools/` —
  fora de `collectors/`.
- `pncp.verificar_obs_sem_pncp` (chamado pelo scheduler): nunca adiciona alerta (lista sempre vazia), mas
  faz 1 chamada HTTP + 0,3 s por CNPJ. "Construído, nunca produz" — aposentar ou religar.

- Ainda "falha → []" em caminho VIVO (achado na revisão; cada um muda contrato com chamador fora de
  `collectors/`): `pncp.buscar_contratacoes` (sem retry; `/api/pncp`, radar, direcionamento),
  `pncp.buscar_contratos_fornecedor` (rota devolve `n: 0`), `pncp.buscar_itens` e `baixar_documentos`
  (dossiê/parecer), `tcerj_licitantes.coletar` (página falha encerra o gerador), `caged.cruzar_folhas_multiplas`
  e `terceirizados.detectar_cpf_duplicado_entre_fontes` (exceção → [] ou parcial), `web_research.buscar_noticias`.
- Resumo honesto, código de saída não: `folha_orquestrador` e `pncp_resultados` imprimem `ok:false` /
  `paginas_indisponiveis` mas saem 0; `folha_mprj` dá `ok` com UMA competência respondendo; `folha_tjrj`
  cai para um mês anterior e diz `ok`; `doerj.coletar_data` com página não reconhecida devolve lista não
  vazia + erro (o `__main__` sai 0); os chamadores vivos do DOERJ (scheduler, Telegram, hermes) ainda não
  leem `erros_ultima_coleta`. `ceis.verificar_obs_contra_sancoes` pula INDISPONÍVEL sem contar.
- `folha_estado`: `float(x or 0)` grava 0.0 para vantagem/líquido/desconto AUSENTE (deveria ser NULL —
  muda o conteúdo da tabela). `tfe_ob.ingest`: "Data da OB" ilegível vira `{ano}-01-01` inventado.
- PNCP termos: 404 permanente fica pendente para sempre e ocupa as vagas de `limite_termos` (separar
  "sumiu" de falha transitória).
- `scheduler.py:181` importa `pncp.verificar_contrato_pncp`, que não existe no repo nem no histórico: o
  `ImportError` cai num log debug e a checagem "contrato não publicado no PNCP" nunca roda.
- Gravar atômico não chegou a: `alerj_transparencia.baixar_pdf` (sem chamador de produção; o retorno já
  confere `%PDF`) e o dump de depuração `sei_last_search.*` do `sei_cdp`.

## 8. Fora do escopo (anotado, não mexido)

- `detectores/x8_aditivo_retroativo.py:105` cita `collectors.pncp.termos_contrato` em texto de
  proveniência; a leitura agora é `_termos_medidos`. É texto de evidência gravado — não alterado.
- O pre-commit deste worktree avisa "validate/gen capabilities falhou" e "ruff ausente" em todos os
  commits (ambiente do worktree; nenhum arquivo de capacidades foi tocado). O lint foi rodado à mão
  (`ruff --select F` limpo em `collectors/`).
- GitNexus: o índice não existe no worktree (`.gitnexus/` ausente); impacto e chamadores foram conferidos
  por grep no repo inteiro e por import de todos os módulos.
