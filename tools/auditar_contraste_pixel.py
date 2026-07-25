"""Contraste medido no PIXEL — o que esta REALMENTE atras dos glifos.

Por que este arquivo existe
---------------------------
`auditar_contraste.py` resolve o fundo lendo as PARADAS de cor declaradas no
`background-image` (linhas 84-108). Isso da laudo errado nos dois sentidos:

1. **Cego para geometria.** Ele nao sabe ONDE o gradiente pinta. Uma faixa de 1px
   encostada na borda de baixo foi lida como fundo do glifo e acusou "Fornecedor"
   a 1,02:1 — um texto perfeitamente legivel. Desse laudo falso nasceu uma regra
   de projeto ("nunca decore o fundo de quem carrega texto") que custou capacidade
   de design sem consertar o instrumento.
2. **Ponto cego na camada de baixo.** O remendo do problema 1 foi ler SO a
   primeira camada. Com isso, camada de cima quase transparente sobre camada de
   baixo clara **passa calada** — falso negativo, que num auditor de
   acessibilidade e pior que o falso positivo: deixa passar falha real.
3. **Parada declarada nao e pixel pintado.** `background-blend-mode`,
   `mix-blend-mode`, `backdrop-filter`, `filter`, opacidade de ancestral e a
   interpolacao real em oklab nao aparecem em nenhuma parada. E `url()` — que e o
   que o v14 usa para placa e nebulosa — nao tem parada nenhuma: o auditor antigo
   simplesmente emudece.

A ideia central
---------------
O fundo sob o texto nao se deduz: fotografa-se. Para cada elemento suspeito, tres
capturas da mesma caixa, mudando so a cor do texto DAQUELE elemento:

  B  = texto em `transparent`  -> o fundo puro, sem glifo nenhum;
  C1 = texto em preto;
  C2 = texto em branco;
  C1 != C2  ->  a mascara dos pixels que os glifos cobrem, antialias incluido.

O contraste e medido entre a cor resolvida do texto e o PIOR pixel de `B` sob essa
mascara — o de luminancia mais proxima a do texto. `B` nunca contem o glifo, entao
a cor do proprio texto nao contamina a medida do fundo.

**Por que a mascara vem de duas sondas, e nao da captura natural.** A primeira
versao deste arquivo montava a mascara comparando a captura natural com `B`. Isso
tem um defeito que so aparece no caso que mais importa: quando o texto e quase da
cor do fundo, a diferenca entre as duas capturas fica abaixo de qualquer limiar
razoavel, a mascara esvazia e o elemento sai como "glifo nao pintou". O
instrumento falhava exatamente onde o contraste era pior — falso negativo, a mesma
especie de defeito que este arquivo existe para corrigir. Pego pelo caso 4 do
gabarito. Com preto contra branco a mascara e maxima e independe do fundo: onde
nao ha glifo, as duas capturas sao identicas pixel a pixel.

Uma conservadora declarada: `text-shadow` e desligado nas tres capturas. Sombra
faz parte do texto, nao do fundo. Se o projeto usar sombra para melhorar
legibilidade, esta medida sera mais severa que a experiencia real — erra para o
lado seguro, de proposito.

Custo
-----
Tres capturas por elemento suspeito. Por isso o nivel 2 so e acionado por quem tem
`background-image`, `backdrop-filter`, `mix-blend-mode` ou `filter` na cadeia — o
fundo plano continua resolvido em JS, exato e em milissegundos, pelo auditor
antigo. Nada e truncado em silencio: se houver teto de amostragem, ele sai no laudo.

Uso
---
    .venv/bin/python tools/auditar_contraste_pixel.py                 # gabarito
    .venv/bin/python tools/auditar_contraste_pixel.py <url> [seletor]
"""

from __future__ import annotations

import base64
import io
import json
import sys
import time
import urllib.request as ur

import websocket
from PIL import Image, ImageChops

