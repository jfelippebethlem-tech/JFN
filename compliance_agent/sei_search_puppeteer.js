const puppeteer = require('puppeteer-core');
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
caps.sort(key=lambda x => x[1], reverse=True)
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
  });

  const page = await browser.newPage();
  
  // Navegar para o SEI
  console.log('Navegando para SEI...');
  await page.goto(SEARCH_URL, { waitUntil: 'networkidle2', timeout: 60000 });
  await new Promise(r => setTimeout(r, 3000));
  
  // Preencher número do processo
  console.log('Preenchendo processo...');
  await page.evaluate((value) => {
    const el = document.getElementById('txtProtocoloPesquisa');
    if (el) {
      el.value = value;
      el.dispatchEvent(new Event('input', { bubbles: true }));
      el.dispatchEvent(new Event('change', { bubbles: true }));
    }
  }, '150016/099785/2026');
  
  // Capturar imagem do captcha
  console.log('Capturando captcha...');
  const imgSrc = await page.$eval('#imgCaptcha', el => el.src).catch(() => null);
  if (!imgSrc) {
    console.error('Captcha não encontrado');
    await browser.disconnect();
    process.exit(1);
  }
  
  const b64 = imgSrc.split(',')[1];
  const imgPath = path.join(SAVE_DIR, 'captcha_live.png');
  fs.writeFileSync(imgPath, Buffer.from(b64, 'base64'));
  console.log('Captcha salvo:', imgPath);
  
  // Resolver com EasyOCR via Python
  console.log('Resolvendo captcha...');
  const captchaText = await solveCaptchaEasyOCR(imgPath);
  console.log('Captcha resolvido:', captchaText);
  
  if (!captchaText) {
    console.error('OCR falhou');
    await browser.disconnect();
    process.exit(1);
  }
  
  // Preencher campo do captcha
  console.log('Preenchendo captcha...');
  await page.evaluate((value) => {
    const el = document.getElementById('txtInfraCaptcha');
    if (el) {
      el.value = value;
      el.dispatchEvent(new Event('input', { bubbles: true }));
      el.dispatchEvent(new Event('change', { bubbles: true }));
    }
  }, captchaText);
  
  // Clicar em Pesquisar
  console.log('Clicando em Pesquisar...');
  await page.evaluate(() => {
    const btn = document.getElementById('sbmPesquisar') || 
                document.querySelector('input[value="Pesquisar"]') ||
                document.querySelector('button:has-text("Pesquisar")');
    if (btn) btn.click();
  });
  
  // Aguardar resultado
  await new Promise(r => setTimeout(r, 5000));
  
  // Salvar screenshot e HTML
  await page.screenshot({ path: path.join(SAVE_DIR, 'resultado_busca.png') });
  const html = await page.content();
  fs.writeFileSync(path.join(SAVE_DIR, 'resultado_busca.html'), html);
  
  // Extrair texto da página
  const bodyText = await page.$eval('body', el => el.innerText);
  console.log('URL final:', page.url());
  console.log('BODY (primeiros 2000 chars):');
  console.log(bodyText.slice(0, 2000));
  
  // Salvar resultado
  const result = {
    captcha: captchaText,
    url: page.url(),
    body: bodyText.slice(0, 5000),
    timestamp: new Date().toISOString()
  };
  fs.writeFileSync(
    path.join(SAVE_DIR, 'resultado_busca.json'),
    JSON.stringify(result, null, 2)
  );
  
  console.log('\nResultado salvo em resultado_busca.json');
  console.log('Captcha usado:', captchaText);
  
  await browser.disconnect();
})();
