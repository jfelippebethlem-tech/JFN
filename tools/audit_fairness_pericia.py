# -*- coding: utf-8 -*-
"""Auditoria de FAIRNESS da perícia de benefícios (guard contra o "caso Vivian").

Verifica, sobre a saída de pericia_beneficios.analisar():
  AUDIT1 — nenhum programa de benefício exibido cai TOTALMENTE fora das janelas de vínculo público
           da pessoa (Câmara: ingresso→atual; Prefeitura: faixa na folha). Deve ser 0.
  AUDIT2 — todo registro tem ao menos uma janela de vínculo legível. Deve ser 0.
Rodar após qualquer mudança na lógica de cruzamento benefício×vínculo:
    cd ~/JFN && PYTHONPATH=. .venv/bin/python tools/audit_fairness_pericia.py
"""
from compliance_agent.pcrj import pericia_beneficios as pb
import re
d=pb.analisar(); regs=d['registros']
print('total registros:',len(regs),'| excluídos por benefício fora do vínculo:',d['fora_vinculo'])
meses={'jan':1,'fev':2,'mar':3,'abr':4,'mai':5,'jun':6,'jul':7,'ago':8,'set':9,'out':10,'nov':11,'dez':12}
def prog_ym(s):  # 'jul/2025' -> '202507'
    m=re.match(r'([a-z]{3})/(\d{4})',s); return f"{m.group(2)}{meses[m.group(1)]:02d}" if m else None
def win_ym(s):   # aceita 'dez/2020' OU '01/05/2025' (DD/MM/YYYY) OU 'atual'
    s=s.strip()
    if s=='atual': return '209912'
    m=re.match(r'([a-z]{3})/(\d{4})',s)
    if m: return f"{m.group(2)}{meses[m.group(1)]:02d}"
    m=re.match(r'\d{2}/(\d{2})/(\d{4})',s)
    if m: return f"{m.group(2)}{m.group(1)}"
    return None
def janelas(v):
    out=[]
    for parte in v.split(' · '):
        m=re.search(r':\s*(.+?)→(.+)$',parte)
        if m:
            lo,hi=win_ym(m.group(1)),win_ym(m.group(2))
            if lo and hi: out.append((lo,hi))
    return out
fora=0; ex=[]
for r in regs:
    jan=janelas(r.get('vinculos',''))
    if not jan: continue
    for pr in r['programas']:
        pd,pa=prog_ym(pr['desde']),prog_ym(pr['ate'])
        if not any(lo<=pa and pd<=hi for lo,hi in jan):
            fora+=1
            if len(ex)<6: ex.append((r['nome'][:26],r['vinculos'][:46],pr['ben'],pr['desde']+'→'+pr['ate']))
            break
print('AUDIT1 — programa totalmente fora de toda janela de vínculo (deve ser 0):',fora)
for e in ex: print('   ',e)
# AUDIT2: registro sem nenhuma janela parseável (não deveria)
semjan=sum(1 for r in regs if not janelas(r.get('vinculos','')))
print('AUDIT2 — registros sem janela de vínculo legível:',semjan)
print('OK — auditoria concluída')
