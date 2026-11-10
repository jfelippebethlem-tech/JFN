#!/usr/bin/env bash
# Guard de OOM: este sweep morre ANTES da sessão do dono (ver tools/lib/oom_guard.sh).
source "$(dirname "$0")/lib/oom_guard.sh" 2>/dev/null || true
# socios_dump_refresh — refresh MENSAL da base reversa de sócios da Receita, VM-safe e RESUMÍVEL.
#
# FLUXO (idempotente; cada etapa é regenerável a partir da fonte):
#   1. baixa Socios*.zip + Empresas*.zip + lookups   (reusa baixar_receita_dump.sh; -c resumível)
#   2. reconstrói `socios_receita`  (QSA dos nossos fornecedores)        [socios_dump_sweep]
#   3. reconstrói `rede_socios_fornecedores` (pessoas ligando >=2)       [socios_dump_sweep --rede via passo 2]
#   4. pré-computa `socios_reverso` (pessoa -> TODOS os CNPJ no Brasil)  [socios_reverso_build]
#   5. materializa `empresas_min` (nomeia os CNPJ do reverso)            [empresas_min_build]
#   6. gera `socios_full.csv.zst` (sócios COMPLETO do Brasil, enxuto+comp) [socios_full_build]
#   7. VALIDA contagens (>0), o reverso do IDESI/Filipe pela TABELA, e o .zst (~27M linhas)
#   8. APAGA SÓ os ZIPs (libera ~1,9 GB) — NUNCA o .zst — e SÓ se a validação passou
#   9. estende a SÉRIE histórica (socio_snapshot) com os meses do espelho após o último ingerido
#
# MÊS: resolvido pela listagem WebDAV da Receita (baixar_receita_dump.sh → data/receita_dump/.mes_baixado)
# e repassado a TODOS os passos com --mes. `MES=AAAA-MM` força. Era fixo em 2026-05: três refreshes
# seguidos re-carregaram maio com "VALIDACAO=OK". O passo 7 agora FALHA se o mês não andou havendo
# mês mais novo publicado (tools/receita_mes.py).
#
# As tabelas vivem no compliance.db local (NÃO versionado; dados pessoais mascarados — LGPD). O
# socios_full.csv.zst (gitignored) FICA: é a base reversa de QUALQUER pessoa sem re-download dos ZIPs.
# Objetivo do dono: REDUZIR espaço — manter as tabelas + o .zst (300-700 MB), sem os 1,9 GB de ZIPs.
#
# VM 2-core sem swap: download já tem guarda de load/mem; os builds Python têm _guarda_recursos + nice(10).
# Uso:  tools/socios_dump_refresh.sh                 (full: baixa -> reconstrói -> apaga ZIPs)
#       SKIP_DOWNLOAD=1 tools/socios_dump_refresh.sh (reusa ZIPs já presentes; útil em re-run)
#       KEEP_ZIPS=1     tools/socios_dump_refresh.sh (NÃO apaga os ZIPs ao fim)
#       MES=2026-10     tools/socios_dump_refresh.sh (força o mês; senão, o mais recente da Receita)
#       SKIP_SERIE=1    tools/socios_dump_refresh.sh (não estende a série histórica no passo 9)
set -u
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO" || exit 1
PY="$REPO/.venv/bin/python"
DUMP="$REPO/data/receita_dump"
LOG="$REPO/data/socios_dump_refresh.log"
LOCK="$REPO/data/.socios_dump_refresh.lock"
NICE="nice -n10 ionice -c2 -n6"
say(){ echo "[$(date '+%F %T')] $*" | tee -a "$LOG"; }

# não duplicar (cron + execução manual)
if [ -f "$LOCK" ] && kill -0 "$(cat "$LOCK" 2>/dev/null)" 2>/dev/null; then
  say "já em execução (PID $(cat "$LOCK")) — saindo"; exit 0
fi
echo $$ > "$LOCK"
trap 'rm -f "$LOCK"' EXIT

t0=$(date +%s)
say "===== socios_dump_refresh INÍCIO ====="
df -h "$REPO" | awk 'NR==2{print "[refresh] disco antes: usado="$3" livre="$4}' | tee -a "$LOG"
# mês JÁ carregado antes deste refresh — é contra ele que o passo 7 mede se a base andou
MES_ANTERIOR=$("$PY" -c "import sqlite3; c=sqlite3.connect('file:data/compliance.db?mode=ro', uri=True, timeout=60); print(c.execute('SELECT MAX(fonte_mes) FROM socios_receita').fetchone()[0] or '')" 2>/dev/null)
say "mês já carregado em socios_receita: ${MES_ANTERIOR:-?}"

