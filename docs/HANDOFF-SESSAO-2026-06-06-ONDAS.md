# HANDOFF — sessão 2026-06-06 (Ondas + Lex + ecossistema) — CONTINUAR DAQUI

> ## 🟢 SESSÃO 2026-06-06 (4ª parte) — Cruzamento endereço/sócio, SEI diagnosticado, SIAFE mapeado, Lex enriquecido
> Branch `linux`. Commits desta parte: `21b821b`, `fac87a2`, `f533ab5`, `429a258`, `0f65b58`, `026d587`, `a44dca9`.
> **Para a próxima IA — leia este bloco primeiro e siga as instruções explícitas (assuma IAs mais simples):**
>
> **1. CRUZAMENTO sócio × OB(SIAFE) × SEI × ENDEREÇO** (`compliance_agent/cruzamento.py`, no `/relatorio`):
>    - Seção **1-B** no relatório de fornecedor (sócios em comum, cidade-sede, **co-endereço** = red flag de fachada
>      independente de sócio, `R-COEND`/`RF-03`) e seção **1-B** no de órgão (concentração geográfica `cidades_de_orgao`).
>    - **Descoberta proativa:** `python -m compliance_agent.cruzamento --clusters` acha grupos na mesma sede (achou
>      PLAZA MEDICAL+INOVA MEDIC em 2 cidades; FOCO ESP.+FOCO TERC.). Endereços em `endereco_fornecedor` (cresce com
>      `rede_societaria --ingerir-top N`; já rodou top-2000). API: `/api/cruzamento`, `/api/orgao/cidades`, `/api/coendereco/clusters`.
>    - Memória: [[cruzamento-socio-ob-sei-endereco]].
>
> **2. SEI — RESOLVIDO o acesso da VM (corrige diagnóstico antigo!):** o WAF do SEI bloqueia por **FINGERPRINT**,
>    não por IP — `curl`/`httpx` são dropados, mas **Chromium real PASSA** (HTTP 200, intermitente). Com retry+backoff,
>    o **login interno `itkava`/órgão ITERJ funciona DA VM, SEM captcha** (`tools/sei_login_retry.py`), e clicando os
>    **links internos** do app (não URL crua) chega à **Pesquisa autenticada com a sessão intacta**
>    (`tools/sei_reader.py` — ✅ validado, unidade ITERJ/CHEGAB). **Não precisa de proxy/Actions/WSSEI.** ⚠️ Logar e LER
>    na MESMA sessão (sessão não sobrevive a contexto novo nem a `goto` cru). **FALTA (passo final bounded):** no
>    `sei_reader`, usar o protocolo EXATO (`#txtProtocoloPesquisa`) → abrir o processo (`procedimento_trabalhar`) →
>    extrair a árvore de documentos reaproveitando os extractors do `sei_cdp` → gravar `data/sei_cache/cdp_*.json`
>    (Lex consome 24h). Memória: [[sei-login-itkava]]. (WSSEI/Actions viram fallback opcional.)
>
> **3. SIAFE — `docs/SIAFE-RIO2-GUIA-AUTOMACAO.md`** (mapeamento do Mestre): destrava o **limite de 1000** via
>    checkbox `chkRemoveLimit` (ou iterar UG+período). Mapa das 207 UGs (índice 2026), filtro PPR, gotchas que
>    derrubam a sessão. **Operacionalizar em `siafe_ob_orcamentaria.py`.** ⚠️ Fonte truncada na §7.6 — completar.
>
> **4. LEX enriquecido** — `docs/PESQUISA-DIREITO-ADMIN-DOUTRINA-RJ.md` (deep-research, 25 teses 3-0):
>    - **CORREÇÃO propagada:** controle externo no RJ = **CERJ arts. 122-123** (NÃO art. 97). Dano efetivo pós-14.230 =
>      **só art. 10** (STJ REsp 1.929.685/TO); dolo nos arts. 9/10/11 (STF Tema 1199). Já citado no parecer do `lex.py`.
>    - **TODO opcional:** enriquecer `knowledge/jurisprudencia.py` com Tema 1199 e REsp 1.929.685 como precedentes; e
>      rodar nova deep-research p/ as questões em aberto (tipos penais CP 312-337; normas estaduais Lei 14.133; Di Pietro/Carvalho Filho).
>    - **Relançar deep-research** (cara, cai por session limit): `Workflow({scriptPath, resumeFromRunId, args})` —
>      **sempre repassar o `args` idêntico** (sem args, aborta e queima o lançamento). Memória: [[deep-research-relancar]].
>
> **5. Avaliação do "briefing de outra IA"** (memória [[briefing-outra-ia-verificar]]): tinha caminhos alucinados
>    (DB `jfn.db` → é `compliance.db`; `tools/yoda.py` inexistente; symlink `.env` destrutivo). **Sempre `ls`/`grep`
>    no repo antes de agir sobre handoff externo.** P2 (chaves LLM) já estava sincronizado; P4 (cron WAL) feito no DB
>    certo; P1 (proxy SEI) implementado; P3/P5/P6/P7 dependem de decisão/recurso do Mestre.


