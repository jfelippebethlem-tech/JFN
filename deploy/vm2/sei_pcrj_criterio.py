# -*- coding: utf-8 -*-
"""Critério POSITIVO da pesquisa pública do SEI da Prefeitura (prefeitura.sei.rio) — VM-2.

Medido ao vivo em 24/11/2026 (~/vault/refatoracao/sei-pcrj-captcha-falso-privado.md): um captcha
ERRADO devolve página IDÊNTICA à de "pesquisa aceita, nenhum resultado" — `#pesquisaResultado` com
0 linhas, sem mensagem, sem alert(), campo do captcha limpo e imagem nova. A frase "código de
confirmação inválido" aparece só às vezes. Ler a AUSÊNCIA da frase como "aceito" gravou 962
processos como privados sem prova (365 deles já tinham sido vistos públicos).

Por isso só há três leituras possíveis de uma submissão:

- ``PUBLICO``        — há linha de dados em ``#pesquisaResultado`` ou link de resultado. É a única
  prova de que a pesquisa foi aceita.
- ``CAPTCHA_ERRADO`` — a frase de erro está no texto. Retenta.
- ``INDETERMINADO``  — nem linha nem frase. Não se sabe se o captcha passou: retenta com captcha
  novo até um teto pequeno e, esgotado, grava NULL. Nunca 0: a página não tem marcador de
  "aceito e vazio", logo PRIVADO não é observável nesta fonte.

Sem dependência de navegador: recebe HTML/texto e devolve a leitura (testável com fixture).
"""
from __future__ import annotations

import unicodedata
from html.parser import HTMLParser

PUBLICO = "publico"
CAPTCHA_ERRADO = "captcha_errado"
INDETERMINADO = "indeterminado"

ERRO_CAPTCHA = "confirmacao invalido"  # 'código de confirmação inválido' = captcha errado (SEI)
MAX_SEM_PROVA = 3                      # submissões sem linha nem frase antes de desistir (NULL)

# href de RESULTADO (abre o processo/documento); o formulário vazio não tem nenhum deles
HREF_RESULTADO = ("procedimento_trabalhar", "protocolo_visualizar", "acessar_documento",
                  "md_pesq_processo_exibir")
SEL_LINK_RESULTADO = ", ".join(f'a[href*="{h}"]' for h in HREF_RESULTADO)


def norm_txt(s: str) -> str:
    t = unicodedata.normalize("NFKD", (s or "").lower())
    return "".join(c for c in t if not unicodedata.combining(c))


class _Contador(HTMLParser):
    """Conta as <tr> da tabela #pesquisaResultado (sem as de tabela aninhada) e os links de resultado."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.linhas = 0
        self.links = 0
        self._prof = 0          # profundidade de <table> dentro de #pesquisaResultado (0 = fora)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "a" and any(h in (a.get("href") or "") for h in HREF_RESULTADO):
            self.links += 1
        if tag == "table":
            if self._prof:
                self._prof += 1
            elif a.get("id") == "pesquisaResultado":
                self._prof = 1
        elif tag == "tr" and self._prof == 1:
            self.linhas += 1

    def handle_endtag(self, tag):
        if tag == "table" and self._prof:
            self._prof -= 1


def contar_resultado(html: str) -> tuple[int, int]:
    """(linhas de DADOS em #pesquisaResultado — sem o cabeçalho —, links de resultado) no HTML."""
    c = _Contador()
    c.feed(html or "")
    c.close()
    return max(0, c.linhas - 1), c.links


def classificar(n_linhas: int, n_links: int, texto: str) -> str:
    """Leitura de UMA submissão. Prova positiva primeiro; a frase de erro só decide retentativa."""
    if n_linhas > 0 or n_links > 0:
        return PUBLICO
    if ERRO_CAPTCHA in norm_txt(texto):
        return CAPTCHA_ERRADO
    return INDETERMINADO


def classificar_html(html: str, texto: str) -> str:
    n_linhas, n_links = contar_resultado(html)
    return classificar(n_linhas, n_links, texto)
