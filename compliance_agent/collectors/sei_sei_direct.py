import time, re, os, json
from pathlib import Path
from playwright.sync_api import sync_playwright
import easyocr

SEARCH_URL = "https://sei.rj.gov.br/sei/modulos/pesquisa/md_pesq_processo_pesquisar.php?acao_externa=protocolo_pesquisar&acao_origem_externa=protocolo_pesquisar&id_orgao_acesso_externo=6"
OUT = Path(os.environ.get("JFN_DATA_DIR", "data")) / "tmp" / "sei_run"
OUT.mkdir(parents=True, exist_ok=True)

reader = easyocr.Reader(['en'], gpu=False)

def screenshot_full(page, name):
    p = OUT / name
    page.screenshot(path=str(p), full_page=False)
    return str(p)

with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222", timeout=20000)
    ctx = browser.contexts[0]
    page = next((pg for pg in ctx.pages if pg.url().startswith("http")), None)
    if page is None:
        page = ctx.new_page()
    page.set_default_timeout(30000)
    page.goto(SEARCH_URL, wait_until="domcontentloaded", timeout=30000)
    time.sleep(2)
    print("URL:", page.url)
    print("TITLE:", page.title())
    screenshot_full(page, "01_loaded.png")
    body = page.inner_text("body")
    print("BODY:\n", body[:1200])

    # Seletores
    input_sel = 'input[name="txtPesquisaRapida"], input[name="txtNroProcesso"], input[name="txtPesquisa"], input[id*="txtPesquisa"]'
    campo = page.query_selector(input_sel)
    print("Campo busca encontrado:", bool(campo))
    btn = page.query_selector('button[name="btnPesquisar"], input[name="btnPesquisar"], button:has-text("Pesquisar")')
    print("Botão Pesquisar encontrado:", bool(btn))

    # Listar elementos com @alt 'Texto da imagem' e imagem próxima
    info = page.evaluate("""() => {
      const out = {labels: [], imgs: [], inputs: []};
      for (const el of document.querySelectorAll('label,img,input')) {
        const txt = ((el.innerText || el.textContent || el.getAttribute('alt') || '')).trim();
        if (/ texto da imagem /i.test(txt) || /captcha/i.test(txt + el.id + (el.className||''))) out.labels.push(txt.slice(0,80));
      }
      for (const el of document.querySelectorAll('img')) {
        out.imgs.push({id:el.id, cls:(el.className||'').toString().slice(0,40), src:(el.src||'').slice(0,140), w: Math.round((el.getBoundingClientRect()||{}).width||0), h: Math.round((el.getBoundingClientRect()||{}).height||0)});
      }
      for (const el of document.querySelectorAll('input,textarea')) {
        out.inputs.push({id:el.id, name:el.getAttribute('name')||'', type:el.getAttribute('type')||'', x: Math.round((el.getBoundingClientRect()||{}).x||0), y: Math.round((el.getBoundingClientRect()||{}).y||0)});
      }
      return out;
    }""")
    print(json.dumps(info, indent=2, ensure_ascii=False))

    # Recorta lower-right box por heurística
    vp = page.viewport_size or {"width":1280,"height":900}
    W, H = vp["width"], vp["height"]
    clip = {"x": int(W*0.58), "y": int(H*0.80), "width": min(380, W - int(W*0.58)), "height": min(140, H - int(H*0.80))}
    shot_box = OUT / "02_captcha_box.png"
    page.screenshot(path=str(shot_box), clip=clip)
    print('Salvo screenshot box captcha:', shot_box)

    # OCR no box
    res_box = reader.readtext(str(shot_box), detail=0, paragraph=False)
    print('EasyOCR box =>', res_box)

    # If image element exists, try direct screenshot
    img_src = None
    try:
        img_src = page.evaluate("""() => {
          const el = document.querySelector('img[id*="captcha"], img[src*="captcha"], img.captcha, #imgCaptcha');
          if (!el) return '';
          return (el.src || el.getAttribute('src') || '').trim();
        }""")
    except Exception as e:
        print('eval img err', e)
    print('img src candidata:', img_src)

    browser.close()