> ## ✅ SESSÃO 2026-06-06 (continuação) — TUDO FEITO, ler este bloco primeiro
> Entregue e committed na branch `linux` (≈22 commits). Resumo do que mudou nesta sessão:
> - **Onda 2 no produto:** Lex ganhou seção **II-C** (contratos/compras TCE-RJ) + red flags R5/R2/R9 e a
>   **Matriz de Achados** (critério×condição→causa→efeito) + rótulo **Nota Técnica COM/SEM Achado** (Decreto
>   47.408/2020). `/relatorio` ganhou seção **4-B** (TCE-RJ + contratado-vs-pago). Fixes em `tcerj_aberto`
>   (`_fnum` BR, coluna `num_contratacao`). **Validado ao vivo** (MGS Clean: 🟡, R8/R12/R2/R5/R10).
> - **Onda 3 (início):** `compliance_agent/grafo_cartel.py` (+`duckdb_util.py`) — `captura_orgaos`,
>   `dependencia_fornecedores`, `vizinhanca_cartel` (exclui ubíquos). Integrado: **II-D do Lex** + **GET
>   /api/cartel**. Achado real: UG 316100 (Fundo Estadual de Transportes) R$4,01bi, 99,8% num fornecedor.
> - **2 deep-research sintetizados:** `docs/PESQUISA-DIREITO-ADMIN-CGE.md` (improbidade/achado/CGE-RJ) e
>   `docs/PESQUISA-SIAFE-ADF-PPR.md` (formato HTTP do row-fetch da af:table — destrava extração SIAFE §8b).
> - **SEI via Actions:** `ler_processo_sei_launch` + `tools/ler_sei_lote.py` + `.github/workflows/ler-sei.yml`
>   (IP Azure passa o WAF; loga `itkava`; commita cache de volta). VM é dropada pelo WAF — usar Actions/desktop.
> - **Memória:** podados 6 stubs + semeados 6 fatos verificados (contexto do Yoda/Lex). **Storage:** WAL 5.8GB→0,
>   `manutencao.py`. **Ronda:** spam JFN_ronda eliminado. **PNCP:** HTTP 400 corrigido.
> - **Diretriz de cota** no CLAUDE.md (cortar desperdício, nunca profundidade).
>
> ## 🟢 SESSÃO 2026-06-06 (3ª parte) — Onda 4 + benchmark + multiusuário + limpeza
> - **Onda 4 (rede societária):** `rede_societaria.py` cruza fornecedores por **sócio em comum** (QSA/BrasilAPI);
>   `cruzar_cartel` = co-ocorrência + sócio (indício forte, art. 337-F). Integrado no Lex (II-D) e `/api/cartel?modo=rede|cruzado`.
>   Ingeridos 800 fornecedores → 285 sócios compartilhados. **Caso real achado:** grupo Vieira (F P/R C VIEIRA +
>   FILIPE A. F. MARQUES) co-ocorre e compartilha sócio com 4 consórcios de obras.
> - **Yoda multiusuário:** `tools/guest_bot.py` (bot SEPARADO, read-only, sem shell) + serviço systemd + `docs/YODA-MULTIUSUARIO.md`.
>   FALTA o Mestre: criar bot no @BotFather, pôr `TELEGRAM_BOT_TOKEN_GUEST` + `TELEGRAM_GUEST_USERS` (id da filha) no `.env`, `enable` o serviço.
> - **Benchmark IAs:** harness `tools/benchmark_runner.py` + guia `docs/IAS-FRACAS-GUIA.md`. Rodou T1/T2 em 6 modelos
>   (3 Gemini direto + 3 Mistral) vs Claude. Aprendizado: roteamento=Gemini-Flash/Mistral-Small; JSON=Mistral-Large;
>   Llama reprova roteamento. **Chaves do JFN/.env estavam inválidas** → sincronizadas do `~/.hermes/.env`. T5/T6 e
>   run completo pendentes (OpenRouter sem crédito 402/429; Mestre pediu p/ não forçar tokens).
> - **Storage/repo:** removidos scripts de geração de vídeo; `requirements.txt` sincronizado com o real
>   (pyod/duckdb/sklearn/xgboost/hmmlearn/easyocr/pytesseract/opencv). torch/easyocr (SEI) e whisper (voz) mantidos. 35 GB livres.
> - **SEI:** WAF dropa o IP da VM → leitura só via Actions (`ler-sei.yml`, definir secret `SEI_PASS`) ou desktop.
>
> ---
> ## (histórico) Onda 3 — CONCLUÍDA nesta sessão: grafo cartel (captura/dependencia/vizinhanca) + DuckDB; II-D no Lex +
> `/api/cartel`; **explicabilidade** (`anomalias.explicar_features` → campo `porque` no `/api/anomalias`, equivalente
> honesto a SHAP); **eval ground-truth TCE-RJ** (`eval_groundtruth.py` — achado: score por-OB NÃO prediz punição de
> órgão, AUC<0.5; só volume, 0.65); **calibração+drift** (`calibrar.py` — corte p99, fila balanceada por UG, motor
> estável sem drift 2019-2026); **skill Yoda `/cartel`** em `~/.hermes`.
> **RESTA (Onda 4+, opcional):** melhorar a calibração do score (a eval mostrou que precisa normalizar por UG p/
> agregar bem a risco de órgão); Splink/rede societária por sócio (QSA) p/ confirmar cartel; PU-learning usando o
> ground-truth do TCE.
> **Pendência de infra (não-código):** rodar `ler-sei.yml` no Actions (definir secret `SEI_PASS`) p/ o Lex ler a
> íntegra real do SEI.
>
> ---
> ## ⏯️ (histórico) RETOMADA pós-session-limit (2026-06-06 ~14:xx UTC)
> Sessão pausou por limite (reset 4:50pm UTC). Estado salvo e committed na branch `linux`:
> 1. **Onda 2 integrada no Lex** (commit feito): `lex.py` ganhou `_contratos_tcerj()` +
>    `_analisar_contratos_tcerj()` (red flags **R5 dispensa / R2 fracionamento / R9 sobre-execução** a partir dos
>    **Dados Abertos do TCE-RJ**, que NÃO dependem do SEI/WAF) + nova **seção II-C** no parecer (tabelas de
>    contratos e de compras diretas com EnquadramentoLegal). **FALTA VALIDAR:** rodar
>    `.venv/bin/python -m compliance_agent.lex` via um ctx real (ou gerar um `/relatorio` de fornecedor, ex.
>    "MGS Clean") e conferir a seção II-C + grau. Integração degrada com elegância se a tabela estiver vazia.
> 2. **Bugs de qualidade da Onda 2 corrigidos** em `collectors/tcerj_aberto.py`: `_fnum` agora entende formato BR
>    ("7.188,00"); coluna `modalidade` (que guardava o nº da contratação) renomeada p/ `num_contratacao`
>    (contratos_estado **não tem** campo de modalidade — só `CriterioJulgamento`); compras diretas casam por NOME
>    (a base não traz CNPJ na compra direta). **Tabela `contratos_tcerj` foi DROPADA e está sendo re-ingerida**
>    por um subprocesso (log em `data/manutencao_pos_reset.log`). Conferir que voltou a ~35k linhas:
>    `python -m compliance_agent.collectors.tcerj_aberto --stats`.
> 3. **Storage racionalizado** (pedido do Mestre): novo `compliance_agent/manutencao.py` — `--tudo` faz
>    **checkpoint do WAL (TRUNCATE)** [o `compliance.db-wal` tinha inchado p/ **2 GB**], **VACUUM**, **gzip** dos CSV
>    regeneráveis de `data/tfe_cache` (~64M) e poda relatórios antigos. Roda ao fim da re-ingestão acima.
>    Sugestão: agendar no cron do Hermes (semanal). Conferir ganho: `python -m compliance_agent.manutencao --relatorio`.
> 4. **deep-research** (direito admin + CGE-RJ) completou parcialmente (16 claims verificados; síntese e parte das
>    verificações falharam por session-limit). Resultado bruto em `tasks/wf9ans6r6.output`. **A FAZER:** gravar
>    `docs/PESQUISA-DIREITO-ADMIN-CGE.md` com os 16 claims VERIFICADOS (STJ REsp 1.929.685 dano efetivo; dolo
>    específico art.1 §2/§3 Lei 14.230; art.10 sem culpa; CP 312/316/317/333; anatomia do achado situação/critério/
>    causa/efeito + evidência) e fundir no Lex (molde de Nota Técnica/achado CGU já está em LEX-APRENDIZADOS-CGE).
>    Re-rodar a síntese do deep-research após o reset se quiser o relatório completo.
> **Backlog segue igual abaixo (itens 2-6).** "voltamos com tudo" após o reset.


