# -*- coding: utf-8 -*-
"""Capacidade construida e nunca exposta e trabalho morto.

O painel tem 137 rotas `/api`. Uma varredura crua acusou 68 sem mencao — mas o
numero era TETO, nao laudo: a checagem por substring nao enxerga rota montada por
concatenacao (o painel chama `'/api/sweeps/'+acao`), e nem toda rota e para a tela
(hermes, tunnel, skills e os sweeps do SIAFE sao plano de controle).

Triado em 2026-07-25: 137 rotas · 49 sem mencao literal · 26 de plano de controle ·
19 falso positivo por concatenacao · **23 capacidades reais sem superficie**.

Este teste nao exige que as 23 sejam expostas — exige que o numero NAO SUBA. Rota
nova sem tela e uma decisao legitima; o que nao pode e a decisao ser silenciosa.
"""

import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
PAINEL = RAIZ / "static" / "jfn-painel.html"

# Medido em 2026-07-25. Ao expor uma rota, ABAIXE este numero de proposito — e a
# unica forma de o progresso aparecer. Ao criar rota nova sem tela, suba com o
# motivo no commit.
TETO_SEM_SUPERFICIE = 23

# Plano de controle: existe para o Hermes/Yoda e para operacao, nao para a tela.
_CONTROLE = re.compile(
    r"^/api/(hermes|tunnel|skills?|siafe/(sweep|atualizar|status)|pipelines|route"
    r"|memoria|nucleo|radar/(ciclo|status|vigiar)|lista|log)"
)


def _rotas_api() -> list[str]:
    rotas = set()
    for f in (RAIZ / "rotas").glob("*.py"):
        rotas |= set(re.findall(r"@router\.(?:get|post)\(\s*[\"']([^\"']+)",
                                f.read_text(encoding="utf-8")))
    rotas |= set(re.findall(r"@app\.(?:get|post)\(\s*[\"']([^\"']+)",
                            (RAIZ / "server.py").read_text(encoding="utf-8")))
    return sorted(r for r in rotas if r.startswith("/api/"))


def _usada(rota: str, painel: str) -> bool:
    base = re.sub(r"\{[^}]+\}", "", rota).rstrip("/")
    if base and base in painel:
        return True
    # rota montada por concatenacao: `'/api/sweeps/' + acao`
    pai = base.rsplit("/", 1)[0] + "/"
    return len(pai) > 6 and pai in painel


def sem_superficie() -> list[str]:
    painel = PAINEL.read_text(encoding="utf-8")
    return [r for r in _rotas_api()
            if not _usada(r, painel) and not _CONTROLE.match(r)]


def test_o_numero_de_rotas_sem_superficie_nao_sobe():
    achadas = sem_superficie()
    assert len(achadas) <= TETO_SEM_SUPERFICIE, (
        f"{len(achadas)} rotas sem superficie no painel (teto {TETO_SEM_SUPERFICIE}). "
        "Capacidade construida e nunca exposta e trabalho morto. Exponha, ou suba o "
        "teto com o motivo no commit:\n  " + "\n  ".join(sorted(achadas))
    )


def test_a_triagem_separa_plano_de_controle():
    """Sem separar, o numero engorda com rota que NUNCA foi para a tela."""
    painel = PAINEL.read_text(encoding="utf-8")
    cru = [r for r in _rotas_api() if not _usada(r, painel)]
    triado = sem_superficie()
    assert len(triado) < len(cru), (
        "a triagem deixou de separar o plano de controle — o numero volta a ser teto"
    )


def test_capacidades_de_alto_valor_estao_no_radar():
    """Estas nao sao rota qualquer: sao produto pronto que ninguem alcanca pela tela.

    Se uma delas SAIR da lista, ou foi exposta (otimo, tire daqui) ou a rota morreu
    (verifique). O teste existe para a mudanca ser notada.
    """
    achadas = set(sem_superficie())
    alto_valor = {"/api/dossie/completo", "/api/dossie/mestre", "/api/sancoes/detalhar"}
    ainda_ocultas = alto_valor & achadas
    # 2026-07-29: as tres foram EXPOSTAS (abas "Peças" e "Detectores"). O teste era um registrador
    # que exigia `ainda_ocultas` nao-vazio para "ter o que verificar" — e por isso passou a falhar
    # justamente quando a divida zerou, o que e o oposto do que ele quer proteger. Invertido: agora
    # afirma o GANHO, e volta a falhar se uma delas for escondida de novo.
    assert not ainda_ocultas, (
        "capacidade de alto valor voltou a ficar sem superficie no painel: "
        + ", ".join(sorted(ainda_ocultas))
    )
