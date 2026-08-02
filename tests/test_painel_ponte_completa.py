"""Todo handler inline do painel acha o nome que precisa — e o numero de globais so DESCE.

POR QUE ESTE TESTE EXISTE. O painel monta ~160 atributos `on*="..."` dentro de 59 renders, e o
navegador avalia esse codigo no escopo GLOBAL. Enquanto tudo era um script classico unico, isso
saia de graca. Quando o fonte vira modulos com build, cada nome usado ali precisa ser reinstalado
no `window` de proposito — e esquecer um nao derruba o boot: derruba UM botao, de UMA aba, no
instante em que alguem clicar. Nao aparece em revisao, nao aparece em smoke test.

Sao duas garantias distintas, e a segunda e a que impede a ponte de virar desculpa:

1. **Completude** — nenhum nome exigido por handler fica sem superficie. Falha = ReferenceError
   futuro, ja localizado por arquivo e linha.
2. **Teto que so desce** — a quantidade de globais e um numero neste arquivo. Migrar um dominio
   para delegacao por `data-*` baixa o teto; escrever um handler inline novo com um nome novo
   estoura. A ponte e um degrau da migracao, nao o destino, e o teto e o que torna isso visivel.
   Mesmo idioma de `test_rotas_sem_superficie.py`, que a casa adotou depois de um teto ficar solto.

A prova viva correspondente esta em `tools/painel_boot_check.py`, que afirma na pagina montada que
cada nome existe de fato no `window`. Este aqui e o estatico, exaustivo e sem navegador.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import painel_ponte_check as ponte  # noqa: E402

# Medido em 2026-08-01. No monolito eram 161 handlers e 68 nomes. Subiu para 69 na etapa 3, e a
# razao importa: `ordenar` NAO era visto pelo extrator porque nao e atributo literal no fonte —
# e ligado em tempo de execucao (`el.setAttribute('onclick', `ordenar('...',this)`)`). Quando ele
# saiu para `nucleo/lista.js`, o bundle o fechou dentro do IIFE e o unico sintoma teria sido um
# ReferenceError no clique do botao A-Z. O extrator passou a ler `setAttribute` tambem; o nome
# entrou na ponte. Nao foi a superficie que cresceu — foi a medicao que ficou honesta.
# 70 desde que o kyber passou a abrir o deck da Consciencia (`conscienciaToggle`) em vez do
# holofeed. E um nome novo no window, e ele entra com o teto subindo de propósito — o deck e
# uma superficie nova, nao um handler que escapou.
#
# 70 -> 58 na v59: o PRIMEIRO domInio saiu da ponte de verdade. Os 12 `vinc*` viraram delegacao por
# `data-vinc` no documento (ver `VINC_ACOES`/`ligarVinculos` em `abas/index.js`), e com eles saem
# tambem 13 handlers inline (168 -> 155). Vinculos foi o primeiro porque os 12 sao handlers de ZERO
# argumento numa aba so — a traducao para `data-*` nao perde informacao nenhuma, o que nao vale
# para `ir('e_resp')` ou `abrirDossie(cnpj,nome)`.
# Este numero SO DESCE. O teste falha de proposito quando ele cai sem ser atualizado aqui: teto que
# nao acompanha o progresso para de medir progresso e vira desculpa permanente.
TETO_GLOBAIS = 58

# Os 19 que o HTML nao le, ESCREVE. `onchange="_respProc=this.value;ir('e_resp')"` e o caso tipico.
# Para estes, `Object.assign(window, {...})` NAO serve: `window._respProc='X'` nao atualiza um
# `let _respProc` de modulo, e a falha e MUDA — o filtro para de responder sem um erro sequer.
# A unica forma correta e `Object.defineProperty` com get E set encaminhando para a variavel.
TETO_ESCRITOS = 19


@pytest.fixture(scope="module")
def laudo():
    return ponte.coletar()


def test_todo_nome_exigido_por_handler_inline_tem_superficie(laudo):
    disponiveis, origem = ponte.superficie()
    faltando = sorted(n for n in laudo["exigidos"] if n not in disponiveis)
    assert not faltando, (
        f"{len(faltando)} nome(s) usados em handler inline nao existem no escopo global "
        f"(superficie lida de: {origem}):\n"
        + "\n".join(f"  • {n} — usado em {', '.join(laudo['exigidos'][n])}" for n in faltando)
        + "\n\nCada um vira ReferenceError no clique, calado ate la. Se a migracao para modulos "
          "ja aconteceu, o conserto e declarar o nome em static/js/src/ponte.js.")


def test_o_numero_de_globais_do_painel_nao_cresce(laudo):
    n = len(laudo["exigidos"])
    assert n <= TETO_GLOBAIS, (
        f"o painel passou a exigir {n} globais (teto {TETO_GLOBAIS}). Um handler inline novo "
        "chamando um nome novo AUMENTA a superficie que a migracao tem de carregar. "
        "O caminho e delegacao por `data-*` no `#view`, nao mais um nome no window.")
    if n < TETO_GLOBAIS:
        pytest.fail(f"boa noticia com pendencia: a superficie caiu para {n}. "
                    f"Baixe TETO_GLOBAIS para {n} neste arquivo — teto solto para de proteger.")


def test_os_estados_escritos_de_dentro_do_html_estao_catalogados(laudo):
    """Escrita inline e a falha silenciosa da migracao. O numero dela e vigiado a parte."""
    escritos = laudo["escritos"]
    assert len(escritos) <= TETO_ESCRITOS, (
        f"{len(escritos)} estados sao ESCRITOS de dentro de atributo on* (teto {TETO_ESCRITOS}): "
        f"{escritos}\nCada um precisa de get+set na ponte. Um a mais e mais uma variavel cuja "
        "falha nao aparece no console.")
    if len(escritos) < TETO_ESCRITOS:
        pytest.fail(f"caiu para {len(escritos)}: {escritos}. Baixe TETO_ESCRITOS neste arquivo.")


def test_o_extrator_reconhece_declaracao_multipla():
    """Calibragem: `let a=1, b=null` declara DOIS nomes.

    A versao ingenua do extrator via so o primeiro e acusava `_compGrupo`, `_compCat`, `_perGrau`,
    `_nuHover` e `aba` como "sem superficie" — todos declarados em sentenca multipla no painel.js.
    Falso positivo de extrator e o modo como uma ferramenta de seguranca vira ruido e depois vira
    desligada. Este teste queima o caso.
    """
    assert ponte._declaradores("_compView='catalogo', _compTermo='', _compGrupo=null") == {
        "_compView", "_compTermo", "_compGrupo"}
    assert ponte._declaradores("esfera='inicio',aba='i_cockpit'") == {"esfera", "aba"}
    # virgula DENTRO de chamada nao abre declarador novo
    assert ponte._declaradores("x=f(1, 2), y=3") == {"x", "y"}


def test_o_extrator_nao_confunde_string_com_identificador():
    """`onclick='...;ir("e_comp")'` nao exige um global chamado `e_comp`.

    Handler escrito com aspas SIMPLES no atributo pode conter string de aspas duplas. Sem remover
    essas strings, o extrator inventava globais que nunca existiram — e um teste que inventa
    trabalho e um teste que sera ignorado.
    """
    assert "e_comp" not in ponte._nomes_do_handler("""_compGrupo=1;ir("e_comp")""")
    assert "ir" in ponte._nomes_do_handler("""_compGrupo=1;ir("e_comp")""")
    # interpolacao de template roda no escopo do modulo, nao no global
    assert "esc" not in ponte._nomes_do_handler("""abrirDossie('${esc(d.cnpj)}')""")


def test_comparacao_nao_conta_como_escrita():
    """`==`, `===`, `!=`, `>=` e `=>` nao sao atribuicao — senao todo handler viraria escrita."""
    assert ponte._escritos_no_handler("if(a===1)ir('x')") == set()
    assert ponte._escritos_no_handler("f(()=>ir('x'))") == set()
    assert ponte._escritos_no_handler("_perGrau='';ir('e_pericias')") == {"_perGrau"}
