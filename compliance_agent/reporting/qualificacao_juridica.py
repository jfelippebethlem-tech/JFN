# -*- coding: utf-8 -*-
"""Seção de QUALIFICAÇÃO JURÍDICA do entregável — a ponte do achado até a peça cabível.

POR QUE ESTA SEÇÃO EXISTE. O dossiê termina no achado: "cláusula restritiva", "aditivo acima do
teto". Quem lê precisa da resposta seguinte, que é a que orienta a ação: *qual peça isto sustenta,
e o que ainda falta provar?* Sem ela, o produto empurra a decisão jurídica para o leitor e, pior,
convida ao salto — chamar de improbidade o que a lei vigente não alcança.

O QUE A SEÇÃO ENTREGA, e cada parte responde a uma exigência legal concreta:

  1. **Hipóteses de enquadramento** (`knowledge/tipicidade`) — regime a regime, com o dispositivo,
     o elemento subjetivo e o órgão competente. Improbidade, crime, Lei 12.846, controle externo
     e ressarcimento pedem coisas diferentes; escolher errado é o que mata a peça na inicial.
  2. **O que falta provar** — checklist das lacunas probatórias. É o produto mais útil de todos
     para um mandato: converte "não consigo afirmar" em pedido de diligência com objeto certo.
  3. **Standard probatório** (`knowledge/standard_prova`) — a evidência disponível alcança a
     pretensão? Se não, a peça é rebaixada para aquela que a evidência sustenta.
  4. **Consequências da invalidação** — LINDB art. 21 exige que a decisão que invalida indique
     expressamente suas consequências jurídicas e administrativas. A Lei 14.230/2021 trouxe a
     mesma exigência para dentro da improbidade (art. 17-C, II).
  5. **Obstáculos reais do gestor** — LINDB art. 22 e, de novo, art. 17-C, III da Lei 8.429:
     a interpretação deve considerar os obstáculos e as dificuldades reais do gestor e as
     exigências das políticas públicas a seu cargo. Registrar isso não enfraquece a peça: é
     requisito de validade dela, e é o que a torna difícil de atacar.

HONESTIDADE. A seção qualifica HIPÓTESES. A tipificação é do Ministério Público, do Tribunal de
Contas e do Judiciário — nunca do JFN. Os elementos "não podem ser presumidos" (Lei 8.429, art.
17-C, I), e o texto gerado repete isso onde o leitor vai olhar.
"""
from __future__ import annotations

from typing import Any

from compliance_agent.knowledge.standard_prova import rebaixar_peca, suficiente
from compliance_agent.knowledge.tipicidade import o_que_falta

_LINDB_21 = ("LINDB, art. 21 (Lei 13.655/2018); Lei 8.429/1992, art. 17-C, II "
             "(redação da Lei 14.230/2021)")
_LINDB_22 = ("LINDB, art. 22 (Lei 13.655/2018); Lei 8.429/1992, art. 17-C, III "
             "(redação da Lei 14.230/2021)")

# Consequências típicas por medida — ponto de partida a ser ajustado ao caso concreto. Enunciar
# o efeito prático é exigência do art. 21 da LINDB; enunciá-lo de forma genérica não cumpre a
# exigência, e por isso o texto marca cada item como "a aferir no caso".
_CONSEQUENCIAS: dict[str, tuple[str, ...]] = {
    "anulacao_certame": (
        "interrupção do fornecimento/serviço até novo certame — aferir se há contrato vigente "
        "ou solução de continuidade",
        "custo do refazimento do procedimento e do prazo até nova contratação",
        "efeitos sobre atos já praticados e sobre terceiros de boa-fé",
    ),
    "anulacao_contrato": (
        "necessidade de contratação emergencial, com risco de novo vício",
        "indenização do que foi executado (vedação ao enriquecimento sem causa)",
        "impacto na política pública atendida pelo contrato",
    ),
    "suspensao_cautelar": (
        "paralisação temporária com custo de mobilização/desmobilização",
        "risco de dano reverso se o vício não se confirmar",
    ),
    "glosa_ressarcimento": (
        "recomposição ao erário do valor apurado, com atualização",
        "eventual responsabilização de quem atestou",
    ),
    "determinacao": (
        "correção prospectiva sem interromper a execução — em regra, a medida menos gravosa",
    ),
}

# Obstáculos que a peça deve CONSIDERAR (não é defesa do gestor: é requisito de validade da peça).
_OBSTACULOS_TIPICOS: dict[str, tuple[str, ...]] = {
    "emergencia_fabricada": (
        "descontinuidade de serviço essencial em curso",
        "prazo real de tramitação de um certame ordinário no órgão",
    ),
    "fracionamento_despesa": (
        "estrutura de compras do órgão e existência de ata de registro de preços disponível",
        "sazonalidade e imprevisibilidade da demanda",
    ),
    "prorrogacao_perpetua": (
        "custo de transição de fornecedor em serviço continuado",
        "disponibilidade de mercado local para o objeto",
    ),
    "aditivo_excessivo": (
        "supervenientes reais de obra (geologia, chuva, desapropriação, interferências)",
    ),
    "barreira_habilitacao": (
        "risco de inexecução que a exigência pretendia mitigar",
        "histórico de contratações frustradas no mesmo objeto",
    ),
}
_OBSTACULOS_PADRAO = (
    "restrições de pessoal e de estrutura da unidade de compras",
    "prazos e exigências da política pública atendida pela contratação",
)


