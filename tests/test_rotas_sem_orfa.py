# -*- coding: utf-8 -*-
"""Catraca de rotas ÓRFÃS — API que ninguém alcança pelo painel.

O DIAGNÓSTICO QUE ORIGINOU ISTO (2026-07-29): de 158 rotas declaradas, **68 (43%) não apareciam em
nenhum `static/*.html`**. Não eram rotas menores: `/api/dossie/completo`, `/api/dossie/mestre`,
`/api/mandato/minuta` (que gera o .docx pronto para o gabinete assinar), `/api/ppp`,
`/api/sei/acatamento`, `/api/intel/hub_compartilhado` e os seis providers de fonte externa. Tudo
implementado, testado, e invisível para quem usa o painel — alcançável só por quem soubesse o curl.

Uma rota órfã não é um detalhe de UI. É trabalho feito que não vira decisão de fiscalização.

COMO A CATRACA FUNCIONA. Mesmo desenho do teto de `tests/test_divida_except_pass.py`: a dívida está
medida e **só pode cair**. Quem adicionar rota nova sem ponto de entrada faz o número subir e o teste
fica vermelho; quem ligar uma órfã abaixa o teto no mesmo commit.

O que NÃO conta como órfã (`_SEM_UI_POR_DESENHO`): contrato do Yoda (`/api/lista`, `/api/skills`),
websockets, autenticação, túnel do Windows, e páginas HTML que são destino de link e não de `fetch`.
Essas são exceções nominadas, uma a uma — não um padrão que engole o que não deveria.

Rodar só este arquivo:  .venv/bin/python -m pytest tests/test_rotas_sem_orfa.py -q
"""
from __future__ import annotations

import re
from pathlib import Path

_RAIZ = Path(__file__).resolve().parent.parent
_STATIC = _RAIZ / "static"

# ── Teto da dívida. SÓ PODE CAIR. ────────────────────────────────────────────────────────────────
# Ligou uma órfã? Abaixe o número no mesmo commit. Subir exige justificativa no corpo do commit.
TETO_ORFAS = 0

# Rotas que por desenho não têm (nem devem ter) ponto de entrada no painel.
_SEM_UI_POR_DESENHO = {
    # contrato máquina-a-máquina do Yoda / skilltree
    "/api/lista", "/api/route", "/api/skills", "/api/skill", "/api/skills/reload",
    "/api/skills/validate",
    # túnel reverso do Windows e websockets
    "/api/tunnel/status", "/api/tunnel/collect", "/tunnel", "/ws", "/otp",
    # autenticação e páginas (destino de link, não de fetch)
    "/login_jfn", "/logout_jfn", "/", "/painel", "/auditoria", "/cockpit", "/chat", "/hermes",
    "/graph", "/controle",
    # downloads servidos por link direto
    "/reports/{filename}", "/screenshots", "/exports",
    # documentação automática do FastAPI
    "/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect",
    # diagnóstico por id de correlação: entra pelo log, não por tela
    "/api/trace/{correlation_id}",
    # mount de arquivos estáticos, não endpoint
    "/output",
}

_RE_ROTA = re.compile(r"^\S+\s+(\S+)\s+->")


def _rotas_declaradas() -> set[str]:
    """Lê o golden do split de rotas — é a mesma fonte que `test_server_snapshot` mantém honesta."""
    golden = _RAIZ / "tests" / "golden" / "server_rotas.txt"
    assert golden.exists(), "golden de rotas ausente: rode tests/test_server_snapshot.py primeiro"
    return {m.group(1) for ln in golden.read_text().splitlines() if (m := _RE_ROTA.match(ln))}


def _texto_do_front() -> str:
    partes = []
    for f in sorted(_STATIC.glob("*.html")):
        if ".bak" in f.name or "_arquivo" in str(f):
            continue
        partes.append(f.read_text(errors="ignore"))
    for f in sorted((_STATIC / "assets").glob("*.js")):
        partes.append(f.read_text(errors="ignore"))
    return "\n".join(partes)


def _base_do_path(path: str) -> str:
    """`/api/hermes/missoes/{id}` -> `/api/hermes/missoes` — o front monta o sufixo em runtime."""
    return re.sub(r"/\{[^}]+\}.*$", "", path)


def _prefixo_montado(path: str) -> str:
    """`/api/sweeps/pausar` -> `/api/sweeps/`.

    O front compõe rota em runtime: `J('/api/sweeps/'+a)`. Sem reconhecer isso, a catraca acusava
    `pausar` e `retomar` de órfãs quando os botões existem desde sempre — e catraca que dá falso
    positivo é catraca que se aprende a ignorar (foi o que aconteceu com o auditor de contraste, que
    acertava 1 de 4). Prefixo com barra final é a assinatura da composição.
    """
    return path.rsplit("/", 1)[0] + "/" if path.count("/") > 2 else ""


def orfas() -> list[str]:
    front = _texto_do_front()
    fora = []
    for p in sorted(_rotas_declaradas()):
        if p in _SEM_UI_POR_DESENHO:
            continue
        if p in front or _base_do_path(p) in front:
            continue
        pref = _prefixo_montado(p)
        if pref and f"'{pref}'" in front.replace('"', "'"):
            continue
        fora.append(p)
    return fora


def test_divida_de_rotas_orfas_nao_cresce():
    fora = orfas()
    assert len(fora) <= TETO_ORFAS, (
        f"rotas órfãs subiram de {TETO_ORFAS} para {len(fora)} — API nova sem ponto de entrada no "
        f"painel é trabalho que não vira decisão de fiscalização.\n"
        + "\n".join(f"  {p}" for p in fora)
    )


def test_teto_esta_apertado():
    """O teto tem de acompanhar a realidade: folga grande deixa a dívida crescer sem alarme."""
    fora = orfas()
    assert len(fora) >= TETO_ORFAS, (
        f"só {len(fora)} órfãs contra teto de {TETO_ORFAS} — baixe o teto para {len(fora)} e "
        "trave o ganho"
    )


def test_produtos_entregaveis_estao_ligados():
    """Estas são as rotas que geram PEÇA (PDF, .docx para assinar). Órfãs, o trabalho fica invisível
    para quem decide — e foi justamente o que a auditoria encontrou."""
    front = _texto_do_front()
    obrigatorias = [
        "/api/dossie/completo",   # dossiê completo de fornecedor
        "/api/dossie/mestre",     # dossiê mestre de licitações
        "/api/mandato/minuta",    # requerimento ALERJ / representação TCE em .docx
        "/api/ppp",               # dossiê pericial de PPP/concessão
        "/api/sei/acatamento",    # auditoria de acatamento de parecer (art. 53)
        "/api/conjunto/orgao",    # avaliação de conjunto dos certames do órgão
    ]
    faltando = [p for p in obrigatorias if p not in front]
    assert not faltando, f"produto entregável sem ponto de entrada no painel: {faltando}"


def test_eixo_de_vinculos_esta_ligado():
    """O eixo novo (beneficiário final, parentesco, histórico societário) nasceu com API e sem UI —
    nascer órfão é o padrão que esta catraca existe para quebrar."""
    front = _texto_do_front()
    faltando = [p for p in ("/api/osint/beneficiario_final", "/api/osint/parentesco",
                            "/api/osint/vinculo_na_data", "/api/osint/serie_societaria")
                if p not in front]
    assert not faltando, f"eixo de vínculos sem ponto de entrada no painel: {faltando}"
