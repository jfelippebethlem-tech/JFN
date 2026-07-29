# -*- coding: utf-8 -*-
"""Matriz de achados estilo diligence (H.6) — uma linha por ato, e célula sem fonte é PROIBIDA.

O FORMATO QUE A CASA JÁ DECLARAVA E NÃO TINHA. A skill `analise-clausulas-br` fixa: *"cobertura
tabular estilo diligence: uma linha por cláusula, cada célula com citação (doc SEI/nº da
cláusula) — nunca célula sem fonte"*. Os relatórios entregavam prosa com trechos embutidos; quem
audita precisa da tabela, porque é nela que se vê o que ficou **sem** resposta.

A REGRA QUE DÁ NOME AO MÓDULO. Uma célula vazia num relatório de diligence não é espaço em
branco: é uma afirmação de que ali não há nada. E "não há nada" é diferente de "não olhei". Aqui
toda célula é um dos três estados, sempre explícito:

    aferido ......... há valor E há fonte (documento + localizador)
    nao_consta ...... procurou-se no documento indicado e não há
    nao_observado ... o documento não foi capturado — lacuna de coleta, NUNCA ausência do fato

Um achado cujo campo decisivo é `nao_observado` **não pode** subir de grau: `consolidar` devolve
`grau_limitado_por_cobertura` e diz qual campo travou. É a mesma disciplina de INDISPONÍVEL ≠ 0,
aplicada à célula.

E A CITAÇÃO É CONFERIDA, não declarada: quando o chamador passa o texto-fonte, o trecho é
ancorado por `nucleo/grounding.ancorar`. Trecho que não existe na fonte derruba a célula para
`nao_observado` com o motivo — nunca vira `aferido` por confiança.
"""
from __future__ import annotations

from typing import Any

ESTADOS = ("aferido", "nao_consta", "nao_observado")


class CelulaSemFonte(ValueError):
    """Erro de programação, não de dado: célula aferida sem documento é o que o módulo proíbe."""


def celula(valor: Any = None, *, documento: str = "", localizador: str = "",
           trecho: str = "", fonte_texto: str | None = None,
           motivo: str = "") -> dict[str, Any]:
    """Uma célula da matriz, com o estado explícito e a fonte conferida quando possível.

    `localizador` é folha, cláusula ou item — o que permite reencontrar a informação. Sem
    documento, `valor` é ignorado e a célula vira `nao_observado`: aceitar valor sem fonte é
    exatamente o que a matriz existe para impedir.
    """
    if valor is None or valor == "":
        return {"estado": "nao_consta" if documento else "nao_observado",
                "valor": None, "documento": documento, "localizador": localizador,
                "motivo": motivo or ("procurado no documento indicado e não consta" if documento
                                     else "documento não capturado — lacuna de coleta")}
    if not documento:
        return {"estado": "nao_observado", "valor": None, "documento": "", "localizador": "",
                "motivo": "valor sem documento de origem — não entra na matriz"}

    ancorado = None
    if trecho and fonte_texto is not None:
        from compliance_agent.nucleo.grounding import ancorar
        r = ancorar(trecho, fonte_texto)
        ancorado = bool(r.get("ancorado"))
        if not ancorado:
            return {"estado": "nao_observado", "valor": None, "documento": documento,
                    "localizador": localizador, "trecho": trecho, "ancorado": False,
                    "motivo": ("o trecho citado não foi localizado no documento — citação não "
                               "conferida não sustenta célula aferida")}
    return {"estado": "aferido", "valor": valor, "documento": documento,
            "localizador": localizador, "trecho": trecho, "ancorado": ancorado}


