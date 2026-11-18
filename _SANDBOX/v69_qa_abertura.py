"""v69 · A/B da abertura (SOMENTE LEITURA): código v64 × filme Blender, com o bundle/CSS/assets do worktree
injetados por interceptação sobre o painel real (sem 2º servidor). Guarda de rede: todo método ≠ GET/HEAD e todo
GET de ação é barrado e respondido pelo próprio teste — provado no fim (POST sonda tem de voltar "bloqueado").

Quadros determinísticos: as animações (WAAPI) e o vídeo são congelados e levados ao MESMO instante nos dois modos;
timers longos (saída) não disparam enquanto se fotografa. Independe da carga da VM.

Uso: xvfb-run -a python _SANDBOX/v69_qa_abertura.py <codigo|video|curta|queda> <cel|desk> [seq]
     curta = visita repetida do dia com a curta já pré-carregada (filme de 1,2 s)
     queda = vídeo indisponível (404 nos assets v69) sem forçar: tem de cair na abertura em código
     seq = além dos 4 quadros, a sequência inteira a 30 q/s (para o vídeo lado a lado)
"""
import json, re, sys, pathlib, mimetypes, shutil
from playwright.sync_api import sync_playwright
WT = pathlib.Path('/home/ubuntu/JFN-wt-v69'); BASE = 'http://127.0.0.1:8000'
modo, tela = sys.argv[1], sys.argv[2]; seq = 'seq' in sys.argv[3:]
SH = WT / 'screenshots/v69'; SH.mkdir(parents=True, exist_ok=True)
SEQ = pathlib.Path('/tmp/v69/seq') / f'{modo}_{tela}'
UA_CEL = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1"
VP = {'cel': dict(viewport={'width': 390, 'height': 844}, device_scale_factor=3, is_mobile=True, has_touch=True, user_agent=UA_CEL),
      'desk': dict(viewport={'width': 1440, 'height': 900}, device_scale_factor=1)}[tela]
LOCAL = ('/static/js/painel.bundle.js', '/static/assets/v69/', '/static/css/painel.css')
ACAO = re.compile(r'(gerar|iniciar|disparar|rodar|consultar|avaliar|enviar|envio|acionar|executar|veredito|limpar|reprocess|coletar|pausar|retomar|telegram|whatsapp|wa_|e-?mail|smtp|protocol|notific|push|lai/(?!lista|prazos))', re.I)
INIT = """(()=>{try{localStorage.removeItem('jfn_abertura_dia');localStorage.removeItem('jfn_portal_off');localStorage.setItem('jfn_abertura_video','%s')}catch(e){}
/* timers >= 400 ms nao correm no relogio real: entram numa fila e disparam no instante simulado (CONGELA). No filme o
   instante devido = tempo do video no registro + ms; no codigo = (registro - inicio das animacoes da abertura) + ms. */
const st=window.setTimeout;window.__st=st;window.__fila=[];
new MutationObserver((ms,o)=>{const a=document.getElementById('v64-abertura');if(a&&a.children.length&&!window.__t0){window.__t0=performance.now();o.disconnect()}})
  .observe(document,{childList:true,subtree:true});
window.setTimeout=(f,ms,...a)=>{if(ms<400||window.__solta)return st(f,ms,...a);
  const v=document.querySelector('#v64-abertura video');
  window.__fila.push({f:()=>f(...a),ms,reg:performance.now(),vt:(v&&!v.paused&&v.currentTime>0)?v.currentTime*1000:null,feito:false});return 0}})();"""
INSTANTES = (100, 400, 700, 1000) if modo == 'curta' else (400, 1100, 1900, 2600)
CONGELA = """async(t)=>{const el=document.getElementById('v64-abertura');if(!el)return;
  const minhas=()=>document.getAnimations().filter(a=>{const g=a.effect&&a.effect.target;return g&&el.contains(g)});
  const dev=x=>x.vt!=null?x.vt+x.ms:(x.reg-window.__t0)+x.ms;
  window.__nasc=window.__nasc||new Map();
  for(const x of window.__fila.filter(x=>!x.feito&&x.reg>=window.__t0-5&&dev(x)<=t).sort((a,b)=>dev(a)-dev(b))){
    const antes=new Set(document.getAnimations());x.feito=true;try{x.f()}catch(e){}
    for(const a of document.getAnimations())if(!antes.has(a))window.__nasc.set(a,dev(x))}
  for(const a of minhas()){a.pause();a.currentTime=Math.max(0,t-(window.__nasc.get(a)||0))}
  const v=el.querySelector('video');if(v){v.pause();v.currentTime=Math.min(t/1000,(v.duration||9)-.001);
    await new Promise(r=>{v.addEventListener('seeked',r,{once:true});window.__st(r,8000)})}}"""


def senha():
    for l in pathlib.Path('/home/ubuntu/JFN/.env').read_text().splitlines():
        if l.startswith('JFN_DASH_PASSWORD='):
            return l.split('=', 1)[1].strip().strip('"').strip("'")
    return ''


