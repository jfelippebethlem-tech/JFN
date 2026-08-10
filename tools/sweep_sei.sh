#!/bin/bash
# Guard de OOM: este sweep morre ANTES da sessão do dono (ver tools/lib/oom_guard.sh).
source "$(dirname "$0")/lib/oom_guard.sh" 2>/dev/null || true
# sweep_sei — GRUPO SEI (itkava/browser): sei_sweep + sei_cpf. Roda SOZINHO (sessão única livre p/ leitura
# manual entre execuções). LEVE: nice/ionice idle (só CPU/IO ocioso), bounded por timeout, SINGLE-PASS
# (o cron repete; NÃO é loop contínuo — esse era o lane ruim que segurava Chromium na memória 24h).
set -u
cd /home/ubuntu/JFN || exit 1
# O cron não herda o .env: sem isto só o Gemini sobrevive na cadeia (ele lê as chaves
# do disco), e Groq/Cerebras/extras ficam "indisponíveis" — foi por isso que os 1.696
# pareceres do Lex saíram 100% do Gemini. Ver tools/obra_fase_sei no crontab (mesmo padrão).
[ -f .env ] && { set -a; . ./.env; set +a; }
export PYTHONPATH=.
PY=.venv/bin/python
# REPO existe porque a linha do colher_vm2 o usava SEM defini-lo — e com `set -u` o shell morre
# ali mesmo. Medido em 2026-08-08: NENHUM `say "fim"` no log desde que o bloco entrou (06/08
# 21:58), e todo passo depois da linha do colher (cpf, refichar, depurar, árvore, direc, lex)
# ficou um dia e meio sem rodar, calado. `set -u` protege — mas só grita no stderr do cron, que
# ninguém lê; o sentinela de "fim" é o que se pode auditar.
REPO=/home/ubuntu/JFN
LOG=data/sweep_sei.log
say(){ echo "[$(date '+%F %T')] $*" >> "$LOG"; }

[ -f data/.pause_sweeps ] && { say "pausado (.pause_sweeps) — pulei"; exit 0; }
[ -f data/.pause_sei_sweep ] && { say "pausado (.pause_sei_sweep) — pulei"; exit 0; }
# bracket evita auto-match; se já há um sei_sweep, NÃO abrir 2ª sessão itkava (o SEI expulsa a duplicada)
# FATIA desta máquina no universo de processos (hash determinístico do número). A VM-1 fica com
# 0/2 e a VM-2 com 1/2, então as duas nunca capturam o mesmo processo — medido em 2026-07-28:
# 21.045 + 20.695 = 41.740, o universo inteiro, sem sobreposição. Sem a variável, `sei_sweep`
# assume máquina única (0/1) e nada muda para quem nunca dividiu.
export JFN_SWEEP_FATIA="${JFN_SWEEP_FATIA:-0/2}"

if pgrep -f 'tools\.sei_swee[p]' >/dev/null; then say "já rodando — pula"; exit 0; fi
# TRAVA DE CICLO. O guard acima só enxerga `tools.sei_sweep`; quando o ciclo anterior está num
# estágio POSTERIOR (sei_cpf, refichar, depurar), o pgrep não vê nada, o novo ciclo entra e trava
# 600s no browser_lock até morrer. Medido em 2026-08-04: **406 ocorrências** de "não adquiriu em
# 600s" no log, 4 a 10 por dia — 10 minutos de sweep perdidos em cada uma, com a fila em anos de
# atraso. O cabeçalho deste arquivo sempre disse "roda SOZINHO"; faltava a trava do ciclo inteiro.
# PID em arquivo, não flock: um `flock` em fd é HERDADO pelos filhos, e um chromium órfão que
# sobreviva a um SIGKILL do Python seguraria o lock para sempre — o sweep pararia calado, que é
# pior que a contenção. Aqui, PID morto (ou reciclado por outro comando) simplesmente libera.
PIDF=data/.sweep_sei.pid
if [ -f "$PIDF" ]; then
  ANT=$(cat "$PIDF" 2>/dev/null | tr -dc '0-9')
  if [ -n "$ANT" ] && kill -0 "$ANT" 2>/dev/null && \
     tr '\0' ' ' < "/proc/$ANT/cmdline" 2>/dev/null | grep -q 'sweep_sei'; then
    say "ciclo anterior (pid $ANT) ainda rodando — pula"; exit 0
  fi
