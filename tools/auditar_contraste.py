"""Contraste REAL do texto do painel, aba por aba (WCAG 2.1).

A primeira versao deste probe lia `getComputedStyle().color` com uma regex de digitos —
mas o Chrome devolve `oklch(0.96 0.012 230)` para a paleta da casa, e ler esses tres
numeros como RGB produz laudo falso. Aqui a cor e resolvida pintando 1 pixel num canvas
e lendo de volta: funciona para QUALQUER notacao que o navegador entenda.

O fundo efetivo tambem e resolvido de verdade — subindo a cadeia de ancestrais ate achar
um fundo opaco, que e o que o olho enxerga atras do texto.
"""
import json
import time
import urllib.request as ur
import websocket

ABAS = ["i_cockpit", "e_alertas", "e_comp", "g_radar", "g_comun", "g_fenix",
        "g_riscos", "p_folha", "t_busca"]
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
  const out=[],naoMedidos=[];
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
    let bg;
    if(img){
      /* Gradiente de cores solidas: extrai as paradas e mede o PIOR caso (a parada
         cuja luminancia esta mais perto da do texto). Sem isso ~21 elementos por aba
         ficavam sem laudo — e auditoria que nao cobre o card, que e onde o dado mora,
         nao e auditoria. Se as paradas nao forem legiveis, declara que nao sabe. */
      /* SO a primeira camada. `background-image` empilha camadas e a PRIMEIRA e a de
         cima; as de baixo podem nem tocar o texto — o herói do painel, por exemplo, tem
         um conico recortado no `border-box` que so pinta o anel de 1px, e le-lo como
         fundo do texto acusava 1,03:1 num texto perfeitamente legivel. */
      const topo=(()=>{let d=0,ini=0;for(let k=0;k<img.length;k++){
        const ch=img[k];if(ch==='(')d++;else if(ch===')')d--;
        else if(ch===','&&d===0)return img.slice(ini,k);}return img;})();
      const paradas=(topo.match(/oklch\([^)]*\)|oklab\([^)]*\)|rgba?\([^)]*\)|#[0-9a-fA-F]{3,8}/g)||[])
        .map(rgb).filter(c=>c&&c[3]>0.05);
      if(!paradas.length){naoMedidos.push((e.id||e.className||e.tagName).toString().slice(0,40));continue;}
      const Lf=L(fg0);
      bg=paradas.reduce((pior,c)=>Math.abs(L(c)-Lf)<Math.abs(L(pior)-Lf)?c:pior).slice(0,3);
    } else bg=fundoEfetivo(e);
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
  return {abaixo:uniq.sort((x,y)=>x.cr-y.cr), nao_medidos:[...new Set(naoMedidos)].length};
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
    nm = r.get("nao_medidos", 0)
    r = r["abaixo"]
    for o in (r or []):
        k = (o["el"], o["px"])
        if k not in todos or o["cr"] < todos[k]["cr"]:
            todos[k] = dict(o, aba=aba)
    print(f"  {aba:12s} {len(r or [])} abaixo do exigido · {nm} com fundo em gradiente (nao medivel)")

print(f"\n=== {len(todos)} padrao(oes) de texto abaixo do minimo WCAG ===")
for o in sorted(todos.values(), key=lambda x: x["cr"])[:25]:
    print(f"  {o['cr']:5.2f}:1 (exige {o['exige']})  {o['px']:>5}px  {o['el'][:34]:34s} {o['cor'][:26]:26s} {o['txt'][:30]!r}")
