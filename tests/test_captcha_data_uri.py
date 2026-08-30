"""O captcha do SEI municipal vem como data: URI — o caminho de rede não serve para ele."""
import base64

import pytest

from compliance_agent.captcha_solver import solve_captcha_data_uri, solve_captcha_url


def test_solve_captcha_url_rejeita_data_uri():
    """Regressão: era este o erro que fazia o OCR nunca rodar no prefeitura.sei.rio."""
    with pytest.raises(Exception) as e:
        solve_captcha_url("data:image/png;base64,iVBORw0KGgo=")
    assert "data" in str(e.value).lower()


def test_data_uri_sem_corpo_devolve_vazio_e_nao_explode():
    assert solve_captcha_data_uri("data:image/png;base64,") == ""


def test_data_uri_exige_prefixo_data():
    with pytest.raises(ValueError):
        solve_captcha_data_uri("https://exemplo/captcha.php")


def test_data_uri_de_imagem_real_chega_ao_ocr(tmp_path):
    """PNG mínimo válido: o que se prova aqui é que os bytes chegam ao OCR sem exceção —
    NÃO que o OCR acerte. A taxa de acerto é outra medida, feita no captcha real."""
    import cv2
    import numpy as np
    img = np.full((50, 180, 3), 255, dtype=np.uint8)
    cv2.putText(img, "A1B2C3", (10, 38), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 0), 3)
    ok, buf = cv2.imencode(".png", img)
    assert ok
    uri = "data:image/png;base64," + base64.b64encode(buf.tobytes()).decode()
    assert isinstance(solve_captcha_data_uri(uri), str)      # sem exceção; conteúdo é outra coisa


# --- ddddocr como resolvedor preferencial (medido, não presumido) ---

def test_ddddocr_vem_antes_do_tesseract():
    import inspect

    from compliance_agent import captcha_solver
    src = inspect.getsource(captcha_solver.solve_captcha_image)
    i_ddd = src.index("_ddddocr_ler")
    i_tes = src.index("pytesseract")
    assert i_ddd < i_tes, "o tesseract mediu 0 acerto neste captcha; não pode vir primeiro"


def test_sem_ddddocr_o_tesseract_continua_servindo(monkeypatch):
    """A troca não pode virar dependência dura: sem a lib, o caminho antigo segue de pé."""
    import builtins

    from compliance_agent import captcha_solver
    real = builtins.__import__

    def sem_ddddocr(nome, *a, **k):
        if nome == "ddddocr":
            raise ImportError("simulado")
        return real(nome, *a, **k)

    monkeypatch.setattr(builtins, "__import__", sem_ddddocr)
    assert captcha_solver._ddddocr_ler(b"nao-e-imagem") == ""


def test_ddddocr_le_captcha_real_do_sei_municipal():
    """Controle positivo com gabarito conferido a olho na imagem original."""
    ddddocr = pytest.importorskip("ddddocr")
    from pathlib import Path
    amostra = Path("tests/dados/captcha_sei_municipal_27cA2y.png")
    if not amostra.exists():
        pytest.skip("amostra não versionada nesta máquina")
    texto = ddddocr.DdddOcr(show_ad=False).classification(amostra.read_bytes())
    assert texto.lower() == "27ca2y"
