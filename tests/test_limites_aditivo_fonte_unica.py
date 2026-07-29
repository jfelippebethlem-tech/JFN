# -*- coding: utf-8 -*-
"""Trava arquitetural: o teto do art. 125 tem UMA fonte, e a natureza do aditivo UM classificador.

`limites_dispensa.py` resolveu esse problema para o teto de DISPENSA depois de cinco cópias
divergentes. O teto de ADITIVO seguia sem fonte única, com **cinco** implementações:

    detectores/x1_crescimento_aditivo    _TETO_PADRAO / _TETO_REFORMA
    cruzamentos_intel.aditivos_estouro   25% no SQL, sem tratar reforma
    pcrj/pericia_gastos.d11              D10_LIMITE_ADITIVO = 1.25, sem tratar reforma
    contratos/thoughts                   ADITIVO_LIMITE / ADITIVO_REFORMA
    nucleo/parametros                    aditivo_limite_frac = 0.25

Pior que o número duplicado é o CLASSIFICADOR duplicado. Decidir o que é "acréscimo do art. 125"
tem três implementações que discordam entre si:

  · `thoughts._e_acrescimo_de_valor` — objeto manda, com "sem acréscimo de valor" e "prorroga"
    negando (aprendido no caso AVANTY, +R$ 51 mi que era renovação de 12 meses);
  · `cruzamentos_intel.aditivos_estouro` — usa `qualif_acrescimo='1'`, que a própria casa
    declarou inútil em `thoughts` ("vem '1' para quase tudo");
  · `pericia_gastos.d11` — não classifica nada: compara `valor_global > valor_inicial * 1.25`,
    de modo que reajuste, reequilíbrio e prorrogação entram no teto como se fossem acréscimo.

E nenhuma delas conhecia o reequilíbrio do art. 124, II, "d" — a causa dos 45% de falso positivo
medidos na estreia da varredura de execução (2026-07-29).
"""
from __future__ import annotations

import ast
import pathlib
import re

import pytest

from compliance_agent.limites_aditivo import (
    ATO_NORMATIVO,
    TETOS,
    acrescimo_computavel,
    ato_normativo,
    classificar_natureza,
    teto_acrescimo,
)

_PERMITIDO = {
    "compliance_agent/limites_aditivo.py",
    "tests/test_limites_aditivo_fonte_unica.py",
}


# ───────────────────────────── a tabela canônica ──────────────────────────────────────────────

@pytest.mark.parametrize("tipo_objeto,esperado", [
    (None, 0.25),
    ("", 0.25),
    ("servico_continuado", 0.25),
    ("obra", 0.25),
    ("reforma", 0.50),
    ("REFORMA DE EDIFÍCIO", 0.50),
    ("reforma de equipamento hospitalar", 0.50),
])
def test_teto_por_tipo_de_objeto(tipo_objeto, esperado):
    assert teto_acrescimo(tipo_objeto) == pytest.approx(esperado)


def test_regime_antigo_tem_o_mesmo_teto_mas_outro_ato():
    """Lei 8.666 art. 65 §1º traz os mesmos 25%/50% — o que muda é o ato a citar na peça."""
    assert teto_acrescimo("obra", regime="8666") == pytest.approx(0.25)
    assert teto_acrescimo("reforma", regime="8666") == pytest.approx(0.50)
    assert "8.666" in ato_normativo("8666")
    assert "14.133" in ato_normativo("14133")


def test_todo_regime_cita_o_ato_normativo():
    """Peça de controle externo sem o dispositivo é inverificável."""
    for regime in TETOS:
        assert regime in ATO_NORMATIVO and ATO_NORMATIVO[regime]


def test_regime_desconhecido_cai_no_vigente_e_nao_quebra():
    assert teto_acrescimo("obra", regime="inexistente") == pytest.approx(0.25)


# ───────────────────────────── o classificador ────────────────────────────────────────────────

