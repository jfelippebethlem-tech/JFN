"""A sequencia de boot do painel e um CONTRATO — 26 efeitos, nesta ordem.

POR QUE ESTE TESTE EXISTE. O boot do painel e uma sequencia de efeitos de topo: registros de
listener, tres IIFEs nomeadas, um `fetch` de sonda, `sabreStart()`, `portalStart()` e dois
`setTimeout` de medicao. Enquanto o painel foi um script classico unico, essa ordem era a ordem do
arquivo e ninguem precisava pensar nela.

Com modulos ES ela deixa de ser automatica: efeito de topo de um modulo roda na ordem do IMPORT,
nao na ordem em que o codigo aparece no entrypoint. Quebrar um dominio de abas para fora pode,
sozinho, adiantar o `portalStart()` — e o sintoma nao e um erro no console, e o portal aparecendo
depois do cockpit, ou a corrida com View Transitions que ja matou este boot uma vez.

DUAS GARANTIAS, e a segunda e a que sustenta a primeira:

1. **A sequencia nao muda sem alguem decidir.** A lista abaixo e a ordem real medida. Reordenar,
   remover ou acrescentar um efeito quebra o teste com o diff na cara.
2. **Nenhum modulo tem efeito de topo.** Enquanto isso valer, a ordem de import e IRRELEVANTE e o
   entrypoint continua sendo o unico lugar onde o boot acontece. E o invariante que torna a
   garantia 1 suficiente.

Nota de desenho: os 26 efeitos NAO foram movidos para um bloco unico no fim do entrypoint. Mover
26 efeitos de lugar e, literalmente, a operacao que reordena um boot em silencio — pagar-se-ia o
risco para evitar o risco. Eles ficam onde estao e passam a ser inventariados.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import painel_efeitos_boot as boot  # noqa: E402

# Medido em 2026-08-01, depois da etapa 3 da quebra em modulos.
SEQUENCIA = [
    "testemunha:readyState",          # a primeira instrucao; prova que o script bloqueia o parser
    "listener:hashchange",            # roteamento por URL
    # v58 · etapa 7: a sonda da arte subiu duas posicoes. Ela ficava no meio do bloco de renders
    # que virou `abas/index.js`; quando o bloco saiu, ela veio junto para o topo da sequencia.
    # Nao muda nada de comportamento — e um `fetch` de HEAD que so acende `body.art-no` se o PNG
    # existir — mas muda a ORDEM, e ordem e o que este contrato vigia.
    "fetch:/static/assets/no-energia.png",   # sonda: a arte existe? entao acende body.art-no
    "listener:pagehide",              # limpa efemeros
    "listener:pointermove",           # paralaxe do cockpit
    "iife:boot-assincrono",           # monta esferas/abas e liga os canvas de fundo
    # A camada de INTERACAO saiu para `ui/index.js` na etapa 6. Os efeitos que ela tinha no
    # topo (DOMContentLoaded da holografia, keydown de Enter/Espaco, os quatro ouvintes do
    # spotlight e a IIFE do dialogo) viraram funcao e passaram a ser CHAMADOS daqui, na
    # mesma ordem relativa. Efeito de topo em modulo roda na ordem do import, e a ordem do
    # import nao e a ordem que este painel precisa.
    "chamada:uiLigarA11y()",
    "chamada:uiLigarSpotlight()",
    "chamada:uiLigarDialogo()",
    "chamada:sobrioAoMudar()",        # o que reavaliar quando o modo sobrio vira: os tres
                                      # videos da cena. Gancho, nao import — senao a folha
                                      # das bandeiras e a cena se importariam em circulo
    "chamada:conscienciaLigar()",     # monta o deck e liga a tecla C; ANTES do barramento,
                                      # porque e ele que recebe os eventos que o deck mostra
    "chamada:sabreStart()",           # barramento SSE
    "chamada:portalStart()",          # portal de ignicao
    "setTimeout:_medirFps",           # 2,6 s: fim da intro + folga; decide o modo sobrio
    "listener:visibilitychange",      # html.rest quando a aba sai de foco
    "listener:resize",                # mascara da barra de esferas
    "listener:scroll",                # idem
    "setTimeout:_sphMask",            # idem, 600 ms
    "iife:_ligarTato",                # onda de toque, delegada no documento
    "iife:_ligarObservadorDeValor",   # o numero que muda acende
    "ponte:window.TABS",              # ── daqui para baixo e a PONTE, sempre por ultimo:
    "ponte:Object.assign",            #    ela precisa de tudo ja declarado
    "iife:arrow",
    "ponte:defineProperty",
]


def test_a_sequencia_de_boot_nao_mudou():
    real = [e["assinatura"] for e in boot.efeitos()]
    assert real == SEQUENCIA, (
        "a sequencia de boot mudou.\n"
        f"  esperada ({len(SEQUENCIA)}): {SEQUENCIA}\n"
        f"  real     ({len(real)}): {real}\n\n"
        "Se a mudanca foi intencional, atualize SEQUENCIA neste arquivo — e confira antes que a "
        "nova ordem e a que voce quer, porque reordenar o boot ja matou esta tela.")


def test_nenhum_efeito_ficou_sem_assinatura():
    """`DESCONHECIDO:` significa que o extrator nao entendeu um efeito — e ele precisa entender."""
    ruins = [e for e in boot.efeitos() if e["assinatura"].startswith("DESCONHECIDO")]
    assert not ruins, (
        "efeito(s) de topo que o extrator nao classificou:\n"
        + "\n".join(f"  linha {e['linha']}: {e['fonte']}" for e in ruins)
        + "\nAcrescente a assinatura em tools/painel_efeitos_boot._ASSINATURAS. Efeito nao "
          "classificado e efeito nao vigiado.")


def test_nenhum_modulo_tem_efeito_de_topo():
    sujos = boot.modulos_com_efeito()
    assert not sujos, (
        "modulo(s) com efeito de topo — isto reordena o boot em silencio, porque efeito de modulo "
        "roda na ordem do IMPORT e nao na do entrypoint:\n"
        + "\n".join(f"  {arq}:{e['linha']}  {e['fonte']}"
                    for arq, lst in sujos.items() for e in lst)
        + "\nMova a chamada para a sequencia de boot em src/entrada.js; deixe no modulo apenas a "
          "funcao que ela chama.")


def test_a_ponte_e_a_ultima_coisa_do_boot():
    """Ela instala no window nomes declarados no arquivo inteiro — nao pode rodar antes deles."""
    real = [e["assinatura"] for e in boot.efeitos()]
    primeira_ponte = next(i for i, a in enumerate(real) if a.startswith("ponte:"))
    depois = [a for a in real[primeira_ponte:] if not a.startswith(("ponte:", "iife:arrow"))]
    assert not depois, (
        f"ha efeito de boot DEPOIS da ponte: {depois}. A ponte fecha a sequencia — qualquer coisa "
        "depois dela roda com o window ja mexido, e a ordem deixa de ser obvia para quem le.")