fi
echo $$ > "$PIDF"
trap 'rm -f "$PIDF"' EXIT
# backstop VM-safe: se a VM já está muito carregada, adia (o cron repete no próximo slot)
L=$(awk '{print int($1)}' /proc/loadavg); [ "$L" -ge 4 ] && { say "load $L alto — adia"; exit 0; }

# ⚠ LIÇÃO §8: o server.py TAMBÉM usa ms-playwright chromium → NUNCA pkill amplo por padrão (mataria o dele).
# Mata SÓ chromium ÓRFÃO do playwright (ppid=1 = vazou de um sweep morto; o do server.py tem pai vivo).
limpa_orfaos(){ for p in $(pgrep -f 'ms-playwright/chromium' 2>/dev/null); do [ "$(ps -o ppid= -p "$p" 2>/dev/null | tr -d ' ')" = "1" ] && kill "$p" 2>/dev/null; done; }
limpa_orfaos

# PRIORIDADE = qualidade: best-effort de baixa prioridade (progride sempre, sem starvar como o ionice idle).
PRIO="nice -n 10 ionice -c2 -n6"
say "início (best-effort baixa prio, bounded)"
# LEITURA COMPLETA = padrão (ler() canônico: TODOS os docs + OCR de scan, WAF-safe + cracked). ~3x mais pesada/processo
# → batch menor p/ caber no timeout e não saturar os 2 vCPU (cron repete; cobre a fila ao longo dos runs).
# --foreground: o SIGTERM do bound vai SÓ para o Python (que para limpo entre processos). Sem ele o
# `timeout` sinaliza o GRUPO e mata o Chromium junto → TargetClosedError com a leitura em voo perdida.
# -k 120: repõe a garantia (SIGKILL se o Python travar).
# TETO DE DOCUMENTOS POR PROCESSO (2026-08-03, pedido do dono: "tudo o mais completo e sem
# limitação de páginas"). Medido antes de mexer: dos 314 processos com cache, a árvore tem 19.583
# documentos e só 9.136 tinham texto lido — 10.447 fechados, com 179 processos parando EXATAMENTE
# em 40, que era o default do `sei_reader`. Sobe para 120. O custo é real e está declarado: o
# tempo por processo cresce, então cada slot cobre MENOS processos — mas o slot é o mesmo, o cron
# repete, e o que se ganha é profundidade onde antes havia corte cego. Ajustável por ambiente.
export SEI_MAX_DOCS=${SEI_MAX_DOCS:-120}
$PRIO timeout -k 120 --foreground 1500 $PY -m tools.sei_sweep --max 12 >> data/sei_cache/sei_sweep_loop.out 2>&1; say "sei_sweep rc=$? (SEI_MAX_DOCS=$SEI_MAX_DOCS)"
# FOCO: UGs sob teste/observação (data/ugs_foco.txt) — lê os processos SEI dessas UGs por valor.
# CAUSA-RAIZ (2026-08-08): o laço antigo era `while read -r ugcod ... < data/ugs_foco.txt`, e o
# arquivo era o STDIN do laço. Cada UG roda `timeout --foreground python -m tools.sei_sweep`, e o
# `--foreground` faz o filho HERDAR esse stdin; o Chromium/Playwright do sei_sweep reposiciona o
# offset do descritor, e o `read` seguinte relê o arquivo DO TOPO — LOOP INFINITO. Medido ao vivo:
# um ciclo rodou 3h20 fazendo três passadas das mesmas 16 UGs, sem NUNCA chegar a recaptura/colher/
# `say "fim"`, e o guard `já rodando — pula` mantinha os ciclos novos (com o conserto) fora do ar.
# Precisou de `kill` por PID para destravar. A ausência de `fim` desde 06/08 era isto.
#
# CONSERTO: `mapfile` lê o arquivo para um ARRAY antes do laço, e o `for` itera o array — o stdin
# do filho deixa de ter qualquer efeito sobre a iteração. De brinde, duas guardas que faltavam:
# (a) ORÇAMENTO TOTAL (FOCO_ORCAMENTO_S): o foco cede e deixa recaptura/colher/fim rodarem, contra
# a inanição — os 16×700 s cabiam em ~3 h e sufocavam a cauda mesmo sem o loop infinito; (b) CURSOR
# de rodízio: cada ciclo começa onde o anterior parou, então nenhuma UG fica faminta.
FOCO_ORCAMENTO_S=${FOCO_ORCAMENTO_S:-2400}
if [ -f data/ugs_foco.txt ]; then
  mapfile -t _UGS < <(grep -vE '^\s*#|^\s*$' data/ugs_foco.txt | awk '{print $1}')
  _N=${#_UGS[@]}
  if [ "$_N" -gt 0 ]; then
    _CUR=$(cat data/.foco_cursor 2>/dev/null || echo 0); case "$_CUR" in ''|*[!0-9]*) _CUR=0;; esac
    _t0=$SECONDS; _feitas=0
    for _i in $(seq 0 $((_N-1))); do
      if [ $((SECONDS - _t0)) -ge "$FOCO_ORCAMENTO_S" ]; then
        say "foco: orçamento de ${FOCO_ORCAMENTO_S}s esgotado após $_feitas UG(s) — cedendo aos passos finais"; break
      fi
      ugcod=${_UGS[$(( (_CUR + _i) % _N ))]}
      # TETO DO SLOT ≥ CUSTO DE UM PROCESSO. Medido em 2026-08-08: com SEI_MAX_DOCS=120 um
      # processo grande custa ~750 s de leitura + ~130 s de fila/login. Com teto de 700 s as UGs
      # de processo grande (180100, 210700, 294200…) morriam rc=137 NO MEIO do 1º processo, toda
      # passada, perdendo a leitura em voo — rodavam sempre e nunca produziam. 1500 s cabe 1
      # grande ou 2 médios; o ORÇAMENTO total acima segue limitando o foco inteiro.
      $PRIO timeout -k 120 --foreground 1500 $PY -m tools.sei_sweep --ug "$ugcod" --max 6 >> data/sei_cache/sei_sweep_loop.out 2>&1; say "sei_foco ug=$ugcod rc=$?"
      _feitas=$((_feitas+1))
    done
    echo $(( (_CUR + _feitas) % _N )) > data/.foco_cursor   # onde o próximo ciclo começa
  fi
