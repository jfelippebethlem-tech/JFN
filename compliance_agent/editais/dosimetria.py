# -*- coding: utf-8 -*-
"""Dosimetria da MEDIDA (H.4) — o que se pede, não apenas qual peça se protocola.

`editais/escalada.recomendar` responde **qual peça** cabe (diligência, representação, cautelar) e
com que urgência. Falta a outra metade da decisão: **o que a peça PEDE**. Recomendação e
imputação de débito são a mesma peça com pedidos incomparáveis, e apresentá-las como equivalentes
é a inflação de manchete que esta casa já corrigiu sete vezes.

AS MEDIDAS, do menos ao mais gravoso, cada uma com o que a autoriza:

    recomendacao ......... falha de instrução sem dano nem violação de teto (Lei 8.443 art. 250 III)
    determinacao ......... violação objetiva de norma, com prazo para corrigir (art. 250 II)
    multa ................ o ato é grave E há responsável identificado (art. 58)
    debito ............... há DANO apurado, com valor e execução comprovada (art. 19 e 57)
    inabilitacao ......... fraude/gravidade + reincidência do agente (art. 60)
    representacao_criminal indício de tipo penal — encaminhamento ao MP, nunca imputação própria

TRÊS TRAVAS, e cada uma corresponde a um erro que a casa já pagou:

  1. **Débito exige dano com OB.** Sobrepreço é vício do orçamento; superfaturamento é dano, e
     dano exige pagamento — Ordem Bancária, nunca empenho. Sem OB, o pedido cai para determinação.
     (`knowledge/economicidade` guarda a distinção; aqui ela vira consequência.)
  2. **Multa e inabilitação exigem responsável identificado.** O extrator de ordenador/gestor/fiscal
     tem cobertura baixa; pedir sanção pessoal sem saber quem assinou é peça devolvida.
  3. **Nenhuma medida pessoal sobre grau C.** Juízo de IA não sustenta sanção — é o teto que
     `editais/flags` já impõe e que `knowledge/standard_prova` mede. Aqui ele corta o pedido.

O QUE ISTO NÃO FAZ: não fixa valor de multa nem percentual. Dosimetria de valor é do julgador; o
que o controle externo entrega é a MEDIDA cabível e o que a fundamenta.
"""
from __future__ import annotations

from typing import Any

# Ordem de gravidade — usada para "a mais grave manda" e para rebaixamento.
ESCALA: tuple[str, ...] = ("recomendacao", "determinacao", "multa", "debito", "inabilitacao")

FUNDAMENTO: dict[str, str] = {
    "recomendacao": "Lei 8.443/1992, art. 250, III (recomendação de aprimoramento)",
    "determinacao": "Lei 8.443/1992, art. 250, II (determinação com prazo para correção)",
    "multa": "Lei 8.443/1992, art. 58 (multa por ato de gestão ilegítimo ou antieconômico)",
    "debito": "Lei 8.443/1992, arts. 19 e 57 (imputação de débito com quantificação do dano)",
    "inabilitacao": "Lei 8.443/1992, art. 60 (inabilitação para função de confiança)",
    "representacao_criminal": ("art. 40 do CPP c/c os arts. 337-E a 337-P do Código Penal "
                               "(incorporados pela Lei 14.133/2021) — ENCAMINHAMENTO ao "
                               "Ministério Público, a quem compete a persecução"),
}

# Graus de evidência que NÃO sustentam medida pessoal (multa, inabilitação, criminal).
_GRAUS_FRACOS = {"C", "D", "E"}
REINCIDENCIA_INABILITACAO = 3


def _mais_grave(a: str, b: str) -> str:
    return a if ESCALA.index(a) >= ESCALA.index(b) else b


