"""Contraste REAL do texto do painel, aba por aba (WCAG 2.1).

A primeira versao deste probe lia `getComputedStyle().color` com uma regex de digitos —
mas o Chrome devolve `oklch(0.96 0.012 230)` para a paleta da casa, e ler esses tres
numeros como RGB produz laudo falso. Aqui a cor e resolvida pintando 1 pixel num canvas
e lendo de volta: funciona para QUALQUER notacao que o navegador entenda.

O fundo efetivo tambem e resolvido de verdade — subindo a cadeia de ancestrais ate achar
um fundo opaco, que e o que o olho enxerga atras do texto.
"""
import json
import sys
import time
import urllib.request as ur

import websocket

# Nivel 2. O import tem duas formas porque este arquivo e chamado como SCRIPT
# (`python tools/auditar_contraste.py`, e ai sys.path[0] e `tools/`) e tambem
# importado como modulo do pacote em teste.
try:
    from tools.auditar_contraste_pixel import medir_pagina_atual
except ImportError:  # pragma: no cover - depende de como o processo foi iniciado
    from auditar_contraste_pixel import medir_pagina_atual

try:
    from tools.painel_abas import abas as _abas_do_painel
except ImportError:  # pragma: no cover
    from painel_abas import abas as _abas_do_painel

# 51 abas, lidas do proprio painel — a lista fixa de 9 envelhecia calada e o laudo
# parcial era lido como laudo do painel inteiro.
ABAS = _abas_do_painel()
if len(sys.argv) > 1:            # uma aba so, para depurar sem pagar as 51
    ABAS = sys.argv[1:]
tabs = json.load(ur.urlopen("http://127.0.0.1:9222/json"))
alvo = next(t for t in tabs if t.get("type") == "page")
ws = websocket.create_connection(alvo["webSocketDebuggerUrl"], timeout=120, suppress_origin=True)
i = [0]

def cmd(m, p=None):
    i[0] += 1
    ws.send(json.dumps({"id": i[0], "method": m, "params": p or {}}))
    while True:
        r = json.loads(ws.recv())
        if r.get("id") == i[0]:
            return r.get("result", {})

def js(e):
    r = cmd("Runtime.evaluate", {"expression": e, "returnByValue": True})
    if r.get("exceptionDetails"):
        return {"_erro": json.dumps(r["exceptionDetails"])[:300]}
    return r.get("result", {}).get("value")

MEDE = r"""(()=>{
  const cv=document.createElement('canvas');cv.width=cv.height=1;
  const g=cv.getContext('2d',{willReadFrequently:true});
  const cache={};
  const rgb=css=>{                      // qualquer notacao -> [r,g,b,a]
    if(cache[css])return cache[css];
    g.clearRect(0,0,1,1);
    try{g.fillStyle='#000';g.fillStyle=css;}catch(e){return cache[css]=null;}
    g.fillRect(0,0,1,1);
    const d=g.getImageData(0,0,1,1).data;
    return cache[css]=[d[0],d[1],d[2],d[3]/255];
  };
  const L=c=>{const f=v=>{v/=255;return v<=0.03928?v/12.92:Math.pow((v+0.055)/1.055,2.4)};
    return 0.2126*f(c[0])+0.7152*f(c[1])+0.0722*f(c[2]);};
  const mistura=(fg,bg)=>[0,1,2].map(k=>fg[k]*fg[3]+bg[k]*(1-fg[3]));
  /* Fundo efetivo: junta as camadas semitransparentes DE BAIXO PARA CIMA.
     A primeira versao parava na primeira camada com alpha>0 e usava a cor CRUA dela —
     um texto rosa sobre um veu de rosa a 7% dava 1,00:1, laudo falso. */
  const fundoEfetivo=el=>{
    const camadas=[];let n=el;
    while(n&&n!==document.documentElement){
      const c=rgb(getComputedStyle(n).backgroundColor);
      if(c&&c[3]>0){camadas.push(c);if(c[3]>=0.999)break;}
      n=n.parentElement;
    }
    const raiz=rgb(getComputedStyle(document.documentElement).backgroundColor);
    let base=(camadas.length&&camadas[camadas.length-1][3]>=0.999)
             ? camadas.pop().slice(0,3)
             : ((raiz&&raiz[3]>0.999)?raiz.slice(0,3):[8,10,20]);
    for(let i=camadas.length-1;i>=0;i--)base=mistura(camadas[i],base);
    return base;
  };
  const vis=e=>{const s=getComputedStyle(e);
    return s.display!=='none'&&s.visibility!=='hidden'&&e.offsetParent!==null&&+s.opacity>0.05};
  const out=[];let delegados=0;
  for(const e of document.querySelectorAll('body *')){
    if(!vis(e))continue;
    const t=[...e.childNodes].filter(n=>n.nodeType===3).map(n=>n.nodeValue.trim()).join('');
    if(t.length<8)continue;                       // texto de verdade, nao um simbolo
    const s=getComputedStyle(e);
    const px=parseFloat(s.fontSize), peso=parseInt(s.fontWeight)||400;
    const grande = px>=24 || (px>=18.66 && peso>=700);
    const fg0=rgb(s.color); if(!fg0)continue;
    /* Fundo pintado por IMAGEM (gradiente) nao e legivel por `backgroundColor`: a
       medicao cairia no fundo do ancestral e acusaria um falso 1,00:1 — foi o que
       aconteceu com `.chip.on`, que pinta o proprio fundo com linear-gradient. Nesse
       caso o probe declara que NAO SABE, em vez de inventar um laudo. */
    let img=null;
    for(let n=e;n&&n!==document.documentElement;n=n.parentElement){
      const bi=getComputedStyle(n).backgroundImage;
      if(bi&&bi!=='none'){img=bi;break;}
      const c0=rgb(getComputedStyle(n).backgroundColor);
      if(c0&&c0[3]>=0.999)break;                 // fundo opaco antes de qualquer imagem
    }
    /* Fundo NAO plano -> nivel 2. Ate 2026-07-25 este ramo tentava adivinhar o
       fundo pelas PARADAS de cor declaradas no gradiente, e errava nos dois
       sentidos: acusava "Fornecedor" a 1,02:1 por causa de uma faixa de 1px longe
       do glifo (falso positivo, do qual nasceu uma regra de projeto inteira), e
       aprovava texto claro sobre camada de baixo clara porque so lia a camada de
       cima (falso negativo, o pior dos dois). Contra o gabarito de 4 casos ele
       acertava 1. Agora nao adivinha: delega para `auditar_contraste_pixel`, que
       fotografa o fundo em vez de deduzi-lo. */
    if(img){delegados++;continue;}
    const bg=fundoEfetivo(e);
    const fg=fg0[3]<1?mistura(fg0,bg):fg0;
    const a=L(fg),b=L(bg);
    const cr=(Math.max(a,b)+0.05)/(Math.min(a,b)+0.05);
    const exigido=grande?3:4.5;
    if(cr<exigido){
      out.push({el:(e.id||e.className||e.tagName).toString().slice(0,40),
                px:Math.round(px*10)/10, cr:Math.round(cr*100)/100, exige:exigido,
                cor:s.color, txt:t.slice(0,34)});
    }
  }
  // deduplica por classe+tamanho: interessa o PADRAO, nao cada instancia
  const visto={},uniq=[];
  for(const o of out){const k=o.el+'|'+o.px;if(visto[k])continue;visto[k]=1;uniq.push(o);}
  return {abaixo:uniq.sort((x,y)=>x.cr-y.cr), delegados:delegados};
})()"""