@pytest.mark.parametrize("objeto,esperado", [
    # acréscimo de verdade — o único que consome o teto
    ("acréscimo de 20% no quantitativo de postos", "valor"),
    ("O presente Termo tem por objeto o ACRÉSCIMO DE QUANTIDADES DO CONTRATO", "valor"),
    ("1ª alteração (quantitativa) ao contrato nº 003/1031/2024", "valor"),
    ("Formalizar o aporte ao Contrato nº 2419892", "valor"),
    ("supressão de itens do contrato", "valor"),
    # prazo — art. 107, não 125
    ("prorrogação do prazo de vigência por 12 meses", "prazo"),
    ("dilatação de prazo contratual", "prazo"),
    # recomposição — art. 124, não consome teto
    ("reajuste contratual pelo IPCA", "reajuste"),
    ("repactuação dos preços por convenção coletiva", "reajuste"),
    ("reequilíbrio econômico-financeiro do contrato", "reajuste"),
    ('revisão, a contar de 01/06/2025, dos valores vigentes do benefício', "reajuste"),
    # nem valor nem prazo
    ("sub-rogação total com vistas à transferência da CONTRATANTE", "outro"),
    ("Adequação, face erro material, do Quadro de Alterações de Itens", "outro"),
    # ilegível
    ("texto que não diz nada", ""),
])
def test_classificacao_por_objeto(objeto, esperado):
    assert classificar_natureza(objeto)[0] == esperado


def test_prorrogacao_que_nega_acrescimo_nao_e_valor():
    """`thoughts` já tratava "sem acréscimo de valor"; a fonte única preserva esse acerto."""
    assert classificar_natureza("prorrogação sem acréscimo de valor")[0] == "prazo"
    assert classificar_natureza("aditamento sem acréscimo de valor")[0] == "outro"


def test_termo_que_faz_revisao_E_acrescimo_e_misto():
    objeto = ('a) revisão dos valores com fundamento no art. 124, II, "d"; '
              'b) acréscimo quantitativo de 25%')
    assert classificar_natureza(objeto)[0] == "misto"


def test_fundamento_legal_decide_quando_o_objeto_e_mudo():
    assert classificar_natureza("alteração contratual",
                                fundamento_legal='art. 124, II, "d"')[0] == "reajuste"
    assert classificar_natureza("alteração contratual",
                                fundamento_legal="art. 125 da Lei 14.133/2021")[0] == "valor"


def test_qualificador_do_pncp_e_o_ultimo_recurso_e_fica_declarado():
    """`qualif_acrescimo` vem '1' para quase tudo — só vale quando nada mais fala."""
    tipo, origem = classificar_natureza("", qualif_acrescimo="1")
    assert (tipo, origem) == ("valor", "qualificador_pncp")
    tipo, origem = classificar_natureza("acréscimo quantitativo", qualif_reajuste="1")
    assert (tipo, origem) == ("valor", "objeto"), "objeto vence o qualificador"


def test_prazo_aditado_em_dias_implica_prorrogacao():
    assert classificar_natureza("", prazo_aditado_dias=365)[0] == "prazo"


# ───────────────────────────── a soma que entra no teto ───────────────────────────────────────

def test_so_acrescimo_de_valor_entra_no_teto():
    aditivos = [
        {"objeto": "acréscimo quantitativo", "valor_acrescido": 100.0},
        {"objeto": "prorrogação de vigência", "valor_acrescido": 900.0},   # não conta
        {"objeto": "reajuste pelo IPCA", "valor_acrescido": 50.0},         # não conta
    ]
    r = acrescimo_computavel(aditivos)
    assert r["acrescimo"] == pytest.approx(100.0)
    assert r["supressao"] == pytest.approx(0.0)
    assert r["fora_do_teto"]["prazo"] == pytest.approx(900.0)
    assert r["fora_do_teto"]["reajuste"] == pytest.approx(50.0)


def test_supressao_e_computada_separadamente():
    """Art. 125: acréscimos e supressões NÃO se compensam."""
    aditivos = [
        {"objeto": "acréscimo quantitativo", "valor_acrescido": 300.0},
        {"objeto": "supressão de itens", "valor_acrescido": 200.0},
    ]
    r = acrescimo_computavel(aditivos)
    assert r["acrescimo"] == pytest.approx(300.0), "supressão não pode abater o acréscimo"
    assert r["supressao"] == pytest.approx(200.0)