def qualificar(vicio: str, *, provas_disponiveis: set[str] | list[str] | None = None,
               grau_evidencia: str | None = None, familias_independentes: int = 1,
               peca_recomendada: str | None = None,
               medida: str | None = None) -> dict[str, Any]:
    """Monta o conteúdo da seção. Puro e testável — não renderiza nada."""
    tip = o_que_falta(vicio, provas_disponiveis)

    standard = None
    if grau_evidencia and peca_recomendada:
        standard = rebaixar_peca(peca_recomendada, grau_evidencia,
                                 familias_independentes=familias_independentes)
    elif grau_evidencia:
        standard = suficiente(grau_evidencia, "representacao",
                              familias_independentes=familias_independentes)

    faltas: list[str] = []
    for r in tip.get("regimes", []):
        for descricao in r["faltam_descrito"]:
            if descricao not in faltas:
                faltas.append(descricao)

    return {
        "vicio": vicio,
        "mapeado": tip["mapeado"],
        "nota": tip.get("nota", ""),
        "regimes": tip.get("regimes", []),
        "algum_fecha": tip.get("algum_fecha", False),
        "o_que_falta": faltas,
        "standard": standard,
        "consequencias": {
            "fundamento": _LINDB_21,
            "medida_considerada": medida or "a definir pelo órgão competente",
            "itens": list(_CONSEQUENCIAS.get(medida or "", ())),
            "aviso": ("A indicação de consequências é obrigatória na decisão que invalida ato, "
                      "contrato ou processo administrativo. Os itens abaixo são o ponto de "
                      "partida: cada um deve ser AFERIDO no caso concreto antes de constar da "
                      "peça — consequência enunciada de forma genérica não cumpre o art. 21."),
        },
        "obstaculos_do_gestor": {
            "fundamento": _LINDB_22,
            "itens": list(_OBSTACULOS_TIPICOS.get(vicio, ())) + list(_OBSTACULOS_PADRAO),
            "aviso": ("Registrar os obstáculos reais não enfraquece a representação: é requisito "
                      "de validade da interpretação e o que a torna difícil de atacar."),
        },
        "ressalva": tip.get("ressalva", ""),
    }


def _li(itens) -> str:
    return "".join(f"<li>{i}</li>" for i in itens)


def render_html(q: dict) -> str:
    """HTML da seção, no formato que `reporting/render_html` consome (`{titulo, html}`)."""
    if not q.get("mapeado"):
        return ("<p><em>Qualificação jurídica não disponível: o vício "
                f"<code>{q.get('vicio')}</code> ainda não está mapeado em "
                "<code>knowledge/tipicidade</code>. Lacuna declarada — a ausência de "
                "enquadramento aqui não significa ausência de enquadramento em direito.</em></p>")

    linhas = []
    for r in q["regimes"]:
        estado = "✔ elementos reunidos" if r["fecha"] else "✖ faltam elementos"
        faltam = ", ".join(r["provas_faltantes"]) or "—"
        linhas.append(
            f"<tr><td>{r['nome']}</td><td>{r['dispositivo']}</td>"
            f"<td>{r['elemento_subjetivo'].replace('_', ' ')}</td>"
            f"<td>{r['orgao_competente']}</td><td>{estado}</td><td>{faltam}</td></tr>")

    partes = [
        "<h3>Hipóteses de enquadramento</h3>",
        "<table><thead><tr><th>Regime</th><th>Dispositivo</th><th>Elemento subjetivo</th>"
        "<th>Órgão competente</th><th>Situação</th><th>Falta provar</th></tr></thead>"
        f"<tbody>{''.join(linhas)}</tbody></table>",
    ]
    if q.get("nota"):
        partes.append(f"<p><strong>Nota de enquadramento:</strong> {q['nota']}</p>")
    if q["o_que_falta"]:
        partes.append("<h3>O que falta para tipificar</h3>"
                      "<p>Cada item abaixo é objeto possível de diligência, requisição de "
                      "informação ou requerimento.</p>"
                      f"<ul>{_li(q['o_que_falta'])}</ul>")
    if q.get("standard"):
        s = q["standard"]
        partes.append(
            "<h3>Standard probatório</h3>"
            f"<p>Exigido: <strong>{s.get('standard_exigido')}</strong> · "
            f"atingido: <strong>{s.get('standard_atingido')}</strong>. {s.get('motivo', '')}</p>"
            + (f"<ul>{_li(s.get('falta', []))}</ul>" if s.get("falta") else ""))

    c = q["consequencias"]
    partes.append(
        f"<h3>Consequências práticas da medida</h3><p><em>{c['fundamento']}</em></p>"
        f"<p>{c['aviso']}</p>"
        + (f"<ul>{_li(c['itens'])}</ul>" if c["itens"]
           else "<p>Medida ainda não definida — as consequências devem ser enunciadas quando ela "
                "o for.</p>"))

    o = q["obstaculos_do_gestor"]
    partes.append(
        f"<h3>Obstáculos e dificuldades reais do gestor</h3><p><em>{o['fundamento']}</em></p>"
        f"<p>{o['aviso']}</p><ul>{_li(o['itens'])}</ul>")

    if q.get("ressalva"):
        partes.append(f"<p class='ressalva'><strong>Ressalva:</strong> {q['ressalva']}</p>")
    return "".join(partes)


def secao(vicio: str, **kw) -> dict:
    """Seção pronta para `render_html(ctx)`: `{titulo, html}`."""
    q = qualificar(vicio, **kw)
    return {"titulo": "Qualificação jurídica e medida cabível", "html": render_html(q),
            "_qualificacao": q}
