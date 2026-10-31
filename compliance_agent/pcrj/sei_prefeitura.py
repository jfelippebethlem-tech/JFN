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


# ── Pesquisa pública: estrutura medida em 2026-09-02 ────────────────────────────────────────
# A pesquisa é AJAX e devolve JSON {"itens": N, "html": "<tr>…"}. Cada resultado traz o
# protocolo em `data-prot` e um link `md_pesq_processo_exibir.php?<token>` — que é o acesso à
# ÍNTEGRA (árvore de documentos) do processo. O token é opaco e por-sessão: não se constrói,
# só se colhe do resultado.
#
# Campos do formulário que carregam a busca (medidos, não presumidos):
#   · txtProtocoloPesquisa  — protocolo; o servidor tira pontuação E espaços antes de casar
#   · txtDescricaoPesquisa  — texto livre. É ESTE o campo de busca livre; `as_q` existe no
#     formulário mas é inerte (devolve resposta sem a chave "itens").
_RE_PROT_ATTR = re.compile(r'data-prot="([^"]+)"')
_RE_LINK_EXIBIR = re.compile(r'href="(md_pesq_processo_exibir\.php\?[^"]+)"')
_RE_UNIDADE = re.compile(r"<b>Unidade:</b>\s*<a[^>]*>([^<]+)</a>")
_RE_DATA = re.compile(r"<b>Data:</b>\s*([0-9/]+)")
_RE_TAG = re.compile(r"<[^>]+>")


def parse_resultado_html(html: str) -> list[dict]:
    """Extrai os resultados do campo `html` da resposta JSON da pesquisa pública.

    Devolve um dict por processo com `protocolo`, `titulo`, `unidade`, `data` e `url_integra`
    (absoluta). Puro e testável offline — a fixture é uma resposta real.
    """
    if not html:
        return []
    itens: list[dict] = []
    # cada registro começa num <tr class="pesquisaTituloRegistro">; o bloco de metadados
    # (Unidade/Data) vem no <tr> seguinte, então fatiamos por registro e olhamos o resto.
    partes = html.split('<tr class="pesquisaTituloRegistro">')
    for parte in partes[1:]:
        m_prot = _RE_PROT_ATTR.search(parte)
        if not m_prot:
            continue
        m_link = _RE_LINK_EXIBIR.search(parte)
        cabeca = parte.split("</tr>", 1)[0]
        titulo = _RE_TAG.sub("", cabeca).replace("&nbsp;", " ")
        titulo = re.sub(r"\s+", " ", titulo).strip()
        m_uni, m_data = _RE_UNIDADE.search(parte), _RE_DATA.search(parte)
        itens.append({
            "protocolo": m_prot.group(1),
            "titulo": titulo,
            "unidade": m_uni.group(1).strip() if m_uni else None,
            "data": m_data.group(1) if m_data else None,
            # token opaco e por-sessão: só vale colhido deste resultado
            "url_integra": f"{BASE}/sei/modulos/pesquisa/{m_link.group(1)}" if m_link else None,
        })
    return itens


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
