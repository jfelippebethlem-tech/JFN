# -*- coding: utf-8 -*-
"""
GERADOR do arquivo unico 'hermes-tudo.sh'.
Roda no PC do Mestre Jorge. Le .env + config.yaml + auth.json do HERMES_HOME e
monta UM arquivo .sh que, ao rodar numa maquina nova (ex.: a VM), recria os 3
arquivos em ~/.hermes/ (com backup, NUNCA apaga).

Este gerador NAO contem segredo nenhum — os valores so entram no arquivo gerado,
que e salvo FORA do repo (em C:\\Users\\socah\\hermes-tudo.sh).
"""
import os, sys, base64
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HOME = r"C:\Users\socah\AppData\Local\hermes"
OUT  = r"C:\Users\socah\hermes-tudo.sh"   # fora do repo
ARQUIVOS = ["config.yaml", "auth.json", ".env"]   # config/auth nao tem CRLF problema; base64 resolve tudo

def b64(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()

linhas = []
def add(s): linhas.append(s)

add("#!/usr/bin/env bash")
add("# ============================================================")
add("# hermes-tudo.sh — instala TODA a config do Hermes em ~/.hermes/")
add("# Gerado no PC do Mestre Jorge. Contem .env, config.yaml e auth.json.")
add("# Uso: copie/transfira este arquivo para a maquina e rode:  bash hermes-tudo.sh")
add("# Ele faz backup do que existir (NUNCA apaga) e recria os 3 arquivos.")
add("#")
add("# O QUE CADA ARQUIVO E (resumo):")
add("#  .env        = tokens (Telegram, Gemini, SEI, GitHub, etc.)")
add("#  config.yaml = comportamento do agente (modelo padrao gemini + fallbacks)")
add("#  auth.json   = pool de rodizio (8 chaves Gemini + reservas)")
add("# ============================================================")
add('set -e')
add('DEST="$HOME/.hermes"')
add('mkdir -p "$DEST"')
add('STAMP=$(date +%s)')
add("")

faltando = []
for nome in ARQUIVOS:
    p = os.path.join(HOME, nome)
    if not os.path.exists(p):
        faltando.append(nome); continue
    data = b64(p)
    add(f'# ---- {nome} ----')
    add(f'[ -f "$DEST/{nome}" ] && cp "$DEST/{nome}" "$DEST/{nome}.bak.$STAMP" || true')
    add(f'echo {data} | base64 -d > "$DEST/{nome}"')
    add("")

add('chmod 600 "$DEST/.env" "$DEST/auth.json" 2>/dev/null || true')
add('echo "=== CONFIG INSTALADA em $DEST ==="')
add('ls -la "$DEST" | grep -E "\\.env|config.yaml|auth.json"')
add('python3 -c "import json,os;print(\'Gemini no pool:\',len(json.load(open(os.path.expanduser(\\"~/.hermes/auth.json\\")))[\'credential_pool\'][\'gemini\']))" 2>/dev/null || true')
add('echo "=== PRONTO. Agora pode (re)iniciar o gateway/servico yoda. ==="')

if faltando:
    print("AVISO: nao encontrei:", ", ".join(faltando), "(serao ignorados)")

with open(OUT, "w", newline="\n", encoding="utf-8") as f:
    f.write("\n".join(linhas) + "\n")

print("OK! Arquivo unico gerado em:")
print("  ", OUT)
print("Tamanho:", os.path.getsize(OUT), "bytes (contem os 3 arquivos embutidos).")
print("")
print("PROXIMO PASSO: leve esse arquivo para a VM e rode:  bash hermes-tudo.sh")
