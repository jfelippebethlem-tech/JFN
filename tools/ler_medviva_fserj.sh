#!/bin/bash
# Leitura DIRIGIDA dos autos do caso FSERJ (vault: casos/fserj-dirigentes-socios-de-contratadas)
# pelo CAMINHO CANÔNICO: `sweep_recaptura_integral.reler` → SR.ler(usar_cache=False) → cache
# canônico → `arquivar` (sei_arquivar_do_cache). A 1ª versão usava sei_processo_integral, que só
# materializa PDF + checkpoint (apagado no fim) — a ficha, o 360 e o arquivo ficavam CEGOS ao que
# foi lido (família "reparar e verificar o EFEITO, não a ação").
# Roda com o sweep PAUSADO (sessão itkava é única).
set -u
cd /home/ubuntu/JFN || exit 1
[ -f .env ] && { set -a; . ./.env; set +a; }
export PYTHONPATH=.
LOG=data/ler_medviva.log
say(){ echo "[$(date '+%F %T')] $*" >> "$LOG"; }

touch data/.pause_sei_sweep
say "início (canônico reler→arquivar) — sweep pausado"
trap 'rm -f data/.pause_sei_sweep; say "flag de pausa removida"' EXIT

.venv/bin/python - <<'PY' >> "$LOG" 2>&1
from datetime import datetime
from tools.sweep_recaptura_integral import _lido_agora, arquivar, reler

def say(msg):
    print(f"[{datetime.now():%F %T}] {msg}", flush=True)

PROCS = ["SEI-080002/014914/2024", "SEI-080002/011699/2024", "SEI-080002/019714/2024",
         "SEI-080002/020069/2024", "SEI-080002/018759/2025", "SEI-080002/017280/2024"]
for p in PROCS:
    say(f"lendo {p} (canônico, teto 200)…")
    try:
        antes = _lido_agora(p)
        n = reler(p, 200, 1500)
        # GANHO ZERO NÃO É SUCESSO. Medido 2026-08-08: o browser_lock estava com o bombeiros,
        # SR.ler esperou 600 s, desistiu LIMPO e o runner logou rc=0 lidos=8 (a contagem VELHA).
        # "Sem erro" que não produziu nada tem de gritar — senão o lote inteiro queima em silêncio.
        if n <= antes:
            say(f"processo {p} rc=1 SEM GANHO ({antes} → {n}) — browser ocupado? lock alheio?")
            continue
        say(f"processo {p} rc=0 lidos={n} (antes {antes})")
    except Exception as e:  # noqa: BLE001 — um processo ruim não derruba o lote
        say(f"processo {p} rc=1 erro={str(e)[:120]}")
        continue
    try:
        arquivar(p)
        say(f"arquivar {p} rc=0")
    except Exception as e:  # noqa: BLE001
        say(f"arquivar {p} rc=1 erro={str(e)[:120]}")
say("fim")
PY
say "fim"