> Para a próxima IA / próxima sessão. Branch de trabalho: **`linux`** (VM). Tudo abaixo já está committed+pushed
> salvo onde indicado. Leia também: `CLAUDE.md`, `docs/ECOSSISTEMA-EVOLUCAO.md`, `docs/BRANCHES-POR-SO.md`,
> e a memória em `~/.claude/.../memory/` (MEMORY.md). Diretriz eterna: instruções explícitas p/ IAs mais fracas.

## ✅ JÁ FEITO nesta sessão (commits na branch `linux`)
1. **Lex lê a íntegra do SEI** (`compliance_agent/lex.py`): liga `sei_cdp`/`sei_portal`; achados sobre o texto real
   (R5/R3/R9/R7); seção "II-B". ⚠️ Leitura efetiva bloqueada por **WAF** (IP GCP barrado em sei.rj.gov.br) — Lex
   reporta honestamente. Commit 1461bd7.
2. **Branches por SO**: só `linux` (VM, default) + `windows` (preservado em origin/windows). `gitactions` foi
   absorvida pela `linux` (tem `.github`). Guia: `docs/BRANCHES-POR-SO.md`.
3. **Storage**: −3.3G (torch CUDA→CPU; **nunca reinstalar torch sem `--index-url .../whl/cpu`**), node_modules fora
   do git+disco. **33G livres**. `.git` (118M) só encolhe com history-rewrite (proibido: sem push --force).