# 1) DOWNLOAD (resumível) ---------------------------------------------------------------------------
if [ "${SKIP_DOWNLOAD:-0}" = "1" ]; then
  say "SKIP_DOWNLOAD=1 — pulando download (reusa ZIPs presentes)"
else
  say "1/7 baixando dump (Socios+Empresas+lookups)..."
  bash "$REPO/tools/baixar_receita_dump.sh" all >> "$LOG" 2>&1 || { say "FALHA no download — abortando (resumível: rerodar)"; exit 1; }
fi
# o mês dos ZIPs em disco: forçado por MES=, senão o que o download registrou ao concluir
MES="${MES:-$(cat "$DUMP/.mes_baixado" 2>/dev/null)}"
case "$MES" in
  [0-9][0-9][0-9][0-9]-[0-9][0-9]) ;;
  *) say "FALHA: mês do dump desconhecido ('$MES') — sem $DUMP/.mes_baixado; force MES=AAAA-MM"; exit 1 ;;
esac
say "mês do dump a carregar: $MES"

# 2+3) socios_receita + rede ------------------------------------------------------------------------
say "2/7 + 3/7 reconstruindo socios_receita + rede_socios_fornecedores..."
PYTHONPATH="$REPO" $NICE "$PY" -m tools.socios_dump_sweep --mes "$MES" >> "$LOG" 2>&1 \
  || { say "FALHA em socios_dump_sweep — abortando (ZIPs preservados)"; exit 1; }

# 4) socios_reverso ---------------------------------------------------------------------------------
say "4/7 pré-computando socios_reverso (stream 1x dos Socios)..."
PYTHONPATH="$REPO" $NICE "$PY" -m tools.socios_reverso_build --mes "$MES" >> "$LOG" 2>&1 \
  || { say "FALHA em socios_reverso_build — abortando (ZIPs preservados)"; exit 1; }

# 5) empresas_min -----------------------------------------------------------------------------------
say "5/8 materializando empresas_min (nomeia os CNPJ do reverso)..."
PYTHONPATH="$REPO" $NICE "$PY" -m tools.empresas_min_build --mes "$MES" >> "$LOG" 2>&1 \
  || { say "FALHA em empresas_min_build — abortando (ZIPs preservados)"; exit 1; }

# 5.1) empresas (razão social de TODAS as raízes que têm estabelecimento) ---------------------------
# A base tinha 6,17 mi de estabelecimentos e a razão social de NENHUM — procurar empresa pelo NOME
# era impossível, e a natureza jurídica (3xxx = terceiro setor) só era conhecida de 3.861 entidades.
# Entra AQUI, antes do passo 8, porque o passo 8 apaga os Empresas*.zip.
say "5.1/8 razão social + natureza das 5,86 mi de raízes com estabelecimento..."
PYTHONPATH="$REPO" $NICE "$PY" -m tools.empresas_rj_build --mes "$MES" >> "$LOG" 2>&1 \
  || { say "FALHA em empresas_rj_build — abortando (ZIPs preservados)"; exit 1; }

# 6) socios_full.csv.zst (sócios COMPLETO do Brasil, enxuto+comprimido) ------------------------------
say "6/8 gerando socios_full.csv.zst (stream unzip -p | awk | zstd -19 -T2)..."
bash "$REPO/tools/socios_full_build.sh" >> "$LOG" 2>&1 \
  || { say "FALHA em socios_full_build — abortando (ZIPs preservados)"; exit 1; }

