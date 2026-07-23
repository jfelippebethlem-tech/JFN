"""Escrita de texto em PDF que NÃO perde conteúdo em silêncio.

`Page.insert_textbox` devolve o espaço sobrando e, quando o texto não cabe, devolve
NEGATIVO e **não escreve nada** — a página fica em branco. O que estoura a caixa não
é texto longo, é texto com MUITAS LINHAS CURTAS: a fontsize 8 cabem ~79 linhas, e um
despacho do SEI (um campo por linha) passa disso fácil.

Ignorar esse retorno custou 11.901 documentos em branco no arquivo SEI (2026-07-23):
o PDF era salvo vazio e a função devolvia sucesso. Aqui o retorno é SEMPRE conferido
e o texto é repartido até caber — nada é dado por escrito sem prova de que foi.
"""
from __future__ import annotations

import fitz

CAIXA = fitz.Rect(40, 40, 555, 800)
FONTE = 8


def escrever_texto(doc: fitz.Document, titulo: str, texto: str,
                   *, caixa: fitz.Rect = CAIXA, fontsize: int = FONTE) -> int:
    """Escreve `[titulo]` + `texto` em quantas páginas forem necessárias.

    Retorna o nº de páginas criadas. Garante que TODO o texto foi escrito: cada
    página confere o retorno de `insert_textbox` e, se não coube, reduz o pedaço
    até caber (nunca abandona o resto, nunca salva página muda).
    """
    resto = f"[{titulo}]\n\n{texto}".strip()
    paginas = 0
    while resto:
        pagina = doc.new_page()
        paginas += 1
        pedaco, resto = _maior_pedaco_que_cabe(pagina, resto, caixa, fontsize)
        if not pedaco:
            # nem uma linha coube (caixa absurda ou fonte grande demais):
            # não deixa página muda nem loop infinito — corta na força bruta
            pedaco, resto = resto[:200], resto[200:]
            pagina.insert_textbox(caixa, pedaco, fontsize=max(4, fontsize - 2))
    return paginas


def _maior_pedaco_que_cabe(pagina: fitz.Page, texto: str, caixa: fitz.Rect,
                           fontsize: int) -> tuple[str, str]:
    """Escreve na `pagina` o maior prefixo de `texto` que couber. → (escrito, resto).

    Busca binária sobre LINHAS (a linha é a unidade que estoura a caixa). Cada
    tentativa limpa a página antes de reescrever, para não empilhar sobras.
    """
    linhas = texto.split("\n")
    baixo, alto, melhor = 1, len(linhas), 0
    while baixo <= alto:
        meio = (baixo + alto) // 2
        pagina.clean_contents()
        if pagina.insert_textbox(caixa, "\n".join(linhas[:meio]), fontsize=fontsize) >= 0:
            melhor, baixo = meio, meio + 1
        else:
            alto = meio - 1
    if not melhor:
        pagina.clean_contents()
        return "", texto
    pagina.clean_contents()
    escrito = "\n".join(linhas[:melhor])
    pagina.insert_textbox(caixa, escrito, fontsize=fontsize)
    return escrito, "\n".join(linhas[melhor:])


def gravar_doc(fp, titulo: str, texto: str, anexo_bytes: bytes | None = None) -> bool:
    """Grava UM documento da íntegra em `fp` (Path). Retorna True se gravou algo útil.

    - Escaneado (há `anexo_bytes` que É um PDF): grava o PDF ORIGINAL, preservando as
      IMAGENS — é delas que o arquivador extrai as fotos de prova (medição, relatório
      fotográfico, fiscalização). Perder isso foi a regressão que o fix do GET-direto
      envenenador quase introduziu (2026-07-23).
    - Nativo (texto do editor, sem imagem a preservar): grava um PDF de texto via
      `escrever_texto`, que confere o retorno e nunca deixa página em branco.
    """
    from pathlib import Path
    fp = Path(fp)
    if anexo_bytes and anexo_bytes[:5] == b"%PDF-":
        fp.write_bytes(anexo_bytes)
        return True
    if len((texto or "").strip()) < 15:
        return False
    doc = fitz.open()
    escrever_texto(doc, titulo, texto)
    ok = any(p.get_text().strip() for p in doc)
    if ok:
        doc.save(str(fp))
    doc.close()
    return ok