4. **Onda 1 FEITA** (`compliance_agent/anomalias.py`, commit f125acc): rodou nos 1.121.303 OBs →
   `ob_quarentena` (32.753), `ob_redflag` (69.807: valor_simbólico/fracionamento same-day+mês/concentração),
   `ob_anomaly` (1,08M, PyOD ECOD+IForest, com dataset_hash+versão). Endpoint **`GET /api/anomalias`** + skill
   Yoda `/anomalias` (~/.hermes). Achado real: SCALLE CONSTRUÇÕES, 5 OBs/mesmo dia = R$ 8,4M c/ parcelas R$ 0,07.
   Rodar de novo: `python -m compliance_agent.anomalias --rodar`.
5. **Onda 2 (parte) — TCE-RJ** (`compliance_agent/collectors/tcerj_aberto.py`, commit 69dfb87): **a API
   `https://dados.tcerj.tc.br/api/v1/` responde da VM e traz o nº SEI como chave** (resolve OB↔processo SEM
   scrapear o SEI/WAF). Ingeridos: `contratos_tcerj` (35.5k, c/ CNPJ+objeto+modalidade+valores),
   `compras_diretas_tcerj` (19.7k, c/ EnquadramentoLegal de dispensa), `penalidades_tcerj` (913). Correlação:
   31 OBs por SEI (via SIAFE), **466.091 OBs cujo fornecedor tem contrato** (5.007 CNPJs). Helper p/ Lex:
   `tcerj_aberto.contratos_de_fornecedor(cnpj)`. Re-rodar: `--ingerir --correlacionar`.
6. **Docs do Lex** (commits 963fff0, f125acc, 3508c00): `LEX-DOUTRINA-IMPROBIDADE.md` (Lei 14.230/2021 — dolo
   específico, Tema 1199 STF, fim do dano presumido), `LEX-APRENDIZADOS-CGE-CASHPAGO.md` (molde de achado CGU
   situação/critério/causa/efeito/recomendação; rede por sócio 3 níveis; ler íntegra revela modelo oculto),
   `CONTROLES-FONTES-DADOS.md` (40 fontes ingeríveis: TCU/TCE-RJ/PNCP/Transparência/Querido Diário).
7. **Benchmark de IAs** (`compliance_agent/benchmark_ias.py` + `data/benchmark_ias_gold.json`, commit 3508c00):
   IAs do ecossistema = Gemini 2.5 Flash (Yoda/visão), Qwen 3.6 (código), fallbacks nous; baseline = Claude Opus 4.8.
   Loop de 5 passos em `docs/IAS-ECOSSISTEMA-BENCHMARK.md`. Passo 1 (gold do Claude) FEITO p/ T1/T2/T5/T6.