def test_misto_fica_fora_do_teto_e_declarado():
    aditivos = [{"objeto": 'a) revisão dos valores; b) acréscimo quantitativo',
                 "valor_acrescido": 500.0}]
    r = acrescimo_computavel(aditivos)
    assert r["acrescimo"] == pytest.approx(0.0)
    assert r["fora_do_teto"]["misto"] == pytest.approx(500.0)
    assert "aditivo_misto" in r["lacunas"]


def test_sem_natureza_com_dinheiro_vira_lacuna_declarada():
    r = acrescimo_computavel([{"objeto": "texto ilegível", "valor_acrescido": 700.0}])
    assert r["acrescimo"] == pytest.approx(0.0)
    assert "aditivo_sem_natureza" in r["lacunas"]


def test_lista_vazia_nao_inventa_zero_como_medicao():
    r = acrescimo_computavel([])
    assert r["acrescimo"] == 0.0 and r["n"] == 0 and not r["lacunas"]


# ───────────────────────────── a trava contra a 6ª cópia ──────────────────────────────────────

# Nomes que denunciam que o número está OPERANDO como teto do art. 125. Varrer 0.25/0.5 solto no
# repo é inútil — são timeout, peso, fração de tela: a primeira versão deste teste acusou 24
# arquivos, quase todos inocentes. O que identifica a cópia é o NOME que recebe o número.
_NOMES_DE_TETO = re.compile(r"aditiv|teto|acr[ée]scim|estouro|limite_adit", re.I)
# 0.50 é peso e meia-nota em meio repositório; só conta como cópia do teto quando o nome fala de
# REFORMA ou de TETO — é a diferença entre `ADITIVO_REFORMA = 0.50` (cópia) e
# `VALOR_ADITIVO_METADE_LIMITE = 0.5` (a nota que o índice dá, não o teto).
_NOMES_DE_REFORMA = re.compile(r"reforma|teto", re.I)


def _e_valor_de_teto(no, *, com_reforma: bool) -> bool:
    if not (isinstance(no, ast.Constant) and isinstance(no.value, (int, float))
            and not isinstance(no.value, bool)):
        return False
    alvos = (0.25, 1.25) + ((0.50, 1.50) if com_reforma else ())
    return any(abs(float(no.value) - v) < 1e-9 for v in alvos)


