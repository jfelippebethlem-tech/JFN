#!/usr/bin/env bash
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
#
# As tabelas vivem no compliance.db local (NÃO versionado; dados pessoais mascarados — LGPD). O
# socios_full.csv.zst (gitignored) FICA: é a base reversa de QUALQUER pessoa sem re-download dos ZIPs.
# Objetivo do dono: REDUZIR espaço — manter as tabelas + o .zst (300-700 MB), sem os 1,9 GB de ZIPs.
#
# VM 2-core sem swap: download já tem guarda de load/mem; os builds Python têm _guarda_recursos + nice(10).
# Uso:  tools/socios_dump_refresh.sh                 (full: baixa -> reconstrói -> apaga ZIPs)
#       SKIP_DOWNLOAD=1 tools/socios_dump_refresh.sh (reusa ZIPs já presentes; útil em re-run)
#       KEEP_ZIPS=1     tools/socios_dump_refresh.sh (NÃO apaga os ZIPs ao fim)
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

# 1) DOWNLOAD (resumível) ---------------------------------------------------------------------------
if [ "${SKIP_DOWNLOAD:-0}" = "1" ]; then
  say "SKIP_DOWNLOAD=1 — pulando download (reusa ZIPs presentes)"
else
  say "1/7 baixando dump (Socios+Empresas+lookups)..."
  bash "$REPO/tools/baixar_receita_dump.sh" all >> "$LOG" 2>&1 || { say "FALHA no download — abortando (resumível: rerodar)"; exit 1; }
fi

# 2+3) socios_receita + rede ------------------------------------------------------------------------
say "2/7 + 3/7 reconstruindo socios_receita + rede_socios_fornecedores..."
PYTHONPATH="$REPO" $NICE "$PY" -m tools.socios_dump_sweep >> "$LOG" 2>&1 \
  || { say "FALHA em socios_dump_sweep — abortando (ZIPs preservados)"; exit 1; }

# 4) socios_reverso ---------------------------------------------------------------------------------
say "4/7 pré-computando socios_reverso (stream 1x dos Socios)..."
PYTHONPATH="$REPO" $NICE "$PY" -m tools.socios_reverso_build >> "$LOG" 2>&1 \
  || { say "FALHA em socios_reverso_build — abortando (ZIPs preservados)"; exit 1; }

# 5) empresas_min -----------------------------------------------------------------------------------
say "5/8 materializando empresas_min (nomeia os CNPJ do reverso)..."
PYTHONPATH="$REPO" $NICE "$PY" -m tools.empresas_min_build >> "$LOG" 2>&1 \
  || { say "FALHA em empresas_min_build — abortando (ZIPs preservados)"; exit 1; }

# 6) socios_full.csv.zst (sócios COMPLETO do Brasil, enxuto+comprimido) ------------------------------
say "6/8 gerando socios_full.csv.zst (stream unzip -p | awk | zstd -19 -T2)..."
bash "$REPO/tools/socios_full_build.sh" >> "$LOG" 2>&1 \
  || { say "FALHA em socios_full_build — abortando (ZIPs preservados)"; exit 1; }

# 7) VALIDAÇÃO --------------------------------------------------------------------------------------
say "7/8 validando contagens, o reverso do IDESI/Filipe pela TABELA, e o .zst (~27M)..."
VAL=$(PYTHONPATH="$REPO" "$PY" - <<'PYEOF'
import sqlite3, sys
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
con.close()
ok = nrev > 0 and nemp > 0 and nsoc > 0 and "28470707" in cnpjs and len(cnpjs) >= 2
print(f"socios_receita={nsoc} socios_reverso={nrev} empresas_min={nemp}")
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

df -h "$REPO" | awk 'NR==2{print "[refresh] disco depois: usado="$3" livre="$4}' | tee -a "$LOG"
say "===== socios_dump_refresh FIM ($(( $(date +%s) - t0 ))s) ====="
