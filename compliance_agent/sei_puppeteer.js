const puppeteer = require('puppeteer');
const { execSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const SEARCH_URL = 'https://sei.rj.gov.br/sei/modulos/pesquisa/md_pesq_processo_pesquisar.php?acao_externa=protocolo_pesquisar&acao_origem_externa=protocolo_pesquisar&id_orgao_acesso_externo=6';
const SAVE_DIR = path.join('C:', 'JFN', 'jfn', 'data', 'tmp', 'sei_captchas');
if (!fs.existsSync(SAVE_DIR)) fs.mkdirSync(SAVE_DIR, { recursive: true });

async function solveCaptchaEasyOCR(imagePath) {
  const py = `"C:/Users/socah/AppData/Local/Programs/Python/Python312/python.exe" - <<'PY'
import sys
sys.path.insert(0, r'C:\\JFN\\jfn')
import easyocr
from pathlib import Path
img = Path(r'${imagePath.replace(/\\/g, '\\\\')}')
reader = easyocr.Reader(['en'], gpu=False)
res = reader.readtext(str(img), detail=1, paragraph=False)
caps = []
for item in res:
    text = item[1].strip()
    conf = float(item[2])
    if 4 <= len(text) <= 8 and any(c.isdigit() for c in text) and any(c.isalpha() for c in text):
        caps.append((text, conf))
caps.sort(key=lambda x: x[1], reverse=True)
print(caps[0][0] if caps else '')
PY`;
  try {
    const out = execSync(py, { encoding: 'utf8', timeout: 120000 }).trim();
    return out;
  } catch (e) {
    console.error('EasyOCR failed:', e.message);
    return '';
  }
}

(async () => {
  // Conectar ao Chrome existente via CDP
  const browser = await puppeteer.connect({
    browserURL: 'http://127.0.0.1:9222',
    defaultViewport: null,
  });

  const page = await browser.newPage();
  await page.setUserAgent('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36');

  await page.goto(SEARCH_URL, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await new Promise(r => setTimeout(r, 2500));

  // Preencher número do processo
  await page.evaluate((value) => {
    const el = document.getElementById('txtProtocoloPesquisa');
    if (!el) return;
    el.value = value;
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
  }, '150016/099785/2026');
  console.log('Processo preenchido');

  // Capturar imagem do captcha
  const imgSrc = await page.$eval('#imgCaptcha', el => el.src);
  if (!imgSrc.startsWith('data:image')) {
    throw new Error('Captcha base64 não encontrado');
  }
  const b64 = imgSrc.split(',')[1];
  const imgPath = path.join(SAVE_DIR, 'captcha_puppeteer.png');
  fs.writeFileSync(imgPath, Buffer.from(b64, 'base64'));
  console.log('Captcha salvo:', imgPath);

  // Resolver com EasyOCR via Python
  const captchaText = await solveCaptchaEasyOCR(imgPath);
  console.log('Captcha resolvido:', captchaText);

  // Preencher campo do captcha
  await page.evaluate((value) => {
    const el = document.getElementById('txtInfraCaptcha');
    if (!el) return;
    el.value = value;
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
  }, captchaText);
  console.log('Captcha preenchido:', captchaText);

  // Clicar em Pesquisar
  await page.evaluate(() => {
    const btn = document.getElementById('sbmPesquisar');
    if (!btn) return;
    btn.click();
  });
  console.log('Botão Pesquisar clicado');
  await new Promise(r => setTimeout(r, 4000));

  await page.screenshot({ path: path.join(SAVE_DIR, 'resultado_puppeteer.png'), fullPage: false });
  const bodyText = await page.$eval('body', el => el.innerText);
  const finalUrl = await page.url();
  console.log('URL final:', finalUrl);
  console.log('BODY start:', bodyText.slice(0, 3000));

  // Salvar resultado
  const result = {
    captcha: captchaText,
    url: finalUrl,
    body: bodyText.slice(0, 5000),
  };
  fs.writeFileSync(path.join(SAVE_DIR, 'resultado_puppeteer.json'), JSON.stringify(result, null, 2), 'utf8');
  console.log('Resultado salvo em', path.join(SAVE_DIR, 'resultado_puppeteer.json'));

  await browser.disconnect();
})();