CDP = "http://127.0.0.1:9222/json"
GABARITO = "file:///home/ubuntu/JFN/tests/fixtures/contraste_gabarito.html"

# Pixel onde a sonda preta difere da branca e pixel de glifo. Fora do glifo as duas
# capturas sao IDENTICAS (o navegador desenha o mesmo fundo), entao qualquer valor
# acima de zero ja separa; 3 e folga contra ruido de subpixel.
LIMIAR_MASCARA = 3

# Descarta os 2% de pixels mais adversos antes de escolher o pior caso. Um unico
# pixel de artefato nao pode condenar uma tela; 2% de uma caixa de texto ainda sao
# dezenas de pixels reais. O numero e declarado, nao escondido.
RUIDO = 0.02

_id = [0]


# ─────────────────────────────────────────────────────────────── CDP cru ──
def conectar(url_ws: str | None = None) -> websocket.WebSocket:
    """Conexao CDP. `suppress_origin` e obrigatorio — sem ele o Chrome recusa com 403."""
    if url_ws is None:
        abas = json.load(ur.urlopen(CDP))
        url_ws = next(t for t in abas if t.get("type") == "page")["webSocketDebuggerUrl"]
    return websocket.create_connection(url_ws, timeout=180, suppress_origin=True)


def cmd(ws, metodo: str, params: dict | None = None) -> dict:
    _id[0] += 1
    ws.send(json.dumps({"id": _id[0], "method": metodo, "params": params or {}}))
    while True:
        r = json.loads(ws.recv())
        if r.get("id") == _id[0]:
            return r.get("result", {})


def js(ws, expr: str):
    r = cmd(ws, "Runtime.evaluate", {"expression": expr, "returnByValue": True})
    if r.get("exceptionDetails"):
        raise RuntimeError(json.dumps(r["exceptionDetails"])[:400])
    return r.get("result", {}).get("value")


# ──────────────────────────────────────────────────────── luminancia WCAG ──
def _lum(px) -> float:
    def canal(v: float) -> float:
        v /= 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    return 0.2126 * canal(px[0]) + 0.7152 * canal(px[1]) + 0.0722 * canal(px[2])


def _contraste(la: float, lb: float) -> float:
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


# ───────────────────────────────────────── inventario dos elementos alvo ──
# Roda no navegador. Devolve so quem CARREGA texto proprio e tem, na cadeia, algo
# que o auditor de paradas nao sabe resolver. Marca cada um com data-cpx para que
# o Python possa enderecar o elemento sem depender de seletor fragil.
INVENTARIO = r"""(()=>{
  const cv=document.createElement('canvas');cv.width=cv.height=1;
  const g=cv.getContext('2d',{willReadFrequently:true});
  const rgb=css=>{g.clearRect(0,0,1,1);
    try{g.fillStyle='#000';g.fillStyle=css;}catch(e){return null;}
    g.fillRect(0,0,1,1);const d=g.getImageData(0,0,1,1).data;return [d[0],d[1],d[2],d[3]/255];};
  const vis=e=>{const s=getComputedStyle(e);
    return s.display!=='none'&&s.visibility!=='hidden'&&e.offsetParent!==null&&+s.opacity>0.05;};
  /* gatilho do nivel 2: o que o auditor de paradas nao resolve corretamente */
  const suspeito=e=>{
    for(let n=e;n&&n!==document.documentElement;n=n.parentElement){
      const s=getComputedStyle(n);
      if(s.backgroundImage&&s.backgroundImage!=='none')return true;
      if(s.backdropFilter&&s.backdropFilter!=='none')return true;
      if(s.mixBlendMode&&s.mixBlendMode!=='normal')return true;
      if(s.filter&&s.filter!=='none')return true;
      const c=rgb(s.backgroundColor);
      if(c&&c[3]>=0.999)return false;      /* fundo opaco antes de qualquer imagem */
    }
    return false;};
  let n=0;const fora=[];
  for(const e of document.querySelectorAll('body *')){
    if(!vis(e))continue;
    const t=[...e.childNodes].filter(x=>x.nodeType===3).map(x=>x.nodeValue.trim()).join('');
    if(t.length<8)continue;                /* texto de verdade, nao um simbolo */
    if(!suspeito(e))continue;              /* fundo plano: o nivel 1 ja resolve */
    const s=getComputedStyle(e);
    const cor=rgb(s.color); if(!cor)continue;
    const px=parseFloat(s.fontSize), peso=parseInt(s.fontWeight)||400;
    e.setAttribute('data-cpx',String(++n));
    fora.push({cpx:n, cor:cor.slice(0,3), alfa:cor[3],
               px:Math.round(px*10)/10, grande:(px>=24||(px>=18.66&&peso>=700)),
               id:(e.id||e.className||e.tagName).toString().slice(0,44),
               verdade:e.getAttribute('data-verdade')||null,
               txt:t.slice(0,40)});
  }
  return fora;})()"""