def _literais_de_teto(caminho: pathlib.Path) -> set[str]:
    """Literais do teto que OPERAM sob um nome de aditivo/teto/acréscimo.

    Três formas, que são exatamente as das cinco cópias que existiam:
      · `_TETO_PADRAO = 0.25` / `ADITIVO_REFORMA = 0.50` / `D10_LIMITE_ADITIVO = 1.25`;
      · `teto = 0.50 if ... else 0.25` e `estouro = pct >= 0.25` (o nome do alvo denuncia);
      · `Parametro("aditivo_limite_frac", 0.25, ...)` — número ao lado de uma string 'aditivo'.
    Comentário e docstring ficam de fora de graça: não existem na árvore.
    """
    try:
        arvore = ast.parse(caminho.read_text(encoding="utf-8"))
    except (SyntaxError, OSError, UnicodeDecodeError):
        return set()

    achados: set[str] = set()

    for no in ast.walk(arvore):
        alvos: list[str] = []
        valor = None
        if isinstance(no, ast.Assign):
            alvos = [t.id for t in no.targets if isinstance(t, ast.Name)]
            valor = no.value
        elif isinstance(no, ast.AnnAssign) and isinstance(no.target, ast.Name):
            alvos, valor = [no.target.id], no.value
        if valor is not None and any(_NOMES_DE_TETO.search(a) for a in alvos):
            reforma = any(_NOMES_DE_REFORMA.search(a) for a in alvos)
            achados |= {repr(n.value) for n in ast.walk(valor)
                        if _e_valor_de_teto(n, com_reforma=reforma)}

        # `Parametro("aditivo_limite_frac", 0.25, ...)` — o valor vem LOGO DEPOIS do nome.
        # Olhar a chamada inteira acusava peso e severidade de `Indicador("...aditivo...", ...,
        # 0.5)`, que não são teto nenhum: só a posição seguinte ao nome é o valor do parâmetro.
        if isinstance(no, ast.Call):
            for i, arg in enumerate(no.args[:-1]):
                if not (isinstance(arg, ast.Constant) and isinstance(arg.value, str)):
                    continue
                if not _NOMES_DE_TETO.search(arg.value):
                    continue
                seguinte = no.args[i + 1]
                if _e_valor_de_teto(seguinte,
                                    com_reforma=bool(_NOMES_DE_REFORMA.search(arg.value))):
                    achados.add(repr(seguinte.value))

        # default de parâmetro: `def d11(con, limite_aditivo=D10_LIMITE_ADITIVO)` só pega se for
        # literal; se for a constante, o Assign acima já pegou.
        #
        # O pareamento nome↔default tem de ser exato: `def f(piso_precisao=0.5,
        # teto_precisao=0.95)` era acusado porque bastava UM nome da assinatura casar com
        # "teto" para todos os defaults entrarem — e o 0.5 acusado era do piso, não do teto.
        if isinstance(no, (ast.FunctionDef, ast.AsyncFunctionDef)):
            pares = list(zip([a.arg for a in no.args.args][-len(no.args.defaults):],
                             no.args.defaults)) if no.args.defaults else []
            pares += [(a.arg, d) for a, d in zip(no.args.kwonlyargs, no.args.kw_defaults) if d]
            for nome, padrao in pares:
                if _NOMES_DE_TETO.search(nome) and _e_valor_de_teto(
                        padrao, com_reforma=bool(_NOMES_DE_REFORMA.search(nome))):
                    achados.add(repr(padrao.value))
    return achados


@pytest.mark.parametrize("codigo,deve_pegar", [
    # as cinco formas que existiam de verdade no repositório
    ("_TETO_PADRAO = 0.25", True),
    ("ADITIVO_REFORMA = 0.50", True),
    ("D10_LIMITE_ADITIVO = 1.25", True),
    ("teto = 0.50 if reforma else 0.25", True),
    ("estouro = pct >= 0.25", True),
    ('Parametro("aditivo_limite_frac", 0.25, "razao")', True),
    ("def d11(con, limite_aditivo=1.25): pass", True),
    # o que NÃO pode ser acusado — a razão de a primeira versão ter listado 24 arquivos
    ("VALOR_ADITIVO_METADE_LIMITE = 0.5", False),          # nota do índice, não teto
    ('Indicador("aditivo_excessivo", "alta", 0.5)', False),  # peso do indicador
    ("def f(piso_precisao=0.5, teto_precisao=0.95): pass", False),  # 0.5 é do PISO
    ("TIMEOUT = 0.25", False),                              # nada a ver com aditivo
    ("_FRACAO_MEDIO = 0.50", False),                        # fração DO teto, não o teto
])
def test_a_catraca_realmente_morde(tmp_path, codigo, deve_pegar):
    """Catraca que nunca dispara é decoração. Este teste prova as duas direções."""
    alvo = tmp_path / "amostra.py"
    alvo.write_text(codigo + "\n", encoding="utf-8")
    achados = _literais_de_teto(alvo)
    assert bool(achados) is deve_pegar, f"{codigo!r} -> {achados}"


def test_nenhum_modulo_de_aditivo_repete_o_teto():
    raiz = pathlib.Path(__file__).resolve().parent.parent
    ofensores: dict[str, list[str]] = {}
    for f in list(raiz.glob("compliance_agent/**/*.py")) + list(raiz.glob("tools/**/*.py")):
        rel = f.relative_to(raiz).as_posix()
        if rel in _PERMITIDO:
            continue
        achados = _literais_de_teto(f)
        if achados:
            ofensores[rel] = sorted(achados)
    assert not ofensores, (
        "teto do art. 125 DUPLICADO — importar de compliance_agent.limites_aditivo "
        f"(teto_acrescimo / acrescimo_computavel): {ofensores}")


