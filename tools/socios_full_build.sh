#!/usr/bin/env bash
# socios_full_build — gera data/receita_dump/socios_full.csv.zst: o cadastro de SÓCIOS COMPLETO do Brasil
# (~27,6M linhas), porém ENXUTO (só as 5 colunas úteis) e COMPRIMIDO (zstd -19). Substitui os 1,9 GB de
# ZIPs por um único arquivo bem menor (alvo 300-700 MB), que permite busca reversa de QUALQUER pessoa
# SEM re-baixar o dump.
#
# Colunas mantidas (das 10 colunas dos Socios*.csv da RFB): cnpj_basico;ident;nome_socio;cpf_cnpj_socio;qualif_cod
#   p[1]=cnpj_basico  p[2]=ident  p[3]=nome_socio  p[4]=cpf_cnpj_socio(doc mascarado)  p[5]=qualif_cod
#
# VM 2-core SEM swap: 100% STREAMING — `unzip -p` (nunca extrai o ZIP) | awk (projeta colunas) | zstd -T2.
# Nada é carregado em RAM. nice/ionice. Guarda de load/mem entre ZIPs.
#
# Uso: tools/socios_full_build.sh            # (re)gera o .zst a partir dos Socios*.zip presentes
set -u
REPO="$(cd "$(dirname "$0")/.." && pwd)"
DUMP="$REPO/data/receita_dump"
OUT="$DUMP/socios_full.csv.zst"
TMP="$DUMP/.socios_full.csv.zst.partial"
NICE="nice -n10 ionice -c2 -n6"

say(){ echo "[socios_full] $*"; }

guarda(){
  while :; do
    load=$(awk '{print int($1)}' /proc/loadavg)
    free_mb=$(free -m | awk '/^Mem:/{print $7}')
    if [ "$load" -ge 4 ] || [ "$free_mb" -lt 800 ]; then
      say "pausa: load=$load free=${free_mb}MB — 20s"; sleep 20
    else break; fi
  done
}

LOCK="$DUMP/.socios_full_build.lock"
if [ -f "$LOCK" ] && kill -0 "$(cat "$LOCK" 2>/dev/null)" 2>/dev/null; then
  say "já em execução (PID $(cat "$LOCK")) — saindo"; exit 0
fi
echo $$ > "$LOCK"
trap 'rm -f "$LOCK"' EXIT

zips=$(ls "$DUMP"/Socios*.zip 2>/dev/null | sort)
if [ -z "$zips" ]; then
  say "ERRO: nenhum Socios*.zip em $DUMP — rode tools/baixar_receita_dump.sh socios"; exit 1
fi

# valida integridade de cada ZIP antes de processar (catálogo central, barato)
for zf in $zips; do
  if ! unzip -l "$zf" >/dev/null 2>&1; then
    say "ERRO: $zf inválido/parcial — re-baixar antes de gerar o .zst"; exit 1
  fi
done

rm -f "$TMP"
t0=$(date +%s)
say "gerando $OUT (streaming unzip -p | awk | zstd -19 -T2) a partir de $(echo "$zips" | wc -l) ZIPs..."

# Pipeline único: concatena o stream de TODOS os ZIPs, projeta as 5 primeiras colunas (mantém as aspas
# e o ';' originais p/ casar os parsers existentes), comprime em streaming. awk usa FS=';' e reimprime
# $1..$5 — campos da RFB não contêm ';' interno, então o split é seguro.
{
  for zf in $zips; do
    guarda
    $NICE unzip -p "$zf"
  done
} | $NICE awk -F';' 'NF>=5 { print $1";"$2";"$3";"$4";"$5 }' \
  | $NICE zstd -19 -T2 -q -o "$TMP"
rc=${PIPESTATUS[2]:-$?}

if [ "$rc" -ne 0 ] || [ ! -s "$TMP" ]; then
  say "FALHA na geração (rc=$rc) — .zst parcial preservado em $TMP p/ inspeção"; exit 1
fi

mv -f "$TMP" "$OUT"
n=$(zstdcat "$OUT" | wc -l)
sz=$(du -h "$OUT" | cut -f1)
say "OK: $OUT  tamanho=$sz  linhas=$n  ($(( $(date +%s) - t0 ))s)"
if [ "$n" -lt 20000000 ]; then
  say "AVISO: contagem ($n) abaixo do esperado (~27M) — verificar ZIPs antes de apagá-los"; exit 1
fi
