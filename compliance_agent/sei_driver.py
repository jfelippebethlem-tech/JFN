from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from webdriver_manager.core.os_manager import ChromeType
import time, base64, re, json
from pathlib import Path
from PIL import Image
from io import BytesIO
import easyocr

SEARCH_URL = "https://sei.rj.gov.br/sei/modulos/pesquisa/md_pesq_processo_pesquisar.php?acao_externa=protocolo_pesquisar&acao_origem_externa=protocolo_pesquisar&id_orgao_acesso_externo=6"
SAVE_DIR = Path(r"C:\JFN\jfn\data\tmp\sei_captchas")
SAVE_DIR.mkdir(parents=True, exist_ok=True)

reader = easyocr.Reader(['en'], gpu=False)


def build_driver() -> webdriver.Chrome:
    opts = Options()
    # reutilizar perfil já autenticado se existir
    profile = Path(r"C:\Users\socah\AppData\Local\Google\Chrome\User Data")
    if profile.exists():
        opts.add_argument(f"--user-data-dir={profile}")
        opts.add_argument("--profile-directory=Default")
    # evitar detecção
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=opts)
    driver.set_window_size(1400, 900)
    return driver


def captcha_ocr(img_path: Path) -> str:
    results = reader.readtext(str(img_path), detail=1, paragraph=False)
    candidates = []
    for item in results:
        text = item[1].strip()
        conf = float(item[2])
        if 4 <= len(text) <= 8 and any(c.isdigit() for c in text) and any(c.isalpha() for c in text):
            candidates.append((text, conf))
    candidates.sort(key=lambda x: x[1], reverse=True)
    return ''.join(ch for ch in candidates[0][0] if ch.isalnum())[:8].upper() if candidates else ""


def save_element_png(driver, element, dest: Path) -> Path:
    png = element.screenshot_as_png
    dest.write_bytes(png)
    return dest


def main() -> None:
    driver = build_driver()
    out = {}
    try:
        driver.get(SEARCH_URL)
        WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.ID, "txtProtocoloPesquisa"))
        )
        out['url'] = driver.current_url

        # Preencher número do processo
        f = driver.find_element(By.ID, "txtProtocoloPesquisa")
        f.clear()
        f.send_keys("150016/099785/2026")

        # Capturar imagem do captcha
        img_el = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "imgCaptcha"))
        )
        captcha_path = SAVE_DIR / "captcha_selenium.png"
        save_element_png(driver, img_el, captcha_path)
        out['captcha_path'] = str(captcha_path)

        # Ler captcha via EasyOCR
        captcha_text = captcha_ocr(captcha_path)
        out['captcha_text'] = captcha_text
        print("Captcha lido:", captcha_text)

        # Preencher campo do captcha
        txt_captcha = driver.find_element(By.ID, "txtInfraCaptcha")
        txt_captcha.clear()
        txt_captcha.send_keys(captcha_text)

        # Submeter
        btn = driver.find_element(By.ID, "sbmPesquisar")
        btn.click()
        time.sleep(3)

        out['result_url'] = driver.current_url
        out['result_title'] = driver.title

        # Esperar lista carregar (tabela ou links)
        page = driver.page_source
        Path(SAVE_DIR / "resultado_selenium.html").write_text(page, encoding="iso-8859-1")
        driver.save_screenshot(str(SAVE_DIR / "resultado_selenium.png"))

        # Extrair primeiro link azul do processo
        try:
            link_el = WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.XPATH, "//a[contains(@href,'protocolo_visualizar')]"))
            )
            out['process_link'] = link_el.get_attribute("href")
            out['process_text'] = link_el.text
        except Exception as e:
            out['process_link'] = None
            out['process_text'] = None
            print("Link do processo não encontrado:", e)

        # Unidade geradora e data: tentar capturar pelo xpath ou texto ao redor
        try:
            texto = driver.find_element(By.XPATH, "//div[contains(@class,'resultado') or contains(@class,'dados')]").text
        except Exception:
            texto = driver.find_element(By.TAG_NAME, "body").text
        out['body_snippet'] = texto[:4000]
        print("BODY:\n", texto[:3000])

    finally:
        Path(SAVE_DIR / "resultado_selenium.json").write_text(
            json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        driver.quit()


if __name__ == "__main__":
    main()
