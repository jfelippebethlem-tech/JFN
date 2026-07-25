"""Auditor de LAYOUT do painel — o que o olho vê, virado em critério verificável.

Irmão de `auditar_contraste.py`. Aquele mede cor; este mede GEOMETRIA, que foi por onde
os defeitos desta safra entraram (esferas sobrepostas a 390px, o botao A→Z arrancado de
dentro do campo, tres blocos do key-art transbordando).

Cinco laudos, todos por medicao no DOM vivo — nenhum por leitura de CSS:

  sobreposicao   dois irmaos visiveis ocupando o MESMO pixel. Foi o defeito das esferas:
                 `flex:1;min-width:0` encolhe o botao abaixo do proprio texto e o rotulo
                 vaza por cima do vizinho. So compara IRMAOS: pai×filho se sobrepoem por
                 definicao, e camadas empilhadas de proposito (`position:absolute` no
                 mesmo canto) sao idioma da casa, nao defeito.
  vazamento      filho cujo retangulo passa do retangulo do pai que tem `overflow` visivel.
  truncado       `scrollWidth > clientWidth` com `text-overflow:ellipsis` — o texto EXISTE
                 e o usuario nao le. Foi o "PREFEITURA …" e o "CENTRAL DE INTELIGÊN…".
  fora_da_tela   elemento que passa da largura do documento SEM nenhum ancestral que corte.
                 A 1a versao nao olhava o ancestral e gritou lobo: acusou o ticker (marquee
                 dentro de `overflow:hidden`) e a tabela da g_radar (dentro de card com
                 `overflow-x:auto`) — os dois transbordam DE PROPOSITO. Auditor que exagera
                 e ignorado, entao o laudo so sai quando ninguem corta.
  alvo_pequeno   acionavel pequeno demais em ponteiro grosso, em DOIS graus, porque 44px e
                 conforto e 24px e norma: `viola` = abaixo de 24px (WCAG 2.5.8 Target Size
                 Minimum, que e o piso) e `aperta` = 24-43px (abaixo do conforto que o CSS
                 da casa promete). Misturar os dois transforma decisao de design em falso
                 alarme de acessibilidade.

Uso:
    .venv/bin/python tools/auditar_layout.py              # 9 abas, 1440 e 390
    .venv/bin/python tools/auditar_layout.py g_radar 390  # uma aba, uma largura

Cache DESLIGADO sempre: sem isso o Chrome reusa a folha antiga e o laudo e do CSS velho.
"""
import json
import sys
import time
import urllib.request as ur

import websocket

ABAS = ["i_cockpit", "e_alertas", "e_comp", "g_radar", "g_comun", "g_fenix",
        "g_riscos", "p_folha", "t_busca"]
LARGURAS = [1440, 390]

if len(sys.argv) > 1:
    ABAS = [sys.argv[1]]
if len(sys.argv) > 2:
    LARGURAS = [int(sys.argv[2])]

tabs = json.load(ur.urlopen("http://127.0.0.1:9222/json"))
alvo = next(t for t in tabs if t.get("type") == "page")
ws = websocket.create_connection(alvo["webSocketDebuggerUrl"], timeout=240,
                                 suppress_origin=True)
_id = [0]


def cmd(m, p=None):
    _id[0] += 1
    ws.send(json.dumps({"id": _id[0], "method": m, "params": p or {}}))
    while True:
        r = json.loads(ws.recv())
        if r.get("id") == _id[0]:
            return r.get("result", {})


def js(e):
    r = cmd("Runtime.evaluate", {"expression": e, "returnByValue": True})
    if r.get("exceptionDetails"):
        return {"_erro": json.dumps(r["exceptionDetails"])[:300]}
    return r.get("result", {}).get("value")