def _caixa(ws, cpx: int) -> dict | None:
    """Rola o elemento para a tela e devolve a caixa em coordenadas de PAGINA."""
    return js(
        ws,
        f"""(()=>{{const e=document.querySelector('[data-cpx="{cpx}"]');
        if(!e)return null;e.scrollIntoView({{block:'center',inline:'nearest'}});
        const r=e.getBoundingClientRect();
        if(r.width<2||r.height<2)return null;
        return {{x:r.left+scrollX,y:r.top+scrollY,w:r.width,h:r.height}};}})()""",
    )


def _capturar(ws, caixa: dict) -> Image.Image:
    r = cmd(
        ws,
        "Page.captureScreenshot",
        {
            "format": "png",
            "captureBeyondViewport": True,
            "clip": {"x": caixa["x"], "y": caixa["y"],
                     "width": caixa["w"], "height": caixa["h"], "scale": 1},
        },
    )
    return Image.open(io.BytesIO(base64.b64decode(r["data"]))).convert("RGB")


def _pintar_texto(ws, cpx: int, cor: str) -> None:
    """Forca a cor do texto DAQUELE elemento. Guarda o valor original na 1a chamada."""
    js(ws, f"""(()=>{{const e=document.querySelector('[data-cpx="{cpx}"]');
        if(e.dataset.cpxCor===undefined){{
          e.dataset.cpxCor=e.style.color||'';e.dataset.cpxSombra=e.style.textShadow||'';}}
        e.style.setProperty('color','{cor}','important');
        e.style.setProperty('text-shadow','none','important');}})()""")


def _restaurar_texto(ws, cpx: int) -> None:
    js(ws, f"""(()=>{{const e=document.querySelector('[data-cpx="{cpx}"]');
        e.style.color=e.dataset.cpxCor||'';e.style.textShadow=e.dataset.cpxSombra||'';
        delete e.dataset.cpxCor;delete e.dataset.cpxSombra;}})()""")


def _pior_fundo(b: Image.Image, c1: Image.Image, c2: Image.Image, lum_texto: float):
    """Pior pixel de fundo sob os glifos.

    A mascara sai de `c1` (texto preto) contra `c2` (texto branco): onde nao ha
    glifo as duas capturas sao identicas. `b` (texto transparente) nunca contem
    glifo, entao o que se le ali sob a mascara e fundo puro.
    Devolve (luminancia, rgb, quantidade de pixels de glifo)."""
    if not (b.size == c1.size == c2.size):
        alvo = b.size
        c1, c2 = c1.resize(alvo), c2.resize(alvo)
    dif = ImageChops.difference(c1, c2).convert("L")
    mascara = dif.point(lambda v: 255 if v >= LIMIAR_MASCARA else 0)
    pix_b, pix_m = b.load(), mascara.load()
    larg, alt = b.size
    candidatos = []
    for y in range(alt):
        for x in range(larg):
            if pix_m[x, y]:
                p = pix_b[x, y]
                candidatos.append((abs(_lum(p) - lum_texto), p))
    if not candidatos:
        return None, None, 0
    candidatos.sort(key=lambda t: t[0])
    corte = min(len(candidatos) - 1, int(len(candidatos) * RUIDO))
    _, p = candidatos[corte]
    return _lum(p), p, len(candidatos)