cmd("Runtime.enable")
cmd("Emulation.setDeviceMetricsOverride", {"width": 1600, "height": 1000,
                                           "deviceScaleFactor": 1, "mobile": False})
cmd("Page.navigate", {"url": "http://127.0.0.1:8000/painel"})
time.sleep(26)

todos = {}
for aba in ABAS:
    js(f"try{{ir('{aba}')}}catch(e){{}}")
    time.sleep(6)
    r = js(MEDE)
    if not isinstance(r, dict) or "abaixo" not in r:
        print(f"  {aba}: erro {r}")
        continue
    delegados = r.get("delegados", 0)
    r = r["abaixo"]
    for o in (r or []):
        k = (o["el"], o["px"])
        if k not in todos or o["cr"] < todos[k]["cr"]:
            todos[k] = dict(o, aba=aba)

    # NIVEL 2 — quem tem fundo nao plano e medido no pixel, na mesma aba ja aberta.
    # Nao existe mais "nao medido": ou o nivel 1 resolveu exatamente, ou o nivel 2
    # fotografou. Silencio de auditor e o que deixa defeito passar.
    n2_falhas = 0
    for o in medir_pagina_atual(ws):
        if o.get("cr") is None:
            print(f"  {aba:12s} ATENCAO: '{o['id'][:30]}' nao pintou glifo — investigar")
            continue
        if o["passa"]:
            continue
        n2_falhas += 1
        k = (o["id"], o["px"])
        norm = {"el": o["id"], "px": o["px"], "cr": o["cr"], "exige": o["exige"],
                "cor": f"rgb{tuple(o['cor'])}", "txt": o["txt"], "aba": aba,
                "fundo": o.get("fundo"), "nivel": 2}
        if k not in todos or o["cr"] < todos[k]["cr"]:
            todos[k] = norm

    print(f"  {aba:12s} {len(r or [])} abaixo do exigido (nivel 1) · "
          f"{delegados} delegado(s) ao pixel, {n2_falhas} abaixo (nivel 2)")

print(f"\n=== {len(todos)} padrao(oes) de texto abaixo do minimo WCAG ===")
for o in sorted(todos.values(), key=lambda x: x["cr"])[:25]:
    print(f"  {o['cr']:5.2f}:1 (exige {o['exige']})  {o['px']:>5}px  {o['el'][:34]:34s} {o['cor'][:26]:26s} {o['txt'][:30]!r}")