def linha(item: str, campos: dict[str, dict], *, decisivos: tuple[str, ...] = ()) -> dict:
    """Uma linha da matriz (uma cláusula, um ato, um aditivo).

    `decisivos` nomeia os campos sem os quais o achado não se sustenta — é o que permite
    distinguir "faltou um detalhe" de "faltou o que decide".
    """
    faltantes = [k for k in decisivos if (campos.get(k) or {}).get("estado") != "aferido"]
    return {
        "item": item, "campos": campos, "decisivos": list(decisivos),
        "decisivos_faltantes": faltantes,
        "completo": not faltantes,
        "n_aferido": sum(1 for c in campos.values() if c.get("estado") == "aferido"),
        "n_nao_consta": sum(1 for c in campos.values() if c.get("estado") == "nao_consta"),
        "n_nao_observado": sum(1 for c in campos.values() if c.get("estado") == "nao_observado"),
    }


def consolidar(linhas: list[dict], *, grau_pretendido: str | None = None) -> dict[str, Any]:
    """Cobertura da matriz e o efeito dela sobre o grau.

    Achado cujo campo DECISIVO é `nao_observado` não pode sustentar o grau pretendido — e a
    resposta diz qual campo travou, para o pedido de diligência sair certeiro.
    """
    total_celulas = sum(len(l["campos"]) for l in linhas) or 1
    aferidas = sum(l["n_aferido"] for l in linhas)
    nao_obs = sum(l["n_nao_observado"] for l in linhas)
    travadas = [{"item": l["item"], "campos": l["decisivos_faltantes"]}
                for l in linhas if l["decisivos_faltantes"]]

    limitado = bool(travadas)
    return {
        "n_linhas": len(linhas),
        "n_celulas": total_celulas,
        "cobertura": round(aferidas / total_celulas, 4),
        "fracao_nao_observada": round(nao_obs / total_celulas, 4),
        "linhas_completas": sum(1 for l in linhas if l["completo"]),
        "grau_limitado_por_cobertura": limitado,
        "grau_pretendido": grau_pretendido,
        "grau_sustentavel": (None if not grau_pretendido else
                             ("nao_aferivel" if limitado else grau_pretendido)),
        "travado_por": travadas,
        "ressalva": _RESSALVA,
    }


def render_html(linhas: list[dict], *, colunas: tuple[str, ...] | None = None,
                titulo: str = "Matriz de achados") -> str:
    """Tabela com o estado visível em cada célula. Vazio nunca é branco: é `não observado`."""
    cols = colunas or tuple(dict.fromkeys(k for l in linhas for k in l["campos"]))
    cab = "".join(f"<th>{c}</th>" for c in cols)

    def _cel(c: dict | None) -> str:
        c = c or {"estado": "nao_observado", "motivo": "campo ausente da matriz"}
        est = c["estado"]
        if est == "aferido":
            fonte = f'{c.get("documento", "")}'
            if c.get("localizador"):
                fonte += f', {c["localizador"]}'
            return (f'<td class="aferido">{c["valor"]}'
                    f'<span class="fonte">[{fonte}]</span></td>')
        rotulo = "não consta" if est == "nao_consta" else "NÃO OBSERVADO"
        return f'<td class="{est}"><em>{rotulo}</em><span class="motivo">{c.get("motivo","")}</span></td>'

    corpo = "".join(
        f'<tr class="{"completa" if l["completo"] else "incompleta"}">'
        f'<td class="item">{l["item"]}</td>'
        + "".join(_cel(l["campos"].get(c)) for c in cols) + "</tr>"
        for l in linhas)
    return (f'<div class="card matriz"><h3>{titulo}</h3>'
            f'<table><thead><tr><th>item</th>{cab}</tr></thead><tbody>{corpo}</tbody></table>'
            f'<p class="ressalva">{_RESSALVA}</p></div>')


_RESSALVA = (
    "Célula vazia não existe nesta matriz: ou o dado foi AFERIDO com documento e localizador, ou "
    "NÃO CONSTA do documento consultado, ou é NÃO OBSERVADO — lacuna de coleta, que não é "
    "ausência do fato. Achado cujo campo decisivo é não observado não sustenta grau: pede "
    "diligência."
)
