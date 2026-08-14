# -*- coding: utf-8 -*-
"""O placar da terceira leitura — e as duas armadilhas que ele já expôs.

A leitura dupla extrai sinal da DIVERGÊNCIA entre regra e LLM grátis, e divergência só enxerga campo
que alguém perguntou. Os dois maiores achados de leitura desta sessão vieram de fora dela: a Ata de
Registro de Preços (21% do acervo, ninguém perguntava) e a regra tributária da planilha de retenção,
que fundamenta RETENÇÃO com a mesma fórmula do fundamento da despesa. Nos dois casos os leitores
CONCORDAVAM e o laudo saía completo e errado por omissão.

**Armadilha 1 — ausência não é erro.** `NAO_CONSTA`, vazio e `SEM CONTRATO` afirmam a mesma coisa.
Tratar isso como divergência foi o defeito que afogou 61 das 77 primeiras linhas da fila.

**Armadilha 2 — "não conferi" ≠ "não existe".** O primeiro placar deu 33% à régua no `favorecido`
porque eu marcara `NAO_CONSTA` em processos onde simplesmente não fui atrás do CNPJ. Gabarito que
afirma ausência onde o leitor apenas não olhou pune quem acertou: com o `?`, a régua sobe para 75%
e a LLM para 100%.
"""
from __future__ import annotations

from tools.gabarito_claude import NAO_CONFERI, concorda, placar


def test_ausencia_casa_com_ausencia():
    for a, b in (("NAO_CONSTA", ""), ("SEM CONTRATO", "NAO_CONSTA"), ("", "N/A")):
        assert concorda(a, b)


def test_grafia_diferente_do_mesmo_numero_casa():
    assert concorda("PE 008/23", "008/23")
    assert concorda("R$ 1.038.330,00", "1038330.00")


def test_numero_diferente_NAO_casa():
    assert not concorda("182/2024", "417/2023")
    assert not concorda("NAO_CONSTA", "025/2024")


def test_nao_conferi_sai_do_placar():
    """Sem isto, o campo que eu não olhei conta como erro de quem leu o documento inteiro."""
    p = placar()
    assert p["ok"]
    marcados = sum(1 for c in ("favorecido",) if c in p["regra"])
    assert marcados == 0 or p["regra"]["favorecido"]["acerto"] + p["regra"]["favorecido"]["erro"] < p["processos"]


def test_o_gabarito_acumula_entre_rodadas():
    """Sem acumular, cada confronto morre na rodada em que aconteceu e vira anedota."""
    p = placar()
    assert p["processos"] >= 8, f"gabarito encolheu para {p['processos']} processos"


def test_o_marcador_de_nao_conferido_e_explicito():
    assert NAO_CONFERI == "?"


def test_conferir_existe_e_cobre_os_quatro_instrumentos():
    """A conferência por documento INTEIRO nasceu de um viés medido: eu montava o gabarito lendo
    TRECHOS e, em cinco casos, escrevi `NAO_CONSTA` onde o documento tinha o instrumento — sempre na
    mesma direção, sempre subestimando o leitor bom.

    Gabarito enviesado para a ausência leva a "consertar" régua que está certa, que é o erro mais
    caro possível numa ferramenta de fiscalização. Por isso a conferência virou comando, em vez de
    depender de eu lembrar de fazê-la.
    """
    import inspect

    from tools.gabarito_claude import conferir
    fonte = inspect.getsource(conferir)
    for campo in ("contrato", "arp", "pregao", "tac"):
        assert f'"{campo}"' in fonte, f"{campo} ficou fora da conferência"
    assert "texto_do_processo" in fonte, "a conferência tem de ler o documento, não um recorte"


def test_entrada_automatica_NAO_pontua_a_regua():
    """Circularidade declarada: os candidatos da conferência vêm da RÉGUA, então uma entrada
    automática a faria concordar consigo mesma. Ela pontua só a LLM, que não participou.

    Sem essa separação, ampliar a cobertura do confronto inflaria o número da régua de graça — que
    é o oposto de medir."""
    import inspect

    from tools.gabarito_claude import placar
    fonte = inspect.getsource(placar)
    assert 'esperado.get("fonte") == "conferido"' in fonte
    assert '(("ia", v_ia),) if automatico' in fonte, (
        "entrada conferida automaticamente não pode pontuar a régua")


def test_auto_conferir_recusa_julgar_o_que_e_juizo():
    """`dispositivo` (escolher entre fundamentos) e `favorecido` (vem da OB, não do texto) nunca
    são preenchidos automaticamente — ali a leitura não basta."""
    import inspect

    from tools.gabarito_claude import NAO_CONFERI, auto_conferir
    fonte = inspect.getsource(auto_conferir)
    assert 'r["dispositivo"] = NAO_CONFERI' in fonte
    assert 'r["favorecido"] = NAO_CONFERI' in fonte
    assert NAO_CONFERI == "?"


def test_varios_candidatos_viram_NAO_CONFERI_em_vez_de_escolha():
    """Metade do acervo cita mais de um contrato. Escolher um seria inventar referência."""
    import inspect

    from tools.gabarito_claude import auto_conferir
    assert "len(vals) == 1" in inspect.getsource(auto_conferir)


def test_o_literal_do_SIAFE_afirma_ausencia_e_tem_digitos():
    """`00000000 - SEM CONTRATO` afirma que NÃO HÁ, e passava por "presente" porque tem dígitos.

    Medido: 15 dos 26 "erros" da LLM em `contrato` eram ela dizendo o literal do SIAFE contra um
    gabarito `NAO_CONSTA`. A mesma resposta, contada como divergência — **exatamente o defeito que
    abriu esta sessão (ausência concorde na fila), agora dentro da ferramenta que julga os outros
    dois leitores.** O placar da LLM subiu de 69% para 81% só com o conserto.
    """
    assert concorda("NAO_CONSTA", "00000000 - SEM CONTRATO")
    assert concorda("SEM CONTRATO", "NAO_CONSTA")
    assert concorda("00000000 - SEM CONTRATO", "")


def test_a_correcao_nao_transforma_numero_em_ausencia():
    """A guarda não pode virar indulgência: número presente contra ausência continua divergindo."""
    assert not concorda("NAO_CONSTA", "443/2025")
    assert not concorda("443/2025", "417/2023")


def test_campo_nao_perguntado_nao_conta_contra_a_IA_mas_a_REGUA_segue_medida():
    """`arp` e `tac` entraram no formulário no meio da sessão: as leituras anteriores não têm a
    chave, e o placar as penalizava como se a IA tivesse calado. **19 dos 20 "erros" em `arp` eram
    isso** — a fila já tratava o caso (`nao_perguntado`), o placar não.

    E a primeira correção exagerou: pular o campo INTEIRO derrubou o denominador da régua de 43 para
    7, apagando medida boa. Quem não foi perguntada foi a IA; a régua respondeu e continua medida.
    """
    import inspect

    from tools.gabarito_claude import placar
    fonte = inspect.getsource(placar)
    assert "ia_perguntada = campo in fatos_ia" in fonte
    assert 'if ia_perguntada else ()' in fonte, "a régua tem de continuar pontuando"
    p = placar()
    assert p["regra"]["arp"]["acerto"] + p["regra"]["arp"]["erro"] > 20, (
        "a régua perdeu denominador — o pulo era só para a IA")
