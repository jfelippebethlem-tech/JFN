# -*- coding: utf-8 -*-
"""Standard probatório por PRETENSÃO — quanto de prova cada peça exige.

POR QUE ESTE MÓDULO EXISTE. A casa já gradua a EVIDÊNCIA (`editais/flags.grau_flag`, A a E) e já
gradua a PEÇA (`editais/escalada.recomendar`, monitorar → representação com cautelar). Faltava a
régua do meio: **quanto de prova cada pretensão exige**. Sem ela, o mesmo conjunto de indícios
serve para pedir diligência e para pedir condenação — e é assim que uma peça morre na inicial.

A DOUTRINA, e ela não é uniforme por acaso:

  · **indício qualificado** basta para DILIGÊNCIA — o objetivo é justamente obter a prova;
  · **preponderância de provas** é o standard do RESSARCIMENTO, que tem natureza indenizatória;
  · **prova clara e convincente** é o exigido para SANÇÃO por improbidade — e a Lei 14.230/2021
    reforçou isso ao dizer, no art. 17-C, I, que os elementos dos arts. 9º, 10 e 11 "não podem
    ser presumidos";
  · **além de dúvida razoável** é o penal.

O STJ é firme em que a frustração à competitividade, por si só, não presume dano nem dolo — ou
seja, o pulo de "cláusula restritiva" para "improbidade" precisa de prova nova, não de retórica.

COMO ISTO SE LIGA AO RESTO. `editais/flags` diz que juízo de IA tem teto no grau C. Aqui isso
vira consequência prática: **grau C não atinge "clara e convincente"**. Um caso inteiramente
sustentado por leitura de IA não pode fundamentar pedido de sanção — pode fundamentar diligência,
que é como se obtém o que falta. A convergência de indícios independentes (a multiplicativa de
`detectores/base.score_processo`) é o caminho legítimo para subir de standard, desde que as
famílias sejam de fato independentes.
"""
from __future__ import annotations

from dataclasses import dataclass

# Graus de evidência da casa (editais/flags): A CERTO · B FORTE · C SUSPEITO · D NÃO-AFERÍVEL ·
# E EXCULPADO. Só A e B podem fundamentar peça (`pode_fundamentar_peca`).
_FORCA_GRAU = {"A": 4, "B": 3, "C": 2, "D": 0, "E": 0}


@dataclass(frozen=True)
class Standard:
    id: str
    nome: str
    nivel: int                 # ordinal, para comparar
    descricao: str
    fundamento: str
    grau_minimo: str           # menor grau de evidência que, sozinho, pode atingi-lo
    exige_convergencia: bool   # ...ou exige ≥2 famílias independentes


STANDARDS: dict[str, Standard] = {
    "indicio": Standard(
        "indicio", "Indício", 1,
        "Sinal que justifica olhar mais de perto. Não sustenta afirmação.",
        "Poder-dever de fiscalização (CF/88 arts. 70 e 71)",
        grau_minimo="C", exige_convergencia=False),
    "indicio_qualificado": Standard(
        "indicio_qualificado", "Indício qualificado", 2,
        "Indício com fonte identificada e trecho ancorado — basta para DILIGÊNCIA, cujo "
        "objetivo é exatamente obter a prova que falta.",
        "LINDB art. 22; dever de motivação",
        grau_minimo="C", exige_convergencia=False),
    "preponderancia": Standard(
        "preponderancia", "Preponderância de provas", 3,
        "Mais provável que não. Standard do RESSARCIMENTO ao erário, de natureza indenizatória.",
        "CF/88 art. 37 §5º; doutrina de standards em ação de improbidade",
        grau_minimo="B", exige_convergencia=False),
    "clara_e_convincente": Standard(
        "clara_e_convincente", "Prova clara e convincente", 4,
        "Exigido para SANÇÃO por improbidade. Os elementos dos arts. 9º, 10 e 11 não podem ser "
        "presumidos.",
        "Lei 8.429/1992, art. 17-C, I (redação da Lei 14.230/2021)",
        grau_minimo="A", exige_convergencia=True),
    "alem_de_duvida_razoavel": Standard(
        "alem_de_duvida_razoavel", "Além de dúvida razoável", 5,
        "Standard penal. Fora do alcance do controle externo administrativo.",
        "CF/88 art. 5º, LVII; CPP",
        grau_minimo="A", exige_convergencia=True),
}

# Pretensão → standard exigido.
PRETENSAO_STANDARD: dict[str, str] = {
    "monitorar": "indicio",
    "diligencia": "indicio_qualificado",
    "requisicao_informacao": "indicio_qualificado",
    "representacao": "preponderancia",
    "representacao_cautelar": "preponderancia",
    "ressarcimento": "preponderancia",
    "sancao_pessoal": "clara_e_convincente",
    "improbidade": "clara_e_convincente",
    "noticia_crime": "clara_e_convincente",
}


