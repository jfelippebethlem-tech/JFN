#!/bin/bash
# Guard de OOM: este sweep morre ANTES da sessão do dono (ver tools/lib/oom_guard.sh).
source "$(dirname "$0")/lib/oom_guard.sh" 2>/dev/null || true
# sweep_dados — GRUPO endereços + benefícios + fachada (DB/rede, sem sessão itkava). LEVE: nice/ionice idle,
# bounded, SINGLE-PASS (cron repete). Escalonado FORA dos horários do SEI (sem overlap).
set -u
cd /home/ubuntu/JFN || exit 1
export PYTHONPATH=.
PY=.venv/bin/python
LOG=data/sweep_dados.log
say(){ echo "[$(date '+%F %T')] $*" >> "$LOG"; }

[ -f data/.pause_sweeps ] && { say "pausado (.pause_sweeps) — pulei"; exit 0; }
L=$(awk '{print int($1)}' /proc/loadavg); [ "$L" -ge 4 ] && { say "load $L alto — adia"; exit 0; }
PRIO="nice -n 10 ionice -c2 -n6"   # qualidade: best-effort, progride sem starvar
say "início (best-effort baixa prio)"
if [ -f data/.pause_endereco_sweep ]; then say "endereço pausado — pulei"; else $PRIO timeout 900 $PY -m tools.backfill_verificacao_endereco --limite 100 --pausa 0.4 >> data/endereco_serial.log 2>&1; say "endereço rc=$?"; fi
if [ -f data/.pause_beneficios_sweep ]; then say "benefícios pausado — pulei"; else $PRIO timeout 900 $PY -m tools.beneficios_sweep --limite 400 --pausa 0.3 >> data/beneficios_serial.log 2>&1; say "benefícios rc=$?"; fi
if [ -f data/.pause_fachada_sweep ]; then say "fachada pausada — pulei"; else $PRIO timeout 900 bash tools/fachada_sweep_rotativo.sh >> data/dd_sweep/cron.log 2>&1; say "fachada rc=$?"; fi
# fachada STREET VIEW (Google Maps Embed API, GRÁTIS/ilimitada) — SUBSTITUI o par Mapillary
# (fachada_visual_sweep + fachada_b2_sync, ambos APOSENTADOS em 2026-06-14: cobertura ruim, fotos efêmeras).
# Um único sweep faz tudo por suspeito (verificacao_sede status=INDICIO, maior R$ primeiro): RENDERIZA o
# Street View Embed (iframe + HTTP local, VM-safe: subprocesso com cap de RAM real do cgroup + timeout + gate
# mem/load — UM render por vez), VALIDA (rejeita branca), SOBE p/ R2→B2 (grava visual_img_b2), RECLASSIFICA
# com o VLM (visual_fonte=street_view_embed) e CRUZA foto×Google (coerencia_google). Resumível (pula quem já
# tem a foto SV) + dedup por prédio. Render é mais pesado → time-bound conservador e pausa entre alvos.
# Pausa: data/.pause_fachada_streetview_sweep. (Os flags antigos .pause_fachada_visual_sweep/.pause_fachada_b2_sync
# ficam só como freio dos sweeps Mapillary aposentados, que saíram do caminho ativo.)
if [ -f data/.pause_fachada_streetview_sweep ]; then say "fachada street view pausada — pulei"; else $PRIO timeout 1500 $PY -m tools.fachada_streetview_sweep --status INDICIO --limite 0 --max-min 22 --pausa 1.0 >> data/fachada_streetview.log 2>&1; say "fachada street view rc=$?"; fi
# REPARO DE DOCUMENTOS SEM TEOR a partir do PDF já guardado em cache — de graça (não toca o SEI,
# não gasta sessão). A ferramenta existia desde 2026-07-24 com a docstring "por isso esta
# ferramenta roda primeiro" e NUNCA teve caller nem cron. Roda no modo por IDENTIFICADOR (o dono
# é o PDF que exibe o id do título, não o de índice igual) e só grava com prova — o casamento
# posicional está desalinhado e escreveria o teor de uma peça sob o título de outra.
# Pausa: data/.pause_reparar_vazios.
if [ -f data/.pause_reparar_vazios ]; then say "reparar vazios pausado — pulei"; else $PRIO timeout 900 $PY -m tools.sei_reparar_vazios --por-identificador --aplicar >> data/reparar_vazios.log 2>&1; say "reparar vazios rc=$?"; fi
# RECAPTURA DO CAP DE 20k — devolve à fila os processos cujo texto foi cortado em 20.000
# caracteres por documento (a assinatura e a data moram no FIM da peça). O alvo é MEDIDO a cada
# rodada, não lido de lista curada. Estava solto no crontab (`40 5 * * *`), e linha solta é o que
# ninguém audita: foi assim que a MESMA linha ficou duplicada, refilando 80 processos por dia com
# duas escritas concorrentes no progresso do sweep. Aqui herda a guarda de carga e a flag de pausa.
# Pausa: data/.pause_recaptura_cap.
if [ -f data/.pause_recaptura_cap ]; then say "recaptura cap pausada — pulei"; else $PRIO timeout 900 $PY -m tools.sei_reparar_truncados --cap --aplicar --max 40 >> data/reparar_cap21k.log 2>&1; say "recaptura cap rc=$?"; fi
# RANKING DE TAC POR UNIDADE — pagamento fora de contrato regular, com régua COMPARATIVA (a
# mediana das 56 unidades acima de R$ 300 mi é 0,3%; a Fundação Saúde está em 27,0%). Uma passada
# sobre 1,16 milhão de OBs aplicando a regex canônica do `detector_tac` (não se reescreve a
# definição em SQL) e grava JSON — a rota /api/tac/ranking só LÊ o arquivo, para o cálculo nunca
# cair dentro do request. Pausa: data/.pause_tac_ranking.
if [ -f data/.pause_tac_ranking ]; then say "tac ranking pausado — pulei"; else $PRIO timeout 600 $PY tools/tac_ranking_ugs.py >> data/tac_ranking.log 2>&1; say "tac ranking rc=$?"; fi
# SENTINELA DE INTEGRIDADE — vigia a QUALIDADE do que os pipelines produzem (texto cortado em 20k,
# `anexo_bytes` serializado, leitura devolvendo 0 documentos por corrida), não o prazo, que é do
# `pipelines_slo`. Existia, era testada e NÃO ESTAVA EM LUGAR NENHUM: nem cron, nem sweep, nem
# rota — a família 8 do catálogo pela quarta vez. Barata (só lê), e por isso roda toda passada.
# Pausa: data/.pause_sentinela.
if [ -f data/.pause_sentinela ]; then say "sentinela pausada — pulei"; else $PRIO timeout 300 $PY -m tools.sentinela_integridade --alerta >> data/sentinela_integridade.log 2>&1; say "sentinela rc=$?"; fi
# GRAFO DE VÍNCULOS DOS CREDORES — `pessoas` e `relacionamentos` estavam desenhadas no schema e
# com ZERO linhas: `salvar_grafo` existia, era testada e não tinha caller. O universo vem do SIAFE
# (`status='Contabilizado'`, OB anulada não é pagamento), do maior valor pago para o menor, e a
# retomada é por FATO — o CNPJ processado é gravado mesmo com zero arestas, porque "olhei e não
# achei" não é "nunca olhei". ~1,9 s por credor sobre 5.615: por isso vai em fatias.
# Pausa: data/.pause_grafo_persistir.
if [ -f data/.pause_grafo_persistir ]; then say "grafo persistir pausado — pulei"; else JFN_SWEEP_FATIA=0/2 $PRIO timeout 900 $PY -m tools.grafo_persistir --limite 300 >> data/grafo_persistir.log 2>&1; say "grafo persistir rc=$?"; fi
# AGENTE PÚBLICO NO QUADRO SOCIETÁRIO DO PAÍS — uma passada de streaming sobre as 27,6 milhões de
# linhas do cadastro nacional de sócios (`socios_full.csv.zst`), semeada pelas 251 mil pessoas das
# folhas que conhecemos. Precisa de rotina porque as DUAS pontas mudam: a folha a cada competência
# e o dump da Receita todo mês. ~206 s, streaming puro, nada em memória.
# Pausa: data/.pause_agente_reverso.
if [ -f data/.pause_agente_reverso ]; then say "agente reverso pausado — pulei"; else $PRIO timeout 900 $PY -m tools.agente_publico_reverso >> data/agente_publico_reverso.log 2>&1; say "agente reverso rc=$?"; fi
# METRICA QUE MENTE — o verificador CLICA em cada KPI clicavel do painel e confere o numero contra
# as linhas que a gaveta abre. Nenhum teste unitario pega isso: o JS esta certo, a rota esta certa,
# e o erro nasce da COMBINACAO (numero contando o universo, lista contendo a pagina). Ja aconteceu
# duas vezes no mesmo dia: 68 comissionados virando 55, e 647 sem-cadastro virando 0.
# Pausa: data/.pause_drill_check.
if [ -f data/.pause_drill_check ]; then say "drill check pausado — pulei"; else $PRIO timeout 600 $PY -m tools.painel_drill_check >> data/painel_drill_check.log 2>&1; say "drill check rc=$?"; fi
# OSINT x PROCESSOS — o sinal sobre a empresa so vira achado quando aponta para AUTOS concretos.
# Roda DEPOIS do agente_publico_reverso, porque le a fila curada que ele grava.
# Pausa: data/.pause_osint_processos.
if [ -f data/.pause_osint_processos ]; then say "osint x processos pausado — pulei"; else $PRIO timeout 600 $PY -m tools.osint_x_processos >> data/osint_x_processos.log 2>&1; say "osint x processos rc=$?"; fi
# ELOS OCULTOS — duas empresas que disputam o mesmo dinheiro publico atendendo pelo mesmo telefone
# ou e-mail. Roda DEPOIS do grafo_persistir, que e quem alimenta as arestas de contato.
# Pausa: data/.pause_elos_ocultos.
if [ -f data/.pause_elos_ocultos ]; then say "elos ocultos pausado — pulei"; else $PRIO timeout 600 $PY -m tools.elos_ocultos >> data/elos_ocultos.log 2>&1; say "elos ocultos rc=$?"; fi
# CO-CONTATO EM CERTAME — dois participantes do MESMO certame atendendo pelo mesmo telefone ou
# e-mail. 40 s por passada sobre 4.517 certames e 5.624 CNPJs; a rota so LE o JSON.
# Pausa: data/.pause_cocontato.
if [ -f data/.pause_cocontato ]; then say "cocontato pausado — pulei"; else $PRIO timeout 600 $PY -m tools.cocontato_certame >> data/cocontato_certame.log 2>&1; say "cocontato rc=$?"; fi
# ASSINATURAS DA PREFEITURA — o SEI-PCRJ publica a MATRICULA de quem assina cada despacho, e a
# folha municipal tem matricula E nome. Le da VM-2 por ssh; falha vira lista vazia.
# Pausa: data/.pause_assin_pcrj.
if [ -f data/.pause_assin_pcrj ]; then say "assinaturas pcrj pausado — pulei"; else $PRIO timeout 600 $PY -m tools.pcrj_assinaturas_x_folha >> data/pcrj_assinaturas.log 2>&1; say "assinaturas pcrj rc=$?"; fi
# SIGNATARIO x QSA — o signatario do despacho municipal e socio de quem a Prefeitura paga? Roda
# DEPOIS de `pcrj_assinaturas_x_folha`, que e quem identifica a matricula.
# Pausa: data/.pause_signatario_qsa.
if [ -f data/.pause_signatario_qsa ]; then say "signatario x qsa pausado — pulei"; else $PRIO timeout 900 $PY -m tools.pcrj_signatario_x_qsa >> data/pcrj_signatario_qsa.log 2>&1; say "signatario x qsa rc=$?"; fi
# A AUTOAUDITORIA **NÃO** ENTRA AQUI. Ela já roda diariamente às 07:10, no `ExecStartPost` de
# `~/.config/systemd/user/jfn-intel-cache.service.d/autoauditoria.conf` — e eu quase a duplicei em
# 2026-08-06 por ter conferido só o crontab e os `*.sh`, sem olhar os drop-ins do systemd. Os
# fingerprints em `data/autoauditoria/` provam que roda (03, 04, 05 e 06/08). Duplicar tarefa
# pesada em VM de 2 vCPU é o oposto do conserto.
say "fim"
