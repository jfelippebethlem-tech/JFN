# -*- coding: utf-8 -*-
"""Leitor único da SUPERFÍCIE do front — o que as duas catracas de rota consideram "alcançável".

POR QUE ESTE MÓDULO EXISTE. As duas catracas mediam a mesma coisa de jeitos diferentes, e **ambos
rasos**:

  • `test_rotas_sem_orfa` lia `static/*.html` — glob **NÃO recursivo** — mais `static/assets/*.js`.
  • `test_rotas_sem_superficie` lia **só** `static/jfn-painel.html`.

Hoje isso funciona porque o painel é um monolito de 504 KB com CSS e JS inline. No momento em que o
JS sair para `static/js/painel.js` (é o plano, para o painel parar de mandar 504 KB sem compressão),
**as duas desabam no mesmo commit**: as chamadas `J('/api/...')` deixam de estar no texto lido, o teto
de órfãs (0) estoura e o de sem-superfície também. E aí não há como saber se quebrou a extração ou se
entrou uma regressão real — duas variáveis mudando ao mesmo tempo.

Então a superfície passa a ser lida de forma RECURSIVA, por aqui, pelas duas. Enquanto o monolito
está intacto os números são idênticos (há teste provando); depois da extração eles continuam
significando a mesma coisa.

`escopo="painel"` = o painel e os arquivos que ele carrega (é o que a catraca de superfície mede).
`escopo="front"` = todo o front servido (é o que a catraca de órfãs mede).
"""
from __future__ import annotations

from pathlib import Path

_RAIZ = Path(__file__).resolve().parents[1]
_STATIC = _RAIZ / "static"

PAINEL = _STATIC / "jfn-painel.html"

# Extensões que podem conter uma chamada de rota.
_EXT = (".html", ".js", ".mjs")

# Fora da superfície: backup e material aposentado não são ponto de entrada de ninguém.
_IGNORAR = (".bak", "_arquivo", "_antes-v")


def _elegivel(p: Path) -> bool:
    s = str(p)
    return p.suffix in _EXT and not any(k in s for k in _IGNORAR)


def arquivos_do_painel() -> list[Path]:
    """O painel + os assets que ele passa a carregar quando o monolito for quebrado.

    `static/js/` e `static/css/` ainda não existem — e é exatamente por isso que entram aqui agora:
    quando existirem, a catraca já os lê, em vez de acusar 40 rotas órfãs de uma vez.
    """
    achados = [PAINEL] if PAINEL.exists() else []
    for sub in ("js", "css"):
        d = _STATIC / sub
        if d.is_dir():
            achados += sorted(p for p in d.rglob("*") if p.is_file() and _elegivel(p))
    return achados


def arquivos_do_front() -> list[Path]:
    """Todo o front servido, RECURSIVO — inclui `static/assets/*.js` e qualquer subpasta futura."""
    return sorted(p for p in _STATIC.rglob("*") if p.is_file() and _elegivel(p))


def _juntar(paths: list[Path]) -> str:
    return "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in paths)


def superficie_texto(escopo: str = "front") -> str:
    if escopo == "painel":
        return _juntar(arquivos_do_painel())
    if escopo == "front":
        return _juntar(arquivos_do_front())
    raise ValueError(f"escopo desconhecido: {escopo!r} (use 'painel' ou 'front')")