# ────────────────────────────────────────────────────────────── auditoria ──
def auditar(url: str, ws=None, largura: int = 1600, altura: int = 1000,
            espera: float = 3.0) -> list[dict]:
    """Mede, no pixel, todo texto sobre fundo que o auditor de paradas nao resolve."""
    proprio = ws is None
    ws = ws or conectar()
    try:
        cmd(ws, "Runtime.enable")
        cmd(ws, "Page.enable")
        cmd(ws, "Network.enable")
        # Sem isto a auditoria nao vale nada: o Chrome reusa a folha de estilo antiga.
        cmd(ws, "Network.setCacheDisabled", {"cacheDisabled": True})
        cmd(ws, "Emulation.setDeviceMetricsOverride",
            {"width": largura, "height": altura, "deviceScaleFactor": 1, "mobile": False})
        cmd(ws, "Page.navigate", {"url": url})
        time.sleep(espera)

        alvos = js(ws, INVENTARIO) or []
        laudo = []
        for alvo in alvos:
            caixa = _caixa(ws, alvo["cpx"])
            if not caixa:
                continue
            # tres capturas da MESMA caixa, mudando so a cor do texto deste elemento
            _pintar_texto(ws, alvo["cpx"], "transparent")
            b = _capturar(ws, caixa)
            _pintar_texto(ws, alvo["cpx"], "#000")
            c1 = _capturar(ws, caixa)
            _pintar_texto(ws, alvo["cpx"], "#fff")
            c2 = _capturar(ws, caixa)
            _restaurar_texto(ws, alvo["cpx"])

            lum_tx = _lum(alvo["cor"])
            lum_bg, rgb_bg, n_glifo = _pior_fundo(b, c1, c2, lum_tx)
            if lum_bg is None:
                # Preto e branco no mesmo lugar deram a MESMA imagem: nao ha glifo
                # pintando nesta caixa (cortado por ancestral, `font-size:0`,
                # `visibility` do filho, texto fora do clip). Declarar, nao inventar.
                laudo.append(dict(alvo, cr=None, motivo="glifo nao pintou", pixels=0))
                continue
            cr = _contraste(lum_tx, lum_bg)
            exige = 3.0 if alvo["grande"] else 4.5
            laudo.append(dict(alvo, cr=round(cr, 2), exige=exige, fundo=rgb_bg,
                              pixels=n_glifo, passa=cr >= exige))
        return laudo
    finally:
        if proprio:
            ws.close()


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    url = argv[0] if argv else GABARITO
    laudo = auditar(url)
    if not laudo:
        print("nenhum elemento com fundo nao-plano — nada para o nivel 2 medir")
        return 0

    print(f"\n=== contraste medido no pixel · {len(laudo)} elemento(s) ===\n")
    reprovados = 0
    for o in laudo:
        if o.get("cr") is None:
            print(f"  ????  {o['id'][:34]:34s}  {o['motivo']}")
            continue
        marca = "ok  " if o["passa"] else "FALHA"
        if not o["passa"]:
            reprovados += 1
        veredito = "aprova" if o["passa"] else "reprova"
        gab = ""
        if o.get("verdade"):
            gab = "  ✓ gabarito" if veredito == o["verdade"] else f"  ✗ GABARITO DIZ {o['verdade']}"
        print(f"  {marca} {o['cr']:6.2f}:1 (exige {o['exige']})  {o['px']:>5}px  "
              f"{o['id'][:30]:30s} fundo={o['fundo']} glifos={o['pixels']}{gab}")
    print(f"\n{reprovados} abaixo do minimo WCAG de {len(laudo)} medidos · 0 nao medidos")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
