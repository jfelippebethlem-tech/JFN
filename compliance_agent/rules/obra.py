"""
Regras específicas de auditoria de OBs de obras.

Usa:
- Limite de dispensa Lei 14.133/21 para obras/serviços de engenharia
- Critérios de suspeição por valor, UG e padrão
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable

# Limite legal dispensa licitação (obras/serviços de engenharia) — Lei 14.133/21
LIMITE_DISPENSA_OBRAS = 119_812.02


@dataclass(frozen=True)
class RegraObra:
    id: str
    titulo: str
    descricao: str
    severidade: str


REGRAS_OBRAS: tuple[RegraObra, ...] = (
    RegraObra(
        id="acima_dispensa_sem_contrato",
        titulo="OB de obra acima do limite de dispensa sem amparo contratual/publicação",
        descricao=(
            f"Valor da OB de obra acima de R$ {LIMITE_DISPENSA_OBRAS:,.2f} "
            "sem publicação de contrato no PNCP."
        ),
        severidade="alta",
    ),
    RegraObra(
        id="redondo_exato",
        titulo="Valor exato/redondo em OB de obra",
        descricao=(
            "OB de obra com valor exato ou excessivamente redondo, "
            "indício de estimativa sem cotação real."
        ),
        severidade="média",
    ),
    RegraObra(
        id="concentracao_ug",
        titulo="Concentração elevada de OBs de obras em uma UG",
        descricao=(
            "A mesma UG acumula valores elevados em OBs de obra em janela curta, "
            "o que pode indicar execução orçamentária forçada."
        ),
        severidade="média",
    ),
)


def _valor_redondo(valor: float) -> bool:
    if valor <= 0:
        return False
    return float(round(valor)) == valor


def auditar_obras(obs_por_ug: dict[str, list[dict]], publicadas: dict[str, bool]) -> list[dict]:
    """
    Aplica regras de auditoria específicas para obras.

    Parâmetros:
        obs_por_ug: dict {ug_codigo: [ob_dict, ...]}
        publicadas: dict {cnpj_ou_identificador: bool/None}
                    True se publicado no PNCP, False se não, None se desconhecido

    Retorna:
        lista de alertas prontos para inclusão no relatório.
    """
    alertas: list[dict] = []

    # 1) Obras acima do limite sem publicação
    for ug, items in obs_por_ug.items():
        for ob in items:
            valor = ob.get("valor") or 0.0
            if valor <= LIMITE_DISPENSA_OBRAS:
                continue
            id_publicacao = (
                ob.get("credor") or ob.get("favorecido") or ob.get("numero_processo") or ""
            )
            pub = publicadas.get(id_publicacao)
            if pub is False:
                alertas.append({
                    "regra": REGRAS_OBRAS[0].id,
                    "titulo": REGRAS_OBRAS[0].titulo,
                    "severidade": REGRAS_OBRAS[0].severidade,
                    "ug": ug,
                    "ob": ob.get("numero_ob") or ob.get("id"),
                    "valor": valor,
                    "favorecido": ob.get("favorecido"),
                })

    # 2) Valores redondos
    for ug, items in obs_por_ug.items():
        for ob in items:
            valor = ob.get("valor") or 0.0
            if _valor_redondo(valor):
                alertas.append({
                    "regra": REGRAS_OBRAS[1].id,
                    "titulo": REGRAS_OBRAS[1].titulo,
                    "severidade": REGRAS_OBRAS[1].severidade,
                    "ug": ug,
                    "ob": ob.get("numero_ob") or ob.get("id"),
                    "valor": valor,
                    "favorecido": ob.get("favorecido"),
                })

    # 3) Concentração por UG
    LIMITE_CONCENTRACAO = 1_000_000.0
    for ug, items in obs_por_ug.items():
        total = sum(ob.get("valor") or 0.0 for ob in items)
        if total >= LIMITE_CONCENTRACAO:
            alertas.append({
                "regra": REGRAS_OBRAS[2].id,
                "titulo": REGRAS_OBRAS[2].titulo,
                "severidade": REGRAS_OBRAS[2].severidade,
                "ug": ug,
                "ob": None,
                "valor": total,
                "favorecido": None,
            })

    return alertas
