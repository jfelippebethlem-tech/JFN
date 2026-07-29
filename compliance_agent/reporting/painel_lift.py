# -*- coding: utf-8 -*-
"""Painel de LIFT por detector (G.8) — qual sinal merece confiança, medido e publicado.

A PERGUNTA QUE NINGUÉM RESPONDIA EM PÚBLICO. O JFN tem 38 detectores e todos entregam "achado".
Nenhum relatório dizia quais deles, historicamente, apontam para empresas que **depois** foram
sancionadas — e sem isso a fila do fiscal trata sinal bom e sinal inútil como iguais.
`retro_auditoria.avaliar_lift` já calculava o número contra o proxy não-circular (sanção
POSTERIOR ao sinal); faltava publicá-lo, que é o que muda o comportamento.

LIFT ABAIXO DE 1 É INFORMAÇÃO, NÃO ERRO A ESCONDER. Medido nesta base: `escalada_preco` tem lift
2,17 e `corrida_dezembro` 0,59 — o segundo aponta para empresas MENOS sancionadas que a média.
Isso não significa que corrida de dezembro seja lícita; significa que, como preditor de sanção,
o sinal não serve, e usá-lo para ordenar a fila desperdiça a atenção do fiscal.

QUATRO RESSALVAS QUE VIAJAM COM O NÚMERO, e sem elas ele engana:

  · **O gabarito é PROXY.** "Foi sancionado depois" não é "cometeu o vício": muita irregularidade
    nunca vira sanção, e sanção pode vir por outro motivo. O lift mede correlação com punição
    efetiva, que é o melhor proxy disponível — não a verdade do achado.
  · **n pequeno não mede nada.** Vinte empresas não sustentam razão de taxas; o painel separa
    quem tem amostra de quem não tem, em vez de ordenar tudo junto.
  · **Circularidade.** Detector que já usa sanção como insumo prevê sanção por construção. Vem
    marcado de `avaliar_lift` e sai declarado.
  · **Lift alto não promove grau.** Continua valendo o teto da régua de evidência: um detector
    preditivo produz achado mais valioso, não achado mais provado.
"""
from __future__ import annotations

from typing import Any

# Faixas de leitura. Não são notas — são o que se pode fazer com o detector.
LIFT_FORTE = 2.0
LIFT_UTIL = 1.3
LIFT_NEUTRO = 0.8
N_MINIMO = 30          # abaixo disto a razão de taxas é ruído


def classificar(lift: float | None, n: int, *, circular: bool = False) -> tuple[str, str]:
    """`(classe, leitura)` — e amostra pequena tem classe própria, nunca vira 'neutro'."""
    if circular:
        return ("circular", "usa sanção como insumo — prevê sanção por construção; "
                            "o lift aqui não informa nada")
    if lift is None:
        return "nao_medido", "sem sinal registrado no período — não medido, e não 'sem valor'"
    if n < N_MINIMO:
        return ("amostra_pequena",
                f"apenas {n} empresas: a razão de taxas não se sustenta; medir de novo depois")
    if lift >= LIFT_FORTE:
        return "forte", "aponta para empresas sancionadas bem acima da base — priorizar na fila"
    if lift >= LIFT_UTIL:
        return "util", "acima da base — contribui para ordenar a fila"
    if lift >= LIFT_NEUTRO:
        return "neutro", "indistinguível da base — não ajuda a priorizar"
    return ("nao_prediz",
            "aponta para empresas MENOS sancionadas que a média — como preditor de sanção "
            "não serve, e usá-lo para ordenar a fila gasta atenção do fiscal")


def montar(resultado: dict[str, Any] | None = None, *, db_path: str | None = None) -> dict:
    """Painel pronto. `resultado` permite injetar a medição (teste não toca a base)."""
    if resultado is None:
        from compliance_agent.retro_auditoria import avaliar_lift
        resultado = avaliar_lift(db_path)
    if not resultado or not resultado.get("ok"):
        return {"estado": "sem_medicao", "detectores": [],
                "mensagem": (resultado or {}).get("erro")
                or "retro-auditoria ainda não pôde ser calculada nesta base",
                "ressalva": _RESSALVA}

    linhas = []
    for d in resultado.get("detectores") or []:
        classe, leitura = classificar(d.get("lift"), int(d.get("n") or 0),
                                      circular=bool(d.get("circular")))
        linhas.append({**d, "classe": classe, "leitura": leitura})

    # Ordena por utilidade real: quem tem amostra primeiro, depois por lift.
    ordem = {"forte": 0, "util": 1, "neutro": 2, "nao_prediz": 3,
             "amostra_pequena": 4, "circular": 5, "nao_medido": 6}
    linhas.sort(key=lambda d: (ordem.get(d["classe"], 9), -(d.get("lift") or 0)))

    com_amostra = [d for d in linhas if d["classe"] in ("forte", "util", "neutro", "nao_prediz")]
    return {
        "estado": "medido",
        "taxa_base": resultado.get("taxa_base"),
        "universo": resultado.get("universo"),
        "sancionados_universo": resultado.get("sancionados_universo"),
        "n_detectores": len(linhas),
        "n_com_amostra": len(com_amostra),
        "detectores": linhas,
        "alertas": [
            f"{d['detector']}: lift {d['lift']:.2f} — {d['leitura']}"
            for d in linhas if d["classe"] == "nao_prediz"
        ],
        "ressalva": _RESSALVA,
    }


def render_html(painel: dict[str, Any]) -> str:
    if painel.get("estado") != "medido":
        return ('<div class="card lift"><h3>Poder preditivo dos detectores</h3>'
                f'<p class="vazio">{painel.get("mensagem")}</p></div>')
    def _linha(d: dict) -> str:
        lift = "—" if d.get("lift") is None else f"{d['lift']:.2f}"
        return (f'<tr class="{d["classe"]}"><td>{d["detector"]}</td>'
                f'<td class="num">{d["n"]}</td><td class="num">{lift}</td>'
                f'<td>{d["leitura"]}</td></tr>')

    linhas = "".join(_linha(d) for d in painel["detectores"])
    base = painel.get("taxa_base")
    return (
        '<div class="card lift"><h3>Poder preditivo dos detectores</h3>'
        f'<p class="detalhe">taxa base de sanção no universo: '
        f'{(base or 0):.2%} · {painel.get("universo")} empresas · '
        f'{painel["n_com_amostra"]} de {painel["n_detectores"]} detectores com amostra suficiente</p>'
        '<table><thead><tr><th>detector</th><th>n</th><th>lift</th><th>leitura</th></tr></thead>'
        f"<tbody>{linhas}</tbody></table>"
        f'<p class="ressalva">{painel["ressalva"]}</p></div>'
    )


_RESSALVA = (
    "O gabarito é PROXY: 'foi sancionado depois' não é 'cometeu o vício' — muita irregularidade "
    "nunca vira sanção e sanção pode vir por outro motivo. Lift alto NÃO promove grau de "
    "evidência: um detector preditivo produz achado mais valioso, não achado mais provado. "
    "Amostra pequena e detector circular saem separados, nunca ordenados junto."
)
