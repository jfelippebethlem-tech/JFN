"""27/11/2026 — conferência de autenticidade do SEI-RJ: pares do rodapé e o original pelo formulário."""
from compliance_agent.sei import conferencia_autenticidade as CA

RODAPE = ("A autenticidade deste documento pode ser conferida no site, informando o código verificador 68750465 e o "
          "código CRC 05e0b8eb. Referência: Processo nº SEI-270060/001751/2023 SEI nº 68750465")


def test_par_de_outro_processo_entra_e_o_do_proprio_nao():
    assert CA.extrair_pares(RODAPE, dono="080002/000001/2025") == [CA.Par("68750465", "05E0B8EB", "270060/001751/2023")]
    assert CA.extrair_pares(RODAPE, dono="270060/001751/2023") == []                  # o próprio: já lemos
    assert CA.extrair_pares("código verificador 123456 e o código CRC ABCDEF12 sem referência") == []


class _R:
    def __init__(self, text="", content=b""):
        self.text, self.content = text, content


class _Cliente:
    def __init__(self, respostas):
        self.respostas, self.posts = respostas, []

    def get(self, url):
        if "hash_download" in url:
            return _R(content=b"<html>ORIGINAL</html>")
        return _R('<img id="imgCaptcha" src="data:image/png;base64,aGVsbG8=">')

    def post(self, url, data):
        self.posts.append(data)
        return _R(self.respostas.pop(0))


class _Ocr:
    def classification(self, b):
        return "ab12"


def test_conferir_tenta_de_novo_no_captcha_errado_e_devolve_original_e_assinaturas():
    ok = ('Lista de Assinaturas (1 registro): Assinante Cargo X Subdiretor 12 de março de 2024 '
          '<a href="controlador_externo.php?acao=documento_conferir&amp;codigo_verificador=1&amp;hash_download=z">ver</a>')
    c = _Cliente(['<input id="txtCodigoVerificador">', ok])
    o = CA.conferir(c, _Ocr(), CA.Par("68750465", "05E0B8EB", "270060/001751/2023"))
    assert o is not None and o.conteudo == b"<html>ORIGINAL</html>" and o.n_assinaturas == 1
    assert len(c.posts) == 2 and c.posts[-1]["txtCodigoVerificador"] == "68750465"


def test_par_que_o_sei_nunca_confirma_fica_pendente():
    c = _Cliente(['<input id="txtCodigoVerificador">'] * 3)
    assert CA.conferir(c, _Ocr(), CA.Par("1", "2", "3"), tentativas=3) is None
