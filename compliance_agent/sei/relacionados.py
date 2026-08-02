# -*- coding: utf-8 -*-
"""relacionados — o processo-pai, que é onde o ato de designação costuma viver.

POR QUE ISTO EXISTE. A cobertura de responsáveis está em 8% dos processos, e a investigação da
causa mudou a hipótese de trabalho: **o ato de designação quase nunca está no processo lido**.
Só 68 dos 2.053 processos do acervo (3,3%) têm algum documento de designação. Faz sentido — o
que se captura em volume é processo de PAGAMENTO, e a portaria que nomeia fiscal e gestor vive
no processo de CONTRATAÇÃO, que o de pagamento apenas referencia.

Medido em 2026-07-28 sobre 600 caches: **18% citam ao menos um número SEI diferente do próprio**.
É por esse fio que se chega ao ato.

O GUARD CENTRAL é não casar o próprio número. O bloco de relacionados repete o número do
processo corrente em quase toda linha (é o cabeçalho de cada item), e sem o filtro a função
devolveria justamente o processo que já se está lendo.

RASTREABILIDADE: quem usa isto para montar ficha deve prefixar o documento com
`rel:<numero>::<arquivo>`, para a evidência dizer que o fiscal veio do processo-pai e não deste.
Um responsável atribuído ao processo errado é pior que responsável não identificado.
"""
from __future__ import annotations

import json
import logging
import pathlib
import re

logger = logging.getLogger(__name__)

_RE_SEI = re.compile(r"SEI-\d{6}/\d{6}/\d{4}")
_RE_PASTA = re.compile(r"^(\d{6})_(\d{6})_(\d{4})$")


def numero_para_pasta(numero: str) -> str:
    """`SEI-260007/004415/2025` → `260007_004415_2025` (o nome da pasta no acervo)."""
    return str(numero or "").replace("SEI-", "").strip().replace("/", "_")


def pasta_para_numero(pasta: str) -> str:
    """`260007_004415_2025` → `SEI-260007/004415/2025`. Formato inesperado volta como veio."""
    m = _RE_PASTA.match(str(pasta or "").strip())
    return f"SEI-{m.group(1)}/{m.group(2)}/{m.group(3)}" if m else str(pasta or "")


def _arquivo_cache(numero_sei: str, cache_dir: pathlib.Path) -> pathlib.Path | None:
    """Cache do processo. Tenta o nome direto e, falhando, casa por dígitos."""
    from compliance_agent.sei.cache_arquivo import glob_cache, localizar, nome_logico

    cache_dir = pathlib.Path(cache_dir)
    # `localizar`/`glob_cache` aceitam o blob comprimido (`.json.zst`). Este é o ÚNICO leitor de
    # cache que ignora o TTL de 24h e vai atrás de blob de qualquer idade — ou seja, é exatamente
    # ele que a compressão cegaria se a busca continuasse literal.
    direto = localizar(cache_dir / f"cdp_SEI_{numero_para_pasta(numero_sei)}.json")
    if direto is not None:
        return direto
    digitos = "".join(c for c in str(numero_sei or "") if c.isdigit())
    if not digitos:
        return None
    for f in glob_cache(cache_dir, "cdp_SEI_*.json"):
        base = nome_logico(f).removesuffix(".json")
        if "".join(c for c in base if c.isdigit()) == digitos:
            return f
    return None


def relacionados_de(numero_sei: str, cache_dir: pathlib.Path) -> list[str]:
    """Números SEI de OUTROS processos citados no cache deste. Ordem de aparição, sem repetir."""
    from compliance_agent.sei.cache_arquivo import ler_json

    f = _arquivo_cache(numero_sei, cache_dir)
    if f is None:
        return []
    d = ler_json(f)   # descomprime `.json.zst` de forma transparente; None = ausente/ilegível
    if d is None:
        logger.debug("cache ilegível para %s", numero_sei)
        return []

    proprio = (d.get("numero") or "").strip() or str(numero_sei or "").strip()
    vistos: list[str] = []
    for r in (d.get("relacionados") or []):
        # O número aparece ora em `texto`, ora no `titulo`, ora só na `url` — varrer o item
        # inteiro é mais robusto que escolher um campo e errar na próxima variação de layout.
        blob = json.dumps(r, ensure_ascii=False) if isinstance(r, dict) else str(r)
        for m in _RE_SEI.findall(blob):
            if m != proprio and m not in vistos:
                vistos.append(m)
    return vistos


def textos_do_relacionado(numero_sei: str, acervo: pathlib.Path,
                          *, max_docs: int = 40) -> dict[str, str]:
    """Textos do processo relacionado, com a chave prefixada por `rel:` para a evidência
    dizer de onde o fato veio."""
    pasta = pathlib.Path(acervo) / numero_para_pasta(numero_sei) / "texto"
    if not pasta.is_dir():
        return {}
    import html

    out: dict[str, str] = {}
    for f in sorted(pasta.glob("*.txt"))[:max_docs]:
        try:
            out[f"rel:{numero_sei}::{f.name}"] = html.unescape(f.read_text(errors="replace"))
        except OSError:
            continue
    return out
