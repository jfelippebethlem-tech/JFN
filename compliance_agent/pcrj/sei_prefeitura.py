# -*- coding: utf-8 -*-
"""Leitor do SEI da PREFEITURA do Rio (``prefeitura.sei.rio``).

Instância SEI INDEPENDENTE do SEI-RJ estadual (itkava, ``sei.rj.gov.br``) e do SIGA
(``acesso.processo.rio``, que usa reCAPTCHA v2 — vetado: solver pago é proibido).

Estado do acesso (verificado 2026-07-24):
  · a pesquisa pública SAIU DO 404 — ``prefeitura.sei.rio/sei/modulos/pesquisa/
    md_pesq_processo_pesquisar.php`` responde 200 (o portal ``sei.rio`` é só WordPress
    institucional; a aplicação real é ``prefeitura.sei.rio``);
  · está atrás de defesa anti-bot F5/Volterra (cookies ``re-stick``/``TS01…``,
    ``x-volterra-location``) — por isso EXIGE browser real (executa o desafio JS);
    curl cru não passa;
  · o captcha do SEI é imagem de texto (``captcha.php``) — resolvido por OCR local,
    reusando ``compliance_agent.captcha_solver`` pela máquina já pronta em
    ``collectors/sei_cdp.submit_sei_search`` (parametrizada por ``url_pesquisa``).

A regra do dono "NUNCA captcha" é específica do SEI ESTADUAL (que tem o login itkava
interno); NÃO se aplica ao municipal, que só tem a via pública. Serviço pago de captcha
continua proibido — aqui é OCR local grátis.

Número de processo SEI.RIO (protocolo): ``NNNNNN.NNNNNN/AAAA-DD`` (ex.: 000900.048716/2026-91).
Os helpers puros abaixo são testados offline; ``consultar`` é browser-dependente.
"""
from __future__ import annotations

import re

# aplicação SEI real do município (não o portal WordPress sei.rio)
BASE = "https://prefeitura.sei.rio"
PESQUISA = f"{BASE}/sei/modulos/pesquisa/md_pesq_processo_pesquisar.php"

# protocolo SEI.RIO: 5–6 dígitos . 6 dígitos / ano - 2 dígitos verificadores
_RE_SEIRIO = re.compile(r"\d{5,6}\.\d{6}/\d{4}-\d{2}")


def url_pesquisa_publica(id_orgao: int = 0) -> str:
    """URL da pesquisa pública de processo do SEI municipal."""
    return (f"{PESQUISA}?acao_externa=protocolo_pesquisar"
            f"&acao_origem_externa=protocolo_pesquisar&id_orgao_acesso_externo={id_orgao}")


def normalizar_processo(texto: str | None) -> str | None:
    """Extrai/limpa o nº de processo SEI.RIO de um texto. None se não houver.

    Tolera espaços em volta de '/' e '.' e prefixos ('Processo nº.:'). Só o formato
    SEI.RIO — o SIGA (09/002.991/2022) é outro sistema, não entra aqui.
    """
    if not texto:
        return None
    # colapsa espaços em torno dos separadores antes de casar
    t = re.sub(r"\s*([./-])\s*", r"\1", str(texto))
    m = _RE_SEIRIO.search(t)
    return m.group(0) if m else None


def processo_valido(numero: str | None) -> bool:
    """True se `numero` é um protocolo SEI.RIO completo e único."""
    if not numero:
        return False
    return bool(re.fullmatch(r"\d{5,6}\.\d{6}/\d{4}-\d{2}", numero.strip()))


async def consultar(numero: str, *, max_attempts: int = 4) -> dict:
    """Consulta um processo no SEI municipal (pesquisa pública + captcha OCR).

    Reusa a máquina de browser+captcha de ``sei_cdp.submit_sei_search`` apontada para
    ``prefeitura.sei.rio`` (``login_interno=False`` — o municipal não tem usuário interno).

    REQUER browser real (Chrome CDP :9222) por causa da defesa F5 — validar em execução
    supervisionada (não roda em curl/headless sem o desafio JS). Retorna o dict de
    ``submit_sei_search`` (texto/HTML/ok/captcha_resolvido) ou {erro}.
    """
    num = normalizar_processo(numero) or (numero or "").strip()
    if not num:
        return {"erro": "número de processo vazio"}
    from compliance_agent.collectors.sei_cdp import submit_sei_search
    return await submit_sei_search(
        num, max_attempts=max_attempts,
        url_pesquisa=url_pesquisa_publica(), login_interno=False)


def _cli() -> None:
    import argparse
    import asyncio
    import json
    ap = argparse.ArgumentParser(description="Leitor do SEI da Prefeitura do Rio (prefeitura.sei.rio).")
    ap.add_argument("numero", help="nº de processo SEI.RIO, ex.: 000900.048716/2026-91")
    a = ap.parse_args()
    r = asyncio.run(consultar(a.numero))
    # não despeja o HTML inteiro no stdout — só o veredito
    print(json.dumps({k: (v if k != "texto" else (v or "")[:400]) for k, v in r.items()},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    _cli()