# 7) VALIDAÇÃO --------------------------------------------------------------------------------------
say "7/8 validando contagens, o reverso do IDESI/Filipe pela TABELA, e o .zst (~27M)..."
VAL=$(MES="$MES" PYTHONPATH="$REPO" "$PY" - <<'PYEOF'
import os, sqlite3, sys
con = sqlite3.connect("data/compliance.db")
def c(t):
    try: return con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    except Exception: return 0
nrev = c("socios_reverso"); nemp = c("empresas_min"); nsoc = c("socios_receita")
# reverso do Filipe Ramos Pereira ***002167** pela TABELA (deve trazer IDESI 28470707 + SIGNAL RIO)
rows = con.execute(
    "SELECT DISTINCT cnpj_basico FROM socios_reverso WHERE doc_socio=? AND nome_norm=?",
    ("***002167**", "FILIPE RAMOS PEREIRA")).fetchall()
cnpjs = sorted(r[0] for r in rows)
meses = sorted(r[0] or "" for r in con.execute("SELECT DISTINCT fonte_mes FROM socios_receita"))
con.close()
# a foto carregada tem de ser UMA e do mês baixado (o passo 2 troca a foto inteira)
ok = (nrev > 0 and nemp > 0 and nsoc > 0 and "28470707" in cnpjs and len(cnpjs) >= 2
      and meses == [os.environ["MES"]])
print(f"socios_receita={nsoc} socios_reverso={nrev} empresas_min={nemp}")
print("MES_CARREGADO=" + ",".join(meses))
print("filipe_cnpjs=" + ",".join(cnpjs))
print("VALIDACAO=" + ("OK" if ok else "FALHOU"))
sys.exit(0 if ok else 1)
PYEOF
)
RC=$?
echo "$VAL" | tee -a "$LOG"
if [ $RC -ne 0 ]; then
  say "VALIDAÇÃO (tabelas) FALHOU — ZIPs PRESERVADOS (investigar antes de apagar)"; exit 1
fi

# o mês ANDOU? igual ao já carregado havendo mais novo na Receita = base congelada (o defeito de 05/09-05/11)
MES_RECEITA=$(PYTHONPATH="$REPO" "$PY" -m tools.receita_mes mais-recente 2>>"$LOG")
DEC=$(PYTHONPATH="$REPO" "$PY" -m tools.receita_mes decidir "$MES" "$MES_ANTERIOR" "$MES_RECEITA")
RC=$?
say "mês: $DEC"
if [ $RC -ne 0 ]; then
  say "VALIDAÇÃO (mês) FALHOU: base CONGELADA — ZIPs PRESERVADOS"; exit 1
fi

# valida o socios_full.csv.zst: existe e tem ~27M linhas (substitui os ZIPs p/ reverso de qualquer pessoa)
ZST="$DUMP/socios_full.csv.zst"
if [ ! -s "$ZST" ]; then
  say "VALIDAÇÃO (.zst) FALHOU: $ZST ausente/vazio — ZIPs PRESERVADOS"; exit 1
fi
NZST=$(zstdcat "$ZST" | wc -l)
say "socios_full.csv.zst: $(du -h "$ZST" | cut -f1)  linhas=$NZST"
if [ "$NZST" -lt 20000000 ]; then
  say "VALIDAÇÃO (.zst) FALHOU: linhas=$NZST < 20M (esperado ~27M) — ZIPs PRESERVADOS"; exit 1
fi

# 8) APAGAR SÓ os ZIPs (NUNCA o .zst) ---------------------------------------------------------------
if [ "${KEEP_ZIPS:-0}" = "1" ]; then
  say "8/8 KEEP_ZIPS=1 — NÃO apagando ZIPs"
else
  say "8/8 validação OK — apagando SÓ os ZIPs (o socios_full.csv.zst FICA)..."
  rm -f "$DUMP"/Socios*.zip "$DUMP"/Empresas*.zip "$DUMP"/Qualificacoes.zip "$DUMP"/Naturezas.zip
  say "ZIPs apagados (socios_full.csv.zst preservado)."
fi

# 9) SÉRIE HISTÓRICA (socio_snapshot/socio_historico) ----------------------------------------------
# Sem cron até aqui: a série parou em 2026-07 à mão. Só os meses POSTERIORES ao último ingerido (um zip
# por vez do espelho casadosdados, filtrado e apagado). Recusa se ainda houver sócio PJ de 14 dígitos.
SERIE_RC=0
if [ "${SKIP_SERIE:-0}" = "1" ]; then
  say "9/9 SKIP_SERIE=1 — série histórica não estendida"
else
  say "9/9 estendendo a série histórica (meses do espelho após o último ingerido)..."
  PYTHONPATH="$REPO" $NICE "$PY" -m tools.socios_serie_historica --faltantes >> "$LOG" 2>&1 \
    || { SERIE_RC=1; say "FALHA na série histórica (socios_serie_historica --faltantes) — ver log"; }
fi

df -h "$REPO" | awk 'NR==2{print "[refresh] disco depois: usado="$3" livre="$4}' | tee -a "$LOG"
say "===== socios_dump_refresh FIM (mês $MES; $(( $(date +%s) - t0 ))s) ====="
exit $SERIE_RC
