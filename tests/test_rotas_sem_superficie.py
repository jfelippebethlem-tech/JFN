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
#
# 2026-07-30: 23 -> 0. A divida ja tinha sido PAGA (as oito abas novas de `cb4dc3bd` expuseram o
# resto) e o teto ficou SOLTO em 23 sem ninguem notar — porque, ao contrario da catraca irma
# `test_rotas_sem_orfa`, esta nao tinha teste de APERTO. Teto folgado nao avisa: ele deixa a divida
# voltar a crescer 23 unidades em silencio. O teste de aperto entrou junto (abaixo).
TETO_SEM_SUPERFICIE = 0

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


def _texto_do_painel() -> str:
    """O painel MAIS os arquivos que ele carrega — ver `tests/superficie.py`.

    Antes lia so `static/jfn-painel.html`. Com o JS inline saindo para `static/js/`, ler so o HTML
    faria esta catraca acusar dezenas de rotas "sem superficie" que continuam sendo chamadas.
    """
    from tests.superficie import superficie_texto

    return superficie_texto("painel")


def sem_superficie() -> list[str]:
    painel = _texto_do_painel()
    return [r for r in _rotas_api()
            if not _usada(r, painel) and not _CONTROLE.match(r)]


def test_o_numero_de_rotas_sem_superficie_nao_sobe():
    achadas = sem_superficie()
    assert len(achadas) <= TETO_SEM_SUPERFICIE, (
        f"{len(achadas)} rotas sem superficie no painel (teto {TETO_SEM_SUPERFICIE}). "
        "Capacidade construida e nunca exposta e trabalho morto. Exponha, ou suba o "
        "teto com o motivo no commit:\n  " + "\n  ".join(sorted(achadas))
    )


def test_teto_esta_apertado():
    """Faltava. Foi por falta deste teste que o teto ficou em 23 com a divida em 0.

    Catraca so vale nos DOIS sentidos: o teto tem de doer quando a divida sobe E acompanhar quando
    ela cai. Teto folgado e catraca desligada com aparencia de ligada.
    """
    achadas = sem_superficie()
    assert len(achadas) >= TETO_SEM_SUPERFICIE, (
        f"so {len(achadas)} rotas sem superficie contra teto de {TETO_SEM_SUPERFICIE} — abaixe o "
        f"teto para {len(achadas)} e trave o ganho"
    )


def test_a_superficie_enxerga_js_extraido(tmp_path, monkeypatch):
    """A extracao do JS do painel (504 KB inline -> arquivo servido) NAO pode cegar esta catraca.

    Este teste e o que autoriza a extracao a acontecer: monta um `static/` de mentira onde a chamada
    da rota esta SO no `.js`, e exige que o leitor de superficie a encontre. Sem ele, o dia da
    extracao seria o dia em que duas catracas estouram juntas e ninguem sabe se foi a extracao ou
    uma regressao real.
    """
    from tests import superficie as S

    falso = tmp_path / "static"
    (falso / "js").mkdir(parents=True)
    (falso / "jfn-painel.html").write_text("<div id=miolo></div>", encoding="utf-8")
    (falso / "js" / "painel.js").write_text("J('/api/dossie/completo')", encoding="utf-8")

    monkeypatch.setattr(S, "_STATIC", falso)
    monkeypatch.setattr(S, "PAINEL", falso / "jfn-painel.html")

    for escopo in ("painel", "front"):
        assert "/api/dossie/completo" in S.superficie_texto(escopo), (
            f"escopo {escopo!r} nao le o JS extraido — a catraca acusaria rotas orfas de mentira"
        )


def test_a_superficie_ignora_backup_e_aposentado():
    """`.bak`, `_arquivo/` e `_antes-v*` nao sao ponto de entrada de ninguem.

    Se contassem, uma rota removida do painel continuaria "coberta" pelo backup de tres versoes
    atras — a catraca ficaria verde medindo codigo que ninguem serve.
    """
    from tests.superficie import arquivos_do_front

    lidos = [str(p) for p in arquivos_do_front()]
    sujos = [p for p in lidos if ".bak" in p or "_arquivo" in p or "_antes-v" in p]
    assert not sujos, f"superficie lendo backup/aposentado: {sujos}"


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
