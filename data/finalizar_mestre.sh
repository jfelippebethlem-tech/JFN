#!/bin/bash
# Finalizador AUTÔNOMO: espera o re-pull (PID passado) terminar, regenera o dossiê-mestre com o Anexo D
# já legível (conteúdo real + OCR), divide em partes <45MB (limite do Telegram) preservando o índice
# clicável, e envia ao Yoda. Roda detached; loga em data/finalizar_mestre.log. NÃO precisa de babá.
set -u
cd /home/ubuntu/JFN || exit 1
export PYTHONPATH=.
PY=.venv/bin/python
PULLPID="${1:-}"
LOG=data/finalizar_mestre.log
say(){ echo "[$(date '+%F %T')] $*" >> "$LOG"; }

say "=== finalizador: aguardando pull PID=$PULLPID terminar ==="
if [ -n "$PULLPID" ]; then
  while kill -0 "$PULLPID" 2>/dev/null; do sleep 60; done
fi
say "pull terminou; processos na íntegra:"
ls -la data/proc_integra/*.pdf >> "$LOG" 2>&1

# 1) regenera o mestre (montar() já injeta índice clicável + links + Anexo D de data/proc_integra)
say "regenerando mestre (montar)…"
$PY - <<'PY' >> "$LOG" 2>&1
import asyncio
from tools.dossie_master import montar
p = asyncio.run(montar())
print("MASTER:", p)
PY

# 2) divide + envia (análise+AnexoD pequeno; anexos probatórios A-C em partes <45MB) + envia
say "dividindo e enviando…"
$PY - <<'PY' >> "$LOG" 2>&1
import os, re, glob, asyncio, fitz
from datetime import date
# acha o mestre mais novo
masters = sorted(glob.glob("reports/DOSSIE_MASTER_pampolha_ambientejovem_*.pdf"), key=os.path.getmtime)
M = masters[-1]
d = fitz.open(M); toc = d.get_toc(); n = d.page_count
def anc(pref):
    for lvl,t,pg in toc:
        if t.startswith(pref): return pg
    return None
A = anc("ANEXO A") or (n//2); D = anc("ANEXO D") or n
outs = []
# LEITURA = análise (1..A-1) + Anexo D (D..n)
lei = fitz.open(); lei.insert_pdf(d, from_page=0, to_page=A-2); base = lei.page_count
if D <= n: lei.insert_pdf(d, from_page=D-1, to_page=n-1)
sub = []
for lvl,t,pg in toc:
    if pg <= A-1: sub.append([lvl,t,pg])
    elif pg >= D: sub.append([min(lvl,2),t, base+(pg-(D-1))])
if sub: lei.set_toc(sub)
P_LEI = f"reports/DOSSIE_leitura_completo_{date.today()}.pdf"; lei.save(P_LEI, deflate=True, garbage=4); lei.close()
outs.append((P_LEI, "📘 DOSSIÊ (leitura): análise completa + Anexo D — processos INEA na ÍNTEGRA com conteúdo real (OCR). Índice clicável."))
# ANEXOS PROBATÓRIOS A..D-1 em 2 partes <45MB
ini, fim = A-1, D-2
if fim > ini:
    meio = ini + (fim-ini)//2
    for k,(a,b) in enumerate([(ini,meio),(meio+1,fim)],1):
        part = fitz.open(); part.insert_pdf(d, from_page=a, to_page=b)
        pp = f"reports/DOSSIE_anexos_probatorios_completo_{date.today()}_v{k}.pdf"; part.save(pp, deflate=True, garbage=1); part.close()
        mb = os.path.getsize(pp)/1e6
        outs.append((pp, f"📎 Anexos probatórios (parte {k}) — instrumentos/TCE/CEDAE (escaneados), {mb:.0f}MB"))
# envia
for ln in open(".env", encoding="utf-8", errors="replace"):
    m = re.match(r"^\s*([A-Z0-9_]+)\s*=\s*(.*?)\s*$", ln)
    if m: os.environ.setdefault(m.group(1), m.group(2).strip().strip('"').strip("'"))
CHAT = os.environ.get("TELEGRAM_OWNER_ID","")
from compliance_agent.notifications.telegram import enviar_arquivo, enviar_mensagem
LIM = 45*1024*1024
def partir(path, cap):
    """Se >45MB, divide em N partes por página (<45MB cada) preservando ordem. Retorna [(path,cap)]."""
    sz = os.path.getsize(path)
    if sz <= LIM:
        return [(path, cap)]
    src = fitz.open(path); npart = sz//LIM + 1; per = (src.page_count//npart) + 1; res = []
    for i, k in enumerate(range(0, src.page_count, per), 1):
        pt = fitz.open(); pt.insert_pdf(src, from_page=k, to_page=min(k+per-1, src.page_count-1))
        pp = path.replace(".pdf", f"_p{i}.pdf"); pt.save(pp, deflate=True, garbage=1); pt.close()
        res.append((pp, cap + f" (parte {i}/{npart})"))
    src.close(); return res
async def go():
    await enviar_mensagem("📕 *Dossiê-mestre COMPLETO* — re-pull concluído: o Anexo D agora traz a íntegra dos processos do INEA com o *conteúdo real legível* (planilhas, aditivos, memórias de cálculo via OCR) e a análise jurídica já corrigida com os valores reais. Segue em partes (o inteiro passa de 50MB):", chat_id=CHAT)
    envios = []
    for path, cap in outs:
        envios += partir(path, cap)
    for path, cap in envios:
        ok = await enviar_arquivo(path, caption=cap, chat_id=CHAT)
        print(("OK" if ok else "FALHOU"), os.path.basename(path), f"{os.path.getsize(path)/1e6:.1f}MB")
asyncio.run(go())
print("ENVIO COMPLETO")
PY
say "=== finalizador: FIM ==="