def graduar(*, sv: int, teste_objetivo_violado: bool = False, dano_apurado: float | None = None,
            dano_com_ob: bool = False, responsavel_identificado: bool = False,
            reincidencia_agente: int = 0, grau_evidencia: str | None = None,
            indicio_penal: bool = False) -> dict[str, Any]:
    """Medida cabível, o que a fundamenta e o que faltou para a mais gravosa.

    `faltou` é tão importante quanto `medida`: dizer "cabe determinação" sem dizer que só não cabe
    débito porque não há OB deixa o leitor sem saber o que buscar. É o mesmo espírito de
    `reporting/quesitos_diligencia`.
    """
    sv_c = max(1, min(25, int(sv)))
    motivos: list[str] = []
    faltou: list[str] = []

    medida = "recomendacao"
    if teste_objetivo_violado:
        medida = _mais_grave(medida, "determinacao")
        motivos.append("violação objetiva de norma aferida por teste determinístico")
    if sv_c >= 10:
        medida = _mais_grave(medida, "determinacao")
        motivos.append(f"matriz S×V em {sv_c} (faixa de diligência prioritária ou acima)")

    grau_forte = bool(grau_evidencia) and grau_evidencia not in _GRAUS_FRACOS
    pessoal_ok = grau_forte and responsavel_identificado

    # ── multa: gravidade + responsável + evidência que sustente sanção pessoal
    if sv_c >= 16 or (teste_objetivo_violado and sv_c >= 10):
        if pessoal_ok:
            medida = _mais_grave(medida, "multa")
            motivos.append("gravidade alta com responsável identificado e evidência A/B")
        else:
            if not responsavel_identificado:
                faltou.append("responsável identificado (ordenador, gestor ou fiscal que assinou "
                              "o ato) — sem isso a sanção pessoal é peça devolvida")
            if not grau_forte:
                atual = grau_evidencia or "não declarado"
                faltou.append(f"evidência de grau A ou B (atual: {atual}) — juízo de IA não "
                              "sustenta sanção pessoal")

    # ── débito: DANO com pagamento comprovado. Sem OB não há dano, há vício de orçamento.
    if dano_apurado and dano_apurado > 0:
        if dano_com_ob:
            medida = _mais_grave(medida, "debito")
            motivos.append("dano quantificado com pagamento comprovado por Ordem Bancária")
        else:
            faltou.append("Ordem Bancária que comprove o pagamento — empenho não é pagamento, e "
                          "sem execução há sobrepreço (vício do orçamento), não superfaturamento "
                          "(dano)")
    elif dano_com_ob:
        faltou.append("quantificação do dano com memória de cálculo — há pagamento, falta o valor")

    # ── inabilitação: gravidade + reincidência do AGENTE (não do órgão)
    if reincidencia_agente >= REINCIDENCIA_INABILITACAO:
        if pessoal_ok and medida in ("multa", "debito"):
            medida = _mais_grave(medida, "inabilitacao")
            motivos.append(f"reincidência do agente em {reincidencia_agente} ocorrências")
        else:
            faltou.append("base para medida pessoal (evidência A/B + responsável identificado) "
                          "antes de a reincidência agravar para inabilitação")

    encaminhamentos: list[dict[str, str]] = []
    if indicio_penal:
        if grau_forte:
            encaminhamentos.append({
                "medida": "representacao_criminal", "fundamento": FUNDAMENTO["representacao_criminal"],
                "nota": ("ENCAMINHAMENTO, não imputação: a tipificação penal compete ao Ministério "
                         "Público e ao Judiciário. O controle externo remete os elementos.")})
        else:
            faltou.append("evidência de grau A ou B para encaminhamento criminal — indício de IA "
                          "não fundamenta notícia-crime")

    return {
        "medida": medida,
        "fundamento": FUNDAMENTO[medida],
        "motivos": motivos,
        "faltou_para_medida_mais_gravosa": faltou,
        "encaminhamentos": encaminhamentos,
        "sv": sv_c,
        "grau_evidencia": grau_evidencia,
        "ressalva": _RESSALVA,
    }


def render_texto(d: dict[str, Any]) -> str:
    """Bloco pronto para a peça, montado pelo código."""
    linhas = [f"MEDIDA CABÍVEL: {d['medida'].replace('_', ' ')}",
              f"Fundamento: {d['fundamento']}", ""]
    if d["motivos"]:
        linhas.append("Por quê:")
        linhas += [f"  - {m}" for m in d["motivos"]]
        linhas.append("")
    if d["encaminhamentos"]:
        linhas.append("Encaminhamento a outro órgão:")
        for e in d["encaminhamentos"]:
            linhas.append(f"  - {e['medida'].replace('_', ' ')} — {e['fundamento']}")
            linhas.append(f"    {e['nota']}")
        linhas.append("")
    if d["faltou_para_medida_mais_gravosa"]:
        linhas.append("O que impede medida mais gravosa (e, portanto, o que buscar):")
        linhas += [f"  - {f}" for f in d["faltou_para_medida_mais_gravosa"]]
        linhas.append("")
    linhas.append(d["ressalva"])
    return "\n".join(linhas)


_RESSALVA = (
    "A medida indicada é SUGESTÃO de encaminhamento do controle externo, não decisão. A "
    "dosimetria de valor e a imputação de responsabilidade competem ao órgão julgador; vigora a "
    "presunção de legitimidade dos atos administrativos e o contraditório é prévio a qualquer "
    "sanção."
)