fi
# SEGUIR OS PROCESSOS-PAI de contratação detectados no cache (recupera a substância dos dockets de
# execução/pagamento que vêm "vazios"). Mesmo slot/sessão única itkava, DEPOIS do sweep normal; bounded;
# resumível (pais já lidos ficam em cache+progress). Lê poucos por slot (qualidade > volume na VM 2 vCPU).
# HISTÓRICO: este passo DERROU A VM em 27/07 (OOM 11× no dia; queda às 22:22:49). Não era vazamento:
# `sei_pais.carregar_cache()` materializava os 18 GB do acervo em RAM. RELIGADO em 27/07 23:1x depois
# de (a) `detectar_pais()` virar streaming — pico medido de 807 MB — e (b) o CHAMADOR aqui parar de
# chamar `carregar_cache()`, que era o que ainda faltava (um OOM de 9 GB às 23:04 nasceu justamente
# de validar o conserto com o chamador antigo). O guard de OOM no topo deste arquivo garante que,
# se algo escapar, quem morre é o sweep — nunca a sessão do dono.
$PRIO timeout -k 120 --foreground 900 $PY -m tools.sei_sweep --seguir-pais --max 5 >> data/sei_cache/sei_sweep_loop.out 2>&1; say "sei_pais rc=$?"
# RECAPTURA INTEGRAL — o modo existia e NINGUEM o chamava. `sei_sweep --recaptura` esta escrito
# desde 2026-08-03 e nenhum agendamento o acionava: a fila de 540 processos com documento sem texto
# lido nao tinha quem a drenasse (familia 8 do catalogo — construido, testado, nunca rodado).
# Entrou aqui, e NAO num cron proprio, porque a sessao itkava e unica: duas capturas simultaneas e o
# SEI expulsa a duplicada. Sequencial, DEPOIS do sweep normal, com orcamento apertado — o custo por
# processo e do login + carga da arvore (~9 min medidos), nao do numero de documentos.
# ORÇAMENTO, MEDIDO — não chutado. O ciclo deste script leva ~3h de ponta a ponta (marcas "fim" do
# log em 2026-08-05: 03:36 · 07:01 · 10:02 · 12:41 · 15:32 · 18:30), porque o laço de foco percorre
# 16 UGs com teto de 700 s cada e o cron de 30 min só encontra "já rodando — pula". A recaptura,
# que vem depois, roda portanto ~1 vez a cada 3 horas — e cada processo custa ~9 min (o custo é do
# login + carga da árvore, não do número de documentos), então 700 s não cabiam nem um. Com 1500 s
# cabem dois, que é o `--max`. Cadência real: ~16 processos/dia sobre uma fila de 537 — semanas,
# não horas. Está escrito aqui para ninguém esperar o que o relógio não dá.
# Pausa: data/.pause_recaptura_integral.
if [ -f data/.pause_recaptura_integral ]; then
  say "recaptura integral pausada — pulei"