def main():
    bloq = []
    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=False, args=['--no-sandbox', '--use-angle=swiftshader', '--enable-unsafe-swiftshader',
                                                     '--autoplay-policy=no-user-gesture-required'])
        c0 = b.new_context(**VP)
        p = c0.new_page(); p.goto(BASE + '/login_jfn'); p.fill('input[name=senha]', senha()); p.press('input[name=senha]', 'Enter')
        p.wait_for_timeout(2000); est = c0.storage_state(); c0.close()
        ctx = b.new_context(**VP, storage_state=est)
        ctx.add_init_script(INIT % {'video': '1', 'curta': '1', 'codigo': '0', 'queda': ''}[modo])
        if modo == 'curta':
            ctx.add_init_script("(()=>{const d=new Date(),p=n=>String(n).padStart(2,'0');try{localStorage.setItem('jfn_abertura_dia',"
                                "`${d.getFullYear()}-${p(d.getMonth()+1)}-${p(d.getDate())}`);localStorage.setItem('jfn_abertura_c_ok','1')}catch(e){}})();")
        if modo == 'queda':
            ctx.add_init_script("(()=>{window.__solta=1;try{localStorage.removeItem('jfn_abertura_video')}catch(e){}})();")   # relógio real

        def guarda(route):
            r = route.request; cam = r.url.split('127.0.0.1:8000', 1)[-1].split('?')[0]
            if r.method not in ('GET', 'HEAD') or (r.url.startswith(BASE) and not cam.startswith('/static/') and ACAO.search(cam)):
                bloq.append(f'{r.method} {cam}')
                return route.fulfill(status=200, content_type='application/json', body='{"ok":false,"erro":"bloqueado pelo teste v69"}')
            if modo == 'queda' and cam.startswith('/static/assets/v69/'):
                return route.fulfill(status=404, body='')
            if r.url.startswith(BASE) and cam.startswith(LOCAL):
                f = WT / cam.lstrip('/')
                if f.exists():
                    dado = f.read_bytes(); tipo = mimetypes.guess_type(str(f))[0] or 'application/octet-stream'
                    if f.name.endswith('.webm'): tipo = 'video/webm'
                    rg = r.headers.get('range')
                    if rg and cam.endswith(('.mp4', '.webm')):
                        a, _, z = rg.replace('bytes=', '').partition('-'); a = int(a); z = int(z) if z else len(dado) - 1
                        return route.fulfill(status=206, body=dado[a:z + 1], headers={'Content-Type': tipo, 'Accept-Ranges': 'bytes',
                                             'Content-Range': f'bytes {a}-{z}/{len(dado)}', 'Content-Length': str(z - a + 1)})
                    return route.fulfill(status=200, body=dado, headers={'Content-Type': tipo})
            return route.continue_()
        ctx.route('**/*', guarda)
        p = ctx.new_page(); erros = []
        p.on('pageerror', lambda e: erros.append(str(e)[:160]))
        p.goto(BASE + '/', wait_until='domcontentloaded')
        p.wait_for_function("()=>{const a=document.getElementById('v64-abertura');return a&&a.children.length>1}", timeout=60000)
        if modo == 'queda':                                   # a espera de 600 ms corre no relógio real (< 400 ms não entra na fila)
            p.wait_for_function("()=>!!document.querySelector('#v64-abertura .ab-reator')", timeout=20000)
        if modo in ('video', 'curta'):
            p.wait_for_function("()=>{const v=document.querySelector('#v64-abertura video');return v&&!v.paused&&v.currentTime>0}", timeout=20000)
        info = p.evaluate("""()=>{const el=document.getElementById('v64-abertura'),v=el.querySelector('video');
          return {classe:el.className,filme:v?v.currentSrc.split('/').pop():null,tem_reator_codigo:!!el.querySelector('.ab-reator'),
                  w:v?v.videoWidth:null,h:v?v.videoHeight:null,ab_s:getComputedStyle(el).getPropertyValue('--ab-s')}}""")
        for k, t in enumerate(INSTANTES):
            p.evaluate(CONGELA, t); p.wait_for_timeout(500)
            p.screenshot(path=str(SH / f'ab_{modo}_{tela}_q{k + 1}_{t}ms.png'), timeout=180000, scale='css')
        if seq:
            shutil.rmtree(SEQ, ignore_errors=True); SEQ.mkdir(parents=True)
            for i, t in enumerate(range(0, 3201, 33)):
                p.evaluate(CONGELA, t); p.wait_for_timeout(60)
                p.screenshot(path=str(SEQ / f'{i:04d}.png'), timeout=180000, scale='css')
        g = p.evaluate("async()=>{const r=await fetch('/api/x/guarda_v69',{method:'POST'});return (await r.text()).includes('bloqueado pelo teste v69')}")
        p.evaluate("()=>{window.__solta=1}")
        ctx.close(); b.close()
    bloq_nav = [x for x in bloq if 'guarda_v69' not in x]
    out = {'modo': modo, 'tela': tela, **info, 'erros': erros, 'guarda_post_barrado': g, 'bloqueados_na_navegacao': bloq_nav}
    print(json.dumps(out, ensure_ascii=False))
    (WT / f'_SANDBOX/v69_qa_abertura_{modo}_{tela}.json').write_text(json.dumps(out, ensure_ascii=False, indent=1))


main()
