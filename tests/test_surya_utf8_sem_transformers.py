"""26/11/2026: com a GPU de volta, o Surya no worker devolvia blocos vazios/com erro em todo texto acentuado — o
`surya_utf8` refazia o texto (U+FFFD) com `transformers.AutoTokenizer`, ausente no worker: a importação falhava DENTRO
da chamada e virava «bloco vazio», calado. Agora usa a biblioteca `tokenizers` (leve) quando o transformers não há."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy" / "itcampo" / "ocr_gpu"))
import surya_utf8 as U  # noqa: E402


class _Falso:
    """tokenizers.Tokenizer mínimo: 'Ã§' é o par de bytes de 'ç' no mapa de bytes do BPE; 9 é um token especial."""
    def get_added_tokens_decoder(self):
        return {9: "<x>"}

    def id_to_token(self, i):
        return {1: "a", 2: "Ã§", 3: "Ã£o", 9: "<x>"}[i]


def test_texto_dos_ids_pelo_tokenizers(monkeypatch):
    monkeypatch.setattr(U, "_TK", None)
    monkeypatch.setattr(U, "_carregar_tokenizador", lambda: ("tokenizers", _Falso()))
    assert U.texto_dos_ids([1, 2, 3, 9]) == "ação<x>"