else
  $PRIO timeout -k 120 --foreground 1500 $PY -m tools.sei_sweep --recaptura --max 5 \
    >> data/sei_cache/sei_sweep_loop.out 2>&1; say "sei_recaptura rc=$?"
fi
# BUSCA DIRIGIDA POR TEXTO — DENTRO do ciclo, porque a sessão itkava é ÚNICA. Rodar
# `sei_busca_mgs.py` por fora disputa a sessão e devolve ZERO com cara de "não achei": aconteceu em
# 2026-08-10, quando o CONTROLE POSITIVO ("MGS CLEAN", que sabidamente retorna) voltou 0 durante o
# ciclo e eu quase registrei "a busca quebrou". Aqui a sessão já é nossa e o browser acabou de ser
# usado. OPT-IN: sem `data/sei_busca_pedidos.txt` nada acontece — o sweep segue idêntico.
# O CONTROLE POSITIVO roda SEMPRE junto: sem ele, zero não é resposta, é ausência de resposta.
PEDIDOS=data/sei_busca_pedidos.txt
if [ -f "$PEDIDOS" ]; then
  mkdir -p data/sei_buscas
  # A sessao itkava ja e nossa aqui e a busca e UMA navegacao — o vm_guard de 1.7 foi calibrado
  # para sweep de browser. Sem o override, o proprio sweep (que mantem load ~1.75) barra a busca:
  # medido em 2026-08-10 10:35, controle e alvo voltaram {"ok":false,"vm_guard":"load1=1.75"}.
  export VM_GUARD_MAX_LOAD=${VM_GUARD_MAX_LOAD:-4.0}
  CTRL=$($PRIO timeout 500 $PY tools/sei_busca_mgs.py "MGS CLEAN" 2>/dev/null \
         | $PY -c "import json,sys;print(json.load(sys.stdin).get('n_total',''))" 2>/dev/null)
  say "busca dirigida — controle positivo 'MGS CLEAN': n_total=${CTRL:-<sem resposta>}"
  # INTEIRO POSITIVO ou aborta. A versao anterior testava so "0" e vazio, e o "?" que eu mesmo
  # usava como fallback de parse passou como se fosse resposta — a guarda existia e nao guardou.
  case "${CTRL:-}" in
    ''|0|*[!0-9]*)
      say "busca dirigida ABORTADA: controle positivo nao devolveu contagem valida ('${CTRL:-vazio}') — qualquer zero do alvo seria inconclusivo" ;;
    *)
    _n=0; _medidas=0
    while IFS= read -r termo; do
      [ -z "$termo" ] && continue
      case "$termo" in \#*) continue ;; esac
      _n=$((_n+1)); [ "$_n" -gt 3 ] && { say "busca dirigida: teto de 3 termos por ciclo"; break; }
      slug=$(printf '%s' "$termo" | tr -cs 'A-Za-z0-9' '_' | cut -c1-40)
      $PRIO timeout 500 $PY tools/sei_busca_mgs.py "$termo" > "data/sei_buscas/$slug.json" 2>/dev/null
      _rc=$?
      _ok=$($PY -c "import json,sys;d=json.load(open(sys.argv[1]));print(1 if d.get('ok') is not False else 0)" "data/sei_buscas/$slug.json" 2>/dev/null || echo 0)
      [ "${_ok:-0}" = "1" ] && _medidas=$((_medidas+1))
      say "busca dirigida '$termo' rc=$_rc mediu=${_ok:-0} -> data/sei_buscas/$slug.json"
    done < "$PEDIDOS"
    # CONSOME so se ALGUMA busca produziu resultado utilizavel. Consumir sem medir apaga o pedido
    # e deixa a lacuna invisivel — foi o que aconteceu no ciclo das 10:35.
    if [ "$_medidas" -gt 0 ]; then
      mv "$PEDIDOS" "$PEDIDOS.feito"
    else
      say "busca dirigida: nenhum termo mediu — pedido PRESERVADO para o proximo ciclo"
    fi ;;
  esac