def standard_de(pretensao: str) -> Standard | None:
    sid = PRETENSAO_STANDARD.get(str(pretensao or "").strip().lower())
    return STANDARDS.get(sid) if sid else None


def atingido(grau: str, *, familias_independentes: int = 1) -> str:
    """O standard MÁXIMO alcançado por um conjunto de evidências.

    `grau` é o melhor grau de evidência do caso (A-E, `editais/flags`); `familias_independentes`
    é quantas famílias de detecção convergiram — duas leituras do MESMO campo não são duas
    famílias, e contá-las como tal é a forma mais fácil de inflar um caso.
    """
    g = str(grau or "").strip().upper()[:1]
    forca = _FORCA_GRAU.get(g, 0)
    if forca == 0:
        return "indicio"
    melhor = "indicio"
    for s in sorted(STANDARDS.values(), key=lambda x: x.nivel):
        if forca < _FORCA_GRAU[s.grau_minimo]:
            continue
        if s.exige_convergencia and familias_independentes < 2:
            continue
        melhor = s.id
    return melhor


def suficiente(grau: str, pretensao: str, *, familias_independentes: int = 1) -> dict:
    """A evidência sustenta a pretensão? Devolve o veredito E o que falta para sustentá-la.

    O `falta` é o produto útil: dizer "para pedir sanção falta subir de C para A/B, e isso exige
    corroboração determinística independente" orienta a próxima diligência. "Insuficiente" sozinho
    não orienta ninguém.
    """
    exigido = standard_de(pretensao)
    if exigido is None:
        return {"ok": False, "motivo": f"pretensão desconhecida: {pretensao!r}",
                "standard_exigido": None, "standard_atingido": None}
    alcancado = STANDARDS[atingido(grau, familias_independentes=familias_independentes)]
    ok = alcancado.nivel >= exigido.nivel
    falta: list[str] = []
    if not ok:
        g = str(grau or "").strip().upper()[:1]
        if _FORCA_GRAU.get(g, 0) < _FORCA_GRAU[exigido.grau_minimo]:
            falta.append(
                f"elevar o grau de evidência de {g or '?'} para {exigido.grau_minimo} — juízo de "
                "IA tem teto no grau C e só sobe por corroboração determinística independente "
                "(editais/flags)")
        if exigido.exige_convergencia and familias_independentes < 2:
            falta.append("convergência de ao menos 2 famílias de detecção INDEPENDENTES "
                         "(dois detectores que leem o mesmo campo não são duas famílias)")
    return {"ok": ok, "standard_exigido": exigido.id, "standard_atingido": alcancado.id,
            "nome_exigido": exigido.nome, "nome_atingido": alcancado.nome,
            "fundamento": exigido.fundamento, "falta": falta,
            "motivo": ("evidência suficiente para a pretensão" if ok else
                       "evidência abaixo do standard da pretensão")}


def rebaixar_peca(peca: str, grau: str, *, familias_independentes: int = 1) -> dict:
    """Se a evidência não sustenta a peça recomendada, devolve a peça que ela sustenta.

    É o antídoto direto contra a inflação de manchete que a casa já corrigiu sete vezes: em vez
    de recomendar representação sobre grau C, recomenda diligência — que é o passo que produz a
    prova. Nunca ELEVA a peça; só rebaixa.
    """
    ordem = ["monitorar", "diligencia", "representacao", "sancao_pessoal"]
    atual = str(peca or "").strip().lower()
    # `representacao_cautelar` guarda a urgência, que é dimensão à parte do standard.
    base = "representacao" if atual.startswith("representacao") else atual
    if base not in ordem:
        return {"peca": peca, "rebaixada": False, "motivo": "peça fora da régua conhecida"}
    for i in range(ordem.index(base), -1, -1):
        candidata = ordem[i]
        r = suficiente(grau, candidata, familias_independentes=familias_independentes)
        if r["ok"]:
            final = peca if candidata == base else candidata
            return {"peca": final, "rebaixada": candidata != base,
                    "standard_exigido": r["standard_exigido"],
                    "standard_atingido": r["standard_atingido"],
                    "motivo": ("evidência sustenta a peça recomendada" if candidata == base else
                               f"evidência não atinge o standard de '{base}' — rebaixado para "
                               f"'{candidata}', que é o passo capaz de produzir a prova que falta"),
                    "falta": []}
    r = suficiente(grau, "monitorar", familias_independentes=familias_independentes)
    return {"peca": "monitorar", "rebaixada": True, "standard_exigido": r["standard_exigido"],
            "standard_atingido": r["standard_atingido"],
            "motivo": "evidência não sustenta peça alguma além do monitoramento",
            "falta": r["falta"]}