SONDA = r"""(()=>{
  const achados=[];
  const alvo=document.querySelector('main')||document.body;
  const nome=e=>{
    const t=(e.tagName||'').toLowerCase();
    const c=(typeof e.className==='string'?e.className:'').trim().split(/\s+/).slice(0,2).join('.');
    const tx=(e.textContent||'').trim().replace(/\s+/g,' ').slice(0,30);
    return t+(c?'.'+c:'')+(tx?` "${tx}"`:'');
  };
  const visivel=e=>{
    const s=getComputedStyle(e);
    if(s.display==='none'||s.visibility==='hidden'||+s.opacity<0.05)return false;
    const r=e.getBoundingClientRect();
    return r.width>1&&r.height>1;
  };
  /* SOBREPOSICAO — so entre IRMAOS, e so quando NENHUM dos dois foi posicionado de
     proposito para empilhar. Sem esse filtro o laudo vira ruido: o painel empilha
     camada sobre camada em toda parte, e isso e o desenho, nao o defeito. */
  const empilhaDeProposito=e=>{
    const s=getComputedStyle(e);
    return s.position==='absolute'||s.position==='fixed'||e.tagName==='SVG'
           ||(s.gridArea&&s.gridArea!=='auto / auto / auto / auto');
  };
  alvo.querySelectorAll('*').forEach(pai=>{
    const filhos=[...pai.children].filter(visivel).filter(c=>!empilhaDeProposito(c));
    for(let i=0;i<filhos.length;i++)for(let j=i+1;j<filhos.length;j++){
      const a=filhos[i].getBoundingClientRect(),b=filhos[j].getBoundingClientRect();
      const sx=Math.min(a.right,b.right)-Math.max(a.left,b.left);
      const sy=Math.min(a.bottom,b.bottom)-Math.max(a.top,b.top);
      if(sx>2&&sy>2)achados.push({tipo:'sobreposicao',px:Math.round(sx)+'x'+Math.round(sy),
        a:nome(filhos[i]),b:nome(filhos[j])});
    }
  });
  /* VAZAMENTO — filho passando do pai que NAO corta. `overflow:hidden/auto` corta de
     proposito; barra rolavel nao e vazamento. */
  alvo.querySelectorAll('*').forEach(pai=>{
    const sp=getComputedStyle(pai);
    if(sp.overflow!=='visible'||sp.overflowX!=='visible'||sp.overflowY!=='visible')return;
    if(sp.display==='contents'||!visivel(pai))return;
    const rp=pai.getBoundingClientRect();
    [...pai.children].filter(visivel).forEach(c=>{
      if(empilhaDeProposito(c))return;
      const rc=c.getBoundingClientRect();
      const bx=Math.round(Math.max(0,rc.right-rp.right,rp.left-rc.left));
      const by=Math.round(Math.max(0,rc.bottom-rp.bottom));
      if(bx>2||by>2)achados.push({tipo:'vazamento',por:bx+'px lado / '+by+'px baixo',
        pai:nome(pai),filho:nome(c)});
    });
  });
  /* TRUNCADO — o texto existe e nao e lido. */
  alvo.querySelectorAll('*').forEach(e=>{
    if(!visivel(e)||e.children.length)return;
    const s=getComputedStyle(e);
    if(s.textOverflow!=='ellipsis')return;
    if(e.scrollWidth>e.clientWidth+1)
      achados.push({tipo:'truncado',perdeu:(e.scrollWidth-e.clientWidth)+'px',
        texto:(e.textContent||'').trim().slice(0,60)});
  });
  /* FORA DA TELA — so quando NINGUEM corta. Um marquee dentro de `overflow:hidden` e uma
     tabela dentro de card rolavel passam da tela de proposito: acusa-los e ruido. */
  const alguemCorta=e=>{
    let n=e.parentElement;
    while(n&&n!==document.documentElement){
      const s=getComputedStyle(n);
      if(/hidden|auto|scroll|clip/.test(s.overflowX+' '+s.overflow))return true;
      n=n.parentElement;
    }
    return false;
  };
  const larg=document.documentElement.clientWidth;
  alvo.querySelectorAll('*').forEach(e=>{
    if(!visivel(e))return;
    const r=e.getBoundingClientRect();
    if(r.right>larg+2&&r.width<=larg&&!alguemCorta(e))
      achados.push({tipo:'fora_da_tela',passa:Math.round(r.right-larg)+'px',quem:nome(e)});
  });
  /* ALVO PEQUENO — dois graus. 24px e a NORMA (WCAG 2.5.8); 44px e o conforto que o
     proprio CSS da casa promete em `pointer:coarse`. Separar os dois evita transformar
     escolha de composicao (os rotulos flutuantes da mesa, a 29px) em violacao. */
  if(matchMedia('(pointer:coarse)').matches){
    alvo.querySelectorAll('button,a,.btn,.chip,.sph,.az,.clk').forEach(e=>{
      if(!visivel(e))return;
      const r=e.getBoundingClientRect();
      if(r.height>=44)return;
      achados.push({tipo:r.height<24?'alvo_viola_norma':'alvo_aperta',
        altura:Math.round(r.height)+'px',quem:nome(e)});
    });
  }
  const visto=new Set();
  const unicos=achados.filter(a=>{const k=JSON.stringify(a);
    if(visto.has(k))return false;visto.add(k);return true;});
  /* NUNCA truncar em silencio: quem le precisa saber que a lista foi cortada. */
  return {total:unicos.length,mostrando:Math.min(unicos.length,40),itens:unicos.slice(0,40)};
})()"""

cmd("Network.enable")
cmd("Network.setCacheDisabled", {"cacheDisabled": True})

total = 0
for larg in LARGURAS:
    print(f"\n{'='*66}\n  {larg}px\n{'='*66}")
    cmd("Emulation.setDeviceMetricsOverride",
        {"width": larg, "height": 900, "deviceScaleFactor": 1, "mobile": larg < 700})
    cmd("Emulation.setTouchEmulationEnabled", {"enabled": larg < 700})
    cmd("Page.navigate", {"url": "http://127.0.0.1:8000/painel"})
    time.sleep(10)
    for aba in ABAS:
        js(f"typeof ir==='function'&&ir('{aba}')")
        time.sleep(4.5)
        r = js(SONDA)
        if not isinstance(r, dict) or r.get("_erro"):
            print(f"  {aba:12s} ERRO NA SONDA {str(r)[:140]}")
            continue
        itens, n = r["itens"], r["total"]
        total += n
        corte = "" if n == r["mostrando"] else f" (mostrando {r['mostrando']})"
        print(f"  {aba:12s} {'ok' if not n else f'{n} achado(s){corte}'}")
        porTipo = {}
        for a in itens:
            porTipo.setdefault(a["tipo"], []).append(a)
        for tipo, itens in porTipo.items():
            print(f"      {tipo} ({len(itens)}):")
            for a in itens[:4]:
                d = {k: v for k, v in a.items() if k != "tipo"}
                print("        · " + " | ".join(f"{k}={v}" for k, v in d.items()))

print(f"\n=== {total} achado(s) de layout no total ===")
ws.close()