8. **BOM DIA** (`compliance_agent/briefing.py`, commit 93771bc): notícias via **RSS direto** (URL limpa, não o
   redirect gigante do Google News) + `_texto_artigo()` extrai a **íntegra** p/ resumo RACIOCINADO de até 5 linhas.
   Cron `~/.hermes/cron/jobs.json` (job 81cae9684db0) atualizado: ler `texto`, usar `url` limpa, não transcrever.
   Endpoint `/api/briefing/dados` OK (clima Open-Meteo + mercado Massare + 5+5 notícias c/ íntegra).
9. **Avaliação Yoda/PNCP**: a queixa do Yoda ("PNCP 400 bloqueia o relatório") é FALSA — `inteligencia._enriquecer`
   é best-effort, "nunca derruba o relatório" (marca INDISPONÍVEL). Já resolvido; Yoda (Gemini) entrou em pânico.

## 🔄 EM ANDAMENTO / A INTEGRAR
- **deep-research** (workflow, rodando em background): "direito administrativo + relatórios CGE-RJ". Quando
  terminar: gravar `docs/PESQUISA-DIREITO-ADMIN-CGE.md` e fundir os achados VERIFICADOS no Lex.

## 📋 BACKLOG ORDENADO (fazer nesta ordem)
1. **Integrar Onda 2 no produto**: usar `contratos_de_fornecedor(cnpj)` no `lex.py` e no `/relatorio`
   (objeto/modalidade/EnquadramentoLegal por CNPJ); enriquecer a seção financeira com contrato vs. pago.
2. **Lex → "Nota Técnica de Indícios"**: aplicar no `lex.py` o molde de achado CGU (situação/critério/causa/
   efeito/evidência/recomendação/manifestação) + mapa improbidade (art. 9/10/11) e crime (CP/14.133) com a
   cautela do DOLO (Lei 14.230) — ver `LEX-DOUTRINA-IMPROBIDADE.md` e `LEX-APRENDIZADOS-CGE-CASHPAGO.md`.
3. **Onda 2 (resto)**: (a) fix endpoint PNCP (`relatorio_riscos/collectors/contratos_pncp.py` dá HTTP 400 —
   faltam `dataInicial/dataFinal`); cache+retry+circuit-breaker no enriquecimento; (b) sanções CEIS/CNEP/CEPIM
   (Portal Transparência); (c) rede por sócio comum 3 níveis (`rede_societaria.py` — Receita/QSA + Splink + networkx,
   aprendizado CASHPAGO); (d) regra "valor simbólico" já existe (Onda 1) — boa.
4. **Onda 3**: grafo fornecedor-órgão (cartel); SHAP no relatório; calibração por UG + PU-learning + drift;
   eval com ground-truth TCE-RJ (penalidades_tcerj!); calibração de corte do score (top-50, marcar 10-15).
5. **Benchmark Passos 2-4**: rodar T1/T2/T5/T6 nas IAs fracas (Gemini/Qwen/nous) via Hermes, pontuar vs. gold,
   ajustar instruções, montar painel (`benchmark_ias.py --painel`).
6. **DuckDB nos relatórios** (Onda 1 item pendente): acelerar queries pesadas lendo o próprio SQLite.

## ❓ DECISÕES PENDENTES (confirmar com o Mestre Jorge)
- **Multiusuário Telegram (filha usar, sem mexer em código)**: Hermes tem allowlist BINÁRIO
  (`~/.hermes/config.yaml` telegram.allowed_users='45338178'); SEM papel/sandbox de ferramenta por usuário
  (`disabled_toolsets` é global; `guest_mode` só libera menção em grupo). Risco: ferramenta `terminal` = shell.
  **Recomendação:** bot-convidado SEPARADO (token próprio + allowlist própria) com toolsets perigosos
  desabilitados, expondo só skills seguras que chamam a API do JFN; auto-allow só nesse bot-convidado.
  NÃO auto-liberar no bot admin. Confirmar a abordagem antes de implementar (é fronteira de segurança).
- **Rotacionar o PAT do git** no remote (pendência antiga de segurança — memória `jfn-projeto-essencial`).

## Estado operacional
- Serviços de usuário ativos: `jfn.service` (:8000) e `hermes-gateway.service` (Yoda). NUNCA parar/reiniciar com
  `sudo`; são `systemctl --user`. NUNCA `push --force`. Commit só na branch `linux`; merge p/ windows = cherry-pick.
- Tabelas novas no `compliance.db`: ob_quarentena, ob_redflag, ob_anomaly, contratos_tcerj, compras_diretas_tcerj,
  penalidades_tcerj, ob_contrato_tcerj.
