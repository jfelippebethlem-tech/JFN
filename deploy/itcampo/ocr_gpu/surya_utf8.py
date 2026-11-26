"""Conserto dos acentos do Surya 2.5 servido pelo vLLM 0.34 (it-campo) — 18/11/2026.

CAUSA MEDIDA: o modelo gera 'ç' como UM byte no padrão Latin-1 (token 2167 = byte 0xE7) em vez dos dois bytes do
UTF-8 ('Ã§' = tokens 2131+2103). O vLLM decodifica a sequência como UTF-8 e o byte solto vira U+FFFD
("Liquida��o"; 75 em uma página). A informação não se perde: está nos IDs dos tokens. Aqui pedimos os IDs ao vLLM
(`return_token_ids`) e refazemos o texto: UTF-8, e só o byte inválido cai para Latin-1.

Uso: `import surya_utf8; surya_utf8.instalar()` antes de criar o RecognitionPredictor.
"""
from __future__ import annotations

import codecs

_MODELO = "datalab-to/surya-ocr-2.5"


def _recuo_latin1(err: UnicodeDecodeError):
    return err.object[err.start:err.end].decode("latin-1"), err.end


codecs.register_error("jfn_latin1", _recuo_latin1)


def utf8_com_recuo(b: bytes) -> str:
    """UTF-8 válido passa igual; byte que não forma UTF-8 vira o caractere Latin-1 correspondente."""
    return b.decode("utf-8", errors="jfn_latin1")


def _bytes_to_unicode() -> dict[int, str]:          # o mesmo mapa byte↔caractere do BPE de bytes (GPT-2/Qwen)
    bs = list(range(ord("!"), ord("~") + 1)) + list(range(ord("¡"), ord("¬") + 1)) + list(range(ord("®"), ord("ÿ") + 1))
    cs = bs[:]
    n = 0
    for b in range(256):
        if b not in bs:
            bs.append(b)
            cs.append(256 + n)
            n += 1
    return dict(zip(bs, map(chr, cs)))


_DEC = {c: b for b, c in _bytes_to_unicode().items()}
_TK = None


def _carregar_tokenizador():
    """(tipo, tokenizador): o `transformers` quando existe (venv da GPU); senão a biblioteca `tokenizers`, leve, sem
    torch (venv do worker do motor). 26/11/2026: no worker o transformers não existe e a importação falhava DENTRO da
    chamada do Surya — todo bloco acentuado voltava vazio/com erro, calado."""
    try:
        from transformers import AutoTokenizer
        return "transformers", AutoTokenizer.from_pretrained(_MODELO)
    except ImportError:
        from tokenizers import Tokenizer
        return "tokenizers", Tokenizer.from_pretrained(_MODELO)


def texto_dos_ids(ids: list[int]) -> str:
    global _TK
    if _TK is None:
        _TK = _carregar_tokenizador()
    tipo, tk = _TK
    if tipo == "transformers":
        especiais = {int(k) for k in getattr(tk, "added_tokens_decoder", {})}
        tokens = tk.convert_ids_to_tokens(ids)
    else:
        especiais = {int(k) for k in tk.get_added_tokens_decoder()}
        tokens = [tk.id_to_token(i) for i in ids]
    out, buf = [], bytearray()
    for i, t in zip(ids, tokens):
        if i in especiais:
            out.append(utf8_com_recuo(bytes(buf)))
            buf.clear()
            out.append(t)
        else:
            for ch in t:                       # caractere fora do mapa de bytes = já é texto: entra em UTF-8 como está
                b = _DEC.get(ch)
                buf.extend([b] if b is not None else ch.encode("utf-8"))
    out.append(utf8_com_recuo(bytes(buf)))
    return "".join(out)


def instalar() -> None:
    """Envolve o `chat.completions.create` do cliente OpenAI: pede os IDs e refaz o texto quando vier U+FFFD."""
    from openai.resources.chat import completions as cc
    if getattr(cc.Completions.create, "_jfn_utf8", False):
        return
    original = cc.Completions.create

    def create(self, *a, **kw):
        eb = dict(kw.pop("extra_body", None) or {})
        eb["return_token_ids"] = True
        resp = original(self, *a, extra_body=eb, **kw)
        for ch in getattr(resp, "choices", []) or []:
            txt = getattr(ch.message, "content", None) or ""
            ids = getattr(ch, "token_ids", None) or (getattr(ch, "model_extra", None) or {}).get("token_ids")
            if "�" in txt and ids:
                ch.message.content = texto_dos_ids(list(ids))
        return resp

    create._jfn_utf8 = True
    cc.Completions.create = create
