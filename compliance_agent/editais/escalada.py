# -*- coding: utf-8 -*-
"""Escalada codificada — de achado a PEÇA recomendada (escalation-flagger, padrão claude-for-legal).

A régua vivia só em prosa (skill analise-clausulas-br §4-§5); aqui ela RODA: recebe o score da matriz
Severidade × Verossimilhança (produto 1-25, `indice_certame._matriz_sv`) e o contexto do certame, e
devolve a medida típica de controle externo com fundamento e urgência. Determinístico, sem LLM.

Régua (skill §4): 1-4 monitorar · 5-9 diligência · 10-15 diligência prioritária + minuta · 16-25
representação + cautelar. Gatilhos (§5) SOBEM a régua; nunca descem (assimetria intencional: gatilho
é agravante, a ausência dele não é atenuante).

Honesto: recomendação é INSUMO de peça para revisão humana — indício ≠ acusação; quem assina decide.
"""
from __future__ import annotations

# ordem crescente de gravidade — índice = degrau da régua
PECAS = ("monitorar", "diligencia", "diligencia_prioritaria", "representacao", "representacao_cautelar")


def _degrau_por_sv(sv: int) -> int:
    if sv <= 4:
        return 0    # monitorar
    if sv <= 9:
        return 1    # diligência
    if sv <= 15:
        return 2    # diligência prioritária + minuta
    return 3        # representação (cautelar vira degrau 4 pelos gatilhos de urgência)


def recomendar(sv: int, *, certame_aberto: bool = False, sessao_marcada: bool = False,
               vinculo_societario_vencedor: bool = False, agente_publico_qsa: bool = False,
               reincidencia_orgao: int = 0, teste_objetivo_violado: bool = False) -> dict:
    """Recomenda a peça de controle externo para um achado pontuado na matriz S×V.

    Args:
      sv: produto Severidade × Verossimilhança (1-25; fora da faixa é clampado — honesto no motivo).
      certame_aberto: certame ainda não homologado (dano evitável).
      sessao_marcada: sessão de abertura/julgamento futura marcada (urgência real).
      vinculo_societario_vencedor: sinal societário liga a exigência restritiva ao vencedor
        (skill §5: o achado muda de natureza — direcionamento consumado).
      agente_publico_qsa: agente público do órgão no QSA de licitante (conflito de interesses).
      reincidencia_orgao: nº de certames do MESMO órgão com o mesmo padrão (≥3 → auditoria temática).
      teste_objetivo_violado: teste finalístico determinístico confirmou violação de teto legal.

    Returns:
      {peca, urgencia ("rotina"|"prioritaria"|"imediata"), gatilhos (list[str]), fundamento,
       auditoria_tematica (bool), sv}
    """
    sv_c = max(1, min(25, int(sv)))
    degrau = _degrau_por_sv(sv_c)
    gatilhos: list[str] = []
    urgencia = "rotina"

    if teste_objetivo_violado and degrau < 2:
        degrau = 2
        gatilhos.append("teste finalístico VIOLADO (teto legal excedido) — régua sobe para minuta de diligência")
    if vinculo_societario_vencedor:
        degrau = max(degrau, 3)
        gatilhos.append("sinal societário liga a restrição ao vencedor — direcionamento consumado (skill §5)")
    if agente_publico_qsa:
        degrau = max(degrau, 3)
        gatilhos.append("agente público no QSA de licitante — conflito de interesses (Lei 14.133 art. 14 I)")
    if certame_aberto and degrau >= 3:
        degrau = 4
        urgencia = "imediata" if sessao_marcada else "prioritaria"
        gatilhos.append("certame ABERTO com vício grave — cautelar para estancar dano evitável"
                        + (" (sessão marcada)" if sessao_marcada else ""))
    elif sessao_marcada:
        urgencia = "prioritaria"
        gatilhos.append("sessão marcada — prazo real para qualquer medida")
    if degrau == 2 and urgencia == "rotina":
        urgencia = "prioritaria"

    auditoria = reincidencia_orgao >= 3
    if auditoria:
        gatilhos.append(f"mesmo padrão em {reincidencia_orgao} certames do órgão — propor auditoria temática")

    fundamento = {
        0: "S×V ≤ 4 — acompanhar; sem base para movimentar o Tribunal (indício fraco)",
        1: "S×V 5-9 — pedir esclarecimentos/documentos ao órgão (diligência)",
        2: "S×V 10-15 ou teto legal violado — diligência prioritária com minuta pronta",
        3: "S×V 16-25 ou gatilho societário/conflito — representação ao Tribunal de Contas competente",
        4: "vício grave em certame aberto — representação com pedido de medida cautelar (suspensão)",
    }[degrau]

    return {"peca": PECAS[degrau], "urgencia": urgencia, "gatilhos": gatilhos,
            "fundamento": fundamento, "auditoria_tematica": auditoria, "sv": sv_c}