fi

# FILA DE RECAPTURA POR PROVA DO PARECER — a conferencia que compara a lista de documentos do
# parecer com a nossa pasta existia, era testada, tinha sido MEDIDA em 03/08 (370 processos) e nao
# tinha UM UNICO CALLER: virava relatorio no PDF do 360 e morria ali. Sem ela a lacuna de captura
# nao vira trabalho, e o motor segue afirmando ausencia que e NOSSA (foi o que rebaixou 5 criticas
# de "pagamento sem prova" para INDISPONIVEL em 07/08). Barata: so le o acervo ja arquivado.
# Pausa: data/.pause_fila_parecer.
if [ -f data/.pause_fila_parecer ]; then say "fila por parecer pausada — pulei"; else $PRIO timeout 900 $PY -m tools.fila_recaptura_por_parecer --gravar >> data/fila_recaptura_parecer.log 2>&1; say "fila por parecer rc=$?"; fi
# COLHEITA DA VM-2 — duas maquinas capturando, uma analisando, e nenhuma ponte entre elas. Medido
# em 2026-08-07: a VM-2 tinha 111 processos com documentos e a VM-1 nunca vira 61 deles. Barato
# (rsync + arquivamento sem browser) e por isso roda toda passada.
# Pausa: data/.pause_colher_vm2.
if [ -f data/.pause_colher_vm2 ]; then say "colheita vm2 pausada — pulei"; else $PRIO timeout 1200 bash "$REPO/tools/colher_vm2.sh" >> data/colher_vm2.log 2>&1; say "colher vm2 rc=$?"; fi
$PRIO timeout 600  $PY -m tools.sei_cpf_sweep >> data/sei_cpf_sweep.log 2>&1; say "sei_cpf rc=$?"
# RE-FICHA bounded: re-extrai a ficha de quem ainda NÃO tem o campo `situacao` (idempotente — pula quem já
# tem). Auto-cura a cobertura ao longo dos dias quando o nous tem janelas boas (sem pendência manual). Bounded.
# ORÇAMENTO INTERNO (07/08/2026): antes o `timeout 600` matava a ferramenta e o log registrava
# `rc=124` em 86% das execuções — alarme permanente, que é alarme desligado. Com `--orcamento-s`
# ela para sozinha e sai 0; o `timeout` fica como rede de segurança, com folga.
$PRIO timeout 700  $PY -m tools.sei_refichar --max 40 --orcamento-s 540 >> data/sei_refichar.log 2>&1; say "sei_refichar rc=$?"
# DEPURA as fichas do cache -> tabela sei_ficha (só info relevante, queryável/cruzável c/ OBs). Idempotente.
# A rodada normal é INCREMENTAL (só blob tocado desde a marca) e leva segundos. O teto folgado é para
# a passada COMPLETA, que acontece com banco vazio/restaurado: medida em 502-587 s sobre 6.428 blobs.
$PRIO timeout 900  $PY -m tools.sei_depurar_db >> data/sei_depurar.log 2>&1; say "sei_depurar rc=$?"
# CONSOLIDA cada árvore de processo num dossiê TXT (data/sei_trees/) + tabela sei_arvore — o que o Lex lê.
$PRIO timeout 400  $PY -m tools.sei_arvore_build >> data/sei_arvore.log 2>&1; say "sei_arvore rc=$?"
# MEMÓRIA cruzada de direcionamento por fornecedor (acumula; barato, sem LLM em massa; ente público zerado).
$PRIO timeout 200  $PY -m tools.sei_direcionamento_varre >> data/sei_direc.log 2>&1; say "sei_direc rc=$?"
# DIRECIONAMENTO on-demand: o cérebro caro (gemini, tier PRODUTO) SÓ nos TOP-SCORE — poucos por slot, NÃO é
# volume; cache de 30d faz a maioria dos slots não reavaliar nada. Surface no Lex/relatorio (§II-F). Bounded.
$PRIO timeout 400  $PY -m tools.sei_direcionamento_llm --top 6 >> data/sei_direc.log 2>&1; say "sei_direc_llm rc=$?"
# PESQUISA-INTERNET (Fase 5): o Lex pesquisa as dúvidas dos TOP-SCORE (OSINT/web/DOERJ/mídia adversa),
# aprende (vault + DB lex_pesquisa) e re-ajusta a análise. Poucos por slot (rede + LLM produto); cache 30d.
$PRIO timeout 600  $PY -m tools.lex_pesquisa_internet --top 3 >> data/lex_pesquisa.log 2>&1; say "lex_pesquisa rc=$?"
# EXECUÇÃO DO CONTRATO (Gemini): o Lex avalia se a entrega foi comprovada e COERENTE com o objeto/
# quantidade (prestação de contas, fiscalização/relatório fotográfico, plausibilidade física). Poucos/slot.
$PRIO timeout 600  $PY -m tools.lex_execucao --top 4 >> data/lex_execucao.log 2>&1; say "lex_execucao rc=$?"
# APRENDIZADO PROGRESSIVO DA PERÍCIA: agrega dúvidas/lacunas recorrentes das perícias do sweep → surfa os
# TÓPICOS p/ nós (lex_feedback → nota do vault) + promove a regras de método (memoria 'metodo:pericia:*')
# que o sei_ficha reinjeta no prompt da próxima perícia. Núcleo determinístico; síntese de regra = best-effort.
$PRIO timeout 200  env PYTHONPATH=. $PY -m tools.pericia_aprendizado >> data/pericia_aprendizado.log 2>&1; say "pericia_aprend rc=$?"
# FEEDBACK Lex/JFN → Claude Code (determinístico, sem LLM): consolida dificuldades/ideias do ciclo na nota do vault.
$PRIO timeout 120  env PYTHONPATH=. $PY -m tools.lex_feedback --auto >> data/lex_feedback.log 2>&1; say "lex_feedback rc=$?"
limpa_orfaos  # fecha SÓ os leftovers órfãos (não o server.py)
say "fim"