# ─────────────── o art. 124 tem incisos que vão para lados OPOSTOS do teto ────────────────────
# Fundamentos VERBATIM da base real (contrato 28538734000148-2-000383/2025 e vizinhos), onde a
# primeira versão deste módulo classificava tudo como recomposição e tirava do teto do art. 125
# um acréscimo quantitativo de +R$ 2,84 mi. Texto legal conferido no Planalto em 2026-07-29.

@pytest.mark.parametrize("fundamento,esperado", [
    # 124, I — alteração unilateral; a alínea "b" é acréscimo/diminuição QUANTITATIVA,
    # "nos limites permitidos por esta Lei" (ou seja, sujeita ao teto do art. 125)
    ('artigo 124, inciso I, alínea "b", da Lei Federal nº 14.133/21', "valor"),
    ("art. 124, I, 'b'", "valor"),
    # 124, II, "d" — restabelecer o equilíbrio econômico-financeiro: recomposição
    ('artigo 124, inciso II, alínea "d", da Lei Federal nº 14.133/21', "reajuste"),
    ('art. 124, II, "d" da Lei nº 14.133/21', "reajuste"),
    # 134 — alteração de preços por criação/alteração/extinção de tributos: recomposição
    ("artigo 134 da Lei Federal nº 14.133/2021", "reajuste"),
    # 135 — repactuação de serviços contínuos com mão de obra: recomposição
    ("art. 135 da Lei 14.133/2021", "reajuste"),
    # 124, II, outras alíneas — garantia, regime de execução, forma de pagamento: não mexem valor
    ('artigo 124, inciso II, alínea "a"', "outro"),
    # 125 — o próprio teto
    ("art. 125 da Lei 14.133/2021", "valor"),
])
def test_inciso_do_art_124_decide_o_lado_do_teto(fundamento, esperado):
    tipo, origem = classificar_natureza("", fundamento_legal=fundamento)
    assert (tipo, origem) == (esperado, "fundamento_legal"), fundamento


def test_objeto_continua_vencendo_o_fundamento():
    """O objeto é a fonte mais confiável; o fundamento só decide quando ele é mudo."""
    tipo, origem = classificar_natureza(
        "prorrogação do prazo de vigência",
        fundamento_legal='art. 124, inciso I, alínea "b"')
    assert (tipo, origem) == ("prazo", "objeto")


# ───────────── a assimetria do art. 125: 50% é SÓ do acréscimo ────────────────────────────────
# "o contratado será obrigado a aceitar ... acréscimos ou supressões de até 25% ..., e, no caso de
# reforma de edifício ou de equipamento, o limite para os ACRÉSCIMOS será de 50%" (texto conferido
# no Planalto em 2026-07-29). Usar o mesmo teto dos dois lados daria 50% de folga a uma supressão
# em reforma — falso negativo justamente onde a supressão costuma esvaziar o objeto depois de
# vencida a licitação.

def test_supressao_em_reforma_continua_limitada_a_25():
    from compliance_agent.limites_aditivo import teto_supressao

    assert teto_supressao("reforma") == pytest.approx(0.25)
    assert teto_supressao("reforma de edifício") == pytest.approx(0.25)
    assert teto_acrescimo("reforma") == pytest.approx(0.50), "o acréscimo é que sobe"


@pytest.mark.parametrize("tipo", [None, "", "obra", "servico_continuado", "reforma"])
def test_teto_de_supressao_e_o_mesmo_para_todo_objeto(tipo):
    from compliance_agent.limites_aditivo import teto_supressao

    assert teto_supressao(tipo) == pytest.approx(0.25)


def test_supressao_no_regime_antigo_tambem_e_25():
    from compliance_agent.limites_aditivo import teto_supressao

    assert teto_supressao("reforma", regime="8666") == pytest.approx(0.25)
